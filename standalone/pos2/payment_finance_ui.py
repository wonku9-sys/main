"""Financial subviews share one date/query/output strip; no dummy actions."""
from datetime import date
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QInputDialog,QSplitter
from .widgets import DataGrid,FormDialog,action,date_field,won
from .workflow_ui import _date,_confirm
from .payment_finance import METHODS
from PySide6.QtGui import QColor


class FinanceGrid(DataGrid):
    def fill(self,rows,records=None):
        self.setSortingEnabled(False);self.horizontalHeader().setSortIndicator(-1,Qt.SortOrder.AscendingOrder)
        super().fill(rows,records);self.setSortingEnabled(False)


class FinancialPane(QWidget):
    def __init__(self,page,headers):
        super().__init__();self.page=page;self.store=page.store
        self.body=QVBoxLayout(self);self.body.setContentsMargins(0,0,0,0)
        self.tools=QHBoxLayout();self.body.addLayout(self.tools)
        self.grid=FinanceGrid(headers);self.grid.menu_key='payments';self.body.addWidget(self.grid,1)
        self.note=QLabel();self.note.setWordWrap(True);self.body.addWidget(self.note)
    def dates(self):return _date(self.page.start),_date(self.page.end)


class BillsPane(FinancialPane):
    def __init__(self,page):
        super().__init__(page,['어음번호','공급사','발행일','만기일','금액','은행','상태','실제 지급일','지급방법','지급 메모'])
        self.scope=QComboBox();self.scope.addItems(['미지급 어음 전체','만기일 기간 조회']);self.tools.addWidget(self.scope);self.scope.currentIndexChanged.connect(self.refresh);self.tools.addStretch()
        self.tools.addWidget(action('어음 지급 기록',self.pay))
        self.note.setText('발행 시 공급사 외상은 어음 부채로 대체됩니다. 만기 지급은 어음만 완료 처리하며 공급사 잔액을 다시 차감하지 않습니다. 실제 송금은 하지 않습니다.')
    def refresh(self):
        first,last=self.dates() if self.scope.currentIndex() else ('0001-01-01','9999-12-31')
        rows=self.store.payable_bills(first,last,self.page.include_voided.isChecked())
        if not self.scope.currentIndex():rows=[r for r in rows if not r['paid_date'] and not r['voided']]
        self.grid.fill([[r['number'],r['partner_name'],r['date'],r['due_date'],r['amount'],r['bank'],r['status'],r['paid_date'],METHODS.get(r['paid_method'],''),r['paid_memo']] for r in rows],rows)
    def pay(self):
        row=self.grid.selected()
        if not row:return self.page.notify('지급할 어음을 선택하세요.')
        form=FormDialog('어음 만기 지급 기록',self);when=date_field();form.form.addRow('실제 지급일',when)
        method=form.combo('method','지급방법',[('현금','cash'),('계좌이체','transfer')]);memo=form.field('memo','메모')
        form.body.addWidget(QLabel(f"{row['number']} · {won(row['amount'])}원\n공급사 잔액은 다시 차감하지 않습니다."))
        def save():
            try:
                if not _confirm(form,'어음 지급 기록','이미 지급한 실제 내역을 기록할까요? 은행 송금은 하지 않습니다.'):return
                self.store.pay_bill(row['id'],_date(when),method.currentData(),memo.text());form.accept()
            except (ValueError,PermissionError) as exc:form.error(exc)
        form.finish(save)
        if form.exec():self.refresh()


class JournalPane(FinancialPane):
    def __init__(self,page):
        super().__init__(page,['코드','처리일','계정과목','구분','금액','결제수단','담당자','상태','메모'])
        self.grid.read_permissions=('reports',)
        self.tools.addWidget(action('업무 수입·비용 등록',self.add));self.tools.addWidget(action('당일 기록 취소',self.void));self.tools.addStretch()
        self.note.setText('매출·매입과 별도의 업무 수입·운영비만 입력하세요. 개인 가계부와 분리되며, 매입대금·어음지급·이미 반영한 할인을 다시 비용/수입으로 입력하면 중복 집계됩니다. 현금 마감표는 기존 판매 시재 기준을 유지합니다.')
    def refresh(self):
        rows=self.store.business_entries(*self.dates())
        self.grid.fill([[r['id'],r['date'],r['account'],'업무 수입' if r['kind']=='income' else '업무 비용',r['amount'],METHODS[r['method']],r['user_name'],'취소' if r['voided'] else '유효',r['memo']] for r in rows],rows)
    def add(self):
        form=FormDialog('간편장부 · 업무 수입/비용',self);when=date_field();form.form.addRow('처리일',when)
        kind=form.combo('kind','구분',[('업무 비용','expense'),('업무 수입','income')]);account=form.field('account','계정과목 *');value=form.field('amount','금액 (원)')
        method=form.combo('method','지급/수금 방법',[(METHODS[k],k) for k in ('cash','transfer','card')]);memo=form.field('memo','메모')
        def save():
            try:
                if not _confirm(form,'업무 장부 등록','매출·매입대금·개인 기록이 아닌 별도 업무 수입/비용을 등록할까요?'):return
                self.store.add_business_entry(_date(when),kind.currentData(),account.text(),value.text(),method.currentData(),memo.text());form.accept()
            except (ValueError,PermissionError) as exc:form.error(exc)
        form.finish(save)
        if form.exec():self.refresh()
    def void(self):
        row=self.grid.selected()
        if not row:return self.page.notify('취소할 업무 기록을 선택하세요.')
        reason,ok=QInputDialog.getText(self,'업무 기록 취소','취소 사유 (당일 기록만 가능)')
        if ok and _confirm(self,'업무 기록 취소','원래 기록을 보존하고 취소 표시할까요?'):
            try:self.store.void_business_entry(row['id'],reason);self.refresh()
            except (ValueError,PermissionError) as exc:self.page.fail(exc)


