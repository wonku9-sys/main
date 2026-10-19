"""Keyboard-friendly Korean business dialogs for 서영 POS."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from typing import Any

from PySide6.QtCore import QDate, QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QDateEdit,
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)


PERMISSIONS = {
    "products": "상품 관리", "partners": "거래처 관리", "purchases": "매입 관리",
    "sales": "매출 관리", "inventory": "재고 관리", "reports": "조회·엑셀",
    "members": "회원·포인트 관리", "promotions": "기간 특매 관리",
    "users": "사용자 관리 (관리자)", "settings": "설정 (관리자)",
}


def money(value: Any) -> str:
    return f"{int(value or 0):,}"


def quantity(value: Any) -> str:
    number = Decimal(str(value or 0))
    return f"{number:,.3f}".rstrip("0").rstrip(".")


def line_edit(value: Any = "", placeholder: str = "") -> QLineEdit:
    field = QLineEdit(str(value if value is not None else ""))
    field.setPlaceholderText(placeholder)
    field.setMinimumHeight(36)
    return field


def number_edit(value: Any = 0, decimal: bool = False) -> QLineEdit:
    field = line_edit(value)
    pattern = r"\d{0,12}(?:\.\d{0,3})?" if decimal else r"\d{0,15}"
    field.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), field))
    field.setAlignment(Qt.AlignmentFlag.AlignRight)
    return field


def date_edit(value: str = "") -> QDateEdit:
    field = QDateEdit()
    field.setCalendarPopup(True)
    field.setDisplayFormat("yyyy-MM-dd")
    parsed = QDate.fromString(value, "yyyy-MM-dd")
    field.setDate(parsed if parsed.isValid() else QDate.currentDate())
    field.setMinimumHeight(36)
    return field


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(39)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setShowGrid(False)
    return widget


def put_row(widget: QTableWidget, values: list[Any], record_id: Any = None) -> int:
    row = widget.rowCount()
    widget.insertRow(row)
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value if value is not None else ""))
        if column == 0:
            item.setData(Qt.ItemDataRole.UserRole, record_id)
        widget.setItem(row, column, item)
    return row


def primary(button: QPushButton) -> QPushButton:
    button.setObjectName("primaryButton")
    button.setMinimumHeight(38)
    return button


class BusinessDialog(QDialog):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} · 서영 POS")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(26, 24, 26, 22)
        self.layout.setSpacing(18)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 8)
        header_layout.setSpacing(5)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        header_layout.addWidget(heading)
        if subtitle:
            description = QLabel(subtitle)
            description.setWordWrap(True)
            description.setObjectName("dialogSubtitle")
            header_layout.addWidget(description)
        self.layout.addWidget(header)

    def error(self, error: Exception) -> None:
        QMessageBox.warning(self, "확인해 주세요", str(error))

    def buttons(self, save_text: str = "저장", callback=None, close_only: bool = False):
        standard = QDialogButtonBox.StandardButton.Close if close_only else (
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        box = QDialogButtonBox(standard)
        if close_only:
            box.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
            box.rejected.connect(self.reject)
        else:
            button = box.button(QDialogButtonBox.StandardButton.Save)
            button.setText(save_text)
            primary(button)
            button.setDefault(True)
            box.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
            box.accepted.connect(callback or self.accept)
            box.rejected.connect(self.reject)
        self.layout.addWidget(box)
        return box


class LoginBackdrop(QMainWindow):
    """A locked, server-free desktop shell while account authentication is pending.

    No service or authenticated business view is installed in this window. Its
    menus are intentionally disabled until the real MainWindow is opened after
    LoginDialog has authenticated the user.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("loginBackdrop")
        self.setWindowTitle("서영 POS · 오프라인 매장 관리")
        self.resize(1280, 800)
        self.setMinimumSize(800, 540)
        self.setStyleSheet("""
            #loginBackdrop, #loginCanvas { background: #FFFFFF; }
            #loginBackdrop QMenuBar { background: #F7F9FC; color: #617287;
                border-bottom: 1px solid #DFE6EE; padding: 3px 8px; }
            #loginBackdrop QMenuBar::item { padding: 5px 11px; }
            #loginBackdrop QMenuBar::item:disabled { color: #8391A3; }
            #loginBackdrop QStatusBar { background: #F7F9FC;
                color: #77879A; border-top: 1px solid #E4EAF1; }
        """)
        self.locked_menus = []
        for title in ("기초관리", "매입·매출관리", "재고관리", "거래 분석", "사용자·설정"):
            menu = self.menuBar().addMenu(title)
            menu.setEnabled(False)
            self.locked_menus.append(menu)
        canvas = QWidget()
        canvas.setObjectName("loginCanvas")
        self.setCentralWidget(canvas)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("사용자 인증 후 업무 메뉴를 사용할 수 있습니다.")
        self.statusBar().addPermanentWidget(QLabel("오프라인 단독 실행 · SQLite"))
        if QApplication.platformName() != "offscreen" and QApplication.primaryScreen():
            available = QApplication.primaryScreen().availableGeometry()
            self.resize(min(self.width(), available.width()), min(self.height(), available.height()))


