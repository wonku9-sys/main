"""One MIS month-close window, with retained history and carry details."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QHBoxLayout,QLabel,QVBoxLayout,QWidget
from .payment_closing import payment_close_target
from .widgets import DataGrid,action,won,reference_grid


class PaymentMonthCloseDialog(QDialog):
    menu_key='payments'
    read_permissions=('trade',)

    def __init__(self,window,parent=None):
        super().__init__(parent or window);self.window,self.store=window,window.store
        self._sy_no_home_button=True;self.snapshot=None;self.changed=False;self._saving=False
        self.setWindowTitle('MIS · 월마감처리');self.resize(820,670);self.setMinimumSize(650,500)
        body=QVBoxLayout(self)
        self.note=QLabel();self.note.setWordWrap(True);body.addWidget(self.note)
        bar=QHBoxLayout();bar.addWidget(action('6개월 이전',lambda:self.move(-6)));bar.addWidget(action('6개월 이후',lambda:self.move(6)))
        bar.addStretch();bar.addWidget(action('다시 조회',self.refresh));body.addLayout(bar)
        self.anchor=date.today().year*12+date.today().month-1
        self.grid=DataGrid(['실행 월','마감 월','외상매입','외상매출','처리자','실행일시']);reference_grid(self.grid)
        body.addWidget(self.grid,1)
        self.carries=DataGrid(['구분','코드','거래처/회원','이월 잔액']);reference_grid(self.carries);body.addWidget(self.carries,1)
        self.grid.itemSelectionChanged.connect(self.detail)
        self.message=QLabel('기존 원장 잔액을 이월 기준으로 보관합니다. 추가 채무·입출금 전표를 만들지 않습니다. 재고마감과 별도입니다.')
        self.message.setWordWrap(True);body.addWidget(self.message)
        self._sy_pinned_footer=QWidget();footer=QHBoxLayout(self._sy_pinned_footer);footer.setContentsMargins(0,0,0,0)
        footer.addStretch();self.run_button=action('월마감 실행',self.run,True);footer.addWidget(self.run_button);body.addWidget(self._sy_pinned_footer)
        self.refresh()

    def refresh(self):
        try:
            self.snapshot=self.store.payment_close_context();data=self.snapshot
            self.note.setText(f"MIS 월마감처리 · {data['run_month']}\n이번 마감: {data['through_date']}까지 · 최근 6개 완료 월은 열어 둡니다. 마감 후 해당 기간의 거래·결제는 작성/수정/취소할 수 없습니다.")
            admin=self.store.actor['role']=='admin' or self.store.actor.get('host_admin',False)
            self.render();self.run_button.setEnabled(data['can_close'] and admin and not self._saving)
            if not admin:self.message.setText('MIS 월마감 실행은 관리자 권한이 필요합니다. 이력과 이월 잔액은 조회할 수 있습니다.')
            elif not data['can_close']:self.message.setText('이번 달 월마감을 이미 실행했습니다. 월 1회로 제한됩니다. 이월 잔액은 아래에서 확인하세요.')
        except (ValueError,PermissionError,ConnectionError) as exc:
            self.snapshot=None;self.grid.fill([]);self.carries.fill([]);self.run_button.setEnabled(False);self.message.setText(str(exc))

    def render(self):
        history={r['run_month']:r for r in self.snapshot['history']};rows=[];records=[]
        for n in range(self.anchor-5,self.anchor+1):
            year,month=divmod(n,12);stamp=f'{year:04d}-{month+1:02d}';row=history.get(stamp)
            target=payment_close_target(date(year,month+1,1));state='실행완료' if row else '미실행' if stamp<=self.snapshot['run_month'] else '예정'
            rows.append([stamp,target[:7],state,state,row['user_name'] if row else '',row['created_at'] if row else '']);records.append(row or {})
        self.grid.setSortingEnabled(False);self.grid.fill(rows,records);self.grid.setSortingEnabled(False)
        for i,r in enumerate(records):
            if r.get('run_month')==self.snapshot['run_month']:self.grid.selectRow(i);break

    def move(self,months):
        if not self.snapshot:return
        target=self.anchor+months
        if not 12<=target<9999*12:return
        self.anchor=target;self.render()

    def detail(self):
        row=self.grid.selected() or {}
        try:
            values=self.store.payment_close_detail(row['id'])['rows'] if row else []
            self.carries.fill([[{'supplier':'공급사','customer':'판매처','member':'회원'}[r['type']],r['code'],r['name'],r['balance']] for r in values],values)
        except (ValueError,PermissionError,ConnectionError) as exc:self.carries.fill([]);self.message.setText(str(exc))

    def run(self):
        if not self.snapshot or not self.snapshot['can_close'] or self._saving:return
        from .workflow_ui import _confirm
        if not _confirm(self,'MIS 결제 월마감',f"{self.snapshot['through_date']}까지 월마감할까요?\n해당 기간의 거래·결제 작성/수정/취소가 차단됩니다. 원장과 이력은 보존되며 월마감을 취소하는 기능은 없습니다."):return
        self._saving=True;self.run_button.setEnabled(False)
        try:
            self.store.close_payment_month(self.snapshot['state']);self.changed=True;self.refresh()
        except (ValueError,PermissionError,ConnectionError) as exc:self.message.setText(str(exc))
        finally:self._saving=False
