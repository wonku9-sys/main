import pytest
from PySide6.QtCore import QPoint, Qt
from test_payment_finance import shop, TODAY, register
from pos2.payment_workspace import ledger_menu
from pos2.recovery import _validate_database


def test_confirmation_mark_only_changes_audit_not_money_or_stock(shop):
    _,s,_,supplier,product,doc=shop
    register(s,supplier,dict(cash=10,dc=5),doc)
    before=s.document(doc);balance=s.ledger(supplier)['closing'];stock=s.catalog_product(product)
    entries=s.supplier_ledger(supplier,TODAY,TODAY)['entries']
    payment=next(r for r in entries if r.get('payment_id'))
    checked=s.set_supplier_ledger_checked(supplier,payment['source_type'],payment['source_id'],True,payment['confirmation_state'])
    assert checked['checked']
    assert s.document(doc)==before and s.ledger(supplier)['closing']==balance and s.catalog_product(product)==stock
    revision=s.audit_revision()
    same=s.set_supplier_ledger_checked(supplier,checked['source_type'],checked['source_id'],True,checked['confirmation_state'])
    assert same==checked and s.audit_revision()==revision
    with pytest.raises(ValueError,match='바뀌었'):
        s.set_supplier_ledger_checked(supplier,payment['source_type'],payment['source_id'],False,payment['confirmation_state'])
    s.set_supplier_ledger_checked(supplier,checked['source_type'],checked['source_id'],False,checked['confirmation_state'])
    assert not any(r.get('checked') for r in s.supplier_ledger(supplier)['entries'])
    _validate_database(s.db)


def test_settlement_confirmed_once_for_opening_and_allocated_rows(shop):
    _,s,_,supplier,_,_=shop
    register(s,supplier,dict(cash=30))
    entries=[r for r in s.supplier_ledger(supplier)['entries'] if r['kind']=='payment']
    assert len(entries)==2
    assert entries[0]['source_type']==entries[1]['source_type']=='settlement'
    assert entries[0]['source_id']==entries[1]['source_id']
    row=entries[0];s.set_supplier_ledger_checked(supplier,row['source_type'],row['source_id'],True,row['confirmation_state'])
    assert all(r['checked'] for r in s.supplier_ledger(supplier)['entries'] if r['kind']=='payment')


def test_confirmation_menu_and_daily_aggregation_no_money_write(shop):
    app,s,w,supplier,_,doc=shop;w.open_page('payments');page=w.current_page
    page.partner.setCurrentIndex(page.partner.findData(supplier));page.tabs.setCurrentIndex(1);page.refresh()
    for i in range(page.ledger_grid.rowCount()):
        row=page.ledger_grid.item(i,0).data(Qt.ItemDataRole.UserRole)
        if row.get('document_id')==doc:page.ledger_grid.selectRow(i);break
    before=s.document(doc)
    ledger_menu(page,QPoint(-1,-1));command=page._ledger_menu.actions()[0];assert command.isEnabled()
    command.trigger();page._ledger_menu.close();app.processEvents()
    assert any(page.ledger_grid.item(i,7).text()=='O' for i in range(page.ledger_grid.rowCount()))
    assert s.document(doc)==before
    page.ledger_mode.setCurrentIndex(1);page.ledger_grid.selectRow(page.ledger_grid.rowCount()-1)
    ledger_menu(page,QPoint(-1,-1));assert not page._ledger_menu.actions()[0].isEnabled();page._ledger_menu.close()