class ProfitPane(FinancialPane):
    def __init__(self,page):
        super().__init__(page,['대분류','계정과목','선택기간 금액','전년동기 금액','증감'])
        self.tools.addWidget(QLabel('부가세 포함 · 저장된 거래원가 기준'));self.tools.addStretch()
        self.monthly=FinanceGrid(['년월','매출액','판매원가','매출총이익','기타 업무수입','업무비용','참고 순이익'])
        self.monthly.menu_key='payments';self.monthly.read_permissions=('reports',)
        self.grid.read_permissions=('reports',);self.body.insertWidget(2,self.monthly,1)
    def refresh(self):
        report=self.store.finance_profit(*self.dates());a,b=report['current'],report['previous']
        rows=[['매출액','상품매출',a['sale_total'],b['sale_total'],a['sale_total']-b['sale_total']],['매출원가','저장된 판매원가',a['cost'],b['cost'],a['cost']-b['cost']]]
        for label,key in (('매출이익','profit'),('기타 업무수입','other_income'),('업무비용','expenses'),('참고 순이익','net_profit')):rows.append([label,'',a[key],b[key],a[key]-b[key]])
        self.grid.fill(rows);self.monthly.fill([[r['period'],r['sale_total'],r['cost'],r['profit'],r['other_income'],r['expenses'],r['net_profit']] for r in report['monthly']])
        for row in (2,5):
            for c in range(self.grid.columnCount()):self.grid.item(row,c).setBackground(QColor('#DDDDF4'))
        self.note.setText(report['basis']+' 하단은 월별 원가·손익 산정 내역이며, 재고 기초/기말액을 임의로 생성하지 않습니다.')


class MembersPane(FinancialPane):
    def __init__(self,page,mode):
        headers=['코드','회원명','휴대폰','외상잔액','외상한도','최종거래'] if mode=='summary' else ['코드','전표상태','거래일자','외상매출','결제금액','미수잔액','비고']
        super().__init__(page,headers);self.mode=mode;self.member=None
        self.search=QLineEdit();self.search.setPlaceholderText('회원명 · 코드 · 전화번호');self.tools.addWidget(self.search,1)
        self.tools.addWidget(action('검색',self.refresh));self.tools.addWidget(action('결제처리 · 회원 수금',self.collect))
        self.grid.read_permissions=('trade','loyalty');self.grid.menu_key='members'
        self.members=FinanceGrid(['코드','회원명']);self.members.menu_key='members';self.members.setMaximumWidth(250)
        self.members.itemSelectionChanged.connect(self.select)
        if mode!='summary':
            self.body.removeWidget(self.grid);split=QSplitter();split.addWidget(self.members);split.addWidget(self.grid);split.setSizes([230,1000]);self.body.insertWidget(1,split,1)
        self.grid.itemDoubleClicked.connect(self.detail)
        self.search.returnPressed.connect(self.refresh)
        self.note.setText('회원 판매전표와 실제 수금·반품을 조회합니다. 수금은 현금·계좌이체만 지원합니다. 공급사 카드 수기와 혼용하지 않습니다. 검색 목록은 최대 500명씩 표시합니다.')
    def refresh(self):
        self.store.require_menu('members')
        rows=self.store.members(self.search.text().strip())[:500];self.rows=rows
        if self.mode=='summary':
            self.grid.fill([[r['code'],r['name'],r['mobile'],r['credit_balance'],r['registration']['credit_limit'],r['last_trade']] for r in rows],rows)
        else:
            self.members.blockSignals(True);self.members.fill([[r['code'],r['name']] for r in rows],rows)
            selected=next((i for i,r in enumerate(rows) if self.member and r['id']==self.member['id']),0)
            if rows:self.members.selectRow(selected)
            self.members.blockSignals(False);self.select()
    def select(self):
        self.member=self.members.selected()
        if not self.member:self.grid.fill([]);return
        report=self.store.finance_member_ledger(self.member['id'],*self.dates());rows=report['entries']
        if self.mode=='payments':rows=[r for r in rows if r['kind']=='payment']
        values=[['','전기이월','','','',report['opening'],'']] if self.mode!='payments' else []
        records=[{}] if values else []
        for r in rows:values.append([r['number'],{'sale':'매출','sale_return':'반품','payment':'수금'}.get(r['kind'],r['kind']),r['date'],r['charge'],r['payment'],r['balance'],r['memo']]);records.append(r)
        from .payment_workspace import fill_ordered
        fill_ordered(self.grid,values,records)
    def selected(self):return self.grid.selected() if self.mode=='summary' else self.member
    def collect(self):
        member=self.selected()
        if not member:return self.page.notify('수금할 회원을 선택하세요.')
        from .customer_query_ui import MemberPaymentDialog
        try:
            if MemberPaymentDialog(self.store,member,self).exec():self.refresh()
        except (ValueError,PermissionError) as exc:self.page.fail(exc)
    def detail(self,*_):
        if self.mode=='summary':
            member=self.grid.selected()
            if member:
                target=self.page.tabs.widget(6);target.member=member;self.page.tabs.setCurrentIndex(6)
        else:
            row=self.grid.selected()
            if row and row.get('document_id'):
                from .workflow_ui import TradeDialog
                record=self.store.document(row['document_id']);TradeDialog(self.page.window,record['kind'],record).exec();self.refresh()
