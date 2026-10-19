"""Offline purchasing, selling, ledgers, counts and immutable closeouts."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .widgets import DataGrid, Page, ScanField, action, amount, date_field, search_icon, won
from .common import decimal as value_decimal, money, qty, rounded


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
    start, end = date_field(date.today().replace(day=1)), date_field()
    layout.addWidget(QLabel("기간"))
    layout.addWidget(start)
    layout.addWidget(QLabel("~"))
    layout.addWidget(end)
    layout.addWidget(action("조회", callback))
    return start, end


class PartnerPicker(QDialog):
    """A compulsory counterparty selection, searchable by name or code."""
    def __init__(self, window, kind, for_filter=False):
        super().__init__(window)
        self.store, self.kind, self.selected_record, self.for_filter = window.store, kind, None, for_filter
        self.setWindowTitle("공급사 검색" if kind == "supplier" else "판매처 검색")
        self.resize(700, 510)
        body = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("거래처명 · 코드 · 연락처 검색")
        body.addWidget(self.search)
        self.grid = DataGrid(["코드", "거래처명", "담당자", "연락처"])
        body.addWidget(self.grid)
        self.search.textChanged.connect(self.refresh)
        self.grid.itemDoubleClicked.connect(self.choose)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)
        self.search.returnPressed.connect(self.choose)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.refresh()

    def refresh(self):
        api = getattr(self.store, "trade_partners", self.store.partners)
        rows = self.store.partners(self.kind, self.search.text()) if self.for_filter else [r for r in api(self.kind, self.search.text()) if r.get("active", True)]
        if self.for_filter:
            rows.insert(0, {"id": None, "code": "전체", "name": "전체 공급사" if self.kind == "supplier" else "전체 판매처", "contact": "", "phone": ""})
        self.grid.fill([[r["code"], r["name"], r.get("contact", ""), r.get("phone", "")] for r in rows], rows)

    def choose(self, *_):
        self.selected_record = self.grid.selected()
        if self.selected_record:
            self.accept()


class ProductPicker(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.store, self.record, self.unit_id = parent.store, None, None
        self.supplier_id = parent.partner.currentData() if getattr(parent, "kind", "").startswith("purchase") else None
        self.supplier_name = parent.partner.currentText() if self.supplier_id else ""
        self.selections, self.checked = [], {}
        self.read_permissions = ("trade",)
        self.setWindowTitle("상품 검색")
        self.resize(1080, 600)
        body = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("상품코드 · 기본/확장 바코드 · 상품명 · 규격으로 검색")
        filters.addWidget(self.search, 1)
        self.supplier_only = QCheckBox("선택 공급사만")
        self.supplier_only.setChecked(bool(self.supplier_id))
        self.supplier_only.setEnabled(bool(self.supplier_id))
        self.supplier_only.setToolTip("체크를 해제하면 전체 공급사의 등록 상품을 조회합니다.")
        filters.addWidget(self.supplier_only)
        body.addLayout(filters)
        self.supplier_label = QLabel(parent.partner.currentText() if self.supplier_id else "전체 공급사 상품")
        body.addWidget(self.supplier_label)
        body.addWidget(QLabel("행을 더블클릭하면 한 품목을 적용합니다. 여러 품목은 체크 후 ‘체크 상품 적용’을 누르세요."))
        self.grid = DataGrid(["선택", "상품코드", "상품명", "규격", "바코드", "단위", "공급사", "매입가", "판매가", "현재고"])
        body.addWidget(self.grid, 1)
        self.search.textChanged.connect(self.refresh)
        self.supplier_only.toggled.connect(self.refresh)
        self.grid.itemChanged.connect(self.check_changed)
        self.grid.cellDoubleClicked.connect(lambda *_: self.choose())
        controls = QHBoxLayout()
        controls.addWidget(action("조회 품목 모두 체크", lambda: self.check_all(True)))
        controls.addWidget(action("체크 모두 해제", lambda: self.check_all(False)))
        self.apply_checked_button = action("체크 상품 적용", self.apply_checked, True)
        controls.addStretch()
        controls.addWidget(self.apply_checked_button)
        body.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("선택")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("닫기")
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)
        self.search.returnPressed.connect(lambda: self.apply_checked() if self.checked else self.choose())
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.refresh()

    def refresh(self, *_):
        records = self.store.trade_products(self.search.text().strip(), self.supplier_id if self.supplier_only.isChecked() else None)
        # A scope change must not silently apply checked products hidden outside it.
        if self.supplier_only.isChecked():
            self.checked = {key: row for key, row in self.checked.items() if row.get("supplier_id") == self.supplier_id}
        self.grid.blockSignals(True)
        self.grid.fill([["", r["code"], r["name"], r["specification"], r["barcode"], r["base_unit"], r.get("supplier_name") or "미지정", r["purchase_price"], r["sale_price"], Decimal(r["stock_qty"])] for r in records], records)
        for index in range(self.grid.rowCount()):
            cell = self.grid.item(index, 0)
            record = cell.data(Qt.ItemDataRole.UserRole)
            cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            cell.setCheckState(Qt.CheckState.Checked if record["id"] in self.checked else Qt.CheckState.Unchecked)
        self.grid.blockSignals(False)
        self.supplier_label.setText((self.supplier_name if self.supplier_only.isChecked() else "전체 공급사 상품") + f" · {len(records):,}개")
        self.update_checked_count()
        if records:
            self.grid.selectRow(0)

    def update_checked_count(self):
        self.apply_checked_button.setText(f"체크 상품 적용 ({len(self.checked):,})")

    def check_changed(self, item):
        if item.column() != 0:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if record:
            if item.checkState() == Qt.CheckState.Checked:
                self.checked[record["id"]] = record
            else:
                self.checked.pop(record["id"], None)
        self.update_checked_count()

    def check_all(self, checked):
        if not checked:
            self.checked.clear()
        for index in range(self.grid.rowCount()):
            self.grid.item(index, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.update_checked_count()

    def apply_checked(self):
        if not self.checked:
            return _warn(self, "적용할 상품을 체크하세요.")
        self.selections = [(record, None) for record in self.checked.values()]
        self.record, self.unit_id = self.selections[0]
        self.accept()

    def choose(self):
        record = self.grid.selected()
        if not record:
            return
        self.record = record
        found = self.store.lookup_barcode(self.search.text().strip()) if self.search.text().strip() else None
        if found and found["product"]["id"] == record["id"] and found.get("unit"):
            if not found["unit"].get("active", True):
                _warn(self, "사용 중지된 확장단위입니다. 상품명으로 검색해 유효한 단위를 선택하세요.")
                return
            self.unit_id = found["unit"]["id"]
        self.selections = [(self.record, self.unit_id)]
        self.accept()


class TradeDialog(QDialog):
    """Explicit draft/post workflow; scans only edit unsaved line quantities."""
    def __init__(self, window, kind="purchase", record=None, source=None):
        super().__init__(window)
        self.window, self.store, self.kind = window, window.store, kind
        self.record = self.store.document(record) if isinstance(record, int) else record
        self.source = self.store.document(source) if isinstance(source, int) else source
        self.readonly = bool(self.record and self.record["status"] != "draft")
        self.is_return = kind.endswith("_return")
        self.saved_id = None
        self.line_rows = []
        self.products = self.store.products()
        self.product_map = {p["id"]: p for p in self.products}
        self.line_columns = ("product", "spec", "barcode", "qty", "unit", "factor", "base_qty", "price", "total", "sale_price", "margin", "category", "supplier", "stock", "delete")
        self.setWindowTitle(f"{KINDS[kind]} 전표 · " + (self.record["number"] if self.record else "새 전표"))
        self.resize(1180, 820)
        self.setMinimumSize(850, 620)
        if QApplication.platformName() != "offscreen" and self.screen():
            area = self.screen().availableGeometry()
            self.resize(min(1180, max(850, area.width() - 50)), min(820, max(620, area.height() - 70)))
        body = QVBoxLayout(self)
        heading = QLabel(f"{KINDS[kind]} 전표")
        heading.setObjectName("pageTitle")
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
        self.pick_button = action("거래처 검색", lambda: self.pick_partner(party_kind))
        metadata.addWidget(self.pick_button)
        self.member = QComboBox()
        self.member.addItem("비회원", None)
        if kind.startswith("sale"):
            for member in self.store.trade_members():
                self.member.addItem(f"{member['code']} · {member['name']}", member["id"])
            metadata.addWidget(QLabel("회원"))
            metadata.addWidget(self.member)
        body.addLayout(metadata)
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
        scanner.addWidget(QLabel("바코드 F8"))
        self.scan = ScanField()
        self.scan.setPlaceholderText("USB 스캐너 입력 후 Enter · 확장단위 바코드 지원")
        self.scan.scanned.connect(self.scan_barcode)
        scanner.addWidget(self.scan, 1)
        self.add_button = action("품목 추가", self.add_line)
        self.search_button = action("상품 검색 (F5)", self.pick_product)
        self.quote_button = action("선택 날짜·회원 제안가 적용", self.apply_quotes)
        scanner.addWidget(self.add_button)
        scanner.addWidget(self.search_button)
        scanner.addWidget(self.quote_button)
        body.addLayout(scanner)
        self.table = QTableWidget(0, len(self.line_columns))
        self.table.setHorizontalHeaderLabels(["상품명", "규격", "바코드", "매입량" if kind.startswith("purchase") else "수량", "입력 단위", "환산량", "총수량 (기본단위)", "매입단가" if kind.startswith("purchase") else "거래단가", "매입금액" if kind.startswith("purchase") else "거래금액", "현재 판매단가 (참고)", "예상이익률", "분류", "공급사", "현재고 / 반품 가능", "삭제"])
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((220, 75, 125, 75, 85, 60, 100, 85, 95, 130, 85, 140, 150, 130, 60)):
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
        self.points = QLineEdit(str((self.record or {}).get("points_used", 0)))
        self.points.setMaximumWidth(110)
        settlement.addWidget(QLabel("환불금액" if self.is_return else "결제금액"))
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
        footer.addWidget(self.print_button)
        footer.addWidget(self.excel_button)
        footer.addStretch()
        self.draft_button = action("초안 저장", lambda: self.save(False))
        self.post_button = action("전표 확정", lambda: self.save(True), True)
        self.close_button = action("닫기", self.reject)
        for button in (self.draft_button, self.post_button, self.close_button):
            button.setAutoDefault(False)
            footer.addWidget(button)
        body.addLayout(footer)
        self.shortcut_scan = QShortcut(QKeySequence("F8"), self)
        self.shortcut_scan.activated.connect(self.focus_scan)
        self.shortcut_product = QShortcut(QKeySequence("F5"), self)
        self.shortcut_product.activated.connect(self.pick_product)
        self.shortcut_delete = QShortcut(QKeySequence("F7"), self)
        self.shortcut_delete.activated.connect(self.remove_selected_line)
        lines = (self.record or {}).get("lines") or (self.source or {}).get("lines") or []
        source_lines = self.source or (self.store.document(self.record["source_id"]) if self.is_return and self.record and self.record.get("source_id") else {})
        source_map = {line["id"]: line for line in source_lines.get("lines", [])}
        for line in lines:
            if self.source and Decimal(str(line.get("remaining_qty", line["input_qty"]))) <= 0:
                continue
            source_line = line if self.source else None
            if self.is_return and self.record and line.get("source_line_id"):
                source_line = source_map.get(line["source_line_id"], {**line, "id": line["source_line_id"]})
            row = self.add_line(line["product_id"], line.get("unit_id"), "0" if self.source else line["input_qty"], line["unit_price"], source_line)
            if self.record:
                row["saved_line"] = line
        if not lines and not self.readonly:
            self.add_line()
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
        self.print_button.setEnabled(bool(self.record))
        self.void_button.setEnabled(bool(self.record and self.record["status"] == "posted"))
        self.refresh_payments()
        self.recalculate()

    def update_partner_info(self, *_):
        party = self.party_map.get(self.partner.currentData(), {})
        mode = "수수료 공급사" if party.get("supplier_mode") == "commission" else "직매입" if self.kind.startswith("purchase") else "판매"
        self.partner_info.setText(f"사업자번호 {party.get('business_no') or '미등록'}  ·  {mode}  ·  부가세 포함 단가  ·  담당자 {(self.store.actor or {}).get('name', '')}")

    def focus_scan(self):
        if self.scan.isEnabled():
            self.scan.setFocus()
            self.scan.selectAll()

    def pick_partner(self, kind):
        picker = PartnerPicker(self.window, kind)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.partner.setCurrentIndex(self.partner.findData(picker.selected_record["id"]))

    def add_line(self, product_id=None, unit_id=None, quantity="1", price=None, source_line=None):
        if isinstance(product_id, bool):
            product_id = None
        row = {"source": source_line}
        product = row["product"] = QComboBox()
        product.addItem("상품 선택", None)
        for item in self.products:
            if not item["active"] and not (self.readonly or self.is_return):
                continue
            product.addItem(f"{item['code']} · {item['name']}", item["id"])
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
            row["unit"].addItem(product["base_unit"], None)
            row["units"] = {u["id"]: u for u in self.store.units(identifier)}
            for unit in row["units"].values():
                if unit.get("active", True):
                    row["unit"].addItem(f"{unit['name']} (×{amount(unit['factor'])})", unit["id"])
            row["stock"].setText(f"{amount(product['stock_qty'])} {product['base_unit']}" if product.get("tracked", True) else "재고 미관리")
            row["spec"].setText(product["specification"])
            row["category"].setText(" / ".join(filter(None, (product["category"], product["category_mid"], product["category_small"]))))
            row["supplier"].setText(product.get("supplier_name") or "미지정")
        else:
            row["units"] = {}
            for key in ("spec", "barcode", "factor", "base_qty", "sale_price", "margin", "category", "supplier", "stock"):
                row[key].clear()
        row["unit"].blockSignals(False)
        if identifier:
            self.unit_changed(row)
        else:
            self.recalculate()

    def pick_product(self):
        if self.readonly or self.is_return:
            return
        dialog = ProductPicker(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for record, unit_id in dialog.selections or [(dialog.record, dialog.unit_id)]:
            if not record:
                continue
            self.product_map[record["id"]] = record
            row = next((r for r in self.line_rows if not r["product"].currentData()), None)
            if row is None:
                if not any(item["id"] == record["id"] for item in self.products):
                    self.products.append(record)
                row = self.add_line(record["id"], unit_id)
            else:
                if row["product"].findData(record["id"]) < 0:
                    row["product"].addItem(f"{record['code']} · {record['name']}", record["id"])
                row["product"].setCurrentIndex(row["product"].findData(record["id"]))
                row["unit"].setCurrentIndex(max(0, row["unit"].findData(unit_id)))
            self.table.setCurrentCell(self.line_rows.index(row), 3)
        self.recalculate()

    def unit_changed(self, row):
        identifier = row["product"].currentData()
        if not identifier:
            return
        product = self.product_map[identifier]
        unit = row.get("units", {}).get(row["unit"].currentData()) or {}
        row["barcode"].setText(unit.get("barcode") or product["barcode"])
        row["factor"].setText(amount((row.get("source") or {}).get("factor", unit.get("factor", "1"))))
        row["reference_sale"] = unit.get("sale_price", product["sale_price"])
        row["sale_price"].setText(won(row["reference_sale"]))
        if not row.get("source") and not self.readonly:
            quote = self.store.quote(identifier, _date(self.date), row["unit"].currentData(), self.member.currentData())
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
                factor = value_decimal(snapshot.get("factor", unit.get("factor", "1")))
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
                    value = rounded(quantity * price)
                row["total"].setText(won(value))
                sale = rounded(quantity * row.get("reference_sale", product["sale_price"]))
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
            lines.append({"product_id": product_id, "unit_id": row["unit"].currentData(), "qty": quantity, "unit_price": row["price"].text().strip(), "source_line_id": row["source"]["id"] if row.get("source") else None})
        return {"kind": self.kind, "date": _date(self.date), "partner_id": self.partner.currentData(), "member_id": self.member.currentData(), "source_id": (self.source or self.record or {}).get("id") if self.source else (self.record or {}).get("source_id"), "lines": lines, "paid": self.paid.text(), "method": self.method.currentData(), "points_used": self.points.text() if self.kind == "sale" else 0, "memo": self.memo.text()}

    def save(self, post):
        if self.readonly:
            return
        try:
            data = self.payload()
            if not data["partner_id"]:
                raise ValueError("거래처를 선택하세요.")
            if post and not _confirm(self, "전표 확정", "재고·결제·포인트에 반영합니다. 확정할까요?"):
                return
            identifier = self.record["id"] if self.record else None
            self.saved_id = self.store.post_document(data, identifier) if post else self.store.save_draft(data, identifier)
            self.accept()
        except (ValueError, PermissionError, InvalidOperation) as exc:
            _warn(self, exc)

    def print_document(self):
        if not self.record:
            return
        record = self.store.document(self.record["id"])
        grid = DataGrid(["상품", "단위", "수량", "단가", "금액"])
        grid.fill([[line["product_name"], line["unit_name"], Decimal(line["input_qty"]), line["unit_price"], line["total"]] for line in record["lines"]])
        info = f"{record['number']} · {record['date']} · {record.get('partner_name', '')}\n합계 {won(record['total'])}원 · 결제 {won(record.get('cash_paid', 0))}원 · 포인트 {won(record.get('points_used', 0))} · 잔액 {won(record['balance'])}원 · {STATUSES[record['status']]}"
        grid.print_pages(self, KINDS[self.kind] + " 전표", info)
        grid.deleteLater()

    def export_document(self):
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

    def refresh_payments(self):
        payments = (self.record or {}).get("payments", [])
        self.payments_grid.fill([[p["id"], p["date"], p["amount"], "현금" if p["method"] == "cash" else "계좌이체", p.get("user_name", ""), "취소" if p["voided"] else "유효", p.get("memo", "")] for p in payments], payments)

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


class TradesPage(Page):
    def __init__(self, window, kind="purchase"):
        self.kind = kind
        super().__init__(window, "매입장" if kind == "purchase" else "매출장", "기간과 거래처를 선택해 전표를 조회합니다. 확정·반품·결제를 구분합니다.")
        self.actions.addWidget(action("매입등록" if kind == "purchase" else "매출등록", self.new_trade, True))
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
        for party in self.store.partners(party_kind):
            self.partner_filter.addItem(f"{party['code']} · {party['name']}", party["id"])
        self.partner_filter.setMinimumWidth(145)
        self.partner_lookup = action("거래처 검색", self.pick_filter_partner)
        self.partner_lookup.setIcon(search_icon())
        self.returns = QCheckBox("반품 포함")
        self.returns.setChecked(True)
        filters.addWidget(self.status)
        filters.addWidget(self.partner_filter)
        filters.addWidget(self.partner_lookup)
        filters.addStretch()
        self.body.addLayout(filters)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.returns)
        self.body.addLayout(search_row)
        self.summary = QLabel()
        self.summary.setObjectName("summary")
        self.body.addWidget(self.summary)
        self.grid = self.table(["전표번호", "구분", "거래일", "거래처", "합계", "결제", "포인트", "미결제", "상태", "담당자", "메모"])
        controls = QHBoxLayout()
        for label, callback in (("상세 / 초안 수정", self.detail), ("수금 · 지급 / 환불", self.settle), ("원전표 반품", self.return_trade), ("확정 취소", self.cancel), ("초안 삭제", self.delete_draft)):
            controls.addWidget(action(label, callback))
        controls.addStretch()
        self.body.addLayout(controls)
        self.grid.itemDoubleClicked.connect(self.detail)
        self.search.returnPressed.connect(self.refresh)
        self.partner_filter.currentIndexChanged.connect(self.refresh)
        self.returns.toggled.connect(self.refresh)

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

    def refresh(self):
        try:
            rows = self.store.documents(start=_date(self.start), end=_date(self.end), partner_id=self.partner_filter.currentData(), status=self.status.currentData(), search=self.search.text())
            rows = [r for r in rows if r["kind"] == self.kind or self.returns.isChecked() and r["kind"] == self.kind + "_return"]
            self.grid.fill([[r["number"], KINDS[r["kind"]], r["date"], r.get("partner_name", ""), -r["total"] if r["kind"].endswith("_return") else r["total"], r.get("cash_paid", 0), r.get("points_used", 0), r.get("net_balance", -r.get("balance", 0) if r["kind"].endswith("_return") else r.get("balance", 0)), STATUSES[r["status"]], r.get("user_name", ""), r["memo"]] for r in rows], rows)
            active = [r for r in rows if r["status"] == "posted"]
            total = sum((-1 if r["kind"].endswith("_return") else 1) * r["total"] for r in active)
            gross = sum(r["total"] for r in active if not r["kind"].endswith("_return"))
            returned = sum(r["total"] for r in active if r["kind"].endswith("_return"))
            paid = sum((-1 if r["kind"].endswith("_return") else 1) * r["cash_paid"] for r in active)
            net_balance = sum(r.get("net_balance", -r.get("balance", 0) if r["kind"].endswith("_return") else r.get("balance", 0)) for r in active)
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
        picker = PartnerPicker(self.window, "supplier" if self.kind == "purchase" else "customer")
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        dialog = TradeDialog(self.window, self.kind)
        dialog.partner.setCurrentIndex(dialog.partner.findData(picker.selected_record["id"]))
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
        row = self.selected()
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
            expected = int(self.opening.text()) + data["expected_cash"]
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
