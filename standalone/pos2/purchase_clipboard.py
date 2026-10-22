"""Reviewed, all-or-nothing Excel-table paste into an unsaved purchase."""
import csv
from io import StringIO
from decimal import Decimal

from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QVBoxLayout
from .common import qty
from .currency import public_input
from .widgets import DataGrid, action


def clipboard_table(value):
    if not isinstance(value, str) or len(value) > 300000:
        raise ValueError('붙여넣기 자료는 최대 500행까지 입력하세요.')
    try: rows = list(csv.reader(StringIO(value), delimiter='\t', strict=True))
    except csv.Error: raise ValueError('엑셀 셀의 따옴표/줄바꿈 형식을 확인하세요.') from None
    rows = [r for r in rows if any(v.strip() for v in r)]
    if len(rows)>501 or any(len(r)>96 for r in rows):raise ValueError('붙여넣기 자료는 제목 포함 최대 501행·96열까지 입력하세요.')
    return rows


def parse_purchase_clipboard(value):
    rows = clipboard_table(value)
    if rows and [v.strip() for v in rows[0]] in (['바코드','수량','매입단가','판매단가'], ['바코드','매입량','매입단가','판매단가']): rows.pop(0)
    if not 1 <= len(rows) <= 500: raise ValueError('바코드·수량·매입단가·판매단가 네 열을 1~500행 복사하세요.')
    result = []
    for i, row in enumerate(rows, 1):
        if len(row) != 4 or not row[0].strip(): raise ValueError(f'{i}행: 바코드·수량·매입단가·판매단가 네 열이 필요합니다.')
        try:
            quantity = Decimal(qty(row[1])) / 1000
            purchase, sale = public_input(row[2]), public_input(row[3])
        except ValueError as exc: raise ValueError(f'{i}행: {exc}') from None
        result.append(dict(barcode=row[0].strip(), qty=str(quantity), unit_price=str(purchase), sale_price=str(sale)))
    return result


def resolve_table(trade, table):
    from .purchase_import import plan_table
    catalog=trade.store.purchase_import_catalog()
    file=plan_table(table,catalog,trade.partner.currentData(),trade.date.date().toString('yyyy-MM-dd'))
    if file['error']:raise ValueError(file['error'])
    if file['partner_id']!=trade.partner.currentData():raise ValueError('표의 공급사가 선택한 공급사와 다릅니다. 공급사를 확인하세요 (F3).')
    products={p['id']:p for p in catalog['products']}
    return [dict(line, product=products[line['product_id']]) for line in file['lines']]


class PurchasePasteDialog(QDialog):
    def __init__(self, trade, rows):
        super().__init__(trade); self.setWindowTitle('엑셀 붙여넣기 검토'); self.resize(1050, 540)
        self._sy_no_home_button = True
        body = QVBoxLayout(self)
        notice = QLabel('상품·단위·가격·금액을 확인하세요. 100g당 가격은 단위에 표시합니다. 적용은 작성 중인 표에만 추가하며, 저장 전까지 재고·결제는 바뀌지 않습니다. 같은 상품의 중복 행은 그대로 보존합니다.')
        notice.setWordWrap(True); body.addWidget(notice)
        grid = DataGrid(['바코드','상품명','단위·가격 기준','매입량','입수량(기본단위)','매입단가','판매단가','매입금액'])
        for column,width in enumerate((130,155,130,80,130,110,110,120)):grid.setColumnWidth(column,width)
        grid.setToolTip('kg 상품의 g 입력은 1g=0.001kg로 환산합니다. 상품장 기본단위·단가 자체는 변경하지 않습니다.')
        grid.fill([[r['barcode'],r['product']['name'],r['unit_name']+(' (100g당)' if r.get('price_basis')==100 else ''),Decimal(r['qty']),Decimal(r['factor_override']) if 'factor_override' in r else '등록 단위 기준',Decimal(r['unit_price']),Decimal(r['sale_price']),Decimal(r['total']) if 'total' in r else '자동 계산'] for r in rows]); body.addWidget(grid,1)
        footer=QHBoxLayout(); footer.addStretch(); footer.addWidget(action('적용',self.accept,True)); footer.addWidget(action('취소',self.reject)); body.addLayout(footer)


