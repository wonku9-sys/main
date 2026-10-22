"""Read-only worksheet detail and per-user columns; never alter ledger amounts.

Legacy entries do not contain reference prices or bottle deposits. Unknown
financial data is deliberately not reconstructed from today's product prices.
"""
from decimal import Decimal
from hashlib import sha256
import json

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel

from .currency import round_amount
from .widgets import won


BASIC_COLUMNS = ('product','spec','barcode','qty','unit','factor','base_qty','total',
                 'price','sale_price','margin','category','supplier','stock','line_memo')
DETAIL_COLUMNS = (
    ('reference_price','기준가'), ('reference_amount','기준가액'),
    ('item_discount','할인'), ('item_discount_rate','할인율(%)'),
    ('supply_unit_price','공급단가'), ('supply_amount','공급가액'),
    ('line_vat','부가세'), ('deposit','보증금'),
    ('unit_profit','낱개이익'), ('sale_amount','판매가액'),
    ('estimated_profit','예정이익'), ('item_type','구분'),
)
DETAIL_KEYS = tuple(key for key,_ in DETAIL_COLUMNS)
EXPANDED_COLUMNS = BASIC_COLUMNS[:7] + DETAIL_KEYS[:8] + ('total','price','sale_price',
    'unit_profit','sale_amount','estimated_profit','margin','item_type','category',
    'supplier','stock','line_memo')
UNKNOWN_HINT = ('기준가·상품 할인·보증금의 저장 근거가 없어 미기록으로 표시합니다. '
                '0원이나 현재 상품장 가격으로 추정하지 않습니다. '
                '보증금은 단가에 포함되지만 공급가액·부가세에서는 제외해야 하므로 '
                '공급가액·부가세도 임의 산출하지 않습니다.')


def profit_values(quantity, factor, purchase_amount, sale_amount, product_basis=1):
    """Public Decimal won. Exact line amounts, not rounded unit-price products."""
    quantity, factor = Decimal(quantity), Decimal(factor)
    purchase_amount, sale_amount = Decimal(purchase_amount), Decimal(sale_amount)
    profit = sale_amount - purchase_amount
    base_quantity = quantity * factor
    return dict(sale_amount=sale_amount, estimated_profit=profit,
                unit_profit=round_amount(profit * product_basis / base_quantity) if base_quantity else None)


