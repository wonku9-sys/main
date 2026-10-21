"""Audited, atomic purchase revisions without reopening a posted document.

Existing sale/count costs remain immutable. Stock-changing revisions therefore
require no subsequent movement for the affected products. Payments are preserved,
never recreated by saving a revision. Zero-line posted vouchers retain their ID.
"""
import calendar
from collections import defaultdict
from datetime import date
import hmac
import json

from .common import day, money, now, qtext, text
from .shared_protocol import fingerprint


def three_month_cutoff(today=None):
    today = today or date.today()
    ordinal = today.year * 12 + today.month - 1 - 3
    year, month = divmod(ordinal, 12)
    month += 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1])).isoformat()


class PurchaseAmendmentMixin:
    def _purchase_revision_snapshot(self, identifier):
        entry = self.db.execute('SELECT payload FROM document_entry WHERE document_id=?', (identifier,)).fetchone()
        return dict(document=self._trade_row(identifier),
                    lines=[dict(r) for r in self.db.execute('SELECT * FROM document_lines WHERE document_id=? ORDER BY id', (identifier,))],
                    entry=json.loads(entry[0]) if entry else {},
                    payments=[dict(r) for r in self.db.execute('SELECT * FROM payments WHERE document_id=? ORDER BY id', (identifier,))])

    def _purchase_original_date(self, identifier, fallback):
        first = self.db.execute("SELECT detail FROM audit WHERE entity='document' AND entity_id=? AND action='revise_purchase' ORDER BY id LIMIT 1", (identifier,)).fetchone()
        return json.loads(first[0])['original_date'] if first else fallback

    def _purchase_revision_anchor(self, record):
        anchor = self.db.execute("SELECT MAX(id) FROM stock_events WHERE document_id=? AND kind='purchase'", (record['id'],)).fetchone()[0]
        if anchor is None:
            # Originally untracked/empty vouchers have no receipt event. Treat
            # same-second events conservatively rather than guess their order.
            anchor = self.db.execute('SELECT COALESCE(MAX(id),0) FROM stock_events WHERE created_at<?', (record['created_at'],)).fetchone()[0]
        return anchor

    def _purchase_stock_edit_check(self, record, products, new_date):
        anchor = self._purchase_revision_anchor(record)
        for product in products:
            if self.db.execute('SELECT 1 FROM stock_events WHERE product_id=? AND id>? AND (document_id IS NULL OR document_id<>?) LIMIT 1', (product, anchor, record['id'])).fetchone():
                raise ValueError('이후 판매·반품·실사 등 재고 이동이 있습니다. 수량·금액·거래일 변경에는 연결 원가 재계산이 필요합니다. 메모·담당자만 수정할 수 있습니다.')
            if new_date < record['date'] and self.db.execute('SELECT 1 FROM stock_events WHERE product_id=? AND date>? AND (document_id IS NULL OR document_id<>?) LIMIT 1', (product, new_date, record['id'])).fetchone():
                raise ValueError('변경할 날짜 이후의 다른 재고 이력이 있습니다. 거래일을 앞당길 수 없습니다.')

    def _purchase_revision_state(self, identifier):
        snapshot = self._purchase_revision_snapshot(identifier)
        products = {r['product_id'] for r in snapshot['lines']}
        products.update(r[0] for r in self.db.execute('SELECT DISTINCT product_id FROM stock_events WHERE document_id=?', (identifier,)))
        stocks = []
        for product in sorted(products):
            row = self.db.execute('SELECT * FROM products WHERE id=?', (product,)).fetchone()
            last = self.db.execute('SELECT COALESCE(MAX(id),0) FROM stock_events WHERE product_id=?', (product,)).fetchone()[0]
            stocks.append([dict(row), last])
        children = [dict(r) for r in self.db.execute('SELECT * FROM documents WHERE source_id=? ORDER BY id', (identifier,))]
        references = [dict(r) for r in self.db.execute('SELECT l.* FROM document_lines l JOIN document_lines s ON s.id=l.source_line_id WHERE s.document_id=? ORDER BY l.id', (identifier,))]
        revision = self.db.execute("SELECT COALESCE(MAX(id),0) FROM audit WHERE entity='document' AND entity_id=?", (identifier,)).fetchone()[0]
        closing = self.db.execute('SELECT MAX(date) FROM inventory_closes').fetchone()[0]
        return fingerprint(dict(snapshot=snapshot, stocks=stocks, children=children, references=references,
                                revision=revision, closing=closing, restore=self._current_restore_token()))

    def purchase_edit_context(self, identifier):
        self._require('trade'); self.require_menu('purchases')
        record = self._trade_row(identifier)
        cutoff = three_month_cutoff()
        result = dict(allowed=False, reason='', stock_editable=False, stock_reason='', minimum_date=cutoff,
                      document_token=self._edit_snapshot('documents', identifier), state=self._purchase_revision_state(identifier))
        try:
            self._require_capability('purchases', 'edit')
            if record['kind'] != 'purchase' or record['status'] != 'posted':
                raise ValueError('확정된 매입전표만 수정할 수 있습니다.')
            original = self._purchase_original_date(identifier, record['date'])
            if min(original, record['date']) < cutoff:
                raise ValueError(f'{cutoff} 이전에 작성된 전표는 수정할 수 없습니다. 기준은 달력상 3개월입니다.')
            if max(original, record['date']) > date.today().isoformat():
                raise ValueError('미래 날짜의 확정 전표는 수정할 수 없습니다.')
            self._assert_open(record['date'])
            result['allowed'] = True
        except (ValueError, PermissionError) as exc:
            result['reason'] = str(exc)
            return result
        try:
            if self.db.execute('SELECT 1 FROM documents WHERE source_id=? LIMIT 1', (identifier,)).fetchone():
                raise ValueError('연결된 반품(초안·취소 이력 포함)이 있습니다. 품목·거래처·거래일은 보존하고 메모·담당자만 수정할 수 있습니다.')
            products = {r[0] for r in self.db.execute('SELECT product_id FROM document_lines WHERE document_id=?', (identifier,))}
            self._purchase_stock_edit_check(record, products, record['date'])
            result['stock_editable'] = True
        except ValueError as exc:
            result['stock_reason'] = str(exc)
        return result

    def revise_purchase(self, identifier, data, expected_state, reason):
        with self._tx():
            self._require('trade'); self._require_capability('purchases', 'edit')
            reason = text(reason, '수정 사유', required=True, maximum=500)
            context = self.purchase_edit_context(identifier)
            if not context['allowed']:
                raise ValueError(context['reason'])
            if not isinstance(expected_state, str) or not hmac.compare_digest(expected_state, context['state']):
                raise ValueError('다른 작업에서 전표·결제·재고가 변경되었습니다. 입력을 보관하고 최신 전표를 다시 열어 수정하세요.')
            self._check_edit_snapshot('documents', identifier, data)
            if data.get('kind') != 'purchase' or data.get('source_id'):
                raise ValueError('매입 수정에서는 전표 유형을 변경할 수 없습니다. 반품 연결을 보존합니다.')
            if money(data.get('paid', 0)) or data.get('payment_plan'):
                raise ValueError('기존 결제는 수정 저장으로 다시 등록하지 않습니다. 결제 메뉴에서 처리하세요.')
            before = self._purchase_revision_snapshot(identifier)
            old = before['document']
            prepared = self._prepare_trade(data, posting=False)
            if not three_month_cutoff() <= prepared['date'] <= date.today().isoformat():
                raise ValueError('변경할 매입일은 달력상 3개월 이내이며 미래일이 아니어야 합니다.')
            self._assert_open(prepared['date'])
            originals = {r['id']: r for r in before['lines']}
            used = set()
            for raw, line in zip(data.get('lines', []), prepared['lines']):
                if 'expected_price_basis' in raw and raw['expected_price_basis'] != line['price_basis']:
                    raise ValueError('상품 단가 기준이 변경되었습니다. 상품을 다시 선택해 확인하세요.')
                if 'expected_base_unit' in raw and raw['expected_base_unit'] != line['product']['base_unit']:
                    raise ValueError('상품 기본단위가 변경되었습니다. 상품을 다시 선택해 확인하세요.')
                source = raw.get('line_id')
                if source is not None:
                    if type(source) is not int or source not in originals or source in used:
                        raise ValueError('수정할 원래 품목 행을 다시 확인하세요.')
                    used.add(source)
                    original = originals[source]
                    original_gram = original['unit_id'] is None and original['unit_name'] == 'g' and line['product']['base_unit'] == 'kg'
                    if (original['product_id'], original['unit_id']) == (line['product_id'], line['unit_id']) and original_gram == bool(raw.get('gram_input')):
                        for key in ('product_name', 'unit_name', 'supplier_id', 'tax_mode', 'price_basis'):
                            line[key] = original[key]
            columns = ('product_id', 'unit_id', 'product_name', 'unit_name', 'factor', 'input_qty', 'base_qty',
                       'unit_price', 'total', 'cost', 'source_line_id', 'supplier_id', 'tax_mode', 'price_basis')
            old_values = [tuple(r[k] for k in columns) for r in before['lines']]
            new_values = [tuple(r[k] for k in columns) for r in prepared['lines']]
            structural = old_values != new_values or prepared['partner_id'] != old['partner_id'] or prepared['date'] != old['date']
            if structural and not context['stock_editable']:
                raise ValueError(context['stock_reason'])
            if prepared['partner_id'] != old['partner_id'] and before['payments']:
                raise ValueError('결제 이력(취소 포함)이 있어 공급사를 변경할 수 없습니다.')
            paid = sum(p['amount'] for p in before['payments'] if not p['voided'])
            if prepared['total'] < paid:
                raise ValueError('수정 금액이 기존 지급·할인·어음 합계보다 작습니다. 결제관리에서 먼저 확인하세요.')
            if any(not p['voided'] and p['date'] < prepared['date'] for p in before['payments']):
                raise ValueError('매입일을 기존 결제일보다 늦게 변경할 수 없습니다.')
            updates = self._purchase_catalog_updates(data, prepared)
            if structural:
                old_stock = {r['product_id']: (r['q'], r['c']) for r in self.db.execute('SELECT product_id,SUM(qty_delta) q,SUM(cost_delta) c FROM stock_events WHERE document_id=? GROUP BY product_id', (identifier,)) if r['q'] or r['c']}
                new_stock = defaultdict(lambda: [0, 0])
                for line in prepared['lines']:
                    if line['tracked']:
                        new_stock[line['product_id']][0] += line['base_qty']
                        new_stock[line['product_id']][1] += line['cost']
                for line in before['lines']:
                    tracked = self.db.execute('SELECT tracked FROM products WHERE id=?', (line['product_id'],)).fetchone()[0]
                    if bool(old_stock.get(line['product_id'], (0, 0))[0]) != bool(tracked):
                        raise ValueError('입고 당시와 재고관리 설정이 다릅니다. 설정과 이력을 먼저 확인하세요.')
                affected = set(old_stock) | set(new_stock)
                self._purchase_stock_edit_check(old, affected, prepared['date'])
                for product in sorted(affected):
                    old_qty, old_cost = old_stock.get(product, (0, 0))
                    new_qty, new_cost = new_stock.get(product, (0, 0))
                    if old['date'] == prepared['date']:
                        if (new_qty, new_cost) != (old_qty, old_cost):
                            self._move(product, new_qty-old_qty, new_cost-old_cost, 'purchase_edit', reason, identifier, old['date'])
                    else:
                        if old_qty or old_cost: self._move(product, -old_qty, -old_cost, 'purchase_edit_reverse', reason, identifier, old['date'])
                        if new_qty or new_cost: self._move(product, new_qty, new_cost, 'purchase_edit', reason, identifier, prepared['date'])
                # A return in any state would have prevented this branch above.
                # Existing IDs are ordinal slots. Reusing them in their sorted
                # order keeps the visible row order aligned with entry metadata,
                # including Up/Down moves and inserting a row in the middle.
                retained = set()
                fields = columns + ('commission_bps', 'commission_amount')
                slots = sorted(originals)
                for index, line in enumerate(prepared['lines']):
                    values = tuple(line[k] for k in fields)
                    source = slots[index] if index < len(slots) else None
                    if source is not None:
                        self.db.execute('UPDATE document_lines SET '+','.join(k+'=?' for k in fields)+' WHERE id=? AND document_id=?', values+(source, identifier))
                        retained.add(source)
                    else:
                        retained.add(self.db.execute('INSERT INTO document_lines(document_id,'+','.join(fields)+') VALUES('+','.join('?' for _ in range(len(fields)+1))+')', (identifier,)+values).lastrowid)
                for old_id in set(originals)-retained:
                    self.db.execute('DELETE FROM document_lines WHERE id=?', (old_id,))
            self.db.execute('UPDATE documents SET date=?,partner_id=?,total=?,memo=? WHERE id=?',
                            (prepared['date'], prepared['partner_id'], prepared['total'], prepared['memo'], identifier))
            # The initial payment plan belongs to the old revision; actual
            # payment batches remain in payments, untouched and auditable.
            self.db.execute('INSERT OR REPLACE INTO document_entry(document_id,payload) VALUES(?,?)',
                            (identifier, json.dumps(prepared['entry'], ensure_ascii=False)))
            for change in updates:
                table = 'product_units' if change['unit_id'] else 'products'
                self.db.execute(f'UPDATE {table} SET purchase_price=?,sale_price=? WHERE id=?', (change['purchase_price'], change['sale_price'], change['unit_id'] or change['product_id']))
                self.db.execute('UPDATE products SET updated_at=? WHERE id=?', (now(), change['product_id']))
                self._audit('purchase_price_check', 'product', change['product_id'], dict(document_id=identifier, **change))
            self._audit('revise_purchase', 'document', identifier,
                        dict(original_date=self._purchase_original_date(identifier, old['date']), reason=reason,
                             before=before, after=self._purchase_revision_snapshot(identifier)))
            return identifier

    def purchase_revisions(self, identifier):
        self._require('trade'); self.require_menu('purchases')
        self._trade_row(identifier)
        rows = []
        for row in self.db.execute("SELECT a.*,u.name user_name FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.entity='document' AND a.entity_id=? AND a.action='revise_purchase' ORDER BY a.id DESC", (identifier,)):
            detail = json.loads(row['detail'])
            for snapshot in (detail['before'], detail['after']):
                for key in ('total', 'cash_paid', 'points_used'): snapshot['document'][key] = money(snapshot['document'][key])
                for line in snapshot['lines']:
                    for key in ('input_qty', 'base_qty', 'factor'): line[key] = qtext(line[key])
                    for key in ('unit_price', 'total', 'cost', 'commission_amount'): line[key] = money(line[key])
                for payment in snapshot['payments']: payment['amount'] = money(payment['amount'])
            rows.append(dict(id=row['id'], at=row['at'], user_name=row['user_name'] or '', **detail))
        return rows
