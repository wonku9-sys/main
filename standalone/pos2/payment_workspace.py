"""PDF 146–153 flow in one stable workspace: supplier → ledger → payment."""
from collections import defaultdict
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtGui import QAction,QColor,QKeySequence,QShortcut
from PySide6.QtWidgets import QCheckBox,QComboBox,QHBoxLayout,QLabel,QLineEdit,QSplitter,QToolBar,QVBoxLayout,QWidget,QPushButton,QMenuBar
from .widgets import DataGrid,won
from .menu_icons import menu_icon
from .workflow_ui import KINDS,_date

SUMMARY_HEADERS=['코드','공급사명','거래','사업자번호','전기이월','매입금액','반품금액','결제[지급]','결제[할인]','기간말 잔액','현재 잔액','최종매입','최종결제','상품재고액(현재)']
HISTORY_HEADERS=['코드','공급사','결제일','현금결제','계좌이체','카드 수기','어음','할인','결제합계','담당자','상태','메모','결제번호']
VIEWS=[('외상매입',0,'payables'),('공급사별',1,'supplier'),('매입결제',2,'purchase_payment'),('어음관리',4,'bill'),
       ('외상매출',5,'receivables'),('회원별',6,'member'),('매출결제',7,'sales_payment'),('계정원장',8,'ledger'),('손익계산',9,'profit')]
VIEW_CODES={0:'1-01',1:'1-02',2:'1-11',3:'1-03',4:'1-21',5:'2-01',6:'2-02',7:'2-11',8:'3-01',9:'3-11'}


def view_caption(page,index=None):
    index=page.tabs.currentIndex() if index is None else index
    return VIEW_CODES[index]+'.'+page.tabs.tabText(index)


