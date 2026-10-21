"""Current-user reauthentication without changing the active POS identity."""
from PySide6.QtCore import QThread,Signal
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QLabel
from .widgets import FormDialog


class RemotePaymentCheck(QThread):
    succeeded=Signal(object);failed=Signal(str)
    def __init__(self,parent,store,password):super().__init__(parent);self.store=store;self.password=password
    def run(self):
        try:self.succeeded.emit(self.store.verify_payment_access(self.password))
        except Exception as exc:self.failed.emit(str(exc))
        finally:self.password=''


class PaymentAccessDialog(FormDialog):
    def __init__(self,window):
        super().__init__('결제관리 · 사용자 확인',window);self.store=window.store;self.worker=None;self.verified=False;self.failure=''
        self._sy_no_home_button=True;self.resize(470,310);self.setMinimumWidth(430)
        self.setStyleSheet('QDialog{background:#F6EFDD;} QLabel#dialogTitle{background:#EABF62;font-size:17px;padding:10px;}')
        name=self.field('name','사용자 이름',self.store.actor['name']);name.setReadOnly(True)
        code=self.field('code','사용자 코드',self.store.actor['code']);code.setReadOnly(True)
        self.password=self.field('password','암호',password=True);self.message=QLabel('현재 로그인 사용자만 재확인합니다.\n다른 계정은 로그아웃 후 로그인하세요.');self.message.setWordWrap(True);self.body.addWidget(self.message)
        self.finish(self.submit);self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('확인')
        self.password.returnPressed.connect(self.submit)
    def submit(self):
        if self.worker and self.worker.isRunning():return
        if not self.password.text():self.message.setText('비밀번호를 입력하세요.');return
        if getattr(self.store,'is_shared_client',False):
            self.worker=RemotePaymentCheck(self,self.store,self.password.text())
            app=QApplication.instance()
            if not hasattr(app,'_sy_catalog_workers'):app._sy_catalog_workers=[]
            app._sy_catalog_workers.append(self.worker)
            self.worker.finished.connect(lambda:app._sy_catalog_workers.remove(self.worker) if self.worker in app._sy_catalog_workers else None)
        else:
            from .background_store import StoreTask
            self.worker=StoreTask(self,self.store,'verify_payment_access',(self.password.text(),))
        self.failure='';self.verified=False;self.password.clear();self.buttons.setEnabled(False)
        self.worker.succeeded.connect(self.succeeded);self.worker.failed.connect(self.failed);self.worker.finished.connect(self.completed);self.worker.start()
    def succeeded(self,result):self.verified=result.get('user_id')==self.store.actor['id']
    def failed(self,error):self.failure=error
    def completed(self):
        self.buttons.setEnabled(True)
        if self.verified:self.accept()
        else:self.message.setText(self.failure or '사용자 확인에 실패했습니다.');self.password.setFocus()
    def reject(self):
        if not self.worker or not self.worker.isRunning():super().reject()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore()
        else:super().closeEvent(event)
