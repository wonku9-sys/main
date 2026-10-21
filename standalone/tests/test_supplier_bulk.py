from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt, QItemSelectionModel, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from pos2.store import Store
from pos2.supplier_ui import SuppliersPage


@pytest.fixture
def shop(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'suppliers.db'); store.setup_admin('owner','관리자','Owner-Password-2026!')
    ids = [store.save_partner(dict(kind='supplier',name=f'공급사 {i}',opening_balance=100+i)) for i in range(4)]
    yield app, store, ids
    for widget in app.topLevelWidgets():
        widget.close(); widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_bulk_status_deduplicated_preserves_financials_and_audits(shop):
    _,store,ids=shop
    before=store.partners('supplier')
    assert store.set_suppliers_active([ids[0],ids[2],ids[0]],False)==2
    after=store.partners('supplier')
    assert [p['active'] for p in after]==[0,1,0,1]
    assert [p['balance'] for p in after]==[p['balance'] for p in before]
    assert store.set_suppliers_active([ids[0],ids[2]],False)==0
    assert store.set_suppliers_active([ids[2]],True)==1
    assert len([r for r in store.audit_log() if r['entity']=='partner' and r['action']=='update'])==3


def test_invalid_mixed_selection_rolls_back_all_and_rejects_bad_input(shop):
    _,store,ids=shop
    customer=store.save_partner(dict(kind='customer',name='판매처'))
    for selection in ([ids[0],customer],[ids[0],99999],[True],[],['1']):
        with pytest.raises(ValueError):store.set_suppliers_active(selection,False)
    assert all(r['active'] for r in store.partners('supplier'))
    with pytest.raises(ValueError):store.set_suppliers_active(ids,1)


def test_payment_method_batch_and_live_edit_denial(shop):
    _,store,ids=shop
    assert store.set_supplier_payment_method(ids[:2],'transfer')==2
    assert [p['settlement_method'] for p in store.partners('supplier')]==['transfer','transfer','cash','cash']
    with pytest.raises(ValueError):store.set_supplier_payment_method([ids[2],99999],'transfer')
    assert store.partners('supplier')[2]['settlement_method']=='cash'
    with pytest.raises(ValueError):store.set_supplier_payment_method(ids,'card')
    store.save_user(dict(code='staff',name='직원',password='Staff-Password-2026!',role='staff',permissions=['catalog','deny:suppliers.edit']))
    store.login('staff','Staff-Password-2026!')
    with pytest.raises(PermissionError):store.set_suppliers_active(ids,False)
    with pytest.raises(PermissionError):store.set_supplier_payment_method(ids,'cash')


def test_context_menu_operates_on_arbitrary_selected_rows(shop,monkeypatch):
    app,store,ids=shop
    page=SuppliersPage(SimpleNamespace(store=store,notify=lambda *_:None))
    page.grid.sortItems(0,Qt.SortOrder.AscendingOrder)
    page.grid.selectRow(0)
    page.grid.selectionModel().select(page.grid.model().index(2,0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
    assert {r['id'] for r in page.selected_suppliers()}=={ids[0],ids[2]}
    menu=page.make_context_menu();actions={a.text():a for a in menu.actions()}
    actions['사람/연락처 보기'].trigger();assert all(page.grid.isColumnHidden(c) for c in (4,5,6,7,8))
    actions['계좌정보 보기'].trigger();assert page.grid.isColumnHidden(12)
    actions['줄여보기'].trigger();assert page.grid.verticalHeader().defaultSectionSize()==25
    monkeypatch.setattr('pos2.supplier_ui.confirm',lambda *_:True)
    actions['선택 공급사 무효'].trigger()
    assert [r['active'] for r in store.partners('supplier')]==[0,1,0,1]
    assert page.grid.rowCount()==2
    page.status.setCurrentIndex(page.status.findData(False));assert page.grid.rowCount()==2
