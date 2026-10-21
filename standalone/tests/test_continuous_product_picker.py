from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from pos2.app import MainWindow
from pos2.store import Store
from pos2.workflow_ui import TradeDialog, ProductPicker
from pos2.offline_ui import SalesFormDialog
from pos2.loyalty_ui import PromotionDialog
from pos2.popup_policy import install_popup_policy


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    store=Store(tmp_path/'continuous.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    supplier=store.save_partner({'kind':'supplier','name':'공급사'})
    store.save_partner({'kind':'customer','name':'판매처'})
    products=[store.save_product({'name':name,'barcode':str(index),'supplier_id':supplier,'base_unit':'개','sale_price':'100'}) for index,name in enumerate(('사과','배','귤'),1)]
    window=MainWindow(store);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    monkeypatch.setattr('pos2.workflow_ui._warn',lambda *_:None)
    yield app,store,window,products
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


@pytest.mark.parametrize('kind',['purchase','sale'])
def test_continuous_multi_search_and_single_keep_window_no_posting(desktop,kind):
    app,store,window,ids=desktop
    trade=TradeDialog(window,kind);trade.show();app.processEvents()
    picker=ProductPicker(trade);picker.set_apply_callback(trade.apply_picked_products);picker.show();app.processEvents()
    picker.keep_open.setChecked(True)
    picker.search.setText('사과');picker.check_all(True)
    picker.search.setText('배');picker.check_all(True)
    assert len(picker.checked)==2 and '확인' in picker.apply_checked_button.text()
    picker.apply_checked_button.click();app.processEvents()
    assert picker.isVisible() and picker.applied_batches==1 and not picker.checked
    assert {r['product'].currentData() for r in trade.line_rows}==set(ids[:2])
    picker.search.setText('귤');picker.grid.setFocus();QTest.keyClick(picker.grid,Qt.Key.Key_Space);app.processEvents()
    assert picker.isVisible() and picker.applied_batches==2
    assert {r['product'].currentData() for r in trade.line_rows}==set(ids)
    assert store.documents()==[] and all(float(row['stock_qty'])==0 for row in store.products())
    picker.keep_open.setChecked(False);picker.search.setText('사과');picker.choose()
    assert not picker.isVisible()


def test_quotation_and_promotion_share_batch_picker_without_financial_posting(desktop):
    app,store,window,ids=desktop
    quote=SalesFormDialog(window,'quotations');quote.show();app.processEvents()
    picker=ProductPicker(quote);picker.set_apply_callback(quote.apply_picked_products)
    picker.keep_open.setChecked(True)
    picker.show();picker.check_all(True);picker.apply_checked();app.processEvents()
    assert set(ids)<={r['product'].currentData() for r in quote.rows} and picker.isVisible()
    promo=PromotionDialog(store,parent=window);promo.show();app.processEvents()
    pick=ProductPicker(promo,product_loader=store.loyalty_products,read_permissions=('loyalty',))
    pick.set_apply_callback(promo.apply_picked_products);pick.show();pick.check_all(True);pick.apply_checked();app.processEvents()
    assert {promo.lines.cellWidget(r,0).currentData() for r in range(promo.lines.rowCount())}==set(ids)
    assert store.documents()==[]


def test_failed_or_stale_batch_keeps_selection_and_does_not_apply(desktop):
    app,store,window,ids=desktop;trade=TradeDialog(window);calls=[]
    picker=ProductPicker(trade);picker.set_apply_callback(calls.append);picker.show();app.processEvents()
    picker.check_all(True);store.save_product({'active':False},ids[0]);picker.apply_checked()
    assert not calls and len(picker.checked)==3 and picker.isVisible() and picker.applied_batches==0


def test_four_check_controls_sort_filter_and_function_keys(desktop):
    app,store,window,ids=desktop;picker=ProductPicker(TradeDialog(window));picker.show();app.processEvents()
    picker.grid.sortItems(2,Qt.SortOrder.DescendingOrder);picker.grid.selectRow(0)
    selected=picker.grid.selected()['id'];picker.check_row_button.click();assert set(picker.checked)=={selected}
    picker.uncheck_row_button.click();assert not picker.checked
    picker.activateWindow();app.processEvents();QTest.keyClick(picker,Qt.Key.Key_F8);assert set(picker.checked)=={selected}
    QTest.keyClick(picker,Qt.Key.Key_F9);assert not picker.checked
    picker.search.setText('사과');picker.check_all_button.click();assert set(picker.checked)=={ids[0]}
    picker.search.setText('배');picker.check_all_button.click();assert set(picker.checked)==set(ids[:2])
    picker.uncheck_all_button.click();assert not picker.checked


def test_dedicated_close_only_closes_popup_and_respects_unsaved_cancel(desktop,monkeypatch):
    app,store,window,ids=desktop
    trade=TradeDialog(window);trade.show();app.processEvents()
    picker=ProductPicker(trade);picker.show();app.processEvents()
    assert not hasattr(picker,'_popup_close_button')
    picker.close();app.processEvents()
    assert not picker.isVisible() and trade.isVisible() and window.isVisible()
    trade.scan_barcode('1')
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Cancel)
    trade.close();app.processEvents();assert trade.isVisible() and store.documents()==[]
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    trade.activateWindow();app.processEvents();QTest.keySequence(trade,QKeySequence('Ctrl+W'));app.processEvents()
    assert not trade.isVisible() and window.isVisible() and store.documents()==[]


def test_loyalty_only_staff_can_search_and_apply_promotion_products(desktop):
    app,store,window,ids=desktop
    store.save_user({'code':'staff','name':'특매 담당','password':'Staff-Password-2026!','permissions':['loyalty']})
    store.login('staff','Staff-Password-2026!')
    promo=PromotionDialog(store,parent=window)
    picker=ProductPicker(promo,product_loader=store.loyalty_products,read_permissions=('loyalty',))
    picker.set_apply_callback(promo.apply_picked_products);picker.show();app.processEvents()
    picker.keep_open.setChecked(True)
    picker.search.setText('귤');picker.choose()
    assert picker.applied_batches==1 and picker.isVisible()
