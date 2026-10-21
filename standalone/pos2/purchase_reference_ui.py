"""Five compact purchase views below the fixed desktop query strip."""
from collections import defaultdict
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox,QComboBox,QHBoxLayout,QLabel,QLineEdit,QSplitter,QVBoxLayout,QWidget
from .widgets import DataGrid,action,date_field,search_icon,won


class ReferenceGrid(DataGrid):
    def fill(self,rows,records=None):
        self.setSortingEnabled(False);super().fill(rows,records)
        for r in range(self.rowCount()):
            summary=self.item(r,0).data(Qt.ItemDataRole.UserRole) is None
            for c in range(self.columnCount()):
                item=self.item(r,c)
                if summary:
                    item.setBackground(QColor('#FFF2BA'));item.setForeground(QColor('#235DAC'))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)


def lookup_row(page):
    surface=QWidget();row=QHBoxLayout(surface);row.setContentsMargins(0,0,0,0);row.setSpacing(4)
    if page.group in {'category','product'}:row.addWidget(page.category)
    row.addWidget(page.supplier)
    find=action('공급사 검색',lambda:pick_supplier(page));find.setText('');find.setIcon(search_icon());find.setFixedWidth(28);find.setToolTip('공급사명 또는 코드로 검색해서 선택합니다.');row.addWidget(find)
    page.header.description.hide();page.header.context.hide();page.header.left_layout.addWidget(surface)


def pick_supplier(page):
    from .workflow_ui import PartnerPicker
    dialog=PartnerPicker(page.window,'supplier',for_filter=True,menu_key=page.menu_key)
    if dialog.exec() and dialog.selected_record is not None:
        page.supplier.setCurrentIndex(max(0,page.supplier.findData(dialog.selected_record['id'])))
    elif dialog.result()==dialog.DialogCode.Accepted:page.supplier.setCurrentIndex(0)


