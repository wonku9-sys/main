"""Offline purchasing, selling, ledgers, counts and immutable closeouts."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from PySide6.QtCore import QDate, Qt, QTimer, QEvent, QItemSelectionModel
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QMenu, QScrollArea, QFrame, QSizePolicy,
)

from .widgets import DataGrid, Cell, HeaderSafeTable, Page, ScanField, action, amount, date_field, search_icon, won
from .common import decimal as value_decimal, qty
from .currency import public_input as money, round_amount as rounded


KINDS = {"purchase": "매입", "sale": "매출", "purchase_return": "매입 반품", "sale_return": "매출 반품"}
STATUSES = {"draft": "초안", "posted": "확정", "cancelled": "취소"}


def _permission(store, key):
    actor = store.actor or {}
    return actor.get("role") == "admin" or key in actor.get("permissions", [])


def _date(field):
    return field.date().toString("yyyy-MM-dd")


def _confirm(parent, title, message):
    return QMessageBox.question(parent, title, message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


def _warn(parent, error):
    QMessageBox.warning(parent, "처리할 수 없습니다", str(error))


def _dates(layout, callback):
    start, end = date_field(), date_field()
    layout.addWidget(QLabel("기간"))
    layout.addWidget(start)
    layout.addWidget(QLabel("~"))
    layout.addWidget(end)
    layout.addWidget(action("조회", callback))
    return start, end


def _compact_scroll_row(layout, height=50):
    """Let small windows scroll controls, never widen the native frame."""
    content=QWidget();content.setLayout(layout)
    from PySide6.QtGui import QPalette
    palette=content.palette();palette.setColor(QPalette.ColorRole.Window,QColor('#DCE1DA'))
    content.setPalette(palette);content.setAutoFillBackground(True)
    scroll=QScrollArea();scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True);scroll.setWidget(content)
    scroll.viewport().setPalette(palette)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
    scroll.setFixedHeight(height)
    return scroll


class PartnerPicker(QDialog):
    """A compulsory counterparty selection, searchable by name or code."""
    def __init__(self, window, kind, for_filter=False, menu_key=None):
        super().__init__(window)
        self.store, self.kind, self.selected_record, self.for_filter = window.store, kind, None, for_filter
        self.setWindowTitle("공급사 검색" if kind == "supplier" else "판매처 검색")
        self._sy_no_home_button=True
        self.resize(700, 510)
        self._fixed_query_header=True
        self.read_permissions=('trade',)
        self.menu_key=menu_key or ('purchases' if kind=='supplier' else 'sales')
        self._cache=None;self._cache_revision=None
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.refresh)
        body = QVBoxLayout(self)
        row=QHBoxLayout();row.setContentsMargins(0,0,0,0);row.addStretch()
        row.addWidget(QLabel('공급사명 또는 코드 검색:' if kind=='supplier' else '판매처명 또는 코드 검색:'))
        self.search = QLineEdit()
        self.search.setPlaceholderText("이름 · 코드 · 연락처")
        self.search.setMinimumWidth(160);self.search.setMaximumWidth(270)
        row.addWidget(self.search);body.addWidget(_compact_scroll_row(row))
        self.grid = DataGrid(["공급사명" if kind=='supplier' else "판매처명", "코드", "구분", "사업자번호", "담당자", "연락처"])
        self.grid.setSortingEnabled(False);self.grid.installEventFilter(self)
        self.search.installEventFilter(self)
        self.grid.menu_key=self.menu_key;self.grid.read_permissions=('trade',)
        self.grid.setColumnWidth(0,260)
        body.addWidget(self.grid,1)
        self.search.textChanged.connect(self.search_changed)
        self.grid.itemDoubleClicked.connect(self.choose)
        self.notice=QLabel();body.addWidget(self.notice)
        controls=QHBoxLayout();controls.addStretch()
        self.choose_button=action('확인',self.choose,True);controls.addWidget(self.choose_button)
        self.close_button=action('닫기',self.reject);controls.addWidget(self.close_button)
        self._sy_close_button=self.close_button;body.addLayout(controls)
        self.search.returnPressed.connect(self.choose)
        self.shortcuts=[]
        for sequence,callback in (('F4',self.focus_search),('F5',self.refresh)):
            shortcut=QShortcut(QKeySequence(sequence),self);shortcut.activated.connect(callback);self.shortcuts.append(shortcut)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.refresh()
        QTimer.singleShot(0,self,self.focus_search)

    def focus_search(self):
        self.search.setFocus();self.search.selectAll()

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.KeyPress:
            if watched is self.search and event.key()==Qt.Key.Key_Down:
                if self.grid.rowCount():self.grid.setFocus();self.grid.selectRow(0)
                return True
            if watched is self.grid and event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
                self.choose();return True
        return super().eventFilter(watched,event)

    def search_changed(self,*_):
        if len(self._cache or [])>500:self.search_timer.start()
        else:self.refresh()

    def refresh(self):
        self.search_timer.stop()
        try:
            self.store.require_menu(self.menu_key)
            revision=(str(self.store.actor),tuple(self.store.audit_revision()))
            if self._cache is None or revision!=self._cache_revision:
                self._cache=self.store.trade_partners(self.kind,include_inactive=self.for_filter)
                self._cache_revision=revision
            query=self.search.text().strip().casefold()
            rows=[r for r in self._cache if query in ' '.join(str(r.get(k,'')) for k in ('name','code','phone')).casefold()]
            if self.for_filter and not query:
                rows.insert(0, {"id": None, "code": "전체", "name": "전체 공급사" if self.kind == "supplier" else "전체 판매처", "contact": "", "phone": ""})
            self.grid.fill([[r['name']+(' (무효)' if not r.get('active',True) else ''),r['code'],
                '수수료' if r.get('supplier_mode')=='commission' else '직매입' if self.kind=='supplier' else '판매처',
                r.get('business_no',''),r.get('contact',''),r.get('phone','')] for r in rows],rows)
            if rows:self.grid.setCurrentCell(0,0,QItemSelectionModel.SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows)
            self.notice.setText(f'검색 {len(rows):,} / 전체 {len(self._cache):,}곳 · 방향키 선택 · Enter/더블클릭 확인 · Esc 닫기')
            self.choose_button.setEnabled(bool(rows))
        except (ValueError,PermissionError) as exc:
            self.grid.fill([]);self.choose_button.setEnabled(False);self.notice.setText(str(exc))

    def choose(self, *_):
        if self.search_timer.isActive():self.refresh()
        selected=self.grid.selected()
        if selected is None:return
        try:
            self.store.require_menu(self.menu_key)
            if selected['id'] is not None:
                selected=next((r for r in self.store.trade_partners(self.kind,include_inactive=self.for_filter) if r['id']==selected['id']),None)
                if selected is None:raise ValueError('삭제되었거나 무효인 거래처입니다. 다시 선택하세요.')
            self.selected_record=selected;self.accept()
        except (ValueError,PermissionError) as exc:
            self.notice.setText(str(exc));self.selected_record=None

    def done(self,result):
        self.search_timer.stop();super().done(result)


class ProductSelectionGrid(DataGrid):
    def selectRow(self,row):
        # Programmatic selection must not toggle an already-selected row when
        # a native Ctrl modifier happens to be held. Mouse Ctrl-click remains Qt's.
        if not 0<=row<self.rowCount():return
        self.setCurrentCell(row,0,QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selectionModel().select(self.model().index(row,0),QItemSelectionModel.SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows)


class ProductPicker(QDialog):
    def __init__(self, parent, product_loader=None, read_permissions=("trade",)):
        super().__init__(parent)
        self.store, self.record, self.unit_id = parent.store, None, None
        self.supplier_id = parent.partner.currentData() if getattr(parent, "kind", "").startswith("purchase") else None
        self.supplier_name = parent.partner.currentText() if self.supplier_id else ""
        self.selections, self.checked = [], {}
        self.read_permissions = read_permissions
        self.product_loader = product_loader
        self._records_cache = None
        self._records_revision = None
        self._units_cache=None;self._units_revision=None
        parent_revision = getattr(parent, 'products_revision', None)
        if product_loader is None and parent_revision is not None and parent_revision == self.store.catalog_revision():
            self._records_cache = list(parent.products)
            self._records_revision = (str(self.store.actor), parent_revision)
            self.index_records()
        self.page = 0
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh)
        self.on_apply = None; self.applied_batches = 0
        self.setWindowTitle("상품 검색")
        self._sy_no_home_button=True
        self.resize(1080, 600)
        self._fixed_query_header=True
        body = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setMinimumWidth(180)
        self.search.setPlaceholderText("상품코드 · 기본/확장 바코드 · 상품명 · 규격으로 검색")
        self.search.setToolTip('상품코드·바코드·상품명·규격을 입력하면 검색합니다.\n단축키: F4 검색칸 이동 · F5 다시 조회')
        filters.addWidget(self.search, 1)
        self.search_button=action('검색 (F5)',self.search_now);filters.addWidget(self.search_button)
        self.supplier_only = QCheckBox("선택 공급사만 (F7)")
        self.supplier_only.setChecked(bool(self.supplier_id))
        self.supplier_only.setEnabled(bool(self.supplier_id))
        self.supplier_only.setToolTip("체크를 해제하면 전체 공급사의 등록 상품을 조회합니다.\n단축키: F7")
        filters.addWidget(self.supplier_only)
        self.expanded_units=QCheckBox('확장단위검색')
        self.expanded_units.setEnabled(product_loader is None)
        self.expanded_units.setToolTip('체크하면 확장단위명·바코드도 검색하고 각 단위를 별도 행으로 표시합니다. 적용 시 그 단위의 환산량·단가를 유지합니다.')
        self.include_inactive=QCheckBox('무효상품포함')
        self.include_inactive.setToolTip('무효 상품·단위도 조회합니다. 무효 항목은 재활성화 전에는 새 전표에 적용할 수 없습니다.')
        self.tracked_only=QCheckBox('재고관리 대상만')
        for control in (self.expanded_units,self.include_inactive,self.tracked_only):filters.addWidget(control)
        body.addWidget(_compact_scroll_row(filters,62))
        self.supplier_label = QLabel(parent.partner.currentText() if self.supplier_id else "전체 공급사 상품")
        body.addWidget(self.supplier_label)
        body.addWidget(QLabel("Space·더블클릭: 선택 품목 적용 · Enter: 체크 품목 적용 · F4: 검색어 · F5: 검색 · F7: 공급사"))
        self.keep_open = QCheckBox('적용 후 검색창 유지 · 연속 검색/추가')
        self.keep_open.setChecked(True); self.keep_open.hide(); body.addWidget(self.keep_open)
        self.result_label = QLabel(); body.addWidget(self.result_label)
        self.grid = ProductSelectionGrid(["선택", "상품코드", "상품명", "규격", "바코드", "단위", "공급사", "매입가", "판매가", "현재고"])
        from PySide6.QtWidgets import QAbstractItemView
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setStyleSheet('QTableWidget::item:selected {background:#176CB0;color:white;}')
        self.grid.setToolTip('방향키: 상품 이동 · 드래그/Ctrl/Shift: 여러 행 선택\nSpace: 선택 상품을 전표에 추가 · F8: 선택행 체크 · F9: 선택행 체크해제')
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.context_menu)
        self.grid.installEventFilter(self)
        body.addWidget(self.grid, 1)
        self.search.textChanged.connect(self.search_changed)
        for control in (self.supplier_only,self.expanded_units,self.include_inactive,self.tracked_only):
            control.toggled.connect(self.scope_changed)
        self.grid.itemChanged.connect(self.check_changed)
        self.grid.cellDoubleClicked.connect(lambda *_: self.choose())
        controls = QHBoxLayout()
        self.check_row_button=action('선택행 체크 (F8)',lambda:self.check_current(True))
        self.uncheck_row_button=action('선택행 체크해제 (F9)',lambda:self.check_current(False))
        self.check_all_button=action('모두 체크',lambda:self.check_all(True))
        self.uncheck_all_button=action('모두 체크해제',lambda:self.check_all(False))
        for button,hint in ((self.check_row_button,'선택한 행을 체크합니다.\n단축키: F8'),
                            (self.uncheck_row_button,'선택한 행의 체크를 해제합니다.\n단축키: F9'),
                            (self.check_all_button,'현재 검색 결과에 표시된 상품을 모두 체크합니다.\n단축키: Ctrl+Shift+A'),
                            (self.uncheck_all_button,'다른 검색어에서 체크한 품목까지 모두 해제합니다.\n단축키: Ctrl+Shift+D')):
            button.setToolTip(hint);controls.addWidget(button)
        self.apply_checked_button = action("체크된 상품 적용", self.apply_checked, True)
        self.apply_checked_button.setToolTip('체크한 상품을 입력 목록에 한 번에 추가합니다. 전표는 최종 저장 전까지 재고·대금에 반영되지 않습니다.\n단축키: Enter')
        pages = QHBoxLayout()
        pages.addWidget(action('이전 500개', lambda: self.move_page(-1)))
        pages.addWidget(action('다음 500개', lambda: self.move_page(1)))
        self.page_label = QLabel()
        pages.addWidget(self.page_label, 1)
        body.addLayout(pages)
        footer=QHBoxLayout();footer.setContentsMargins(0,0,0,0)
        footer.addWidget(_compact_scroll_row(controls),1)
        footer.addWidget(self.apply_checked_button)
        self.close_button=action('닫기',self.reject);footer.addWidget(self.close_button)
        self._sy_close_button=self.close_button;body.addLayout(footer)
        self.search.returnPressed.connect(self.search_enter)
        self.search.installEventFilter(self)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.shortcuts = []
        for sequence, callback in (('F4', self.focus_search), ('F5', self.search_now),
                                   ('F7', lambda:self.supplier_only.toggle() if self.supplier_only.isEnabled() else None),
                                   ('F8', lambda:self.check_current(True)), ('F9', lambda:self.check_current(False)),
                                   ('Ctrl+Shift+A',lambda:self.check_all(True)),('Ctrl+Shift+D',lambda:self.check_all(False))):
            shortcut=QShortcut(QKeySequence(sequence),self);shortcut.activated.connect(callback);self.shortcuts.append(shortcut)
        for sequence in ('Return','Enter'):
            enter=QShortcut(QKeySequence(sequence),self.grid);enter.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);enter.activated.connect(self.apply_checked);self.shortcuts.append(enter)
        self.refresh()
        QTimer.singleShot(0,self,self.focus_search)

    def set_apply_callback(self, callback):
        self.on_apply = callback; self.keep_open.show()

    def eventFilter(self, watched, event):
        if watched is self.search and event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Down:
            if self.grid.rowCount():self.grid.setFocus();self.grid.selectRow(0)
            return True
        if watched is self.grid and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self.apply_selected()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def focus_search(self):
        self.search.setFocus(); self.search.selectAll()

    def search_enter(self):
        if self.checked:self.apply_checked()
        else:self.search_now()

    def search_now(self):
        self.refresh()
        if self.grid.rowCount():self.grid.setFocus()

    @staticmethod
    def selection_key(record):
        unit_id=record.get('_picker_unit_id')
        return (record['id'],unit_id) if unit_id else record['id']

    def scope_changed(self,*_):
        self.checked={key:record for key,record in self.checked.items()
            if (not self.supplier_only.isChecked() or record.get('supplier_id')==self.supplier_id)
            and (self.expanded_units.isChecked() or not record.get('_picker_unit_id'))
            and (self.include_inactive.isChecked() or record.get('active',True) and record.get('_picker_unit',{}).get('active',True))
            and (not self.tracked_only.isChecked() or record.get('tracked',True))}
        self.refresh()

    def check_current(self, checked):
        items=[self.grid.item(index.row(),0) for index in self.grid.selectionModel().selectedRows()]
        sorting=self.grid.isSortingEnabled();self.grid.setSortingEnabled(False)
        try:
            for item in items:item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:self.grid.setSortingEnabled(sorting)

    def apply_selected(self):
        indices = self.grid.selectionModel().selectedRows()
        if len(indices) <= 1:
            return self.choose()
        self.selections = [(record,record.get('_picker_unit_id')) for index in indices
            if (record:=self.grid.item(index.row(), 0).data(Qt.ItemDataRole.UserRole))]
        self.record, self.unit_id = self.selections[0]
        self.deliver()

    def context_menu(self, point):
        item = self.grid.itemAt(point)
        if item is not None and not item.isSelected():
            self.grid.selectRow(item.row())
        menu = QMenu(self)
        for label, callback in (('선택 상품 적용 (Space)', self.apply_selected),
                ('체크된 상품 적용 (Enter)', self.apply_checked),
                ('선택행 체크 (F8)', lambda: self.check_current(True)),
                ('선택행 체크해제 (F9)', lambda: self.check_current(False)),
                ('현재 페이지 모두 체크', lambda: self.check_all(True)),
                ('모든 체크해제', lambda: self.check_all(False))):
            menu.addAction(label, callback)
        menu.addSeparator(); menu.addAction('이 창 닫기', self.reject)
        menu.exec(self.grid.viewport().mapToGlobal(point))

    def records(self, search='', supplier_id=None):
        # Revalidate authority even on cache hits; an audit/restore change invalidates it.
        self.store._require(*(('trade',) if self.product_loader is None else self.read_permissions))
        revision = (str(self.store.actor), self.store.catalog_revision() if self.product_loader is None else tuple(self.store.audit_revision()))
        if self._records_cache is None or revision != self._records_revision:
            self._records_cache = self.store.trade_products(include_inactive=True) if self.product_loader is None else self.product_loader()
            self._records_revision = revision
            self.index_records()
        query=search.casefold()
        return [r for r in self._records_cache if (self.include_inactive.isChecked() or r.get('active',True))
                and (not supplier_id or r.get('supplier_id')==supplier_id)
                and (not self.tracked_only.isChecked() or r.get('tracked',True))
                and query in self._search_text[r['id']]]

    def index_records(self):
        self._search_text = {r['id']: ' '.join(str(r.get(key,'')) for key in ('code','barcode','name','specification')).casefold()
                            for r in self._records_cache}

    def search_units(self):
        if self.product_loader is not None:return []
        if self._units_cache is None or self._units_revision!=self._records_revision:
            self._units_cache=self.store.trade_search_units(include_inactive=True)
            self._units_revision=self._records_revision
        return self._units_cache

    def search_changed(self, *_):
        if len(self._records_cache or []) > 500:
            self.search_timer.start()
        else:
            self.refresh()

    def move_page(self, direction):
        self.page += direction
        self.render_records()

    def refresh(self, *_):
        self.search_timer.stop()
        records=self.records(supplier_id=self.supplier_id if self.supplier_only.isChecked() else None)
        query=self.search.text().strip().casefold()
        self.matches=[r for r in records if query in self._search_text[r['id']]]
        if self.expanded_units.isChecked():
            products={r['id']:r for r in records}
            for unit in self.search_units():
                product=products.get(unit['product_id'])
                if product is None or not self.include_inactive.isChecked() and not unit['active']:continue
                text=' '.join((product['code'],product['name'],product.get('specification',''),unit['name'],unit['barcode'])).casefold()
                if query in text:self.matches.append({**product,'_picker_unit_id':unit['id'],'_picker_unit':unit})
        self.page = 0
        self.render_records()

    def render_records(self):
        count = len(self.matches)
        self.page = max(0, min(self.page, max(0, (count-1)//500)))
        records = self.matches[self.page*500:(self.page+1)*500]
        # A scope change must not silently apply checked products hidden outside it.
        if self.supplier_only.isChecked():
            self.checked = {key: row for key, row in self.checked.items() if row.get("supplier_id") == self.supplier_id}
        self.grid.blockSignals(True)
        self.grid.fill([["", r["code"], r["name"]+(' (무효)' if not r.get('active',True) or not r.get('_picker_unit',{}).get('active',True) else ''), r.get("specification",''), r.get('_picker_unit',{}).get('barcode',r.get("barcode",'')), r.get('_picker_unit',{}).get('name',r["base_unit"]), r.get("supplier_name") or "미지정", r.get('_picker_unit',{}).get('purchase_price',r["purchase_price"]), r.get('_picker_unit',{}).get('sale_price',r["sale_price"]), Decimal(r["stock_qty"]) if 'stock_qty' in r else '—'] for r in records], records)
        from .tax_display import tax_icon
        icons={mode:tax_icon(mode) for mode in ('taxable','exempt')}
        for index in range(self.grid.rowCount()):
            cell = self.grid.item(index, 0)
            record = cell.data(Qt.ItemDataRole.UserRole)
            cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            cell.setCheckState(Qt.CheckState.Checked if self.selection_key(record) in self.checked else Qt.CheckState.Unchecked)
            self.grid.item(index,2).setIcon(icons.get(record.get('tax_mode'),QIcon()))
        self.grid.blockSignals(False)
        self.supplier_label.setText((self.supplier_name if self.supplier_only.isChecked() else "전체 공급사 상품") + f" · {count:,}개")
        self.page_label.setText(f'{self.page+1} / {max(1,(count+499)//500)}쪽 · 모두 체크는 현재 표시된 500개까지 적용')
        self.update_checked_count()
        if records:
            self.grid.selectRow(0)

    def done(self, result):
        self.search_timer.stop()
        super().done(result)

    def update_checked_count(self):
        self.apply_checked_button.setText(f"체크된 상품 적용 ({len(self.checked):,})")

    def check_changed(self, item):
        if item.column() != 0:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if record:
            if item.checkState() == Qt.CheckState.Checked:
                self.checked[self.selection_key(record)] = record
            else:
                self.checked.pop(self.selection_key(record), None)
        self.update_checked_count()

    def check_all(self, checked):
        if not checked:
            self.checked.clear()
        sorting=self.grid.isSortingEnabled();self.grid.setSortingEnabled(False)
        try:
            for index in range(self.grid.rowCount()):
                self.grid.item(index, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:self.grid.setSortingEnabled(sorting)
        self.update_checked_count()

    def apply_checked(self):
        if not self.checked:
            return _warn(self, "적용할 상품을 체크하세요.")
        self.selections = [(record,record.get('_picker_unit_id')) for record in self.checked.values()]
        self.record, self.unit_id = self.selections[0]
        self.deliver()

    def deliver(self):
        try:
            fresh={r['id']:r for r in self.records()}
            selections=[]
            units={u['id']:u for u in self.search_units()} if any(unit_id for _,unit_id in self.selections) else {}
            for record,unit_id in self.selections:
                if record['id'] not in fresh or not fresh[record['id']].get('active',True):raise ValueError('사용할 수 없는 상품이 있습니다. 다시 검색해 선택하세요.')
                unit=units.get(unit_id)
                if unit_id and (not unit or unit['product_id']!=record['id'] or not unit.get('active',True)):
                    raise ValueError('사용 중지된 확장단위입니다. 다시 선택하세요.')
                selections.append((fresh[record['id']],unit_id))
            self.selections=selections
            self.record,self.unit_id=selections[0]
            if self.on_apply is None:self.accept();return
            self.on_apply(selections)
        except (ValueError,PermissionError) as exc:
            _warn(self,exc);return
        self.applied_batches+=1;self.checked.clear()
        self.result_label.setText(f'{len(selections):,}개 품목을 입력 목록에 추가했습니다. 전표는 최종 저장 전입니다.')
        if not self.keep_open.isChecked():self.accept();return
        self.selections=[];self.search.blockSignals(True);self.search.clear();self.search.blockSignals(False);self.refresh();self.focus_search()

    def choose(self):
        record = self.grid.selected()
        if not record:
            return
        self.record = record
        self.unit_id = record.get('_picker_unit_id')
        found = self.store.lookup_barcode(self.search.text().strip()) if self.expanded_units.isChecked() and self.search.text().strip() and self.product_loader is None else None
        if found and found["product"]["id"] == record["id"] and found.get("unit"):
            if not found["unit"].get("active", True):
                _warn(self, "사용 중지된 확장단위입니다. 상품명으로 검색해 유효한 단위를 선택하세요.")
                return
            self.unit_id = found["unit"]["id"]
        self.selections = [(self.record, self.unit_id)]
        self.deliver()


class PurchaseSourcePicker(QDialog):
    """Choose the original purchase without permitting unrelated returns."""
    def __init__(self, window, partner_id=None):
        super().__init__(window)
        self.store, self.partner_id, self.record = window.store, partner_id, None
        self.setWindowTitle("반품할 매입전표 선택")
        self.resize(900, 550)
        body = QVBoxLayout(self)
        body.addWidget(QLabel("반품할 원매입전표를 선택하세요. 남은 수량만 반품하며, 원래 단가로 미지급잔액과 재고를 차감합니다."))
        filters = QHBoxLayout()
        self.start, self.end = _dates(filters, self.refresh)
        self.start.setDate(QDate.currentDate().addMonths(-3))
        body.addLayout(filters)
        self.search = QLineEdit()
        self.search.setPlaceholderText("전표번호 · 공급사명 · 메모 검색")
        self.search.returnPressed.connect(self.refresh)
        body.addWidget(self.search)
        self.grid = DataGrid(["전표번호", "매입일", "공급사", "매입합계", "미지급잔액", "메모"])
        self.grid.read_permissions = ("trade",)
        body.addWidget(self.grid, 1)
        self.grid.itemDoubleClicked.connect(self.choose)
        controls = QHBoxLayout()
        controls.addStretch()
        controls.addWidget(action("선택", self.choose, True))
        controls.addWidget(action("닫기", self.reject))
        body.addLayout(controls)
        self.refresh()

    def refresh(self):
        if not hasattr(self, "grid"):
            return
        try:
            self.store.require_menu("purchases")
            rows = self.store.documents("purchase", _date(self.start), _date(self.end), self.partner_id, "posted", self.search.text())
            self.grid.fill([[r["number"], r["date"], r["partner_name"], r["total"], r["balance"], r["memo"]] for r in rows], rows)
        except (ValueError, PermissionError) as exc:
            _warn(self, exc)

    def choose(self, *_):
        row = self.grid.selected()
        if not row:
            return
        try:
            self.record = self.store.document(row["id"])
            if not any(Decimal(str(line["remaining_qty"])) > 0 for line in self.record["lines"]):
                return _warn(self, "이미 전량 반품한 전표입니다. 다른 전표를 선택하세요.")
            self.accept()
        except (ValueError, PermissionError) as exc:
            _warn(self, exc)


class TradeDetailDialog(QDialog):
    """Small read-only trade information, never an alternative save path."""
    def __init__(self,trade,title,headers,rows,note=''):
        super().__init__(trade);self.store=trade.store
        self.menu_key='purchases' if trade.kind.startswith('purchase') else 'sales'
        self.store.require_menu(self.menu_key)
        self._fixed_query_header=True;self._sy_no_home_button=True
        self.setWindowTitle(title);self.resize(720,450)
        layout=QVBoxLayout(self)
        if note:
            label=QLabel(note);label.setWordWrap(True);layout.addWidget(label)
        self.grid=DataGrid(headers);self.grid.read_permissions=('trade',);self.grid.menu_key=self.menu_key
        self.grid.fill(rows);layout.addWidget(self.grid,1)
        footer=QHBoxLayout();footer.addStretch()
        self._sy_close_button=action('닫기',self.reject);footer.addWidget(self._sy_close_button);layout.addLayout(footer)


class PurchaseBatchDialog(QDialog):
    def __init__(self,trade):
        super().__init__(trade);self.trade=trade;self.store=trade.store
        self._fixed_query_header=True;self._sy_no_home_button=True;self.applied=False
        self.setWindowTitle('매입 수량·단가 일괄입력');self.resize(760,500)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('현재 전표의 수량·단가만 적용합니다. 최종 저장 전에는 재고·결제가 바뀌지 않습니다.'))
        self.table=HeaderSafeTable(0,4);self.table.setHorizontalHeaderLabels(['상품명','입력 단위','수량','매입단가'])
        self.inputs=[]
        for row in trade.line_rows:
            if not row['product'].currentData():continue
            index=self.table.rowCount();self.table.insertRow(index)
            for column,text in enumerate((row['product'].currentText(),row['unit'].currentText())):
                item=QTableWidgetItem(text);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(index,column,item)
            quantity=QLineEdit(row['qty'].text());price=QLineEdit(row['price'].text());price.setReadOnly(bool(row.get('source')))
            self.table.setCellWidget(index,2,quantity);self.table.setCellWidget(index,3,price)
            self.inputs.append((row,quantity,price))
        self.initial=tuple((quantity.text(),price.text()) for _,quantity,price in self.inputs)
        self.table.setColumnWidth(0,260);self.table.setColumnWidth(1,190)
        layout.addWidget(self.table,1)
        footer=QHBoxLayout();footer.addStretch();footer.addWidget(action('수량·단가 적용',self.apply_values,True))
        self._sy_close_button=action('닫기',self.reject);footer.addWidget(self._sy_close_button);layout.addLayout(footer)

    def apply_values(self):
        try:
            self.store._require_capability('purchases','edit' if self.trade.record else 'create')
            values=[]
            for row,quantity,price in self.inputs:
                qty(quantity.text(),allow_zero=self.trade.is_return)
                money(price.text());values.append((row,quantity.text(),price.text()))
            self.trade._batch_lines=True
            try:
                for row,quantity,price in values:row['qty'].setText(quantity);row['price'].setText(price)
            finally:self.trade._batch_lines=False
            self.trade.recalculate();self.applied=True;self.accept()
        except (ValueError,PermissionError) as exc:_warn(self,exc)

    def reject(self):
        changed=tuple((quantity.text(),price.text()) for _,quantity,price in self.inputs)!=self.initial
        if changed and not self.applied and not _confirm(self,'일괄입력 닫기','적용하지 않은 수량·단가 변경을 버릴까요?'):return
        super().reject()


class TradeDialog(QDialog):
    """Explicit draft/post workflow; scans only edit unsaved line quantities."""

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()
    def __init__(self, window, kind="purchase", record=None, source=None):
        super().__init__(window)
        self._sy_no_home_button=kind.startswith('purchase')
        self._reserved_function_keys={'F11'} if kind.startswith('purchase') else set()
        self.window, self.store, self.kind = window, window.store, kind
        self.record = self.store.document(record) if isinstance(record, int) else record
        self.source = self.store.document(source) if isinstance(source, int) else source
        self.readonly = bool(self.record and self.record["status"] != "draft")
        from .permissions import can_action
        resource = "purchases" if kind.startswith("purchase") else "sales"
        self.store.require_menu(resource)
        if self.record and not can_action(self.store.actor, resource, "edit"):
            self.readonly = True
        self.is_return = kind.endswith("_return")
        self.rounding_mode = (self.record or self.source or {}).get("rounding_mode", self.store.calculation_policy()["rounding_mode"])
        self.saved_id = None
        self.line_rows = []
        before = self.store.catalog_revision()
        self.products = self.window.cached_products() if hasattr(self.window, 'cached_products') else self.store.products()
        self.products_revision = before if before == self.store.catalog_revision() else None
        self.product_map = {p["id"]: p for p in self.products}
        from .trade_product_model import TradeProductModel
        self.product_model = TradeProductModel([p for p in self.products if p['active'] or self.readonly or self.is_return], self)
        self._batch_lines = False
        self.line_columns = ("product", "spec", "barcode", "qty", "unit", "factor", "base_qty", "price", "total", "sale_price", "margin", "category", "supplier", "stock", "delete")
        self.setWindowTitle(("새 반품전표" if self.is_return else "새 매입전표") if kind.startswith("purchase") and not self.record else f"{KINDS[kind]} 전표 · " + (self.record["number"] if self.record else "새 전표"))
        self.resize(1180, 820)
        self.setMinimumSize(850, 620)
        if QApplication.platformName() != "offscreen" and self.screen():
            area = self.screen().availableGeometry()
            self.resize(min(1180, max(850, area.width() - 50)), min(820, max(620, area.height() - 70)))
        body = QVBoxLayout(self)
        body.setSpacing(5);body.setContentsMargins(10,8,10,8)
        heading = QLabel(("반품전표" if self.is_return else "매입전표") if kind.startswith("purchase") else f"{KINDS[kind]} 전표")
        self.heading = heading
        heading.setObjectName("pageTitle")
        if kind.startswith('purchase'):heading.setStyleSheet('font-size:16px;font-weight:600;')
        body.addWidget(heading)
        self.explanation = QLabel("초안은 재고·결제·포인트를 변경하지 않습니다. 확정 후에는 수정 대신 취소 후 재등록합니다.")
        self.explanation.setWordWrap(True)
        body.addWidget(self.explanation)
        metadata = QHBoxLayout()
        self.date = date_field((self.record or {}).get("date"))
        metadata.addWidget(QLabel("거래일"))
        metadata.addWidget(self.date)
        self.partner = QComboBox()
        self.partner.setMinimumWidth(230)
        self.partner.addItem("거래처를 선택하세요", None)
        party_kind = "supplier" if kind.startswith("purchase") else "customer"
        api = getattr(self.store, "trade_partners", self.store.partners)
        self.party_map = {}
        for party in api(party_kind):
            self.party_map[party["id"]] = party
            self.partner.addItem(f"{party['code']} · {party['name']}", party["id"])
        metadata.addWidget(self.partner, 1)
        self.pick_button = action("공급사 (F3)" if kind.startswith("purchase") else "거래처 검색", lambda: self.pick_partner(party_kind))
        metadata.addWidget(self.pick_button)
        self.member = QComboBox()
        self.member.addItem("비회원", None)
        if kind.startswith("sale"):
            for member in self.store.trade_members():
                self.member.addItem(f"{member['code']} · {member['name']}", member["id"])
            metadata.addWidget(QLabel("회원"))
            metadata.addWidget(self.member)
        body.addWidget(_compact_scroll_row(metadata,46))
        self.return_mode = None
        if kind.startswith("purchase"):
            mode_row = QHBoxLayout()
            self.return_mode = QCheckBox("반품")
            self.return_mode.setChecked(self.is_return)
            self.return_mode.setEnabled(not self.record and not self.readonly and can_action(self.store.actor, "purchases", "delete"))
            self.return_mode.setToolTip("체크하면 원매입전표를 선택해 반품합니다. 확정 전표의 종류는 변경하지 않습니다.")
            mode_row.addWidget(QLabel("전표 구분"))
            mode_row.addWidget(self.return_mode)
            self.source_label = QLabel(f"원전표 {self.source['number']}" if self.source else "매입 · 반품 체크 시 원전표 선택")
            mode_row.addWidget(self.source_label, 1)
            body.addLayout(mode_row)
            self.return_mode.toggled.connect(self.switch_purchase_mode)
        original = self.record or self.source or {}
        if original.get("partner_id") and self.partner.findData(original["partner_id"]) < 0:
            self.partner.addItem(original.get("partner_name", "이력 거래처"), original["partner_id"])
        self.partner.setCurrentIndex(max(0, self.partner.findData(original.get("partner_id"))))
        self.member.setCurrentIndex(max(0, self.member.findData(original.get("member_id"))))
        self.partner_info = QLabel()
        self.partner_info.setObjectName("muted")
        self.partner_info.setWordWrap(True)
        body.addWidget(self.partner_info)
        self.partner.currentIndexChanged.connect(self.update_partner_info)
        self.update_partner_info()
        if self.source:
            body.addWidget(QLabel(f"원전표 {self.source['number']} · 남은 반품 가능 수량 이내로 입력하세요. 환불액은 원단가 기준입니다."))
        scanner = QHBoxLayout()
        scan_key='Ctrl+B' if kind.startswith('purchase') else 'F8'
        scanner.addWidget(QLabel('바코드 '+scan_key))
        self.scan = ScanField()
        self.scan.setMinimumWidth(210)
        self.scan.setPlaceholderText("USB 스캐너 입력 후 Enter · 확장단위 바코드 지원")
        self.scan.setToolTip("바코드를 입력하거나 USB 스캐너로 읽은 뒤 Enter를 누르세요. 확장단위 바코드도 지원합니다.\n단축키: "+scan_key)
        self.scan.scanned.connect(self.scan_barcode)
        scanner.addWidget(self.scan, 1)
        self.add_button = action("품목 추가", self.add_line)
        self.search_button = action("상품검색 (F5)", self.pick_product)
        self.quote_button = action("선택 날짜·회원 제안가 적용", self.apply_quotes)
        scanner.addWidget(self.add_button)
        line_tools=QHBoxLayout();line_tools.setContentsMargins(0,0,0,0)
        if kind.startswith('purchase'):
            self.move_up_button=action('위로',lambda:self.move_line(-1))
            self.move_down_button=action('아래로',lambda:self.move_line(1))
            self.move_up_button.setToolTip('선택 품목을 한 행 위로 이동합니다.\n단축키: Alt+Up')
            self.move_down_button.setToolTip('선택 품목을 한 행 아래로 이동합니다.\n단축키: Alt+Down')
            for button in (self.move_up_button,self.move_down_button):
                button.setEnabled(not self.readonly);line_tools.addWidget(button)
            line_tools.addWidget(self.search_button)
        else:scanner.addWidget(self.search_button)
        if kind.startswith("purchase"):
            from .permissions import has_menu
            self.catalog_button = action("상품장", self.open_catalog)
            self.catalog_button.setToolTip("매입전표를 유지한 채 상품장을 엽니다. 새 상품 저장 후 품목을 바로 적용할 수 있습니다.")
            self.catalog_button.setEnabled(not self.readonly and not self.is_return and has_menu(self.store.actor, "products"))
            scanner.addWidget(self.catalog_button)
        if kind.startswith("purchase"):
            self.edit_line_button = action("매입수정 (F6)", self.edit_selected_line)
            self.remove_line_button = action("선택행삭제 (F7)", self.remove_selected_line)
            line_tools.addWidget(self.edit_line_button)
            line_tools.addWidget(self.remove_line_button)
            self.batch_button=action('일괄입력',self.bulk_edit_lines);self.batch_button.setEnabled(not self.readonly)
            self.batch_button.setToolTip('작성 중인 품목의 수량·단가를 한 창에서 검토해 적용합니다.\n단축키: Ctrl+I')
            line_tools.addWidget(self.batch_button);line_tools.addStretch()
            self.edit_line_button.setEnabled(not self.readonly)
            self.remove_line_button.setEnabled(not self.readonly)
        scanner.addWidget(self.quote_button)
        if kind.startswith('purchase'):body.addWidget(_compact_scroll_row(line_tools,48))
        body.addWidget(_compact_scroll_row(scanner,48))
        self.table = HeaderSafeTable(0, len(self.line_columns))
        self.table.setHorizontalHeaderLabels(["상품명", "규격", "바코드", "매입량" if kind.startswith("purchase") else "수량", "입력 단위", "환산량", "총수량 (기본단위)", "매입단가" if kind.startswith("purchase") else "거래단가", "매입금액" if kind.startswith("purchase") else "거래금액", "현재 판매단가 (참고)", "예상이익률", "분류", "공급사", "현재고 / 반품 가능", "삭제"])
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((220, 75, 125, 75, 180, 60, 100, 85, 95, 130, 85, 140, 150, 130, 60)):
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.addTab(self.table, "거래 품목")
        self.payments_grid = DataGrid(["번호", "일자", "금액", "방법", "담당자", "상태", "메모"])
        payment_panel = QWidget()
        payment_layout = QVBoxLayout(payment_panel)
        payment_layout.addWidget(self.payments_grid)
        payment_controls = QHBoxLayout()
        payment_controls.addWidget(action("결제 이력 엑셀", lambda: self.payments_grid.export(self, "결제 이력")))
        payment_controls.addWidget(action("결제 이력 인쇄", lambda: self.payments_grid.print_pages(self, "결제 이력")))
        self.void_button = action("선택 결제 취소", self.void_payment)
        payment_controls.addWidget(self.void_button)
        payment_controls.addStretch()
        payment_layout.addLayout(payment_controls)
        self.detail_tabs.addTab(payment_panel, "결제 · 환불 이력")
        body.addWidget(self.detail_tabs, 1)
        figures = QGridLayout()
        self.tax_label, self.quantity_label, self.estimate_label = QLabel(), QLabel(), QLabel()
        for column, label in enumerate((self.tax_label, self.quantity_label, self.estimate_label)):
            label.setWordWrap(True)
            label.setObjectName("muted")
            figures.addWidget(label, 0, column)
        body.addLayout(figures)
        settlement = QHBoxLayout()
        self.total_label = QLabel("합계 0원")
        self.total_label.setObjectName("summary")
        settlement.addWidget(self.total_label, 1)
        self.paid = QLineEdit(str((self.record or {}).get("cash_paid", 0)))
        self.paid.setMaximumWidth(145)
        self.method = QComboBox()
        self.method.addItem("현금", "cash")
        self.method.addItem("계좌이체", "transfer")
        if kind.startswith('purchase'):
            self.method.addItem('카드 수기', 'card')
        self.points = QLineEdit(str((self.record or {}).get("points_used", 0)))
        self.points.setMaximumWidth(110)
        self.paid_caption = QLabel("환불금액" if self.is_return else "결제금액")
        settlement.addWidget(self.paid_caption)
        settlement.addWidget(self.paid)
        settlement.addWidget(self.method)
        if kind == "sale":
            settlement.addWidget(QLabel("사용 포인트"))
            settlement.addWidget(self.points)
        body.addLayout(settlement)
        self.balance_label = QLabel()
        self.balance_label.setObjectName("summary")
        self.balance_label.setWordWrap(True)
        self.payment_status = QLabel()
        balance_row = QHBoxLayout()
        balance_row.addWidget(self.balance_label, 1)
        balance_row.addWidget(self.payment_status)
        body.addLayout(balance_row)
        self.paid.textChanged.connect(self.recalculate)
        self.points.textChanged.connect(self.recalculate)
        self.memo = QLineEdit((self.record or {}).get("memo", ""))
        self.memo.setPlaceholderText("전표 메모")
        body.addWidget(self.memo)
        footer = QHBoxLayout()
        self.print_button = action("전표 인쇄", self.print_document)
        self.excel_button = action("엑셀 저장", self.export_document)
        if not kind.startswith('purchase'):
            footer.addWidget(self.print_button)
            footer.addWidget(self.excel_button)
        if kind.startswith('purchase'):
            self.print_button.setText('인쇄 ▾')
            self.print_button.clicked.disconnect()
            self.print_menu=QMenu(self.print_button)
            self.print_menu.addAction('인쇄그리드 · 목록 미리보기',self.print_grid)
            self.print_menu.addAction('프린터 · 매입전표 양식 미리보기',self.print_document)
            self.print_button.setMenu(self.print_menu)
            self.pdf_button=action('PDF 저장',lambda:self.purchase_output('pdf'))
            # PDF remains a real, directly reachable print-menu command.
            self.print_menu.addAction('PDF 저장',lambda:self.purchase_output('pdf'))
            line_tools.addWidget(self.excel_button);line_tools.addWidget(self.print_button)
            self.excel_button.setToolTip('열려 있는 매입전표 한 건을 공급자·공급받는 자와 품목표가 있는 A4 엑셀 양식으로 저장합니다.')
            from PySide6.QtCore import QSize
            for button,label in ((self.excel_button,'엑셀 저장'),(self.print_button,'인쇄')):
                button.setAccessibleName(label);button.setText('');button.setFixedWidth(44);button.setIconSize(QSize(23,23))
            self.print_button.setToolTip('인쇄그리드·프린터 미리보기·PDF 저장을 선택합니다.\n단축키: Ctrl+P')
            self.excel_button.setToolTip('공급자·공급받는 자와 품목표가 있는 A4 엑셀 양식으로 저장합니다.\n단축키: Ctrl+E')
        if kind.startswith("purchase"):
            self.product_info_button=action('상품정보 (F8)',self.product_info)
            footer.addWidget(self.product_info_button)
            self.new_product_button = action("새 상품등록 (F9)", self.new_product)
            self.new_product_button.setEnabled(not self.readonly and not self.is_return and can_action(self.store.actor, "products", "create"))
            footer.addWidget(self.new_product_button)
            self.tax_info_button=action('과면세 정보 (F11)',self.tax_info)
            footer.addWidget(self.tax_info_button)
            self.payment_button=action('결제 (P)',self.payment_input)
            self.payment_button.setEnabled(not self.readonly or bool(self.record and self.record['status']=='posted' and self.kind=='purchase'))
            self.payment_button.setToolTip('저장 전에는 결제 입력값을 적용하고, 확정된 매입전표에서는 지급 등록·이력·당일 수정·취소를 엽니다.\n단축키: Alt+P')
            footer.addWidget(self.payment_button)
        footer.addStretch()
        self.draft_button = action("전표 적용 (A)" if kind.startswith("purchase") else "초안 저장", lambda: self.save(False, not self.kind.startswith("purchase")))
        self.draft_button.setToolTip("입력을 초안으로 저장하고 계속 작업합니다. 재고·결제에는 반영하지 않습니다." if kind.startswith("purchase") else "초안을 저장합니다.")
        self.post_button = action("저장" if kind.startswith("purchase") else "전표 확정", lambda: self.save(True), True)
        allowed = can_action(self.store.actor, resource, "edit" if self.record else "create")
        if self.is_return:
            allowed = allowed and can_action(self.store.actor, resource, "delete")
        self.draft_button.setEnabled(allowed)
        self.post_button.setEnabled(allowed)
        self.close_button = action("닫기", self.reject)
        self._sy_close_button=self.close_button
        for button in (self.draft_button, self.post_button):
            button.setAutoDefault(False)
            footer.addWidget(button)
        if kind.startswith('purchase'):
            footer_row=QHBoxLayout();footer_row.addWidget(_compact_scroll_row(footer,50),1);footer_row.addWidget(self.close_button)
            body.addLayout(footer_row)
        else:footer.addWidget(self.close_button);body.addLayout(footer)
        self.shortcut_scan = QShortcut(QKeySequence(scan_key), self)
        self.shortcut_scan.activated.connect(self.focus_scan)
        self.shortcut_product = QShortcut(QKeySequence("F5"), self)
        self.shortcut_product.activated.connect(self.pick_product)
        self.shortcut_delete = QShortcut(QKeySequence("F7"), self)
        self.shortcut_delete.activated.connect(self.remove_selected_line)
        if kind.startswith("purchase"):
            self.shortcut_supplier = QShortcut(QKeySequence("F3"), self)
            self.shortcut_supplier.activated.connect(lambda: self.pick_partner("supplier") if self.pick_button.isEnabled() else None)
            self.shortcut_edit = QShortcut(QKeySequence("F6"), self)
            self.shortcut_edit.activated.connect(self.edit_selected_line)
            self.shortcut_new_product = QShortcut(QKeySequence("F9"), self)
            self.shortcut_new_product.activated.connect(self.new_product)
            self.purchase_shortcuts=[]
            for sequence,callback in (('F8',self.product_info),('F11',self.tax_info),('Alt+P',self.payment_input),
                    ('Alt+Up',lambda:self.move_line(-1)),('Alt+Down',lambda:self.move_line(1)),('Ctrl+I',self.bulk_edit_lines),
                    ('Ctrl+E',self.export_document),('Ctrl+P',self.print_button.showMenu),('Ctrl+Shift+S',lambda:self.purchase_output('pdf'))):
                shortcut=QShortcut(QKeySequence(sequence),self);shortcut.activated.connect(callback);self.purchase_shortcuts.append(shortcut)
            self.shortcut_apply = QShortcut(QKeySequence("Alt+A"), self)
            self.shortcut_apply.activated.connect(lambda: self.save(False, False))
            self.shortcut_save = QShortcut(QKeySequence("Alt+S"), self)
            self.shortcut_save.activated.connect(lambda: self.save(True))
        lines = (self.record or {}).get("lines") or (self.source or {}).get("lines") or []
        source_lines = self.source or (self.store.document(self.record["source_id"]) if self.is_return and self.record and self.record.get("source_id") else {})
        source_map = {line["id"]: line for line in source_lines.get("lines", [])}
        self._batch_lines = True
        for line in lines:
            if self.source and Decimal(str(line.get("remaining_qty", line["input_qty"]))) <= 0:
                continue
            source_line = line if self.source else None
            if self.is_return and self.record and line.get("source_line_id"):
                source_line = source_map.get(line["source_line_id"], {**line, "id": line["source_line_id"]})
            unit_id = line.get('unit_id')
            product = self.product_map.get(line['product_id'], {})
            if not unit_id and line.get('unit_name') == 'g' and product.get('base_unit') == 'kg':
                unit_id = 'grams'
            row = self.add_line(line["product_id"], unit_id, "0" if self.source else line["input_qty"], line["unit_price"], source_line)
            if self.record:
                row["saved_line"] = line
        if not lines and not self.readonly:
            self.add_line()
        self._batch_lines = False
        if self.readonly:
            for widget in (self.date, self.partner, self.pick_button, self.member, self.scan, self.add_button, self.search_button, self.quote_button, self.paid, self.method, self.points, self.memo):
                widget.setEnabled(False)
            for row in self.line_rows:
                for widget in row.values():
                    if isinstance(widget, QWidget):
                        widget.setEnabled(False)
            self.draft_button.hide()
            self.post_button.hide()
        if self.is_return:
            self.partner.setEnabled(False)
            self.member.setEnabled(False)
            self.pick_button.setEnabled(False)
            self.add_button.setEnabled(False)
            self.search_button.setEnabled(False)
            self.scan.setEnabled(False)
            self.quote_button.setEnabled(False)
        self.print_button.setEnabled(kind.startswith('purchase') or bool(self.record))
        self.void_button.setEnabled(bool(self.record and self.record["status"] == "posted"))
        if kind.startswith('purchase'):
            # One direct payment manager, not a second cancellation path that
            # would bypass the manual's same-day supplier-payment rule.
            self.void_button.hide()
            self.payments_grid.itemDoubleClicked.connect(self.payment_input)
        self.refresh_payments()
        self.recalculate()

    def switch_purchase_mode(self, checked):
        if self.record or self.readonly:
            return
        source = None
        if checked:
            try:
                self.store._require_capability("purchases", "delete")
            except PermissionError as exc:
                _warn(self, exc)
                self.return_mode.blockSignals(True)
                self.return_mode.setChecked(False)
                self.return_mode.blockSignals(False)
                return
            picker = PurchaseSourcePicker(self.window, self.partner.currentData())
            if picker.exec() != QDialog.DialogCode.Accepted:
                self.return_mode.blockSignals(True)
                self.return_mode.setChecked(False)
                self.return_mode.blockSignals(False)
                return
            source = picker.record
        if any(row["product"].currentData() for row in self.line_rows):
            if not _confirm(self, "전표 구분 변경", "입력한 품목을 비우고 전표 구분을 변경할까요?"):
                self.return_mode.blockSignals(True)
                self.return_mode.setChecked(not checked)
                self.return_mode.blockSignals(False)
                return
        self.line_rows.clear()
        self.table.setRowCount(0)
        self.source, self.is_return = source, checked
        self.kind = "purchase_return" if checked else "purchase"
        self.heading.setText("반품전표" if checked else "매입전표")
        self.setWindowTitle("새 반품전표" if checked else "새 매입전표")
        self.source_label.setText(f"원전표 {source['number']} · 반품수량 입력" if checked else "매입 · 반품 체크 시 원전표 선택")
        self.paid.setText("0")
        self.paid_caption.setText("환불금액" if checked else "결제금액")
        for control in (self.partner, self.pick_button, self.add_button, self.search_button, self.scan, self.quote_button):
            control.setEnabled(not checked)
        from .permissions import can_action
        self.new_product_button.setEnabled(not checked and can_action(self.store.actor, "products", "create"))
        from .permissions import has_menu
        self.catalog_button.setEnabled(not checked and has_menu(self.store.actor,"products"))
        if source:
            self.partner.setCurrentIndex(self.partner.findData(source["partner_id"]))
            for line in source["lines"]:
                if Decimal(str(line["remaining_qty"])) > 0:
                    self.add_line(line["product_id"], line.get("unit_id"), "0", line["unit_price"], line)
        else:
            self.add_line()
        self.recalculate()

    def edit_selected_line(self):
        if self.readonly:
            return
        index = self.table.currentRow()
        if self.line_rows:
            index = max(0, index)
            self.table.setCurrentCell(index, 3)
            self.line_rows[index]["qty"].setFocus()
            self.line_rows[index]["qty"].selectAll()

    def move_line(self,direction):
        if self.readonly:return
        index=self.table.currentRow();target=index+direction
        if not 0<=index<len(self.line_rows) or not 0<=target<len(self.line_rows):return
        def snapshot(row):
            return dict(product=row['product'].currentData(),unit=row['unit'].currentData(),quantity=row['qty'].text(),
                price=row['price'].text(),source=row.get('source'),saved_line=row.get('saved_line'))
        before=[snapshot(self.line_rows[position]) for position in (index,target)]
        self._batch_lines=True
        try:
            for position,data in zip((index,target),reversed(before)):
                row=self.line_rows[position]
                row['source']=data['source']
                if data['saved_line'] is None:row.pop('saved_line',None)
                else:row['saved_line']=data['saved_line']
                row['product'].setCurrentIndex(row['product'].findData(data['product']))
                self.product_changed(row)
                row['unit'].setCurrentIndex(max(0,row['unit'].findData(data['unit'])))
                row['qty'].setText(data['quantity']);row['price'].setText(data['price'])
                row['product'].setEnabled(not bool(data['source']));row['unit'].setEnabled(not bool(data['source']))
                row['price'].setReadOnly(bool(data['source']))
                if data['source']:row['stock'].setText('최대 '+amount(data['source'].get('remaining_qty',data['source']['input_qty'])))
        finally:self._batch_lines=False
        self.recalculate();self.table.setCurrentCell(target,3)

    def bulk_edit_lines(self):
        if self.readonly:return
        PurchaseBatchDialog(self).exec()

    def product_info(self):
        index=self.table.currentRow()
        if not self.line_rows:return
        row=self.line_rows[max(0,index)];identifier=row['product'].currentData()
        if not identifier:return _warn(self,'상품을 먼저 선택하세요.')
        try:
            product=self.store.catalog_product(identifier)
            path=' / '.join(product.get(key,'') for key in ('category','category_mid','category_small'))
            rows=[[label,product.get(key,'')] for label,key in (('상품코드','code'),('상품명','name'),('바코드','barcode'),('규격','specification'),('기본단위','base_unit'),('매입단가','purchase_price'),('판매단가','sale_price'))]
            rows+=[['과면세','과 · 과세' if product['tax_mode']=='taxable' else '면 · 면세'],['대/중/소분류',path],['현재고',product['stock_qty']],['재고관리','대상' if product['tracked'] else '대상 아님']]
            TradeDetailDialog(self,'상품정보',['항목','내용'],rows,'현재 상품 등록정보입니다. 저장된 과거 전표의 품명·단가·과면세는 변경하지 않습니다.').exec()
        except (ValueError,PermissionError) as exc:_warn(self,exc)

    def tax_info(self):
        self.recalculate();rows=[]
        for row in self.line_rows:
            identifier=row['product'].currentData()
            if not identifier:continue
            snapshot=(row.get('saved_line') if self.readonly else None) or row.get('source') or self.product_map[identifier]
            rows.append([snapshot.get('product_name',self.product_map[identifier]['name']),
                '과 · 과세' if snapshot['tax_mode']=='taxable' else '면 · 면세',row['total'].text()])
        TradeDetailDialog(self,'과면세 정보',['상품명','과면세','매입금액'],rows,self.tax_label.text()).exec()

    def payment_input(self, *_):
        if self.record and self.record['status']=='posted' and self.kind=='purchase':
            from .purchase_payment_ui import open_payment
            try:
                if open_payment(self.window, self.record['id'], self):
                    self.record = self.store.document(self.record['id'])
                    self.saved_id = self.record['id']
                    self.paid.setText(str(self.record['cash_paid']))
                    self.refresh_payments()
                    self.recalculate()
                    from .navigation import mark_saved
                    mark_saved(self)
            except (ValueError, PermissionError) as exc:_warn(self, exc)
            return
        if self.readonly:return
        self.recalculate()
        dialog=QDialog(self);dialog.setWindowTitle('매입 결제 입력');dialog._sy_no_home_button=True
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel('입력값만 전표에 적용합니다. 실제 결제 기록은 전표 저장 시 반영됩니다.'))
        form=QFormLayout();paid=QLineEdit(self.paid.text());method=QComboBox()
        method.addItem('현금','cash');method.addItem('계좌이체','transfer');method.addItem('카드 수기','card');method.setCurrentIndex(max(0,method.findData(self.method.currentData())))
        form.addRow('환불금액' if self.is_return else '결제금액',paid);form.addRow('결제방법',method);layout.addLayout(form)
        def apply():
            try:
                value=money(paid.text());total=sum((money(row['total'].text()) for row in self.line_rows if row['product'].currentData()),Decimal(0))
                if value>total:raise ValueError('결제금액은 전표 합계 이내로 입력하세요.')
                self.paid.setText(str(value));self.method.setCurrentIndex(self.method.findData(method.currentData()));dialog.accept()
            except ValueError as exc:_warn(dialog,exc)
        buttons=QHBoxLayout();buttons.addWidget(action('적용',apply,True));dialog._sy_close_button=action('닫기',dialog.reject);buttons.addWidget(dialog._sy_close_button);layout.addLayout(buttons)
        dialog.exec()

    def new_product(self):
        if self.readonly or self.is_return:
            return
        try:
            self.store._require_capability("products", "create")
            from .catalog_ui import ProductDialog
            dialog = ProductDialog(self.store, parent=self)
            dialog.supplier.setCurrentIndex(max(0, dialog.supplier.findData(self.partner.currentData())))
            dialog.saved.connect(self.apply_master_product)
            dialog.exec()
        except (ValueError, PermissionError) as exc:
            _warn(self, exc)

    def open_catalog(self):
        if self.readonly or self.is_return:
            return
        try:
            self.store.require_menu("products")
            ProductCatalogDialog(self).exec()
        except (ValueError, PermissionError) as exc:
            _warn(self, exc)

    def apply_master_product(self, identifier):
        self.store.require_menu("products")
        if self.readonly or self.is_return:
            return False
        product = self.store.catalog_product(identifier)
        if not product['active']:
            product = None
        if not product:
            raise ValueError("유효한 상품을 다시 선택하세요.")
        self.product_map[identifier] = product
        self.products = [row for row in self.products if row["id"] != identifier] + [product]
        self.product_model.ensure(product)
        row = next((row for row in self.line_rows if row["product"].currentData() == identifier), None)
        if row is None:
            row = self.add_line(identifier, quantity="0" if product["base_unit"] == "g" else "1")
        self.table.setCurrentCell(self.line_rows.index(row), 3)
        row["qty"].setFocus()
        row["qty"].selectAll()
        return True

    def update_partner_info(self, *_):
        party = self.party_map.get(self.partner.currentData(), {})
        mode = "수수료 공급사" if party.get("supplier_mode") == "commission" else "직매입" if self.kind.startswith("purchase") else "판매"
        self.partner_info.setText(f"사업자번호 {party.get('business_no') or '미등록'}  ·  {mode}  ·  부가세 포함 단가  ·  담당자 {(self.store.actor or {}).get('name', '')}")

    def focus_scan(self):
        if self.scan.isEnabled():
            self.scan.setFocus()
            self.scan.selectAll()

    def pick_partner(self, kind):
        picker = PartnerPicker(self, kind)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.partner.setCurrentIndex(self.partner.findData(picker.selected_record["id"]))

    def add_line(self, product_id=None, unit_id=None, quantity="1", price=None, source_line=None):
        if isinstance(product_id, bool):
            product_id = None
        if product_id in self.product_map:
            self.product_model.ensure(self.product_map[product_id])
        row = {"source": source_line}
        from .trade_product_model import TradeProductCombo
        product = row["product"] = TradeProductCombo(self.product_model)
        unit = row["unit"] = QComboBox()
        row["qty"], row["price"] = QLineEdit(str(quantity)), QLineEdit("0" if price is None else str(price))
        row["total"], row["stock"] = QLabel(), QLabel()
        for key in ("spec", "barcode", "factor", "base_qty", "sale_price", "margin", "category", "supplier"):
            row[key] = QLabel()
            row[key].setMargin(5)
        for key in ("qty", "price"):
            row[key].setAlignment(Qt.AlignmentFlag.AlignRight)
        row["total"].setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row["total"].setMargin(5)
        row["delete"] = action("×", lambda: self.remove_line(row))
        # A decorative icon plus ordinary button padding hides the cross in
        # the compact delete column. Keep a clear, named single-symbol action.
        row["delete"].setIcon(QIcon())
        row["delete"].setStyleSheet('padding:4px;')
        row["delete"].setAccessibleName('이 품목 삭제')
        row["delete"].setToolTip('이 품목을 전표 입력 목록에서 삭제합니다. 전표 확정 전까지 재고는 바뀌지 않습니다.')
        self.line_rows.append(row)
        self.table.setRowCount(len(self.line_rows))
        index = len(self.line_rows) - 1
        for column, key in enumerate(self.line_columns):
            self.table.setCellWidget(index, column, row[key])
        product.currentIndexChanged.connect(lambda _=0: self.product_changed(row))
        unit.currentIndexChanged.connect(lambda _=0: self.unit_changed(row))
        row["qty"].textChanged.connect(self.recalculate)
        row["price"].textChanged.connect(self.recalculate)
        product.setCurrentIndex(max(0, product.findData(product_id)))
        if product_id:
            if unit_id and unit.findData(unit_id) < 0:
                historical = next((u for u in self.store.units(product_id) if u["id"] == unit_id), None)
                if historical:
                    unit.addItem(f"{historical['name']} (이력 단위)", unit_id)
            unit.setCurrentIndex(max(0, unit.findData(unit_id)))
        if price is not None:
            row["price"].setText(str(price))
        if source_line or self.readonly:
            product.setEnabled(False)
            unit.setEnabled(False)
        if source_line:
            row["price"].setReadOnly(True)
            row["stock"].setText(f"최대 {amount(source_line.get('remaining_qty', source_line['input_qty']))}")
        self.recalculate()
        return row

    def product_changed(self, row):
        identifier = row["product"].currentData()
        row["unit"].blockSignals(True)
        row["unit"].clear()
        product = self.product_map.get(identifier)
        if product:
            row["unit"].addItem("g (100g당)" if product["base_unit"] == "g" and product.get("price_basis") == 100 else product["base_unit"], None)
            if product["base_unit"] == "kg":
                row["unit"].addItem("g (100g당 · kg 환산)", "grams")
            row["units"] = {u["id"]: u for u in self.store.units(identifier)}
            for unit in row["units"].values():
                if unit.get("active", True):
                    row["unit"].addItem(f"{unit['name']} (×{amount(unit['factor'])})", unit["id"])
            row["stock"].setText(f"{amount(product['stock_qty'])} {product['base_unit']}" if product.get("tracked", True) else "재고 미관리")
            row['stock'].setStyleSheet('color:#B42318;font-weight:700' if Decimal(str(product['stock_qty']))<0 else '')
            row["spec"].setText(product["specification"])
            row["category"].setText(" / ".join(filter(None, (product["category"], product["category_mid"], product["category_small"]))))
            row["supplier"].setText(product.get("supplier_name") or "미지정")
            for key in ('stock','spec','category','supplier'):
                row[key].setToolTip(row[key].text())
        else:
            row["units"] = {}
            for key in ("spec", "barcode", "factor", "base_qty", "sale_price", "margin", "category", "supplier", "stock"):
                row[key].clear()
                row[key].setToolTip('')
        row["unit"].blockSignals(False)
        if identifier:
            self.unit_changed(row)
        else:
            self.recalculate()

    def pick_product(self):
        if self.readonly or self.is_return:
            return
        dialog = ProductPicker(self)
        dialog.set_apply_callback(self.apply_picked_products)
        if dialog.exec() == QDialog.DialogCode.Accepted and not dialog.applied_batches:
            self.apply_picked_products(dialog.selections or [(dialog.record, dialog.unit_id)])

    def apply_picked_products(self, selections):
        if self.readonly or self.is_return:return
        if sum(bool(r['product'].currentData()) for r in self.line_rows) + sum(bool(record) for record, _ in selections) > 2000:
            raise ValueError('매입전표 한 건은 최대 2,000개 품목입니다. 별도 전표로 나눠 추가하세요.')
        self._batch_lines = True
        self.table.setUpdatesEnabled(False)
        try:
            for record, unit_id in selections:
                if not record:
                    continue
                if record['id'] not in self.product_map:
                    self.products.append(record)
                self.product_map[record["id"]] = record
                self.product_model.ensure(record)
                row = next((r for r in self.line_rows if not r["product"].currentData()), None)
                if row is None:
                    row = self.add_line(record["id"], unit_id)
                else:
                    row["product"].setCurrentIndex(row["product"].findData(record["id"]))
                    row["unit"].setCurrentIndex(max(0, row["unit"].findData(unit_id)))
                self.table.setCurrentCell(self.line_rows.index(row), 3)
        finally:
            self._batch_lines = False
            self.table.setUpdatesEnabled(True)
        self.recalculate()

    def unit_changed(self, row):
        identifier = row["product"].currentData()
        if not identifier:
            return
        product = self.product_map[identifier]
        unit = row.get("units", {}).get(row["unit"].currentData()) or {}
        gram_input = row["unit"].currentData() == "grams"
        row["unit"].setToolTip(row["unit"].currentText())
        row["price_basis"] = (row.get("source") or {}).get("price_basis", 100 if gram_input else 1 if unit else product.get("price_basis", 1))
        row["barcode"].setText(unit.get("barcode") or product["barcode"])
        row["factor"].setText(amount((row.get("source") or {}).get("factor", "0.001" if gram_input else unit.get("factor", "1"))))
        row["reference_sale"] = unit.get("sale_price", product["sale_price"])
        if gram_input:
            row['reference_sale'] = rounded(row['reference_sale'] / 10)
        row["sale_price"].setText(won(row["reference_sale"]))
        if not row.get("source") and not self.readonly:
            quote = self.store.quote(identifier, _date(self.date), None if gram_input else row["unit"].currentData(), self.member.currentData())
            if gram_input:
                quote = {**quote, "price": rounded(quote["price"] / 10), "purchase_price": rounded(quote["purchase_price"] / 10)}
            row["reference_sale"] = quote["price"]
            row["sale_price"].setText(won(quote["price"]))
            row["price"].setText(str(quote["purchase_price"] if self.kind.startswith("purchase") else quote["price"]))
        self.recalculate()

    def remove_selected_line(self):
        index = self.table.currentRow()
        if not self.readonly and 0 <= index < len(self.line_rows):
            self.remove_line(self.line_rows[index])

    def remove_line(self, row):
        if self.readonly:
            return
        index = self.line_rows.index(row)
        self.line_rows.pop(index)
        self.table.removeRow(index)
        self.recalculate()

    def scan_barcode(self, barcode):
        if self.readonly or self.is_return:
            return
        try:
            found = self.store.lookup_barcode(barcode.strip())
            if not found:
                raise ValueError("등록되지 않은 바코드입니다. 상품 등록에서 먼저 확인하세요.")
            product_id = found["product"]["id"]
            product = found['product']
            if product_id not in self.product_map:
                self.products.append(product)
            self.product_map[product_id] = product
            self.product_model.ensure(product)
            unit_id = found["unit"]["id"] if found.get("unit") else None
            for row in self.line_rows:
                if row["product"].currentData() == product_id and row["unit"].currentData() == unit_id:
                    row["qty"].setText(str(Decimal(row["qty"].text()) + 1))
                    break
            else:
                empty = next((row for row in self.line_rows if not row["product"].currentData()), None)
                if empty:
                    empty["product"].setCurrentIndex(empty["product"].findData(product_id))
                    empty["unit"].setCurrentIndex(empty["unit"].findData(unit_id))
                    empty["qty"].setText("1")
                else:
                    self.add_line(product_id, unit_id)
            self.scan.clear()
            self.focus_scan()
        except (ValueError, PermissionError, InvalidOperation) as exc:
            _warn(self, exc)
            self.scan.selectAll()

    def apply_quotes(self):
        if not _confirm(self, "제안가 적용", "입력한 단가를 선택 날짜·회원의 제안가로 바꿀까요? 날짜 변경만으로 단가는 바뀌지 않습니다."):
            return
        try:
            for row in self.line_rows:
                self.unit_changed(row)
        except (ValueError, PermissionError) as exc:
            _warn(self, exc)

    def recalculate(self, *_):
        if self._batch_lines:
            return
        total = taxable = exempt = estimated_sale = 0
        quantities, invalid = {}, False
        for row in self.line_rows:
            identifier = row["product"].currentData()
            if not identifier:
                row["total"].setText("—")
                continue
            try:
                product = self.product_map[identifier]
                quantity = Decimal(qty(row["qty"].text() or "0", allow_zero=True)) / 1000
                price = money(row["price"].text() or "0")
                unit = row.get("units", {}).get(row["unit"].currentData()) or {}
                saved = row.get("saved_line") if self.readonly else None
                original = row.get("source")
                snapshot = saved or original or {}
                factor = value_decimal(snapshot.get("factor", "0.001" if row["unit"].currentData() == "grams" else unit.get("factor", "1")))
                base_qty = quantity * factor
                row["factor"].setText(amount(factor))
                row["base_qty"].setText(f"{amount(base_qty)} {product['base_unit']}")
                if saved:
                    value = saved["total"]
                elif original:
                    before = value_decimal(original.get("returned_qty", "0"))
                    denominator = value_decimal(original["input_qty"])
                    value = rounded(Decimal(original["total"]) * (before + quantity) / denominator) - rounded(Decimal(original["total"]) * before / denominator)
                else:
                    value = rounded(quantity * price / row.get("price_basis", 1), self.rounding_mode)
                row["total"].setText(won(value))
                sale = rounded(quantity * row.get("reference_sale", product["sale_price"]) / row.get("price_basis", 1), self.rounding_mode)
                row["margin"].setText(f"{(Decimal(sale - value) * 100 / sale):.2f}%" if sale else "—")
                row["margin"].setToolTip("현재 판매가 기준 참고 이익률입니다. 확정 매출의 실제 이익이 아닙니다.")
                total += value
                estimated_sale += sale
                if snapshot.get("tax_mode", product["tax_mode"]) == "taxable":
                    taxable += value
                else:
                    exempt += value
                quantities[product["base_unit"]] = quantities.get(product["base_unit"], Decimal(0)) + base_qty
            except (InvalidOperation, ValueError, OverflowError):
                invalid = True
                row["total"].setText("입력 확인")
        if hasattr(self, "total_label"):
            self.total_label.setText(f"{'매입합계' if self.kind.startswith('purchase') else '합계'} {won(total)}원")
            vat = rounded(Decimal(taxable) / 11)
            self.tax_label.setText(f"과세 공급가 {won(taxable - vat)}원 · 면세 {won(exempt)}원\n부가세 {won(vat)}원 (포함, 참고)")
            self.quantity_label.setText("총수량  " + (" · ".join(f"{amount(value)} {key}" for key, value in sorted(quantities.items())) or "0"))
            self.estimate_label.setText(f"현재 판매가 기준 참고\n예상판매액 {won(estimated_sale)}원 · 차액 {won(estimated_sale - total)}원")
        if not hasattr(self, "balance_label"):
            return
        try:
            paid = money(self.paid.text() or "0")
            points = money(self.points.text() or "0") if self.kind == "sale" else 0
            if invalid:
                raise ValueError("품목 입력을 확인하세요.")
            if self.readonly:
                balance = self.record["balance"]
            else:
                if paid + points > total:
                    raise ValueError("결제금액이 전표 금액을 초과했습니다.")
                balance = total - paid - points
            label = "미환불잔액" if self.is_return else "미지급잔액" if self.kind.startswith("purchase") else "미수잔액"
            if self.is_return and not self.readonly:
                label = "반품액 − 입력환불액 (외상 차감 전)"
            preview = " (초안 예상)" if not self.readonly else ""
            self.balance_label.setText(f"{label}  {won(balance)}원{preview}")
            self.balance_label.setStyleSheet("color: #B35339;" if balance else "color: #16705A;")
            state = "미결제" if not paid and balance else "부분결제" if balance else "결제완료"
            if not total:
                state = "입력 대기"
            if self.readonly and not self.is_return and total and not balance and paid + points < total:
                state = "정산완료 (반품 반영)"
            if self.is_return:
                state = "확정 시 원전표 외상과 정산" if not self.readonly else "환불 대기" if balance else "정산완료"
            if self.record and self.record["status"] == "cancelled":
                state = "취소된 전표"
            if not self.readonly and state == "결제완료":
                state = "입력상 결제완료 · 확정 전"
            self.payment_status.setText(state)
            self.balance_label.setToolTip("이 전표의 잔액입니다. 확정 전표는 실제 결제·반품을 반영하며, 거래처 전체 잔액은 원장에서 확인합니다.")
        except (ValueError, InvalidOperation, OverflowError) as exc:
            self.balance_label.setText("잔액 계산: 입력을 확인하세요.")
            self.payment_status.setText(str(exc))

    def payload(self):
        lines = []
        for row in self.line_rows:
            product_id = row["product"].currentData()
            if not product_id:
                continue
            quantity = row["qty"].text().strip()
            if self.is_return and value_decimal(quantity or "0") == 0:
                continue
            lines.append({"product_id": product_id, "unit_id": None if row["unit"].currentData() == "grams" else row["unit"].currentData(), "gram_input": row["unit"].currentData() == "grams", "qty": quantity, "unit_price": row["price"].text().strip(), "source_line_id": row["source"]["id"] if row.get("source") else None})
        return {"kind": self.kind, "date": _date(self.date), "partner_id": self.partner.currentData(), "member_id": self.member.currentData(), "source_id": (self.source or self.record or {}).get("id") if self.source else (self.record or {}).get("source_id"), "lines": lines, "paid": self.paid.text(), "method": self.method.currentData(), "points_used": self.points.text() if self.kind == "sale" else 0, "memo": self.memo.text(),"rounding_mode":self.rounding_mode}

    def save(self, post, close=True):
        if self.readonly:
            return
        try:
            data = self.payload()
            data['_expected_token']=(self.record or {}).get('_edit_token')
            data["rounding_mode"] = self.rounding_mode
            if not data["partner_id"]:
                raise ValueError("거래처를 선택하세요.")
            if post and not _confirm(self, "전표 확정", "재고·결제·포인트에 반영합니다. 확정할까요?"):
                return
            identifier = self.record["id"] if self.record else None
            self.saved_id = self.store.post_document(data, identifier) if post else self.store.save_draft(data, identifier)
            from .navigation import mark_saved
            mark_saved(self)
            if close:
                self.accept()
            else:
                self.record = self.store.document(self.saved_id)
                self.return_mode.setEnabled(False)
                mark_saved(self)
                self.explanation.setText("전표를 초안으로 저장했습니다. 계속 입력하거나 ‘저장’을 눌러 재고·결제에 반영하세요.")
        except (ValueError, PermissionError, InvalidOperation) as exc:
            _warn(self, exc)

    def print_document(self):
        if self.kind.startswith('purchase'):return self.purchase_output('preview')
        if not self.record:
            return
        record = self.store.document(self.record["id"])
        grid = DataGrid(["상품", "단위", "수량", "단가", "금액"])
        grid.fill([[line["product_name"], line["unit_name"], Decimal(line["input_qty"]), line["unit_price"], line["total"]] for line in record["lines"]])
        info = f"{record['number']} · {record['date']} · {record.get('partner_name', '')}\n합계 {won(record['total'])}원 · 결제 {won(record.get('cash_paid', 0))}원 · 포인트 {won(record.get('points_used', 0))} · 잔액 {won(record['balance'])}원 · {STATUSES[record['status']]}"
        grid.print_pages(self, KINDS[self.kind] + " 전표", info)
        grid.deleteLater()

    def export_document(self):
        if self.kind.startswith('purchase'):return self.purchase_output('xlsx')
        from .widgets import export_rows, authorize_output
        if not authorize_output(self):
            return
        try:
            if self.readonly:
                record = self.store.document(self.record["id"])
                rows = [[record["number"], record["date"], record["partner_name"], STATUSES[record["status"]], line["product_name"], line["unit_name"], Decimal(line["input_qty"]), line["unit_price"], line["total"]] for line in record["lines"]]
            else:
                self.recalculate()
                rows = [["미확정 입력", _date(self.date), self.partner.currentText(), "미확정", self.product_map[row["product"].currentData()]["name"], row["unit"].currentText(), value_decimal(row["qty"].text()), money(row["price"].text()), money(row["total"].text())] for row in self.line_rows if row["product"].currentData()]
            export_rows(self, KINDS[self.kind] + " 전표", ["전표번호", "거래일", "거래처", "상태", "상품명", "단위", "수량", "단가", "금액"], rows)
        except (ValueError, PermissionError, InvalidOperation) as exc:
            _warn(self, exc)

    def print_grid(self):
        return self.purchase_output('grid')

    def purchase_output(self,mode):
        from .purchase_output import output_purchase
        try:return output_purchase(self,mode)
        except (ValueError,PermissionError,InvalidOperation,OSError) as exc:_warn(self,exc)

    def refresh_payments(self):
        payments = (self.record or {}).get("payments", [])
        self.payments_grid.fill([[p["id"], p["date"], p["amount"], {'cash':'현금','transfer':'계좌이체','card':'카드 수기'}.get(p['method'],p['method']), p.get("user_name", ""), "취소" if p["voided"] else "유효", p.get("memo", "")] for p in payments], payments)

    def void_payment(self):
        payment = self.payments_grid.selected()
        if not payment:
            return _warn(self, "취소할 결제 이력을 선택하세요.")
        reason, accepted = QInputDialog.getText(self, "결제 취소", "취소 사유")
        if accepted and _confirm(self, "결제 취소", "선택한 실제 입출금 반영을 취소할까요? 마감되었거나 반품이 연결되면 거부됩니다."):
            try:
                self.store.void_payment(payment["id"], reason)
                self.record = self.store.document(self.record["id"])
                self.saved_id = self.record["id"]
                self.paid.setText(str(self.record["cash_paid"]))
                self.refresh_payments()
            except (ValueError, PermissionError) as exc:
                _warn(self, exc)


class ProductCatalogDialog(QDialog):
    def __init__(self, trade):
        super().__init__(trade)
        self.trade, self.store = trade, trade.store
        self.setWindowTitle("상품장 · 매입전표 품목 적용")
        self.resize(1250, 790)
        from .catalog_ui import ProductsPage
        from types import SimpleNamespace
        self.initial_ids = {row["id"] for row in self.store.products()}
        body = QVBoxLayout(self)
        self.note = QLabel("상품장에서 새 상품을 등록하거나 기존 상품을 선택해 작성 중인 매입전표에 적용하세요. 전표는 자동 확정하지 않습니다.")
        self.note.setWordWrap(True)
        body.addWidget(self.note)
        self.page = ProductsPage(SimpleNamespace(store=self.store, notify=self.note.setText))
        body.addWidget(self.page, 1)
        self.auto_apply = QCheckBox("새 상품 저장 후 매입전표에 바로 적용")
        self.auto_apply.setChecked(True)
        body.addWidget(self.auto_apply)
        controls = QHBoxLayout()
        controls.addWidget(action("선택 상품 매입전표에 적용", self.apply_selected, True))
        controls.addWidget(action("닫기", self.reject))
        body.addLayout(controls)
        self.page.product_saved.connect(self.product_saved)

    def product_saved(self, identifier):
        if identifier not in self.initial_ids and self.auto_apply.isChecked():
            try:
                self.trade.apply_master_product(identifier)
                self.note.setText("새 상품을 매입전표 품목으로 적용했습니다. 전표로 돌아가 g 수량·단가를 입력하고 저장하세요.")
            except (ValueError, PermissionError) as exc:
                self.note.setText(str(exc))
        self.initial_ids.add(identifier)

    def apply_selected(self):
        try:
            self.store.require_menu("products")
            ids = self.page.selected_product_ids()
            for identifier in ids:
                self.trade.apply_master_product(identifier)
            self.note.setText(f"{len(ids):,}개 상품을 매입전표에 적용했습니다. 전표는 아직 확정하지 않았습니다.")
        except (ValueError, PermissionError) as exc:
            self.note.setText(str(exc))


class PurchaseJournalCell(Cell):
    SUMMARY_ROLE=Qt.ItemDataRole.UserRole+20
    def __lt__(self,other):
        own,opposite=bool(self.data(self.SUMMARY_ROLE)),bool(other.data(self.SUMMARY_ROLE))
        if own!=opposite:
            table=self.tableWidget()
            descending=table and table.horizontalHeader().sortIndicatorOrder()==Qt.SortOrder.DescendingOrder
            return own if descending else not own
        return super().__lt__(other)


class PurchaseJournalGrid(DataGrid):
    cell_type=PurchaseJournalCell
    def __init__(self,headers):
        super().__init__(headers)
        self.verticalHeader().hide()
        self.horizontalHeader().setMinimumSectionSize(36)
        self.setStyleSheet('QTableWidget{background:#A7ABA8;} QTableWidget::item:selected{background:#176CB0;color:white;}')

    def fill(self,rows,records=None):
        super().fill(rows,records)
        self.setSortingEnabled(False)
        for index in range(self.rowCount()):
            summary=self.item(index,0).data(Qt.ItemDataRole.UserRole) is None
            for column in range(self.columnCount()):
                item=self.item(index,column)
                item.setData(PurchaseJournalCell.SUMMARY_ROLE,summary)
                item.setBackground(QColor('#DDE2DC' if summary else '#EAD5D3' if column in (6,7,8) else '#D9DEBF' if column in (0,1,2,3) else '#E1E6CC' if column==4 else '#E8EDDF' if index%2==0 else '#DEE7D8'))
                if summary:item.setForeground(QColor('#2258A0'))
                elif column==4:
                    item.setForeground(QColor('#24538D'));item.setToolTip(item.toolTip()+'\n더블클릭하면 이 매입전표를 엽니다.')
                elif column==10 and item.text():
                    item.setText(item.text().replace('T',' ')[:16])
                if summary or column==6:
                    font=item.font();font.setBold(True);item.setFont(font)
            if not summary:
                from .menu_icons import menu_icon
                self.item(index,1).setIcon(menu_icon('purchases'))
        self.setSortingEnabled(True)


class TradesPage(Page):
    def __init__(self, window, kind="purchase"):
        self.kind = kind
        super().__init__(window, "매입전표" if kind == "purchase" else "매출장", "매입등록 → 공급사 → 상품·수량·매입가 → 저장. 반품은 전표 창의 ‘반품’에 체크합니다." if kind == "purchase" else "기간과 거래처를 선택해 전표를 조회합니다.")
        self.new_button=action("매입등록" if kind == "purchase" else "매출등록", self.new_trade, True)
        if kind!='purchase':self.actions.addWidget(self.new_button)
        if kind == 'purchase':
            self.import_button=action('매입 엑셀 불러오기', self.import_excel)
        filters = QHBoxLayout()
        self.start, self.end = _dates(filters, self.refresh)
        self.status = QComboBox()
        self.status.addItem("전체 상태", "")
        for key, value in STATUSES.items():
            self.status.addItem(value, key)
        self.search = QLineEdit()
        self.search.setPlaceholderText("전표번호 · 거래처 · 메모")
        self.partner_filter = QComboBox()
        self.partner_filter.addItem("전체 공급사" if kind == "purchase" else "전체 판매처", None)
        party_kind = "supplier" if kind == "purchase" else "customer"
        for party in self.store.trade_partners(party_kind,include_inactive=True):
            self.partner_filter.addItem(f"{party['code']} · {party['name']}", party["id"])
        self.partner_filter.setMinimumWidth(145)
        self.partner_lookup = action("거래처 검색", self.pick_filter_partner)
        self.partner_lookup.setIcon(search_icon())
        if kind=='purchase':
            self.partner_lookup.setText('');self.partner_lookup.setAccessibleName('공급사 검색')
            self.partner_lookup.setFixedWidth(36)
            self.partner_lookup.setToolTip('공급사명·코드로 검색해 조회할 공급사를 선택합니다.')
            lookup=QWidget();lookup_row=QHBoxLayout(lookup);lookup_row.setContentsMargins(0,0,0,0);lookup_row.setSpacing(3)
            self.header.left_layout.removeWidget(self.header.context)
            lookup_row.addWidget(self.header.context,1)
            self.partner_filter.setMaximumWidth(210)
            lookup_row.addWidget(self.partner_filter,1);lookup_row.addWidget(self.partner_lookup)
            self.header.description.hide();self.header.left_layout.setSpacing(0);self.header.left_layout.addWidget(lookup)
        self.returns = QCheckBox("반품 포함")
        self.returns.setChecked(True)
        self.type_filter = QComboBox()
        self.type_filter.addItem("전체 유형", "")
        self.type_filter.addItem("매입" if kind == "purchase" else "매출", kind)
        self.type_filter.addItem("반품", kind + "_return")
        filters.addWidget(self.type_filter)
        filters.addWidget(self.status)
        if kind!='purchase':
            filters.addWidget(self.partner_filter)
            filters.addWidget(self.partner_lookup)
        self.settlement_filter=QComboBox();self.settlement_filter.addItem('결제유형 전체',None)
        self.group_filter=QComboBox();self.group_filter.addItem('그룹 전체',None)
        self.group_exclude=QCheckBox('제외')
        self.by_user=QCheckBox('담당자');self.user_filter=QLineEdit();self.user_filter.setPlaceholderText('담당자명')
        self.user_filter.setMaximumWidth(120);self.user_filter.setEnabled(False)
        self._filter_revision=None;self._supplier_groups={}
        if kind=='purchase':
            for control in (self.settlement_filter,self.group_filter,self.group_exclude,self.by_user,self.user_filter):filters.addWidget(control)
            self.settlement_filter.setToolTip('현재 공급사 결제유형 그룹으로 조회합니다. 과거 전표의 결제금액은 변경하지 않습니다.')
            self.group_filter.setToolTip('공급사관리에서 등록한 현재 일반그룹 기준입니다.')
        filters.addStretch()
        if kind=='purchase':
            filters.setContentsMargins(0,0,0,0)
            filter_strip=QHBoxLayout();filter_strip.addWidget(_compact_scroll_row(filters),1)
            filter_strip.addWidget(self.new_button,0,Qt.AlignmentFlag.AlignRight)
            self.body.addLayout(filter_strip)
        else:self.body.addLayout(filters)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.returns.hide()
        self.body.addLayout(search_row)
        self.summary = QLabel()
        self.summary.setObjectName("summary")
        self.body.addWidget(self.summary)
        if kind=='purchase':
            self.grid=self.table(['No.','구분','유형','코드','공급사','입고일시','매입합계','결제금액','외상매입','메모','수정일시','상태','전표번호','담당자','포인트'],PurchaseJournalGrid)
            for column,width in enumerate((44,55,62,52,150,100,90,90,90,65,128,80,200,100,80)):self.grid.setColumnWidth(column,width)
            self.grid.horizontalHeaderItem(5).setToolTip('저장된 입고일입니다. 입고 시간은 보관하지 않아 만들어 표시하지 않습니다.')
            self.grid.horizontalHeaderItem(10).setToolTip('전표 저장·확정·취소 감사기록의 마지막 일시입니다. 과거에 기록이 없으면 빈칸입니다.')
            self.grid.horizontalHeaderItem(2).setToolTip('현재 등록된 공급사의 직매입/수수료 구분입니다.')
            self.grid.sortItems(0,Qt.SortOrder.AscendingOrder)
        else:self.grid = self.table(["전표번호", "구분", "거래일", "거래처", "합계", "결제", "포인트", "미결제", "상태", "담당자", "메모"])
        controls = QHBoxLayout()
        if kind=='purchase':
            self.body.removeItem(search_row);search_row.removeWidget(self.search);search_row.deleteLater()
            self.search.setMaximumWidth(230);controls.addWidget(self.search,1)
            self.body.removeWidget(self.summary);self.body.addWidget(self.summary)
        if kind=='purchase':controls.addWidget(self.import_button)
        for label, callback in (("전표 조회 / 수정", self.detail), ("결제관리 / 환불" if kind=='purchase' else "결제 / 환불", self.settle), ("반품등록", self.return_trade), ("확정 취소", self.cancel), ("초안 삭제", self.delete_draft)):
            controls.addWidget(action(label, callback))
        controls.addStretch()
        if kind=='purchase':self.body.addWidget(_compact_scroll_row(controls,50))
        else:self.body.addLayout(controls)
        self.grid.itemDoubleClicked.connect(self.detail)
        self.search.returnPressed.connect(self.refresh)
        self.partner_filter.currentIndexChanged.connect(self.refresh)
        self.returns.toggled.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        for control in (self.settlement_filter,self.group_filter):control.currentIndexChanged.connect(self.refresh)
        self.group_exclude.toggled.connect(self.refresh)
        self.by_user.toggled.connect(lambda enabled:(self.user_filter.setEnabled(enabled),self.refresh()))
        self.user_filter.returnPressed.connect(self.refresh)

    def pick_filter_partner(self):
        picker = PartnerPicker(self.window, "supplier" if self.kind == "purchase" else "customer", for_filter=True)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        selected = picker.selected_record
        index = self.partner_filter.findData(selected["id"])
        if index < 0:
            self.partner_filter.addItem(selected["name"], selected["id"])
            index = self.partner_filter.count() - 1
        self.partner_filter.setCurrentIndex(index)
        self.refresh()

    def import_excel(self):
        from .purchase_import_ui import PurchaseImportDialog
        try:
            dialog = PurchaseImportDialog(self.store, self.window)
            dialog.imported.connect(self.refresh)
            dialog.exec()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def refresh(self):
        try:
            if self.kind=='purchase':
                revision=(str(self.store.actor),tuple(self.store.audit_revision()))
                if revision!=self._filter_revision:
                    groups=self.store.trade_supplier_groups();self._supplier_groups={g['id']:set(g['members']) for g in groups}
                    for box,kind in ((self.settlement_filter,'settlement'),(self.group_filter,'general')):
                        selected=box.currentData();box.blockSignals(True)
                        while box.count()>1:box.removeItem(1)
                        for group in groups:
                            if group['kind']==kind:box.addItem(group['name'],group['id'])
                        box.setCurrentIndex(max(0,box.findData(selected)));box.blockSignals(False)
                    self._filter_revision=revision
                modified={r['document_id']:r['modified_at'] for r in self.store.purchase_journal_dates(_date(self.start),_date(self.end))}
                supplier_modes={r['id']:r['supplier_mode'] for r in self.store.trade_partners('supplier',include_inactive=True)}
            rows = self.store.documents(start=_date(self.start), end=_date(self.end), partner_id=self.partner_filter.currentData(), status=self.status.currentData(), search=self.search.text())
            rows = [r for r in rows if r["kind"] == self.kind or self.returns.isChecked() and r["kind"] == self.kind + "_return"]
            if self.type_filter.currentData():
                rows = [r for r in rows if r["kind"] == self.type_filter.currentData()]
            if self.kind=='purchase':
                if self.settlement_filter.currentData() is not None:
                    members=self._supplier_groups.get(self.settlement_filter.currentData(),set())
                    rows=[r for r in rows if r['partner_id'] in members]
                if self.group_filter.currentData() is not None:
                    members=self._supplier_groups.get(self.group_filter.currentData(),set())
                    rows=[r for r in rows if (r['partner_id'] in members)!=self.group_exclude.isChecked()]
                if self.by_user.isChecked():
                    rows=[r for r in rows if self.user_filter.text().strip().casefold() in r.get('user_name','').casefold()]
            if self.kind!='purchase':self.grid.fill([[r["number"], KINDS[r["kind"]], r["date"], r.get("partner_name", ""), -r["total"] if r["kind"].endswith("_return") else r["total"], r.get("cash_paid", 0), r.get("points_used", 0), r.get("net_balance", -r.get("balance", 0) if r["kind"].endswith("_return") else r.get("balance", 0)), STATUSES[r["status"]], r.get("user_name", ""), r["memo"]] for r in rows], rows)
            active = [r for r in rows if r["status"] == "posted"]
            total = sum((-1 if r["kind"].endswith("_return") else 1) * r["total"] for r in active)
            gross = sum(r["total"] for r in active if not r["kind"].endswith("_return"))
            returned = sum(r["total"] for r in active if r["kind"].endswith("_return"))
            paid = sum((-1 if r["kind"].endswith("_return") else 1) * r["cash_paid"] for r in active)
            net_balance = sum(r.get("net_balance", -r.get("balance", 0) if r["kind"].endswith("_return") else r.get("balance", 0)) for r in active)
            if self.kind=='purchase':
                values=[[index,KINDS[r['kind']],'수수료' if supplier_modes.get(r['partner_id'])=='commission' else '직매입',r['partner_code'],r['partner_name'],r['date'],
                    -r['total'] if r['kind'].endswith('_return') else r['total'],
                    -r['cash_paid'] if r['kind'].endswith('_return') else r['cash_paid'],r.get('net_balance',0),r['memo'],modified.get(r['id'],''),STATUSES[r['status']],r['number'],r['user_name'],r.get('points_used',0)] for index,r in enumerate(rows,1)]
                if rows:
                    values.append(['','','','','Σ 합계 (확정)', '',total,paid,net_balance,'','','','','',''])
                self.grid.fill(values,rows+([None] if rows else []))
            self.summary.setWordWrap(True)
            self.summary.setText(f"{_date(self.start)} ~ {_date(self.end)} · {self.partner_filter.currentText()} · 조회 {len(rows):,}건\n확정 거래 {won(gross)}원 − 반품 {won(returned)}원 = 순거래 {won(total)}원 · 결제/환불 순액 {won(paid)}원 · 조회전표 현재 순미결제 {won(net_balance)}원  (음수: 환불 예정 · 초안/취소 제외)")
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def selected(self):
        row = self.grid.selected()
        if not row:
            self.notify("전표를 선택하세요.")
        return row

    def new_trade(self):
        try:
            self.store._require_capability("purchases" if self.kind == "purchase" else "sales", "create")
        except PermissionError as exc:
            return self.fail(exc)
        picker = PartnerPicker(self.window, "supplier" if self.kind == "purchase" else "customer")
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        # The account/supplier can change while a modeless host is in use.
        try:
            self.store._require_capability('purchases' if self.kind=='purchase' else 'sales','create')
            selected=next((r for r in self.store.trade_partners('supplier' if self.kind=='purchase' else 'customer') if r['id']==picker.selected_record['id']),None)
            if selected is None:raise ValueError('사용 중인 거래처를 다시 선택하세요.')
        except (ValueError,PermissionError) as exc:return self.fail(exc)
        dialog = TradeDialog(self.window, self.kind)
        dialog.partner.setCurrentIndex(dialog.partner.findData(selected["id"]))
        if dialog.exec() == QDialog.DialogCode.Accepted or dialog.saved_id:
            self.refresh()

    def focus_scan(self):
        self.new_trade()

    def detail(self, *_):
        row = self.selected()
        if row:
            TradeDialog(self.window, row["kind"], self.store.document(row["id"])).exec()
            self.refresh()

    def settle(self):
        row = self.selected()
        if not row:
            return
        if row["status"] != "posted":
            return self.notify("확정 전표에서만 결제·환불할 수 있습니다.")
        if self.kind == 'purchase' and row['kind'] == 'purchase':
            from .purchase_payment_ui import open_payment
            try:
                if open_payment(self.window, row['id'], self):self.refresh()
            except (ValueError, PermissionError) as exc:self.fail(exc)
            return
        value, accepted = QInputDialog.getText(self, "수금 · 지급 / 환불", "금액 (양수 원, 반품은 자동 환불 처리)")
        if not accepted:
            return
        method, accepted = QInputDialog.getItem(self, "결제 방법", "실제 결제 방법", ["현금", "계좌이체"], 0, False)
        if not accepted:
            return
        payment_date, accepted = QInputDialog.getText(self, "결제 일자", "실제 입출금일 YYYY-MM-DD", text=date.today().isoformat())
        if not accepted:
            return
        try:
            self.store.add_payment(row["id"], value, payment_date, "cash" if method == "현금" else "transfer")
            self.refresh()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def return_trade(self):
        row = self.grid.selected()
        if self.kind == "purchase" and (not row or row["status"] != "posted" or row["kind"] != "purchase"):
            picker = PurchaseSourcePicker(self.window, self.partner_filter.currentData())
            if picker.exec() != QDialog.DialogCode.Accepted:
                return
            row = picker.record
        if not row:
            return
        if row["status"] != "posted" or row["kind"] != self.kind:
            return self.notify("취소되지 않은 원매입·매출 전표를 선택하세요.")
        if TradeDialog(self.window, self.kind + "_return", source=self.store.document(row["id"])).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def cancel(self):
        row = self.selected()
        if not row:
            return
        reason, accepted = QInputDialog.getText(self, "확정 취소", "취소 사유 (결제·반품 연결이 있으면 취소가 제한됩니다)")
        if accepted and _confirm(self, "확정 취소", "전표 재고 반영을 되돌릴까요? 이력은 보존됩니다."):
            try:
                self.store.cancel_document(row["id"], reason)
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)

    def delete_draft(self):
        row = self.selected()
        if row and _confirm(self, "초안 삭제", "선택한 초안을 삭제할까요? 확정 전표는 삭제할 수 없습니다."):
            try:
                self.store.delete_draft(row["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)


class LedgerPage(Page):
    def __init__(self, window):
        super().__init__(window, "거래처 원장", "초기 외상과 기간 전 이월을 포함해 거래·입출금·잔액을 확인합니다.")
        filters = QHBoxLayout()
        self.partner = QComboBox()
        self.partner.addItem("거래처 선택", None)
        for kind, title in (("supplier", "공급사"), ("customer", "판매처")):
            for row in self.store.partners(kind):
                self.partner.addItem(f"[{title}] {row['code']} · {row['name']}", row["id"])
        filters.addWidget(self.partner, 1)
        self.start, self.end = _dates(filters, self.refresh)
        self.body.addLayout(filters)
        self.summary = QLabel("거래처를 선택하세요.")
        self.summary.setObjectName("summary")
        self.body.addWidget(self.summary)
        self.grid = self.table(["일자", "구분", "전표번호", "거래액", "지급 · 수금", "잔액", "메모"])

    def refresh(self):
        if not self.partner.currentData():
            return
        try:
            result = self.store.ledger(self.partner.currentData(), _date(self.start), _date(self.end))
            self.grid.fill([[r["date"], KINDS.get(r["kind"], r["kind"]), r.get("number", ""), r["charge"], r["payment"], r["balance"], r.get("memo", "")] for r in result["entries"]], result["entries"])
            self.summary.setText(f"이월 {won(result['opening'])}원  + 거래 {won(result['charge'])}원  − 입출금 {won(result['payment'])}원  = 잔액 {won(result['closing'])}원")
        except (ValueError, PermissionError) as exc:
            self.fail(exc)


class CountEditor(QDialog):
    """Inputs are keyed by immutable product ID; sorting never changes targets."""

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()
    def __init__(self, window):
        super().__init__(window)
        self.store, self.saved_id = window.store, None
        self.setWindowTitle("새 재고 실사 · 초안")
        self.resize(940, 700)
        body = QVBoxLayout(self)
        form = QHBoxLayout()
        self.title = QLineEdit(f"{date.today().isoformat()} 정기 실사")
        self.date = date_field()
        form.addWidget(self.title, 1)
        form.addWidget(self.date)
        body.addLayout(form)
        body.addWidget(QLabel("실제 수량을 기본단위로 입력하세요. 빈칸은 실사에서 제외합니다. 초안 저장 후 차이를 검토하고 별도 확정합니다."))
        self.grid = QTableWidget(0, 5)
        self.grid.setHorizontalHeaderLabels(["상품코드", "상품명", "기본단위", "장부수량", "실제수량 (빈칸 제외)"])
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.inputs = {}
        self.snapshot = {}
        products = [p for p in self.store.products(active_only=True) if p.get("tracked", True)]
        self.grid.setRowCount(len(products))
        for index, product in enumerate(products):
            self.snapshot[product["id"]] = product["stock_qty"]
            for column, value in enumerate((product["code"], product["name"], product["base_unit"], amount(product["stock_qty"]))):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.grid.setItem(index, column, item)
            field = QLineEdit()
            field.setPlaceholderText("미실사")
            self.inputs[product["id"]] = field
            self.grid.setCellWidget(index, 4, field)
        self.grid.setSortingEnabled(True)
        body.addWidget(self.grid, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)

    def save(self):
        try:
            items = [{"product_id": identifier, "expected_qty": self.snapshot[identifier], "counted_qty": field.text().strip()} for identifier, field in self.inputs.items() if field.text().strip()]
            if not items:
                raise ValueError("실사한 상품의 실제 수량을 입력하세요.")
            self.saved_id = self.store.create_count({"title": self.title.text(), "date": _date(self.date), "items": items})
            from .navigation import mark_saved
            mark_saved(self)
            self.accept()
        except (ValueError, PermissionError) as exc:
            _warn(self, exc)


class CountsPage(Page):
    def __init__(self, window):
        super().__init__(window, "재고 실사", "장부 스냅샷 → 실제 수량 → 초안 검토 → 조정 확정. 이후 재고가 변하면 확정을 차단합니다.")
        self.actions.addWidget(action("새 실사 초안", self.create, True))
        self.grid = self.table(["번호", "실사명", "기준일", "상태", "품목 수", "담당자"])
        controls = QHBoxLayout()
        controls.addWidget(action("차이 미리보기", self.detail))
        controls.addWidget(action("실사 확정", self.apply))
        controls.addWidget(action("초안 삭제", self.delete))
        controls.addStretch()
        self.body.addLayout(controls)
        self.grid.itemDoubleClicked.connect(self.detail)

    def refresh(self):
        rows = self.store.counts()
        self.grid.fill([[r["id"], r["title"], r["date"], "초안" if r["status"] == "draft" else "확정", r["item_count"], r.get("user_name", "")] for r in rows], rows)

    def create(self):
        if CountEditor(self.window).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def detail(self, *_):
        row = self.grid.selected()
        if not row:
            return self.notify("실사 초안을 선택하세요.")
        try:
            record = self.store.count(row["id"])
            dialog = QDialog(self)
            dialog.setWindowTitle(record["title"] + " · 차이 검토")
            dialog.resize(1000, 650)
            body = QVBoxLayout(dialog)
            grid = DataGrid(["상품", "단위", "장부", "실제", "수량 차이", "장부 원가", "실사 원가", "원가 차이"])
            grid.fill([[r["product_name"], r["base_unit"], Decimal(r["expected_qty"]), Decimal(r["counted_qty"]), Decimal(r["difference"]), r["expected_cost"], r["counted_cost"], r["cost_difference"]] for r in record["items"]])
            body.addWidget(grid)
            buttons = QHBoxLayout()
            buttons.addWidget(action("엑셀 저장", lambda: grid.export(dialog, "실사 차이")))
            buttons.addWidget(action("인쇄", lambda: grid.print_pages(dialog, record["title"])))
            buttons.addWidget(action("닫기", dialog.accept))
            body.addLayout(buttons)
            dialog.exec()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def apply(self):
        row = self.grid.selected()
        if row and _confirm(self, "실사 확정", "검토한 차이를 재고에 반영할까요? 초안 이후 입출고가 있으면 안전을 위해 거부됩니다."):
            try:
                self.store.apply_count(row["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)

    def delete(self):
        row = self.grid.selected()
        if row and _confirm(self, "초안 삭제", "미확정 실사 초안을 삭제할까요?"):
            try:
                self.store.delete_count(row["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)


class ReportPage(Page):
    def __init__(self, window):
        super().__init__(window, "거래 분석", "확정 거래의 반품·이동평균 원가를 반영합니다. 서로 다른 단위의 수량은 합산하지 않습니다.")
        filters = QHBoxLayout()
        self.start, self.end = _dates(filters, self.refresh)
        self.group = QComboBox()
        for label, value in (("일별", "day"), ("월별", "month"), ("상품별", "product"), ("분류별", "category"), ("공급사별", "supplier"), ("회원별", "member")):
            self.group.addItem(label, value)
        filters.addWidget(self.group)
        filters.addStretch()
        self.body.addLayout(filters)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("summary")
        self.body.addWidget(self.summary)
        self.grid = self.table(["집계 항목", "단위", "순매입 수량", "순매출 수량", "순매입액", "순매출액", "매출원가", "매출이익"])

    def refresh(self):
        try:
            result = self.store.report(_date(self.start), _date(self.end), self.group.currentData())
            self.grid.fill([[r["label"], r["unit"], Decimal(str(r["purchase_qty"])), Decimal(str(r["sale_qty"])), r["purchase_total"], r["sale_total"], r["cost"], r["profit"]] for r in result["rows"]], result["rows"])
            totals = result["totals"]
            self.summary.setText(f"순매입 {won(totals['purchase_total'])}원 · 순매출 {won(totals['sale_total'])}원 · 원가 {won(totals['cost'])}원 · 이익 {won(totals['profit'])}원\n현금 순입금 {won(totals.get('cash_net', 0))}원 · 계좌 순입금 {won(totals.get('transfer_net', 0))}원 · 사용 포인트 {won(totals.get('points_used', 0))}")
        except (ValueError, PermissionError) as exc:
            self.fail(exc)


class ClosingsPage(Page):
    def __init__(self, window):
        super().__init__(window, "업무 마감", "현금은 실제 담당자별 입출금 기준, 월 재고는 해당 월말 거래일 기준으로 동결합니다.")
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self.cash_panel = QWidget()
        cash = QVBoxLayout(self.cash_panel)
        controls = QHBoxLayout()
        self.cash_date = date_field()
        self.opening = QLineEdit("0")
        self.counted = QLineEdit("0")
        self.memo = QLineEdit()
        self.memo.setPlaceholderText("마감 메모")
        controls.addWidget(self.cash_date)
        for label, widget in (("시재", self.opening), ("실제 현금", self.counted)):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addWidget(action("예상 현금 조회", self.preview_cash))
        self.cash_save = action("현금 마감 확정", self.close_cash, True)
        controls.addWidget(self.cash_save)
        cash.addLayout(controls)
        cash.addWidget(self.memo)
        self.cash_summary = QLabel()
        self.cash_summary.setWordWrap(True)
        cash.addWidget(self.cash_summary)
        self.cash_grid = DataGrid(["일자", "담당자", "시재", "현금 순입금", "예상", "실제", "차이", "메모"])
        self.cash_grid.read_permissions = ("trade", "reports")
        cash.addWidget(self.cash_grid)
        self.tabs.addTab(self.cash_panel, "현금 마감")
        self.inventory_panel = QWidget()
        inventory = QVBoxLayout(self.inventory_panel)
        controls = QHBoxLayout()
        self.month = QLineEdit(date.today().replace(day=1).isoformat()[:7])
        self.month.setPlaceholderText("YYYY-MM")
        controls.addWidget(QLabel("마감 월"))
        controls.addWidget(self.month)
        self.inventory_save = action("월 재고 마감 확정", self.close_inventory, True)
        self.inventory_save.setEnabled(_permission(self.store, "inventory"))
        controls.addWidget(self.inventory_save)
        controls.addStretch()
        inventory.addLayout(controls)
        inventory.addWidget(QLabel("이미 끝난 월만 마감할 수 있습니다. 마감일 이전 거래·재고 변경은 금지되며 마감은 되돌릴 수 없습니다."))
        self.inventory_grid = DataGrid(["번호", "마감 월", "월말 기준일", "재고 원가", "품목 수"])
        self.inventory_grid.read_permissions = ("inventory", "reports")
        inventory.addWidget(self.inventory_grid)
        controls = QHBoxLayout()
        controls.addWidget(action("마감 재고 상세", self.inventory_detail))
        controls.addStretch()
        inventory.addLayout(controls)
        self.tabs.addTab(self.inventory_panel, "월 재고 마감")
        self.actions.addWidget(action("엑셀 저장", self.export))
        self.actions.addWidget(action("인쇄", self.print))
        self.tabs.setTabEnabled(0, _permission(self.store, "trade") or _permission(self.store, "reports"))
        self.tabs.setTabEnabled(1, _permission(self.store, "inventory") or _permission(self.store, "reports"))
        self.cash_save.setEnabled(_permission(self.store, "trade"))
        if not self.tabs.isTabEnabled(0):
            self.tabs.setCurrentIndex(1)

    def refresh(self):
        if self.tabs.isTabEnabled(0):
            rows = self.store.cash_closes()
            self.cash_grid.fill([[r["date"], r["user_name"], r["opening_cash"], r["cash_net"], r["expected_cash"], r["counted_cash"], r["difference"], r["memo"]] for r in rows], rows)
            self.preview_cash()
        if self.tabs.isTabEnabled(1):
            rows = self.store.inventory_closes()
            self.inventory_grid.fill([[r["id"], r["month"], r["date"], r["stock_cost"], r["item_count"]] for r in rows], rows)

    def preview_cash(self):
        try:
            data = self.store.cash_expected(_date(self.cash_date))
            expected = money(self.opening.text()) + data["expected_cash"]
            self.cash_summary.setText(f"{data.get('user_name', '')} · 현금 수금 {won(data['cash_receipts'])}원 − 환불 {won(data['cash_refunds'])}원 · 시재 포함 예상 {won(expected)}원 (이체·포인트 제외)")
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def close_cash(self):
        if not _confirm(self, "현금 마감", "입출금과 실제 현금을 확인했나요? 이 담당자의 해당 일자 현금 업무가 잠깁니다."):
            return
        try:
            self.store.cash_close({"date": _date(self.cash_date), "opening_cash": self.opening.text(), "counted_cash": self.counted.text(), "memo": self.memo.text()})
            self.refresh()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def close_inventory(self):
        if not _confirm(self, "월 재고 마감", "월말 재고를 동결합니다. 마감일 이전 입출고는 이후 등록·수정할 수 없습니다. 계속할까요?"):
            return
        try:
            self.store.inventory_close(self.month.text().strip())
            self.refresh()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def inventory_detail(self):
        row = self.inventory_grid.selected()
        if not row:
            return self.notify("월 마감을 선택하세요.")
        record = self.store.inventory_close_detail(row["id"])
        dialog = QDialog(self)
        dialog.read_permissions = ("inventory", "reports")
        dialog.setWindowTitle(record["month"] + " 월말 재고")
        dialog.resize(850, 620)
        body = QVBoxLayout(dialog)
        grid = DataGrid(["상품", "기본단위", "월말 수량", "재고 원가"])
        grid.fill([[r["product_name"], r["base_unit"], Decimal(r["stock_qty"]), r["stock_cost"]] for r in record["lines"]])
        body.addWidget(grid)
        controls = QHBoxLayout()
        controls.addWidget(action("엑셀 저장", lambda: grid.export(dialog, "월말 재고")))
        controls.addWidget(action("인쇄", lambda: grid.print_pages(dialog, record["month"] + " 월말 재고")))
        controls.addWidget(action("닫기", dialog.accept))
        body.addLayout(controls)
        dialog.exec()

    def export(self):
        (self.cash_grid if self.tabs.currentIndex() == 0 else self.inventory_grid).export(self, "업무 마감")

    def print(self):
        (self.cash_grid if self.tabs.currentIndex() == 0 else self.inventory_grid).print_pages(self, "업무 마감")
