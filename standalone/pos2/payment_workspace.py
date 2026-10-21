"""PDF 146–153 flow in one stable workspace: supplier → ledger → payment."""
from collections import defaultdict
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtGui import QAction,QColor,QKeySequence,QShortcut
from PySide6.QtWidgets import QCheckBox,QComboBox,QHBoxLayout,QLabel,QLineEdit,QSplitter,QToolBar,QVBoxLayout,QWidget,QPushButton
from .widgets import DataGrid,won
from .menu_icons import menu_icon
from .workflow_ui import KINDS,_date

SUMMARY_HEADERS=['코드','공급사명','거래','사업자번호','전기이월','매입금액','반품금액','결제[현금]','결제[이체]','결제[카드 수기]','순지급','기간말 잔액','현재 잔액','최종매입일','최종결제일']
HISTORY_HEADERS=['코드','공급사','결제일','현금결제','계좌이체','카드 수기','지급합계','담당자','상태','메모','결제번호']


def setup(page):
    page._payment_workspace=True;page._payment_revision=None
    # Reuse the actual existing controls and grids; remove their duplicate
    # placements, not the underlying payment/void/export functionality.
    def hide_item(item):
        if item.widget():item.widget().hide()
        elif item.layout():
            while item.layout().count():hide_item(item.layout().takeAt(0))
    while page.body.count()>1:hide_item(page.body.takeAt(1))
    for button in page.header.findChildren(QPushButton):
        if button.text()=='결제 처리':page.actions.removeWidget(button);button.hide();button.deleteLater()
    page.body.setContentsMargins(6,6,6,6);page.body.setSpacing(5)
    toolbar=QToolBar();toolbar.setMovable(False);toolbar.setIconSize(QSize(34,34));toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    toolbar.setStyleSheet('QToolBar{background:#CFDADC;border-bottom:1px solid #8FADB2;padding:3px;} QToolButton{background:transparent;border:0;border-radius:0;padding:4px 9px;} QToolButton:hover{background:#B8CFD2;}')
    page.payment_toolbar=toolbar
    page.payment_views=[]
    for label,tab in (('외상매입',0),('공급사별',1),('매입결제',2),('매입 상세내역',3)):
        tool=QAction(menu_icon(label),label,toolbar);tool.setCheckable(True);tool.setToolTip(label+' 화면으로 이동합니다. 상세내역은 공급사 거래 전표를 더블클릭하세요.');tool.triggered.connect(lambda checked=False,index=tab:page.tabs.setCurrentIndex(index));toolbar.addAction(tool);page.payment_views.append(tool)
    page.payment_views[0].setChecked(True)
    page.tabs.tabBar().hide()
    page.tabs.currentChanged.connect(lambda index:[tool.setChecked(i==index) for i,tool in enumerate(page.payment_views)])
    toolbar.addSeparator()
    for label,callback in (('결제처리',page.pay),('카드 수기결제',lambda:page.pay('card')),('당일 결제 정정',page.edit_payment),('선택 결제 취소',page.void)):
        tool=QAction(menu_icon(label),label,toolbar);tool.setToolTip(label+' · 실제 송금·카드 승인 통신은 하지 않습니다.');tool.triggered.connect(callback);toolbar.addAction(tool)
        if label=='선택 결제 취소':page.payment_void_action=tool
        if label=='당일 결제 정정':page.payment_edit_action=tool
    page.body.addWidget(toolbar)
    splitter=QSplitter(Qt.Orientation.Horizontal);left=QWidget();side=QVBoxLayout(left);side.setContentsMargins(0,0,4,0);side.setSpacing(5)
    page.search.setPlaceholderText('공급사명 · 코드 검색');side.addWidget(page.search)
    page.include_inactive=QCheckBox('무효 공급사 포함');side.addWidget(page.include_inactive)
    page.supplier_list=DataGrid(['코드','공급사명']);page.supplier_list.setColumnWidth(0,60);page.supplier_list.setColumnWidth(1,190);side.addWidget(page.supplier_list,1);splitter.addWidget(left)
    right=QWidget();main=QVBoxLayout(right);main.setContentsMargins(0,0,0,0);main.setSpacing(5)
    dates=QHBoxLayout();dates.addWidget(QLabel('기간'));dates.addWidget(page.start);dates.addWidget(QLabel('~'));dates.addWidget(page.end)
    page.settlement_filter=QComboBox();page.settlement_filter.addItem('결제유형 전체',None);dates.addWidget(page.settlement_filter)
    page.day_filter=QComboBox();page.day_filter.addItem('결제일 전체',None)
    for value in range(1,32):page.day_filter.addItem(str(value)+'일',value)
    dates.addWidget(page.day_filter);dates.addWidget(page.only_purchases);dates.addWidget(page.include_voided);dates.addStretch();main.addLayout(dates)
    selection=QHBoxLayout();selection.addWidget(QLabel('공급사'));page.selected_supplier_name=QLineEdit('전체공급사');page.selected_supplier_name.setReadOnly(True);selection.addWidget(page.selected_supplier_name,1)
    page.all_suppliers=QCheckBox('전체공급사');page.all_suppliers.setChecked(True);selection.addWidget(page.all_suppliers)
    page.ledger_mode=QComboBox();page.ledger_mode.addItems(['전표별','일자별']);selection.addWidget(page.ledger_mode)
    page.method_filter=QComboBox()
    for title,key in (('결제방법 전체',''),('현금','cash'),('계좌이체','transfer'),('카드 수기','card')):page.method_filter.addItem(title,key)
    selection.addWidget(page.method_filter);main.addLayout(selection)
    page.grid.setColumnCount(len(SUMMARY_HEADERS));page.grid.setHorizontalHeaderLabels(SUMMARY_HEADERS)
    page.history_grid.setColumnCount(len(HISTORY_HEADERS));page.history_grid.setHorizontalHeaderLabels(HISTORY_HEADERS)
    page.tabs.setTabText(0,'외상매입현황');page.tabs.setTabText(1,'공급사별 거래내역');page.tabs.setTabText(2,'매입결제현황')
    page.purchase_detail_grid=DataGrid(['상품명','규격','바코드','수량','입력단위','단가','단가 기준','매입금액','과면세'])
    page.tabs.addTab(page.purchase_detail_grid,'매입 상세내역')
    main.addWidget(page.tabs,1);page.tabs.show()
    bank=QHBoxLayout();page.bank_fields={}
    for key,title in (('bank','은행'),('account_holder','예금주'),('account','계좌')):
        bank.addWidget(QLabel(title));field=QLineEdit();field.setReadOnly(True);bank.addWidget(field,2 if key=='account' else 1);page.bank_fields[key]=field
    main.addLayout(bank);page.summary.show();main.addWidget(page.summary)
    splitter.addWidget(right);splitter.setSizes([240,1100]);page.body.addWidget(splitter,1)
    for grid in (page.grid,page.ledger_grid,page.history_grid,page.supplier_list,page.purchase_detail_grid):
        grid.setStyleSheet('QTableWidget{background:#A6ABAB;gridline-color:#BEC6C5;} QHeaderView::section{background:#C8DEE0;color:#263F47;border:1px solid #9AAFB3;} QTableWidget::item:selected{background:#176CB0;color:white;}')
    page._supplier_pick=False
    page.supplier_list.itemSelectionChanged.connect(lambda:select_supplier(page))
    page.all_suppliers.toggled.connect(lambda enabled:set_all(page,enabled))
    for control in (page.include_inactive,):control.toggled.connect(page.refresh)
    for control in (page.settlement_filter,page.day_filter,page.ledger_mode,page.method_filter):control.currentIndexChanged.connect(page.refresh)
    page._payment_search_timer=QTimer(page);page._payment_search_timer.setSingleShot(True);page._payment_search_timer.setInterval(250);page._payment_search_timer.timeout.connect(page.refresh)
    page.search.textChanged.disconnect();page.search.textChanged.connect(lambda:page._payment_search_timer.start());page.search.returnPressed.connect(page.refresh)
    page.tabs.currentChanged.connect(lambda index:page.payment_void_action.setEnabled(index==2))
    page.tabs.currentChanged.connect(lambda index:page.payment_edit_action.setEnabled(index==2))
    page.payment_void_action.setEnabled(False)
    page.payment_edit_action.setEnabled(False)
    page._detail_shortcut=QShortcut(QKeySequence('F6'),page);page._detail_shortcut.activated.connect(page.detail)
    for control in (page.start,page.end,page.search,page.only_purchases,page.include_voided,page.tabs):control.show()