class LoginDialog(BusinessDialog):
    def __init__(self, service, parent: QWidget | None = None):
        self.service = service
        self.initial = service.users_count() == 0
        super().__init__(
            "첫 관리자 등록" if self.initial else "사용자 확인",
            "첫 관리자 계정을 만들어 매장 관리를 시작하세요." if self.initial else
            "서영 POS · 매입·매출 및 재고 관리", parent,
        )
        self.setObjectName("loginDialog")
        self.setMinimumWidth(0)
        self.setFixedWidth(500 if self.initial else 460)
        self.layout.setContentsMargins(24, 22, 24, 22)
        self.layout.setSpacing(16)
        self.setStyleSheet("""
            #loginDialog { background: #FFFFFF; }
            #loginDialog #dialogHeader { background: #FFF7E8;
                border-top: 3px solid #E7AE3C; border-bottom: 1px solid #F1E2C5;
                border-radius: 6px; padding: 13px 14px; }
            #loginDialog #dialogTitle { color: #473D28; font-size: 20px; font-weight: 700; }
            #loginDialog #dialogSubtitle { color: #8B7B60; font-size: 11px; }
            #loginDialog QLineEdit { min-height: 20px; padding: 6px 9px; }
            #loginDialog #mutedLabel { font-size: 11px; color: #8090A3; }
        """)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.username = line_edit("", "등록한 사용자 코드 (아이디)")
        self.username.setObjectName("loginUsername")
        self.name = line_edit("", "예: 매장 관리자")
        self.name.setObjectName("loginName")
        self.password = line_edit("", "8자 이상 비밀번호" if self.initial else "비밀번호")
        self.password.setObjectName("loginPassword")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = line_edit("", "비밀번호를 한 번 더 입력하세요")
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        if self.initial:
            form.addRow("사용자 코드", self.username)
            form.addRow("사용자 이름", self.name)
        else:
            self.name.setReadOnly(True)
            self.name.setPlaceholderText("로그인 후 확인됩니다")
            self.name.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            form.addRow("사용자 이름", self.name)
            form.addRow("사용자 코드", self.username)
        form.addRow("암호", self.password)
        if self.initial:
            form.addRow("비밀번호 확인", self.confirm)
        self.layout.addLayout(form)
        note = QLabel("서버·인터넷 연결 없이 사용합니다.\n거래자료는 이 PC의 데이터베이스에 보관됩니다.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        self.layout.addWidget(note)
        self.button_box = self.buttons("관리자 계정 만들기" if self.initial else "확인", self.submit)
        QWidget.setTabOrder(self.username, self.name if self.initial else self.password)
        if self.initial:
            QWidget.setTabOrder(self.name, self.password)
            QWidget.setTabOrder(self.password, self.confirm)
        self.username.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        if self.parentWidget() and self.parentWidget().isVisible():
            frame = self.frameGeometry()
            frame.moveCenter(self.parentWidget().frameGeometry().center())
            screen = self.parentWidget().screen()
            if screen and QApplication.platformName() != "offscreen":
                available = screen.availableGeometry()
                frame.moveLeft(max(available.left(), min(frame.left(), available.right() - frame.width() + 1)))
                frame.moveTop(max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1)))
            self.move(frame.topLeft())

    def submit(self):
        try:
            username = self.username.text().strip()
            password = self.password.text()
            if not username or not password:
                raise ValueError("아이디와 비밀번호를 입력해 주세요.")
            if self.initial:
                if not self.name.text().strip():
                    raise ValueError("관리자 이름을 입력해 주세요.")
                if password != self.confirm.text():
                    raise ValueError("비밀번호 확인이 일치하지 않습니다.")
                self.service.create_initial_admin(username, self.name.text().strip(), password)
                self.initial = False
            user = self.service.login(username, password)
            self.name.setText(user["name"])
            self.accept()
        except Exception as error:
            self.error(error)


class PartnerDialog(BusinessDialog):
    def __init__(self, service, kind: str, record: dict | None = None, parent=None):
        self.service, self.kind, self.record = service, kind, record or {}
        label = "공급사" if kind == "supplier" else "고객·거래처"
        super().__init__(f"{label} {'수정' if record else '등록'}", "거래자료가 있는 거래처는 안전하게 보존됩니다.", parent)
        self.resize(660, 630)
        form = QFormLayout()
        form.setSpacing(11)
        self.fields = {}
        for key, title, placeholder in [
            ("code", f"{label} 코드 *", "중복되지 않는 코드"),
            ("name", f"{label}명 *", "상호 또는 거래처 이름"),
            ("business_no", "사업자등록번호", "000-00-00000"),
            ("contact", "담당자", "담당자 이름"), ("phone", "전화번호", "연락처"),
            ("bank", "은행명", "은행 이름"), ("account", "계좌번호", "입금·출금 계좌"),
            ("account_holder", "예금주", "예금주 이름"),
        ]:
            field = line_edit(self.record.get(key, ""), placeholder)
            field.setObjectName(f"partner_{key}")
            self.fields[key] = field
            form.addRow(title, field)
        self.memo = QTextEdit(self.record.get("memo", ""))
        self.memo.setMaximumHeight(85)
        form.addRow("메모", self.memo)
        self.layout.addLayout(form)
        self.buttons(callback=self.save)
        self.fields["name"].setFocus()

    def save(self):
        try:
            data = {key: value.text().strip() for key, value in self.fields.items()}
            if not data["name"]:
                raise ValueError("거래처명을 입력해 주세요.")
            data.update(kind=self.kind, memo=self.memo.toPlainText().strip())
            self.saved_id = self.service.save_partner(data, self.record.get("id"))
            self.accept()
        except Exception as error:
            self.error(error)


class PartnerPicker(BusinessDialog):
    def __init__(self, service, kind: str, parent=None):
        self.service, self.kind, self.selected = service, kind, None
        label = "공급사" if kind == "supplier" else "고객·거래처"
        super().__init__(f"{label} 선택", "이름·코드·담당자로 검색한 후 더블클릭하거나 선택 버튼을 누르세요.", parent)
        self.resize(760, 580)
        self.search = line_edit("", f"{label}명, 코드, 담당자 검색")
        self.search.setClearButtonEnabled(True)
        self.search.setObjectName("partnerSearch")
        self.layout.addWidget(self.search)
        self.table = table(["코드", label, "담당자", "전화번호"])
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 255)
        self.table.setColumnWidth(2, 115)
        self.layout.addWidget(self.table, 1)
        self.buttons("선택", self.choose)
        self.table.cellDoubleClicked.connect(lambda *_: self.choose())
        self.search.textChanged.connect(self.refresh)
        self.refresh()
        self.search.setFocus()

    def refresh(self):
        try:
            self.records = self.service.list_partners(self.kind, self.search.text().strip())
            self.table.setRowCount(0)
            for record in self.records:
                put_row(self.table, [record.get(key, "") for key in ("code", "name", "contact", "phone")], record["id"])
            if self.records:
                self.table.selectRow(0)
        except Exception as error:
            self.error(error)

    def choose(self):
        row = self.table.currentRow()
        if row < 0:
            self.error(ValueError("거래처를 선택해 주세요. 거래처가 없다면 먼저 등록해 주세요."))
            return
        self.selected = self.records[row]
        self.accept()