class PurchaseWorksheetView:
    def __init__(self, trade):
        self.trade = trade
        self.mode = 'compact'
        self.dc_amount = QLabel('DC금액: 미기록', trade)
        self.dc_rate = QLabel('DC율: 미기록', trade)
        for field in (self.dc_amount,self.dc_rate):
            field.setToolTip('상품 기준가 할인 표시입니다. 공급사 지급 D/C와 다릅니다. '+UNKNOWN_HINT)
            field.setTextFormat(Qt.TextFormat.PlainText)
        self.settings = QSettings('SY-POS','PurchaseWorksheet')
        path = getattr(trade.store,'path',None)
        actor = getattr(trade.store,'actor',None) or {}
        identity = f'{path}|{actor.get("id","")}'
        self.preference_key = 'columns-v1/'+sha256(identity.encode()).hexdigest() if path else None
        self.set_view('compact', persist=False)
        if self.preference_key:
            raw = self.settings.value(self.preference_key,'')
            try:
                if not isinstance(raw,str) or len(raw)>4096: return
                saved = json.loads(raw)
                if not isinstance(saved,dict) or set(saved)!={'mode','visible'}: return
                if saved['mode'] not in {'compact','expanded','custom'}: return
                visible = saved['visible']
                if not isinstance(visible,list) or any(not isinstance(k,str) for k in visible): return
                if not {'product','spec'}<=set(visible) or set(visible)-set(trade.line_columns): return
                self._apply(saved['mode'],set(visible))
            except (ValueError,TypeError):
                pass

    def _apply(self,mode,visible):
        table = self.trade.table
        scope,row,column = table.selection_scope,table.currentRow(),table.currentColumn()
        self.mode = mode
        order = EXPANDED_COLUMNS if mode!='compact' else self.trade.line_columns
        header = table.horizontalHeader()
        table.setUpdatesEnabled(False)
        try:
            for position,key in enumerate(order):
                logical = self.trade.line_columns.index(key)
                current = header.visualIndex(logical)
                if current!=position: header.moveSection(current,position)
            for index,key in enumerate(self.trade.line_columns):
                table.setColumnHidden(index,key not in visible)
            if column>=0 and self.trade.line_columns[column] not in visible:
                if scope=='row': table.choose_row(row)
                else:
                    target='price' if 'price' in visible else next(k for k in self.trade.line_columns if k in visible)
                    table.choose_cell(row,self.trade.line_columns.index(target))
        finally:
            table.setUpdatesEnabled(True)
        detailed = bool(set(DETAIL_KEYS)&visible)
        self.dc_amount.setVisible(detailed);self.dc_rate.setVisible(detailed)

    def visible_keys(self):
        return {key for i,key in enumerate(self.trade.line_columns) if not self.trade.table.isColumnHidden(i)}

    def _persist(self):
        if self.preference_key:
            visible=self.visible_keys()
            self.settings.setValue(self.preference_key,json.dumps(dict(mode=self.mode,
                visible=[key for key in self.trade.line_columns if key in visible])))
            self.settings.sync()

    def set_view(self,mode,persist=True):
        if mode not in {'compact','expanded'}: raise ValueError('표시 방식을 확인하세요.')
        self._apply(mode,set(BASIC_COLUMNS if mode=='compact' else self.trade.line_columns))
        if persist: self._persist()

    def set_column_visible(self,key,visible):
        if key in {'product','spec'} or key not in self.trade.line_columns: return
        selected = self.visible_keys()
        if visible: selected.add(key)
        else: selected.discard(key)
        self._apply('custom',selected);self._persist()

    def column_menu(self,menu):
        columns = menu.addMenu('열 선택')
        columns.setToolTipsVisible(True)
        columns.menuAction().setToolTip('표에 표시할 열을 선택합니다. 설정은 현재 점포·사용자별로 보존하며 장부는 변경하지 않습니다.')
        menu._sy_submenus.append(columns)
        for index,key in enumerate(self.trade.line_columns):
            item = columns.addAction(self.trade.table.horizontalHeaderItem(index).text())
            item.setCheckable(True);item.setChecked(not self.trade.table.isColumnHidden(index))
            item.setEnabled(key not in {'product','spec'})
            item.setToolTip('상품명·규격은 행 선택을 위한 고정 열입니다.' if key in {'product','spec'}
                            else '이 열의 표시 여부를 현재 점포·사용자별로 보존합니다. 장부는 변경하지 않습니다.')
            item.toggled.connect(lambda checked,key=key:self.set_column_visible(key,checked))
        columns._sy_actions=columns.actions()

    def clear_row(self,row,text='—'):
        for key in DETAIL_KEYS:
            row[key].setText(text)
            row[key].setToolTip('상품과 유효한 수량·단가를 입력하세요.')

    def update_row(self,row,quantity,factor,value,sale,product):
        for key in DETAIL_KEYS:
            row[key].setText('미기록');row[key].setToolTip(UNKNOWN_HINT)
        historic = row.get('saved_line') or row.get('source')
        if historic and historic['product_id']!=row['product'].currentData(): historic=None
        if historic and 'sale_price' not in historic.get('entry',{}) and not row.get('sale_price_reentered'):
            for key in ('unit_profit','sale_amount','estimated_profit'):
                row[key].setToolTip('당시 판매단가 기록이 없어 현재 상품장 가격으로 과거 이익을 계산하지 않습니다.')
            return
        values = profit_values(quantity,factor,value,sale,product.get('price_basis',1))
        for key,amount in values.items():
            row[key].setText(won(amount) if amount is not None else '—')
            column=self.trade.line_columns.index(key)
            needed=row[key].fontMetrics().horizontalAdvance(row[key].text())+14
            if self.trade.table.columnWidth(column)<needed:self.trade.table.setColumnWidth(column,needed)
            row[key].setToolTip('판매가액 − 매입금액의 참고 차액입니다. 실제 판매 확정 이익이 아닙니다.'
                if key!='unit_profit' else f"상품 기본단위 {product.get('price_basis',1)} {product['base_unit']} 기준 참고 차액입니다. 보증금을 구분한 상품 이익은 아닙니다.")