def paste_purchase(trade):
    from .workflow_ui import _warn
    if trade.kind != 'purchase' or trade.readonly or trade.amending and not trade.amend_context['stock_editable']: return
    try:
        if not trade.partner.currentData(): raise ValueError('먼저 공급사를 선택하세요 (F3).')
        value=QApplication.clipboard().text();table=clipboard_table(value)
        whole_table=bool(table and len(table[0])>4)
        rows = resolve_table(trade,table) if whole_table else parse_purchase_clipboard(value)
        if len(trade.line_rows)+len(rows)>1000: raise ValueError('작성 중인 표는 최대 1,000행까지 붙여넣을 수 있습니다.')
        # Resolve every barcode before changing any editable row. Cache repeats
        # without coalescing them, so different prices/units remain independent.
        if not whole_table:
            cache = {r['barcode']:r['found'] for r in trade.store.purchase_clipboard_products([r['barcode'] for r in rows])}
            for i,row in enumerate(rows,1):
                barcode=row['barcode'];found=cache[barcode]
                if not found or not found['product']['active']: raise ValueError(f'{i}행: 등록되지 않았거나 무효인 바코드입니다: {barcode}')
                row.update(product=found['product'], unit_id=found['unit']['id'] if found.get('unit') else None,
                           unit_name=found['unit']['name'] if found.get('unit') else found['product']['base_unit'],
                           price_basis=1 if found.get('unit') else found['product'].get('price_basis',1))
        dialog=PurchasePasteDialog(trade,rows)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        if whole_table and resolve_table(trade,table)!=rows:
            raise ValueError('검토 중 상품/단위가 변경되었습니다. 다시 붙여넣어 확인하세요.')
        # The confirmation loop may permit another PC to change a product.
        # Refresh first, preserving explicit pasted prices; invalid rows abort.
        refreshed={} if whole_table else {r['barcode']:r['found'] for r in trade.store.purchase_clipboard_products([r['barcode'] for r in rows])}
        def basis(found):
            product=found['product'];unit=found.get('unit') or {}
            return (product['id'],product['base_unit'],product.get('price_basis',1),product['name'],
                    unit.get('id'),unit.get('name'),unit.get('factor'),unit.get('active',True))
        for row in ([] if whole_table else rows):
            current=refreshed[row['barcode']]
            if not current or not current['product']['active'] or basis(current)!=basis(cache[row['barcode']]):
                raise ValueError('검토 중 상품/단위가 변경되었습니다. 다시 붙여넣어 확인하세요.')
            row['product']=current['product']
        original_rows=list(trade.line_rows)
        trade._batch_lines=True
        try:
            for source in rows:
                product=source['product']; trade.product_map[product['id']]=product; trade.product_model.ensure(product)
                row=trade.add_line(product['id'],source['unit_id'],source['qty'],source['unit_price'])
                if source.get('gram_input'):
                    row['unit'].setCurrentIndex(row['unit'].findData('grams'))
                    row['price'].setText(source['unit_price'])
                row['sale_price'].setText(source['sale_price'])
                row['line_memo'].setText(source.get('line_memo',''))
                if 'factor_override' in source:row['factor'].setText(source['factor_override'])
                if 'amount_override' in source:row['amount_override']=source['amount_override']
        except BaseException:
            for row in list(trade.line_rows):
                if not any(row is original for original in original_rows):trade.remove_line(row)
            raise
        finally: trade._batch_lines=False
        # Discard only untouched placeholder rows, after the whole append has
        # succeeded. Cancellation/failure leaves the original worksheet intact.
        for row in original_rows:
            if (not row['product'].currentData() and not row['barcode'].text().strip() and not row['line_memo'].text()
                    and row['qty'].text()=='1' and not row.get('amount_override')
                    and row['price'].text() in {'','0','0.00'} and row['sale_price'].text() in {'','0','0.00'}):
                trade.remove_line(row)
        trade.recalculate(); trade.table.choose_row(len(trade.line_rows)-1)
    except (ValueError, PermissionError, ConnectionError) as exc: _warn(trade,exc)
