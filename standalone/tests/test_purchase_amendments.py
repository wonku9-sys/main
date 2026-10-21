"""PDF p.15: revision window, retained zero voucher and atomic ledger changes."""
from datetime import date, timedelta
from decimal import Decimal
import json
import pytest
from pos2.store import Store
from pos2.purchase_amendments import three_month_cutoff
from pos2.recovery import _validate_database

TODAY = date.today().isoformat()


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path/'revision.db'); store.setup_admin('owner', '관리자', 'Revision-Strong-2026!')
    supplier = store.save_partner(dict(kind='supplier', name='공급사'))
    product = store.save_product(dict(name='수정 상품', base_unit='개', purchase_price=10, sale_price=20, supplier_id=supplier))
    document = store.post_document(dict(kind='purchase', date=TODAY, partner_id=supplier,
                                       lines=[dict(product_id=product, qty=10, unit_price=10)]))
    yield store, supplier, product, document
    store.close()


def payload(store, identifier):
    record = store.document(identifier)
    return dict(kind='purchase', date=record['date'], partner_id=record['partner_id'], paid=0,
                memo=record['memo'], rounding_mode=record['rounding_mode'],
                entry_datetime=record['entry'].get('datetime', record['date']+' 00:00:00'),
                entry_staff=record['entry'].get('staff', '관리자'), _expected_token=record['_edit_token'],
                lines=[dict(line_id=line['id'], product_id=line['product_id'], unit_id=line['unit_id'],
                            qty=line['input_qty'], factor_override=line['factor'], unit_price=line['unit_price'],
                            line_memo=line.get('entry', {}).get('memo', ''),
                            sale_price=line.get('entry', {}).get('sale_price', '0')) for line in record['lines']])


def save(store, identifier, data):
    return store.revise_purchase(identifier, data, store.purchase_edit_context(identifier)['state'], '입고 수량 재확인')


def stock(store, product):
    record = store.catalog_product(product)
    return record['stock_qty'], record['stock_cost']


@pytest.mark.parametrize('today,expected', [(date(2026, 5, 31), '2026-02-28'), (date(2024, 5, 31), '2024-02-29'),
                                           (date(2026, 1, 31), '2025-10-31'), (date(2026, 10, 21), '2026-07-21')])
def test_calendar_month_boundary(today, expected):
    assert three_month_cutoff(today) == expected


def test_quantity_price_revision_retains_identity_and_full_before_after(shop):
    s, supplier, product, identifier = shop; before = s.document(identifier)
    data = payload(s, identifier); data['lines'][0].update(qty='12.5', unit_price='12.34')
    save(s, identifier, data)
    after = s.document(identifier)
    assert (after['id'], after['number'], after['created_at'], after['user_id'], after['status']) == (before['id'], before['number'], before['created_at'], before['user_id'], 'posted')
    assert after['lines'][0]['id'] == before['lines'][0]['id']
    assert after['total'] == Decimal('154.25') and after['balance'] == Decimal('154.25')
    assert stock(s, product) == ('12.500', Decimal('154.25'))
    history = s.purchase_revisions(identifier)
    assert len(history) == 1 and history[0]['before']['document']['total'] == 100
    assert history[0]['after']['document']['total'] == Decimal('154.25')
    assert history[0]['before']['lines'][0]['input_qty'] == '10.000'
    assert s.ledger(supplier)['closing'] == Decimal('154.25')
    movement = s.inventory_assets(TODAY, TODAY)['rows'][0]
    assert movement['purchase_qty'] == '12.500' and movement['adjustment_qty'] == '0.000'
    _validate_database(s.db)


def test_zero_line_voucher_keeps_number_and_can_be_filled_again(shop):
    s, supplier, product, identifier = shop; original = s.document(identifier)
    data = payload(s, identifier); data['lines'] = []; save(s, identifier, data)
    empty = s.document(identifier)
    assert empty['status'] == 'posted' and empty['number'] == original['number']
    assert empty['lines'] == [] and empty['total'] == empty['balance'] == 0
    assert stock(s, product) == ('0.000', 0) and s.ledger(supplier)['closing'] == 0
    data = payload(s, identifier); data['lines'] = [dict(product_id=product, qty=2, unit_price=15)]
    save(s, identifier, data)
    assert s.document(identifier)['total'] == 30 and stock(s, product) == ('2.000', 30)
    assert len(s.purchase_revisions(identifier)) == 2
    _validate_database(s.db)