def setup(page):
    page._reference=True;page._filter_revision=None;page._details_key=None
    page.body.setContentsMargins(8,8,8,8);page.body.setSpacing(5)
    page.start,page.end=date_field(),date_field();page.supplier=QComboBox();page.supplier.addItem('전체 공급사',None);page.supplier.setMaximumWidth(190)
    page.category=QComboBox();page.category.addItem('전체 분류','');page.category.setMaximumWidth(190)
    page.search=QLineEdit();page.search.setPlaceholderText('상품 · 공급사 · 전표 / 사업자번호');page.search.setMaximumWidth(250)
    page.returns=QCheckBox('반품 포함');page.returns.setChecked(True)
    page.kind=QComboBox()
    for title,key in (('전체',''),('매입','purchase'),('반품','purchase_return')):page.kind.addItem(title,key)
    controls=QHBoxLayout();controls.setSpacing(5);controls.addWidget(QLabel('매입기간' if page.group=='statement' else '기간'));controls.addWidget(page.start);controls.addWidget(QLabel('~'));controls.addWidget(page.end)
    if page.group=='supplier':
        controls.addWidget(page.category);page.settlement=QComboBox();page.settlement.addItem('결제유형 전체',None)
        page.general_group=QComboBox();page.general_group.addItem('그룹 전체',None);page.exclude_group=QCheckBox('제외');page.zero_suppliers=QCheckBox('거래 없음 포함')
        for control in (page.settlement,page.general_group,page.exclude_group,page.zero_suppliers):controls.addWidget(control)
    elif page.group=='product':
        controls.addWidget(QLabel('검색어'));controls.addWidget(page.search);page.by_supplier=QCheckBox('공급사별');controls.addWidget(page.by_supplier)
    elif page.group=='document':
        controls.addWidget(page.kind);page.sort_mode=QComboBox();page.sort_mode.addItems(['일자순','공급사순']);controls.addWidget(page.sort_mode)
    elif page.group=='statement':controls.addWidget(QLabel('사업자 / 검색어'));controls.addWidget(page.search);controls.addWidget(page.kind)
    controls.addWidget(page.returns);controls.addStretch();page.body.addLayout(controls);lookup_row(page)
    headers={
        'supplier':['코드','공급사명','구분','사업자번호','면세매입','과세매입','과세공급가액','공급가액 합','부가세','매입합계','반품금액','순매입금액','전표 수'],
        'category':['분류명','유형','면세매입','과세매입','과세공급가액','공급가액 합','부가세','매입합계','반품금액','순매입금액'],
        'product':['상품명','규격','바코드','매입량','입력단위','매입단가','단가 기준','공급가액','부가세','매입액','공급사'],
        'document':['코드','공급사','상품명','규격','바코드','매입량','단위','공급가액','부가세','매입액','매입단가','단가 기준','매입일','전표번호'],
        'statement':['구분','공급사','매입일','사업자번호','매입합계','면세매입','과세매입','전표번호'],
    }[page.group]
    page.grid=page.table(headers,grid_type=ReferenceGrid);page.grid.setSortingEnabled(False)
    page.grid.setColumnWidth(1 if page.group=='supplier' else 0,210)
    if page.group=='supplier':
        page.body.removeWidget(page.grid);splitter=QSplitter(Qt.Orientation.Vertical);splitter.addWidget(page.grid)
        lower=QSplitter(Qt.Orientation.Horizontal);page.supplier_documents=DataGrid(['구분','유형','입고일','매입합계','전표결제','현재 미지급 / 환불예정','메모','전표번호'])
        page.supplier_payments=DataGrid(['구분','결제일','결제금액','메모'])
        lower.addWidget(page.supplier_documents);lower.addWidget(page.supplier_payments);splitter.addWidget(lower);splitter.setSizes([600,180]);page.body.addWidget(splitter,1)
        page.grid.itemSelectionChanged.connect(lambda:drill_supplier(page));page.supplier_documents.cellDoubleClicked.connect(lambda *_:open_document(page,page.supplier_documents))
    elif page.group=='statement':
        page.body.removeWidget(page.grid);splitter=QSplitter(Qt.Orientation.Horizontal);splitter.addWidget(page.grid)
        right=QWidget();layout=QVBoxLayout(right);layout.setContentsMargins(0,0,0,0)
        note=QLabel('계산서 대조용 내부 집계\n발행자료가 아닙니다. 실제 계산서 파일 형식 확인 후 가져오기 연결 예정.');note.setWordWrap(True);layout.addWidget(note)
        page.invoice_comparison=DataGrid(['상호','대표자명','매입합계','공급가액','부가세','전표 수']);layout.addWidget(page.invoice_comparison,1);splitter.addWidget(right);page.body.addWidget(splitter,1)
    page.summary=QLabel();page.summary.setWordWrap(True);page.body.addWidget(page.summary)
    if page.group in {'document','statement'}:page.grid.cellDoubleClicked.connect(lambda *_:open_document(page,page.grid))
    for name in ('supplier','category','kind','settlement','general_group','sort_mode'):
        if hasattr(page,name):getattr(page,name).currentIndexChanged.connect(page.refresh)
    for name in ('returns','exclude_group','zero_suppliers','by_supplier'):
        if hasattr(page,name):getattr(page,name).toggled.connect(page.refresh)
    page.search.returnPressed.connect(page.refresh);page.refresh()


def populate(combo,choices):
    current=combo.currentData();combo.blockSignals(True)
    while combo.count()>1:combo.removeItem(1)
    for label,value in choices:combo.addItem(label,value)
    combo.setCurrentIndex(max(0,combo.findData(current)));combo.blockSignals(False)


def metadata(page):
    revision=page.store.audit_revision()
    if revision!=page._filter_revision:
        data=page.store.purchase_status_filters(page.group);page._filter_data=data;page._filter_revision=revision
        populate(page.supplier,[(r['name'],r['id']) for r in data['suppliers']]);populate(page.category,[(c,c) for c in data['categories']])
        if page.group=='supplier':
            for combo,kind in ((page.settlement,'settlement'),(page.general_group,'general')):populate(combo,[(r['name'],r['id']) for r in data['groups'] if r['kind']==kind])
    return page._filter_data


