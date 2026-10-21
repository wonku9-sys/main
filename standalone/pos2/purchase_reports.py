"""Offline purchase views: supplier/category/product/document and statement."""
from decimal import Decimal

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit
from PySide6.QtGui import QColor

from .common import day, qtext, rounded
from .widgets import Page, action, won,date_field
from .workflow_ui import TradeDialog, _date, _dates


PURCHASE_VIEWS = {
    "supplier": ("purchase_suppliers", "공급사별 매입현황"),
    "category": ("purchase_categories", "분류별 매입현황"),
    "product": ("purchase_products", "단품별 매입현황"),
    "document": ("purchase_documents", "전표별 매입현황"),
    "statement": ("purchase_statement", "매입계산서"),
}


class PurchaseReportingMixin:
    def purchase_status_filters(self,group='supplier'):
        if group not in PURCHASE_VIEWS:raise ValueError('매입현황 종류를 선택하세요.')
        self.require_menu(PURCHASE_VIEWS[group][0])
        return dict(suppliers=[dict(row) for row in self.db.execute(
            "SELECT s.id,s.code,s.name,s.business_no,s.supplier_mode,COALESCE(p.settlement_method,'cash') settlement_method FROM partners s LEFT JOIN supplier_profiles p ON p.partner_id=s.id WHERE s.kind='supplier' ORDER BY s.name,s.id")],
            groups=[dict(r) for r in self.db.execute('SELECT * FROM supplier_groups ORDER BY kind,sort_order,code,id')],
            memberships=[dict(r) for r in self.db.execute('SELECT * FROM supplier_group_members')],
            categories=[r[0] for r in self.db.execute("SELECT DISTINCT category FROM products WHERE category<>'' ORDER BY category")])

    def purchase_status_lines(self,start,end,group='document',partner_id=None,category='',search='',include_returns=True):
        if group not in PURCHASE_VIEWS:raise ValueError('매입현황 종류를 선택하세요.')
        self.require_menu(PURCHASE_VIEWS[group][0]);start,end=day(start),day(end)
        if start>end:raise ValueError('조회 시작일과 종료일을 확인하세요.')
        sql="""SELECT l.*,d.id document_id,d.date,d.number,d.kind,d.partner_id,s.code supplier_code,s.name supplier_name,
            s.business_no,s.supplier_mode,p.code product_code,p.barcode,p.specification,p.category,p.category_mid,p.category_small,
            p.base_unit FROM document_lines l JOIN documents d ON d.id=l.document_id JOIN partners s ON s.id=d.partner_id
            JOIN products p ON p.id=l.product_id WHERE d.status='posted' AND d.kind IN ('purchase','purchase_return') AND d.date BETWEEN ? AND ?"""
        params=[start,end]
        if partner_id is not None:sql+=' AND d.partner_id=?';params.append(partner_id)
        if category:sql+=' AND p.category=?';params.append(category)
        if not include_returns:sql+=" AND d.kind='purchase'"
        if str(search).strip():
            sql+=' AND (l.product_name LIKE ? OR p.code LIKE ? OR p.barcode LIKE ? OR s.name LIKE ? OR d.number LIKE ? OR s.business_no LIKE ?)'
            params += ['%'+str(search).strip()+'%']*6
        result=[]
        for record in self.db.execute(sql+' ORDER BY d.date,d.id,l.id',params):
            row=dict(record);sign=-1 if row['kind']=='purchase_return' else 1
            row['qty']=qtext(row['input_qty']);row['signed_qty']=qtext(sign*row['input_qty'])
            row['net_total']=sign*row['total'];row['vat']=rounded(Decimal(row['net_total'])/11) if row['tax_mode']=='taxable' else 0
            row['supply_value']=row['net_total']-row['vat'];row['exempt_total']=row['net_total'] if row['tax_mode']=='exempt' else 0
            row['taxable_total']=row['net_total'] if row['tax_mode']=='taxable' else 0
            result.append(row)
        return result

    def purchase_status(self, start, end, group="supplier", partner_id=None, category="", search="", include_returns=True):
        if group not in PURCHASE_VIEWS:
            raise ValueError("매입현황 종류를 선택하세요.")
        self.require_menu(PURCHASE_VIEWS[group][0])
        first, last = day(start), day(end)
        if first > last:
            raise ValueError("기간 시작일을 종료일 이전으로 선택하세요.")
        sql = "SELECT l.*,d.number,d.date,d.kind,d.id document_id,s.id report_supplier_id,s.name supplier_name,s.code supplier_code,s.business_no,s.supplier_mode,p.category,p.category_mid,p.category_small,p.code product_code,p.barcode,p.specification,p.base_unit FROM document_lines l JOIN documents d ON d.id=l.document_id JOIN partners s ON s.id=d.partner_id JOIN products p ON p.id=l.product_id WHERE d.status='posted' AND d.kind IN ('purchase','purchase_return') AND d.date BETWEEN ? AND ?"
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
            row = groups.setdefault((identifier, '' if group=='supplier' else unit), {"code": code, "label": label, "unit": unit, "purchase_qty": 0, "return_qty": 0, "purchase_total": 0, "return_total": 0, "taxable_total": 0, "exempt_total": 0, "documents": set(), "document_id": line["document_id"] if group == "document" else None,
                    "supplier_id":line["report_supplier_id"],"business_no":line["business_no"],"supplier_mode":line["supplier_mode"],"_units":{},"vat":0})
            units=row['_units'].setdefault(unit,dict(purchase_qty=0,return_qty=0))
            returned = line["kind"] == "purchase_return"
            row["return_qty" if returned else "purchase_qty"] += quantity
            units["return_qty" if returned else "purchase_qty"]+=quantity
            row["return_total" if returned else "purchase_total"] += line["total"]
            row["taxable_total" if line["tax_mode"] == "taxable" else "exempt_total"] += (-1 if returned else 1) * line["total"]
            if line['tax_mode']=='taxable':row['vat']+=(-1 if returned else 1)*rounded(Decimal(line['total'])/11)
            row["documents"].add(line["document_id"])
        rows = list(groups.values())
        for row in rows:
            units=row.pop('_units')
            row['quantities']=[dict(unit=unit,purchase_qty=qtext(q['purchase_qty']),return_qty=qtext(q['return_qty']),net_qty=qtext(q['purchase_qty']-q['return_qty'])) for unit,q in units.items()]
            row["net_qty"] = qtext(row["purchase_qty"] - row["return_qty"])
            row["purchase_qty"], row["return_qty"] = qtext(row["purchase_qty"]), qtext(row["return_qty"])
            if len(units)>1:row.update(unit='혼합 (단위별 상세)',purchase_qty='',return_qty='',net_qty='')
            row["net_total"] = row["purchase_total"] - row["return_total"]
            row["supply_value"] = row["taxable_total"] - row["vat"]
            row["total_supply_value"]=row["supply_value"]+row["exempt_total"]
            row["count"] = len(row.pop("documents"))
        totals = {key: sum(row[key] for row in rows) for key in ("purchase_total", "return_total", "net_total", "taxable_total", "exempt_total", "vat", "supply_value")}
        return {"rows": rows, "totals": totals, "start": first, "end": last, "group": group}


class PurchaseStatusPage(Page):
    def __init__(self,window,group):
        self.group=group
        self.menu_key,title=PURCHASE_VIEWS[group]
        super().__init__(window,title,'확정 전표 기준 · 매입/반품/순매입 · 상단 조회/출력 고정. 부가세는 포함세액 참고 집계입니다.')
        self.read_permissions=('trade',)
        from .purchase_reference_ui import setup
        setup(self)

    def refresh(self,*_):
        if not hasattr(self,'grid'):return
        try:
            from .purchase_reference_ui import refresh
            refresh(self)
        except (ValueError,PermissionError,OSError) as exc:
            self.grid.fill([])
            for name in ('supplier_documents','supplier_payments','invoice_comparison'):
                if hasattr(self,name):getattr(self,name).fill([])
            self._details_key=None
            self.fail(exc)

    def detail(self,*_):
        from .purchase_reference_ui import open_document
        open_document(self,self.grid)
