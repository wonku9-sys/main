"""Keyboard-friendly Korean business dialogs for 서영 POS."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from PySide6.QtCore import QDate, QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDateEdit,
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)


PERMISSIONS = {
    "products": "상품 관리", "partners": "거래처 관리", "purchases": "매입 관리",
    "sales": "매출 관리", "inventory": "재고 관리", "reports": "조회·엑셀",
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


class LoginDialog(BusinessDialog):
    def __init__(self, service, parent: QWidget | None = None):
        self.service = service
        self.initial = service.users_count() == 0
        super().__init__(
            "서영 POS 시작하기" if self.initial else "서영 POS 로그인",
            "첫 관리자 계정을 만들어 매장 관리를 시작하세요." if self.initial else
            "오늘의 거래, 재고와 미결제 잔액을 한곳에서 관리하세요.", parent,
        )
        self.setFixedWidth(500)
        form = QFormLayout()
        form.setSpacing(14)
        self.username = line_edit("", "로그인 아이디")
        self.username.setObjectName("loginUsername")
        self.name = line_edit("", "예: 매장 관리자")
        self.password = line_edit("", "8자 이상 비밀번호" if self.initial else "비밀번호")
        self.password.setObjectName("loginPassword")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = line_edit("", "비밀번호를 한 번 더 입력하세요")
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("아이디", self.username)
        if self.initial:
            form.addRow("이름", self.name)
        form.addRow("비밀번호", self.password)
        if self.initial:
            form.addRow("비밀번호 확인", self.confirm)
        self.layout.addLayout(form)
        note = QLabel("오프라인 사용 · 거래자료는 이 기기에 안전하게 보관됩니다.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        self.layout.addWidget(note)
        self.buttons("관리자 계정 만들기" if self.initial else "로그인", self.submit)
        self.username.setFocus()

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
            self.service.login(username, password)
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
        self.service, self.record = service, record or {}
        super().__init__("상품 수정" if record else "새 상품 등록", "중량과 단가를 정확하게 관리하고 거래·재고 이력을 확인하세요.", parent)
        self.resize(880, 720)
        tabs = QTabWidget()
        self.layout.addWidget(tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(16, 22, 16, 18)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(14)
        self.fields = {}
        definitions = [
            ("code", "상품 코드 *", "중복되지 않는 상품 코드"), ("barcode", "바코드", "스캐너 입력 가능"),
            ("name", "상품명 *", "예: 국내산 삼겹살"), ("category", "분류", "예: 돈육 / 우육 / 가공"),
            ("specification", "규격", "예: 냉장 · 구이용"), ("origin", "원산지", "예: 국내산"),
        ]
        for index, (key, title, placeholder) in enumerate(definitions):
            field = line_edit(self.record.get(key, ""), placeholder)
            field.setObjectName(f"product_{key}")
            self.fields[key] = field
            column, row = index % 2, index // 2
            form = QVBoxLayout()
            form.setSpacing(6)
            form.addWidget(QLabel(title))
            form.addWidget(field)
            grid.addLayout(form, row, column)
        self.unit = QComboBox()
        self.unit.addItems(["kg", "g", "개", "박스", "팩", "EA", "L", "mL"])
        self.unit.setEditable(True)
        self.unit.setCurrentText(self.record.get("unit", "kg"))
        self.supplier = QComboBox()
        self.supplier.addItem("공급사 미지정", None)
        try:
            for partner in service.list_partners("supplier"):
                self.supplier.addItem(f"{partner['name']}  ·  {partner['code']}", partner["id"])
        except Exception as error:
            self.error(error)
        index = self.supplier.findData(self.record.get("supplier_id"))
        self.supplier.setCurrentIndex(max(index, 0))
        for column, (title, field) in enumerate([("거래 단위", self.unit), ("기본 공급사", self.supplier)]):
            form = QVBoxLayout()
            form.setSpacing(6)
            form.addWidget(QLabel(title))
            form.addWidget(field)
            grid.addLayout(form, 3, column)
        self.purchase_price = number_edit(self.record.get("purchase_price", 0))
        self.sale_price = number_edit(self.record.get("sale_price", 0))
        self.min_stock = number_edit(self.record.get("min_stock", "0"), True)
        for index, (title, field) in enumerate([
            ("매입 단가 (원 / 거래 단위)", self.purchase_price),
            ("판매 단가 (원 / 거래 단위)", self.sale_price),
            ("최소 재고 (거래 단위)", self.min_stock),
        ]):
            form = QVBoxLayout()
            form.setSpacing(6)
            form.addWidget(QLabel(title))
            form.addWidget(field)
            grid.addLayout(form, 4 + index // 2, index % 2)
        self.active = QCheckBox("사용 중인 상품")
        self.active.setChecked(bool(self.record.get("active", True)))
        grid.addWidget(self.active, 5, 1)
        self.memo = QTextEdit(self.record.get("memo", ""))
        self.memo.setPlaceholderText("이력번호·보관 방법 등 필요한 정보를 기록하세요.")
        self.memo.setMaximumHeight(90)
        grid.addWidget(QLabel("메모"), 6, 0, 1, 2)
        grid.addWidget(self.memo, 7, 0, 1, 2)
        note = QLabel("단가는 선택한 거래 단위 기준입니다. 예: 단위 kg, 판매 단가 38,000원 → 0.5kg 판매액 19,000원")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        grid.addWidget(note, 8, 0, 1, 2)
        if record:
            current_stock = QLabel(f"현재 재고  {quantity(record.get('stock_qty'))} {record.get('unit', '')}    ·    재고 원가액  {money(record.get('stock_cost'))} 원")
            current_stock.setObjectName("totalValue")
            grid.addWidget(current_stock, 9, 0, 1, 2)
        grid.setRowStretch(10, 1)
        scroll.setWidget(content)
        tabs.addTab(scroll, "상품정보")
        self.history_tables = {}
        for kind, label in [("purchase", "매입이력"), ("sale", "매출이력"), ("stock", "재고이력")]:
            page = QWidget()
            layout = QVBoxLayout(page)
            if record:
                headers = ["일자", "전표번호", "거래처", "수량", "단가", "금액", "상태"] if kind != "stock" else ["일자", "구분", "수량", "재고", "전표번호", "사유"]
                history = table(headers)
                self.history_tables[kind] = history
                layout.addWidget(history)
            else:
                hint = QLabel("상품을 저장하면 거래와 재고 이력이 표시됩니다.")
                hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hint.setObjectName("mutedLabel")
                layout.addWidget(hint)
            tabs.addTab(page, label)
            needed = {"purchase": "purchases", "sale": "sales", "stock": "inventory"}[kind]
            if record and not (service.has_permission(needed) or service.has_permission("reports")):
                tabs.setTabEnabled(tabs.count() - 1, False)
                tabs.setTabToolTip(tabs.count() - 1, "이력 조회 권한이 필요합니다.")
        tabs.currentChanged.connect(self.load_history)
        self.buttons(callback=self.save)
        self.fields["name"].setFocus()

    def load_history(self, tab_index: int):
        if not self.record or tab_index == 0:
            return
        kind = ["purchase", "sale", "stock"][tab_index - 1]
        widget = self.history_tables[kind]
        widget.setRowCount(0)
        try:
            if kind == "stock":
                labels = {"purchase": "매입", "sale": "매출", "adjustment": "재고 조정", "cancel_purchase": "매입 취소", "cancel_sale": "매출 취소"}
                for item in self.service.list_stock_movements(self.record["id"]):
                    put_row(widget, [item.get("date", ""), labels.get(item.get("kind"), item.get("kind", "")), quantity(item.get("qty")), quantity(item.get("balance_qty")), item.get("document_number", ""), item.get("reason", "")])
            else:
                for item in self.service.product_history(self.record["id"], kind):
                    put_row(widget, [item.get("date", ""), item.get("number", ""), item.get("partner_name", ""), quantity(item.get("qty")), money(item.get("unit_price")), money(item.get("item_total", 0)), "취소" if item.get("status") == "cancelled" else "정상"])
            widget.resizeColumnsToContents()
        except Exception as error:
            self.error(error)

    def save(self):
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
            )
            self.saved_id = self.service.save_product(data, self.record.get("id"))
            self.accept()
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
        header.addWidget(QLabel("거래일"))
        header.addWidget(self.date)
        header.addSpacing(18)
        header.addWidget(self.partner_label, 1)
        header.addWidget(self.partner_button)
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
            price.setText(str(record.get("purchase_price" if self.kind == "purchase" else "sale_price", 0)) if record else "0")
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