def test_partial_payment_preserved_and_overpayment_rejected(shop):
    s, _, product, identifier = shop
    s.add_payment(identifier, 60, TODAY, 'card', '수기 카드')
    payments = s.document(identifier)['payments']
    data = payload(s, identifier); data['lines'][0]['qty'] = '8'
    save(s, identifier, data)
    assert s.document(identifier)['balance'] == 20 and s.document(identifier)['payments'] == payments
    before = s.document(identifier); inventory = stock(s, product); audit = s.audit_revision()
    data = payload(s, identifier); data['lines'][0]['qty'] = '5'
    with pytest.raises(ValueError, match='기존 지급'): save(s, identifier, data)
    assert s.document(identifier) == before and stock(s, product) == inventory and s.audit_revision() == audit


def test_stale_payment_even_after_void_and_unchanged_total_is_detected(shop):
    s, _, _, identifier = shop; data = payload(s, identifier); context = s.purchase_edit_context(identifier)
    pay = s.add_payment(identifier, 1, TODAY, 'transfer'); s.void_payment(pay, '취소')
    with pytest.raises(ValueError, match='다른 작업'): s.revise_purchase(identifier, data, context['state'], '충돌')
    assert not s.purchase_revisions(identifier)


def test_later_sale_blocks_stock_revision_but_memo_keeps_cost_and_line_ids(shop):
    s, _, product, identifier = shop
    customer = s.save_partner(dict(kind='customer', name='판매처'))
    sale = s.post_document(dict(kind='sale', date=TODAY, partner_id=customer, lines=[dict(product_id=product, qty=1, unit_price=20)]))
    costs = s.document(sale)['lines']; original = s.document(identifier); inventory = stock(s, product)
    context = s.purchase_edit_context(identifier)
    assert context['allowed'] and not context['stock_editable']
    data = payload(s, identifier); data['lines'][0]['qty'] = '11'
    with pytest.raises(ValueError, match='이후 판매'): save(s, identifier, data)
    data = payload(s, identifier); data.update(memo='입고 담당 확인', entry_staff='수정 담당')
    save(s, identifier, data)
    assert s.document(identifier)['memo'] == '입고 담당 확인'
    assert s.document(identifier)['lines'][0]['id'] == original['lines'][0]['id']
    assert stock(s, product) == inventory and s.document(sale)['lines'] == costs


@pytest.mark.parametrize('posted', [False, True])
def test_return_references_in_any_state_keep_original_rows(shop, posted):
    s, supplier, product, identifier = shop; original = s.document(identifier)
    returned = dict(kind='purchase_return', date=TODAY, partner_id=supplier, source_id=identifier,
                    lines=[dict(product_id=product, qty=1, source_line_id=original['lines'][0]['id'])])
    return_id = s.post_document(returned) if posted else s.save_draft(returned)
    assert not s.purchase_edit_context(identifier)['stock_editable']
    data = payload(s, identifier); data['lines'] = []
    with pytest.raises(ValueError, match='연결된 반품'): save(s, identifier, data)
    data = payload(s, identifier); data['memo'] = '반품 이력 보존'; save(s, identifier, data)
    assert s.document(return_id)['lines'][0]['source_line_id'] == original['lines'][0]['id']
    _validate_database(s.db)


def test_date_shift_preserves_period_stock_totals_and_active_payment_date(shop):
    s, _, product, identifier = shop
    yesterday = (date.today()-timedelta(days=1)).isoformat()
    data = payload(s, identifier); data.update(date=yesterday, entry_datetime=yesterday+' 10:35:00')
    save(s, identifier, data)
    assert s.document(identifier)['date'] == yesterday and stock(s, product) == ('10.000', 100)
    assert s.db.execute('SELECT SUM(qty_delta) FROM stock_events WHERE product_id=? AND date=?', (product, TODAY)).fetchone()[0] == 0
    assert s.db.execute('SELECT SUM(qty_delta) FROM stock_events WHERE product_id=? AND date=?', (product, yesterday)).fetchone()[0] == 10000
    assert s.inventory_assets(TODAY, TODAY)['rows'][0]['purchase_qty'] == '0.000'
    assert s.inventory_assets(yesterday, yesterday)['rows'][0]['purchase_qty'] == '10.000'
    s.add_payment(identifier, 1, yesterday, 'transfer')
    data = payload(s, identifier); data.update(date=TODAY, entry_datetime=TODAY+' 10:00:00')
    with pytest.raises(ValueError, match='결제일보다'): save(s, identifier, data)


def test_cutoff_original_day_cannot_be_extended_by_date_edit(shop):
    s, supplier, product, _ = shop; boundary = three_month_cutoff()
    old = s.post_document(dict(kind='purchase', date=boundary, partner_id=supplier, lines=[dict(product_id=product, qty=1, unit_price=1)]))
    assert s.purchase_edit_context(old)['allowed']
    expired = (date.fromisoformat(boundary)-timedelta(days=1)).isoformat()
    identifier = s.post_document(dict(kind='purchase', date=expired, partner_id=supplier, lines=[dict(product_id=product, qty=1, unit_price=1)]))
    assert not s.purchase_edit_context(identifier)['allowed']
    with pytest.raises(ValueError, match='3개월'): save(s, identifier, payload(s, identifier))


