"""F11 shows the selected item's price history beside the purchase worksheet."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSplitter
from .widgets import DataGrid, reference_grid


class PurchasePricePanel(QWidget):
    def __init__(self, trade):
        super().__init__(trade)
        self.trade = trade; self.enabled = False; self.last_key = None
        self.setObjectName('purchasePriceHistory'); self.setMinimumWidth(270); self.setMaximumWidth(440)
        layout = QVBoxLayout(self); layout.setContentsMargins(4, 0, 0, 0); layout.setSpacing(4)
        self.product_label = QLabel('상품을 선택하세요.'); self.product_label.setWordWrap(True)
        self.product_label.setMaximumHeight(42)
        self.barcode_label = QLabel('바코드: —'); self.basis_label = QLabel(); self.basis_label.setWordWrap(True)
        self.basis_label.setMaximumHeight(30); self.basis_label.setStyleSheet('font-size:11px;')
        for label in (self.product_label, self.barcode_label, self.basis_label):layout.addWidget(label)
        self.history = DataGrid(['매입일', '매입가', '판매가']); reference_grid(self.history)
        self.history.setSortingEnabled(False); self.history.verticalHeader().hide()
        self.history.setMinimumHeight(80)
        self.history.horizontalHeader().setSortIndicator(-1,Qt.SortOrder.AscendingOrder)
        self.history.setColumnWidth(0,90); self.history.setColumnWidth(1,85); self.history.setColumnWidth(2,85)
        layout.addWidget(self.history, 3)
        self.events = DataGrid(['행사기간', '매입가', '판매가']); reference_grid(self.events)
        self.events.setSortingEnabled(False); self.events.verticalHeader().hide()
        self.events.horizontalHeader().setSortIndicator(-1,Qt.SortOrder.AscendingOrder)
        self.events.setColumnWidth(0,130); self.events.setColumnWidth(1,85); self.events.setColumnWidth(2,85)
        self.events.setMinimumHeight(55); self.events.setMaximumHeight(110); layout.addWidget(self.events, 1)
        self.notice = QLabel(); self.notice.setWordWrap(True); self.notice.setMaximumHeight(32)
        self.notice.setStyleSheet('font-size:11px;'); layout.addWidget(self.notice)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh); self.hide()

    def toggle(self):
        self.enabled = not self.enabled; self.trade.tax_info_button.setChecked(self.enabled)
        self.setVisible(self.enabled and self.trade.detail_tabs.currentIndex()==0)
        if self.enabled:
            self.last_key = None
            self.trade.price_splitter.setSizes([max(420,self.trade.width()-330),310])
            self.refresh()
        else:self.timer.stop()

    def schedule(self, *_):
        if self.enabled:self.timer.start()

    def refresh(self):
        if not self.enabled:return
        trade = self.trade
        index = max(0, trade.table.currentRow())
        row = trade.line_rows[index] if index < len(trade.line_rows) else None
        identifier = row['product'].currentData() if row else None
        if not identifier:
            self.last_key = None; self.product_label.setText('상품을 선택하세요.'); self.barcode_label.setText('바코드: —')
            self.basis_label.clear(); self.history.fill([]); self.events.fill([]); self.notice.clear(); return
        unit = row['unit'].currentData(); cutoff = trade.date.date().toString('yyyy-MM-dd')
        key = (identifier, unit, cutoff)
        if key == self.last_key:return
        try:
            data = trade.store.purchase_price_history(identifier, cutoff, None if unit=='grams' else unit, unit=='grams')
            self.last_key = key
            self.product_label.setText('상품명: '+data['name']); self.product_label.setToolTip(data['name'])
            self.barcode_label.setText('바코드: '+(row['barcode'].text() or '—'))
            self.basis_label.setText(f"{data['basis']} · {cutoff}까지 확정 매입 · 최신순")
            records = data['records']
            self.history.fill([[r['date'], r['purchase_price'], r['sale_price'] if r['sale_price'] is not None else '—'] for r in records], records)
            self.history.setSortingEnabled(False)
            for i, record in enumerate(records):
                tip=f"{record['number']} · {record['supplier_name']} · 원단위 {record['original_basis']}{record['original_unit']}당\n판매가는 당시 전표에 기록한 판매단가입니다."
                changed = i+1 < len(records) and any(record[k] != records[i+1][k] for k in ('purchase_price','sale_price'))
                for column in range(3):
                    item=self.history.item(i,column); item.setToolTip(tip)
                    if changed:item.setBackground(QColor('#FFE3DF'))
                    if trade.record and record['document_id']==trade.record['id']:
                        font=item.font(); font.setBold(True); item.setFont(font)
            events=data['promotions']
            self.events.fill([[r['start']+' ~ '+r['end'],r['purchase_price'] if r['purchase_price'] is not None else '—',
                               r['sale_price'] if r['sale_price'] is not None else '—'] for r in events], events)
            self.events.setSortingEnabled(False)
            for i, event in enumerate(events):
                for column in range(3):self.events.item(i,column).setToolTip(event['title'])
            self.notice.setText(('최근 500건 · ' if data['truncated'] else '')+
                ('변경 가격 강조 · ' if records else '확정 매입 없음 · ')+'미저장 제외 · — 기록 없음')
            self.notice.setToolTip('변경된 가격은 연한 붉은색입니다. 미저장 입력은 제외하며, 기록 없는 과거 판매가는 현재 가격으로 채우지 않습니다.')
        except (ValueError, PermissionError, ConnectionError) as exc:
            self.last_key=None; self.history.fill([]); self.events.fill([])
            self.product_label.setText('가격 이력 조회 불가'); self.barcode_label.clear(); self.basis_label.clear(); self.notice.setText(str(exc))


def install_price_panel(trade, layout):
    index=layout.indexOf(trade.detail_tabs); layout.removeWidget(trade.detail_tabs)
    trade.price_splitter=QSplitter(Qt.Orientation.Horizontal,trade)
    trade.price_splitter.setChildrenCollapsible(False); trade.price_splitter.addWidget(trade.detail_tabs)
    trade.price_panel=PurchasePricePanel(trade); trade.price_splitter.addWidget(trade.price_panel)
    trade.price_splitter.setStretchFactor(0,1); trade.price_splitter.setStretchFactor(1,0)
    layout.insertWidget(index,trade.price_splitter,1)
    trade.tax_info_button.setCheckable(True)
    trade.tax_info_button.setToolTip('오른쪽에서 선택 상품의 매입일·매입가·당시 판매가·행사기간을 확인합니다. 다시 누르면 숨깁니다.\n단축키: F11')
    trade.table.currentCellChanged.connect(lambda row,col,old_row,old_col: trade.price_panel.schedule() if row!=old_row else None)
    trade.date.dateTimeChanged.connect(trade.price_panel.schedule)
    trade.detail_tabs.currentChanged.connect(lambda index: trade.price_panel.setVisible(trade.price_panel.enabled and index==0))
