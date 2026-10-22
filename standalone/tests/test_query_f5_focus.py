"""Physical F5 must follow the visible query button from every purchase control."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest,QSignalSpy

from test_menu_shortcuts import desktop


@pytest.mark.parametrize('focus',['window','button','search','start','end','supplier','status','grid','tree'])
def test_purchase_f5_from_each_focus_runs_same_query_once(desktop,monkeypatch,focus):
    app,store,window=desktop;window.open_page('purchases');page=window.current_page
    called=[];monkeypatch.setattr(page,'refresh',lambda:called.append('query'))
    field={'window':window,'button':page.header.query_button,'search':page.search,
           'start':page.start,'end':page.end,'supplier':page.partner_filter,
           'status':page.status,'grid':page.grid,'tree':window.tree}[focus]
    window.activateWindow();field.setFocus();app.processEvents()
    QTest.keyClick(field,Qt.Key.Key_F5);app.processEvents()
    assert called==['query'],(focus,called,app.focusWidget())
    page.header.query_button.click()
    assert called==['query','query']


def test_f5_in_visible_purchase_page_does_not_refresh_last_active_popup(desktop,monkeypatch):
    app,_,window=desktop
    window.open_page('purchases');purchase=window.current_page
    window.popup_menus=True;window.open_page('products');popup=window.popup_windows['products']
    app.processEvents();called=[]
    monkeypatch.setattr(purchase,'refresh',lambda:called.append('purchases'))
    monkeypatch.setattr(popup.page,'refresh',lambda:called.append('products'))
    window.activateWindow();purchase.grid.setFocus();app.processEvents()
    assert window.stack.currentWidget() is window.page_surfaces['purchases']
    QTest.keyClick(purchase.grid,Qt.Key.Key_F5);app.processEvents()
    assert called==['purchases']
    popup.activateWindow();popup.page.search.setFocus();app.processEvents()
    QTest.keyClick(popup.page.search,Qt.Key.Key_F5);app.processEvents()
    assert called==['purchases','products']


def test_f5_really_reloads_new_purchase_and_emits_one_button_click_without_writing(desktop):
    from datetime import date
    app,store,window=desktop
    supplier=store.save_partner(dict(kind='supplier',name='조회 검사 공급사'))
    product=store.save_product(dict(name='조회 검사 상품',base_unit='개',tracked=False))
    window.open_page('purchases');page=window.current_page
    assert page.grid.rowCount()==0
    identifier=store.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,
        lines=[dict(product_id=product,qty=2,unit_price='1000.25')]))
    before=store.audit_revision(),store.document(identifier)
    spy=QSignalSpy(page.header.query_button.clicked)
    page.grid.setFocus();app.processEvents();QTest.keyClick(page.grid,Qt.Key.Key_F5);app.processEvents()
    assert spy.count()==1
    assert any(page.grid.item(row,0).data(Qt.ItemDataRole.UserRole).get('id')==identifier
        for row in range(page.grid.rowCount()) if page.grid.item(row,0).data(Qt.ItemDataRole.UserRole))
    assert (store.audit_revision(),store.document(identifier))==before


def test_f5_keeps_unsaved_settings_when_user_cancels_reload(desktop,monkeypatch):
    app,_,window=desktop;window.open_page('settings');page=window.current_page
    page.fields['store_name'].setText('저장하지 않은 점포명')
    called=[];monkeypatch.setattr(page,'refresh',lambda:called.append('discarded'))
    page.fields['store_name'].setFocus();app.processEvents()
    QTest.keyClick(page.fields['store_name'],Qt.Key.Key_F5);app.processEvents()
    assert not called and page.fields['store_name'].text()=='저장하지 않은 점포명'


def test_modal_purchase_f5_still_searches_products_not_background_list(desktop,monkeypatch):
    from pos2.workflow_ui import TradeDialog
    app,_,window=desktop;window.open_page('purchases');called=[]
    monkeypatch.setattr(window.current_page,'refresh',lambda:called.append('background'))
    monkeypatch.setattr(TradeDialog,'pick_product',lambda self:called.append('product-search'))
    dialog=TradeDialog(window,'purchase');dialog.setModal(True);dialog.show();dialog.activateWindow();app.processEvents()
    field=dialog.line_rows[0]['qty'];field.setFocus();QTest.keyClick(field,Qt.Key.Key_F5);app.processEvents()
    assert called==['product-search']
    dialog.reject()


def test_nested_product_picker_f5_keeps_its_own_search(desktop,monkeypatch):
    from pos2.workflow_ui import TradeDialog,ProductPicker
    app,_,window=desktop;window.open_page('purchases');called=[]
    monkeypatch.setattr(window.current_page,'refresh',lambda:called.append('background'))
    monkeypatch.setattr(ProductPicker,'search_now',lambda self:called.append('picker-search'))
    trade=TradeDialog(window,'purchase');trade.setModal(True);trade.show();app.processEvents()
    picker=ProductPicker(trade);picker.setModal(True);picker.show();picker.activateWindow();app.processEvents()
    picker.search.setFocus();QTest.keyClick(picker.search,Qt.Key.Key_F5);app.processEvents()
    assert called==['picker-search']
    picker.reject();trade.reject()


@pytest.mark.parametrize('state',['hidden','disabled'])
def test_f5_does_not_bypass_hidden_or_disabled_query_button(desktop,monkeypatch,state):
    app,_,window=desktop;window.open_page('purchases');page=window.current_page;called=[]
    monkeypatch.setattr(page,'refresh',lambda:called.append('query'))
    if state=='hidden':page.header.query_button.hide()
    else:page.header.query_button.setEnabled(False)
    page.grid.setFocus();app.processEvents();QTest.keyClick(page.grid,Qt.Key.Key_F5);app.processEvents()
    assert not called


def test_cached_business_pages_do_not_compete_for_f5(desktop,monkeypatch):
    app,_,window=desktop;called=[]
    monkeypatch.setattr(window,'verify_payment_entry',lambda:True)
    for key in ('products','purchases','suppliers','purchase_suppliers','purchase_categories',
                'purchase_products','purchase_documents','sales','inventory','reports','members',
                'settings','store_profile','payments','purchases'):
        assert window.open_page(key)
        page=window.current_page
        monkeypatch.setattr(page,'refresh',lambda key=key:called.append(key))
        host=window.popup_windows.get(key,window)
        called.clear();host.activateWindow();page.header.query_button.setFocus();app.processEvents()
        QTest.keyClick(page.header.query_button,Qt.Key.Key_F5);app.processEvents()
        assert called==[key],(key,called)
