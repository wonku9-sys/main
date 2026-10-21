"""Fresh desktop catalog screens, derived from the offline manual's workflows.

No network lookup or old application dependency is used by these screens.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QDate, QTime, Qt, Signal, QTimer, QEvent, QSize
from PySide6.QtGui import QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTabWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QMenu, QStyle, QTreeWidget, QTreeWidgetItem, QSpinBox, QTimeEdit,QSplitter, QToolButton,
)

from .widgets import DataGrid, Page, ScanField, won, date_field, action, search_icon
from .permissions import can_action, restrict_button
from .catalog import CATEGORY_FIELDS, DEFAULT_PRODUCT_CATEGORY
from .category_tree import CategoryTree, folder_icon


PERMISSION_LABELS = {
    "catalog": "상품·거래처", "trade": "매입·매출·원장", "inventory": "재고·마감",
    "loyalty": "회원·특매", "reports": "분석·보고서", "admin": "사용자·설정",
}
PRODUCT_LABELS = {
    "code": "상품코드", "barcode": "바코드", "name": "상품명", "receipt_name": "표시명",
    "category": "대분류", "category_mid": "중분류", "category_small": "소분류",
    "specification": "규격", "base_unit": "기본단위", "tax_mode": "과세구분",
    "tracked": "재고관리", "active": "사용여부", "supplier_id": "공급사",
    "purchase_price": "매입단가", "sale_price": "판매단가", "min_qty": "최소재고",
    "origin": "원산지", "warehouse": "창고", "shelf": "진열위치", "keywords": "검색어",
    "memo": "메모", "factor": "기본단위 환산수량",
}


def product_status(record):
    return "무효" if not record.get("active", True) else "퇴출대상" if record.get("retirement_target") else "유효"


class CategoryChoice(QComboBox):
    """A master-data selector with text helpers used by the product form."""
    def text(self):
        return self.currentText() if self.currentData() != "" else ""

    def setText(self, value):
        index = self.findText(value) if value else 0
        if index < 0:
            self.addItem(value, value)
            index = self.count() - 1
        self.setCurrentIndex(index)


def _won(value):
    return won(value)


def _quantity(value):
    return f"{Decimal(str(value or 0)):,.3f}"


def _button(label, callback, layout, primary=False):
    button = QPushButton(label)
    if primary:
        button.setObjectName("primary")
    button.clicked.connect(lambda *_: callback())
    from .widgets import mark_query_button
    mark_query_button(button,callback)
    from .menu_help import ACTION_HELP, attach_help
    attach_help(button, ACTION_HELP.get(label))
    restrict_button(button, callback)
    layout.addWidget(button)
    return button


def _error(parent, error):
    QMessageBox.warning(parent, "입력 확인", str(error))


def _confirm(parent, title, text):
    return QMessageBox.question(parent, title, text,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


def _combo(options, value=None, editable=False):
    box = QComboBox()
    box.setEditable(editable)
    for label, data in options:
        box.addItem(label, data)
    index = box.findData(value)
    if index >= 0:
        box.setCurrentIndex(index)
    elif editable and value:
        box.setEditText(str(value))
    return box


class EntryDialog(QDialog):
    """Small consistent editor for local records and conversion units."""

    def accept(self):
        from .navigation import mark_saved
        mark_saved(self)
        super().accept()

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()

    def __init__(self, title, parent=None, width=580):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(width, 420)
        self.fields = {}
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 22, 24, 22)
        heading = QLabel(title)
        heading.setObjectName("dialogHeading")
        self.body.addWidget(heading)
        viewport = QScrollArea()
        viewport.setWidgetResizable(True)
        content = QWidget()
        self.form = QFormLayout()
        self.form.setSpacing(10)
        content.setLayout(self.form)
        viewport.setWidget(content)
        self.body.addWidget(viewport, 1)

    def field(self, key, label, value="", password=False):
        field = QLineEdit(str(value if value is not None else ""))
        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        self.fields[key] = field
        self.form.addRow(label, field)
        return field

    def finish(self, callback):
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#bd3232;")
        self.body.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                       QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(lambda: self._submit(callback))
        self.buttons.rejected.connect(self.reject)
        self.body.addWidget(self.buttons)

    def _submit(self, callback):
        try:
            callback()
        except (ValueError, PermissionError, OSError) as exc:
            self.error_label.setText(str(exc))
        else:
            self.accept()

    def values(self):
        return {key: field.text().strip() for key, field in self.fields.items()}


class CategoriesPage(Page):
    def __init__(self, window):
        super().__init__(window, "상품 분류체계 관리", "분류를 먼저 등록한 뒤 상품 등록창에서 선택하세요.")
        self.read_permissions = ("catalog",)
        for title, callback in (("대분류 추가", self.add_root), ("하위분류 추가", self.add_child), ("수정", self.edit), ("삭제", self.delete)):
            _button(title, callback, self.actions)
        _button('기본 분류 구성',self.seed_defaults,self.actions)
        self.search = QLineEdit()
        self.search.setPlaceholderText("분류명 검색 · 대분류 / 중분류 / 소분류")
        self.search.textChanged.connect(self.filter_tree)
        self.body.addWidget(self.search)
        self.tree = CategoryTree()
        self.tree.setMinimumHeight(350)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.body.addWidget(self.tree, 1)
        note = QLabel("항목 선택 후 마우스 오른쪽 버튼: 추가·수정·삭제·유효/무효·하위분류 보기/감추기\n상품이 연결되었거나 하위 분류가 있는 항목은 삭제할 수 없습니다.")
        note.setWordWrap(True)
        self.body.addWidget(note)
        self.refresh()

    def seed_defaults(self):
        if not _confirm(self,'기본 분류 구성','야채·청과·정육·수산·가공식품·비식품 등의 대·중·소분류를 추가할까요? 기존 분류·상품은 변경하지 않습니다.'):return
        try:
            added=self.store.seed_catalog_categories();self.refresh();self.notify(f'분류 {added:,}개 추가')
        except (ValueError,PermissionError) as exc:_error(self,exc)

    def selected(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def refresh(self):
        previous = self.selected()
        self.tree.clear()
        self.root = QTreeWidgetItem(self.tree, ["전체분류"])
        self.root.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.items = {}
        for record in self.store.categories():
            parent = self.items.get(record["parent_id"], self.root)
            item = QTreeWidgetItem(parent, [record["name"] + (" (무효)" if not record["active"] else "")])
            item.setIcon(0, folder_icon(record["level"], record["active"]))
            item.setData(0, Qt.ItemDataRole.UserRole, record)
            item.setToolTip(0, f"{' / '.join(record['path'])} · 연결 상품 {record['product_count']:,}개")
            if not record["active"]:
                item.setForeground(0, QColor("#8A9298"))
            self.items[record["id"]] = item
        self.tree.expandAll()
        self.tree.setCurrentItem(self.items.get(previous["id"], self.root) if previous else self.root)
        self.filter_tree()

    def filter_tree(self, *_):
        if not hasattr(self, "items"):
            return
        term = self.search.text().strip().casefold()
        for item in reversed(list(self.items.values())):
            record = item.data(0, Qt.ItemDataRole.UserRole)
            match = term in " / ".join(record["path"]).casefold()
            visible = match or any(not item.child(index).isHidden() for index in range(item.childCount()))
            item.setHidden(not visible)
            if term and visible:
                item.setExpanded(True)

    def editor(self, record=None, parent_id=None):
        dialog = EntryDialog("분류 수정" if record else "분류 추가", self)
        dialog.field("name", "분류명", record["name"] if record else "")
        identifier = []
        def save():
            identifier.append(self.store.save_category({"name": dialog.fields["name"].text(), "parent_id": record["parent_id"] if record else parent_id}, record["id"] if record else None))
        dialog.finish(save)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            if identifier:
                self.tree.setCurrentItem(self.items[identifier[0]])

    def add_root(self):
        self.editor()

    def add_child(self):
        record = self.selected()
        if record and record["level"] == 3:
            return self.notify("소분류 아래에는 추가할 수 없습니다.")
        self.editor(parent_id=record["id"] if record else None)

    def edit(self):
        record = self.selected()
        if record:
            self.editor(record)
        else:
            self.notify("수정할 분류를 선택하세요.")

    def delete(self):
        record = self.selected()
        if record and _confirm(self, "분류 삭제", f"'{record['name']}' 분류를 삭제할까요?"):
            try:
                self.store.delete_category(record["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                _error(self, exc)

    def set_active(self, active):
        record = self.selected()
        if record:
            try:
                self.store.save_category({"name": record["name"], "active": active}, record["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                _error(self, exc)

    def make_context_menu(self):
        record = self.selected()
        item = self.tree.currentItem() or self.root
        menu = QMenu(self)
        def option(text, callback, enabled=True):
            entry = menu.addAction(text)
            operation = "create" if "추가" in text else "delete" if "삭제" in text else "edit" if any(word in text for word in ("수정", "무효화", "유효화")) else None
            entry.setEnabled(enabled and (not operation or can_action(self.store.actor, "categories", operation)))
            entry.triggered.connect(lambda _checked=False: callback())
        option("분류 등록정보 / 수정", self.edit, bool(record))
        menu.addSeparator()
        option("분류 추가", self.add_child, not record or record["level"] < 3 and bool(record["active"]))
        option("분류 삭제", self.delete, bool(record))
        menu.addSeparator()
        option("분류를 무효화", lambda: self.set_active(False), bool(record and record["active"]))
        option("분류를 유효화", lambda: self.set_active(True), bool(record and not record["active"]))
        menu.addSeparator()
        def expand(expanded):
            def walk(node):
                node.setExpanded(expanded)
                for index in range(node.childCount()):
                    walk(node.child(index))
            walk(item)
        option("하위분류 보기", lambda: expand(True))
        option("하위분류 감추기", lambda: expand(False))
        return menu

    def context_menu(self, position):
        item = self.tree.itemAt(position)
        if item:
            self.tree.setCurrentItem(item)
        self.make_context_menu().exec(self.tree.viewport().mapToGlobal(position))


class CategoryDialog(QDialog):
    def __init__(self, store, parent=None, select=False):
        super().__init__(parent)
        self.store, self.record = store, None
        self.read_permissions = ("catalog",)
        self.setWindowTitle("상품분류체계 관리")
        self.resize(440, 690)
        body = QVBoxLayout(self)
        context = SimpleNamespace(store=store, notify=lambda text: QMessageBox.information(self, "상품 분류", text))
        self.page = CategoriesPage(context)
        self.page.body.setContentsMargins(8, 4, 8, 6)
        self.page.findChild(QLabel, "pageTitle").hide()
        for index in range(self.page.actions.count()):
            widget = self.page.actions.itemAt(index).widget()
            if widget:
                widget.hide()
        body.addWidget(self.page)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.reject)
        if select:
            self.page.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            for index in range(self.page.actions.count()):
                widget = self.page.actions.itemAt(index).widget()
                if widget:
                    widget.hide()
            choose = buttons.addButton("선택 적용", QDialogButtonBox.ButtonRole.AcceptRole)
            choose.clicked.connect(self.choose)
            self.page.tree.itemDoubleClicked.connect(lambda *_: self.choose())
        body.addWidget(buttons)

    def choose(self):
        record = self.page.selected()
        if record and record["active"]:
            records = {row["id"]: row for row in self.store.categories()}
            ancestor = record
            while ancestor["parent_id"]:
                ancestor = records[ancestor["parent_id"]]
                if not ancestor["active"]:
                    return
            self.record = record
            self.accept()


class PartnerPicker(QDialog):
    def __init__(self, store, kind="supplier", parent=None):
        super().__init__(parent)
        self.store, self.kind, self.record = store, kind, None
        self.setWindowTitle("공급사 선택" if kind == "supplier" else "판매처 선택")
        self.resize(800, 550)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("거래처명 · 코드 · 전화번호 검색")
        layout.addWidget(self.search)
        self.grid = DataGrid(["코드", "거래처명", "사업자등록번호", "담당자", "전화번호", "상태"])
        layout.addWidget(self.grid)
        self.search.textChanged.connect(self.refresh)
        self.grid.itemDoubleClicked.connect(lambda *_: self.choose())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("선택")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("닫기")
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        rows = [item for item in self.store.partners(self.kind, self.search.text()) if item["active"]]
        self.grid.fill([[r["code"], r["name"], r["business_no"], r["contact"], r["phone"], "사용"]
                        for r in rows], rows)

    def choose(self):
        self.record = self.grid.selected()
        if self.record:
            self.accept()


class SupplierFilterDialog(QDialog):
    """Read-only product supplier lookup with bounded, cached search results."""
    PAGE_SIZE = 500
    ALL = {'id': None, 'code': '', 'name': '전체 공급사', 'active': True, 'supplier_mode': ''}

    def __init__(self, store, parent=None, records=None, selected_id=None):
        super().__init__(parent)
        self.store, self.record = store, None
        self.read_permissions = ('catalog',)
        self.menu_key = 'products'
        store.require_menu('products')
        self.records = list(store.catalog_suppliers() if records is None else records)
        self.records.sort(key=lambda r: (r['name'].casefold(), str(r['code']).casefold(), r['id']))
        self.index = [(r, (r['name']+'\n'+str(r['code'])).casefold()) for r in self.records]
        self.matches, self.page, self._query = [], 0, None
        self.setWindowTitle('공급사 검색 · 상품장 조회 조건')
        self.resize(780, 620)
        body = QVBoxLayout(self)
        row = QHBoxLayout(); row.addWidget(QLabel('공급사명 또는 코드 검색'))
        self.search = QLineEdit(); self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText('공급사명 · 코드 일부로 검색 / Enter 선택')
        self.search.setAccessibleName('공급사명 또는 코드 검색')
        row.addWidget(self.search, 1); body.addLayout(row)
        self.grid = DataGrid(['공급사명', '코드', '구분', '상태'])
        self.grid.setSortingEnabled(False)
        self.grid.horizontalHeader().setSectionsClickable(False)
        self.grid.setWordWrap(False)
        self.grid.verticalHeader().setVisible(True)
        self.grid.verticalHeader().setFixedWidth(55)
        for column, width in enumerate((310, 115, 115, 90)):
            self.grid.setColumnWidth(column, width)
        body.addWidget(self.grid, 1)
        pages = QHBoxLayout()
        self.previous = action('이전 500개', lambda: self.move_page(-1))
        self.next = action('다음 500개', lambda: self.move_page(1))
        pages.addWidget(self.previous); pages.addWidget(self.next)
        self.summary = QLabel(); self.summary.setWordWrap(True); pages.addWidget(self.summary, 1)
        body.addLayout(pages)
        self.notice = QLabel('전체 공급사를 선택하면 공급사 조건을 해제합니다. 무효 공급사도 이력 조회를 위해 표시합니다.')
        self.notice.setWordWrap(True); body.addWidget(self.notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.choose_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.choose_button.setText('선택 적용')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('닫기')
        for button in buttons.buttons(): button.setAutoDefault(False)
        buttons.accepted.connect(self.choose); buttons.rejected.connect(self.reject); body.addWidget(buttons)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self.search_changed)
        self.search.returnPressed.connect(self.choose)
        self.grid.cellDoubleClicked.connect(lambda *_: self.choose())
        self.grid.installEventFilter(self); self.search.installEventFilter(self)
        self.refresh()
        position = next((i for i, r in enumerate(self.matches) if r['id'] == selected_id), 0)
        self.page = position // self.PAGE_SIZE
        self.render_page({'id': selected_id})

    def showEvent(self, event):
        super().showEvent(event)
        self.search.setFocus()

    def search_changed(self):
        if len(self.records) > self.PAGE_SIZE:
            self.timer.start()
        else:
            self.refresh()

    def refresh(self):
        self.timer.stop()
        try:
            self.store.require_menu('products')
        except (PermissionError, ValueError) as exc:
            self.grid.clearContents(); self.grid.setRowCount(0)
            self.matches = []; self._query = None
            self.choose_button.setEnabled(False); self.notice.setText(str(exc))
            return
        query = self.search.text().strip().casefold()
        if query != self._query:
            self.matches = ([self.ALL] if not query else []) + [r for r, text in self.index if not query or query in text]
            self._query, self.page = query, 0
        self.render_page()

    def render_page(self, preferred=None):
        selected = preferred if preferred is not None else self.grid.selected()
        start = self.page * self.PAGE_SIZE
        rows = self.matches[start:start+self.PAGE_SIZE]
        self.grid.clearContents(); self.grid.setRowCount(len(rows))
        self.grid.clearSelection(); self.grid.setCurrentCell(-1, -1)
        from .menu_icons import menu_icon
        for index, record in enumerate(rows):
            mode = '' if record['id'] is None else '수수료' if record['supplier_mode'] == 'commission' else '직매입'
            status = '' if record['id'] is None else '유효' if record['active'] else '무효'
            for column, value in enumerate((record['name'], record['code'], mode, status)):
                item = QTableWidgetItem(str(value)); item.setToolTip(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record)
                    item.setIcon(menu_icon('suppliers'))
                self.grid.setItem(index, column, item)
            self.grid.setVerticalHeaderItem(index, QTableWidgetItem(str(start+index+1)))
        if rows:
            target = next((i for i, r in enumerate(rows) if selected is not None and r['id'] == selected['id']), 0)
            self.grid.setCurrentCell(target, 0); self.grid.selectRow(target)
        self.choose_button.setEnabled(bool(rows))
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start+self.PAGE_SIZE < len(self.matches))
        count = sum(r['id'] is not None for r in self.matches)
        self.summary.setText(f'검색 {count:,} / 전체 {len(self.records):,} 공급사 · {self.page+1} / {max(1,(len(self.matches)+self.PAGE_SIZE-1)//self.PAGE_SIZE)}쪽')

    def move_page(self, delta):
        if self.timer.isActive(): self.refresh()
        target = max(0, min(self.page+delta, max(0, (len(self.matches)-1)//self.PAGE_SIZE)))
        if target != self.page:
            self.page = target; self.render_page()

    def choose(self):
        if self.timer.isActive(): self.refresh()
        selected = self.grid.selected()
        if selected is None: return
        try:
            self.store.require_menu('products')
            latest = self.store.catalog_suppliers()
        except (ValueError, PermissionError, OSError) as exc:
            self.grid.clearContents(); self.grid.setRowCount(0)
            self.choose_button.setEnabled(False); self.notice.setText(str(exc)); return
        if selected['id'] is None:
            self.record = dict(self.ALL)
        else:
            self.record = next((r for r in latest if r['id'] == selected['id']), None)
        if self.record is not None:
            self.accept()
        else:
            self.records = latest
            self.index = [(r, (r['name']+'\n'+str(r['code'])).casefold()) for r in latest]
            self._query = None; self.refresh()
            self.notice.setText('공급사가 삭제되었거나 변경되었습니다. 목록을 확인해 다시 선택하세요.')

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if watched is self.grid and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.choose(); return True
            if watched is self.search and event.key() == Qt.Key.Key_Down:
                if self.timer.isActive(): self.refresh()
                if self.grid.rowCount(): self.grid.setFocus()
                return True
        return super().eventFilter(watched, event)

    def done(self, result):
        self.timer.stop()
        super().done(result)


def selectable_category_records(records):
    by_id={r['id']:r for r in records};result=[]
    for record in records:
        current=record
        for _ in range(4):
            if not current or not current['active']:break
            if not current['parent_id']:result.append(record);break
            current=by_id.get(current['parent_id'])
    return result


class CategorySearchDialog(QDialog):
    """Read-only three-level lookup; never creates categories from typed text."""
    def __init__(self,store,parent=None,query=''):
        super().__init__(parent);self.store=store;self.record=None;self.read_permissions=('catalog',)
        self.setWindowTitle('상품분류 검색');self.resize(830,620);body=QVBoxLayout(self)
        self.query=QLineEdit(query);self.query.setPlaceholderText('전체 경로 검색 · 분류명 일부로 검색');self.query.setClearButtonEnabled(True);body.addWidget(self.query)
        row=QHBoxLayout();row.setSpacing(12);self.filters=[];self.shortcuts=[];self.focus_buttons=[]
        for index,label in enumerate(('대분류','중분류','소분류')):
            group=QWidget();line=QHBoxLayout(group);line.setContentsMargins(0,0,0,0);line.setSpacing(5)
            field=QLineEdit();field.setClearButtonEnabled(True);field.setPlaceholderText(label+' 이름')
            tag=QPushButton(f'{label} (F{index+5})');tag.setAutoDefault(False)
            tag.setIcon(folder_icon(index+1,True))
            def focus(checked=False,field=field):field.setFocus();field.selectAll()
            tag.clicked.connect(focus);self.focus_buttons.append(tag)
            line.addWidget(tag);line.addWidget(field,1);row.addWidget(group,1);self.filters.append(field)
            shortcut=QShortcut(QKeySequence(f'F{index+5}'),self);shortcut.setContext(Qt.ShortcutContext.WindowShortcut);shortcut.activated.connect(focus);self.shortcuts.append(shortcut)
        body.addLayout(row);self.grid=DataGrid(['대분류','중분류','소분류']);body.addWidget(self.grid,1)
        self.grid.cellDoubleClicked.connect(lambda *_:self.choose())
        self.summary=QLabel();self.summary.setWordWrap(True);body.addWidget(self.summary)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('선택 적용');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.choose);buttons.rejected.connect(self.reject);body.addWidget(buttons)
        self.query.textChanged.connect(self.refresh)
        for field in self.filters:field.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self,*_):
        query=self.query.text().strip().casefold();terms=[field.text().strip().casefold() for field in self.filters]
        rows=[]
        for record in selectable_category_records(self.store.categories()):
            path=record['path']+['']*(3-len(record['path']))
            if query and query not in ' / '.join(record['path']).casefold():continue
            if any(term and term not in path[i].casefold() for i,term in enumerate(terms)):continue
            rows.append(record)
        self.grid.fill([r['path']+['']*(3-len(r['path'])) for r in rows],rows)
        for i,record in enumerate(rows):
            for column in range(len(record['path'])):self.grid.item(i,column).setIcon(folder_icon(column+1,True))
        if rows:self.grid.selectRow(0)
        self.summary.setText(f'{len(rows)}개 분류 · 등록된 유효 분류만 표시합니다. 행을 더블클릭하거나 선택 적용을 누르세요.')

    def choose(self):
        selected=self.grid.selected()
        if not selected:return
        self.record=next((r for r in selectable_category_records(self.store.categories()) if r['id']==selected['id']),None)
        if self.record is not None:self.accept()
        else:self.refresh();self.summary.setText('분류가 변경되었거나 무효 상태입니다. 다시 검색해 주세요.')


class ProductDialog(QDialog):
    """Real product editor with read-only transaction history and unit CRUD."""
    saved = Signal(int)

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()

    def __init__(self, store, record=None, parent=None):
        super().__init__(parent)
        self.store, self.record = store, dict(record or {})
        self.saved_id = None
        self.fields = {}
        self.history_tables, self.history_filters, self.history_summaries = {}, {}, {}
        self.setObjectName("productDialog")
        self._sy_no_home_button = True
        self._fixed_query_header = True  # Tabs own scrolling; the footer stays visible.
        self.setWindowTitle("상품 등록정보" if record else "새 상품 등록")
        self.resize(700, 800)
        self.setMinimumSize(420, 400)
        self.setStyleSheet('''
            QDialog#productDialog QLineEdit, QDialog#productDialog QComboBox {
                min-width:0px; min-height:20px; padding:3px 5px;
            }
            QDialog#productDialog QPushButton {min-height:20px; padding:4px 8px;}
            QDialog#productDialog QToolButton {min-width:0px; padding:2px 3px;}
            QDialog#productDialog QTabBar::tab {padding:6px 7px;}
            QDialog#productDialog QGroupBox {margin-top:10px; padding-top:9px; border-radius:3px;}
        ''')
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(5)
        head = QHBoxLayout()
        heading = self.heading = QLabel("상품 등록정보" if record else "새 상품 등록")
        heading.setObjectName("dialogHeading")
        head.addWidget(heading)
        head.addStretch()
        head.addWidget(QLabel("금액: 원 · 수량: 소수 3자리"))
        root.addLayout(head)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._product_tab()
        for key, title in (("purchases", "매입정보"), ("sales", "판매정보")):
            self._history_tab(key, title)
        self._stock_tab()
        self._audit_tab()
        self._member_price_tab()
        self._units_tab()
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#bd3232;")
        root.addWidget(self.error_label)
        self.footer = QWidget()
        self._sy_pinned_footer = self.footer
        footer = QHBoxLayout(self.footer)
        footer.setContentsMargins(0, 0, 0, 0)
        self.meta = QLabel()
        self.meta.setWordWrap(True)
        self.meta.setObjectName("muted")
        footer.addWidget(self.meta)
        footer.addStretch()
        self.save_button = _button("저장(S)", self.save, footer, True)
        self.cancel_button = _button("취소", self.cancel, footer)
        self.apply_button = _button("적용(A)", self.apply_changes, footer)
        self.apply_button.setEnabled(can_action(self.store.actor, 'products', 'create'))
        self.save_button.setToolTip('Alt+S · 상품을 저장하고 창을 닫습니다.')
        self.cancel_button.setToolTip('입력 중인 내용은 저장하지 않고 창을 닫습니다.')
        self.apply_button.setToolTip('Alt+A · 상품을 저장하고 새 입력칸을 엽니다. 분류·공급사만 유지합니다.')
        from .menu_icons import menu_icon
        for button, icon in ((self.save_button, '저장'), (self.cancel_button, '취소'), (self.apply_button, '추가')):
            button.setIcon(menu_icon(icon)); button.setIconSize(QSize(20, 20))
            button.setAutoDefault(False)
        self._shortcuts = []
        for key, callback in (('Alt+S', self.save), ('Alt+A', self.apply_changes), ('Alt+C', self.choose_category), ('Alt+V', self.pick_supplier)):
            shortcut = QShortcut(QKeySequence(key), self); shortcut.setAutoRepeat(False)
            shortcut.activated.connect(callback); self._shortcuts.append(shortcut)
        root.addWidget(self.footer)
        self.refresh_details()
        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            height = max(400, min(800, available.height() - 60))
            self.resize(max(420, min(700, available.width() - 40, height - 30)), height)

    def _field(self, layout, key, label, default=""):
        from .number_edit import GroupedNumberEdit
        field = ScanField() if key == "barcode" else GroupedNumberEdit() if key in {'purchase_price', 'sale_price', 'min_qty'} else QLineEdit()
        field.setText(str(self.record.get(key, default)))
        self.fields[key] = field
        layout.addRow(label, field)
        return field

    def _group(self, title):
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setContentsMargins(8, 5, 8, 7)
        form.setSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return group, form

    def _product_tab(self):
        viewport = QScrollArea()
        viewport.setObjectName('productFormScroll')
        viewport.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        classification = QFrame()
        top = QVBoxLayout(classification)
        top.setContentsMargins(4, 4, 4, 4)
        top.setSpacing(5)
        choices=QHBoxLayout();choices.setSpacing(8);top.addLayout(choices)
        def paired(label,field,stretch=0):
            group=QWidget();line=QHBoxLayout(group);line.setContentsMargins(0,0,0,0);line.setSpacing(5)
            text=QLabel(label);text.setBuddy(field);line.addWidget(text);line.addWidget(field,1);choices.addWidget(group,stretch)
            return text
        self.product_status = _combo([("유효", "유효"), ("무효", "무효"), ("퇴출대상", "퇴출대상")], product_status(self.record))
        self.product_status.setToolTip("무효: 신규 거래 제외 / 퇴출대상: 재고 정리용 판매 가능")
        paired('상태',self.product_status)
        self.tax_mode = _combo([("면세", "exempt"), ("과세", "taxable")], self.record.get("tax_mode", "exempt"))
        paired('과면세',self.tax_mode)
        from .tax_display import style_tax_label,tax_style
        self.tax_badge=QLabel();self.tax_badge.setObjectName('productTaxBadge');choices.addWidget(self.tax_badge)
        def tax_changed(*_):
            style_tax_label(self.tax_badge,self.tax_mode.currentData())
            _,_,fg,bg=tax_style(self.tax_mode.currentData())
            self.tax_mode.setStyleSheet(f'QComboBox{{color:{fg};background:{bg};font-weight:700;}}')
        self.tax_mode.currentIndexChanged.connect(tax_changed);tax_changed()
        choices.addStretch()
        choices = QHBoxLayout(); choices.setSpacing(5); top.addLayout(choices)
        self.category_displays={}
        self.category_buttons = {}
        for key, label in (("category", "대"), ("category_mid", "중"), ("category_small", "소")):
            field = CategoryChoice()
            field.addItem("선택 안 함", "")
            field.setPlaceholderText(label)
            self.fields[key] = field
            field.setParent(classification);field.hide()
            display=QLineEdit();display.setReadOnly(True);display.setMinimumWidth(40)
            display.setStyleSheet('QLineEdit{color:#214A40;background:#F6FAF7;font-weight:600;}')
            display.setToolTip('옆의 화살표로 해당 단계 분류를 선택하거나 분류(C)에서 전체 경로를 검색합니다.')
            self.category_displays[key]=display
            group=QWidget();line=QHBoxLayout(group);line.setContentsMargins(0,0,0,0);line.setSpacing(2)
            arrow=QToolButton();arrow.setText(label+' ▸');arrow.setAccessibleName(label+'분류 선택')
            arrow.setToolTip(label+'분류 선택 · 상위 분류에 속한 유효 분류만 표시합니다.')
            arrow.clicked.connect(lambda checked=False,k=key:self.open_category_menu(k))
            self.category_buttons[key]=arrow;line.addWidget(arrow);line.addWidget(display,1);choices.addWidget(group,1)
        self.classification_button=QPushButton('분류(C)');self.classification_button.clicked.connect(lambda:self.choose_category())
        self.classification_button.setToolTip('Alt+C · 대·중·소분류 전체 경로 검색')
        choices.addWidget(self.classification_button)
        self.fields["category"].currentIndexChanged.connect(self.reload_middle)
        self.fields["category_mid"].currentIndexChanged.connect(self.reload_small)
        self.reload_categories()
        suppliers = self.store.partners("supplier")
        options = [("공급사 미지정", None)] + [(f"{p['name']} · {p['code']}", p["id"]) for p in suppliers]
        self.supplier = _combo(options, self.record.get("supplier_id"))
        supplier_row=QHBoxLayout();supplier_row.setSpacing(5);supplier_label=QLabel('공급사');supplier_label.setBuddy(self.supplier);supplier_row.addWidget(supplier_label)
        supplier_row.addWidget(self.supplier,1)
        supplier_search = QPushButton("공급사(V)")
        supplier_search.setToolTip('Alt+V · 공급사 검색')
        supplier_search.clicked.connect(self.pick_supplier)
        supplier_row.addWidget(supplier_search);top.addLayout(supplier_row)
        layout.addWidget(classification)
        columns = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        basics, form = self._group("상품 기본정보")
        for key, label in (("code", "상품코드 *"), ("barcode", "바코드"), ("name", "상품명 *"),
                           ("receipt_name", "표시명"), ("specification", "규격")):
            self._field(form, key, label)
        self.fields["code"].setReadOnly(True)
        self.fields["code"].setPlaceholderText("저장 시 순차 자동 생성")
        units = ["kg", "g", "개", "박스", "팩", "EA", "mg", "L", "mL", "P", "m", "cm", "mm", "W"]
        current = self.record.get("base_unit", "g")
        self.unit = _combo([(u, u) for u in units], current, editable=True)
        form.addRow("기본단위 *", self.unit)
        self.price_basis = _combo([("기본단위 1당", 1), ("100g당", 100)], self.record.get("price_basis", 100 if current == "g" else 1))
        form.addRow("단가 기준", self.price_basis)
        def update_basis(unit):
            if unit != "g" and self.price_basis.currentData() == 100:
                self.price_basis.setCurrentIndex(0)
        self.unit.currentTextChanged.connect(update_basis)
        unit_note = QLabel("이력·확장단위 등록 후 기본단위 변경 불가")
        unit_note.setWordWrap(True)
        unit_note.setObjectName("muted")
        form.addRow(unit_note)
        left.addWidget(basics)
        prices, form = self._group("기준 단가")
        self.purchase_price = self._field(form, "purchase_price", "매입단가 (원)", 0)
        self.sale_price = self._field(form, "sale_price", "판매단가 (원)", 0)
        self.margin = QLabel()
        self.margin.setObjectName("amount")
        form.addRow("이익률", self.margin)
        self.purchase_price.textChanged.connect(self.update_margin)
        self.sale_price.textChanged.connect(self.update_margin)
        note = QLabel("과세·면세는 상품 분류 정보이며 입력 단가는 최종 거래단가입니다.\n특매·예약·회원가격은 기준단가를 변경하지 않습니다.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        form.addRow(note)
        left.addWidget(prices)
        left.addStretch()
        stock, form = self._group("재고 · 보관정보")
        self.tracked = QCheckBox("재고 수량·원가 관리")
        self.tracked.setChecked(bool(self.record.get("tracked", True)))
        form.addRow(self.tracked)
        self.stock_quantity = QLabel()
        self.stock_cost = QLabel()
        self.stock_quantity.setObjectName("amount")
        self.stock_cost.setObjectName("amount")
        form.addRow("현재고", self.stock_quantity)
        form.addRow("현재고 원가액", self.stock_cost)
        self._field(form, "min_qty", "최소재고", "0.000")
        for key, label in (("origin", "원산지"), ("warehouse", "보관창고"), ("shelf", "진열위치")):
            self._field(form, key, label)
        right.addWidget(stock)
        memo, form = self._group("검색 · 상품설명")
        self._field(form, "keywords", "검색어")
        self.memo = QTextEdit(self.record.get("memo", ""))
        self.memo.setAcceptRichText(False)
        self.memo.setMinimumHeight(100)
        form.addRow(QLabel('상품설명 / 메모'))
        form.addRow(self.memo)
        right.addWidget(memo)
        right.addStretch()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns)
        viewport.setWidget(content)
        self.tabs.addTab(viewport, "상품정보")
        self.fields["barcode"].scanned.connect(lambda *_: self.fields["name"].setFocus())
        self.update_margin()

    def _history_tab(self, key, title):
        widget = QWidget()
        body = QVBoxLayout(widget)
        filters = QHBoxLayout()
        enabled = QCheckBox("기간 지정")
        enabled.setChecked(True)
        start, end = QDateEdit(QDate.currentDate()), QDateEdit(QDate.currentDate())
        for field in (start, end):
            field.setCalendarPopup(True)
            field.setDisplayFormat("yyyy-MM-dd")
            field.setEnabled(True)
            field.dateChanged.connect(self.refresh_details)
        enabled.toggled.connect(start.setEnabled)
        enabled.toggled.connect(end.setEnabled)
        enabled.toggled.connect(self.refresh_details)
        for item in (enabled, start, QLabel("~"), end):
            filters.addWidget(item)
        filters.addStretch()
        _button("조회", self.refresh_details, filters)
        body.addLayout(filters)
        grid = DataGrid(["일자", "전표번호", "구분", "거래처", "입력수량", "단위", "단가", "금액", "상태"])
        body.addWidget(grid, 1)
        summary = QLabel()
        summary.setWordWrap(True)
        summary.setObjectName("summary")
        body.addWidget(summary)
        self.history_tables[key] = grid
        self.history_filters[key] = enabled, start, end
        self.history_summaries[key] = summary
        self.tabs.addTab(widget, title)

    def _stock_tab(self):
        widget = QWidget()
        body = QVBoxLayout(widget)
        body.addWidget(QLabel("기본단위 수량 · 이동평균 매입원가 기준 / 취소·반품·실사 이동을 모두 표시합니다."))
        self.stock_table = DataGrid(["일자", "구분", "수량증감", "원가증감", "이동 후 수량", "이동 후 원가", "사유"])
        body.addWidget(self.stock_table)
        self.tabs.addTab(widget, "재고정보")

    def _audit_tab(self):
        widget = QWidget()
        body = QVBoxLayout(widget)
        body.addWidget(QLabel("이 상품의 실제 저장 이력입니다. 변경차=변경후−변경전, 비율=변경차÷|변경전|×100. 기준 0·문자 항목은 비율을 계산하지 않습니다."))
        filters=QHBoxLayout();self.audit_period=QCheckBox('기간 지정');self.audit_start,self.audit_end=date_field(),date_field();self.audit_start.setEnabled(False);self.audit_end.setEnabled(False)
        self.audit_field=_combo([('전체 변경항목','')]+[(label,label) for key,label in PRODUCT_LABELS.items()])
        for control in (self.audit_period,self.audit_start,QLabel('~'),self.audit_end,self.audit_field):filters.addWidget(control)
        self.audit_period.toggled.connect(self.audit_start.setEnabled);self.audit_period.toggled.connect(self.audit_end.setEnabled)
        self.audit_period.toggled.connect(self.refresh_details);self.audit_start.dateChanged.connect(self.refresh_details);self.audit_end.dateChanged.connect(self.refresh_details);self.audit_field.currentIndexChanged.connect(self.refresh_details)
        _button('조회',self.refresh_details,filters);body.addLayout(filters)
        self.audit_table = DataGrid(["변경내용", "변경전", "변경후", "변경차", "비율(%)", "변경일시", "변경사용자", "업무"])
        for column,width in enumerate((90,88,88,80,75,138,90,70)):self.audit_table.setColumnWidth(column,width)
        body.addWidget(self.audit_table)
        tools=QHBoxLayout();_button('엑셀 저장',lambda:self.audit_table.export(self,'상품 변경로그'),tools);_button('인쇄',lambda:self.audit_table.print_pages(self,'상품 변경로그'),tools);tools.addStretch();body.addLayout(tools)
        self.tabs.addTab(widget, "변경로그")

    def _member_price_tab(self):
        panel=QWidget();body=QVBoxLayout(panel);self.member_price_note=QLabel('상품 저장 후 회원별 지정 판매가를 조회합니다. 회원관리 권한이 필요합니다.');self.member_price_note.setWordWrap(True);body.addWidget(self.member_price_note)
        self.member_price_grid=DataGrid(['회원코드','회원명','지정 판매가','회원 상태']);self.member_price_grid.read_permissions=('loyalty',);self.member_price_grid.menu_key='member_prices';body.addWidget(self.member_price_grid,1)
        tools=QHBoxLayout();self.member_price_add=_button('지정가 등록·수정',self.edit_member_price,tools);self.member_price_delete=_button('지정가 삭제',self.remove_member_price,tools);_button('조회',self.refresh_member_prices,tools);body.addLayout(tools);self.tabs.addTab(panel,'회원지정가')

    def refresh_member_prices(self):
        identifier=self.record.get('id');allowed=bool(identifier) and can_action(self.store.actor,'members','edit')
        self.member_price_add.setEnabled(allowed);self.member_price_delete.setEnabled(bool(identifier) and can_action(self.store.actor,'members','delete'))
        if not identifier:self.member_price_grid.fill([]);return
        try:
            records=self.store.product_member_prices(identifier);self.member_price_grid.fill([[r['code'],r['name'],r['price'],'유효' if r['active'] else '무효'] for r in records],records);self.member_price_note.setText(f'{len(records):,}명 지정가 · 기본단위 {self.record["price_basis"]}{self.record["base_unit"]}당 · 회원 지정가는 특매보다 우선 적용됩니다.')
        except PermissionError:
            self.member_price_grid.fill([]);self.member_price_note.setText('회원지정가를 보려면 회원관리·회원지정가 메뉴 권한이 필요합니다.');self.member_price_add.setEnabled(False);self.member_price_delete.setEnabled(False)

    def edit_member_price(self):
        if not self.record.get('id'):return
        try:members=[r for r in self.store.members() if r['active']]
        except PermissionError as exc:self.error_label.setText(str(exc));return
        selected=self.member_price_grid.selected() or {};dialog=EntryDialog('상품 회원지정가',self)
        member=_combo([(f"{r['code']} · {r['name']}",r['id']) for r in members],selected.get('member_id'));dialog.form.addRow('회원',member);price=dialog.field('price','지정 판매가',selected.get('price',self.record['sale_price']))
        dialog.finish(lambda:self.store.save_member_price(dict(member_id=member.currentData(),product_id=self.record['id'],price=price.text())))
        if dialog.exec()==QDialog.DialogCode.Accepted:self.refresh_member_prices()

    def remove_member_price(self):
        record=self.member_price_grid.selected()
        if record and _confirm(self,'회원지정가 삭제',f"{record['name']} 회원의 지정가를 삭제할까요?"):
            try:self.store.delete_member_price(record['id']);self.refresh_member_prices()
            except (ValueError,PermissionError) as exc:self.error_label.setText(str(exc))

    def _units_tab(self):
        widget = QWidget()
        body = QVBoxLayout(widget)
        note = QLabel("확장단위 1개 = 기본단위 환산수량입니다. 예: 기본단위 kg, 박스 1개 = 12.000 kg.\n확장단위 매입·판매단가는 별도로 등록하며 특매가를 자동 환산하지 않습니다.")
        note.setWordWrap(True)
        body.addWidget(note)
        self.unit_table = DataGrid(["단위명", "바코드", "기본단위 환산수량", "매입단가", "판매단가", "사용"])
        body.addWidget(self.unit_table, 1)
        actions = QHBoxLayout()
        self.unit_buttons = [
            _button("확장단위 추가", self.add_unit, actions, True),
            _button("수정", self.edit_unit, actions),
            _button("삭제", self.delete_unit, actions),
        ]
        actions.addStretch()
        body.addLayout(actions)
        self.unit_table.itemDoubleClicked.connect(lambda *_: self.edit_unit())
        self.tabs.addTab(widget, "확장단위")

    def pick_supplier(self):
        picker = PartnerPicker(self.store, "supplier", self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            index = self.supplier.findData(picker.record["id"])
            self.supplier.setCurrentIndex(index)

    def _fill_category(self, key, records, current=""):
        field = self.fields[key]
        field.blockSignals(True)
        field.clear()
        field.addItem("선택 안 함", "")
        for row in records:
            old_path = [self.record.get(key, "") for key in ("category", "category_mid", "category_small")[:row["level"]]]
            if row["active"] or row["path"] == old_path:
                field.addItem(row["name"], row["id"])
        field.setText(current)
        field.blockSignals(False)

    def reload_categories(self):
        self.category_records = self.store.categories()
        path = [self.record.get(key, "") for key in CATEGORY_FIELDS] if self.record else DEFAULT_PRODUCT_CATEGORY
        self._fill_category("category", [r for r in self.category_records if r["level"] == 1])
        self.set_category_path(path)

    def apply_category_id(self,identifier):
        fresh=self.store.categories();record=next((r for r in selectable_category_records(fresh) if r['id']==identifier),None)
        if record is None:
            self.error_label.setText('분류가 변경되었거나 무효 상태입니다. 다시 검색해 선택해 주세요.');return False
        self.reload_categories();self.set_category_path(record['path']);self.error_label.clear();return True

    def set_category_path(self, path):
        path = list(path) + [""] * (3 - len(path))
        self.fields["category"].setText(path[0])
        self.reload_middle()
        self.fields["category_mid"].setText(path[1])
        self.reload_small()
        self.fields["category_small"].setText(path[2])
        for key,display in self.category_displays.items():display.setText(self.fields[key].text() or '선택 없음')

    def reload_middle(self, *_):
        path = [self.fields["category"].text()]
        self._fill_category("category_mid", [r for r in self.category_records if r["level"] == 2 and r["path"][:-1] == path])
        self.reload_small()

    def reload_small(self, *_):
        path = [self.fields["category"].text(), self.fields["category_mid"].text()]
        self._fill_category("category_small", [r for r in self.category_records if r["level"] == 3 and r["path"][:-1] == path])

    def choose_category(self,query=''):
        dialog = CategorySearchDialog(self.store, self, query=query)
        dialog.query.setFocus()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_category_id(dialog.record['id'])

    def category_menu(self, key):
        """Pick one registered level, with its ancestors validated again on apply."""
        level = CATEGORY_FIELDS.index(key) + 1
        parent_path = [self.fields[k].text() for k in CATEGORY_FIELDS[:level-1]]
        menu = QMenu(self)
        for row in selectable_category_records(self.store.categories()):
            if row['level'] != level or row['path'][:-1] != parent_path:
                continue
            choice = menu.addAction(row['name'])
            choice.setData(row['id']); choice.setCheckable(True)
            choice.setChecked(row['name'] == self.fields[key].text())
            choice.triggered.connect(lambda checked=False, identifier=row['id']: self.apply_category_id(identifier))
        if not menu.actions():
            menu.addAction('먼저 상위 분류를 선택하거나 분류를 등록하세요.').setEnabled(False)
        menu.aboutToHide.connect(menu.deleteLater)
        return menu

    def open_category_menu(self, key):
        button = self.category_buttons[key]
        menu = self.category_menu(key)
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))

    def update_margin(self):
        try:
            cost = Decimal(self.purchase_price.text().replace(",", ""))
            price = Decimal(self.sale_price.text().replace(",", ""))
            margin = (price - cost) * 100 / price if price > 0 else Decimal(0)
            self.margin.setText(f"{margin:,.2f} %")
            self.margin.setStyleSheet("color:#bd3232;" if margin < 0 else "color:#156757;")
        except (InvalidOperation, ZeroDivisionError):
            self.margin.setText("—")

    def values(self):
        data = {key: field.text().strip() for key, field in self.fields.items()}
        for key in ("category", "category_mid", "category_small"):
            if data[key] and not isinstance(self.fields[key].currentData(), int):
                raise ValueError("기초관리 → 상품 분류에서 먼저 등록한 분류를 선택하세요.")
        data.update(base_unit=self.unit.currentText().strip(), price_basis=self.price_basis.currentData(), supplier_id=self.supplier.currentData(),
                    tax_mode=self.tax_mode.currentData(), tracked=self.tracked.isChecked(),
                    active=self.product_status.currentData() != "무효", retirement_target=self.product_status.currentData() == "퇴출대상", memo=self.memo.toPlainText().strip())
        return data

    def save(self, close=True):
        try:
            data=self.values();data['_expected_token']=self.record.get('_edit_token')
            self.saved_id = self.store.save_product(data, self.record.get("id"))
            self.record = self.store.catalog_product(self.saved_id)
            self.fields["code"].setText(self.record["code"])
            self.reload_categories()
            from .navigation import mark_saved
            mark_saved(self)
            self.error_label.clear()
            self.refresh_details()
            self.saved.emit(self.saved_id)
        except (ValueError, PermissionError) as exc:
            self.error_label.setStyleSheet('color:#bd3232;')
            self.error_label.setText(str(exc))
            return False
        if close:
            self.accept()
        return True

    def apply_changes(self):
        if not can_action(self.store.actor, 'products', 'create'):
            self.error_label.setText('새 상품을 등록할 권한이 없습니다.');return False
        if not self.save(False):return False
        self.last_saved_id = self.saved_id
        path = [self.fields[key].text() for key in CATEGORY_FIELDS]
        self.record = {}; self.saved_id = None
        for key, field in self.fields.items():
            if key not in CATEGORY_FIELDS:field.setText('0' if key in {'purchase_price','sale_price','min_qty'} else '')
        self.memo.clear(); self.product_status.setCurrentIndex(0); self.tracked.setChecked(True)
        self.tax_mode.setCurrentIndex(self.tax_mode.findData('exempt'))
        self.unit.setCurrentText('g'); self.price_basis.setCurrentIndex(self.price_basis.findData(100))
        self.reload_categories(); self.set_category_path(path)
        self.stock_table.fill([]); self.audit_table.fill([]); self.unit_table.fill([])
        self.setWindowTitle('새 상품 등록'); self.heading.setText('새 상품 등록')
        self.refresh_details(); self.tabs.setCurrentIndex(0)
        from .navigation import mark_saved
        mark_saved(self)
        self.error_label.setStyleSheet('color:#156757;')
        self.error_label.setText('등록 완료 · 새 상품을 입력하세요. 분류·공급사만 유지합니다.')
        self.fields['name'].setFocus()
        return True

    def next_record(self):
        # Legacy callers use the same single apply operation, not another button.
        return self.apply_changes()

    def cancel(self):
        """Explicit cancel discards only the current inputs, never saved products."""
        from .navigation import mark_saved
        mark_saved(self)  # Forget any recovery draft without writing catalog data.
        super().reject()

    @staticmethod
    def _audit_text(detail):
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (TypeError, ValueError):
                return detail
        if not isinstance(detail, dict):
            return str(detail)
        changes = detail.get("changes", detail)
        parts = []
        for key, change in changes.items():
            label = PRODUCT_LABELS.get(key, key)
            if isinstance(change, dict) and "old" in change:
                parts.append(f"{label}: {change.get('old', '')} → {change.get('new', '')}")
            elif isinstance(change, (list, tuple)) and len(change) == 2:
                parts.append(f"{label}: {change[0]} → {change[1]}")
            else:
                parts.append(f"{label}: {change}")
        return " / ".join(parts)

    def refresh_details(self, *_):
        record_id = self.record.get("id")
        if record_id:
            try:
                latest = self.store.catalog_product(record_id)
            except ValueError:
                latest = self.record
            self.record = dict(latest)
        self.stock_quantity.setText(f"{_quantity(self.record.get('stock_qty', 0))} {self.record.get('base_unit', self.unit.currentText())}")
        self.stock_cost.setText(f"{_won(self.record.get('stock_cost', 0))} 원")
        for key,label in (('stock_qty',self.stock_quantity),('stock_cost',self.stock_cost)):
            label.setStyleSheet('color:#B42318;font-weight:700' if Decimal(str(self.record.get(key,0)))<0 else '')
        def timestamp(key, default):
            value = self.record.get(key)
            if not value:
                return default
            try:
                return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
            except ValueError:
                return str(value)
        self.meta.setText(f"등록 {timestamp('created_at', '저장 전')}  ·  수정 {timestamp('updated_at', '—')}")
        for button in self.unit_buttons:
            button.setEnabled(bool(record_id))
        self.refresh_member_prices()
        if not record_id:
            for key in ("purchases", "sales"):
                self.history_tables[key].fill([])
                self.history_summaries[key].setText("상품을 먼저 저장하면 이력을 조회할 수 있습니다.")
            return
        history = self.store.product_history(record_id)
        kind_labels = {"purchase": "매입", "purchase_return": "매입반품", "sale": "판매", "sale_return": "판매반품"}
        state_labels = {"draft": "초안", "posted": "확정", "cancelled": "취소"}
        for key in ("purchases", "sales"):
            records = history.get(key, [])
            enabled, start, end = self.history_filters[key]
            if enabled.isChecked():
                first, last = start.date().toString("yyyy-MM-dd"), end.date().toString("yyyy-MM-dd")
                records = [r for r in records if first <= str(r["date"])[:10] <= last]
            self.history_tables[key].fill([
                [r["date"], r["number"], kind_labels.get(r["kind"], r["kind"]), r.get("partner_name", ""),
                 Decimal(str(r.get("qty", r.get("input_qty", 0)))), r.get("unit_name", ""), r["unit_price"], r["total"],
                 state_labels.get(r["status"], r["status"])] for r in records], records)
            posted = [r for r in records if r["status"] == "posted"]
            total = sum((-1 if "return" in r["kind"] else 1) * r["total"] for r in posted)
            by_unit = {}
            for row in posted:
                unit = row.get("unit_name", "")
                group = by_unit.setdefault(unit, {"qty": Decimal(0), "amount": 0, "prices": []})
                sign = -1 if "return" in row["kind"] else 1
                group["qty"] += sign * Decimal(str(row.get("qty", row.get("input_qty", 0))))
                group["amount"] += sign * row["total"]
                if sign > 0:
                    group["prices"].append(row["unit_price"])
            unit_summaries = []
            for unit, group in sorted(by_unit.items()):
                summary = f"{unit}: 순수량 {group['qty']:,.3f}"
                if group["prices"]:
                    summary += f" · 최저 {_won(min(group['prices']))} / 최고 {_won(max(group['prices']))} 원"
                if group["qty"] > 0:
                    summary += f" · 평균 {Decimal(group['amount']) / group['qty']:,.2f} 원"
                unit_summaries.append(summary)
            text = f"조회 {len(records):,}행  ·  확정 금액 (반품 차감) {_won(total)} 원  ·  초안·취소 제외"
            if unit_summaries:
                text += "\n" + "\n".join(unit_summaries)
            self.history_summaries[key].setText(text)
        stock = history.get("stock", [])
        self.stock_table.fill([[r["date"], kind_labels.get(r["kind"], r["kind"]), Decimal(str(r["qty_delta"])),
                               r.get("cost_delta", 0), Decimal(str(r["balance_qty"])), r["balance_cost"], r.get("reason", "")]
                              for r in stock], stock)
        audit = self.store.product_audit(record_id)
        from .catalog_audit import audit_rows
        changes=audit_rows(audit,PRODUCT_LABELS)
        if self.audit_period.isChecked():
            first,last=self.audit_start.date().toString('yyyy-MM-dd'),self.audit_end.date().toString('yyyy-MM-dd');changes=[r for r in changes if first<=r[5][:10]<=last]
        if self.audit_field.currentData():changes=[r for r in changes if r[0]==self.audit_field.currentData()]
        self.audit_table.fill(changes)
        self.refresh_units()

    def refresh_units(self):
        units = self.store.units(self.record["id"])
        self.unit_table.fill([[r["name"], r["barcode"], Decimal(str(r["factor"])), r["purchase_price"],
                               r["sale_price"], "사용" if r["active"] else "중지"] for r in units], units)

    def _unit_editor(self, record=None):
        if not self.record.get("id"):
            return
        record = dict(record or {})
        editor = EntryDialog("확장단위 수정" if record else "확장단위 추가", self)
        editor.field("name", "단위명 *", record.get("name", ""))
        editor.field("barcode", "바코드", record.get("barcode", ""))
        editor.field("factor", f"1단위당 {self.record['base_unit']} 수량 *", record.get("factor", "1.000"))
        editor.field("purchase_price", "확장단위 매입단가 (원)", record.get("purchase_price", 0))
        editor.field("sale_price", "확장단위 판매단가 (원)", record.get("sale_price", 0))
        # One compact row: the conversion and both prices stay in view together.
        controls = list(editor.fields.items())
        while editor.form.count():
            item = editor.form.takeAt(0)
            widget = item.widget()
            if widget and widget not in editor.fields.values():
                widget.deleteLater()
        panel = QWidget()
        compact = QHBoxLayout(panel)
        compact.setContentsMargins(0,0,0,0)
        labels = {"name":"단위명 *","barcode":"확장 바코드","factor":f"입수량 ({self.record['base_unit']}) *","purchase_price":"매입단가 (원)","sale_price":"판매단가 (원)"}
        for key,field in controls:
            column = QVBoxLayout()
            column.addWidget(QLabel(labels[key])); column.addWidget(field)
            compact.addLayout(column,2 if key=="barcode" else 1)
        editor.form.addRow(panel)
        editor.resize(1020,260)
        active = QCheckBox("사용")
        active.setChecked(bool(record.get("active", True)))
        editor.form.addRow(active)
        editor.finish(lambda: self.store.save_unit(dict(editor.values(), product_id=self.record["id"], active=active.isChecked()), record.get("id")))
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.refresh_details()

    def add_unit(self):
        self._unit_editor()

    def edit_unit(self):
        record = self.unit_table.selected()
        if record:
            self._unit_editor(record)

    def delete_unit(self):
        record = self.unit_table.selected()
        if record and _confirm(self, "확장단위 삭제", f"'{record['name']}' 단위를 삭제할까요?\n거래 이력이 있으면 삭제할 수 없습니다."):
            try:
                self.store.delete_unit(record["id"])
                self.refresh_details()
            except (ValueError, PermissionError) as exc:
                self.error_label.setText(str(exc))


class ProductsPage(Page):
    product_saved = Signal(int)

    def __init__(self, window):
        super().__init__(window, "상품장", "상품 · 기준단가 · 확장단위 · 입출고 이력을 한곳에서 관리합니다.")
        self.window = window
        self.product_dialogs={}
        self._catalog_cache_key=None;self._catalog_filter_key=None;self._catalog_page=0;self._catalog_page_size=500;self._catalog_matches=[];self._catalog_rendering=False
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(250);self.search_timer.timeout.connect(self.run_delayed_search)
        self.search = QLineEdit()
        self.search.setPlaceholderText("상품코드 · 바코드 · 상품명 · 규격")
        self.search.setMinimumWidth(230)
        self.scan = ScanField()
        self.scan.setMinimumWidth(200)
        self.scan.scanned.connect(self.scan_barcode)
        self.category = QComboBox()
        self.supplier = QComboBox()
        self.supplier.setObjectName('catalogSupplierFilter')
        self.supplier.setAccessibleName('상품장 공급사 선택')
        self.supplier.setMinimumContentsLength(14)
        self.supplier.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.supplier.setMaxVisibleItems(20)
        self.supplier.view().setUniformItemSizes(True)
        arrow = (Path(__file__).resolve().parent/'assets'/'step-down.svg').as_posix()
        self.supplier.setStyleSheet(f'''QComboBox#catalogSupplierFilter::drop-down {{width:25px;border-left:1px solid #CFDCE2;background:#EDF4F0;}}
            QComboBox#catalogSupplierFilter::down-arrow {{image:url("{arrow}");width:12px;height:9px;}}''')
        self.supplier_search_button = action('', self.pick_supplier_filter)
        self.supplier_search_button.setObjectName('catalogSupplierSearch')
        self.supplier_search_button.setIcon(search_icon())
        self.supplier_search_button.setAccessibleName('공급사 검색')
        self.supplier_search_button.setToolTip('공급사명 또는 코드로 검색해 상품장 조회 조건에 적용합니다. 더블클릭·Enter로 선택하고 닫기·Esc로 취소합니다.')
        self.status_filter = _combo([("전체 상태", ""), ("유효", "유효"), ("무효", "무효"), ("퇴출대상", "퇴출대상")], "유효")
        self.low_only = QCheckBox("최소재고 이하")
        self.middle_filter=QComboBox();self.small_filter=QComboBox()
        self.tracked_filter=_combo([('재고관리 전체',None),('재고관리 상품',True),('재고관리 제외',False)])
        self.tax_filter=_combo([('과면세 전체',''),('과세','taxable'),('면세','exempt')])
        self.period_filter=_combo([('기간조건 없음',''),('신규 등록일','created_at'),('상품 수정일','updated_at')])
        self.period_start,self.period_end=date_field(),date_field()
        self.period_start.setEnabled(False);self.period_end.setEnabled(False)
        filters = QHBoxLayout()
        for label, widget in (("검색", self.search), ("분류", self.category), ("공급사", self.supplier)):
            filters.addWidget(QLabel(label))
            filters.addWidget(widget)
            if widget is self.supplier:
                filters.addWidget(self.supplier_search_button)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.low_only)
        self.body.addLayout(filters)
        details=QHBoxLayout()
        for label,widget in (('중분류',self.middle_filter),('소분류',self.small_filter),('재고관리',self.tracked_filter),('과면세',self.tax_filter)):
            details.addWidget(QLabel(label));details.addWidget(widget,1)
        self.body.addLayout(details)
        dates=QHBoxLayout();dates.addWidget(self.period_filter);dates.addWidget(self.period_start);dates.addWidget(QLabel('~'));dates.addWidget(self.period_end);dates.addStretch()
        dates.addWidget(QLabel('등록·수정일 조건으로 새 상품/변경 상품을 찾아 라벨 출력할 수 있습니다.'));self.body.addLayout(dates)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("USB 바코드"))
        tools.addWidget(self.scan)
        self.scan_result = QLabel()
        self.scan_result.setObjectName("muted")
        tools.addWidget(self.scan_result, 1)
        _button("상세 / 수정", self.edit, tools)
        _button("삭제", self.delete, tools)
        _button("분류 일괄변경", self.bulk_category, tools)
        _button("라벨 인쇄", self.print_labels, tools)
        _button("조회", self.refresh, tools)
        self.body.addLayout(tools)
        self.grid = self.table(["상품코드", "상품명", "대분류", "중분류", "규격", "바코드", "공급사", "매입단가", "판매단가", "현재고", "단위", "재고 원가액", "상태","소분류","과면세","재고관리","단가 기준"])
        self.grid.verticalHeader().setVisible(True);self.grid.verticalHeader().setFixedWidth(65);self.grid.verticalHeader().setToolTip('검색 결과의 순번 · 현재 정렬 순서대로 1부터 표시합니다.')
        self.body.removeWidget(self.grid);self.catalog_splitter=QSplitter(Qt.Orientation.Horizontal);self.catalog_splitter.addWidget(self.grid)
        panel=QWidget();right=QVBoxLayout(panel);right.setContentsMargins(8,0,0,0);right.addWidget(QLabel('상품 분류 · 대 / 중 / 소'))
        self.category_path_label=QLabel('전체 분류');self.category_path_label.setWordWrap(True);right.addWidget(self.category_path_label)
        self.category_tree=CategoryTree();self.category_tree.setMinimumWidth(230);self.category_tree.itemSelectionChanged.connect(self.tree_category_selected);right.addWidget(self.category_tree,1)
        self.selected_product_summary=QLabel('상품을 선택하면 과면세와 분류를 표시합니다.');self.selected_product_summary.setWordWrap(True);right.addWidget(self.selected_product_summary);_button('선택 상품 등록정보',self.edit,right)
        _button('전체 분류 보기',lambda:self.set_tree_path(()),right);self.catalog_splitter.addWidget(panel);self.catalog_splitter.setStretchFactor(0,4);self.catalog_splitter.setStretchFactor(1,1);self.catalog_splitter.setSizes([850,260]);self.body.addWidget(self.catalog_splitter,1)
        for column, width in enumerate((85, 185, 80, 80, 80, 130, 130, 100, 100, 95, 60, 115, 65)):
            self.grid.setColumnWidth(column, width)
        self.summary = QLabel()
        self.summary.setObjectName("summary")
        self.body.addWidget(self.summary)
        paging=QHBoxLayout();self.previous_page=action('이전 500개',lambda:self.move_catalog_page(-1));self.next_page=action('다음 500개',lambda:self.move_catalog_page(1));paging.addWidget(self.previous_page);paging.addWidget(self.next_page)
        self.page_label=QLabel('');paging.addWidget(self.page_label,1);self.body.addLayout(paging)
        self.add_button = _button("새 상품 등록", self.add, self.actions, True)
        _button('엑셀 상품 등록',self.import_excel,self.actions)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.context_menu)
        self.grid.itemDoubleClicked.connect(lambda *_: self.edit())
        self.grid.itemSelectionChanged.connect(self.selection_changed)
        self.grid.horizontalHeader().setSortIndicator(0,Qt.SortOrder.AscendingOrder)
        self.grid.horizontalHeader().sortIndicatorChanged.connect(self.catalog_sort_changed)
        self.search.textChanged.connect(lambda *_:self.search_timer.start())
        self.search.returnPressed.connect(self.refresh)
        for control in (self.category, self.supplier):
            control.currentIndexChanged.connect(self.refresh)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.low_only.toggled.connect(self.refresh)
        for control in (self.middle_filter,self.small_filter,self.tracked_filter,self.tax_filter,self.period_filter):control.currentIndexChanged.connect(self.refresh)
        for control in (self.period_start,self.period_end):control.dateChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        self.search_timer.stop()
        self.store.require_menu('products')
        cache_key=(self.store.actor['id'],self.store.catalog_revision())
        metadata_changed = cache_key!=self._catalog_cache_key
        if metadata_changed:
            products=self.store.products();categories=self.store.categories();suppliers=self.store.catalog_suppliers()
            self._catalog_all_products=products;self._category_records=categories;self._catalog_suppliers=suppliers
            self._catalog_search_index={p['id']:'\n'.join(str(p.get(key,'')) for key in ('name','code','barcode','specification','keywords','receipt_name')).casefold()+'\n'+'\n'.join(p.get('unit_barcodes',[])).casefold() for p in products}
            self._catalog_cache_key=cache_key
        all_products=self._catalog_all_products
        current_category, current_supplier = self.category.currentData(), self.supplier.currentData()
        self.category.blockSignals(True)
        self.supplier.blockSignals(True)
        self.category.clear()
        self.category.addItem("전체 분류", "")
        for category in sorted({p["category"] for p in all_products if p["category"]}|{r['name'] for r in self._category_records if r['level']==1}):
            self.category.addItem(category, category)
        self.category.setCurrentIndex(max(0, self.category.findData(current_category)))
        suppliers = self._catalog_suppliers
        supplier_map = {p["id"]: p["name"] for p in suppliers}
        if metadata_changed or not self.supplier.count():
            from .menu_icons import menu_icon
            self.supplier.clear()
            self.supplier.addItem("전체 공급사", None)
            for partner in suppliers:
                caption = partner['name'] + (' (무효)' if not partner['active'] else '')
                self.supplier.addItem(menu_icon('suppliers'), caption, partner['id'])
                self.supplier.setItemData(self.supplier.count()-1, f"{partner['code']} · {caption}", Qt.ItemDataRole.ToolTipRole)
            self.supplier.setCurrentIndex(max(0, self.supplier.findData(current_supplier)))
        self.supplier.setToolTip(self.supplier.currentText()+'\n목록에서 선택하거나 옆 돋보기로 검색하세요.')
        self.category.blockSignals(False)
        self.supplier.blockSignals(False)
        for field,key,parent_key in ((self.middle_filter,'category_mid','category'),(self.small_filter,'category_small','category_mid')):
            old=field.currentData();field.blockSignals(True);field.clear();field.addItem('전체','')
            options=[p for p in all_products if (not self.category.currentData() or p['category']==self.category.currentData())]
            if key=='category_small' and self.middle_filter.currentData():options=[p for p in options if p['category_mid']==self.middle_filter.currentData()]
            values={p[key] for p in options if p[key]}
            for record in self._category_records:
                index=1 if key=='category_mid' else 2;path=record['path']
                if len(path)<=index or self.category.currentData() and path[0]!=self.category.currentData():continue
                if index==2 and self.middle_filter.currentData() and path[1]!=self.middle_filter.currentData():continue
                values.add(path[index])
            for value in sorted(values):field.addItem(value,value)
            field.setCurrentIndex(max(0,field.findData(old)));field.blockSignals(False)
        query_key=(cache_key,self.search.text(),self.category.currentData(),self.supplier.currentData(),self.middle_filter.currentData(),self.small_filter.currentData(),self.tax_filter.currentData(),self.tracked_filter.currentData(),self.period_filter.currentData(),self.period_start.date().toJulianDay(),self.period_end.date().toJulianDay(),self.status_filter.currentData(),self.low_only.isChecked())
        if query_key==self._catalog_filter_key:return
        term=self.search.text().strip().casefold();category=self.category.currentData();supplier=self.supplier.currentData()
        rows=[p for p in all_products if (not term or term in self._catalog_search_index[p['id']]) and (not category or p['category']==category) and (supplier is None or p['supplier_id']==supplier)]
        for field,key in ((self.middle_filter,'category_mid'),(self.small_filter,'category_small'),(self.tax_filter,'tax_mode')):
            if field.currentData():rows=[r for r in rows if r[key]==field.currentData()]
        if self.tracked_filter.currentData() is not None:rows=[r for r in rows if bool(r['tracked'])==self.tracked_filter.currentData()]
        period_key=self.period_filter.currentData();self.period_start.setEnabled(bool(period_key));self.period_end.setEnabled(bool(period_key))
        if period_key:
            first,last=self.period_start.date().toString('yyyy-MM-dd'),self.period_end.date().toString('yyyy-MM-dd')
            def local_day(record):
                try:return datetime.fromisoformat(record[period_key]).astimezone().date().isoformat()
                except (ValueError,KeyError,TypeError):return ''
            rows=[r for r in rows if first<=local_day(r)<=last]
        if self.status_filter.currentData():
            rows = [r for r in rows if product_status(r) == self.status_filter.currentData()]
        if self.low_only.isChecked():
            rows = [r for r in rows if r["tracked"] and Decimal(r["stock_qty"]) <= Decimal(r["min_qty"])]
        self._catalog_supplier_map=supplier_map;self._catalog_matches=rows;self._catalog_page=0
        self.sort_catalog_matches();self.render_catalog_page();self._catalog_filter_key=query_key
        self.refresh_category_tree()
        totals = {}
        for r in rows:
            if r["tracked"]:
                totals[r["base_unit"]] = totals.get(r["base_unit"], Decimal(0)) + Decimal(r["stock_qty"])
        quantities = " / ".join(f"{value:,.3f} {unit}" for unit, value in sorted(totals.items())) or "—"
        self.summary.setText(f"검색 {len(rows):,} / 전체 {len(all_products):,}품목 · 왼쪽 순번 1~{len(rows):,} · 과=과세 / 면=면세 · 재고 {quantities} · 원가 합계 {_won(sum(r['stock_cost'] for r in rows if r['tracked']))} 원")

    def pick_supplier_filter(self):
        try:
            self.refresh()
            dialog = SupplierFilterDialog(self.store, self, self._catalog_suppliers, self.supplier.currentData())
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.record is None:
                return
            self.store.require_menu('products')
            self.refresh()
            index = self.supplier.findData(dialog.record['id'])
            if index < 0:
                raise ValueError('선택한 공급사가 삭제되었거나 변경되었습니다. 다시 검색하세요.')
            self.supplier.setCurrentIndex(index)
        except (ValueError, PermissionError, OSError) as exc:
            self.fail(exc)

    def run_delayed_search(self):
        try:self.refresh()
        except (ValueError,PermissionError,OSError) as exc:
            self._catalog_cache_key=None;self._catalog_filter_key=None;self._catalog_matches=[];self.grid.fill([]);self.summary.clear();self.fail(exc)

    def catalog_values(self,rows):
        suppliers=self._catalog_supplier_map
        return [[r['code'],r['name'],r['category'],r['category_mid'],r['specification'],r['barcode'],suppliers.get(r['supplier_id'],'—'),r['purchase_price'],r['sale_price'],Decimal(r['stock_qty']),r['base_unit'],r['stock_cost'],product_status(r),r['category_small'],'과세' if r['tax_mode']=='taxable' else '면세','관리' if r['tracked'] else '제외',f"{r['price_basis']}{r['base_unit']}당"] for r in rows]

    def sort_catalog_matches(self):
        header=self.grid.horizontalHeader();column=header.sortIndicatorSection();descending=header.sortIndicatorOrder()==Qt.SortOrder.DescendingOrder
        if column<0:return
        self._catalog_matches.sort(key=(lambda r:r['code']) if column==0 else lambda r:self.catalog_values([r])[0][column],reverse=descending)

    def catalog_sort_changed(self,*_):
        if self._catalog_rendering or not self._catalog_matches:return
        self.sort_catalog_matches();self.render_catalog_page()

    def move_catalog_page(self,direction):
        self.store.require_menu('products');self._catalog_page+=direction;self.render_catalog_page()

    def render_catalog_page(self):
        from .tax_display import tax_icon,tax_style
        count=len(self._catalog_matches);size=self._catalog_page_size
        self._catalog_page=max(0,min(self._catalog_page,max(0,(count-1)//size)))
        start=self._catalog_page*size;rows=self._catalog_matches[start:start+size]
        icons={mode:tax_icon(mode) for mode in ('taxable','exempt')}
        self._catalog_rendering=True;blocked=self.grid.blockSignals(True);self.grid.setUpdatesEnabled(False)
        try:
            self.grid.fill(self.catalog_values(rows),rows)
            sorting=self.grid.isSortingEnabled();self.grid.setSortingEnabled(False)
            for index in range(self.grid.rowCount()):
                record=self.grid.item(index,0).data(Qt.ItemDataRole.UserRole);mode=record['tax_mode'];letter,caption,fg,bg=tax_style(mode)
                self.grid.item(index,1).setIcon(icons[mode]);self.grid.item(index,1).setToolTip(f"{letter} · {caption} / {record['name']}")
                item=self.grid.item(index,14);item.setText(letter+' · '+caption);item.setForeground(QColor(fg));item.setBackground(QColor(bg))
            self.grid.setSortingEnabled(sorting)
            self.grid.setVerticalHeaderLabels([str(start+i+1) for i in range(len(rows))])
        finally:
            self.grid.blockSignals(blocked);self.grid.setUpdatesEnabled(True);self._catalog_rendering=False
        self.previous_page.setEnabled(self._catalog_page>0);self.next_page.setEnabled(start+len(rows)<count)
        self.page_label.setText(f"표시 {start+1 if count else 0:,}~{start+len(rows):,} / 검색 {count:,}개 · {self._catalog_page+1}/{max(1,(count+size-1)//size)}쪽 · 정렬·엑셀은 검색 전체 기준")
        self.selection_changed()

    def export(self):
        from .widgets import authorize_output,export_rows
        if not authorize_output(self):return
        self.refresh()
        return export_rows(self,self.title,[self.grid.horizontalHeaderItem(i).text() for i in range(self.grid.columnCount())],self.catalog_values(self._catalog_matches))

    def print(self):
        from .widgets import authorize_output
        if not authorize_output(self):return
        self.refresh();grid=DataGrid([self.grid.horizontalHeaderItem(i).text() for i in range(self.grid.columnCount())])
        grid.horizontalHeader().setSortIndicator(self.grid.horizontalHeader().sortIndicatorSection(),self.grid.horizontalHeader().sortIndicatorOrder())
        try:grid.fill(self.catalog_values(self._catalog_matches));grid.print_pages(self,self.title,'검색 결과 전체')
        finally:grid.deleteLater()

    def refresh_category_tree(self):
        selected=tuple(value for value in (self.category.currentData(),self.middle_filter.currentData(),self.small_filter.currentData()) if value)
        tree_key=(self._catalog_cache_key,selected)
        if tree_key==getattr(self,'_catalog_tree_key',None):return
        self._catalog_tree_key=tree_key
        self.category_tree.blockSignals(True);self.category_tree.clear();root=QTreeWidgetItem(self.category_tree,['전체분류']);root.setData(0,Qt.ItemDataRole.UserRole,());items={};current=root
        for record in self._category_records:
            parent=items.get(record['parent_id'],root);item=QTreeWidgetItem(parent,[f"{record['name']} ({record['product_count']:,})"]);item.setIcon(0,folder_icon(record['level'],record['active']));item.setData(0,Qt.ItemDataRole.UserRole,tuple(record['path']));item.setToolTip(0,' / '.join(record['path']));items[record['id']]=item
            if tuple(record['path'])==selected:current=item
        self.category_tree.expandToDepth(0);self.category_tree.setCurrentItem(current)
        parent=current.parent()
        while parent:parent.setExpanded(True);parent=parent.parent()
        self.category_tree.blockSignals(False);self.category_path_label.setText(' / '.join(selected) or '전체 분류')

    def tree_category_selected(self):
        item=self.category_tree.currentItem()
        if item:self.set_tree_path(item.data(0,Qt.ItemDataRole.UserRole) or ())

    def set_tree_path(self,path):
        # Populate dependent selectors before the one final table refresh.
        for control in (self.category,self.middle_filter,self.small_filter):control.blockSignals(True)
        self.category.setCurrentIndex(max(0,self.category.findData(path[0] if path else '')))
        for control,key,index in ((self.middle_filter,'category_mid',1),(self.small_filter,'category_small',2)):
            control.clear();control.addItem('전체','')
            values={r[key] for r in self._catalog_all_products if all(r[k]==v for k,v in zip(('category','category_mid'),path[:index])) and r[key]}
            values.update(r['path'][index] for r in self._category_records if len(r['path'])>index and tuple(r['path'][:index])==tuple(path[:index]))
            for value in sorted(values):control.addItem(value,value)
            control.setCurrentIndex(max(0,control.findData(path[index] if len(path)>index else '')))
        for control in (self.category,self.middle_filter,self.small_filter):control.blockSignals(False)
        self.refresh()

    def import_excel(self):
        from .catalog_import_ui import CatalogImportDialog
        self.import_dialog=CatalogImportDialog(self.store,self);self.import_dialog.imported.connect(self.refresh);self.import_dialog.show()

    def add(self):
        self.show_product_dialog(None)

    def selection_changed(self):
        record=self.grid.selected()
        if not record:self.selected_product_summary.setText('상품을 선택하면 과면세와 분류를 표시합니다.');self.selected_product_summary.setStyleSheet('');return
        from .tax_display import tax_style
        letter,caption,fg,bg=tax_style(record['tax_mode']);self.selected_product_summary.setText(f"{letter} · {caption}\n{record['name']}\n"+' / '.join(record[k] for k in ('category','category_mid','category_small') if record[k]));self.selected_product_summary.setStyleSheet(f'color:{fg};background:{bg};padding:8px;border-radius:5px;')

    def show_product_dialog(self,record):
        from shiboken6 import isValid
        key=record['id'] if record else None;existing=self.product_dialogs.get(key)
        if existing is not None and isValid(existing) and existing.isVisible() and existing.record.get('id') == key:existing.raise_();existing.activateWindow();return existing
        dialog=ProductDialog(self.store,record,self);dialog.saved.connect(self._product_saved);dialog.setWindowModality(Qt.WindowModality.NonModal);self.product_dialogs[key]=dialog;dialog.show();return dialog

    def _product_saved(self, identifier):
        self.refresh()
        self.product_saved.emit(identifier)

    def edit(self):
        record = self.grid.selected()
        if record:
            return self.show_product_dialog(record)

    def context_menu(self, position):
        row = self.grid.rowAt(position.y())
        if row < 0:
            return
        if row not in {index.row() for index in self.grid.selectedIndexes()}:
            self.grid.selectRow(row)
        self.make_context_menu().exec(self.grid.viewport().mapToGlobal(position))

    def make_context_menu(self):
        menu = QMenu(self)
        selected = bool(self.selected_product_ids())
        editable = selected and can_action(self.store.actor, "products", "edit")
        def option(label, callback, enabled=True, parent=menu):
            item = parent.addAction(label)
            item.setEnabled(enabled)
            item.triggered.connect(lambda checked=False: callback())
            return item
        option("상품 등록정보 / 수정", self.edit, selected)
        menu.addSeparator()
        option("상품분류 이동", self.move_category, editable)
        option("공급사", self.change_supplier, editable)
        for label, key in (("판매가 일괄설정", "sale_price"), ("매입가 일괄설정", "purchase_price"), ("원산지 일괄설정", "origin"), ("최소재고 일괄설정", "min_qty")):
            option(label, lambda field=key, caption=label: self.bulk_field(field, caption), editable)
        menu.addSeparator()
        states = menu.addMenu("상품상태")
        for label, values in (("유효", {"active": True, "retirement_target": False}), ("무효", {"active": False}), ("퇴출대상", {"active": True, "retirement_target": True})):
            option(label, lambda values=values: self.apply_bulk(values), editable, states)
        stock = menu.addMenu("재고관리")
        option("재고관리 사용", lambda: self.apply_bulk({"tracked": True}), editable, stock)
        option("재고관리 안 함", lambda: self.apply_bulk({"tracked": False}), editable, stock)
        tax = menu.addMenu("과/면세")
        option("과세", lambda: self.apply_bulk({"tax_mode": "taxable"}), editable, tax)
        option("면세", lambda: self.apply_bulk({"tax_mode": "exempt"}), editable, tax)
        menu.addSeparator()
        from .permissions import has_menu
        option("라벨 출력", self.print_labels, selected and has_menu(self.store.actor,"labels"))
        option("바코드 복사", self.copy_barcodes, selected)
        columns = menu.addMenu("열 선택")
        for column in range(self.grid.columnCount()):
            item = columns.addAction(self.grid.horizontalHeaderItem(column).text())
            item.setCheckable(True)
            item.setChecked(not self.grid.isColumnHidden(column))
            item.toggled.connect(lambda shown, column=column: self.grid.setColumnHidden(column, not shown))
        option("전체 열 보기", lambda: [self.grid.setColumnHidden(column, False) for column in range(self.grid.columnCount())])
        return menu

    def apply_bulk(self, values):
        ids = self.selected_product_ids()
        if ids and _confirm(self, "상품 일괄 변경", f"선택한 {len(ids):,}개 상품에 적용할까요? 기존 확정 전표는 변경하지 않습니다."):
            try:
                count = self.store.bulk_update_products(ids, values)
                self.refresh()
                self.notify(f"{count:,}개 상품을 변경했습니다.")
            except (ValueError, PermissionError) as exc:
                _error(self, exc)

    def bulk_field(self, key, caption):
        value, accepted = QInputDialog.getText(self, caption, "적용할 값 (가격은 각 상품의 1단위/100g 단가기준을 따릅니다)")
        if accepted:
            self.apply_bulk({key: value})

    def move_category(self):
        dialog = CategoryDialog(self.store, self, select=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            path = dialog.record["path"] + [""] * (3 - len(dialog.record["path"]))
            self.apply_bulk(dict(zip(CATEGORY_FIELDS, path)))

    def change_supplier(self):
        dialog = PartnerPicker(self.store, "supplier", self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_bulk({"supplier_id": dialog.record["id"]})

    def copy_barcodes(self):
        self.store.require_menu("products")
        ids = set(self.selected_product_ids())
        codes = [row["barcode"] for row in self._catalog_all_products if row["id"] in ids and row["barcode"]]
        QApplication.clipboard().setText("\n".join(codes))
        self.notify(f"바코드 {len(codes):,}개를 복사했습니다.")

    def delete(self):
        record = self.grid.selected()
        if record and _confirm(self, "상품 삭제", f"'{record['name']}' 상품을 삭제할까요?\n이력이 있는 상품은 삭제 대신 '사용 상품' 체크를 해제하세요."):
            try:
                self.store.delete_product(record["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                _error(self, exc)

    def focus_scan(self):
        self.scan.setFocus()
        self.scan.selectAll()

    def scan_barcode(self, barcode):
        try:
            result = self.store.lookup_barcode(barcode)
            if not result:
                self.scan_result.setText(f"미등록 바코드: {barcode}")
                self.scan.selectAll()
                return
            controls=(self.category,self.supplier,self.low_only,self.middle_filter,self.small_filter,self.tracked_filter,self.tax_filter,self.period_filter,self.status_filter,self.search)
            blocked=[(control,control.blockSignals(True)) for control in controls]
            try:
                self.category.setCurrentIndex(0);self.supplier.setCurrentIndex(0);self.low_only.setChecked(False)
                for field in (self.middle_filter,self.small_filter,self.tracked_filter,self.tax_filter,self.period_filter):field.setCurrentIndex(0)
                self.status_filter.setCurrentIndex(0);self.search.setText(barcode)
            finally:
                for control,previous in blocked:control.blockSignals(previous)
            self.refresh()
            identifier = result["product"]["id"]
            for row in range(self.grid.rowCount()):
                if self.grid.item(row, 0).data(Qt.ItemDataRole.UserRole)["id"] == identifier:
                    self.grid.setCurrentCell(row, 0)
                    self.grid.selectRow(row)
                    break
            unit = result.get("unit")
            suffix = f" · {unit['name']} 1 = {unit['factor']} {result['product']['base_unit']}" if unit else " · 기본단위"
            self.scan_result.setText(result["product"]["name"] + suffix)
            self.scan.selectAll()
        except (ValueError, PermissionError) as exc:
            self.scan_result.setText(str(exc))

    def selected_product_ids(self):
        ids = []
        for row in sorted({index.row() for index in self.grid.selectedIndexes()}):
            record = self.grid.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if record:
                ids.append(record["id"])
        return ids

    def print_labels(self):
        selected = self.selected_product_ids()
        if not selected:
            self.notify("라벨을 출력할 상품을 먼저 선택하세요. Ctrl 키로 여러 상품을 선택할 수 있습니다.")
            return
        from .labels import LabelDialog
        LabelDialog(self.store, selected, self).exec()

    def bulk_category(self):
        selected = self.selected_product_ids()
        if not selected:
            return
        category, accepted = QInputDialog.getText(self, "상품 분류 일괄변경", f"선택한 {len(selected)}품목의 새 대분류")
        if accepted and category.strip() and _confirm(self, "일괄변경 확인", f"{len(selected)}품목의 대분류를 '{category.strip()}'로 변경할까요?"):
            try:
                self.store.bulk_category(selected, category.strip())
                self.refresh()
            except (ValueError, PermissionError) as exc:
                _error(self, exc)


class PartnersPage(Page):
    def __init__(self, window, kind):
        self.kind, self.window = kind, window
        self.label = "공급사" if kind == "supplier" else "판매처"
        super().__init__(window, f"{self.label} 관리", "거래처 기본정보와 시작 외상잔액을 관리합니다. 거래내역은 거래처 원장에서 확인하세요.")
        self.search = QLineEdit()
        self.search.setPlaceholderText("거래처명 · 코드 · 사업자번호 · 전화번호")
        self.body.addWidget(self.search)
        self.grid = self.table(["코드", f"{self.label}명", "사업자등록번호", "담당자", "전화번호", "은행", "계좌번호", "예금주", "시작 외상잔액", "잔액 기준일", "현재 외상잔액", "유형", "수수료율", "상태"])
        _button(f"{self.label} 등록", self.add, self.actions, True)
        tools = QHBoxLayout()
        _button("수정", self.edit, tools)
        _button("삭제", self.delete, tools)
        actor = self.store.actor
        if actor["role"] == "admin" or "trade" in actor["permissions"]:
            _button("원장 보기", lambda: self.window.open_page("ledger"), tools)
        _button("조회", self.refresh, tools)
        tools.addStretch()
        self.body.insertLayout(2, tools)
        self.grid.itemDoubleClicked.connect(lambda *_: self.edit())
        self.search.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        records = self.store.partners(self.kind, self.search.text())
        self.grid.fill([[r["code"], r["name"], r["business_no"], r["contact"], r["phone"], r["bank"], r["account"],
                         r["account_holder"], r["opening_balance"], r["opening_date"], r.get("balance", 0),
                         "수수료" if r.get("supplier_mode") == "commission" else "직매입", Decimal(r.get("commission_bps", 0)) / 100,
                         "사용" if r["active"] else "중지"] for r in records], records)

    def editor(self, record=None):
        record = dict(record or {})
        dialog = EntryDialog(f"{self.label} {'수정' if record else '등록'}", self)
        for key, label in (("code", "거래처 코드 *"), ("name", f"{self.label}명 *"), ("business_no", "사업자등록번호"),
                           ("contact", "담당자"), ("phone", "전화번호"), ("bank", "은행명"), ("account", "계좌번호"),
                           ("account_holder", "예금주"), ("memo", "메모")):
            dialog.field(key, label, record.get(key, ""))
        dialog.field("opening_balance", "시작 외상잔액 (원)", record.get("opening_balance", 0))
        supplier_mode = _combo([("직매입", "direct"), ("수수료 공급사", "commission")], record.get("supplier_mode", "direct"))
        if self.kind == "supplier":
            dialog.form.addRow("거래 유형", supplier_mode)
            dialog.field("commission_bps", "수수료율 (100 = 1%)", record.get("commission_bps", 0))
        opening_date = QDateEdit(QDate.fromString(record.get("opening_date", date.today().isoformat()), "yyyy-MM-dd"))
        opening_date.setDisplayFormat("yyyy-MM-dd")
        opening_date.setCalendarPopup(True)
        dialog.form.addRow("시작 잔액 기준일", opening_date)
        active = QCheckBox("사용 거래처")
        active.setChecked(bool(record.get("active", True)))
        dialog.form.addRow(active)
        dialog.finish(lambda: self.store.save_partner(dict(dialog.values(), kind=self.kind, active=active.isChecked(),
                                                           supplier_mode=supplier_mode.currentData(), opening_date=opening_date.date().toString("yyyy-MM-dd")), record.get("id")))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def add(self):
        self.editor()

    def edit(self):
        record = self.grid.selected()
        if record:
            self.editor(record)

    def delete(self):
        record = self.grid.selected()
        if record and _confirm(self, "거래처 삭제", f"'{record['name']}'을 삭제할까요?\n거래 이력이 있는 경우 사용을 중지하세요."):
            try:
                self.store.delete_partner(record["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                _error(self, exc)


class UsersPage(Page):
    def __init__(self, window):
        super().__init__(window, "사용자 · 권한", "관리자만 사용자와 업무 접근권한을 관리합니다. 비밀번호는 안전한 해시로 저장됩니다.")
        self.grid = self.table(["사용자 코드", "이름", "역할", "접근권한", "상태"])
        _button("사용자 등록", self.add, self.actions, True)
        _button("정보 / 권한 / 비밀번호", self.edit, self.actions)
        _button("메뉴별 권한 설정", self.permissions, self.actions)
        _button("사용자 삭제", self.delete, self.actions)
        _button("조회", self.refresh, self.actions)
        self.grid.itemDoubleClicked.connect(lambda *_: self.edit())
        self.refresh()

    def refresh(self):
        users = self.store.list_users()
        self.grid.fill([[r["code"], r["name"], "관리자" if r["role"] == "admin" else "일반 사용자",
                         "모든 업무" if r["role"] == "admin" else ", ".join(PERMISSION_LABELS[p] for p in sorted(r["permissions"]) if p in PERMISSION_LABELS) + (" · 세부 제한" if any(p.startswith("deny:") for p in r["permissions"]) else ""),
                         "사용" if r["active"] else "중지"] for r in users], users)

    def editor(self, record=None):
        record = dict(record or {})
        dialog = EntryDialog("사용자 수정" if record else "사용자 등록", self)
        dialog.field("code", "사용자 코드 *", record.get("code", ""))
        dialog.field("name", "이름 *", record.get("name", ""))
        dialog.field("password", "새 비밀번호 (빈칸: 유지)" if record else "비밀번호 *", password=True)
        password_confirmation = QLineEdit()
        password_confirmation.setEchoMode(QLineEdit.EchoMode.Password)
        dialog.form.addRow("새 비밀번호 확인", password_confirmation)
        role = _combo([("일반 사용자", "staff"), ("관리자", "admin")], record.get("role", "staff"))
        dialog.form.addRow("역할", role)
        active = QCheckBox("사용 계정")
        active.setChecked(bool(record.get("active", True)))
        dialog.form.addRow(active)
        permission_widget = QWidget()
        permissions_layout = QVBoxLayout(permission_widget)
        permissions_layout.setContentsMargins(0, 0, 0, 0)
        permission_boxes = {}
        for key, label in PERMISSION_LABELS.items():
            if key == "admin":
                continue
            box = QCheckBox(label)
            box.setChecked(key in record.get("permissions", []))
            permissions_layout.addWidget(box)
            permission_boxes[key] = box
        dialog.form.addRow("일반 사용자 접근권한", permission_widget)
        role.currentIndexChanged.connect(lambda *_: permission_widget.setEnabled(role.currentData() == "staff"))
        permission_widget.setEnabled(role.currentData() == "staff")

        def save():
            values = dialog.values()
            if values.get("password") != password_confirmation.text():
                raise ValueError("새 비밀번호와 확인이 일치하지 않습니다.")
            if not values.get("password") and record:
                values.pop("password", None)
            self.store.save_user(dict(values, role=role.currentData(), active=active.isChecked(),
                                      permissions=[key for key, box in permission_boxes.items() if box.isChecked()] + [p for p in record.get("permissions", []) if p.startswith("deny:")]), record.get("id"))
        dialog.finish(save)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def add(self):
        self.editor()

    def edit(self):
        record = self.grid.selected()
        if record:
            self.editor(record)

    def delete(self):
        record = self.grid.selected()
        if record and _confirm(self, "사용자 삭제", f"'{record['name']}' 계정을 삭제할까요?\n현재 로그인 계정, 마지막 관리자, 업무 이력이 있는 계정은 삭제할 수 없습니다."):
            try:
                self.store.delete_user(record["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                _error(self, exc)

    def permissions(self):
        if hasattr(self.window, "open_page") and self.window.open_page("permissions"):
            selected = self.grid.selected()
            page = self.window.current_page
            if selected:
                page.user.setCurrentIndex(page.user.findData(selected["id"]))


class SettingsPage(Page):
    def factory_reset(self):
        if not hasattr(self.store,'reset_business_data'):
            self.fail('업무 초기화는 단독 사용 중인 기준 PC에서만 실행할 수 있습니다.');return
        if not self.window.navigation.allow_leave(self):return
        try:
            from .factory_reset_ui import BusinessResetDialog
            dialog=BusinessResetDialog(self.window,self)
            if dialog.exec()==QDialog.DialogCode.Accepted and dialog.result_data:self.window.finish_restore(dialog.result_data)
        except (ValueError,PermissionError,OSError) as exc:self.fail(exc)

    def restore_defaults(self):
        from .settings_defaults import SettingsDefaultsDialog,stage_defaults
        dialog=SettingsDefaultsDialog(self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            try:stage_defaults(self,dialog.selected())
            except (ValueError,PermissionError) as exc:self.fail(exc)

    def mail_settings(self):
        from .email_ui import MailSettingsDialog
        MailSettingsDialog(self.store,self).exec()

    def __init__(self, window):
        super().__init__(window, "매장 설정 · 백업", "서버 없이 이 PC의 SQLite 파일에 모든 업무자료를 저장합니다.")
        self.fields = {}
        _button('기본값 복원',self.restore_defaults,self.actions)
        reset=_button('업무자료 초기화',self.factory_reset,self.actions);reset.setObjectName('danger')
        reset.setToolTip('전용 인증·최종 경고 확인 후 보호 백업을 만들고 업무자료를 초기화합니다. 개인 기록과 기존 계정은 보존합니다.')
        reset.setEnabled(hasattr(self.store,'reset_business_data'))
        _button("이메일 발송 설정",self.mail_settings,self.actions)
        _button('점포 등록정보',lambda:self.window.open_page('store_profile'),self.actions)
        from .store_profile_ui import business_registration
        self.business_registration,self.business_registration_grid=business_registration(self.fields,'매장 기본정보 · 사업자 등록 정보 (영수증 표기)')
        self.body.addWidget(self.business_registration)
        appearance=QGroupBox('화면 색감 · 계절 스킨');appearance_form=QFormLayout(appearance)
        from .appearance import THEMES
        self.appearance_theme=_combo([(title,key) for key,title in THEMES.items()])
        appearance_form.addRow('스킨 선택',self.appearance_theme)
        self.holiday_skin=QCheckBox('특정일 자동 스킨 · 석가탄신일(음력 4/8) / 크리스마스(12/25)')
        self.snow_effect=QCheckBox('은은한 눈 효과 · 입력 중/팝업/최소화 시 일시정지')
        self.weather_effect=QCheckBox('첫화면 날씨 예보 연동 효과 · 맑음/구름/비/눈')
        for box in (self.holiday_skin,self.snow_effect,self.weather_effect):appearance_form.addRow(box)
        skin_note=QLabel('기본값은 회색/올리브입니다. 설정 저장 후 적용하고 다음 실행에도 유지합니다.\n랜덤은 프로그램 실행/설정 저장 때 선택하며 작업 중에는 자동 변경하지 않습니다. 금액·반품·경고 구분색은 유지합니다.');skin_note.setWordWrap(True);appearance_form.addRow(skin_note)
        self.body.addWidget(appearance)
        sounds=QGroupBox('프로그램 효과음');sound_form=QFormLayout(sounds)
        from .popup_sound import sound_checkbox
        self.sound_enabled=sound_checkbox(self.store);sound_form.addRow(self.sound_enabled)
        sound_note=QLabel('메뉴·팝업 열기/닫기·저장·수정·삭제·경고에 짧은 효과음을 냅니다. 변경 즉시 현재 계정에 저장됩니다. 배경 음악은 별도 설정입니다.');sound_note.setWordWrap(True);sound_form.addRow(sound_note)
        from .lucky_audio import login_sound_settings
        from .lucky_audio import mouse_sound
        self.mouse_click_enabled=QCheckBox('왼쪽 클릭 소리');self.mouse_click_enabled.setChecked(mouse_sound('click').enabled);self.mouse_click_enabled.toggled.connect(mouse_sound('click').set_enabled);sound_form.addRow(self.mouse_click_enabled)
        self.mouse_context_enabled=QCheckBox('오른쪽 메뉴 소리');self.mouse_context_enabled.setChecked(mouse_sound('context').enabled);self.mouse_context_enabled.toggled.connect(mouse_sound('context').set_enabled);sound_form.addRow(self.mouse_context_enabled)
        from .widgets import action
        sound_form.addRow(action('로그인·경고 사운드 설정',lambda:login_sound_settings(self)))
        self.restore_sounds=QCheckBox('설정 저장 시 기본 효과음·음량으로 복원')
        self.restore_sounds.setToolTip('기본값 복원에서 선택한 대기 항목입니다. 설정 저장 전에는 기존 소리·음량을 유지합니다. 직접 선택한 음원 파일을 삭제하지 않습니다.')
        sound_form.addRow(self.restore_sounds)
        self.body.addWidget(sounds)
        calculation = QGroupBox("금액 계산 · 반올림")
        calculation_form = QFormLayout(calculation)
        self.rounding_mode = _combo([("소수점 2자리 보존 (기본)", "decimal"), ("원 단위 반올림", "won")])
        calculation_form.addRow("전표 행 금액 계산", self.rounding_mode)
        calculation_note = QLabel("단가는 소수점 두 자리까지 입력합니다. 행 금액은 선택한 기준으로 계산하고, 결제·잔액은 0.01원까지 보존합니다.\n설정 변경은 새 전표에만 적용하며 기존 전표의 계산 방식은 유지합니다.")
        calculation_note.setWordWrap(True)
        calculation_form.addRow(calculation_note)
        self.negative_stock=QCheckBox('재고 부족 시 마이너스 재고로 거래 기록 허용')
        calculation_form.addRow(self.negative_stock)
        negative_note=QLabel('부족분 원가는 상품장 매입단가 등으로 잠정 계산됩니다. 매입 입고를 확인하고 실사로 원가 차이를 조정하세요. 수량 0에 원가가 남으면 월마감 전 실사가 필요합니다.')
        negative_note.setWordWrap(True);calculation_form.addRow(negative_note)
        self.body.addWidget(calculation)
        points = QGroupBox("회원 포인트 정책")
        point_form = QFormLayout(points)
        self.point_enabled = QCheckBox("포인트 적립·사용 허용")
        point_form.addRow(self.point_enabled)
        for key, label in (("earn_bps", "적립률 (100 = 1%)"), ("point_min", "최소 사용 포인트"), ("point_step", "포인트 사용 단위")):
            field = QLineEdit()
            self.fields[key] = field
            point_form.addRow(label, field)
        point_form.addRow(QLabel("확정 회원매출에 적립합니다. 허용된 외상판매도 거래금액 기준이며 반품 시 원거래 적립을 역산합니다. 기존 포인트 이력은 유지됩니다."))
        self.body.addWidget(points)
        schedule = QGroupBox("자동 백업 설정")
        schedule_form = QFormLayout(schedule)
        self.backup_mode = QComboBox()
        self.backup_mode.addItem("자동 · 정해진 일정에 백업", "auto")
        self.backup_mode.addItem("수동 · 지금 백업 버튼으로 실행", "manual")
        schedule_form.addRow("백업 방식", self.backup_mode)
        self.backup_frequency = QComboBox()
        for label, value in (("매일", "daily"), ("요일 선택", "weekly"), ("며칠 간격", "interval")):
            self.backup_frequency.addItem(label, value)
        schedule_form.addRow("자동 백업 주기", self.backup_frequency)
        self.backup_time = QTimeEdit()
        self.backup_time.setDisplayFormat("HH:mm")
        schedule_form.addRow("실행 시간 (이 PC 시간)", self.backup_time)
        day_widget = QWidget()
        day_layout = QHBoxLayout(day_widget)
        day_layout.setContentsMargins(0, 0, 0, 0)
        self.backup_weekdays = []
        for label in ("월", "화", "수", "목", "금", "토", "일"):
            box = QCheckBox(label)
            self.backup_weekdays.append(box)
            day_layout.addWidget(box)
        schedule_form.addRow("실행 요일", day_widget)
        self.backup_every = QSpinBox()
        self.backup_every.setRange(1, 365)
        self.backup_every.setSuffix("일 간격")
        schedule_form.addRow("기간 간격", self.backup_every)
        self.backup_exit = QCheckBox("프로그램 종료 시 자동 백업")
        schedule_form.addRow(self.backup_exit)
        tip = QLabel("자동 백업은 정상 종료 시에만 실행합니다. 로그인 직후·매입 입력 중에는 실행하지 않습니다.\n설정 저장 후 적용됩니다. 강제 종료·정전 시에는 종료 백업이 실행되지 않습니다. ‘지금 백업’은 언제든 사용 가능합니다.")
        tip.setWordWrap(True)
        schedule_form.addRow(tip)
        # Retain legacy schedule values for compatibility, without offering an inactive schedule.
        for field in (self.backup_mode, self.backup_frequency, self.backup_time, day_widget, self.backup_every):
            field.hide()
            label = schedule_form.labelForField(field)
            if label:
                label.hide()
        self.body.addWidget(schedule)
        self.backup_mode.currentIndexChanged.connect(self.update_backup_controls)
        self.backup_frequency.currentIndexChanged.connect(self.update_backup_controls)
        backup = QGroupBox("안전한 데이터 보관")
        backup_layout = QVBoxLayout(backup)
        self.data_location = QLabel()
        self.data_location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.data_location.setWordWrap(True)
        backup_layout.addWidget(self.data_location)
        note = QLabel("백업은 전체 장부를 별도 SQLite 파일로 저장합니다.\n복원은 선택한 백업 시점으로 전체 자료를 되돌리며, 현재 자료를 자동 백업한 뒤 진행합니다.\n복원 후 프로그램을 다시 실행해 백업 당시 계정으로 로그인하세요. 다른 버전의 프로그램은 먼저 종료하세요.")
        note.setWordWrap(True)
        backup_layout.addWidget(note)
        self.backup_grid = DataGrid(["생성일시", "백업 파일명", "종류", "크기 (KB)"])
        self.backup_grid.read_permissions = ("admin",)
        backup_layout.addWidget(self.backup_grid)
        policy = QLabel("전용 폴더에 자동 저장 · 주 1회 정리 · 최신 15개는 유지 · 삭제 시 알림\n처음 실행한 날부터 7일 후 확인하며, 꺼져 있던 기간은 다음 실행 시 확인합니다.")
        policy.setWordWrap(True)
        backup_layout.addWidget(policy)
        actions = QHBoxLayout()
        _button("지금 백업", self.backup, actions, True)
        self.restore_button = _button("선택한 백업 적용", self.restore_selected, actions)
        _button("다른 폴더의 백업 선택", self.restore, actions)
        _button("목록 새로고침", self.refresh_backups, actions)
        actions.addStretch()
        backup_layout.addLayout(actions)
        self.body.addWidget(backup)
        self.body.addStretch()
        _button("설정 저장", self.save, self.actions, True)
        _button("현재 설정 다시 조회", self.refresh, self.actions)
        self.refresh()

    def refresh(self):
        guard = getattr(self, "_navigation_guard", None)
        if guard and not guard.allow_leave(self):
            return
        settings = self.store.settings()
        self.appearance_theme.setCurrentIndex(max(0,self.appearance_theme.findData(settings.get('appearance_theme','default'))))
        self.holiday_skin.setChecked(settings.get('holiday_skin_enabled',False));self.snow_effect.setChecked(settings.get('snow_effect_enabled',False));self.weather_effect.setChecked(settings.get('weather_effect_enabled',False))
        self.restore_sounds.setChecked(False)
        self.sound_enabled.blockSignals(True);self.sound_enabled.setChecked(self.store.popup_sound_enabled());self.sound_enabled.blockSignals(False)
        from .lucky_audio import mouse_sound
        for field,kind in ((self.mouse_click_enabled,'click'),(self.mouse_context_enabled,'context')):
            field.blockSignals(True);field.setChecked(mouse_sound(kind).enabled);field.blockSignals(False)
        self.rounding_mode.setCurrentIndex(max(0, self.rounding_mode.findData(settings["rounding_mode"])))
        defaults = {"earn_bps": 100, "point_min": 1000, "point_step": 100}
        for key, field in self.fields.items():
            field.setText(str(settings.get(key, defaults.get(key, ""))))
        self.point_enabled.setChecked(bool(settings.get("point_enabled", True)))
        self.negative_stock.setChecked(bool(settings.get('allow_negative_stock',True)))
        policy = self.store.backup_schedule()
        self.backup_mode.setCurrentIndex(self.backup_mode.findData(policy["mode"]))
        self.backup_frequency.setCurrentIndex(self.backup_frequency.findData(policy["frequency"]))
        self.backup_time.setTime(QTime.fromString(policy["time"], "HH:mm"))
        self.backup_every.setValue(policy["every_days"])
        self.backup_exit.setChecked(policy["on_exit"])
        for index, box in enumerate(self.backup_weekdays):
            box.setChecked(index in policy["weekdays"])
        self.update_backup_controls()
        self.data_location.setText(f"업무 데이터: {getattr(self.store, 'path', '현재 로컬 데이터베이스')}")
        self.refresh_backups()
        from .navigation import mark_saved
        mark_saved(self)

    def update_backup_controls(self, *_):
        automatic = self.backup_mode.currentData() == "auto"
        frequency = self.backup_frequency.currentData()
        self.backup_frequency.setEnabled(automatic)
        self.backup_time.setEnabled(automatic)
        self.backup_every.setEnabled(automatic and frequency == "interval")
        for box in self.backup_weekdays:
            box.setEnabled(automatic and frequency == "weekly")

    def backup_schedule_values(self):
        return {"mode": self.backup_mode.currentData(), "frequency": self.backup_frequency.currentData(),
                "time": self.backup_time.time().toString("HH:mm"), "every_days": self.backup_every.value(),
                "weekdays": [index for index, box in enumerate(self.backup_weekdays) if box.isChecked()],
                "on_exit": self.backup_exit.isChecked()}

    def refresh_backups(self):
        records = self.store.backup_files()
        self.backup_grid.fill([[row["created"], row["name"], row["kind"], Decimal(row["size"]) / 1024] for row in records], records)
        self.backup_grid.sortItems(0, Qt.SortOrder.DescendingOrder)
        if records:
            self.backup_grid.selectRow(0)

    def restore_selected(self):
        record = self.backup_grid.selected()
        if not record:
            self.notify("목록에서 적용할 백업 파일을 선택하세요.")
            return
        self.restore(record["path"])

    def save(self):
        try:
            values = {key: field.text().strip() for key, field in self.fields.items()}
            for key in ("earn_bps", "point_min", "point_step"):
                values[key] = int(values[key])
            if not 0 <= values["earn_bps"] <= 10000 or values["point_min"] < 0 or values["point_step"] <= 0:
                raise ValueError("적립률은 0~10000, 최소 사용은 0 이상, 사용 단위는 1 이상으로 입력하세요.")
            values["point_enabled"] = self.point_enabled.isChecked()
            values['allow_negative_stock']=self.negative_stock.isChecked()
            values["rounding_mode"] = self.rounding_mode.currentData()
            values['appearance_theme']=self.appearance_theme.currentData()
            values.update(holiday_skin_enabled=self.holiday_skin.isChecked(),snow_effect_enabled=self.snow_effect.isChecked(),weather_effect_enabled=self.weather_effect.isChecked())
            values["backup_schedule"] = self.backup_schedule_values()
            self.store.save_settings(values)
            if hasattr(self.window,'update_appearance'):self.window.update_appearance()
            else:
                from .appearance import apply_theme
                apply_theme(values['appearance_theme'],values['holiday_skin_enabled'])
            if self.restore_sounds.isChecked():
                from .settings_defaults import restore_sound_defaults
                restore_sound_defaults(self.store);self.restore_sounds.setChecked(False)
                self.sound_enabled.blockSignals(True);self.sound_enabled.setChecked(True);self.sound_enabled.blockSignals(False)
                for field in (self.mouse_click_enabled,self.mouse_context_enabled):
                    field.blockSignals(True);field.setChecked(True);field.blockSignals(False)
            from .navigation import mark_saved
            mark_saved(self)
            self.notify("매장 설정을 저장했습니다.")
        except (ValueError, PermissionError) as exc:
            _error(self, exc)

    def backup(self):
        try:
            filename = self.store.create_backup()
            self.refresh_backups()
            self.notify(f"백업을 저장했습니다: {filename}")
        except (ValueError, PermissionError, OSError) as exc:
            _error(self, exc)

    def restore(self, filename=None):
        try:
            self.store._require("admin")
            finish = getattr(self.window, "finish_restore", None)
            if not callable(finish):
                raise ValueError("메인 화면의 관리자 설정에서 복원을 실행하세요.")
            if not filename:
                filename, _ = QFileDialog.getOpenFileName(self, "복원할 백업 파일 선택", "", "SQLite 백업 (*.db *.sqlite *.sqlite3);;모든 파일 (*)")
            if not filename:
                return
            info = self.store.inspect_backup(filename)
            counts = info["counts"]
            message = (f"주의: 현재 자료가 선택한 백업으로 바뀝니다.\n상품 {counts['products']:,}개 · 전표 {counts['documents']:,}건 · 회원 {counts['members']:,}명\n"
                       "현재 자료는 자동 백업됩니다. 적용 후 프로그램이 종료됩니다.\n재실행 후 백업 당시 계정으로 로그인하세요.\n\n적용할까요?")
            if not _confirm(self, "백업 복원 확인", message):
                return
            password, accepted = QInputDialog.getText(self, "관리자 확인", "현재 로그인한 관리자의 비밀번호", QLineEdit.EchoMode.Password)
            if not accepted:
                return
            self.restore_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                result = self.store.restore_backup(filename, password, expected_digest=info["digest"])
            finally:
                QApplication.restoreOverrideCursor()
                self.restore_button.setEnabled(True)
            finish(result)
        except (ValueError, PermissionError, OSError) as exc:
            _error(self, exc)
        except RuntimeError as exc:
            QMessageBox.critical(self, "복원 중단", str(exc))
            self.window.close()
            QApplication.instance().quit()
