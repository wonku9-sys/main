"""Real ledger changes from purchasing, not mock-only payment buttons."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QDialogButtonBox

from pos2.app import MainWindow
from pos2.store import Store
from pos2.workflow_ui import TradeDialog
from pos2.purchase_payment_ui import PurchasePaymentDialog

PASSWORD = 'Owner-Password-2026!'


@pytest.fixture
def shop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'direct.db')
    store.setup_admin('owner', '관리자', PASSWORD)
    supplier = store.save_partner(dict(kind='supplier', code='S01', name='공급사',
        bank='시험은행', account='000-0000', account_holder='시험예금주',
        opening_balance=1000, opening_date='2025-01-01'))
    product = store.save_product(dict(name='상품', supplier_id=supplier, purchase_price=100))
    def post(value):
        return store.post_document(dict(kind='purchase', date=date.today().isoformat(),
            partner_id=supplier, lines=[dict(product_id=product, qty='1', unit_price=value)]))
    first, second = post('500'), post('100.25')
    window = MainWindow(store)
    monkeypatch.setattr(window, 'verify_payment_entry', lambda: True)
    monkeypatch.setattr('pos2.purchase_payment_ui._confirm', lambda *_: True)
    monkeypatch.setattr('pos2.navigation.ask_unsaved', lambda *_: QMessageBox.StandardButton.Discard)
    yield app, store, window, supplier, product, first, second
    window.navigation.suspended=True
    window.navigation.disable()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()


def pay(store, identifier, components, snapshot=None, when=None):
    when = when or date.today()
    snapshot = snapshot or store.purchase_payment_context(identifier, when)
    return store.add_purchase_payments(identifier, components, when, '수기 내역', snapshot['state'])


def test_split_payment_only_pays_selected_document_and_supplier_ledger_agrees(shop):
    _, s, _, supplier, _, first, second = shop
    context=s.purchase_payment_context(second)
    assert context['cap']==Decimal('100.25') and context['balance']==Decimal('1600.25')
    cash=s.cash_expected(date.today())['expected_cash']
    result=pay(s,second,{'cash':'20.25','transfer':30,'card':50},context)
    assert result['amount']==Decimal('100.25') and len(result['payment_ids'])==3
    assert s.document(second)['balance']==0 and s.document(first)['balance']==500
    assert s.supplier_outstanding(supplier)['balance']==1500
    # Existing cashier-close totals cover sales cash only. Purchasing payments
    # remain in the supplier ledger, not silently in a cashier's cash drawer.
    assert s.cash_expected(date.today())['expected_cash']==cash
    summary=s.supplier_summary(date.today(),date.today(),partner_id=supplier)[0]
    assert summary['cash_payment']==Decimal('20.25')
    assert summary['transfer_payment']==30 and summary['card_payment']==50
    assert {r['method'] for r in s.document(second)['payments']}=={'cash','transfer','card'}
    with pytest.raises(ValueError,match='바뀌었'):
        pay(s,second,{'cash':1},context)
    assert len(s.document(second)['payments'])==3


@pytest.mark.parametrize('components', [{'cash':101}, {'cash':-1}, {'cash':'0.001'},
    {'cash':0}, {'coupon':1}, [], {'cash':'not money'}])
def test_invalid_batch_has_no_payment_or_stock_effect(shop,components):
    _,s,_,_,product,_,document=shop
    stock=s.catalog_product(product)['stock_qty']
    with pytest.raises(ValueError):pay(s,document,components)
    assert not s.document(document)['payments']
    assert s.catalog_product(product)['stock_qty']==stock


def test_failure_of_second_component_rolls_back_all_changes(shop,monkeypatch):
    _,s,_,_,_,_,document=shop
    actual=s._insert_trade_payment
    def insert(*args):
        if args[3]=='transfer':raise ValueError('injected failure')
        return actual(*args)
    monkeypatch.setattr(s,'_insert_trade_payment',insert)
    with pytest.raises(ValueError,match='injected'):
        pay(s,document,{'cash':10,'transfer':20})
    assert s.document(document)['cash_paid']==0 and not s.document(document)['payments']
    assert not s.db.execute("SELECT 1 FROM audit WHERE action='purchase_payment_batch'").fetchone()


def test_other_client_change_rejects_stale_snapshot(shop):
    _,s,_,_,_,_,document=shop
    snapshot=s.purchase_payment_context(document)
    other=Store(s.path)
    try:
        other.login('owner',PASSWORD)
        other.add_payment(document,1,date.today(),'card')
        with pytest.raises(ValueError,match='바뀌었'):pay(s,document,{'cash':1},snapshot)
    finally:other.close()
    assert s.document(document)['cash_paid']==1


def test_future_past_and_draft_contexts_are_not_payable(shop):
    _,s,_,supplier,_,_,document=shop
    with pytest.raises(ValueError,match='미래'):
        s.purchase_payment_context(document,date.today()+timedelta(days=1))
    snapshot=s.purchase_payment_context(document,date.today()-timedelta(days=1))
    assert snapshot['cap']==0
    with pytest.raises(ValueError,match='초과'):pay(s,document,{'cash':1},snapshot,snapshot['date'])
    draft=s.save_draft(dict(kind='purchase',date=date.today(),partner_id=supplier,lines=[]))
    with pytest.raises(ValueError,match='확정'):s.purchase_payment_context(draft)


def test_cash_close_blocks_mixed_batch_without_partial_transfer(shop):
    _,s,_,_,_,_,document=shop
    s.cash_close(dict(date=date.today(),opening_cash=0,counted_cash=0))
    with pytest.raises(ValueError,match='마감'):pay(s,document,{'cash':10,'card':20})
    assert not s.document(document)['payments']
    pay(s,document,{'card':20})
    assert s.document(document)['cash_paid']==20


def test_context_and_write_recheck_permissions(shop):
    _,s,_,_,_,_,document=shop
    snapshot=s.purchase_payment_context(document)
    s.save_user(dict(code='staff',name='직원',password=PASSWORD,role='staff',permissions=['catalog']))
    s.login('staff',PASSWORD)
    with pytest.raises(PermissionError):s.purchase_payment_context(document)
    with pytest.raises(PermissionError):pay(s,document,{'cash':1},snapshot)


def test_direct_dialog_shows_record_account_and_manual_card_then_saves_once(shop):
    app,s,window,_,_,_,document=shop
    dialog=PurchasePaymentDialog(window,document)
    dialog.show();app.processEvents()
    assert dialog.info['bank'].text()=='시험은행' and dialog.info['account_holder'].text()=='시험예금주'
    assert dialog.items_grid.rowCount()==1 and dialog.payments_grid.rowCount()==0
    for key,field in dialog.components.items():field.setText('10.25' if key=='card' else '0')
    dialog.save();dialog.save()
    assert dialog.result()==QDialog.DialogCode.Accepted and dialog.changed
    assert s.document(document)['cash_paid']==Decimal('10.25')
    assert len(s.document(document)['payments'])==1


def test_cancel_confirmation_does_not_disable_save_or_write(shop,monkeypatch):
    _,s,window,_,_,_,document=shop
    dialog=PurchasePaymentDialog(window,document)
    monkeypatch.setattr('pos2.purchase_payment_ui._confirm',lambda *_:False)
    dialog.save()
    assert dialog.save_button.isEnabled() and not dialog.changed
    assert not s.document(document)['payments']


def test_posted_trade_footer_opens_same_manager_and_refreshes_record(shop,monkeypatch):
    app,s,window,_,_,_,document=shop
    trade=TradeDialog(window,'purchase',s.document(document))
    assert trade.amending and trade.payment_button.isEnabled()
    called=[]
    def execute(dialog):
        called.append(dialog.document_id)
        for key,field in dialog.components.items():field.setText('12.25' if key=='card' else '0')
        dialog.save()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PurchasePaymentDialog,'exec',execute)
    trade.payment_input()
    assert called==[document] and trade.record['cash_paid']==Decimal('12.25')
    assert trade.payments_grid.item(0,3).text()=='카드 수기'
    assert trade.void_button.isHidden()


def test_purchase_list_uses_same_guarded_manager_without_changing_page(shop,monkeypatch):
    _,s,window,_,_,_,document=shop
    window.open_page('purchases')
    page=window.current_page;page.refresh()
    index=next(i for i in range(page.grid.rowCount()) if (page.grid.item(i,0).data(256) or {}).get('id')==document)
    page.grid.setCurrentCell(index,0)
    called=[]
    monkeypatch.setattr('pos2.purchase_payment_ui.open_payment',lambda owner,identifier,parent:(called.append(identifier) or False))
    page.settle()
    assert called==[document] and window.current_key=='purchases'


def test_direct_void_preserves_history_and_restores_balance(shop,monkeypatch):
    _,s,window,_,_,_,document=shop
    pay(s,document,{'card':'20.25'})
    dialog=PurchasePaymentDialog(window,document)
    dialog.tabs.setCurrentIndex(1);dialog.payments_grid.setCurrentCell(0,0)
    monkeypatch.setattr('pos2.purchase_payment_ui.QInputDialog.getText',lambda *_:('입력 정정',True))
    dialog.void_payment()
    assert dialog.changed and s.document(document)['balance']==Decimal('100.25')
    assert s.document(document)['payments'][0]['voided']


def test_direct_edit_is_atomic_and_keeps_original(shop,monkeypatch):
    _,s,window,_,_,_,document=shop
    pay(s,document,{'card':'20.25'})
    dialog=PurchasePaymentDialog(window,document)
    dialog.tabs.setCurrentIndex(1);dialog.payments_grid.setCurrentCell(0,0)
    def execute(form):
        for field in form.components.values():field.setText('0')
        form.components['card'].setText('10.25')
        form._target_explicit=False;form.recalculate()
        form.save()
        return form.result()
    monkeypatch.setattr('pos2.purchase_payment_ui.PurchasePaymentDialog.exec',execute)
    monkeypatch.setattr('pos2.purchase_payment_ui.QInputDialog.getText',lambda *_:('금액 입력 정정',True))
    dialog.edit_payment()
    result=s.document(document)
    assert dialog.changed and result['cash_paid']==Decimal('10.25')
    assert len(result['payments'])==2 and result['payments'][0]['voided']


def test_grouped_payments_cannot_be_partially_voided(shop):
    _,s,window,supplier,_,_,document=shop
    s.settle_supplier(supplier,'1600.25',date.today(),'card')
    dialog=PurchasePaymentDialog(window,document)
    dialog.tabs.setCurrentIndex(1);dialog.payments_grid.setCurrentCell(0,0)
    assert not dialog.void_button.isEnabled() and not dialog.edit_button.isEnabled()
    with pytest.raises(ValueError,match='묶음'):dialog.selected_payment()


def test_new_apis_are_in_shared_pc_contract():
    from pos2.shared_protocol import READS,WRITES
    assert 'purchase_payment_context' in READS and 'add_purchase_payments' in WRITES
