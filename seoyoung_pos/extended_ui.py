"""서영 POS 8차: 원본 데이터/업무 규칙 위에서 동작하는 상세 업무 메뉴와 매입 분석."""
from __future__ import annotations

from decimal import Decimal
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import app as base
from . import dialogs
from .service import POSService, _day, _integer, _quantity, _rounded, _qty_text, MAX_INTEGER


# The listed menu names follow the user's Together POS screenshots.
# Unsupported device/server workflows remain visibly disabled, NOT simulated.
GROUPS = [
    ("1. 기초관리", [
        ("01. 상품장", "products"), ("02. 확장단위", None),
        ("03. 프리셋", None), ("04. 셀프프리셋", None),
        ("05. 상품변경로그", None), ("06. 퇴출대상", None),
        ("07. 회원지정가", None), ("08. 라벨출력", None),
        ("09. 저울상품", None), ("10. 소분상품", None),
        ("11. 상품분류", None), ("12. 공급사관리", "suppliers"),
        ("13. 직원관리", "users"), ("14. 직원접속로그", None),
        ("15. 공급사변경로그", None), ("21. 환경설정", "settings"),
        ("22. 로컬설정", None), ("23. 표준분류관리", None),
    ]),
    ("2. 매입/발주관리", [
        ("01. 매입전표", "purchases"),
        ("02. 공급사별 매입현황", "supplier_purchase"),
        ("03. 분류별 매입현황", "category_purchase"),
        ("04. 단품별 매입현황", "product_purchase"),
        ("05. 전표별 매입현황", "purchases"),
        ("06. 매입계산서", None),
        ("11. 결제관리", "purchase_settlement"),
        ("21. 발주서", None), ("22. 발주서 원본", None),
    ]),
    ("3. 판매관리", [
        ("01. 판매전표", "sales"), ("02. 판매조회", "sales"),
        ("03. 상품별 판매현황", "product_sale"), ("04. 판매처 관리", "customers"),
    ]),
    ("4. 신용승인", [("01. 카드승인 내역", None)]),
    ("5. 마케팅관리", [("01. 프로모션 관리", None)]),
    ("6. 재고관리", [
        ("01. 재고조회", "inventory"), ("02. 재고 입출고", "inventory"),
        ("03. 재고 실사", "inventory"),
    ]),
    ("7. 레포트관리", [
        ("01. 매입·매출 분석", "reports"), ("02. 공급사별 현황", "supplier_purchase"),
        ("03. 상품별 매입현황", "product_purchase"),
    ]),
    ("8. 회원관리", [("01. 판매처 관리", "customers"), ("02. 회원 포인트", None)]),
    ("9. 센터서비스", [("01. 원격지원", None)]),
    ("0. 기타", [("01. 사용자 설정", "settings"), ("02. 프로그램 정보", "dashboard")]),
]

BASE_PERMISSIONS = {
    "dashboard": "reports", "products": "products", "suppliers": "partners",
    "customers": "partners", "purchases": "purchases", "sales": "sales",
    "inventory": "inventory", "reports": "reports", "users": "users",
    "settings": "settings", "supplier_purchase": "purchases",
    "category_purchase": "purchases", "product_purchase": "purchases",
    "purchase_settlement": "purchases", "product_sale": "sales",
}