def fill_ordered(grid,values,records):
    # Ledger balances and the final total belong in their source order, never
    # Qt's remembered column sort (which can put the total before suppliers).
    grid.setSortingEnabled(False);grid.horizontalHeader().setSortIndicator(-1,Qt.SortOrder.AscendingOrder)
    grid.fill(values,records);grid.setSortingEnabled(False)


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
    page.payment_chrome=QWidget();chrome=QVBoxLayout(page.payment_chrome);chrome.setContentsMargins(0,0,0,0);chrome.setSpacing(0)
    page.payment_menubar=QMenuBar();chrome.addWidget(page.payment_menubar)
    toolbar=QToolBar();toolbar.setMovable(False);toolbar.setIconSize(QSize(38,38));toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    toolbar.setStyleSheet('QToolBar{background:palette(window);border-bottom:1px solid #9BB0B4;padding:2px;} QToolButton{background:transparent;border:0;border-radius:2px;padding:3px 7px;} QToolButton:hover{background:#D5E8EF;} QToolButton:checked{background:#CCE1EC;} QToolBar::separator{background:#9AAFB3;width:1px;margin:7px 5px;}')
    page.payment_toolbar=toolbar
    from .menu_icons import payment_icon
    for name,kind in (('outputPrintIcon','printer'),('outputSaveIcon','excel')):
        button=page.header.findChild(QPushButton,name)
        if button:button.setIcon(payment_icon(kind))
    page.payment_history=[0];page.payment_history_index=0;page._payment_replaying=False
    page.payment_back=toolbar.addAction(payment_icon('back'),'이전',lambda:travel(page,-1))
    page.payment_forward=toolbar.addAction(payment_icon('forward'),'다음',lambda:travel(page,1));toolbar.addSeparator()
    page.payment_views={}
    for label,tab,icon in VIEWS:
        if tab in {5,8}:toolbar.addSeparator()
        tool=QAction(payment_icon(icon),label,toolbar);tool.setCheckable(True);tool.setToolTip(label+' 화면으로 이동합니다.');tool.triggered.connect(lambda checked=False,index=tab:page.tabs.setCurrentIndex(index));toolbar.addAction(tool);page.payment_views[tab]=tool
        from .permissions import has_menu
        if tab in {5,6,7} and not has_menu(page.store.actor,'members'):tool.setEnabled(False);tool.setToolTip('회원 조회 권한이 필요합니다.')
        if tab in {8,9} and not has_menu(page.store.actor,'reports'):tool.setEnabled(False);tool.setToolTip('보고서 권한이 필요합니다.')
    page.payment_views[0].setChecked(True)
    page.tabs.tabBar().hide()
    toolbar.addSeparator()
    for label,icon,callback,enabled in (('DB연결','connection',getattr(page.window,'configure_network',None),bool(getattr(page.window,'network_path',None))),('업데이트','update',None,False),('원격지원','remote',None,False)):
        tool=QAction(payment_icon(icon),label,toolbar);toolbar.addAction(tool);tool.setEnabled(enabled)
        if callback:tool.triggered.connect(callback)
        tool.setToolTip('기준 PC 연결 설정' if enabled else label+' 서비스는 연결되지 않았습니다. 자동 설치·원격 접속을 실행하지 않습니다.')
    chrome.addWidget(toolbar);page.body.addWidget(page.payment_chrome)
    splitter=QSplitter(Qt.Orientation.Horizontal);left=QWidget();side=QVBoxLayout(left);side.setContentsMargins(0,0,4,0);side.setSpacing(5)
    page.search.setPlaceholderText('공급사명 · 코드 검색');side.addWidget(page.search)
    page.payment_search_layout=side
    page.include_inactive=QCheckBox('무효 공급사 포함');side.addWidget(page.include_inactive)
    page.supplier_list=DataGrid(['코드','공급사명']);page.supplier_list.setColumnWidth(0,60);page.supplier_list.setColumnWidth(1,190);side.addWidget(page.supplier_list,1);splitter.addWidget(left)
    page.payment_side=left
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
    selection.addWidget(page.method_filter)
    page.payment_process_button=action_button('결제처리',page.pay);selection.addWidget(page.payment_process_button)
    page.payment_edit_button=action_button('당일 결제 수정',page.edit_payment);selection.addWidget(page.payment_edit_button)
    page.payment_void_button=action_button('선택 결제 취소',page.void);selection.addWidget(page.payment_void_button)
    page.payment_selection=QWidget();page.payment_selection.setLayout(selection);main.addWidget(page.payment_selection)
    page.payment_void_action=page.payment_void_button;page.payment_edit_action=page.payment_edit_button
    page.grid.setColumnCount(len(SUMMARY_HEADERS));page.grid.setHorizontalHeaderLabels(SUMMARY_HEADERS)
    page.history_grid.setColumnCount(len(HISTORY_HEADERS));page.history_grid.setHorizontalHeaderLabels(HISTORY_HEADERS)
    page.tabs.setTabText(0,'외상매입현황');page.tabs.setTabText(1,'공급사별 거래내역');page.tabs.setTabText(2,'매입결제현황')
    page.purchase_detail_grid=DataGrid(['상품명','규격','바코드','수량','입력단위','단가','단가 기준','매입금액','과면세'])
    page.tabs.addTab(page.purchase_detail_grid,'매입 상세내역')
    from .payment_finance_ui import BillsPane,MembersPane,JournalPane,ProfitPane
    for title,pane in (('어음관리',BillsPane(page)),('외상매출현황',MembersPane(page,'summary')),('회원별 거래내역',MembersPane(page,'ledger')),('매출결제현황',MembersPane(page,'payments')),('계정원장',JournalPane(page)),('월손익계산서',ProfitPane(page))):page.tabs.addTab(pane,title)
    configure_menus(page)
    page.tabs.currentChanged.connect(lambda index:view_changed(page,index))
    main.addWidget(page.tabs,1);page.tabs.show()
    bank=QHBoxLayout();page.bank_fields={}
    for key,title in (('bank','은행'),('account_holder','예금주'),('account','계좌')):
        bank.addWidget(QLabel(title));field=QLineEdit();field.setReadOnly(True);bank.addWidget(field,2 if key=='account' else 1);page.bank_fields[key]=field
    page.bank_panel=QWidget();page.bank_panel.setLayout(bank);main.addWidget(page.bank_panel);page.summary.show();main.addWidget(page.summary)
    splitter.addWidget(right);splitter.setSizes([240,1100]);page.body.addWidget(splitter,1)
    for grid in page.findChildren(DataGrid):
        grid.setStyleSheet('QTableWidget{background:#A6ABAB;gridline-color:#BEC6C5;} QHeaderView::section{background:#C8DEE0;color:#263F47;border:1px solid #9AAFB3;} QTableWidget::item:selected{background:#176CB0;color:white;}')
    for grid in (page.grid,page.history_grid):
        grid.setColumnWidth(0,60);grid.setColumnWidth(1,205)
    page.grid.setColumnWidth(2,65);page.grid.setColumnWidth(3,115)
    for c in range(4,page.grid.columnCount()):page.grid.setColumnWidth(c,110)
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
    view_changed(page,0,False)


