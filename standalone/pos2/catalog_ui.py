"""Fresh desktop catalog screens, derived from the offline manual's workflows.

No network lookup or old application dependency is used by these screens.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .widgets import DataGrid, Page, ScanField


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


def _won(value):
    return f"{int(value or 0):,}"


def _quantity(value):
    return f"{Decimal(str(value or 0)):,.3f}"


def _button(label, callback, layout, primary=False):
    button = QPushButton(label)
    if primary:
        button.setObjectName("primary")
    button.clicked.connect(lambda *_: callback())
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


class ProductDialog(QDialog):
    """Real product editor with read-only transaction history and unit CRUD."""

    def __init__(self, store, record=None, parent=None):
        super().__init__(parent)
        self.store, self.record = store, dict(record or {})
        self.saved_id = None
        self.fields = {}
        self.history_tables, self.history_filters, self.history_summaries = {}, {}, {}
        self.setObjectName("productDialog")
        self.setWindowTitle("상품 등록정보" if record else "새 상품 등록")
        self.resize(1110, 830)
        self.setMinimumSize(850, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        head = QHBoxLayout()
        heading = QLabel("상품 등록정보" if record else "새 상품 등록")
        heading.setObjectName("dialogHeading")
        head.addWidget(heading)
        head.addStretch()
        head.addWidget(QLabel("기본단위 기준 원 / 수량 소수 3자리"))
        root.addLayout(head)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._product_tab()
        for key, title in (("purchases", "매입이력"), ("sales", "판매이력")):
            self._history_tab(key, title)
        self._stock_tab()
        self._audit_tab()
        self._units_tab()
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#bd3232;")
        root.addWidget(self.error_label)
        footer = QHBoxLayout()
        self.meta = QLabel()
        self.meta.setWordWrap(True)
        self.meta.setObjectName("muted")
        footer.addWidget(self.meta)
        footer.addStretch()
        self.apply_button = _button("적용", self.apply_changes, footer)
        self.cancel_button = _button("닫기", self.reject, footer)
        self.save_button = _button("저장", self.save, footer, True)
        root.addLayout(footer)
        self.refresh_details()
        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(1110, available.width() - 40), min(830, available.height() - 60))

    def _field(self, layout, key, label, default=""):
        field = ScanField() if key == "barcode" else QLineEdit()
        field.setText(str(self.record.get(key, default)))
        self.fields[key] = field
        layout.addRow(label, field)
        return field

    def _group(self, title):
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setContentsMargins(12, 8, 12, 10)
        form.setSpacing(6)
        return group, form

    def _product_tab(self):
        viewport = QScrollArea()
        viewport.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 15, 14, 15)
        classification = QFrame()
        top = QGridLayout(classification)
        top.setContentsMargins(4, 4, 4, 4)
        top.setHorizontalSpacing(7)
        top.setVerticalSpacing(6)
        self.active = QCheckBox("사용 상품")
        self.active.setChecked(bool(self.record.get("active", True)))
        top.addWidget(self.active, 0, 0)
        self.tax_mode = _combo([("면세", "exempt"), ("과세", "taxable")], self.record.get("tax_mode", "exempt"))
        top.addWidget(QLabel("과세"), 0, 1)
        top.addWidget(self.tax_mode, 0, 2)
        for col, (key, label) in enumerate((("category", "대분류"), ("category_mid", "중분류"), ("category_small", "소분류"))):
            top.addWidget(QLabel(label), 0, col * 2 + 3)
            field = QLineEdit(self.record.get(key, ""))
            field.setPlaceholderText(label)
            self.fields[key] = field
            top.addWidget(field, 0, col * 2 + 4)
        suppliers = self.store.partners("supplier")
        options = [("공급사 미지정", None)] + [(f"{p['name']} · {p['code']}", p["id"]) for p in suppliers]
        self.supplier = _combo(options, self.record.get("supplier_id"))
        top.addWidget(QLabel("공급사"), 1, 0)
        top.addWidget(self.supplier, 1, 1, 1, 6)
        supplier_search = QPushButton("공급사 검색")
        supplier_search.clicked.connect(self.pick_supplier)
        top.addWidget(supplier_search, 1, 7, 1, 2)
        layout.addWidget(classification)
        columns = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        basics, form = self._group("상품 기본정보")
        for key, label in (("code", "상품코드 *"), ("barcode", "바코드"), ("name", "상품명 *"),
                           ("receipt_name", "표시명"), ("specification", "규격")):
            self._field(form, key, label)
        units = ["kg", "g", "개", "박스", "팩", "EA", "mg", "L", "mL", "P", "m", "cm", "mm", "W"]
        current = self.record.get("base_unit", "kg")
        self.unit = _combo([(u, u) for u in units], current, editable=True)
        form.addRow("기본단위 *", self.unit)
        unit_note = QLabel("기본단위 기준 단가·재고입니다. 이력·확장단위 등록 후에는 기본단위를 바꿀 수 없습니다.")
        unit_note.setWordWrap(True)
        unit_note.setObjectName("muted")
        form.addRow(unit_note)
        left.addWidget(basics)
        prices, form = self._group("기준 단가")
        self.purchase_price = self._field(form, "purchase_price", "매입단가 (원)", 0)
        self.sale_price = self._field(form, "sale_price", "판매단가 (원)", 0)
        self.margin = QLabel()
        self.margin.setObjectName("amount")
        form.addRow("판매가 기준 이익률", self.margin)
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
        self.memo.setMinimumHeight(110)
        form.addRow("상품설명 / 메모", self.memo)
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
        start, end = QDateEdit(QDate.currentDate().addMonths(-1)), QDateEdit(QDate.currentDate())
        for field in (start, end):
            field.setCalendarPopup(True)
            field.setDisplayFormat("yyyy-MM-dd")
            field.setEnabled(False)
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
        self.tabs.addTab(widget, "재고이력")

    def _audit_tab(self):
        widget = QWidget()
        body = QVBoxLayout(widget)
        body.addWidget(QLabel("이 상품과 연결된 확장단위의 변경사항만 표시합니다."))
        self.audit_table = DataGrid(["변경일시", "담당자", "업무", "변경 내용"])
        body.addWidget(self.audit_table)
        self.tabs.addTab(widget, "변경기록")

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
        data.update(base_unit=self.unit.currentText().strip(), supplier_id=self.supplier.currentData(),
                    tax_mode=self.tax_mode.currentData(), tracked=self.tracked.isChecked(),
                    active=self.active.isChecked(), memo=self.memo.toPlainText().strip())
        return data

    def save(self, close=True):
        try:
            self.saved_id = self.store.save_product(self.values(), self.record.get("id"))
            self.record = next(r for r in self.store.products() if r["id"] == self.saved_id)
            self.error_label.clear()
            self.refresh_details()
        except (ValueError, PermissionError) as exc:
            self.error_label.setText(str(exc))
            return False
        if close:
            self.accept()
        return True

    def apply_changes(self):
        self.save(False)

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
            latest = next((r for r in self.store.products() if r["id"] == record_id), self.record)
            self.record = dict(latest)
        self.stock_quantity.setText(f"{_quantity(self.record.get('stock_qty', 0))} {self.record.get('base_unit', self.unit.currentText())}")
        self.stock_cost.setText(f"{_won(self.record.get('stock_cost', 0))} 원")
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
        self.audit_table.fill([[r["at"], r.get("user_name", ""), r["action"], self._audit_text(r["detail"])] for r in audit], audit)
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
    def __init__(self, window):
        super().__init__(window, "상품장", "상품 · 기준단가 · 확장단위 · 입출고 이력을 한곳에서 관리합니다.")
        self.window = window
        self.search = QLineEdit()
        self.search.setPlaceholderText("상품명 · 코드 · 바코드 · 검색어")
        self.search.setMinimumWidth(230)
        self.scan = ScanField()
        self.scan.setMinimumWidth(200)
        self.scan.scanned.connect(self.scan_barcode)
        self.category = QComboBox()
        self.supplier = QComboBox()
        self.active_only = QCheckBox("사용 상품만")
        self.active_only.setChecked(True)
        self.low_only = QCheckBox("최소재고 이하")
        filters = QHBoxLayout()
        for label, widget in (("검색", self.search), ("분류", self.category), ("공급사", self.supplier)):
            filters.addWidget(QLabel(label))
            filters.addWidget(widget)
        filters.addWidget(self.active_only)
        filters.addWidget(self.low_only)
        self.body.addLayout(filters)
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
        self.grid = self.table(["상품코드", "상품명", "대분류", "중분류", "규격", "바코드", "공급사", "매입단가", "판매단가", "현재고", "단위", "재고 원가액", "상태"])
        for column, width in enumerate((85, 185, 80, 80, 80, 130, 130, 100, 100, 95, 60, 115, 65)):
            self.grid.setColumnWidth(column, width)
        self.summary = QLabel()
        self.summary.setObjectName("summary")
        self.body.addWidget(self.summary)
        self.add_button = _button("새 상품 등록", self.add, self.actions, True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.itemDoubleClicked.connect(lambda *_: self.edit())
        self.search.textChanged.connect(self.refresh)
        for control in (self.category, self.supplier):
            control.currentIndexChanged.connect(self.refresh)
        self.active_only.toggled.connect(self.refresh)
        self.low_only.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        all_products = self.store.products()
        current_category, current_supplier = self.category.currentData(), self.supplier.currentData()
        self.category.blockSignals(True)
        self.supplier.blockSignals(True)
        self.category.clear()
        self.category.addItem("전체 분류", "")
        for category in sorted({p["category"] for p in all_products if p["category"]}):
            self.category.addItem(category, category)
        self.category.setCurrentIndex(max(0, self.category.findData(current_category)))
        self.supplier.clear()
        self.supplier.addItem("전체 공급사", None)
        suppliers = self.store.partners("supplier")
        supplier_map = {p["id"]: p["name"] for p in suppliers}
        for partner in suppliers:
            self.supplier.addItem(partner["name"], partner["id"])
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(current_supplier)))
        self.category.blockSignals(False)
        self.supplier.blockSignals(False)
        rows = self.store.products(search=self.search.text(), supplier_id=self.supplier.currentData(),
                                   category=self.category.currentData() or "", active_only=self.active_only.isChecked())
        if self.low_only.isChecked():
            rows = [r for r in rows if r["tracked"] and Decimal(r["stock_qty"]) <= Decimal(r["min_qty"])]
        self.grid.fill([[r["code"], r["name"], r["category"], r["category_mid"], r["specification"], r["barcode"],
                         supplier_map.get(r["supplier_id"], "—"), r["purchase_price"], r["sale_price"],
                         Decimal(r["stock_qty"]), r["base_unit"], r["stock_cost"], "사용" if r["active"] else "중지"] for r in rows], rows)
        totals = {}
        for r in rows:
            if r["tracked"]:
                totals[r["base_unit"]] = totals.get(r["base_unit"], Decimal(0)) + Decimal(r["stock_qty"])
        quantities = " / ".join(f"{value:,.3f} {unit}" for unit, value in sorted(totals.items())) or "—"
        self.summary.setText(f"검색 {len(rows):,}품목  ·  재고 {quantities}  ·  원가 합계 {_won(sum(r['stock_cost'] for r in rows if r['tracked']))} 원")

    def add(self):
        dialog = ProductDialog(self.store, parent=self)
        dialog.exec()
        if dialog.saved_id:
            self.refresh()

    def edit(self):
        record = self.grid.selected()
        if record:
            dialog = ProductDialog(self.store, record, self)
            dialog.exec()
            if dialog.saved_id:
                self.refresh()

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
            self.category.setCurrentIndex(0)
            self.supplier.setCurrentIndex(0)
            self.low_only.setChecked(False)
            self.search.setText(barcode)
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
        _button("사용자 삭제", self.delete, self.actions)
        _button("조회", self.refresh, self.actions)
        self.grid.itemDoubleClicked.connect(lambda *_: self.edit())
        self.refresh()

    def refresh(self):
        users = self.store.list_users()
        self.grid.fill([[r["code"], r["name"], "관리자" if r["role"] == "admin" else "일반 사용자",
                         "모든 업무" if r["role"] == "admin" else ", ".join(PERMISSION_LABELS.get(p, p) for p in sorted(r["permissions"])),
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
                                      permissions=[key for key, box in permission_boxes.items() if box.isChecked()]), record.get("id"))
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


class SettingsPage(Page):
    def __init__(self, window):
        super().__init__(window, "매장 설정 · 백업", "서버 없이 이 PC의 SQLite 파일에 모든 업무자료를 저장합니다.")
        self.fields = {}
        business = QGroupBox("매장 기본정보")
        form = QFormLayout(business)
        for key, label in (("store_name", "매장명"), ("business_no", "사업자등록번호"),
                           ("phone", "전화번호"), ("address", "주소")):
            field = QLineEdit()
            self.fields[key] = field
            form.addRow(label, field)
        self.body.addWidget(business)
        points = QGroupBox("회원 포인트 정책")
        point_form = QFormLayout(points)
        self.point_enabled = QCheckBox("포인트 적립·사용 허용")
        point_form.addRow(self.point_enabled)
        for key, label in (("earn_bps", "적립률 (100 = 1%)"), ("point_min", "최소 사용 포인트"), ("point_step", "포인트 사용 단위")):
            field = QLineEdit()
            self.fields[key] = field
            point_form.addRow(label, field)
        point_form.addRow(QLabel("회원매출은 전액 정산 시 적립됩니다. 정책 변경 전 거래의 포인트 내역은 유지됩니다."))
        self.body.addWidget(points)
        backup = QGroupBox("안전한 데이터 보관")
        backup_layout = QVBoxLayout(backup)
        self.data_location = QLabel()
        self.data_location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.data_location.setWordWrap(True)
        backup_layout.addWidget(self.data_location)
        note = QLabel("백업은 사용 중인 데이터베이스를 일관된 별도 SQLite 파일로 저장합니다.\n복원은 프로그램을 종료한 뒤 원본 파일을 별도 보관하고 진행하세요. ZIP 배포파일에는 거래자료가 포함되지 않습니다.")
        note.setWordWrap(True)
        backup_layout.addWidget(note)
        actions = QHBoxLayout()
        _button("백업 파일 저장", self.backup, actions, True)
        actions.addStretch()
        backup_layout.addLayout(actions)
        self.body.addWidget(backup)
        self.body.addStretch()
        _button("설정 저장", self.save, self.actions, True)
        _button("다시 불러오기", self.refresh, self.actions)
        self.refresh()

    def refresh(self):
        settings = self.store.settings()
        defaults = {"earn_bps": 100, "point_min": 1000, "point_step": 100}
        for key, field in self.fields.items():
            field.setText(str(settings.get(key, defaults.get(key, ""))))
        self.point_enabled.setChecked(bool(settings.get("point_enabled", True)))
        self.data_location.setText(f"업무 데이터: {getattr(self.store, 'path', '현재 로컬 데이터베이스')}")

    def save(self):
        try:
            values = {key: field.text().strip() for key, field in self.fields.items()}
            for key in ("earn_bps", "point_min", "point_step"):
                values[key] = int(values[key])
            if not 0 <= values["earn_bps"] <= 10000 or values["point_min"] < 0 or values["point_step"] <= 0:
                raise ValueError("적립률은 0~10000, 최소 사용은 0 이상, 사용 단위는 1 이상으로 입력하세요.")
            values["point_enabled"] = self.point_enabled.isChecked()
            self.store.save_settings(values)
            self.notify("매장 설정을 저장했습니다.")
        except (ValueError, PermissionError) as exc:
            _error(self, exc)

    def backup(self):
        filename, _ = QFileDialog.getSaveFileName(self, "업무자료 백업", f"서영POS-백업-{date.today().isoformat()}.db", "SQLite 백업 (*.db)")
        if filename:
            try:
                self.store.backup(filename)
                self.notify(f"백업을 저장했습니다: {filename}")
            except (ValueError, PermissionError, OSError) as exc:
                _error(self, exc)