def revise_purchase(self, doc_id, partner_id, date, items, memo=""):
    """Atomically revise a posted purchase while retaining its number/payments/audit.

    Strictly refuses edits when a later movement exists for an old item.
    This prevents edits from invalidating later stock balances or average costs.
    """
    self._require("purchases")
    day = _day(date)
    if not items or not isinstance(items, (tuple, list)):
        raise ValueError("전표에 품목을 한 건 이상 입력해 주세요.")
    prepared = []
    for line in items:
        qty = _quantity(line.get("qty", ""))
        if qty <= 0:
            raise ValueError("매입 수량은 0보다 커야 합니다.")
        price = _integer(line.get("unit_price", ""), "매입단가")
        amount = _rounded(Decimal(qty) * price / 1000)
        prepared.append((line.get("product_id"), qty, price, amount))
    total = sum(row[3] for row in prepared)
    if total > MAX_INTEGER:
        raise ValueError("전표 합계가 허용 범위를 초과했습니다.")

    with self._transaction():
        self._require("purchases")
        doc = self._document(doc_id)
        if doc["kind"] != "purchase" or doc["status"] != "posted":
            raise ValueError("정상 매입전표만 수정할 수 있습니다.")
        if day != doc["date"]:
            raise ValueError("전표번호와 거래 이력 보존을 위해 거래일은 수정할 수 없습니다.")
        if total < doc["paid"]:
            raise ValueError("변경할 전표 금액은 이미 지급한 금액보다 작을 수 없습니다.")
        partner = self.db.execute(
            "SELECT id FROM partners WHERE id=? AND kind='supplier'", (partner_id,)
        ).fetchone()
        if partner is None:
            raise ValueError("공급사를 선택해 주세요.")

        old = self.db.execute(
            "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,)
        ).fetchall()
        # Audit trails and average-cost calculations must not be altered retroactively.
        seen = set()
        for item in old:
            pid = item["product_id"]
            if pid in seen:
                continue
            seen.add(pid)
            last = self.db.execute(
                "SELECT MAX(id) FROM stock_movements "
                "WHERE document_id=? AND product_id=? AND kind='purchase'",
                (doc_id, pid),
            ).fetchone()[0]
            if last is None or self.db.execute(
                "SELECT 1 FROM stock_movements WHERE product_id=? AND id>? LIMIT 1",
                (pid, last),
            ).fetchone():
                raise ValueError(
                    "이 전표 이후 해당 상품의 입출고 이력이 있어 수정할 수 없습니다. "
                    "원가·재고 보호를 위해 후속 거래를 먼저 검토해 주세요."
                )
        for pid, qty, price, amount in prepared:
            prod = self.db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not prod or not prod["active"]:
                raise ValueError("사용 가능한 상품만 등록할 수 있습니다.")

        # Reverse each original purchase line, retaining dated compensating movements.
        for item in reversed(old):
            prod = self.db.execute(
                "SELECT stock_qty,stock_cost FROM products WHERE id=?",
                (item["product_id"],),
            ).fetchone()
            if prod["stock_qty"] < item["qty"] or prod["stock_cost"] < item["cost"]:
                raise ValueError("현재 수량이나 원가가 부족해 안전한 수정이 불가능합니다.")
            self._stock_move(
                item["product_id"], -item["qty"], "purchase_edit_reverse",
                "매입전표 수정 전 기존 품목 취소", doc_id, day,
            )
            self.db.execute(
                "UPDATE products SET stock_cost=stock_cost-? WHERE id=?",
                (item["cost"], item["product_id"]),
            )
        self.db.execute("DELETE FROM document_items WHERE document_id=?", (doc_id,))
        self.db.execute(
            "UPDATE documents SET partner_id=?,total=?,memo=? WHERE id=?",
            (partner_id, total, str(memo).strip(), doc_id),
        )
        for pid, qty, price, amount in prepared:
            prod = self.db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if prod["stock_cost"] + amount > MAX_INTEGER:
                raise ValueError("상품의 재고원가가 허용 범위를 초과했습니다.")
            self.db.execute(
                "INSERT INTO document_items "
                "(document_id,product_id,product_name,unit,qty,unit_price,total,cost) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (doc_id, pid, prod["name"], prod["unit"], qty, price, amount, amount),
            )
            self._stock_move(
                pid, qty, "purchase", str(memo).strip() or doc["number"], doc_id, day
            )
            self.db.execute(
                "UPDATE products SET stock_cost=stock_cost+? WHERE id=?",
                (amount, pid),
            )
        self._audit(
            "revise", "document", doc_id,
            {"number": doc["number"], "old_total": doc["total"],
             "new_total": total, "old_item_count": len(old),
             "new_item_count": len(prepared)},
        )
    return doc_id


class PurchaseRevisionDialog(dialogs.DocumentDialog):
    """Edit individual lines of an existing, eligible purchase voucher."""
    def __init__(self, service, document_id, parent=None):
        doc = service.get_document(document_id)
        if doc["kind"] != "purchase" or doc["status"] != "posted":
            raise ValueError("수정할 수 있는 매입전표가 아닙니다.")
        partner = next(
            (dict(r) for r in service.db.execute(
                "SELECT * FROM partners WHERE id=?", (doc["partner_id"],)
            )), None
        )
        self.revision_id = document_id
        super().__init__(service, "purchase", partner=partner, parent=parent)
        self.setWindowTitle("매입전표 품목 수정 · " + doc["number"])
        self.items.setRowCount(0)
        self.date.setDate(QDate.fromString(doc["date"], "yyyy-MM-dd"))
        self.date.setEnabled(False)
        self.paid.setText(str(doc["paid"]))
        self.paid.setReadOnly(True)
        self.memo.setPlainText(doc.get("memo", ""))
        for line in doc["items"]:
            self.add_line()
            row = self.items.rowCount() - 1
            product = self.items.cellWidget(row, 0)
            found = product.findData(line["product_id"])
            if found >= 0:
                product.setCurrentIndex(found)
            self.items.cellWidget(row, 2).setText(str(line["qty"]))
            self.items.cellWidget(row, 3).setText(str(line["unit_price"]))
        self.recalculate()
        self.resize(1150, 820)

    def save(self):
        try:
            if not self.partner:
                raise ValueError("공급사를 선택해 주세요.")
            lines = []
            for r in range(self.items.rowCount()):
                product = self.items.cellWidget(r, 0)
                pid = product.currentData()
                if not pid or product.currentText() != product.itemText(product.currentIndex()):
                    raise ValueError(f"{r+1}행 상품을 목록에서 선택해 주세요.")
                lines.append({
                    "product_id": pid,
                    "qty": self.items.cellWidget(r, 2).text(),
                    "unit_price": self.items.cellWidget(r, 3).text(),
                })
            self.service.revise_purchase(
                self.revision_id, self.partner["id"],
                self.date.date().toString("yyyy-MM-dd"),
                lines, self.memo.toPlainText().strip(),
            )
            self.accept()
        except (ValueError, PermissionError) as exc:
            self.error(exc)