def paint(page,values,records,financial=(),pink=()):
    page.grid.fill(values,records)
    for r in range(page.grid.rowCount()):
        summary=page.grid.item(r,0).data(Qt.ItemDataRole.UserRole) is None
        if summary:continue
        for c in financial:page.grid.item(r,c).setBackground(QColor('#E0EFDE'))
        for c in pink:
            page.grid.item(r,c).setBackground(QColor('#EAD0D2'));font=page.grid.item(r,c).font();font.setBold(True);page.grid.item(r,c).setFont(font)


def refresh(page):
    data=metadata(page);start,end=page.start.date().toString('yyyy-MM-dd'),page.end.date().toString('yyyy-MM-dd')
    if start>end:raise ValueError('조회 시작일과 종료일을 확인하세요.')
    if page.group=='supplier':
        rows=page.store.purchase_status(start,end,'supplier',page.supplier.currentData(),page.category.currentData(),page.search.text(),page.returns.isChecked())['rows']
        if page.zero_suppliers.isChecked() and not page.category.currentData() and not page.search.text().strip():
            present={r['supplier_id'] for r in rows}
            for s in data['suppliers']:
                if s['id'] not in present and (page.supplier.currentData() is None or page.supplier.currentData()==s['id']):
                    rows.append(dict(code=s['code'],label=s['name'],supplier_id=s['id'],business_no=s['business_no'],supplier_mode=s['supplier_mode'],**{k:Decimal(0) for k in ('exempt_total','taxable_total','supply_value','total_supply_value','vat','purchase_total','return_total','net_total')},count=0))
        memberships=defaultdict(set)
        for member in data['memberships']:memberships[member['group_id']].add(member['partner_id'])
        for combo in (page.settlement,page.general_group):
            if combo.currentData() is None:continue
            excluded=combo is page.general_group and page.exclude_group.isChecked()
            rows=[r for r in rows if (r['supplier_id'] in memberships[combo.currentData()])!=excluded]
        values=[[r['code'],r['label'],'직매입' if r['supplier_mode']=='direct' else '수수료',r['business_no'],r['exempt_total'],r['taxable_total'],r['supply_value'],r['total_supply_value'],r['vat'],r['purchase_total'],r['return_total'],r['net_total'],r['count']] for r in rows]
        paint(page,values,rows,range(4,9),(11,))
        if rows:page.grid.selectRow(0)
        else:page.supplier_documents.fill([]);page.supplier_payments.fill([])
        total=sum(r['net_total'] for r in rows);count=len(rows)
    else:
        lines=page.store.purchase_status_lines(start,end,page.group,page.supplier.currentData(),page.category.currentData(),page.search.text(),page.returns.isChecked())
        if page.kind.currentData():lines=[r for r in lines if r['kind']==page.kind.currentData()]
        total=sum((r['net_total'] for r in lines),Decimal(0));count=len(lines)
        values,records=table_rows(page,lines)
        financial,pink={'category':(range(2,7),(7,9)),'product':((7,8),(9,)),'document':((7,8),(9,)),'statement':((5,6),(4,))}[page.group]
        paint(page,values,records,financial,pink)
        if page.group=='statement':
            groups=defaultdict(list)
            for line in lines:groups[line['partner_id']].append(line)
            page.invoice_comparison.fill([[v[0]['supplier_name'],'',sum(r['net_total'] for r in v),sum(r['supply_value'] for r in v),sum(r['vat'] for r in v),len({r['document_id'] for r in v})] for v in groups.values()])
    page.summary.setText(f'{start} ~ {end} · 조회 {count:,}건 · 순매입 {won(total)}원 · 확정 전표 기준 · 포함세액 참고 집계 / 보증금 별도 원장·센터 연동 없음')