def action_button(label,callback):
    from .widgets import action
    return action(label,callback)


def configure_menus(page):
    groups=[('1.외상매입',[(t,i) for t,i,_ in VIEWS[:4]]),('2.외상매출',[(t,i) for t,i,_ in VIEWS[4:7]]),('3.간편장부',[('계정원장',8),('손익계산',9)]),('4.레포트출력',[]),('5.마감관리',[]),('6.기타',[])]
    page.payment_menu_groups=[]
    for title,entries in groups:
        menu=page.payment_menubar.addMenu(title);page.payment_menu_groups.append(menu)
        for label,index in entries:menu.addAction(page.payment_views[index])
    reports=page.payment_menu_groups[3]
    reports.addAction('현재 조회 결과 인쇄',page.print);reports.addAction('현재 조회 결과 엑셀',page.export)
    reports.addSeparator();reports.addAction('영업일보',lambda:page.window.open_page('report_day_summary'))
    reports.addAction('매입현황',lambda:page.tabs.setCurrentIndex(0))
    page.payment_menu_groups[4].addAction('현금 · 월재고 마감',lambda:page.window.open_page('closings'))
    misc=page.payment_menu_groups[5];misc.addAction('매입전표로 돌아가기',lambda:page.window.open_page('purchases'));misc.addAction('첫화면',lambda:page.window.go_home())


def travel(page,step):
    target=page.payment_history_index+step
    if not 0<=target<len(page.payment_history):
        if step<0:page.window.previous_menu()
        return
    page.payment_history_index=target;page._payment_replaying=True
    try:page.tabs.setCurrentIndex(page.payment_history[target])
    finally:page._payment_replaying=False
    update_history(page)


def update_history(page):
    history=getattr(page.window,'menu_history',None)
    page.payment_back.setEnabled(page.payment_history_index>0 or bool(history and history.target(-1) is not None))
    page.payment_forward.setEnabled(page.payment_history_index<len(page.payment_history)-1)
    if getattr(page.window,'current_key',None)=='payments':
        for title,step in (('이전',-1),('다음',1)):
            target=page.payment_history_index+step
            if 0<=target<len(page.payment_history):
                tool=page.window.history_actions[title];tool.setEnabled(True)
                tool.setToolTip(title+' · '+view_caption(page,page.payment_history[target]))