def test_mid_stock_failure_rolls_back_all_changes_and_audit(shop, monkeypatch):
    s, _, product, identifier = shop
    second = s.save_product(dict(name='두 번째 상품', base_unit='개'))
    data = payload(s, identifier); data['lines'][0]['qty'] = '12'
    data['lines'].append(dict(product_id=second, qty=1, unit_price=9))
    original = s.document(identifier); before = stock(s, product); revision = s.audit_revision(); move = s._move
    def fail(product_id, *args):
        if product_id == second: raise ValueError('재고 기록 실패 주입')
        return move(product_id, *args)
    monkeypatch.setattr(s, '_move', fail)
    with pytest.raises(ValueError, match='실패 주입'): save(s, identifier, data)
    assert s.document(identifier) == original and stock(s, product) == before
    assert s.audit_revision() == revision and not s.purchase_revisions(identifier)


def test_reason_payment_replay_duplicate_rows_and_bad_types_rejected(shop):
    s, _, _, identifier = shop; data = payload(s, identifier); context = s.purchase_edit_context(identifier)
    with pytest.raises(ValueError, match='수정 사유'): s.revise_purchase(identifier, data, context['state'], '')
    data['paid'] = 1
    with pytest.raises(ValueError, match='다시 등록'): save(s, identifier, data)
    data['paid'] = 0; data['lines'] *= 2
    with pytest.raises(ValueError, match='원래 품목'): save(s, identifier, data)
    data = payload(s, identifier); data['lines'][0]['line_id'] = 100000
    with pytest.raises(ValueError, match='원래 품목'): save(s, identifier, data)


def test_supplier_change_with_voided_payment_history_is_rejected(shop):
    s, _, _, identifier = shop; other = s.save_partner(dict(kind='supplier', name='다른 공급사'))
    p = s.add_payment(identifier, 1, TODAY); s.void_payment(p, '취소')
    data = payload(s, identifier); data['partner_id'] = other
    with pytest.raises(ValueError, match='공급사를 변경'): save(s, identifier, data)


def test_gram_quantity_exact_amount_and_tax_supplier_snapshots(shop):
    s, supplier, _, _ = shop
    product = s.save_product(dict(name='그램 상품', base_unit='g', price_basis=100, tax_mode='taxable', supplier_id=supplier))
    identifier = s.post_document(dict(kind='purchase', date=TODAY, partner_id=supplier,
                                      lines=[dict(product_id=product, qty=1000, unit_price='10.25')]))
    s.save_product(dict(name='바뀐 상품명', tax_mode='exempt'), product)
    data = payload(s, identifier); data['lines'][0].update(qty='2000', unit_price='10.25')
    save(s, identifier, data)
    line = s.document(identifier)['lines'][0]
    assert line['tax_mode'] == 'taxable' and line['product_name'] == '그램 상품'
    assert stock(s, product) == ('2000.000', Decimal('205.00'))
    unit = s.save_unit(dict(product_id=product, name='봉', factor='2', purchase_price=20, sale_price=40))
    data = payload(s, identifier); data['lines'][0].update(unit_id=unit, factor_override=2, qty=5, unit_price=20)
    save(s, identifier, data)
    line = s.document(identifier)['lines'][0]
    assert line['tax_mode'] == 'taxable' and line['product_name'] == '그램 상품'
    assert line['price_basis'] == 1 and line['unit_id'] == unit and line['total'] == 100
    _validate_database(s.db)


def test_reordered_and_inserted_lines_keep_saved_metadata_aligned(shop):
    s, _, product, identifier = shop
    second = s.save_product(dict(name='두 번째', base_unit='개'))
    data = payload(s, identifier)
    data['lines'][0]['line_memo'] = '첫 상품 메모'
    data['lines'].append(dict(product_id=second, qty=2, unit_price=20, line_memo='둘째 메모'))
    save(s, identifier, data)
    data = payload(s, identifier); data['lines'].reverse(); save(s, identifier, data)
    record = s.document(identifier)
    assert [r['product_id'] for r in record['lines']] == [second, product]
    assert [r['entry']['memo'] for r in record['lines']] == ['둘째 메모', '첫 상품 메모']
    third = s.save_product(dict(name='중간 추가', base_unit='개'))
    data = payload(s, identifier)
    data['lines'].insert(1, dict(product_id=third, qty=3, unit_price=30, line_memo='중간 메모'))
    save(s, identifier, data)
    record = s.document(identifier)
    assert [r['product_id'] for r in record['lines']] == [second, third, product]
    assert [r['entry']['memo'] for r in record['lines']] == ['둘째 메모', '중간 메모', '첫 상품 메모']
    _validate_database(s.db)


