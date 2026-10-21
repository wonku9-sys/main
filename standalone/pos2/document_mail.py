"""Explicitly addressed PNG document mail; credentials never cross the LAN."""
from PySide6.QtCore import QBuffer,QIODevice,QThreadPool
from PySide6.QtWidgets import QLabel,QDialogButtonBox
from .email_recovery import EmailDelivery,email_address,masked_address
from .email_ui import MailWorker,MailSettingsDialog
from .commercial_paper import paper_document,paper_images
from .widgets import FormDialog,action


def prepare_document_mail(store,record,title,recipient):
    recipient=email_address(recipient)
    from .offline_menus import FORM_VIEWS
    store.require_menu(next(key for key,(_,kind) in FORM_VIEWS.items() if kind==record['kind']))
    local=store.private if getattr(store,'is_shared_client',False) else store
    local._require()
    row=local.db.execute('SELECT config FROM email_smtp WHERE id=1').fetchone()
    if not row:raise ValueError('이 PC의 관리자에게 이메일 발송 설정(SMTP)을 요청하세요. 수신 주소 입력만으로 발송되지 않습니다.')
    images=paper_images(paper_document(record,title));attachments=[];size=0
    for index,image in enumerate(images,1):
        buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer,'PNG'):raise ValueError('문서 이미지 변환에 실패했습니다.')
        payload=bytes(buffer.data());size+=len(payload)
        if size>15*1024*1024 or index>20:raise ValueError('이메일 첨부는 20쪽·15MB까지입니다. 문서를 나누거나 이미지 파일로 저장하세요.')
        attachments.append((f"SY-POS-{record['number']}-{index:02d}.png",payload))
    return EmailDelivery('commercial-paper',masked_address(recipient),'',bytes(row[0]),recipient,f"{title} {record['number']}을 첨부합니다.\n작성일: {record['date']}\n공급자: {record['seller'].get('store_name','')}\n첨부 이미지를 확인해 주세요.",f"[SY POS] {title} {record['number']}",tuple(attachments))


class DocumentMailDialog(FormDialog):
    def __init__(self,store,record,title,parent=None):
        super().__init__('문서 이미지 이메일 전송',parent);self.store,self.record,self.title=store,record,title;self.sending=False
        self.recipient=self.field('recipient','받는 이메일 주소');self.recipient.setPlaceholderText('문서를 받을 이메일 주소를 직접 확인하세요')
        self.body.addWidget(QLabel('현재 선택한 문서를 PNG 이미지로 변환해 첨부합니다.\n발송 계정·보안 SMTP 설정과 인터넷 연결이 필요합니다.'))
        self.status=QLabel();self.status.setWordWrap(True);self.body.addWidget(self.status)
        if store.actor.get('role')=='admin' or store.actor.get('host_admin'):
            self.body.addWidget(action('이 PC 이메일 발송 설정',lambda:MailSettingsDialog(store.private if getattr(store,'is_shared_client',False) else store,self).exec()))
        self.finish(self.send);self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('주소 확인 후 전송')
    def send(self):
        if self.sending:return
        try:job=prepare_document_mail(self.store,self.record,self.title,self.recipient.text())
        except (ValueError,PermissionError,OSError) as exc:self.error(exc);return
        self.sending=True;self.recipient.setEnabled(False);self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.status.setText('이미지 문서를 발송 중입니다…');self.worker=MailWorker(job);self.worker.signals.finished.connect(self.sent);QThreadPool.globalInstance().start(self.worker)
    def sent(self,success,message):
        self.sending=False;self.recipient.setEnabled(True);self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        self.status.setText('메일 서버가 발송을 접수했습니다. 수신함·스팸함을 확인하세요.' if success else message.replace('기존 암호는 변경되지 않았습니다.',''))
    def reject(self):
        if self.sending:self.status.setText('발송 결과를 확인한 뒤 닫아 주세요.');return
        super().reject()