class PurchaseAnalyticsPage(base.Page):
    """Reports query the existing service database; no independent ledger."""
    TITLES = {
        "supplier_purchase": ("공급사별 매입현황", "공급사별 거래금액 · 결제 · 잔액"),
        "category_purchase": ("분류별 매입현황", "상품 분류와 단위별 매입실적"),
        "product_purchase": ("단품별 매입현황", "상품별 수량 · 금액 · 평균 매입단가"),
        "purchase_settlement": ("매입 결제관리", "기간별 공급사 지급내역"),
        "product_sale": ("상품별 판매현황", "상품별 매출금액과 수량"),
    }

    def __init__(self, window, mode):
        self.mode = mode
        title, subtitle = self.TITLES[mode]
        super().__init__(window, title, subtitle, mode)
        self.add_export()
        f = self.filter_frame()
        f.addWidget(QLabel("기간"))
        self.start = QDateEdit(QDate.currentDate().addMonths(-1))
        self.end = QDateEdit(QDate.currentDate())
        for d in (self.start, self.end):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
            d.setFixedWidth(125)
            f.addWidget(d)
        self.partner = QComboBox()
        self.partner.setMinimumWidth(180)
        f.addWidget(self.partner)
        f.addWidget(self.search_field("상품 · 공급사 검색"), 1)
        f.addWidget(base.button("조회 (F5)", self.refresh, primary=True, glyph="search"))
        columns = {
            "supplier_purchase": ["공급사코드", "공급사명", "전표건수", "매입합계", "결제금액", "미지급잔액"],
            "category_purchase": ["상품분류", "단위", "총매입량", "매입금액", "상품종류"],
            "product_purchase": ["상품코드", "상품명", "분류", "단위", "매입량", "매입금액", "평균단가"],
            "purchase_settlement": ["결제일", "공급사명", "전표번호", "결제금액", "메모"],
            "product_sale": ["상품코드", "상품명", "분류", "단위", "판매량", "판매금액", "평균단가"],
        }
        self.table_frame(columns[mode], title + " 목록")
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(65)
        self.rows = []

    def refresh(self):
        self.service._require("sales" if self.mode == "product_sale" else "purchases")
        if self.start.date() > self.end.date():
            raise ValueError("조회 기간을 확인해 주세요.")
        selected = self.partner.currentData()
        self.partner.blockSignals(True)
        self.partner.clear()
        self.partner.addItem("전체 거래처", None)
        kind = "customer" if self.mode == "product_sale" else "supplier"
        for record in self.service.db.execute(
            "SELECT id,name FROM partners WHERE kind=? ORDER BY name", (kind,)
        ):
            self.partner.addItem(record["name"], record["id"])
        self.partner.setCurrentIndex(max(0, self.partner.findData(selected)))
        self.partner.blockSignals(False)
        params = [self.start.date().toString("yyyy-MM-dd"),
                  self.end.date().toString("yyyy-MM-dd")]
        conditions = ["d.status='posted'", "d.date BETWEEN ? AND ?"]
        pid = self.partner.currentData()
        if pid is not None:
            conditions.append("d.partner_id=?")
            params.append(pid)
        term = "%" + self.search.text().strip() + "%"
        if self.mode == "supplier_purchase":
            if self.search.text().strip():
                conditions.append("p.name LIKE ?")
                params.append(term)
            rows = self.service.db.execute(
                "SELECT p.code,p.name,COUNT(d.id) cnt,SUM(d.total) total,"
                "SUM(d.paid) paid,SUM(d.total-d.paid) balance "
                "FROM documents d JOIN partners p ON p.id=d.partner_id "
                "WHERE d.kind='purchase' AND " + " AND ".join(conditions) +
                " GROUP BY p.id ORDER BY total DESC", params,
            )
            values = [[r["code"], r["name"], r["cnt"], r["total"], r["paid"], r["balance"]]
                      for r in rows]
        elif self.mode == "purchase_settlement":
            if self.search.text().strip():
                conditions.append("p.name LIKE ?")
                params.append(term)
            rows = self.service.db.execute(
                "SELECT pay.date,p.name,d.number,pay.amount,pay.memo "
                "FROM payments pay JOIN documents d ON d.id=pay.document_id "
                "JOIN partners p ON p.id=d.partner_id "
                "WHERE d.kind='purchase' AND " + " AND ".join(conditions).replace("d.date BETWEEN ? AND ?", "pay.date BETWEEN ? AND ?") +
                " ORDER BY pay.date DESC,pay.id DESC", params,
            )
            values = [list(r) for r in rows]
        else:
            if self.search.text().strip():
                conditions.append("(i.product_name LIKE ? OR p.name LIKE ?)")
                params.extend([term, term])
            if self.mode == "category_purchase":
                select = ("COALESCE(pr.category,'미분류') grp,i.unit,"
                          "ROUND(SUM(i.qty)/1000.0,3) qty,SUM(i.total) total,"
                          "COUNT(DISTINCT i.product_id) kinds")
                group = "COALESCE(pr.category,'미분류'),i.unit"
            else:
                select = ("pr.code,i.product_name,COALESCE(pr.category,'미분류'),i.unit,"
                          "ROUND(SUM(i.qty)/1000.0,3) qty,SUM(i.total) total,"
                          "ROUND(1000.0*SUM(i.total)/NULLIF(SUM(i.qty),0),2) average")
                group = "i.product_id,i.unit"
            doc_kind = "sale" if self.mode == "product_sale" else "purchase"
            rows = self.service.db.execute(
                f"SELECT {select} FROM document_items i "
                "JOIN documents d ON d.id=i.document_id "
                "JOIN partners p ON p.id=d.partner_id "
                "LEFT JOIN products pr ON pr.id=i.product_id "
                "WHERE d.kind=? AND " + " AND ".join(conditions) +
                f" GROUP BY {group} ORDER BY total DESC",
                [doc_kind, *params],
            )
            values = [list(r) for r in rows]
        self.rows = values
        self.table.populate(values, numeric=tuple(
            range(2 if self.mode == "supplier_purchase" else
                  3 if self.mode == "category_purchase" else
                  3 if self.mode == "purchase_settlement" else 4,
                  len(values[0]) if values else self.table.columnCount())
        ))
        total_index = {"supplier_purchase": 3, "category_purchase": 3,
                       "product_purchase": 5, "purchase_settlement": 3,
                       "product_sale": 5}[self.mode]
        self.results(len(values), f"조회합계   {base.money(sum(int(v[total_index] or 0) for v in values))} 원")