def view_changed(page,index,query=True):
    for tab,tool in page.payment_views.items():tool.setChecked(tab==index)
    if not page._payment_replaying and page.payment_history[page.payment_history_index]!=index:
        page.payment_history=page.payment_history[:page.payment_history_index+1]+[index];page.payment_history_index+=1
        if len(page.payment_history)>100:page.payment_history=page.payment_history[-100:];page.payment_history_index=len(page.payment_history)-1
    update_history(page)
    caption=view_caption(page,index);page.header.context.setText(caption);page.header.context.show()
    if getattr(page.window,'current_key',None)=='payments':
        from . import __version__
        page.window.setWindowTitle(caption+' ◀ '+page.window._store_name+' ◀ SY POS '+__version__)
        page.window._update_history_actions()
    extra=index>=4;page.payment_side.setVisible(index in {1,2,3})
    page.payment_selection.setVisible(not extra)
    if index==0:
        page.payment_search_layout.removeWidget(page.search);page.payment_selection.layout().insertWidget(0,page.search,1);page.search.show()
    elif index in {1,2,3}:
        page.payment_selection.layout().removeWidget(page.search);page.payment_search_layout.insertWidget(0,page.search);page.search.show()
    for control in (page.settlement_filter,page.day_filter,page.only_purchases):control.setVisible(index==0)
    page.include_voided.setVisible(index in {2,4})
    page.payment_process_button.setVisible(index in {0,1});page.payment_edit_button.setVisible(index==2);page.payment_void_button.setVisible(index==2)
    page.bank_panel.setVisible(index==1)
    if index>=4:page.summary.hide()
    else:page.summary.show()
    if query:page.refresh()


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
    if page.tabs.currentIndex()>=4:
        pane=page.tabs.currentWidget();pane.refresh();page.summary.setText(pane.note.text());return
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
    rows=page.store.payment_summary(first,last,page.search.text().strip(),page.only_purchases.isChecked(),party)
    if not page.include_inactive.isChecked():rows=[r for r in rows if r['active']]
    if page.day_filter.currentData() is not None:rows=[r for r in rows if r['settlement_day']==page.day_filter.currentData()]
    if page.settlement_filter.currentData() is not None:
        allowed={m['partner_id'] for m in data['memberships'] if m['group_id']==page.settlement_filter.currentData()};rows=[r for r in rows if r['id'] in allowed]
    values=[[r['code'],r['name'],'직영' if r['supplier_mode']=='direct' else '수수료',r['business_no'],r['opening'],r['purchase'],r['returns'],r['paid_total'],r['discount_payment'],r['closing'],r['balance'],r['last_purchase'] or '',r['last_payment'] or '',r['stock_value']] for r in rows]
    total=['합계','','','']+[sum(r[k] for r in rows) for k in ('opening','purchase','returns','paid_total','discount_payment','closing','balance')]+['','',sum(r['stock_value'] for r in rows)]
    fill_ordered(page.grid,values+[total],rows+[{}])
    for r in range(page.grid.rowCount()):
        for c,color in ((4,'#DBEFDD'),(5,'#F7DADC'),(7,'#DFE4E7'),(8,'#E5DBED'),(9,'#F6F4C4'),(10,'#F6F4C4')):page.grid.item(r,c).setBackground(QColor(color))
    for c in range(page.grid.columnCount()):page.grid.item(len(rows),c).setForeground(QColor('#24538D'))
    page.summary.setText(f"공급사 {len(rows):,}개 · 기간말 잔액 {won(sum(r['closing'] for r in rows))}원 / 현재 잔액 {won(sum(r['balance'] for r in rows))}원 · 지급(어음 포함)과 할인은 별도 집계합니다.\n상품재고액은 현재 상품 공급사 기준의 저장 원가입니다. 수기 장부이며 은행 송금·카드 승인 통신은 하지 않습니다.")
    ledger_data=page.store.ledger(party,first,last) if party else None
    ledger=ledger_data['entries'] if ledger_data else []
    if page.ledger_mode.currentIndex()==1:
        groups=defaultdict(list)
        for r in ledger:groups[r['date']].append(r)
        ledger=[dict(date=key,kind='day',number='일자 합계',charge=sum(r['charge'] for r in values),payment=sum(r['payment'] for r in values),balance=values[-1]['balance'],memo='') for key,values in groups.items()]
    if ledger_data:ledger=[dict(date=first,kind='carry',number='전기이월',charge=0,payment=0,balance=ledger_data['opening'],memo='')]+ledger
    fill_ordered(page.ledger_grid,[[r['date'],KINDS.get(r['kind'],{'carry':'전기이월','opening':'초기 외상','payment':'지급/할인','refund':'환급','day':'일자 합계'}.get(r['kind'],r['kind'])),r['number'],r['charge'],r['payment'],r['balance'],r['memo']] for r in ledger],ledger)
    history=page.store.supplier_payment_history(first,last,party,page.include_voided.isChecked())
    history=[r for r in history if term in (r['partner_code']+' '+r['partner_name']).casefold() and (not page.method_filter.currentData() or r['method']==page.method_filter.currentData())]
    from .payment_finance import DISCOUNTS
    page.history_grid.fill([[r['partner_code'],r['partner_name'],r['date'],r['amount'] if r['method']=='cash' else 0,r['amount'] if r['method']=='transfer' else 0,r['amount'] if r['method']=='card' else 0,r['amount'] if r['method']=='bill' else 0,r['amount'] if r['method'] in DISCOUNTS else 0,r['amount'],r['user_name'],'취소' if r['voided'] else '유효',r['memo'],r['number']] for r in history],history)
