"""Manual-inspired business screens backed exclusively by the local SQLite service.

The application imports this module lazily after its shared page widgets exist.
No page in this module contacts a server or a payment provider.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import sqlite3

from PySide6.QtCore import QDate, QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTextEdit, QVBoxLayout,
)

from .app import DataTable, Page, button, label, money, quantity
from .dialogs import BusinessDialog, date_edit, line_edit, number_edit
from .export import export_workbook


ERRORS = (ValueError, PermissionError, sqlite3.Error)


def _day(field):
    return field.date().toString("yyyy-MM-dd")


def _dates(start, end):
    if start.date() > end.date():
        raise ValueError("조회 시작일이 종료일보다 늦습니다.")
    return _day(start), _day(end)


def _month_dates():
    today = QDate.currentDate()
    return date_edit(today.toString("yyyy-MM-01")), date_edit(today.toString("yyyy-MM-dd"))


def _compact_table(widget):
    widget.verticalHeader().setDefaultSectionSize(36)
    widget.horizontalHeader().setDefaultSectionSize(110)


def _export_rows(parent, headers, rows, title):
    if not rows:
        QMessageBox.information(parent, "엑셀 내보내기", "내보낼 조회 결과가 없습니다.")
        return
    filename, _ = QFileDialog.getSaveFileName(parent, "엑셀로 저장", f"서영POS_{title}.xlsx", "Excel 통합문서 (*.xlsx)")
    if filename:
        if not filename.lower().endswith(".xlsx"):
            filename += ".xlsx"
        try:
            export_workbook(filename, title, headers, rows)
        except (OSError, ValueError) as error:
            QMessageBox.warning(parent, "저장 실패", str(error))


def _export_table(parent, widget, title):
    _export_rows(parent, [widget.horizontalHeaderItem(c).text() for c in range(widget.columnCount())], widget.export_rows(), title)


class OfflinePage(Page):
    def __init__(self, window, title, subtitle, code):
        super().__init__(window, title, subtitle, code)
        self.body.setContentsMargins(18, 16, 18, 14)
        self.body.setSpacing(11)

    def table_frame(self, headers, title):
        result = super().table_frame(headers, title)
        _compact_table(result)
        return result

    def fail(self, error):
        QMessageBox.warning(self, "처리할 수 없습니다", str(error))


class LedgerPage(OfflinePage):
    def __init__(self, window):
        super().__init__(window, "거래처 원장", "매입·매출과 지급·수금 내역을 날짜순으로 대조합니다. 카드사 연동 없이 관리합니다.", "ledger")
        self.add_export()
        filters = self.filter_frame()
        self.kind = QComboBox()
        for title, kind, permission in (("공급사 · 매입원장", "supplier", "purchases"), ("판매처 · 매출원장", "customer", "sales")):
            if self.service.has_permission(permission) or self.service.has_permission("reports"):
                self.kind.addItem(title, kind)
        self.partner = QComboBox()
        self.partner.setMinimumWidth(200)
        self.start, self.end = _month_dates()
        filters.addWidget(self.kind)
        filters.addWidget(self.partner, 1)
        filters.addWidget(self.start)
        filters.addWidget(label("~"))
        filters.addWidget(self.end)
        filters.addWidget(button("조회", self.refresh, primary=True, glyph="search"))
        self.summary = label("거래처를 선택해 주세요.", "footerTotal")
        self.summary.setWordWrap(True)
        self.body.addWidget(self.summary)
        self.table_frame(["일자", "구분", "전표번호", "거래금액", "지급·수금", "잔액", "메모", "담당자"], "거래·결제 내역")
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(6, 230)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.partner.currentIndexChanged.connect(self.refresh)
        self._load_partners()

    def _load_partners(self):
        previous = self.partner.currentData()
        self.partner.blockSignals(True)
        self.partner.clear()
        if self.kind.currentData():
            for record in self.service.list_partners(self.kind.currentData()):
                self.partner.addItem(f"{record['name']}  ·  {record['code']}", record["id"])
        index = self.partner.findData(previous)
        if index >= 0:
            self.partner.setCurrentIndex(index)
        self.partner.blockSignals(False)

    def _kind_changed(self):
        self._load_partners()
        self.refresh()

    def refresh(self):
        try:
            start, end = _dates(self.start, self.end)
            self._load_partners()
            if self.partner.currentData() is None:
                self.table.populate([])
                self.summary.setText("등록된 거래처가 없습니다.")
                self.results(0)
                return
            report = self.service.partner_ledger(self.kind.currentData(), self.partner.currentData(), start, end)
            records = report["entries"]
            self.table.populate([[r["date"], "거래" if r["event_type"] == "document" else "지급" if self.kind.currentData() == "supplier" else "수금",
                                  r["document_number"], r["charge"], r["payment"], r["balance"], r["memo"], r["user_name"]] for r in records],
                                records, emphasized={5: "#BC694D"})
            self.summary.setText(f"기초잔액  {money(report['opening_balance'])}원     거래  {money(report['total_charge'])}원     지급·수금  {money(report['total_payment'])}원")
            self.results(len(records), f"기말잔액   {money(report['closing_balance'])} 원")
        except ERRORS as error:
            self.fail(error)


class AnalysisPage(OfflinePage):
    GROUPS = [("일별", "daily"), ("월별", "monthly"), ("상품별", "product"), ("분류별", "category"), ("공급사별", "supplier")]

    def __init__(self, window):
        super().__init__(window, "매입·매출 집계", "일별·월별·상품·분류·공급사 실적을 실제 전표에서 집계합니다. 취소 전표는 제외합니다.", "analysis")
        self.add_export()
        filters = self.filter_frame()
        self.group = QComboBox()
        for title, value in self.GROUPS:
            self.group.addItem(title, value)
        self.start, self.end = _month_dates()
        filters.addWidget(label("집계 기준"))
        filters.addWidget(self.group)
        filters.addWidget(self.start)
        filters.addWidget(label("~"))
        filters.addWidget(self.end)
        filters.addStretch()
        filters.addWidget(button("집계 조회", self.refresh, primary=True, glyph="search"))
        self.note = label("수량은 단위별로 분리합니다. 공급사별 매출·분류는 현재 상품장의 소속 기준입니다.", "mutedLabel")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        self.table_frame(["집계항목", "단위", "매입수량", "판매수량", "매입금액", "매출금액", "매출원가", "매출이익"], "실적 집계")
        self.table.setColumnWidth(0, 240)
        self.group.currentIndexChanged.connect(self.refresh)

    def refresh(self):
        try:
            report = self.service.grouped_report(*_dates(self.start, self.end), group_by=self.group.currentData())
            records = report["rows"]
            self.table.populate([[r["label"], r["unit"], Decimal(r["purchase_qty"]), Decimal(r["sale_qty"]),
                                  r["purchase_total"], r["sale_total"], r["cost_total"], r["gross_profit"]] for r in records],
                                records, emphasized={7: "#008C82"})
            totals = report["summary"]
            self.results(len(records), f"매입  {money(totals['purchase_total'])}원    매출  {money(totals['sale_total'])}원    이익  {money(totals['gross_profit'])}원")
        except ERRORS as error:
            self.fail(error)


class StocktakePage(OfflinePage):
    def __init__(self, window):
        super().__init__(window, "일괄 재고실사", "실제 수량을 입력한 상품만 한 번에 반영합니다. 조회 이후 변동된 재고는 저장을 차단합니다.", "stocktake")
        self.add_export()
        self.actions.addWidget(button("실사 저장", self.save, primary=True, glyph="plus"))
        filters = self.filter_frame()
        filters.addWidget(self.search_field("상품명 · 코드 · 바코드로 검색"), 1)
        filters.addWidget(button("새로 조회", self.refresh, glyph="refresh"))
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("실사 사유 필수 · 예: 월말 냉장창고 실사")
        filters.addWidget(self.reason, 1)
        self.table_frame(["상품코드", "상품명", "단위", "장부수량", "실제수량 입력", "차이"], "실사 수량 입력")
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(4, 170)
        self.table.setMinimumHeight(230)
        self.body.addWidget(label("실사 이력 · 더블클릭하면 저장 당시 수량을 확인할 수 있습니다.", "sectionTitle"))
        self.history = DataTable(["실사번호", "실사일", "사유", "품목수", "변경품목", "재고금액 증감", "담당자"])
        _compact_table(self.history)
        self.history.setMaximumHeight(190)
        self.history.setColumnWidth(0, 190)
        self.history.setColumnWidth(2, 260)
        self.history.cellDoubleClicked.connect(self.show_history)
        self.body.addWidget(self.history)
        self.count_fields = {}
        self.expected = {}
        self.difference_labels = {}

    def _update_difference(self, product_id):
        text = self.count_fields[product_id].text().strip()
        result = self.difference_labels[product_id]
        try:
            difference = Decimal(text) - Decimal(self.expected[product_id])
            result.setText(quantity(difference))
            result.setStyleSheet("color: #C2684F; font-weight: 700;" if difference < 0 else "color: #008C82; font-weight: 700;")
        except InvalidOperation:
            result.setText("미입력")

    def refresh(self, force=False):
        if not force and any(field.text().strip() for field in self.count_fields.values()):
            if QMessageBox.question(self, "입력 중인 실사", "새로 조회하면 아직 저장하지 않은 실사 수량이 지워집니다. 계속할까요?") != QMessageBox.StandardButton.Yes:
                return
        try:
            records = [record for record in self.service.list_products(self.search.text().strip()) if record["active"]]
            self.table.setSortingEnabled(False)
            self.table.populate([[r["code"], r["name"], r["unit"], Decimal(r["stock_qty"]), "", ""] for r in records], records)
            self.table.setSortingEnabled(False)
            self.count_fields, self.expected, self.difference_labels = {}, {}, {}
            for row in range(self.table.rowCount()):
                record = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                product_id = record["id"]
                field = number_edit("", decimal=True)
                field.setMinimumHeight(24)
                field.setPlaceholderText("미입력 · 변경 안 함")
                field.setObjectName(f"stocktakeCount_{product_id}")
                difference = label("미입력")
                difference.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.expected[product_id] = record["stock_qty"]
                self.count_fields[product_id] = field
                self.difference_labels[product_id] = difference
                self.table.setCellWidget(row, 4, field)
                self.table.setCellWidget(row, 5, difference)
                field.textChanged.connect(lambda _text, product_id=product_id: self._update_difference(product_id))
            # Column widgets move with their rows; write identity never comes from row position.
            self.table.setSortingEnabled(True)
            self.results(len(records), "미입력 상품은 저장하지 않습니다 · 수량 단위는 상품장 기준")
            history = self.service.list_stocktakes()
            self.history.populate([[r["number"], r["date"], r["reason"], r["items_count"], r["changed_count"], r["value_change"], r["user_name"]] for r in history], history)
        except ERRORS as error:
            self.fail(error)

    def add(self):
        self.save()

    def export(self):
        rows = []
        for row in range(self.table.rowCount()):
            record = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            counted = self.count_fields[record["id"]].text().strip()
            expected = Decimal(self.expected[record["id"]])
            try:
                actual = Decimal(counted) if counted else ""
                difference = actual - expected if counted else ""
            except InvalidOperation:
                self.fail(ValueError("실제 수량을 확인한 뒤 엑셀로 저장해 주세요."))
                return
            rows.append([record["code"], record["name"], record["unit"], expected, actual, difference])
        _export_rows(self, [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())], rows, "재고실사입력")

    def save(self):
        items = [{"product_id": product_id, "expected_qty": self.expected[product_id], "counted_qty": field.text().strip()}
                 for product_id, field in self.count_fields.items() if field.text().strip()]
        if not items:
            self.fail(ValueError("실제 수량을 입력한 상품이 없습니다."))
            return
        if not self.reason.text().strip():
            self.fail(ValueError("실사 사유를 입력해 주세요."))
            return
        if QMessageBox.question(self, "실사 저장 확인", f"입력한 {len(items):,}개 상품의 재고를 실제 수량으로 변경할까요?\n저장 후에는 실사 이력이 보존됩니다.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.save_stocktake(items, self.reason.text().strip())
            self.reason.clear()
            self.refresh(force=True)
            self.window.show_message(f"{len(items):,}개 상품 실사 저장 완료")
        except ERRORS as error:
            self.fail(error)

    def show_history(self, *_args):
        selected = self.history.selected()
        if not selected:
            return
        try:
            record = self.service.get_stocktake(selected["id"])
            dialog = BusinessDialog("재고실사 상세", f"{record['number']} · {record['reason']}", self)
            dialog.resize(930, 600)
            grid = DataTable(["상품코드", "상품명", "단위", "장부수량", "실제수량", "차이", "이전금액", "실사금액"])
            _compact_table(grid)
            grid.populate([[r["product_code"], r["product_name"], r["unit"], Decimal(r["expected_qty"]), Decimal(r["counted_qty"]),
                            Decimal(r["delta"]), r["previous_cost"], r["counted_cost"]] for r in record["items"]])
            dialog.layout.addWidget(grid, 1)
            dialog.layout.addWidget(button("엑셀 내보내기", lambda: _export_table(dialog, grid, "재고실사")))
            dialog.buttons(close_only=True)
            dialog.exec()
        except ERRORS as error:
            self.fail(error)


class MemberDialog(BusinessDialog):
    def __init__(self, service, record=None, parent=None):
        self.service, self.record = service, record or {}
        super().__init__("회원 정보 수정" if record else "회원 등록", "회원 정보와 포인트는 이 PC의 데이터베이스에만 보관됩니다.", parent)
        form = QFormLayout()
        self.fields = {}
        for key, title in (("code", "회원코드 *"), ("name", "회원명 *"), ("phone", "연락처")):
            self.fields[key] = line_edit(self.record.get(key, ""))
            form.addRow(title, self.fields[key])
        self.active = QCheckBox("사용 회원")
        self.active.setChecked(self.record.get("active", True))
        form.addRow("상태", self.active)
        self.memo = QTextEdit(self.record.get("memo", ""))
        self.memo.setMaximumHeight(100)
        form.addRow("메모", self.memo)
        self.layout.addLayout(form)
        self.buttons(callback=self.save)

    def save(self):
        try:
            data = {key: field.text().strip() for key, field in self.fields.items()}
            data.update(active=self.active.isChecked(), memo=self.memo.toPlainText().strip())
            self.saved_id = self.service.save_member(data, self.record.get("id"))
            self.accept()
        except ERRORS as error:
            self.error(error)


class PointsDialog(BusinessDialog):
    def __init__(self, service, member, parent=None):
        self.service, self.member = service, member
        super().__init__("회원 포인트 조정", f"{member['name']} · 현재 {money(service.member_points(member['id']))} P", parent)
        form = QFormLayout()
        self.points = line_edit("", "적립 100 / 차감 -100")
        self.points.setValidator(QRegularExpressionValidator(QRegularExpression(r"-?\d{0,12}"), self.points))
        self.date = date_edit()
        self.reason = line_edit("", "조정 사유 필수")
        form.addRow("적립·차감 포인트", self.points)
        form.addRow("일자", self.date)
        form.addRow("사유", self.reason)
        self.layout.addLayout(form)
        note = label("포인트 내역은 수정·삭제하지 않습니다. 정정은 반대 금액으로 새 내역을 등록하세요.", "mutedLabel")
        note.setWordWrap(True)
        self.layout.addWidget(note)
        self.buttons(callback=self.save)

    def save(self):
        try:
            self.service.adjust_member_points(self.member["id"], self.points.text().strip(), self.reason.text().strip(), date=_day(self.date))
            self.accept()
        except ERRORS as error:
            self.error(error)


class MembersPage(OfflinePage):
    def __init__(self, window):
        super().__init__(window, "회원·포인트 관리", "회원 등록과 포인트 적립·차감 이력을 오프라인으로 관리합니다. 자동 적립·카드 결제 기능은 없습니다.", "members")
        self.add_export()
        self.editable = self.service.has_permission("members")
        if self.editable:
            self.actions.addWidget(button("회원 등록", self.add, primary=True, glyph="plus"))
        filters = self.filter_frame()
        filters.addWidget(self.search_field("회원명 · 코드 · 연락처 검색"), 1)
        self.active_only = QCheckBox("사용 회원만")
        filters.addWidget(self.active_only)
        filters.addWidget(button("조회", self.refresh, glyph="search"))
        if self.editable:
            filters.addWidget(button("정보 수정", self.edit))
            filters.addWidget(button("포인트 조정", self.adjust_points))
            filters.addWidget(button("삭제", self.delete, danger=True))
        self.table_frame(["회원코드", "회원명", "연락처", "보유 포인트", "상태", "메모"], "회원 목록")
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(5, 260)
        self.table.setMinimumHeight(210)
        self.table.itemSelectionChanged.connect(self.refresh_history)
        if self.editable:
            self.table.cellDoubleClicked.connect(self.edit)
        history_head = QHBoxLayout()
        self.history_title = label("회원 포인트 이력 · 회원을 선택하세요.", "sectionTitle")
        history_head.addWidget(self.history_title)
        history_head.addStretch()
        history_head.addWidget(button("이력 엑셀", lambda: _export_table(self, self.history, "회원포인트이력")))
        self.body.addLayout(history_head)
        self.history = DataTable(["지정일자", "적립·차감", "등록순 잔액", "사유", "담당자"])
        self.history.setToolTip("잔액은 지정일자가 아니라 실제 등록 순서 기준입니다. 기존 기록을 고치지 않고 반대 방향의 조정 내역으로 정정합니다.")
        _compact_table(self.history)
        self.history.setMaximumHeight(190)
        self.history.setColumnWidth(3, 320)
        self.body.addWidget(self.history)

    def refresh(self):
        try:
            selected = self.table.selected()
            records = self.service.list_members(self.search.text().strip(), active_only=self.active_only.isChecked())
            self.table.blockSignals(True)
            self.table.populate([[r["code"], r["name"], r["phone"], r["points"], "사용" if r["active"] else "중지", r["memo"]] for r in records], records, emphasized={3: "#008C82"})
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            if selected:
                for row in range(self.table.rowCount()):
                    if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)["id"] == selected["id"]:
                        self.table.selectRow(row)
                        break
            self.table.blockSignals(False)
            self.results(len(records), f"보유 포인트 합계   {money(sum(r['points'] for r in records))} P")
            self.refresh_history()
        except ERRORS as error:
            self.table.blockSignals(False)
            self.fail(error)

    def refresh_history(self):
        selected = self.table.selected()
        if not selected:
            self.history.populate([])
            self.history_title.setText("회원 포인트 이력 · 회원을 선택하세요.")
            return
        try:
            records = self.service.member_point_history(selected["id"])
            self.history.populate([[r["date"], r["points"], r["balance"], r["reason"], r["username"]] for r in records], records)
            self.history_title.setText(f"{selected['name']} · 포인트 이력 {len(records):,}건")
        except ERRORS as error:
            self.fail(error)

    def add(self):
        if MemberDialog(self.service, parent=self).exec():
            self.refresh()

    def edit(self, *_args):
        selected = self.selected()
        if selected and MemberDialog(self.service, selected, self).exec():
            self.refresh()

    def adjust_points(self):
        selected = self.selected()
        if selected and PointsDialog(self.service, selected, self).exec():
            self.refresh()

    def delete(self):
        selected = self.selected()
        if selected and QMessageBox.question(self, "회원 삭제 확인", f"'{selected['name']}' 회원을 삭제할까요?\n포인트 이력이 있는 회원은 삭제할 수 없습니다.") == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.service.delete_member(selected["id"]))


class PromotionDialog(BusinessDialog):
    def __init__(self, service, record=None, parent=None):
        self.service, self.record = service, record or {}
        super().__init__("특매 정보 수정" if record else "특매 등록", "상품별 적용 기간과 매입·판매 특가를 지정합니다. 같은 상품의 사용 기간은 겹칠 수 없습니다.", parent)
        self.resize(580, 550)
        form = QFormLayout()
        self.product = QComboBox()
        for product in service.list_promotion_products():
            self.product.addItem(f"{product['name']}  ·  {product['code']}  / {product['unit']}", product["id"])
        if record:
            self.product.setCurrentIndex(self.product.findData(record["product_id"]))
        self.title = line_edit(self.record.get("title", ""), "예: 주말 한돈 특가")
        self.start = date_edit(self.record.get("date_from", ""))
        self.end = date_edit(self.record.get("date_to", ""))
        self.purchase_price = number_edit(self.record.get("purchase_price") if self.record.get("purchase_price") is not None else "")
        self.sale_price = number_edit(self.record.get("sale_price") if self.record.get("sale_price") is not None else "")
        self.purchase_price.setPlaceholderText("비우면 일반 매입가 적용")
        self.sale_price.setPlaceholderText("비우면 일반 판매가 적용")
        self.active = QCheckBox("특매 사용")
        self.active.setChecked(self.record.get("active", True))
        for title, field in (("상품 *", self.product), ("특매명 *", self.title), ("시작일", self.start), ("종료일", self.end),
                             ("매입 특가 · 원", self.purchase_price), ("판매 특가 · 원", self.sale_price), ("상태", self.active)):
            form.addRow(title, field)
        self.layout.addLayout(form)
        self.buttons(callback=self.save)

    def save(self):
        try:
            start, end = _dates(self.start, self.end)
            data = {"product_id": self.product.currentData(), "title": self.title.text().strip(), "date_from": start, "date_to": end,
                    "purchase_price": self.purchase_price.text().strip() or None,
                    "sale_price": self.sale_price.text().strip() or None, "active": self.active.isChecked()}
            self.saved_id = self.service.save_promotion(data, self.record.get("id"))
            self.accept()
        except ERRORS as error:
            self.error(error)


class PromotionsPage(OfflinePage):
    def __init__(self, window):
        super().__init__(window, "특매 관리", "기간별 상품 특가를 등록합니다. 전표 입력 시 날짜에 맞는 특가를 적용하고 저장 전 단가를 확인하세요.", "promotions")
        self.add_export()
        self.editable = self.service.has_permission("promotions")
        if self.editable:
            self.actions.addWidget(button("특매 등록", self.add, primary=True, glyph="plus"))
        filters = self.filter_frame()
        filters.addWidget(self.search_field("상품명 · 상품코드 · 특매명 검색"), 1)
        self.active_only = QCheckBox("사용 특매만")
        self.on_date = QCheckBox("기준일 적용 중")
        self.date = date_edit()
        self.date.setEnabled(False)
        self.on_date.toggled.connect(self.date.setEnabled)
        filters.addWidget(self.active_only)
        filters.addWidget(self.on_date)
        filters.addWidget(self.date)
        filters.addWidget(button("조회", self.refresh, glyph="search"))
        if self.editable:
            filters.addWidget(button("수정", self.edit))
            filters.addWidget(button("삭제", self.delete, danger=True))
        self.table_frame(["특매명", "상품코드", "상품명", "단위", "시작일", "종료일", "매입 특가", "판매 특가", "상태"], "특매 목록")
        self.table.setColumnWidth(0, 210)
        self.table.setColumnWidth(2, 240)
        if self.editable:
            self.table.cellDoubleClicked.connect(self.edit)

    def refresh(self):
        try:
            records = self.service.list_promotions(self.search.text().strip(), active_only=self.active_only.isChecked() or self.on_date.isChecked(), on_date=_day(self.date) if self.on_date.isChecked() else None)
            self.table.populate([[r["title"], r["product_code"], r["product_name"], r["unit"], r["date_from"], r["date_to"],
                                  r["purchase_price"] if r["purchase_price"] is not None else "일반가", r["sale_price"] if r["sale_price"] is not None else "일반가",
                                  "사용" if r["active"] else "중지"] for r in records], records, emphasized={7: "#008C82"})
            self.results(len(records), "동일 상품의 사용 기간 중복 방지 · 가격 단위: 원 / 상품 단위")
        except ERRORS as error:
            self.fail(error)

    def add(self):
        if PromotionDialog(self.service, parent=self).exec():
            self.refresh()

    def edit(self, *_args):
        selected = self.selected()
        if selected and PromotionDialog(self.service, selected, self).exec():
            self.refresh()

    def delete(self):
        selected = self.selected()
        if selected and QMessageBox.question(self, "특매 삭제 확인", f"'{selected['title']}' 특매를 삭제할까요?\n이미 저장한 전표의 단가는 변경되지 않습니다.") == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.service.delete_promotion(selected["id"]))
