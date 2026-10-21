"""Administrator-managed local supplier identity for commercial papers."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout,QGroupBox,QLineEdit,QLabel
from .widgets import Page,action
from .navigation import mark_saved

FIELDS=(('store_name','상호 · 점포명'),('business_no','사업자등록번호'),('representative','대표자'),('business_type','업태'),('business_category','종목'),('phone','전화번호'),('fax','팩스'),('address','주소'),('store_email','점포 이메일'),('bank','은행명'),('account','계좌번호'),('account_holder','예금주'))


class StoreProfilePage(Page):
    def __init__(self,window):
        super().__init__(window,'점포 등록정보','환경설정과 같은 점포 자료입니다. 새 견적서·거래명세서·주문서의 공급자로 자동 입력됩니다.')
        self.fields={}
        for key,label in FIELDS:
            field=QLineEdit();field.setMaxLength(500);field.setAccessibleName(label);self.fields[key]=field
        self.registration=QGroupBox('사업자 등록 정보 (영수증 표기)');self.registration.setObjectName('businessRegistration')
        self.registration.setMaximumWidth(1100)
        self.registration.setStyleSheet('QGroupBox#businessRegistration{background:#E5E7DA;border:1px solid #8F998A;border-radius:2px;margin-top:12px;padding-top:10px;}')
        self.registration_grid=QGridLayout(self.registration);self.registration_grid.setContentsMargins(14,18,14,14)
        self.registration_grid.setHorizontalSpacing(12);self.registration_grid.setVerticalSpacing(9)
        def field(grid,row,column,label,key,span=1):
            caption=QLabel(label);caption.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
            caption.setBuddy(self.fields[key]);grid.addWidget(caption,row,column)
            grid.addWidget(self.fields[key],row,column+1,1,span)
        for row,left,right in ((0,('상호(영수증용)','store_name'),('업태','business_type')),
                              (1,('사업자등록번호','business_no'),('종목','business_category')),
                              (2,('대표자명','representative'),('전화번호','phone'))):
            field(self.registration_grid,row,0,*left);field(self.registration_grid,row,2,*right)
        field(self.registration_grid,3,0,'주소','address',3)
        field(self.registration_grid,4,0,'팩스','fax');field(self.registration_grid,4,2,'이메일','store_email')
        for column in (1,3):self.registration_grid.setColumnStretch(column,1)
        self.body.addWidget(self.registration)
        self.payment=QGroupBox('입금 계좌 (선택 입력)');self.payment.setMaximumWidth(1100)
        payment_grid=QGridLayout(self.payment);payment_grid.setContentsMargins(14,18,14,14);payment_grid.setHorizontalSpacing(12)
        field(payment_grid,0,0,'은행명','bank');field(payment_grid,0,2,'예금주','account_holder')
        field(payment_grid,1,0,'계좌번호','account',3)
        for column in (1,3):payment_grid.setColumnStretch(column,1)
        self.body.addWidget(self.payment)
        # Keep natural keyboard order despite the two-column certificate layout.
        order=('store_name','business_type','business_no','business_category','representative','phone','address','fax','store_email','bank','account_holder','account')
        for first,second in zip(order,order[1:]):self.setTabOrder(self.fields[first],self.fields[second])
        note=QLabel('저장한 문서는 작성 당시 점포 정보를 보존합니다. 점포 정보를 바꿔도 기존 발행 문서가 임의로 바뀌지 않습니다.');note.setWordWrap(True);self.body.addWidget(note)
        self.actions.addWidget(action('적용 · 저장',self.save,primary=True));self.body.addStretch()
    def refresh(self):
        values=self.store.store_profile()
        for key,field in self.fields.items():field.setText(values[key])
    def save(self):
        try:
            self.store.save_settings({key:field.text() for key,field in self.fields.items()})
            if getattr(self.window,'current_page',None) is self:self.window._sync_menu_context('store_profile',self,record=False)
            mark_saved(self);self.notify('점포 정보를 저장했습니다. 새 문서의 공급자 정보에 적용됩니다.');return True
        except (ValueError,PermissionError) as exc:self.fail(exc);return False