def test_permission_revocation_rechecked_at_save(shop):
    s, _, _, identifier = shop
    uid = s.save_user(dict(code='staff', name='직원', role='staff', password='Staff-Strong-2026!', permissions=['trade']))
    staff = Store(s.path)
    try:
        staff.login('staff', 'Staff-Strong-2026!'); data = payload(staff, identifier)
        context = staff.purchase_edit_context(identifier)
        assert context['allowed']
        s.save_user(dict(code='staff', name='직원', role='staff', permissions=['trade', 'deny:purchases.edit']), uid)
        with pytest.raises(PermissionError): staff.revise_purchase(identifier, data, context['state'], '권한 재검사')
        assert not s.purchase_revisions(identifier)
    finally: staff.close()


def test_month_close_blocks_revision_and_old_snapshot(shop):
    s, supplier, _, _ = shop
    last = date.today().replace(day=1)-timedelta(days=1)
    product = s.save_product(dict(name='마감 상품', base_unit='개'))
    identifier = s.post_document(dict(kind='purchase', date=last.isoformat(), partner_id=supplier,
                                      lines=[dict(product_id=product, qty=1, unit_price=10)]))
    context = s.purchase_edit_context(identifier); data = payload(s, identifier)
    assert context['allowed']
    s.inventory_close(last.strftime('%Y-%m'))
    assert not s.purchase_edit_context(identifier)['allowed']
    with pytest.raises(ValueError, match='월 재고마감'):
        s.revise_purchase(identifier, data, context['state'], '마감 후 수정 차단')


def test_original_revision_date_window_survives_date_change(shop, monkeypatch):
    s, supplier, _, _ = shop
    product = s.save_product(dict(name='기간 경계 상품', base_unit='개'))
    identifier = s.post_document(dict(kind='purchase', date=three_month_cutoff(), partner_id=supplier,
                                      lines=[dict(product_id=product, qty=1, unit_price=1)]))
    data = payload(s, identifier); data.update(date=TODAY, entry_datetime=TODAY+' 09:00:00')
    save(s, identifier, data)
    assert s.document(identifier)['date'] == TODAY
    actual = date.today()
    class NextDay(date):
        @classmethod
        def today(cls): return actual+timedelta(days=1)
    monkeypatch.setattr('pos2.purchase_amendments.date', NextDay)
    assert not s.purchase_edit_context(identifier)['allowed']


def test_switching_kg_gram_input_preserves_the_new_explicit_basis(shop):
    s, supplier, _, _ = shop
    product = s.save_product(dict(name='kg 상품', base_unit='kg'))
    identifier = s.post_document(dict(kind='purchase', date=TODAY, partner_id=supplier,
                                      lines=[dict(product_id=product, qty=1000, unit_price=10, gram_input=True)]))
    data = payload(s, identifier); data['lines'][0].update(qty=2, unit_price=20, factor_override=1, gram_input=False)
    save(s, identifier, data)
    line = s.document(identifier)['lines'][0]
    assert line['price_basis'] == 1 and line['unit_name'] == 'kg' and line['total'] == 40
    assert stock(s, product) == ('2.000', 40)


def test_new_item_stale_base_unit_or_price_basis_is_rejected(shop):
    s, _, _, identifier = shop
    product = s.save_product(dict(name='새 품목', base_unit='g', price_basis=100))
    data = payload(s, identifier)
    data['lines'].append(dict(product_id=product, qty=1000, unit_price=10, expected_price_basis=1, expected_base_unit='g'))
    with pytest.raises(ValueError, match='단가 기준'): save(s, identifier, data)
    data['lines'][-1].update(expected_price_basis=100, expected_base_unit='kg')
    with pytest.raises(ValueError, match='기본단위'): save(s, identifier, data)
    assert stock(s, product) == ('0.000', 0) and not s.purchase_revisions(identifier)


def test_editor_identity_preserved_after_staff_removal(shop):
    s, _, _, identifier = shop
    uid = s.save_user(dict(code='editor', name='수정 담당', role='staff', password='Editor-Strong-2026!', permissions=['trade']))
    data = payload(s, identifier); data['memo'] = '품목 유지·메모 수정'
    other = Store(s.path)
    try:
        other.login('editor', 'Editor-Strong-2026!'); save(other, identifier, data)
    finally: other.close()
    s.delete_user(uid)
    history = s.purchase_revisions(identifier)[0]
    assert history['user_name'] == '수정 담당' and history['editor_code'] == 'editor'
