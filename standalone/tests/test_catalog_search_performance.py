"""Bounded widgets, coalesced typing and complete cached catalog results."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt,QCoreApplication,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pos2.store import Store
from pos2.catalog_ui import ProductsPage


@pytest.fixture
def catalog(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'large.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    with store._tx():
        store.db.executemany("INSERT INTO products(code,name,barcode,category,category_mid,category_small,created_at,updated_at) VALUES(?,?,?,'미분류','미분류','신상품','2026-10-20','2026-10-20')",[(f'S{i:06d}',f'합성 상품 {i:06d}',f'880{i:010d}') for i in range(1201)])
    page=ProductsPage(SimpleNamespace(store=store,notify=lambda *_:None));page.show();app.processEvents()
    yield app,store,page
    page.search_timer.stop();page.close();page.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_bounded_page_global_sort_absolute_numbers_and_complete_export(catalog,monkeypatch):
    _,_,page=catalog
    assert len(page._catalog_matches)==1201 and page.grid.rowCount()==500
    page.grid.sortItems(0,Qt.SortOrder.DescendingOrder)
    assert page.grid.item(0,0).text()=='S001200'
    page.move_catalog_page(1);assert page.grid.item(0,0).text()=='S000700'
    assert page.grid.verticalHeaderItem(0).text()=='501'
    page.move_catalog_page(1);assert page.grid.rowCount()==201 and not page.next_page.isEnabled()
    captured=[];monkeypatch.setattr('pos2.widgets.export_rows',lambda *args,**kwargs:captured.append(args[3]))
    page.export();assert len(captured[0])==1201 and captured[0][0][0]=='S001200'
    assert '1,201' in page.summary.text()


def test_typing_is_coalesced_and_unchanged_catalog_not_reloaded(catalog,monkeypatch):
    app,store,page=catalog;calls=[];original=page.refresh
    def refresh(*args):calls.append(True);return original(*args)
    monkeypatch.setattr(page,'refresh',refresh)
    def forbidden(*args,**kwargs):pytest.fail('Typing reloaded unchanged catalog metadata')
    monkeypatch.setattr(store,'products',forbidden);monkeypatch.setattr(store,'categories',forbidden);monkeypatch.setattr(store,'partners',forbidden)
    page.search.setFocus();QTest.keyClicks(page.search,'S001200')
    assert not calls and page.grid.rowCount()==500
    QTest.qWait(400);app.processEvents()
    assert len(calls)==1 and page.grid.rowCount()==1 and page.grid.item(0,0).text()=='S001200'


def test_committed_change_invalidates_cache_and_maintains_search(catalog):
    _,store,page=catalog
    page.search.setText('새로 등록된 검색품');page.refresh();assert page.grid.rowCount()==0
    product=store.save_product(dict(name='새로 등록된 검색품',barcode='000001111111'))
    page.refresh();assert page.grid.rowCount()==1 and page.grid.item(0,0).data(Qt.ItemDataRole.UserRole)['id']==product


def test_expanded_barcode_in_cache_and_matching_edit_tokens(catalog):
    _,store,page=catalog
    product=store.products()[0];identifier=product['id']
    assert product['_edit_token']==store._edit_snapshot('products',identifier)
    store.save_unit(dict(product_id=identifier,name='확장팩',barcode='000009999999',factor='2'))
    page.search.setText('000009999999');page.refresh()
    assert page.grid.rowCount()==1 and page.grid.item(0,0).data(Qt.ItemDataRole.UserRole)['id']==identifier
    statements=[];store.db.set_trace_callback(statements.append)
    try:records=store.products()
    finally:store.db.set_trace_callback(None)
    assert len(records)==1201
    assert sum(s.lstrip().upper().startswith('SELECT') for s in statements)<15
    assert next(r for r in records if r['id']==identifier)['_edit_token']==store._edit_snapshot('products',identifier)
