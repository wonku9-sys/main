"""Category/product/supplier stock views and immutable month-end snapshots."""
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox,QComboBox,QHBoxLayout,QLabel,QMessageBox
from .widgets import Page,ScanField,action,won,FormDialog,DataGrid
from .category_tree import folder_icon

TITLES={'products':'현재고-단품별','categories':'현재고-분류별','suppliers':'현재고-공급사별','monthly':'월말재고'}

def quantity_text(values):
    return ' / '.join(f'{Decimal(value):,.3f} {unit}' for unit,value in values.items()) or '—'

class InventoryStatusPage(Page):
    def __init__(self,window,group='products'):
        self.group=group;self._ready=False
        super().__init__(window,TITLES[group],'PDF 재고관리 기준의 분류·공급사별 조회입니다. 수량은 기본단위, 금액은 소수점 두 자리입니다.')
        filters=QHBoxLayout();self.category=QComboBox();self.category.setMinimumWidth(210);self.category.addItem('전체분류',[])
        self.supplier=QComboBox();self.supplier.setMinimumWidth(190);self.supplier.addItem('전체 공급사',None)
        filters.addWidget(QLabel('분류'));filters.addWidget(self.category,1);filters.addWidget(QLabel('공급사'));filters.addWidget(self.supplier,1)
        filters.addWidget(action('조회',self.refresh));filters.addWidget(action('전체분류',lambda:self.category.setCurrentIndex(0)))
        self.body.addLayout(filters)
        controls=QHBoxLayout();self.search=ScanField();self.search.setPlaceholderText('상품코드 · 바코드 · 상품명 · 규격 · 공급사 검색');controls.addWidget(self.search,1)
        self.stock_filter=QComboBox()
        for title,key in [('재고 전체','all'),('재고 0 제외','nonzero'),('재고 > 0','positive'),('재고 = 0','zero'),('재고 < 0','negative')]:self.stock_filter.addItem(title,key)
        controls.addWidget(self.stock_filter)
        self.inactive=QCheckBox('무효상품 포함');controls.addWidget(self.inactive)
        self.children=QCheckBox('하위분류 표시');self.children.setEnabled(group=='categories');controls.addWidget(self.children)
        self.children.setToolTip('중·소분류 소계와 하위 상품을 함께 표시합니다. 소계를 중복 합산하지 않으며 하단 합계는 상품별 한 번만 계산합니다.')
        self.body.addLayout(controls)
        options=QHBoxLayout();self.valuation=QComboBox();self.valuation.addItem('재고평가: 상품장 매입가','catalog');self.valuation.addItem('재고평가: 이동평균 장부원가','average');options.addWidget(self.valuation)
        self.month=QComboBox();self.month.setMinimumWidth(150);self.month.setVisible(group=='monthly');options.addWidget(self.month)
        self.monthly_group=QComboBox()
        for title,key in [('분류별','categories'),('단품별','products'),('공급사별','suppliers')]:self.monthly_group.addItem(title,key)
        self.monthly_group.setVisible(group=='monthly');options.addWidget(self.monthly_group)
        self.valuation.setEnabled(group!='monthly');self.inactive.setEnabled(group!='monthly');options.addStretch();self.body.addLayout(options)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setObjectName('notice');self.body.addWidget(self.summary)
        self.grid=self.table(['분류 / 상품','상품종수','수량 (단위별)','매입가액','판매가액','면세재고','과세재고','장부원가'])
        self.grid.setColumnWidth(0,260);self.grid.itemDoubleClicked.connect(self.drill)
        self.total=QLabel();self.total.setWordWrap(True);self.body.addWidget(self.total)
        self.actions.addWidget(action('선택 상품 입출고 이력',self.history))
        for control in (self.category,self.supplier,self.stock_filter,self.valuation,self.month,self.monthly_group):control.currentIndexChanged.connect(self.auto_refresh)
        for control in (self.inactive,self.children):control.toggled.connect(self.auto_refresh)
        self.search.scanned.connect(lambda *_:self.refresh());self._ready=True

    def auto_refresh(self,*_):
        if self._ready:self.refresh()

    def fill_options(self,report):
        def fill(control,options):
            old=control.currentData();control.blockSignals(True);control.clear()
            for caption,value in options:control.addItem(caption,value)
            control.setCurrentIndex(max(0,control.findData(old)));control.blockSignals(False)
        fill(self.category,[('전체분류',[])]+[('  '*(len(row['path'])-1)+' / '.join(row['path']),row['path']) for row in report['filters']['categories']])
        fill(self.supplier,[('전체 공급사',None)]+([] if self.group=='monthly' else [('공급사 미지정',0)])+[(f"{r['code']} · {r['name']}".strip(' ·'),r['id']) for r in report['filters']['suppliers']])
        fill(self.month,[(r['month'],r['month']) for r in report['filters']['months']])

    def refresh(self):
        if not self._ready:return
        try:
            arguments=dict(group=self.group,category_path=self.category.currentData() or [],supplier_id=self.supplier.currentData(),search=self.search.text().strip(),include_inactive=self.inactive.isChecked(),show_children=self.children.isChecked(),stock_filter=self.stock_filter.currentData(),valuation=self.valuation.currentData(),month=self.month.currentData() or '',monthly_group=self.monthly_group.currentData())
            report=self.store.inventory_status(**arguments);self.fill_options(report)
            actual=dict(category_path=self.category.currentData() or [],supplier_id=self.supplier.currentData(),month=self.month.currentData() or '')
            if any(arguments[key]!=value for key,value in actual.items()):
                arguments.update(actual);report=self.store.inventory_status(**arguments);self.fill_options(report)
            self.report=report
            effective=self.monthly_group.currentData() if self.group=='monthly' else self.group
            self.grid.setSortingEnabled(False)
            if effective=='products':
                headers=['상품코드','상품명','규격','바코드','분류','공급사','현재고','단위','단가 기준','매입단가','판매단가','매입가액','판매가액','장부원가','최종실사일']
                values=[[r['code'],r['name'],r.get('specification','—'),r.get('barcode','—'),' / '.join(r['path']),r.get('supplier_name') or '미지정',Decimal(r['stock_qty']),r['base_unit'],f"{r['price_basis']}{r['base_unit']}당" if 'price_basis' in r else '—',r.get('purchase_price','—'),r.get('sale_price','—'),r.get('purchase_total','—'),r.get('sale_total','—'),r['stock_cost'],r.get('last_count','—')] for r in report['rows']]
            else:
                headers=['분류 / 상품' if effective=='categories' else '공급사','상품종수','수량 (단위별)','매입가액','판매가액','면세재고','과세재고','장부원가','과세 공급가액 (참고)','부가세 (참고)']
                values=[]
                for row in report['rows']:
                    quantities=row.get('quantities',{row.get('base_unit',''):row.get('stock_qty','0')})
                    values.append(['   '*row['depth']+('↳ ' if row['row_kind']=='product' else '')+row['label'],row.get('item_count',1),quantity_text(quantities),*[row.get(key,0) if not report['snapshot'] else '—' for key in ('purchase_total','sale_total','exempt_total','taxable_total')],row['stock_cost'],*[row.get(key,0) if not report['snapshot'] else '—' for key in ('supply_value','vat')]])
            self.grid.setColumnCount(len(headers));self.grid.setHorizontalHeaderLabels(headers)
            if effective=='categories':self.grid.horizontalHeader().setSortIndicator(-1,Qt.SortOrder.AscendingOrder)
            self.grid.fill(values,report['rows'])
            # Tree-like order must stay intact; users can sort individual and supplier lists.
            self.grid.setSortingEnabled(effective!='categories')
            if effective=='categories':
                for index,row in enumerate(report['rows']):
                    if row['row_kind']=='group':self.grid.item(index,0).setIcon(folder_icon(min(3,max(1,len(row['path'])))))
            totals=report['totals'];self.total.setText(f"합계 {totals['item_count']:,}개 상품 · {quantity_text(totals['quantities'])} · 장부원가 {won(totals['stock_cost'])}원"+('' if report['snapshot'] else f" · 상품장 매입가액 {won(totals['purchase_total'])}원 · 판매가액 {won(totals['sale_total'])}원"))
            self.summary.setText(('마감 자료가 없습니다. ‘현금 · 월재고 마감’에서 먼저 월말 마감하세요.' if not report['closed_at'] else f"저장된 월말 마감: {self.month.currentData()} · {report['closed_at']}\n마감 당시 상품명·대분류·공급사·수량·장부원가만 보존합니다. 중·소분류/단가/과면세는 과거값이 없어 재계산하지 않습니다.") if report['snapshot'] else '분류를 더블클릭하면 하위 단계로 이동합니다. 하위분류 표시는 중·소분류와 상품까지 펼칩니다. 소계는 중복 합산하지 않습니다.\n매입가액·판매가액은 현재 상품장의 1단위/100g 기준이며, 장부원가는 이동평균 원가입니다. 재고관리 제외 상품은 집계하지 않습니다.')
            self.summary.setText(self.summary.text()+'\n음수 재고의 원가와 이익은 잠정값입니다. 부족 입고를 확인하고 원가 차이는 재고실사로 조정하세요.')
        except (ValueError,PermissionError) as exc:self.grid.fill([]);self.total.clear();self.summary.clear();self.fail(exc)

    def focus_scan(self):self.search.setFocus();self.search.selectAll()

    def drill(self,*_):
        row=self.grid.selected()
        if not row:return
        if row['row_kind']=='product':self.history();return
        if row.get('path'):
            if self.group=='monthly' and row['path']==self.category.currentData():
                self.monthly_group.setCurrentIndex(self.monthly_group.findData('products'));return
            index=self.category.findData(row['path'])
            if index>=0:self.category.setCurrentIndex(index)
        elif 'supplier_id' in row:
            self.supplier.setCurrentIndex(max(0,self.supplier.findData(row['supplier_id'])))
            if self.group=='monthly':self.monthly_group.setCurrentIndex(self.monthly_group.findData('products'))
            elif 'inventory' in self.window.items:
                self.window.open_page('inventory');page=self.window.pages['inventory'];page.supplier.setCurrentIndex(max(0,page.supplier.findData(row['supplier_id'] or 0)))

    def history(self):
        row=self.grid.selected()
        if not row or row['row_kind']!='product':return
        try:
            records=self.store.stock_events(row['id']);dialog=FormDialog(row['name']+' · 입출고 이력',self);dialog.resize(1000,630)
            grid=DataGrid(['일자','구분','수량 증감','잔여수량','원가 증감','잔여원가','사유']);grid.read_permissions=('inventory',)
            grid.fill([[r['date'],r['kind'],Decimal(r['qty_delta']),Decimal(r['balance_qty']),r['cost_delta'],r['balance_cost'],r['reason']] for r in records],records)
            dialog.body.addWidget(grid);dialog.body.addWidget(action('엑셀 저장',lambda:grid.export(dialog,'입출고 이력')));dialog.body.addWidget(action('인쇄',lambda:grid.print_pages(dialog,'입출고 이력')));dialog.exec()
        except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'재고 이력',str(exc))
