"""Offline purchase views: supplier/category/product/document and statement."""
from decimal import Decimal

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit

from .common import day, qtext, rounded
from .widgets import Page, action, won
from .workflow_ui import TradeDialog, _date, _dates


PURCHASE_VIEWS = {
    "supplier": ("purchase_suppliers", "공급사별 매입현황"),
    "category": ("purchase_categories", "분류별 매입현황"),
    "product": ("purchase_products", "단품별 매입현황"),
    "document": ("purchase_documents", "전표별 매입현황"),
    "statement": ("purchase_statement", "매입계산서"),
}


class PurchaseReportingMixin:
    def purchase_status(self, start, end, group="supplier", partner_id=None, category="", search="", include_returns=True):
        if group not in PURCHASE_VIEWS:
            raise ValueError("매입현황 종류를 선택하세요.")
        self.require_menu(PURCHASE_VIEWS[group][0])
        first, last = day(start), day(end)
        if first > last:
            raise ValueError("기간 시작일을 종료일 이전으로 선택하세요.")
        sql = "SELECT l.*,d.number,d.date,d.kind,d.id document_id,s.name supplier_name,s.code supplier_code,p.category,p.category_mid,p.category_small,p.code product_code,p.barcode,p.specification,p.base_unit FROM document_lines l JOIN documents d ON d.id=l.document_id JOIN partners s ON s.id=d.partner_id JOIN products p ON p.id=l.product_id WHERE d.status='posted' AND d.kind IN ('purchase','purchase_return') AND d.date BETWEEN ? AND ?"
        params = [first, last]
        if partner_id is not None:
            sql += " AND d.partner_id=?"
            params.append(partner_id)
        if category:
            sql += " AND p.category=?"
            params.append(category)
        term = str(search).strip()
        if term:
            sql += " AND (p.code LIKE ? OR p.name LIKE ? OR p.barcode LIKE ? OR p.specification LIKE ? OR s.code LIKE ? OR s.name LIKE ? OR d.number LIKE ?)"
            params += [f"%{term}%"] * 7
        if not include_returns:
            sql += " AND d.kind='purchase'"
        groups = {}
        for line in self.db.execute(sql + " ORDER BY d.date,d.id,l.id", params):
            code, label, identifier = (line["supplier_code"], line["supplier_name"], line["supplier_code"])
            if group == "category":
                code = " / ".join(filter(None, (line["category"], line["category_mid"], line["category_small"]))) or "미분류"
                label = code
                identifier = code
            elif group == "product":
                code, label, identifier = line["product_code"], line["product_name"], line["product_id"]
            elif group == "document":
                code, label, identifier = line["number"], line["supplier_name"], line["document_id"]
            unit = "g" if line["base_unit"] == "kg" else line["base_unit"]
            quantity = line["base_qty"] * (1000 if line["base_unit"] == "kg" else 1)
            row = groups.setdefault((identifier, unit), {"code": code, "label": label, "unit": unit, "purchase_qty": 0, "return_qty": 0, "purchase_total": 0, "return_total": 0, "taxable_total": 0, "exempt_total": 0, "documents": set(), "document_id": line["document_id"] if group == "document" else None})
            returned = line["kind"] == "purchase_return"
            row["return_qty" if returned else "purchase_qty"] += quantity
            row["return_total" if returned else "purchase_total"] += line["total"]
            row["taxable_total" if line["tax_mode"] == "taxable" else "exempt_total"] += (-1 if returned else 1) * line["total"]
            row["documents"].add(line["document_id"])
        rows = list(groups.values())
        for row in rows:
            row["net_qty"] = qtext(row["purchase_qty"] - row["return_qty"])
            row["purchase_qty"], row["return_qty"] = qtext(row["purchase_qty"]), qtext(row["return_qty"])
            row["net_total"] = row["purchase_total"] - row["return_total"]
            row["vat"] = rounded(Decimal(row["taxable_total"]) / 11)
            row["supply_value"] = row["taxable_total"] - row["vat"]
            row["count"] = len(row.pop("documents"))
        totals = {key: sum(row[key] for row in rows) for key in ("purchase_total", "return_total", "net_total", "taxable_total", "exempt_total", "vat", "supply_value")}
        return {"rows": rows, "totals": totals, "start": first, "end": last, "group": group}


class PurchaseStatusPage(Page):
    def __init__(self, window, group):
        self.group = group
        self.menu_key, title = PURCHASE_VIEWS[group]
        super().__init__(window, title, "확정 전표 기준 · 매입·반품·순매입을 분리합니다. kg 재고도 조회 수량은 g로 환산합니다.")
        self.read_permissions = ("trade",)
        filters = QHBoxLayout()
        self.start, self.end = _dates(filters, self.refresh)
        self.supplier = QComboBox()
        self.supplier.addItem("전체 공급사", None)
        for row in self.store.partners("supplier"):
            self.supplier.addItem(f"{row['code']} · {row['name']}", row["id"])
        filters.addWidget(self.supplier, 1)
        self.body.addLayout(filters)
        options = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItem("전체 분류", "")
        for category in sorted({row["category"] for row in self.store.products() if row["category"]}):
            self.category.addItem(category, category)
        self.search = QLineEdit()
        self.search.setPlaceholderText("상품코드 · 바코드 · 상품명 · 규격 · 공급사 · 전표번호")
        self.returns = QCheckBox("반품 포함")
        self.returns.setChecked(True)
        options.addWidget(self.category)
        options.addWidget(self.search, 1)
        options.addWidget(self.returns)
        self.body.addLayout(options)
        self.grid = self.table(["코드 / 전표번호", "명칭", "단위", "매입량", "반품량", "순매입량", "매입금액", "반품금액", "순매입금액", "과세 공급가액", "부가세", "면세금액", "전표 수"])
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.body.addWidget(self.summary)
        if group == "statement":
            notice = QLabel("매입계산서는 내부 관리용 집계입니다. 전자세금계산서 발급·전송이나 세무 신고 자료의 정확성을 보증하지 않습니다. 부가세는 최종 과세금액의 포함세액 참고 계산입니다.")
            notice.setWordWrap(True)
            self.body.addWidget(notice)
        self.supplier.currentIndexChanged.connect(self.refresh)
        self.category.currentIndexChanged.connect(self.refresh)
        self.returns.toggled.connect(self.refresh)
        self.search.returnPressed.connect(self.refresh)
        self.grid.itemDoubleClicked.connect(self.detail)
        self.refresh()

    def refresh(self, *_):
        if not hasattr(self, "grid"):
            return
        try:
            result = self.store.purchase_status(_date(self.start), _date(self.end), self.group, self.supplier.currentData(), self.category.currentData(), self.search.text(), self.returns.isChecked())
            self.grid.fill([[row["code"], row["label"], row["unit"], row["purchase_qty"], row["return_qty"], row["net_qty"], row["purchase_total"], row["return_total"], row["net_total"], row["supply_value"], row["vat"], row["exempt_total"], row["count"]] for row in result["rows"]], result["rows"])
            totals = result["totals"]
            self.summary.setText(f"조회 {len(result['rows']):,}행 · 매입 {won(totals['purchase_total'])}원 − 반품 {won(totals['return_total'])}원 = 순매입 {won(totals['net_total'])}원")
        except (ValueError, PermissionError) as exc:
            self.grid.fill([])
            self.fail(exc)

    def detail(self, *_):
        row = self.grid.selected()
        if row and row.get("document_id"):
            try:
                record = self.store.document(row["document_id"])
                TradeDialog(self.window, record["kind"], record).exec()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)
