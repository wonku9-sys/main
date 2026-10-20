"""Administrator-managed local supplier identity for commercial papers."""
from PySide6.QtWidgets import QFormLayout,QGroupBox,QLineEdit,QLabel
from .widgets import Page,action
from .navigation import mark_saved

FIELDS=(('store_name','상호 · 점포명'),('business_no','사업자등록번호'),('representative','대표자'),('business_type','업태'),('business_category','종목'),('phone','전화번호'),('fax','팩스'),('address','주소'),('store_email','점포 이메일'),('bank','은행명'),('account','계좌번호'),('account_holder','예금주'))


class StoreProfilePage(Page):
    def __init__(self,window):
        super().__init__(window,'점포 등록정보','환경설정과 같은 점포 자료입니다. 새 견적서·거래명세서·주문서의 공급자로 자동 입력됩니다.')
        self.fields={};group=QGroupBox('🏪 사업자 · 연락처 · 입금 계좌');form=QFormLayout(group)
        for key,label in FIELDS:
            field=QLineEdit();field.setMaxLength(500);self.fields[key]=field;form.addRow(label,field)
        self.body.addWidget(group)
        note=QLabel('저장한 문서는 작성 당시 점포 정보를 보존합니다. 점포 정보를 바꿔도 기존 발행 문서가 임의로 바뀌지 않습니다.');note.setWordWrap(True);self.body.addWidget(note)
        self.actions.addWidget(action('적용 · 저장',self.save,primary=True));self.body.addStretch()
    def refresh(self):
        values=self.store.store_profile()
        for key,field in self.fields.items():field.setText(values[key])
    def save(self):
        try:
            self.store.save_settings({key:field.text() for key,field in self.fields.items()})
            mark_saved(self);self.notify('점포 정보를 저장했습니다. 새 문서의 공급자 정보에 적용됩니다.');return True
        except (ValueError,PermissionError) as exc:self.fail(exc);return False