def _new_navigation(self):
    previous = self.current_page.code if self.current_page else None
    while self.nav_layout.count():
        item = self.nav_layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
    while self.stack.count():
        widget = self.stack.widget(0)
        self.stack.removeWidget(widget)
        widget.deleteLater()
    self.pages.clear()
    self.page_scrollers.clear()
    self.nav_buttons.clear()
    self.current_page = None

    sidebar = self.nav_layout.parentWidget()
    if sidebar is not None:
        sidebar.setFixedWidth(265)
    tree = QTreeWidget()
    tree.setObjectName("professionalMenu")
    tree.setHeaderHidden(True)
    tree.setIndentation(18)
    tree.setAnimated(True)
    tree.setUniformRowHeights(True)
    tree.setMinimumHeight(400)
    for group_name, children in GROUPS:
        parent = QTreeWidgetItem(tree, [group_name])
        parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for title, key in children:
            child = QTreeWidgetItem(parent, [title])
            if key is None:
                child.setDisabled(True)
                child.setToolTip(0, "추후 개발 항목 · 실제 거래 처리 없음")
            elif self.service.has_permission(BASE_PERMISSIONS[key]):
                child.setData(0, Qt.ItemDataRole.UserRole, key)
                self.nav_buttons[key] = child
            else:
                child.setHidden(True)
        parent.setExpanded(group_name.startswith(("1.", "2.")))
    tree.itemClicked.connect(
        lambda item, col: self.navigate(item.data(0, Qt.ItemDataRole.UserRole))
        if item.data(0, Qt.ItemDataRole.UserRole) else None
    )
    self.nav_layout.addWidget(tree, 1)
    self.menu_tree = tree

    self.user_label.setText(self.service.user["name"])
    self.role_label.setText(
        "관리자" if self.service.user["role"] == "admin" else "일반 사용자"
    )
    target = previous if previous in self.nav_buttons else (
        "purchases" if "purchases" in self.nav_buttons else
        next(iter(self.nav_buttons), None)
    )
    if target:
        self.navigate(target)
    else:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.addWidget(QLabel("현재 계정에 허용된 업무 화면이 없습니다."))
        self.stack.addWidget(screen)
    self.show_message(
        f"원본 SQLite 자료 유지 · {self.database_path} | F5 조회 · Ctrl+N 등록 · Ctrl+E 엑셀"
    )