def set_all(page,enabled):
    if enabled:
        page.partner.setCurrentIndex(0);page.selected_supplier_name.setText('전체공급사')
    page.refresh()


def select_supplier(page):
    if page._supplier_pick:return
    selected=page.supplier_list.selected()
    if not selected:return
    page.all_suppliers.blockSignals(True);page.all_suppliers.setChecked(False);page.all_suppliers.blockSignals(False)
    page.partner.setCurrentIndex(page.partner.findData(selected['id']));page.selected_supplier_name.setText(selected['name'])
    for key,field in page.bank_fields.items():field.setText(selected.get(key,''))


def refresh(page):
    page.store.require_menu('payments');page._payment_search_timer.stop()
    first,last,party=_date(page.start),_date(page.end),page.partner.currentData()
    revision=page.store.audit_revision()
    if revision!=page._payment_revision:
        page._payment_metadata=page.store.payment_filters();page._payment_revision=revision
        data=page._payment_metadata;current=page.settlement_filter.currentData()
        page.settlement_filter.blockSignals(True)
        while page.settlement_filter.count()>1:page.settlement_filter.removeItem(1)
        for row in data['groups']:page.settlement_filter.addItem(row['name'],row['id'])
        page.settlement_filter.setCurrentIndex(max(0,page.settlement_filter.findData(current)));page.settlement_filter.blockSignals(False)
    data=page._payment_metadata;term=page.search.text().strip().casefold()
    suppliers=[r for r in data['suppliers'] if (page.include_inactive.isChecked() or r['active']) and term in (r['code']+' '+r['name']).casefold()]
    page._supplier_pick=True;page.supplier_list.fill([[r['code'],r['name']] for r in suppliers],suppliers);page._supplier_pick=False
    rows=page.store.supplier_summary(first,last,page.search.text().strip(),page.only_purchases.isChecked(),party)
    if not page.include_inactive.isChecked():rows=[r for r in rows if r['active']]
    if page.day_filter.currentData() is not None:rows=[r for r in rows if r['settlement_day']==page.day_filter.currentData()]
    if page.settlement_filter.currentData() is not None:
        allowed={m['partner_id'] for m in data['memberships'] if m['group_id']==page.settlement_filter.currentData()};rows=[r for r in rows if r['id'] in allowed]
    page.grid.fill([[r['code'],r['name'],'직매입' if r['supplier_mode']=='direct' else '수수료',r['business_no'],r['opening'],r['purchase'],r['returns'],r['cash_payment'],r['transfer_payment'],r['card_payment'],r['payment'],r['closing'],r['balance'],r['last_purchase'] or '',r['last_payment'] or ''] for r in rows],rows)
    for r in range(page.grid.rowCount()):
        for c,color in ((4,'#DBEFDD'),(5,'#EDD0D2'),(7,'#DDE1DE'),(8,'#E0E6F0'),(9,'#E5D8E8'),(11,'#F5F0BB'),(12,'#F5F0BB')):page.grid.item(r,c).setBackground(QColor(color))
    page.summary.setText(f"Σ 공급사 {len(rows):,}개 · 매입 {won(sum(r['purchase'] for r in rows))} − 반품 {won(sum(r['returns'] for r in rows))} · 순지급 {won(sum(r['payment'] for r in rows))} · 기간말 잔액 {won(sum(r['closing'] for r in rows))} · 현재 잔액 {won(sum(r['balance'] for r in rows))}원\n음수는 환급·상계 대상입니다. 카드 수기는 지급 기록만 반영하며 카드 승인·은행 송금은 하지 않습니다.")
    ledger=page.store.ledger(party,first,last)['entries'] if party else []
    if page.ledger_mode.currentIndex()==1:
        groups=defaultdict(list)
        for r in ledger:groups[r['date']].append(r)
        ledger=[dict(date=key,kind='day',number='일자 합계',charge=sum(r['charge'] for r in values),payment=sum(r['payment'] for r in values),balance=values[-1]['balance'],memo='') for key,values in groups.items()]
    page.ledger_grid.fill([[r['date'],KINDS.get(r['kind'],{'opening':'초기 외상','payment':'지급','refund':'환급','day':'일자 합계'}.get(r['kind'],r['kind'])),r['number'],r['charge'],r['payment'],r['balance'],r['memo']] for r in ledger],ledger)
    history=page.store.supplier_payment_history(first,last,party,page.include_voided.isChecked())
    history=[r for r in history if term in (r['partner_code']+' '+r['partner_name']).casefold() and (not page.method_filter.currentData() or r['method']==page.method_filter.currentData())]
    page.history_grid.fill([[r['partner_code'],r['partner_name'],r['date'],r['amount'] if r['method']=='cash' else 0,r['amount'] if r['method']=='transfer' else 0,r['amount'] if r['method']=='card' else 0,r['amount'],r['user_name'],'취소' if r['voided'] else '유효',r['memo'],r['number']] for r in history],history)
