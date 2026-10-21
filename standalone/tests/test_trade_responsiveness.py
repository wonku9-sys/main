import time
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt,QItemSelectionModel,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMainWindow
from pos2.store import Store
from pos2.workflow_ui import TradeDialog,ProductPicker
from pos2.app import LoginDialog,MainWindow


@pytest.fixture
def shop(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'large.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    supplier=store.save_partner(dict(kind='supplier',name='시험 공급사'))
    with store._tx():
        store.db.executemany("INSERT INTO products(code,name,barcode,supplier_id,created_at,updated_at) VALUES(?,?,?,?,'2026-10-20','2026-10-20')",[(f'S{i:06d}',f'시험 상품 {i:06d}',f'880{i:010d}',supplier) for i in range(1201)])
    window=QMainWindow();window.store=store;window.notify=lambda *_:None
    yield app,store,supplier,window
    for worker in list(getattr(app,'_sy_catalog_workers',[])):worker.wait(10000)
    app.processEvents()
    for widget in app.topLevelWidgets():
        if isinstance(widget,MainWindow):widget.navigation.suspended=True;widget.navigation.disable()
        widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_shared_lazy_model_and_constant_time_identifier_lookup(shop,monkeypatch):
    _,store,_,window=shop
    dialog=TradeDialog(window,'purchase');changes=[]
    original=dialog.total_label.setText
    monkeypatch.setattr(dialog.total_label,'setText',lambda text:(changes.append(text),original(text)))
    dialog.apply_picked_products([(r,None) for r in dialog.products[:100]])
    assert len(dialog.line_rows)==100 and len(changes)==1
    assert all(row['product'].model() is dialog.product_model for row in dialog.line_rows)
    last=dialog.products[-1]['id'];assert dialog.line_rows[0]['product'].findData(last)==1201
    product=store.save_product(dict(name='추가 상품'))
    assert dialog.apply_master_product(product)
    assert dialog.line_rows[-1]['product'].currentData()==product
    assert not store.documents()


def test_picker_paging_cached_coalesced_search_and_revalidation(shop,monkeypatch):
    app,store,supplier,window=shop
    dialog=TradeDialog(window,'purchase');dialog.partner.setCurrentIndex(dialog.partner.findData(supplier))
    picker=ProductPicker(dialog)
    assert len(picker.matches)==1201 and picker.grid.rowCount()==500
    picker.move_page(2);assert picker.grid.rowCount()==201
    def no_reload(*_,**__):pytest.fail('Search reloaded unchanged products')
    monkeypatch.setattr(store,'trade_products',no_reload)
    picker.search.setText('S001200');assert picker.search_timer.isActive()
    picker.refresh();assert picker.grid.rowCount()==1
    assert picker.grid.item(0,1).text()=='S001200'
    picker.reject();assert not picker.search_timer.isActive()


def test_multi_selection_coloring_checks_arrows_and_space_apply_without_post(shop):
    app,store,_,window=shop
    dialog=TradeDialog(window,'purchase');picker=ProductPicker(dialog);picker.set_apply_callback(dialog.apply_picked_products)
    picker.show();picker.activateWindow();app.processEvents();picker.grid.sortItems(1,Qt.SortOrder.AscendingOrder);picker.grid.selectRow(0)
    for index in (1,2):
        picker.grid.selectionModel().select(picker.grid.model().index(index,0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
    assert 'background:#176CB0' in picker.grid.styleSheet()
    picker.check_current(True);assert len(picker.checked)==3
    picker.check_current(False);assert not picker.checked
    picker.grid.setFocus();QTest.keyClick(picker.grid,Qt.Key.Key_Space);app.processEvents()
    assert len([r for r in dialog.line_rows if r['product'].currentData()])==3
    assert picker.isVisible() and picker.applied_batches==1 and not store.documents()
    picker.grid.setCurrentCell(0,1);QTest.keyClick(picker.grid,Qt.Key.Key_Down)
    assert picker.grid.currentRow()==1


def test_async_login_keeps_event_loop_live_and_success_audio_only_after_auth(shop,monkeypatch):
    app,store,_,_=shop;store.logout()
    import pos2.background_store as background
    original=background.StoreTask.run
    def slow(worker):time.sleep(.15);original(worker)
    monkeypatch.setattr(background.StoreTask,'run',slow)
    dialog=LoginDialog(store);dialog.code.setText('owner');dialog.password.setText('Owner-Password-2026!')
    ticks=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
    dialog.start_submit();dialog.start_submit();assert not dialog.isEnabled() and store.actor is None
    until=time.monotonic()+10
    while (dialog.login_worker.isRunning() or store.actor is None) and time.monotonic()<until:app.processEvents();time.sleep(.01)
    app.processEvents();timer.stop()
    assert store.actor['code']=='owner' and len(ticks)>=3
    assert dialog.result()==dialog.DialogCode.Accepted and dialog._login_result is None


def test_automatic_backup_never_runs_during_login_or_entry_only_exit(shop,monkeypatch):
    app,store,_,_=shop
    window=MainWindow(store);calls=[]
    monkeypatch.setattr(store,'run_scheduled_backup',lambda *_:pytest.fail('Unexpected in-session backup'))
    monkeypatch.setattr(store,'run_backup_retention',lambda *_:pytest.fail('Unexpected in-session retention'))
    assert not window.backup_timer.isActive() and not window.maintenance_timer.isActive()
    window._backup_runtime_enabled=True
    window.scheduled_backup()
    monkeypatch.setattr(store,'backup_on_exit',lambda:calls.append('exit'))
    assert window.prepare_exit() and calls==['exit']
    assert window.prepare_exit() and calls==['exit']
