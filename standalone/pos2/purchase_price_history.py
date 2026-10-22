"""Read-only purchase trends in an explicitly labelled common unit basis."""
from decimal import Decimal
from .common import day, rounded
from .currency import money_input as money


class PurchasePriceHistoryMixin:
    def purchase_price_history(self, product_id, as_of, unit_id=None, gram_input=False):
        self.require_menu('purchases')
        self._require('trade')
        cutoff = day(as_of)
        product = self.db.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone()
        if product is None:
            raise ValueError('상품을 찾을 수 없습니다.')
        factor, basis, unit_name = 1000, product['price_basis'], product['base_unit']
        if unit_id is not None:
            unit = self.db.execute('SELECT * FROM product_units WHERE id=? AND product_id=?', (unit_id, product_id)).fetchone()
            if unit is None or gram_input:
                raise ValueError('올바른 상품 단위를 선택하세요.')
            factor, basis, unit_name = unit['factor'], 1, unit['name']
        elif gram_input:
            if product['base_unit'] != 'kg':
                raise ValueError('g 환산은 kg 상품에서만 가능합니다.')
            factor, basis, unit_name = 1, 100, 'g'
        def normalized(value, old_factor, old_basis):
            return None if value is None else rounded(Decimal(value)*factor*basis/(old_factor*old_basis))
        query = """SELECT l.*,d.date,d.number,d.id document_id,p.name supplier_name,
            COALESCE(json_extract(e.payload,'$.datetime'),d.date) entry_datetime,
            json_extract(e.payload,'$.lines[' || (SELECT COUNT(*) FROM document_lines prior
                WHERE prior.document_id=l.document_id AND prior.id<l.id) || '].sale_price') recorded_sale
            FROM document_lines l JOIN documents d ON d.id=l.document_id
            JOIN partners p ON p.id=d.partner_id LEFT JOIN document_entry e ON e.document_id=d.id
            WHERE l.product_id=? AND d.kind='purchase' AND d.status='posted' AND d.date<=?
            ORDER BY d.date DESC,entry_datetime DESC,d.id DESC,l.id DESC LIMIT 501"""
        source = list(self.db.execute(query, (product_id, cutoff)))
        rows = []
        for row in source[:500]:
            rows.append(dict(document_id=row['document_id'], line_id=row['id'], date=row['date'],
                datetime=row['entry_datetime'], number=row['number'], supplier_name=row['supplier_name'],
                original_unit=row['unit_name'], original_basis=row['price_basis'],
                purchase_price=normalized(row['unit_price'], row['factor'], row['price_basis']),
                sale_price=normalized(money(row['recorded_sale']) if row['recorded_sale'] is not None else None,
                                      row['factor'], row['price_basis'])))
        promotions = []
        for row in self.db.execute("""SELECT p.id,p.title,p.start,p.end,i.purchase_price,i.sale_price
            FROM promotions p JOIN promotion_items i ON i.promotion_id=p.id
            WHERE i.product_id=? AND p.active=1 ORDER BY p.start DESC,p.id DESC LIMIT 100""", (product_id,)):
            promotions.append(dict(row) | {key: normalized(row[key],1000,product['price_basis'])
                                           for key in ('purchase_price','sale_price')})
        return dict(product_id=product_id, name=product['name'], barcode=product['barcode'], as_of=cutoff,
                    basis=f'{basis if basis != 1 else ""}{unit_name}당', records=rows,
                    truncated=len(source)>500, promotions=promotions)
