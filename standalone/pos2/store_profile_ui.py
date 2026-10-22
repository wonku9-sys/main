"""Administrator-managed local supplier identity for commercial papers."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout,QGroupBox,QLineEdit,QLabel,QWidget
from .widgets import Page,action
from .navigation import mark_saved

FIELDS=(('store_name','상호'),('business_no','사업자등록번호'),('representative','대표자명'),('address','주소'),('business_type','업태'),('business_category','종목'),('account','입금하실 계좌'),('phone','연락처'),('store_memo','메모'),('fax','팩스'),('store_email','점포 이메일'),('bank','은행명'),('account_holder','예금주'))


def business_registration(fields,title='사업자 등록정보 (영수증 표기)',extras=False):
    """One certificate layout and the same persisted keys in both settings pages."""
    panel=QGroupBox(title);panel.setObjectName('businessRegistration');panel.setMaximumWidth(1100)
    panel.setStyleSheet('QGroupBox#businessRegistration{background:#E5E7DA;border:1px solid #8F998A;border-radius:2px;margin-top:12px;padding-top:10px;}')
    grid=QGridLayout(panel);grid.setContentsMargins(14,18,14,14);grid.setHorizontalSpacing(12);grid.setVerticalSpacing(9)
    def add(row,column,label,key,span=1):
        if key not in fields:fields[key]=QLineEdit()
        entry=fields[key];entry.setMaxLength(500);entry.setAccessibleName(label)
        caption=QLabel(label);caption.setObjectName('businessLabel_'+key)
        caption.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter);caption.setBuddy(entry)
        grid.addWidget(caption,row,column);grid.addWidget(entry,row,column+1,1,span)
    add(0,0,'상호','store_name',3)
    add(1,0,'사업자등록번호','business_no');add(1,2,'대표자명','representative')
    add(2,0,'주소','address',3)
    for row,left,right in ((3,('업태','business_type'),('종목','business_category')),
                          (4,('입금하실 계좌','account'),('연락처','phone'))):
        add(row,0,*left);add(row,2,*right)
    add(5,0,'메모','store_memo',3)
    fields['account'].setPlaceholderText('계좌번호 또는 은행 · 계좌번호 · 예금주')
    fields['store_memo'].setPlaceholderText('영수증·견적서·거래명세서·주문서에 표기할 매장 안내')
    order=['store_name','business_no','representative','address','business_type','business_category','account','phone','store_memo']
    if extras:
        add(6,0,'팩스','fax');add(6,2,'이메일','store_email')
        add(7,0,'은행명','bank');add(7,2,'예금주','account_holder')
        order+=['fax','store_email','bank','account_holder']
    for first,second in zip(order,order[1:]):QWidget.setTabOrder(fields[first],fields[second])
    for column in (1,3):grid.setColumnStretch(column,1)
    return panel,grid


class StoreProfilePage(Page):
    def __init__(self,window):
        super().__init__(window,'점포 등록정보','환경설정과 같은 점포 자료입니다. 새 견적서·거래명세서·주문서의 공급자로 자동 입력됩니다.')
        self.fields={}
        for key,label in FIELDS:
            field=QLineEdit();field.setMaxLength(500);field.setAccessibleName(label);self.fields[key]=field
        self.registration,self.registration_grid=business_registration(self.fields,extras=True)
        self.body.addWidget(self.registration)
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