def _new_navigate(self, key):
    if not key or key not in self.nav_buttons:
        return
    if key not in self.pages:
        factories = {
            "dashboard": lambda: base.DashboardPage(self),
            "products": lambda: base.ProductsPage(self),
            "suppliers": lambda: base.PartnersPage(self, "supplier"),
            "customers": lambda: base.PartnersPage(self, "customer"),
            "purchases": lambda: base.DocumentsPage(self, "purchase"),
            "sales": lambda: base.DocumentsPage(self, "sale"),
            "inventory": lambda: base.InventoryPage(self),
            "reports": lambda: base.ReportsPage(self),
            "users": lambda: base.UsersPage(self),
            "settings": lambda: base.SettingsPage(self),
        }
        if key in PurchaseAnalyticsPage.TITLES:
            page = PurchaseAnalyticsPage(self, key)
        else:
            page = factories[key]()
        self.pages[key] = page
        scroller = QScrollArea()
        scroller.setObjectName("pageScroller")
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setWidget(page)
        self.page_scrollers[key] = scroller
        self.stack.addWidget(scroller)
    page = self.pages[key]
    try:
        page.refresh()
    except (ValueError, PermissionError) as exc:
        QMessageBox.warning(self, "조회 오류", str(exc))
        return
    self.current_page = page
    self.stack.setCurrentWidget(self.page_scrollers[key])
    self.breadcrumb.setText("서영 POS  /  " + page.title)
    self.menu_tree.blockSignals(True)
    self.menu_tree.setCurrentItem(self.nav_buttons[key])
    self.menu_tree.blockSignals(False)


def _detail_edit(self):
    try:
        edited = PurchaseRevisionDialog(self.service, self.document_id, self)
        if edited.exec() == QDialog.DialogCode.Accepted:
            self.items.setRowCount(0)
            self.document = self.service.get_document(self.document_id)
            for item in self.document["items"]:
                self.add_readonly_line(item)
            self.memo.setPlainText(self.document.get("memo", ""))
            self.partner_label.setText(self.document.get("partner_name", ""))
            self.changed = True
            self.update_detail()
    except (ValueError, PermissionError) as exc:
        self.error(exc)


def install():
    POSService.revise_purchase = revise_purchase
    base.MainWindow.rebuild_navigation = _new_navigation
    base.MainWindow.navigate = _new_navigate
    dialogs.DocumentDialog.edit_saved_purchase = _detail_edit

    original_init = dialogs.DocumentDialog.__init__

    def enhanced_detail_init(self, service, kind, partner=None, document_id=None, parent=None):
        original_init(self, service, kind, partner, document_id, parent)
        if document_id and kind == "purchase" and self.document["status"] == "posted":
            control = base.button("전표 품목 수정", self.edit_saved_purchase, glyph="box")
            control.setToolTip(
                "원본 전표번호와 지급 이력을 보존합니다. 후속 입출고가 있다면 안전을 위해 수정이 거부됩니다."
            )
            control.setEnabled(service.has_permission("purchases"))
            # Add beside the existing '추가 결제' and '전표 취소' controls.
            self.layout.insertWidget(max(0, self.layout.count()-2), control)

    dialogs.DocumentDialog.__init__ = enhanced_detail_init
    base.STYLE += """
QTreeWidget#professionalMenu { background:#122238; color:#C9D7EB; border:0; outline:0;
    font-size:12px; padding:4px 1px; }
QTreeWidget#professionalMenu::item { padding:6px 2px; border-radius:5px; }
QTreeWidget#professionalMenu::item:selected { background:#174E58; color:#80F0D8; }
QTreeWidget#professionalMenu::item:hover { background:#29415D; color:white; }
QTreeWidget#professionalMenu::item:disabled { color:#526981; }
"""