class ProductDialog(BusinessDialog):
    def __init__(self, service, record: dict | None = None, parent=None):
        self.service, self.record = service, dict(record or {})
        # Product-list rows can predate the last transaction. Always open the latest
        # persisted quantities and descriptive metadata when editing a product.
        if self.record.get("id"):
            self.record = next((item for item in service.list_products()
                                if item["id"] == self.record["id"]), self.record)
        super().__init__("상품 등록정보" if record else "새 상품 등록",
                         "상품 기본정보와 가격·보관정보를 입력하고, 탭에서 거래와 변경 이력을 확인하세요.", parent)
        self.setObjectName("productDialog")
        self.setMinimumSize(900, 680)
        self.resize(1020, 830)
        screen = self.screen()
        if screen and QApplication.platformName() != "offscreen":
            available = screen.availableGeometry()
            self.resize(min(1020, available.width() - 30), min(830, available.height() - 45))
        self.layout.setContentsMargins(20, 18, 20, 16)
        self.layout.setSpacing(12)
        self.fields = {}
        for key, placeholder in [
            ("code", "필수 · 중복되지 않는 코드"), ("barcode", "바코드 스캔 또는 직접 입력"),
            ("name", "필수 · 예: 국내산 삼겹살"), ("category", "예: 정육"),
            ("category_mid", "예: 돈육"), ("category_small", "예: 삼겹살"),
            ("specification", "예: 냉장 · 구이용"), ("origin", "예: 국내산"),
            ("receipt_name", "매장 내 상품 표기용 이름"), ("capacity", "예: 500"),
            ("unit_capacity", "예: g / 팩"), ("warehouse", "예: 냉장 1창고"),
            ("shelf", "예: A-03"), ("keywords", "예: 구이, 냉장, 한돈"),
        ]:
            field = self._compact(line_edit(self.record.get(key, ""), placeholder))
            field.setObjectName(f"product_{key}")
            self.fields[key] = field

        self.unit = self._compact(QComboBox())
        self.unit.addItems(["kg", "g", "개", "박스", "팩", "EA", "L", "mL"])
        self.unit.setEditable(True)
        self.unit.setCurrentText(self.record.get("unit", "kg"))
        self.unit.setObjectName("product_unit")
        self.supplier = self._compact(QComboBox())
        self.supplier.setObjectName("product_supplier")
        self.supplier.addItem("공급사 미지정", None)
        try:
            for partner in service.list_partners("supplier"):
                self.supplier.addItem(f"{partner['name']}  ·  {partner['code']}", partner["id"])
        except Exception as error:
            self.error(error)
        index = self.supplier.findData(self.record.get("supplier_id"))
        self.supplier.setCurrentIndex(max(index, 0))
        self.purchase_price = self._compact(number_edit(self.record.get("purchase_price", 0)))
        self.purchase_price.setObjectName("product_purchase_price")
        self.sale_price = self._compact(number_edit(self.record.get("sale_price", 0)))
        self.sale_price.setObjectName("product_sale_price")
        self.min_stock = self._compact(number_edit(self.record.get("min_stock", "0"), True))
        self.min_stock.setObjectName("product_min_stock")
        self.box_quantity = self._compact(number_edit(self.record.get("box_quantity", "0"), True))
        self.box_quantity.setObjectName("product_box_quantity")
        self.active = QCheckBox("사용 상품")
        self.active.setChecked(bool(self.record.get("active", True)))
        self.tax_type = self._compact(QComboBox())
        self.tax_type.setObjectName("product_tax_type")
        self.tax_type.addItem("면세", "exempt")
        self.tax_type.addItem("과세", "taxable")
        self.tax_type.setCurrentIndex(max(0, self.tax_type.findData(self.record.get("tax_type", "exempt"))))
        self.tax_type.setToolTip("상품 분류용 정보입니다. 전표 금액이나 부가세를 자동으로 변경하지 않습니다.")
        self.memo = QTextEdit(self.record.get("memo", ""))
        self.memo.setObjectName("product_memo")
        self.memo.setPlaceholderText("이력번호·보관 방법 등 필요한 정보를 기록하세요.")
        self.memo.setMinimumHeight(84)
        self.memo.setMaximumHeight(106)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("productTabs")
        self.layout.addWidget(self.tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("productForm")
        form_layout = QVBoxLayout(content)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setSpacing(12)

        classification = QFrame()
        classification.setObjectName("productSection")
        classify = QGridLayout(classification)
        classify.setContentsMargins(12, 10, 12, 10)
        classify.setHorizontalSpacing(9)
        classify.setVerticalSpacing(8)
        classify.addWidget(self.active, 0, 0)
        classify.addWidget(self._label("과세 구분"), 0, 1)
        classify.addWidget(self.tax_type, 0, 2)
        for column, key, label in [(3, "category", "대분류"), (5, "category_mid", "중분류"), (7, "category_small", "소분류")]:
            classify.addWidget(self._label(label), 0, column)
            classify.addWidget(self.fields[key], 0, column + 1)
            classify.setColumnStretch(column + 1, 1)
        classify.addWidget(self._label("기본 공급사"), 1, 0)
        classify.addWidget(self.supplier, 1, 1, 1, 5)
        self.supplier_search = QPushButton("공급사 검색")
        self.supplier_search.setObjectName("productSupplierSearch")
        self.supplier_search.setMinimumHeight(32)
        self.supplier_search.clicked.connect(self.pick_supplier)
        classify.addWidget(self.supplier_search, 1, 6, 1, 3)
        form_layout.addWidget(classification)

        panels = QGridLayout()
        panels.setHorizontalSpacing(12)
        panels.setVerticalSpacing(12)
        panels.setColumnStretch(0, 1)
        panels.setColumnStretch(1, 1)
        basic, basic_grid = self._group("상품 기본정보")
        self._row(basic_grid, 0, "상품 코드 *", self.fields["code"])
        self._row(basic_grid, 1, "바코드", self.fields["barcode"])
        self._row(basic_grid, 2, "상품명 *", self.fields["name"])
        self._row(basic_grid, 3, "규격", self.fields["specification"])
        basic_grid.addWidget(self._label("거래 단위 *"), 4, 0)
        basic_grid.addWidget(self.unit, 4, 1)
        basic_grid.addWidget(self._label("용량"), 4, 2)
        basic_grid.addWidget(self.fields["capacity"], 4, 3)
        basic_grid.addWidget(self._label("단위 용량"), 5, 0)
        basic_grid.addWidget(self.fields["unit_capacity"], 5, 1, 1, 3)
        panels.addWidget(basic, 0, 0)

        stock, stock_grid = self._group("재고 · 보관정보")
        self._row(stock_grid, 0, "상품 표기명", self.fields["receipt_name"])
        self.fields["receipt_name"].setToolTip("이름을 보관하는 항목입니다. 영수증 출력 기능은 제공하지 않습니다.")
        stock_summary = QFrame()
        stock_summary.setObjectName("productSummary")
        summary = QGridLayout(stock_summary)
        summary.setContentsMargins(10, 8, 10, 8)
        self.stock_quantity_label = QLabel()
        self.stock_quantity_label.setObjectName("readonlyValue")
        self.stock_cost_label = QLabel()
        self.stock_cost_label.setObjectName("readonlyValue")
        self.stock_quantity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.stock_cost_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self._label("현재 재고"), 0, 0)
        summary.addWidget(self.stock_quantity_label, 0, 1)
        summary.addWidget(self._label("재고 원가액"), 1, 0)
        summary.addWidget(self.stock_cost_label, 1, 1)
        summary.setColumnStretch(1, 1)
        stock_grid.addWidget(stock_summary, 1, 0, 1, 4)
        stock_grid.addWidget(self._label("최소 재고"), 2, 0)
        stock_grid.addWidget(self.min_stock, 2, 1)
        stock_grid.addWidget(self._label("원산지"), 2, 2)
        stock_grid.addWidget(self.fields["origin"], 2, 3)
        stock_grid.addWidget(self._label("보관 창고"), 3, 0)
        stock_grid.addWidget(self.fields["warehouse"], 3, 1)
        stock_grid.addWidget(self._label("매대·위치"), 3, 2)
        stock_grid.addWidget(self.fields["shelf"], 3, 3)
        self._row(stock_grid, 4, "박스 입수", self.box_quantity)
        self.box_quantity.setToolTip("보관용 입수 정보입니다. 거래 수량이나 재고를 자동으로 환산하지 않습니다.")
        stock_grid.setRowStretch(5, 1)
        panels.addWidget(stock, 0, 1)

        pricing, pricing_grid = self._group("가격정보")
        self.purchase_price_label = self._label("매입 단가 (원)")
        self.sale_price_label = self._label("판매 단가 (원)")
        pricing_grid.addWidget(self.purchase_price_label, 0, 0)
        pricing_grid.addWidget(self.purchase_price, 0, 1, 1, 3)
        pricing_grid.addWidget(self.sale_price_label, 1, 0)
        pricing_grid.addWidget(self.sale_price, 1, 1, 1, 3)
        self.margin_label = QLabel()
        self.margin_label.setObjectName("productMargin")
        self.margin_label.setWordWrap(True)
        pricing_grid.addWidget(self.margin_label, 2, 0, 1, 4)
        unit_note = QLabel("단가는 거래 단위 기준입니다. 과세 구분은 분류 정보로만 저장됩니다.")
        unit_note.setObjectName("productMeta")
        unit_note.setWordWrap(True)
        pricing_grid.addWidget(unit_note, 3, 0, 1, 4)
        pricing_grid.setRowStretch(4, 1)
        panels.addWidget(pricing, 1, 0)

        description, description_grid = self._group("상품 설명 · 관리 메모")
        self._row(description_grid, 0, "키워드", self.fields["keywords"])
        description_grid.addWidget(self.memo, 1, 0, 1, 4)
        description_grid.setRowStretch(1, 1)
        panels.addWidget(description, 1, 1)
        form_layout.addLayout(panels)
        form_layout.addStretch(1)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, "상품정보")

        self.history_tables = {}
        self.history_filters = {}
        self.history_summaries = {}
        self.history_totals = self.history_summaries
        self.history_hints = {}
        for kind, label in [("purchase", "매입정보"), ("sale", "판매정보"), ("stock", "재고정보")]:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(12)
            if kind != "stock":
                filters = QHBoxLayout()
                dates_enabled = QCheckBox("기간 지정")
                start, end = date_edit(), date_edit()
                start.setDate(QDate.currentDate().addMonths(-1))
                self._compact(start)
                self._compact(end)
                start.setEnabled(False)
                end.setEnabled(False)
                dates_enabled.toggled.connect(start.setEnabled)
                dates_enabled.toggled.connect(end.setEnabled)
                refresh = QPushButton("조회")
                refresh.setMinimumHeight(32)
                refresh.clicked.connect(lambda _checked=False, key=kind: self.load_history({"purchase": 1, "sale": 2}[key]))
                filters.addWidget(dates_enabled)
                filters.addWidget(start)
                filters.addWidget(QLabel("~"))
                filters.addWidget(end)
                filters.addStretch(1)
                filters.addWidget(refresh)
                layout.addLayout(filters)
                self.history_filters[kind] = (dates_enabled, start, end)
            hint = QLabel("상품 저장 후 실제 거래·재고 이력을 확인할 수 있습니다.")
            hint.setObjectName("productMeta")
            hint.setWordWrap(True)
            self.history_hints[kind] = hint
            layout.addWidget(hint)
            headers = (["일자", "전표번호", "거래처", "수량", "단가 (원)", "금액 (원)", "상태"]
                       if kind != "stock" else ["일자", "구분", "수량", "잔여 재고", "전표번호", "사유"])
            history = table(headers)
            history.setObjectName(f"productHistory_{kind}")
            self.history_tables[kind] = history
            layout.addWidget(history, 1)
            totals = QLabel()
            totals.setObjectName("productMargin")
            totals.setWordWrap(True)
            self.history_summaries[kind] = totals
            layout.addWidget(totals)
            self.tabs.addTab(page, label)

        change_page = QWidget()
        change_layout = QVBoxLayout(change_page)
        change_layout.setContentsMargins(14, 14, 14, 14)
        self.changes_hint = QLabel("상품 저장 후 등록·수정 내역을 확인할 수 있습니다.")
        self.changes_hint.setObjectName("productMeta")
        self.changes_hint.setWordWrap(True)
        change_layout.addWidget(self.changes_hint)
        self.changes_table = table(["변경일시", "작업자", "구분", "변경 내용"])
        self.change_table = self.changes_table
        self.changes_table.setObjectName("productChangeLog")
        change_layout.addWidget(self.changes_table, 1)
        self.tabs.addTab(change_page, "변경로그")
        self.tabs.currentChanged.connect(self.load_history)

        self.record_context = QLabel()
        self.record_context.setObjectName("productMeta")
        self.record_context.setWordWrap(True)
        self.layout.addWidget(self.record_context)
        self.button_box = self.buttons(callback=self.save)
        self.apply_button = self.button_box.addButton("적용", QDialogButtonBox.ButtonRole.ApplyRole)
        self.apply_button.setObjectName("productApply")
        self.apply_button.setMinimumHeight(38)
        self.apply_button.clicked.connect(self.apply_changes)
        self.purchase_price.textChanged.connect(self.update_price_summary)
        self.sale_price.textChanged.connect(self.update_price_summary)
        self.unit.currentTextChanged.connect(self.update_price_summary)
        self.refresh_record_context()
        self.update_history_access()
        self.update_price_summary()
        self.fields["name"].setFocus()

    @staticmethod
    def _compact(widget):
        widget.setMinimumHeight(32)
        return widget

    @staticmethod
    def _label(text):
        label = QLabel(text)
        label.setObjectName("productFieldLabel")
        return label

    @staticmethod
    def _group(title):
        group = QGroupBox(title)
        group.setObjectName("productGroup")
        grid = QGridLayout(group)
        grid.setContentsMargins(12, 16, 12, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return group, grid

    def _row(self, grid, row, label, widget):
        grid.addWidget(self._label(label), row, 0)
        grid.addWidget(widget, row, 1, 1, 3)

    def pick_supplier(self):
        picker = PartnerPicker(self.service, "supplier", self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            selected = picker.selected
            index = self.supplier.findData(selected["id"])
            if index < 0:
                self.supplier.addItem(f"{selected['name']}  ·  {selected['code']}", selected["id"])
                index = self.supplier.count() - 1
            self.supplier.setCurrentIndex(index)

    def update_price_summary(self, *_):
        purchase = Decimal(self.purchase_price.text() or "0")
        sale = Decimal(self.sale_price.text() or "0")
        unit = self.unit.currentText().strip() or "거래 단위"
        self.purchase_price_label.setText(f"매입 단가 (원/{unit})")
        self.sale_price_label.setText(f"판매 단가 (원/{unit})")
        margin = (sale - purchase) / sale * 100 if sale else None
        margin_text = f"{margin.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}%" if margin is not None else "—"
        self.margin_label.setText(f"판매 기준 이익률  {margin_text}     단위당 차액  {money(sale - purchase)} 원")
        self.margin_label.setStyleSheet("color: #BC4B3B;" if sale and sale < purchase else "")

    def refresh_record_context(self):
        unit = self.record.get("unit", self.unit.currentText())
        self.stock_quantity_label.setText(f"{quantity(self.record.get('stock_qty'))} {unit}")
        self.stock_cost_label.setText(f"{money(self.record.get('stock_cost'))} 원")
        if self.record.get("id"):
            def readable_time(value):
                if not value:
                    return "기존 자료 · 일시 미기록"
                try:
                    return datetime.fromisoformat(str(value)).astimezone().strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    return str(value)
            created = readable_time(self.record.get("created_at"))
            updated = readable_time(self.record.get("updated_at"))
            self.record_context.setText(f"상품 코드  {self.record.get('code', '')}    ·    등록  {created}    ·    수정  {updated}")
        else:
            self.record_context.setText("새 상품  ·  * 필수 항목    |    적용: 저장 후 계속 편집    ·    저장: 저장 후 닫기")

    def update_history_access(self):
        for index, permission in [(1, "purchases"), (2, "sales"), (3, "inventory")]:
            allowed = self.service.has_permission(permission) or self.service.has_permission("reports")
            self.tabs.setTabEnabled(index, allowed)
            self.tabs.setTabToolTip(index, "" if allowed else "이력 조회 권한이 필요합니다.")
        allowed = self.service.has_permission("products") or self.service.has_permission("reports")
        self.tabs.setTabEnabled(4, allowed)
        self.tabs.setTabToolTip(4, "" if allowed else "상품 또는 조회 권한이 필요합니다.")

    def load_history(self, tab_index: int):
        if tab_index == 0 or tab_index < 0 or not self.tabs.isTabEnabled(tab_index):
            return
        if tab_index == 4:
            self.load_changes()
            return
        kind = ["purchase", "sale", "stock"][tab_index - 1]
        widget = self.history_tables[kind]
        widget.setRowCount(0)
        if not self.record.get("id"):
            self.history_hints[kind].setText("상품 저장 후 실제 거래·재고 이력을 확인할 수 있습니다.")
            self.history_summaries[kind].setText("")
            return
        try:
            if kind == "stock":
                labels = {"purchase": "매입", "sale": "매출", "adjustment": "재고 조정", "stocktake": "재고 실사", "cancel_purchase": "매입 취소", "cancel_sale": "매출 취소"}
                records = self.service.list_stock_movements(self.record["id"])
                for item in records:
                    put_row(widget, [item.get("date", ""), labels.get(item.get("kind"), item.get("kind", "")), quantity(item.get("qty")), quantity(item.get("balance_qty")), item.get("document_number", ""), item.get("reason", "")])
                self.history_summaries[kind].setText(f"재고 변동  {len(records):,}건    ·    현재 재고  {quantity(self.record.get('stock_qty'))} {self.record.get('unit', '')}")
            else:
                records = self.service.product_history(self.record["id"], kind)
                enabled, start, end = self.history_filters[kind]
                if enabled.isChecked():
                    first, last = start.date().toString("yyyy-MM-dd"), end.date().toString("yyyy-MM-dd")
                    if first > last:
                        raise ValueError("조회 시작일은 종료일보다 늦을 수 없습니다.")
                    records = [item for item in records if first <= str(item.get("date", ""))[:10] <= last]
                for item in records:
                    put_row(widget, [item.get("date", ""), item.get("number", ""), item.get("partner_name", ""), quantity(item.get("qty")), money(item.get("unit_price")), money(item.get("item_total", 0)), "취소" if item.get("status") == "cancelled" else "정상"])
                posted = [item for item in records if item.get("status") != "cancelled"]
                qty = sum((Decimal(str(item.get("qty") or "0")) for item in posted), Decimal("0"))
                amount = sum(item.get("item_total", 0) for item in posted)
                self.history_summaries[kind].setText(f"조회  {len(records):,}건    ·    정상 수량  {quantity(qty)} {self.record.get('unit', '')}    ·    정상 금액  {money(amount)} 원    (취소 제외)")
            self.history_hints[kind].setText("실제 저장된 이력입니다." if records else "조회 조건에 해당하는 이력이 없습니다.")
            widget.resizeColumnsToContents()
        except Exception as error:
            self.error(error)

    def load_changes(self):
        self.changes_table.setRowCount(0)
        if not self.record.get("id"):
            return
        labels = {
            "code": "상품 코드", "barcode": "바코드", "name": "상품명", "category": "대분류",
            "category_mid": "중분류", "category_small": "소분류", "specification": "규격",
            "origin": "원산지", "receipt_name": "상품 표기명", "unit": "거래 단위",
            "capacity": "용량", "unit_capacity": "단위 용량", "supplier_id": "공급사 ID",
            "purchase_price": "매입 단가", "sale_price": "판매 단가", "min_stock": "최소 재고",
            "active": "사용 여부", "memo": "관리 메모", "tax_type": "과세 구분",
            "box_quantity": "박스 입수", "warehouse": "보관 창고", "shelf": "매대·위치", "keywords": "키워드",
        }

        def display(key, value):
            if value in (None, ""):
                return "—"
            if key == "tax_type":
                return {"exempt": "면세", "taxable": "과세"}.get(value, str(value))
            if key == "active":
                return "사용" if value else "사용 중지"
            return str(value)

        try:
            records = self.service.product_changes(self.record["id"])
            for item in records:
                try:
                    detail = json.loads(item.get("detail") or "{}")
                except (TypeError, ValueError):
                    detail = {}
                changes = detail.get("changes", {}) if isinstance(detail, dict) else {}
                summary = []
                if isinstance(changes, dict):
                    for key, change in changes.items():
                        if key not in labels or not isinstance(change, dict):
                            continue
                        summary.append(f"{labels[key]}: {display(key, change.get('old'))} → {display(key, change.get('new'))}")
                action = {"create": "등록", "update": "수정", "adjust_stock": "재고 조정"}.get(item.get("action"), "변경")
                if item.get("action") == "adjust_stock" and isinstance(detail, dict):
                    summary = [f"재고 증감: {detail.get('qty', '—')} {self.record.get('unit', '')}",
                               f"조정 사유: {detail.get('reason', '—')}"]
                if not summary:
                    summary = ["상품 등록" if item.get("action") == "create" else "상품 정보 수정 (상세 기록 없음)"]
                row = put_row(self.changes_table, [str(item.get("at", item.get("created_at", ""))).replace("T", " "),
                             item.get("user_name") or item.get("username", ""), action, "  /  ".join(summary)])
                self.changes_table.item(row, 3).setToolTip("\n".join(summary))
            self.changes_hint.setText(f"등록·수정 기록 {len(records):,}건  ·  변경 내용 위에 마우스를 올리면 전체 내용을 확인할 수 있습니다.")
            self.changes_table.setColumnWidth(0, 200)
            self.changes_table.setColumnWidth(1, 110)
            self.changes_table.setColumnWidth(2, 65)
        except Exception as error:
            self.error(error)

    def apply_changes(self):
        self.save(close=False)

    def save(self, close=True):
        try:
            data = {key: value.text().strip() for key, value in self.fields.items()}
            if not data["name"]:
                raise ValueError("상품명을 입력해 주세요.")
            if not self.unit.currentText().strip():
                raise ValueError("거래 단위를 입력해 주세요.")
            data.update(
                unit=self.unit.currentText().strip(), supplier_id=self.supplier.currentData(),
                purchase_price=int(self.purchase_price.text() or "0"),
                sale_price=int(self.sale_price.text() or "0"),
                min_stock=str(Decimal(self.min_stock.text() or "0")),
                active=self.active.isChecked(), memo=self.memo.toPlainText().strip(),
                tax_type=self.tax_type.currentData(),
                box_quantity=str(Decimal(self.box_quantity.text() or "0")),
            )
            self.saved_id = self.service.save_product(data, self.record.get("id"))
            self.record = next((item for item in self.service.list_products() if item["id"] == self.saved_id),
                               {**self.record, **data, "id": self.saved_id})
            if close:
                self.accept()
            else:
                self.setWindowTitle("상품 등록정보 · 서영 POS")
                self.refresh_record_context()
                self.load_history(self.tabs.currentIndex())
        except (ValueError, InvalidOperation, PermissionError) as error:
            self.error(error)
        except Exception as error:
            self.error(error)


class DocumentDialog(BusinessDialog):
    def __init__(self, service, kind: str, partner: dict | None = None, document_id: int | None = None, parent=None):
        self.service, self.kind = service, kind
        self.partner, self.document_id = partner, document_id
        self.changed = False
        self.document = service.get_document(document_id) if document_id else None
        self.products = []
        self.loading = True
        label = "매입" if kind == "purchase" else "매출"
        super().__init__(f"{label}전표 {'상세' if document_id else '등록'}", "거래 단위 기준 수량과 단가를 입력하세요. 저장 시 거래·재고·미결제 잔액이 함께 반영됩니다.", parent)
        self.resize(1050, 760)
        header = QHBoxLayout()
        self.partner_label = line_edit()
        self.partner_label.setReadOnly(True)
        self.partner_label.setPlaceholderText("공급사 선택" if kind == "purchase" else "고객·거래처 선택")
        self.partner_button = QPushButton("공급사 검색" if kind == "purchase" else "거래처 검색")
        self.partner_button.clicked.connect(self.pick_partner)
        self.date = date_edit(self.document.get("date", "") if self.document else "")
        self.date.setToolTip("상품을 선택할 때 이 날짜의 특매·기본 단가를 제시합니다. 날짜만 바꾸면 수동 단가는 유지되며, '기간 단가 적용'으로 다시 계산할 수 있습니다.")
        header.addWidget(QLabel("거래일"))
        header.addWidget(self.date)
        header.addSpacing(18)
        header.addWidget(self.partner_label, 1)
        header.addWidget(self.partner_button)
        if not self.document:
            self.price_button = QPushButton("기간 단가 적용")
            self.price_button.setToolTip("선택한 거래일의 특매 또는 기본 단가로 모든 상품 단가를 다시 적용합니다. 수동 입력 단가가 바뀝니다.")
            self.price_button.clicked.connect(self.apply_period_prices)
            header.addWidget(self.price_button)
        self.layout.addLayout(header)
        self.items = table(["상품 / 규격", "단위", "수량", "단가 (원)", "금액 (원)", ""])
        self.items.setObjectName("documentItems")
        self.items.horizontalHeader().setStretchLastSection(False)
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in [(1, 65), (2, 125), (3, 150), (4, 150), (5, 60)]:
            self.items.setColumnWidth(column, width)
        self.items.verticalHeader().setDefaultSectionSize(46)
        self.layout.addWidget(self.items, 1)
        self.add_button = QPushButton("+  상품 행 추가")
        self.add_button.clicked.connect(self.add_line)
        self.layout.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignLeft)
        footer = QGridLayout()
        self.memo = QTextEdit(self.document.get("memo", "") if self.document else "")
        self.memo.setMaximumHeight(80)
        self.memo.setPlaceholderText("전표 메모")
        footer.addWidget(QLabel("메모"), 0, 0)
        footer.addWidget(self.memo, 1, 0, 2, 1)
        totals = QFormLayout()
        self.total_label = QLabel("0 원")
        self.total_label.setObjectName("totalValue")
        self.paid = number_edit(self.document.get("paid", 0) if self.document else 0)
        self.paid.setObjectName("documentPaid")
        self.balance_label = QLabel("0 원")
        self.balance_label.setObjectName("balanceValue")
        totals.addRow("전표 합계", self.total_label)
        totals.addRow("결제 금액 (원)", self.paid)
        totals.addRow("미결제 잔액", self.balance_label)
        footer.addLayout(totals, 0, 1, 3, 1)
        footer.setColumnStretch(0, 1)
        footer.setColumnMinimumWidth(1, 295)
        self.layout.addLayout(footer)
        self.paid.textChanged.connect(self.recalculate)
        if self.document:
            self.partner_label.setText(self.document.get("partner_name", ""))
            for item in self.document["items"]:
                self.add_readonly_line(item)
            self.date.setEnabled(False)
            self.partner_button.hide()
            self.add_button.hide()
            self.memo.setReadOnly(True)
            self.paid.setReadOnly(True)
            actions = QHBoxLayout()
            self.status = QLabel()
            actions.addWidget(self.status, 1)
            self.payment_button = primary(QPushButton("추가 결제"))
            self.payment_button.clicked.connect(self.add_payment)
            self.cancel_button = QPushButton("전표 취소")
            self.cancel_button.setObjectName("dangerButton")
            self.cancel_button.clicked.connect(self.cancel_document)
            actions.addWidget(self.payment_button)
            actions.addWidget(self.cancel_button)
            self.layout.addLayout(actions)
            self.payments_table = table(["결제일", "결제액", "메모"])
            self.payments_table.setMaximumHeight(130)
            self.layout.addWidget(self.payments_table)
            self.buttons(close_only=True)
            self.update_detail()
        else:
            self.products = [product for product in self.service.list_products() if product.get("active", True)]
            if self.partner:
                self.partner_label.setText(f"{self.partner['name']}  ·  {self.partner['code']}")
            self.add_line()
            self.buttons("전표 저장", self.save)
        self.loading = False
        self.recalculate()

    def pick_partner(self):
        picker = PartnerPicker(self.service, "supplier" if self.kind == "purchase" else "customer", self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.partner = picker.selected
            self.partner_label.setText(f"{self.partner['name']}  ·  {self.partner['code']}")

    def add_line(self):
        row = self.items.rowCount()
        self.items.insertRow(row)
        product = QComboBox()
        product.setEditable(True)
        product.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        product.addItem("상품명·코드·바코드로 검색", None)
        for record in self.products:
            product.addItem(f"{record['name']}  ·  {record['code']}  {record.get('barcode', '')}", record["id"])
        completer = product.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        qty, price = number_edit("1", True), number_edit("0")
        unit = QLabel("—")
        unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        amount = QLabel("0")
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        remove = QPushButton("×")
        remove.setToolTip("상품 행 삭제")
        self.items.setCellWidget(row, 0, product)
        self.items.setCellWidget(row, 1, unit)
        self.items.setCellWidget(row, 2, qty)
        self.items.setCellWidget(row, 3, price)
        self.items.setCellWidget(row, 4, amount)
        self.items.setCellWidget(row, 5, remove)

        def selected(_index):
            record = next((item for item in self.products if item["id"] == product.currentData()), None)
            unit.setText(record["unit"] if record else "—")
            price.setText(str(self.service.get_effective_price(record["id"], self.date.date().toString("yyyy-MM-dd"), self.kind)) if record else "0")
            self.recalculate()

        def delete():
            for index in range(self.items.rowCount()):
                if self.items.cellWidget(index, 5) is remove:
                    self.items.removeRow(index)
                    break
            self.recalculate()

        product.currentIndexChanged.connect(selected)
        product.editTextChanged.connect(lambda _: self.recalculate())
        qty.textChanged.connect(self.recalculate)
        price.textChanged.connect(self.recalculate)
        remove.clicked.connect(delete)
        if not self.loading:
            product.setFocus()

    def apply_period_prices(self):
        if self.document:
            return
        if QMessageBox.question(self, "기간 단가 적용", "선택한 거래일의 특매·기본 단가를 모든 상품에 다시 적용할까요?\n직접 입력한 단가도 변경됩니다.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            prices = []
            for row in range(self.items.rowCount()):
                product = self.items.cellWidget(row, 0)
                if product.currentData() and product.currentText() == product.itemText(product.currentIndex()):
                    prices.append((row, self.service.get_effective_price(product.currentData(), self.date.date().toString("yyyy-MM-dd"), self.kind)))
            for row, value in prices:
                self.items.cellWidget(row, 3).setText(str(value))
            self.recalculate()
        except (ValueError, PermissionError) as error:
            self.error(error)

    def add_readonly_line(self, record: dict):
        put_row(self.items, [record.get("product_name", ""), record.get("unit", ""), quantity(record.get("qty")), money(record.get("unit_price")), money(record.get("total")), ""])

    def recalculate(self, *_):
        if self.loading:
            return
        total = 0
        if self.document:
            total = self.document["total"]
        else:
            for row in range(self.items.rowCount()):
                try:
                    qty = Decimal(self.items.cellWidget(row, 2).text() or "0")
                    price = int(self.items.cellWidget(row, 3).text() or "0")
                    amount = int((qty * price).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                except (ValueError, InvalidOperation):
                    amount = 0
                self.items.cellWidget(row, 4).setText(money(amount))
                total += amount
        paid = int(self.paid.text() or "0")
        self.total_label.setText(f"{money(total)} 원")
        balance = self.document["balance"] if self.document else total - paid
        self.balance_label.setText(f"{money(balance)} 원")

    def save(self):
        try:
            if not self.partner:
                raise ValueError("거래처를 선택해 주세요.")
            items = []
            for row in range(self.items.rowCount()):
                combo = self.items.cellWidget(row, 0)
                product_id = combo.currentData()
                if not product_id or combo.currentText() != combo.itemText(combo.currentIndex()):
                    raise ValueError(f"{row + 1}행의 상품을 검색 목록에서 선택해 주세요.")
                qty = Decimal(self.items.cellWidget(row, 2).text() or "0")
                if qty <= 0:
                    raise ValueError(f"{row + 1}행의 수량은 0보다 커야 합니다.")
                items.append({"product_id": product_id, "qty": str(qty), "unit_price": int(self.items.cellWidget(row, 3).text() or "0")})
            if not items:
                raise ValueError("상품을 한 개 이상 추가해 주세요.")
            self.saved_id = self.service.create_document(
                self.kind, self.partner["id"], self.date.date().toString("yyyy-MM-dd"), items,
                paid=int(self.paid.text() or "0"), memo=self.memo.toPlainText().strip(),
            )
            self.accept()
        except Exception as error:
            self.error(error)

    def update_detail(self):
        self.document = self.service.get_document(self.document_id)
        cancelled = self.document.get("status") == "cancelled"
        self.status.setText("취소된 전표 · 거래 이력 보존" if cancelled else f"전표번호 {self.document['number']}")
        self.paid.setText(str(self.document["paid"]))
        can_manage = self.service.has_permission("purchases" if self.kind == "purchase" else "sales")
        self.payment_button.setEnabled(can_manage and not cancelled and self.document["balance"] > 0)
        self.cancel_button.setEnabled(can_manage and not cancelled and self.document["paid"] == 0)
        self.payment_button.setToolTip("전표 관리 권한이 필요합니다." if not can_manage else "전표 미결제 잔액 결제")
        self.cancel_button.setToolTip("전표 관리 권한이 필요합니다." if not can_manage else "결제된 전표는 취소할 수 없습니다." if self.document["paid"] else "미결제 전표 취소")
        self.payments_table.setRowCount(0)
        for payment in self.document.get("payments", []):
            put_row(self.payments_table, [payment.get("date", ""), money(payment.get("amount")), payment.get("memo", "")])
        self.recalculate()

    def add_payment(self):
        dialog = BusinessDialog("추가 결제", "결제액을 입력하면 전표의 미결제 잔액이 줄어듭니다.", self)
        form = QFormLayout()
        payment_date = date_edit()
        amount = number_edit(self.document["balance"])
        memo = line_edit("", "계좌이체·현금 등 결제 메모")
        form.addRow("결제일", payment_date)
        form.addRow("결제액 (원)", amount)
        form.addRow("메모", memo)
        dialog.layout.addLayout(form)

        def save():
            try:
                value = int(amount.text() or "0")
                if value <= 0:
                    raise ValueError("결제액은 0보다 커야 합니다.")
                self.service.add_payment(self.document_id, value, payment_date.date().toString("yyyy-MM-dd"), memo.text().strip())
                self.changed = True
                dialog.accept()
                self.update_detail()
            except Exception as error:
                dialog.error(error)

        dialog.buttons("결제 저장", save)
        dialog.exec()

    def cancel_document(self):
        dialog = BusinessDialog("전표 취소", "전표를 취소하면 재고와 미결제 잔액이 되돌려집니다. 취소 이력은 보존됩니다.", self)
        reason = line_edit("", "취소 사유를 입력하세요")
        dialog.layout.addWidget(reason)

        def cancel():
            try:
                if not reason.text().strip():
                    raise ValueError("취소 사유를 입력해 주세요.")
                self.service.cancel_document(self.document_id, reason.text().strip())
                self.changed = True
                dialog.accept()
                self.update_detail()
            except Exception as error:
                dialog.error(error)

        dialog.buttons("전표 취소 확인", cancel)
        dialog.exec()


class UserDialog(BusinessDialog):
    def __init__(self, service, record: dict | None = None, parent=None):
        self.service, self.record = service, record or {}
        super().__init__("사용자 수정" if record else "사용자 등록", "관리자는 전체 기능을 사용할 수 있습니다. 일반 사용자는 허용한 업무만 접근합니다.", parent)
        self.resize(650, 620)
        form = QFormLayout()
        form.setSpacing(13)
        self.username = line_edit(self.record.get("username", ""), "로그인 아이디")
        self.name = line_edit(self.record.get("name", ""), "사용자 이름")
        self.password = line_edit("", "변경할 때만 입력" if record else "8자 이상 비밀번호")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.role = QComboBox()
        self.role.addItem("일반 사용자", "staff")
        self.role.addItem("관리자", "admin")
        self.role.setCurrentIndex(1 if self.record.get("role") == "admin" else 0)
        form.addRow("아이디 *", self.username)
        form.addRow("이름 *", self.name)
        form.addRow("비밀번호" if record else "비밀번호 *", self.password)
        form.addRow("계정 유형", self.role)
        self.layout.addLayout(form)
        self.layout.addWidget(QLabel("접근 권한"))
        permissions = self.record.get("permissions", [])
        self.permissions = {}
        grid = QGridLayout()
        for index, (key, title) in enumerate(PERMISSIONS.items()):
            check = QCheckBox(title)
            check.setChecked(key in permissions or (not record and key not in ("users", "settings")))
            self.permissions[key] = check
            grid.addWidget(check, index // 2, index % 2)
        self.layout.addLayout(grid)
        self.layout.addStretch()
        self.role.currentIndexChanged.connect(self.update_role)
        self.update_role()
        self.buttons(callback=self.save)

    def update_role(self):
        admin = self.role.currentData() == "admin"
        for key, checkbox in self.permissions.items():
            checkbox.setEnabled(not admin and key not in ("users", "settings"))
            if admin:
                checkbox.setChecked(True)
            elif key in ("users", "settings"):
                checkbox.setChecked(False)

    def save(self):
        try:
            if not self.username.text().strip() or not self.name.text().strip():
                raise ValueError("아이디와 이름을 입력해 주세요.")
            if not self.record and not self.password.text():
                raise ValueError("비밀번호를 입력해 주세요.")
            data = {
                "username": self.username.text().strip(), "name": self.name.text().strip(),
                "role": self.role.currentData(),
                "permissions": [key for key, checkbox in self.permissions.items() if checkbox.isChecked()],
            }
            if self.password.text():
                data["password"] = self.password.text()
            self.saved_id = self.service.save_user(data, self.record.get("id"))
            self.accept()
        except Exception as error:
            self.error(error)


class PasswordDialog(BusinessDialog):
    def __init__(self, service, parent=None):
        self.service = service
        super().__init__("내 비밀번호 변경", "현재 비밀번호를 확인한 후 새 비밀번호로 변경합니다.", parent)
        form = QFormLayout()
        form.setSpacing(14)
        self.old = line_edit("", "현재 비밀번호")
        self.new = line_edit("", "8자 이상 새 비밀번호")
        self.confirm = line_edit("", "새 비밀번호 다시 입력")
        for field in (self.old, self.new, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("현재 비밀번호", self.old)
        form.addRow("새 비밀번호", self.new)
        form.addRow("새 비밀번호 확인", self.confirm)
        self.layout.addLayout(form)
        self.buttons("비밀번호 변경", self.save)

    def save(self):
        try:
            if self.new.text() != self.confirm.text():
                raise ValueError("새 비밀번호 확인이 일치하지 않습니다.")
            self.service.change_password(self.old.text(), self.new.text())
            self.accept()
        except Exception as error:
            self.error(error)
