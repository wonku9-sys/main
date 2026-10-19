"""Supplier debt, monthly transaction drill-down and payment history."""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from .common import money
from .widgets import DataGrid, Page, action, date_field, search_icon, won
from .workflow_ui import KINDS, PartnerPicker, TradeDialog, _confirm, _date, _warn


class SupplierPaymentDialog(QDialog):
    read_permissions = ("trade",)

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()

    def __init__(self, window, partner_id):
        super().__init__(window)
        self.store, self.partner_id, self.saved_id, self.snapshot = window.store, partner_id, None, None
        self.setWindowTitle("공급사 결제 처리")
        self.resize(850, 620)
        body = QVBoxLayout(self)
        self.balance = QLabel()
        self.balance.setObjectName("pageTitle")
        self.balance.setWordWrap(True)
        body.addWidget(self.balance)
        body.addWidget(QLabel("실제 지급한 내역만 기록하세요. 은행 송금 기능은 아닙니다. 초기 외상 → 오래된 매입전표 순으로 배분합니다."))
        form = QFormLayout()
        self.date = date_field()
        self.amount = QLineEdit()
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.method = QComboBox()
        self.method.addItem("현금", "cash")
        self.method.addItem("계좌이체", "transfer")
        self.memo = QLineEdit()
        for name, field in (("실제 결제일", self.date), ("결제금액 (원)", self.amount), ("결제방법", self.method), ("결제 메모", self.memo)):
            form.addRow(name, field)
        body.addLayout(form)
        self.grid = DataGrid(["배분 대상", "거래일", "미지급잔액", "이번 결제 배분액"])
        body.addWidget(self.grid, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        body.addWidget(self.error)
        controls = QHBoxLayout()
        controls.addWidget(action("잔액 다시 조회", self.refresh))
        controls.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("결제 등록")
        self.save_button.setAutoDefault(False)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        controls.addWidget(buttons)
        body.addLayout(controls)
        self.date.dateChanged.connect(self.refresh)
        self.amount.textChanged.connect(self.refresh_allocations)
        self.refresh()

    def refresh(self, *_):
        try:
            previous = self.snapshot
            self.snapshot = self.store.supplier_outstanding(self.partner_id, _date(self.date))
            data = self.snapshot
            party = data["partner"]
            self.balance.setText(f"{party['code']} · {party['name']}\n현재 미지급 {won(data['balance'])}원 · 선택일 결제 가능 {won(data['cap'])}원")
            if not self.amount.text() or previous and self.amount.text().replace(",", "") == str(previous["cap"]):
                self.amount.setText(str(data["cap"]))
            self.error.setText("정정은 당일 취소 후 재등록합니다. 취소 이력은 보존합니다.")
            self.save_button.setEnabled(data["cap"] > 0)
            self.refresh_allocations()
        except (ValueError, PermissionError) as exc:
            self.error.setText(str(exc))
            self.save_button.setEnabled(False)

    def refresh_allocations(self, *_):
        if not self.snapshot:
            return
        try:
            remaining = money(self.amount.text() or "0")
        except ValueError:
            remaining = 0
        rows = []
        if self.snapshot["opening"]:
            allocated = min(remaining, self.snapshot["opening"])
            rows.append(["초기 외상", self.snapshot["partner"]["opening_date"], self.snapshot["opening"], allocated])
            remaining -= allocated
        for doc in self.snapshot["documents"]:
            allocated = min(remaining, doc["balance"])
            rows.append([doc["number"], doc["date"], doc["balance"], allocated])
            remaining -= allocated
        self.grid.fill(rows)

    def save(self):
        if self.saved_id or not self.snapshot:
            return
        try:
            value = money(self.amount.text(), positive=True)
            if value > self.snapshot["cap"]:
                raise ValueError("결제 가능 잔액을 초과합니다.")
            if not _confirm(self, "결제 등록", f"{self.snapshot['partner']['name']}에 {won(value)}원을 {self.method.currentText()}로 지급한 내역을 기록할까요?\n실제 송금이나 카드 승인은 하지 않습니다."):
                return
            self.saved_id = self.store.settle_supplier(self.partner_id, value, _date(self.date), self.method.currentData(), self.memo.text(), self.snapshot["state"])
            self.save_button.setEnabled(False)
            from .navigation import mark_saved
            mark_saved(self)
            self.accept()
        except (ValueError, PermissionError) as exc:
            self.error.setText(str(exc))


class SupplierPaymentsPage(Page):
    def __init__(self, window):
        super().__init__(window, "결제관리", "공급사 외상 현황 → 거래내역 → 결제내역. 실제 지급을 기록하며 카드·은행 연동은 하지 않습니다.")
        self.actions.addWidget(action("결제 처리", self.pay, True))
        filters = QHBoxLayout()
        filters.addWidget(QLabel("기간"))
        self.start, self.end = date_field(date.today().replace(day=1)), date_field()
        filters.addWidget(self.start)
        filters.addWidget(QLabel("~"))
        filters.addWidget(self.end)
        self.partner = QComboBox()
        self.partner.addItem("전체 공급사", None)
        for party in self.store.partners("supplier"):
            self.partner.addItem(f"{party['code']} · {party['name']}", party["id"])
        filters.addWidget(self.partner, 1)
        lookup = action("공급사 검색", self.pick_partner)
        lookup.setIcon(search_icon())
        filters.addWidget(lookup)
        filters.addWidget(action("조회", self.refresh))
        self.body.addLayout(filters)
        options = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("공급사명 · 코드 검색")
        self.only_purchases = QCheckBox("기간 내 매입 있는 공급사만")
        self.include_voided = QCheckBox("취소 결제 포함")
        self.include_voided.setChecked(True)
        options.addWidget(self.search, 1)
        options.addWidget(self.only_purchases)
        options.addWidget(self.include_voided)
        self.body.addLayout(options)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("summary")
        self.body.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.grid = self.table(["공급사코드", "공급사명", "기간 전 이월", "기간 매입", "기간 반품", "순지급 (환급 차감)", "기간말 잔액", "현재 잔액", "매입 건수"])
        self.body.removeWidget(self.grid)
        self.ledger_grid = DataGrid(["일자", "구분", "전표번호", "거래액", "지급·환급", "누적잔액", "메모"])
        self.history_grid = DataGrid(["결제일", "결제번호", "공급사코드", "공급사명", "구분", "결제금액", "방법", "담당자", "상태", "메모"])
        for name, grid in (("외상매입내역조회", self.grid), ("월별거래내역조회", self.ledger_grid), ("결제내역조회", self.history_grid)):
            self.tabs.addTab(grid, name)
        self.body.addWidget(self.tabs, 1)
        controls = QHBoxLayout()
        controls.addWidget(action("선택 공급사 거래내역", self.drill_down))
        controls.addWidget(action("선택 내역 상세", self.detail))
        controls.addWidget(action("선택 결제 취소", self.void))
        controls.addStretch()
        self.body.addLayout(controls)
        self.grid.itemDoubleClicked.connect(self.drill_down)
        self.ledger_grid.itemDoubleClicked.connect(self.detail)
        self.history_grid.itemDoubleClicked.connect(self.detail)
        self.partner.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self.only_purchases.toggled.connect(self.refresh)
        self.include_voided.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        try:
            first, last, party = _date(self.start), _date(self.end), self.partner.currentData()
            rows = self.store.supplier_summary(first, last, self.search.text().strip(), self.only_purchases.isChecked(), party)
            self.grid.fill([[r["code"], r["name"], r["opening"], r["purchase"], r["returns"], r["payment"], r["closing"], r["balance"], r["count"]] for r in rows], rows)
            self.summary.setText(f"공급사 {len(rows):,}개 · 기간 매입 {won(sum(r['purchase'] for r in rows))}원 · 기간말 잔액 {won(sum(r['closing'] for r in rows))}원 · 현재 잔액 {won(sum(r['balance'] for r in rows))}원\n음수 잔액은 환급·상계 대상입니다. 공급사를 더블클릭하면 상세 거래내역을 봅니다.")
            ledger = self.store.ledger(party, first, last)["entries"] if party else []
            self.ledger_grid.fill([[r["date"], KINDS.get(r["kind"], {"opening": "초기 외상", "payment": "지급", "refund": "환급"}.get(r["kind"], r["kind"])), r["number"], r["charge"], r["payment"], r["balance"], r["memo"]] for r in ledger], ledger)
            history = self.store.supplier_payment_history(first, last, party, self.include_voided.isChecked())
            term = self.search.text().strip().casefold()
            history = [r for r in history if term in (r["partner_code"] + " " + r["partner_name"]).casefold()]
            self.history_grid.fill([[r["date"], r["number"], r["partner_code"], r["partner_name"], "환급" if r["amount"] < 0 else "묶음 지급" if r["type"] == "settlement" else "전표 지급", r["amount"], "현금" if r["method"] == "cash" else "계좌이체", r["user_name"], "취소" if r["voided"] else "유효", r["memo"]] for r in history], history)
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def pick_partner(self):
        picker = PartnerPicker(self.window, "supplier", for_filter=True)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.partner.setCurrentIndex(max(0, self.partner.findData(picker.selected_record["id"])))

    def drill_down(self, *_):
        row = self.grid.selected()
        if row:
            self.partner.setCurrentIndex(self.partner.findData(row["id"]))
            self.tabs.setCurrentIndex(1)

    def pay(self):
        party = self.partner.currentData() or (self.grid.selected() or {}).get("id")
        if not party:
            self.notify("결제할 공급사를 선택하세요.")
            return
        if SupplierPaymentDialog(self.window, party).exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.tabs.setCurrentIndex(2)

    def detail(self, *_):
        if self.tabs.currentIndex() == 0:
            return self.drill_down()
        row = self.active_grid().selected()
        if not row:
            return
        try:
            if self.tabs.currentIndex() == 2 and row["type"] == "settlement":
                group = self.store.supplier_settlement_detail(row["id"])
                dialog = QDialog(self)
                dialog.setWindowTitle(f"결제-{group['id']:06d} · 배분 내역")
                dialog.resize(820, 480)
                body = QVBoxLayout(dialog)
                label = QLabel(f"{group['date']} · {group['partner_name']} · {won(group['amount'])}원 · {'취소' if group['voided'] else '유효'}\n{group['memo']}")
                label.setWordWrap(True)
                body.addWidget(label)
                grid = DataGrid(["배분 대상", "거래일", "배분 금액"])
                values = [["초기 외상", "이월", group["opening_amount"]]] if group["opening_amount"] else []
                values += [[r["number"], r["document_date"], r["amount"]] for r in group["allocations"]]
                grid.fill(values)
                body.addWidget(grid)
                controls = QHBoxLayout()
                controls.addWidget(action("엑셀 저장", lambda: grid.export(dialog, "결제 배분")))
                controls.addWidget(action("인쇄", lambda: grid.print_pages(dialog, "결제 배분")))
                controls.addWidget(action("닫기", dialog.accept))
                body.addLayout(controls)
                dialog.exec()
            elif row.get("document_id"):
                document = self.store.document(row["document_id"])
                TradeDialog(self.window, document["kind"], document).exec()
                self.refresh()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def void(self):
        row = self.history_grid.selected() if self.tabs.currentIndex() == 2 else None
        if not row:
            return self.notify("결제 내역 탭에서 취소할 결제를 선택하세요.")
        reason, accepted = QInputDialog.getText(self, "결제 취소", "취소 사유 (당일 결제만 가능)")
        if accepted and _confirm(self, "결제 취소", "선택한 결제를 취소하고 미지급잔액을 되돌릴까요? 이력은 남습니다."):
            try:
                api = self.store.void_supplier_settlement if row["type"] == "settlement" else self.store.void_supplier_payment
                api(row["id"], reason)
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)

    def active_grid(self):
        return (self.grid, self.ledger_grid, self.history_grid)[self.tabs.currentIndex()]

    def export(self):
        self.active_grid().export(self, self.title)

    def print(self):
        self.active_grid().print_pages(self, self.title)