def table_rows(page,lines):
    values=[];records=[]
    if page.group=='category':
        groups=defaultdict(list)
        for r in lines:groups[(' / '.join(filter(None,(r['category'],r['category_mid'],r['category_small']))) or '미분류',r['supplier_mode'])].append(r)
        for (name,mode),rows in groups.items():
            exempt=sum(r['exempt_total'] for r in rows);taxable=sum(r['taxable_total'] for r in rows);vat=sum(r['vat'] for r in rows)
            purchase=sum(r['total'] for r in rows if r['kind']=='purchase');returned=sum(r['total'] for r in rows if r['kind']=='purchase_return')
            values.append([name,'직매입' if mode=='direct' else '수수료',exempt,taxable,taxable-vat,exempt+taxable-vat,vat,purchase,returned,purchase-returned]);records.append(dict(label=name))
        if values:values.append(['Σ 합계','']+[sum(v[c] for v in values) for c in range(2,10)]);records.append(None)
    elif page.group=='product':
        groups=defaultdict(list)
        for r in lines:groups[(r['product_id'],r['unit_name'],r['factor'],r['price_basis'],r['partner_id'] if page.by_supplier.isChecked() else None)].append(r)
        for key,rows in groups.items():
            r=rows[0];quantity=sum((Decimal(x['signed_qty']) for x in rows),Decimal(0));total=sum(x['net_total'] for x in rows)
            price=(total/quantity*r['price_basis']).quantize(Decimal('.01')) if quantity else ''
            values.append([r['product_name'],r['specification'],r['barcode'],quantity,r['unit_name'],price,r['price_basis'],sum(x['supply_value'] for x in rows),sum(x['vat'] for x in rows),total,r['supplier_name'] if key[-1] is not None else '전체']);records.append(dict(product_id=r['product_id']))
        if values:values.append(['Σ 합계','','','','','','']+[sum(v[c] for v in values) for c in (7,8,9)]+['']);records.append(None)
    else:
        groups=defaultdict(list)
        ordered=sorted(lines,key=lambda r:(r['supplier_name'],r['date'],r['document_id'],r['id'])) if page.group=='document' and page.sort_mode.currentIndex()==1 else lines
        for r in ordered:groups[r['document_id']].append(r)
        for rows in groups.values():
            r=rows[0]
            if page.group=='statement':
                values.append(['반품' if r['kind']=='purchase_return' else '매입',r['supplier_name'],r['date'],r['business_no'],sum(x['net_total'] for x in rows),sum(x['exempt_total'] for x in rows),sum(x['taxable_total'] for x in rows),r['number']]);records.append(r)
            else:
                for x in rows:
                    values.append([x['supplier_code'],x['supplier_name'],x['product_name'],x['specification'],x['barcode'],Decimal(x['signed_qty']),x['unit_name'],x['supply_value'],x['vat'],x['net_total'],x['unit_price'],x['price_basis'],x['date'],x['number']]);records.append(x)
                values.append(['',f"[{r['date']} {r['number']} 소계]",'','','','','',sum(x['supply_value'] for x in rows),sum(x['vat'] for x in rows),sum(x['net_total'] for x in rows),'','','','']);records.append(None)
        if page.group=='statement' and values:values.append(['','Σ 합계','','']+[sum(v[c] for v in values) for c in (4,5,6)]+['']);records.append(None)
    return values,records


def drill_supplier(page):
    record=page.grid.selected()
    if not record:return
    start,end=page.start.date().toString('yyyy-MM-dd'),page.end.date().toString('yyyy-MM-dd')
    key=(record['supplier_id'],start,end,page._filter_revision)
    if key==page._details_key:return
    page._details_key=key
    try:
        records=[r for r in page.store.documents(start=start,end=end,partner_id=record['supplier_id'],status='posted') if r['kind'].startswith('purchase')]
        page.supplier_documents.fill([['반품' if r['source_id'] else '매입','직매입' if record['supplier_mode']=='direct' else '수수료',r['date'],(-1 if r['source_id'] else 1)*r['total'],(-1 if r['source_id'] else 1)*r['cash_paid'],r['net_balance'],r['memo'],r['number']] for r in records],records)
        payments=page.store.supplier_payment_history(start,end,record['supplier_id'],False)
        page.supplier_payments.fill([['묶음 결제' if r['type']=='settlement' else '전표 결제',r['date'],r['amount'],r['memo']] for r in payments],payments)
    except (ValueError,PermissionError) as exc:page.supplier_documents.fill([]);page.supplier_payments.fill([]);page.fail(exc)


def open_document(page,grid):
    record=grid.selected()
    if not record:return
    identifier=record.get('document_id',record.get('id'))
    if not identifier:return
    from .workflow_ui import TradeDialog
    try:
        doc=page.store.document(identifier);TradeDialog(page.window,doc['kind'],doc).exec()
    except (ValueError,PermissionError) as exc:page.fail(exc)
