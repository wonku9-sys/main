"""Member books, promotion groups and gifts for the independent desktop UI."""
from __future__ import annotations

from datetime import date
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTabWidget, QTableWidget, QVBoxLayout, QWidget, QFormLayout,
)

from .widgets import DataGrid, FormDialog, Page, ScanField, action, date_field, won,authorize_output
from .trade_sheet import EntrySheet


def choose(grid, parent):
    selected = grid.selected()
    if not selected:
        QMessageBox.information(parent, "선택", "먼저 목록에서 처리할 자료를 선택하세요.")
    return selected


def confirm(parent, text):
    return QMessageBox.question(parent, "처리 확인", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


def change(dialog, callback):
    try:
        result = callback()
        dialog.saved_id = result
        dialog.accept()
    except (ValueError, PermissionError, OSError) as exc:
        dialog.error(exc)


from .customer_ui import MemberDialog


class MembersPage(Page):
    def __init__(self, window):
        super().__init__(window, "회원조회/등록", "최근 등록순 상위 건수 · 회원 조건 조회 · 외상 수금 · F4 검색어 / F5 조회. 카드·문자·센터 연동은 하지 않습니다.")
        from .customer_query_ui import CustomerQuery,MemberGrid,HEADERS
        self.customer_query=CustomerQuery(self);self.search=self.customer_query.search;self.status=self.customer_query.status
        self.body.addWidget(self.customer_query)
        filters = QHBoxLayout()
        filters.addWidget(action("수정", self.edit))
        filters.addWidget(action("외상 수금", self.collect_credit))
        filters.addWidget(action("포인트 조정", self.adjust))
        filters.addWidget(action("구매 순위", self.ranking))
        filters.addWidget(action("삭제", self.delete, danger=True))
        self.body.addLayout(filters)
        self.grid = self.table(HEADERS,grid_type=MemberGrid)
        self.grid.setSortingEnabled(False)
        self.body.addWidget(self.customer_query.pager)
        self.grid.setColumnWidth(1, 160)
        self.grid.setMinimumHeight(210)
        self.grid.itemSelectionChanged.connect(self.details)
        self.grid.cellDoubleClicked.connect(lambda *_: self.edit())
        self.tabs = QTabWidget()
        self.points = DataGrid(["일자", "구분", "증감", "등록순 잔액", "연결 전표", "사유", "담당자"])
        self.history = DataGrid(["일자", "전표번호", "구분", "상태", "거래액", "지급·수금", "사용 포인트", "적립 포인트"])
        self.prices = DataGrid(["상품", "회원 지정 판매가"])
        for title, grid in (("포인트 이력", self.points), ("구매·반품 내역", self.history), ("회원 지정가", self.prices)):
            panel = QWidget()
            layout = QVBoxLayout(panel)
            tools = QHBoxLayout()
            if grid is self.prices:
                tools.addWidget(action("지정가 등록·수정", self.member_price))
                tools.addWidget(action("지정가 삭제", self.delete_price, danger=True))
            tools.addStretch()
            layout.addLayout(tools)
            layout.addWidget(grid)
            self.tabs.addTab(panel, title)
        self.tabs.setMinimumHeight(240)
        self.body.addWidget(self.tabs)
        self.output_target=QComboBox()
        for title in ('회원 목록','포인트 이력','구매·반품 내역','회원 지정가'):self.output_target.addItem(title)
        self.output_target.setToolTip('우측 인쇄·엑셀 아이콘으로 출력할 자료를 선택합니다.')
        filters.addWidget(QLabel('출력 대상'));filters.addWidget(self.output_target)

    def refresh(self, *_):
        if not hasattr(self,'grid') or not hasattr(self,'tabs'):return
        try:self.customer_query.refresh()
        except (ValueError,PermissionError,OSError) as exc:
            for grid in (self.grid,self.points,self.history,self.prices):grid.fill([])
            self.grid.all_export_rows=[];self.fail(exc)

    def export(self):
        if not authorize_output(self):return
        index=self.output_target.currentIndex()
        (self.grid,self.points,self.history,self.prices)[index].export(self,self.output_target.currentText())

    def print(self):
        if not authorize_output(self):return
        index=self.output_target.currentIndex()
        (self.grid,self.points,self.history,self.prices)[index].print_pages(self,self.output_target.currentText())

    def collect_credit(self):
        member=choose(self.grid,self)
        if not member:return
        from .customer_query_ui import MemberPaymentDialog
        try:
            if MemberPaymentDialog(self.store,member,self).exec():self.refresh()
        except (ValueError,PermissionError,OSError) as exc:self.fail(exc)

    def details(self):
        member = self.grid.selected()
        if not member:
            for grid in (self.points, self.history, self.prices):
                grid.fill([])
            return
        points = self.store.point_history(member["id"])
        self.points.fill([[r["date"], r["kind"], r["delta"], r["balance"], r.get("document_number") or "", r["reason"], r.get("user_name", "")] for r in points], points)
        records = self.store.member_history(member["id"])
        self.history.fill([[r["date"], r["number"], "매출" if r["kind"] == "sale" else "반품", r["status"], r["total"], r["cash_paid"], r["points_used"], r["points_earned"]] for r in records], records)
        prices = self.store.member_prices(member["id"])
        self.prices.fill([[r["product_name"], r["price"]] for r in prices], prices)

    def add(self):
        if MemberDialog(self.store, parent=self).exec():
            self.refresh()

    def edit(self):
        row = choose(self.grid, self)
        if row and MemberDialog(self.store, row, self).exec():
            self.refresh()

    def delete(self):
        row = choose(self.grid, self)
        if row and confirm(self, f"'{row['name']}' 회원을 삭제할까요? 이력이 있으면 삭제가 제한됩니다."):
            try:
                self.store.delete_member(row["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)

    def adjust(self):
        member = choose(self.grid, self)
        if not member:
            return
        dialog = FormDialog(f"{member['name']} · 포인트 조정", self)
        delta = dialog.field("delta", "증감 포인트 (+적립 / -차감)")
        reason = dialog.field("reason", "사유 *")
        dialog.finish(lambda: change(dialog, lambda: self.store.adjust_points(member["id"], delta.text(), reason.text())))
        if dialog.exec():
            self.refresh()

    def member_price(self):
        member = choose(self.grid, self)
        if not member:
            return
        dialog = FormDialog("회원 지정 판매가", self)
        product = dialog.combo("product", "상품", [(f"{r['name']} / {r['base_unit']}", r["id"]) for r in self.store.loyalty_products()])
        price = dialog.field("price", "기본단위당 지정가 (원)")
        dialog.finish(lambda: change(dialog, lambda: self.store.save_member_price({"member_id": member["id"], "product_id": product.currentData(), "price": price.text()})))
        if dialog.exec():
            self.details()

    def delete_price(self):
        row = choose(self.prices, self)
        if row and confirm(self, "선택한 회원 지정가를 해제할까요?"):
            try:
                self.store.delete_member_price(row["id"])
                self.details()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)

    def ranking(self):
        dialog = FormDialog("회원 구매 순위", self)
        dialog.resize(950, 650)
        start, end = date_field(date.today().replace(day=1).isoformat()), date_field()
        dialog.form.addRow("시작", start)
        dialog.form.addRow("종료", end)
        grid = DataGrid(["회원 코드", "회원명", "거래 횟수", "순구매액", "현재 포인트", "첫 구매", "최근 구매"])
        def refresh():
            try:
                rows = self.store.best_members(start.date().toString("yyyy-MM-dd"), end.date().toString("yyyy-MM-dd"))
                grid.fill([[r["code"], r["name"], r["sale_count"], r["total"], r["points"], r["first_purchase"], r["last_purchase"]] for r in rows], rows)
            except (ValueError, PermissionError) as exc:
                dialog.error(exc)
        dialog.body.addWidget(action("조회", refresh))
        dialog.body.addWidget(grid, 1)
        tools = QHBoxLayout()
        tools.addWidget(action("엑셀 저장", lambda: grid.export(dialog, "회원 구매 순위")))
        tools.addWidget(action("인쇄", lambda: grid.print_pages(dialog, "회원 구매 순위")))
        tools.addWidget(action("닫기", dialog.reject))
        dialog.body.addLayout(tools)
        refresh()
        dialog.exec()

    def focus_scan(self):
        self.search.setFocus()
        self.search.selectAll()


class PromotionDialog(FormDialog):
    def __init__(self, store, record=None, parent=None):
        super().__init__("특매 그룹", parent)
        self.resize(920, 690)
        self.store, self.record = store, record or {}
        self.field("title", "행사명 *", self.record.get("title", ""))
        self.start, self.end = date_field(self.record.get("start")), date_field(self.record.get("end"))
        self.form.addRow("시작일", self.start)
        self.form.addRow("종료일", self.end)
        self.active = QCheckBox("행사 사용")
        self.active.setChecked(self.record.get("active", True))
        self.form.addRow("상태", self.active)
        self.products = store.loyalty_products()
        self.lines = EntrySheet(0, 4)
        self.lines.setHorizontalHeaderLabels(["상품", "특매 매입가 (빈칸=기본)", "특매 판매가 (빈칸=기본)", ""])
        self.lines.horizontalHeader().setStretchLastSection(False)
        self.lines.setColumnWidth(0, 300)
        self.lines.setColumnWidth(1, 200)
        self.lines.setColumnWidth(2, 200)
        self.body.addWidget(self.lines, 1)
        self.body.addWidget(action("상품 추가", self.add_line))
        self.body.addWidget(action('상품 검색 · 체크해서 일괄 추가',self.pick_products))
        for row in self.record.get("items", []):
            self.add_line(row)
        if not self.lines.rowCount():
            self.add_line()
        self.finish(self.save)

    def add_line(self, record=None):
        record = record if isinstance(record, dict) else {}
        row = self.lines.rowCount()
        self.lines.insertRow(row)
        product = QComboBox()
        for item in self.products:
            product.addItem(item["name"], item["id"])
        if record:
            product.setCurrentIndex(product.findData(record.get("product_id")))
        purchase = QLineEdit("" if record.get("purchase_price") is None else str(record["purchase_price"]))
        sale = QLineEdit("" if record.get("sale_price") is None else str(record["sale_price"]))
        remove = action("삭제", lambda: self.remove_line(product))
        for column, widget in enumerate((product, purchase, sale, remove)):
            self.lines.setCellWidget(row, column, widget)

    def remove_line(self, product):
        for row in range(self.lines.rowCount()):
            if self.lines.cellWidget(row, 0) is product:
                self.lines.removeRow(row)
                return

    def pick_products(self):
        from .workflow_ui import ProductPicker
        picker=ProductPicker(self,product_loader=self.store.loyalty_products,read_permissions=('loyalty',))
        picker.set_apply_callback(self.apply_picked_products);picker.exec()

    def apply_picked_products(self,selections):
        existing={self.lines.cellWidget(row,0).currentData() for row in range(self.lines.rowCount())}
        self.products=self.store.loyalty_products()
        for product,_unit_id in selections:
            if product['id'] not in existing:
                self.add_line({'product_id':product['id']});existing.add(product['id'])

    def save(self):
        items = [{"product_id": self.lines.cellWidget(r, 0).currentData(), "purchase_price": self.lines.cellWidget(r, 1).text().strip() or None, "sale_price": self.lines.cellWidget(r, 2).text().strip() or None} for r in range(self.lines.rowCount())]
        data = {"title": self.fields["title"].text(), "start": self.start.date().toString("yyyy-MM-dd"), "end": self.end.date().toString("yyyy-MM-dd"), "active": self.active.isChecked(), "items": items}
        change(self, lambda: self.store.save_promotion(data, self.record.get("id")))


class PromotionsPage(Page):
    def __init__(self, window):
        super().__init__(window, "특매 그룹", "행사 기간과 여러 상품의 매입·판매 특가를 함께 관리합니다. 기본 상품가는 변경하지 않습니다.")
        for title, callback in (("새 특매", self.add), ("수정", self.edit), ("기간 연장", self.extend), ("다음 행사로 복제", self.clone), ("사용 중지", self.delete)):
            self.actions.addWidget(action(title, callback, primary=title == "새 특매"))
        self.grid = self.table(["행사명", "시작일", "종료일", "상품수", "상태"])
        self.grid.itemSelectionChanged.connect(self.details)
        self.grid.cellDoubleClicked.connect(lambda *_: self.edit())
        self.detail = DataGrid(["상품코드", "상품명", "행사 매입가", "행사 판매가"])
        self.detail.setMaximumHeight(220)
        self.body.addWidget(self.detail)

    def refresh(self):
        rows = self.store.promotions()
        self.grid.fill([[r["title"], r["start"], r["end"], r["item_count"], "사용" if r["active"] else "중지"] for r in rows], rows)
        if rows:
            self.grid.selectRow(0)
        self.details()

    def details(self):
        row = self.grid.selected()
        items = self.store.promotion(row["id"])["items"] if row else []
        self.detail.fill([[r["product_code"], r["product_name"], r["purchase_price"], r["sale_price"]] for r in items], items)

    def add(self):
        if PromotionDialog(self.store, parent=self).exec():
            self.refresh()

    def edit(self):
        row = choose(self.grid, self)
        if row and PromotionDialog(self.store, self.store.promotion(row["id"]), self).exec():
            self.refresh()

    def extend(self):
        row = choose(self.grid, self)
        if row:
            dialog = FormDialog("특매 기간 연장", self)
            end = date_field(row["end"])
            dialog.form.addRow("새 종료일", end)
            dialog.finish(lambda: change(dialog, lambda: self.store.extend_promotion(row["id"], end.date().toString("yyyy-MM-dd"))))
            if dialog.exec():
                self.refresh()

    def clone(self):
        row = choose(self.grid, self)
        if row:
            dialog = FormDialog("새 행사로 복제", self)
            start, end = date_field(), date_field()
            dialog.form.addRow("새 시작일", start)
            dialog.form.addRow("새 종료일", end)
            dialog.finish(lambda: change(dialog, lambda: self.store.clone_promotion(row["id"], start.date().toString("yyyy-MM-dd"), end.date().toString("yyyy-MM-dd"))))
            if dialog.exec():
                self.refresh()

    def delete(self):
        row = choose(self.grid, self)
        if row and confirm(self, "행사 사용을 중지할까요? 등록 이력은 보존합니다."):
            try:
                self.store.delete_promotion(row["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)


class PricesPage(Page):
    def __init__(self, window):
        super().__init__(window, "가격 변경 예약", "지정한 날짜부터 적용되는 제시 가격입니다. 확정된 과거 거래나 상품 기본가는 소급 변경하지 않습니다.")
        self.actions.addWidget(action("가격 예약", self.add, primary=True))
        self.actions.addWidget(action("선택 예약 수정", self.edit))
        self.actions.addWidget(action("예약 중지", self.delete, danger=True))
        self.grid = self.table(["적용일", "제목", "상품명", "매입 단가", "판매 단가", "상태"])

    def refresh(self):
        rows = self.store.price_schedules()
        self.grid.fill([[r["date"], r["title"], r["product_name"], r["purchase_price"], r["sale_price"], "사용" if r["active"] else "중지"] for r in rows], rows)

    def editor(self, record=None):
        record = record or {}
        dialog = FormDialog("가격 변경 예약", self)
        product = dialog.combo("product", "상품", [(r["name"], r["id"]) for r in self.store.loyalty_products()], record.get("product_id"))
        title = dialog.field("title", "제목", record.get("title", ""))
        apply_date = date_field(record.get("date"))
        dialog.form.addRow("적용일", apply_date)
        purchase = dialog.field("purchase", "매입가 (빈칸=유지)", record.get("purchase_price"))
        sale = dialog.field("sale", "판매가 (빈칸=유지)", record.get("sale_price"))
        active = QCheckBox("예약 사용")
        active.setChecked(record.get("active", True))
        dialog.form.addRow("상태", active)
        dialog.finish(lambda: change(dialog, lambda: self.store.save_price_schedule({"product_id": product.currentData(), "title": title.text(), "date": apply_date.date().toString("yyyy-MM-dd"), "purchase_price": purchase.text().strip() or None, "sale_price": sale.text().strip() or None, "active": active.isChecked()}, record.get("id"))))
        if dialog.exec():
            self.refresh()

    def add(self):
        self.editor()

    def edit(self):
        row = choose(self.grid, self)
        if row:
            self.editor(row)

    def delete(self):
        row = choose(self.grid, self)
        if row and confirm(self, "선택한 가격 예약을 중지할까요?"):
            try:
                self.store.delete_price_schedule(row["id"])
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)


class GiftsPage(Page):
    def __init__(self, window):
        super().__init__(window, "사은품 · 포인트 교환", "사은품 지급 시 회원 포인트와 사은품 재고를 동시에 반영하고, 원 지급 내역으로 반품합니다.")
        for title, callback in (("사은품 등록", self.add), ("수정", self.edit), ("지급", self.redeem), ("지급 내역 반품", self.return_gift)):
            self.actions.addWidget(action(title, callback, primary=title == "지급"))
        self.grid = self.table(["코드", "사은품명", "필요 포인트", "재고수량", "상태"])
        self.history = DataGrid(["일자", "회원", "사은품", "구분", "수량", "포인트", "사유", "담당자"])
        self.history.setMaximumHeight(230)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("사은품 지급·반품 이력"), 1)
        tools.addWidget(action("이력 엑셀", lambda: self.history.export(self, "사은품 이력")))
        tools.addWidget(action("이력 인쇄", lambda: self.history.print_pages(self, "사은품 이력")))
        self.body.addLayout(tools)
        self.body.addWidget(self.history)

    def refresh(self):
        rows = self.store.gifts()
        self.grid.fill([[r["code"], r["name"], r["points"], r["stock"], "사용" if r["active"] else "중지"] for r in rows], rows)
        history = self.store.gift_history()
        self.history.fill([[r.get("date", r.get("created_at", "")), r["member_name"], r["gift_name"], r["kind"], r["qty"], r["points"], r["reason"], r["user_name"]] for r in history], history)

    def editor(self, record=None):
        record = record or {}
        dialog = FormDialog("사은품 정보", self)
        for key, title, default in (("code", "코드 *", ""), ("name", "사은품명 *", ""), ("points", "필요 포인트 *", 1000), ("stock", "현재 사은품 수량", 0)):
            dialog.field(key, title, record.get(key, default))
        active = QCheckBox("사용")
        active.setChecked(record.get("active", True))
        dialog.form.addRow("상태", active)
        def save():
            data = {key: field.text() for key, field in dialog.fields.items()}
            data["active"] = active.isChecked()
            return self.store.save_gift(data, record.get("id"))
        dialog.finish(lambda: change(dialog, save))
        if dialog.exec():
            self.refresh()

    def add(self):
        self.editor()

    def edit(self):
        row = choose(self.grid, self)
        if row:
            self.editor(row)

    def redeem(self):
        gift = choose(self.grid, self)
        if not gift:
            return
        dialog = FormDialog("사은품 지급", self)
        member = dialog.combo("member", "회원", [(f"{r['name']} · {won(r['points'])}P", r["id"]) for r in self.store.members() if r["active"]])
        quantity = dialog.field("qty", "지급 수량", 1)
        reason = dialog.field("reason", "지급 사유 *", "포인트 사은품 교환")
        dialog.finish(lambda: change(dialog, lambda: self.store.redeem_gift(member.currentData(), gift["id"], quantity.text(), reason.text())))
        if dialog.exec():
            self.refresh()

    def return_gift(self):
        record = choose(self.history, self)
        if not record:
            return
        dialog = FormDialog("원 지급 기준 사은품 반품", self)
        quantity = dialog.field("qty", "반품 수량", 1)
        reason = dialog.field("reason", "반품 사유 *")
        dialog.finish(lambda: change(dialog, lambda: self.store.return_gift(record["id"], quantity.text(), reason.text())))
        if dialog.exec():
            self.refresh()
