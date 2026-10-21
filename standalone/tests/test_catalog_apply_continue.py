import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from pos2.app import MainWindow
from pos2.store import Store
from pos2.catalog_ui import ProductDialog
from pos2.supplier_ui import SupplierDialog


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'apply.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    window=MainWindow(store);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Cancel)
    yield app,store,window
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


@pytest.mark.parametrize('kind',['product','supplier'])
def test_apply_is_immediate_stays_open_no_duplicates_and_next_record(desktop,kind):
    app,store,window=desktop
    dialog=ProductDialog(store,parent=window) if kind=='product' else SupplierDialog(window)
    rows=store.products if kind=='product' else lambda:store.partners('supplier')
    seen=[];dialog.saved.connect(seen.append);dialog.show();app.processEvents()
    dialog.fields['name'].setText('첫 기록');dialog.apply_button.click()
    identifier=dialog.saved_id
    assert identifier and dialog.isVisible() and len(rows())==1
    assert not window.navigation.changed(dialog)
    dialog.fields['name'].setText('수정한 첫 기록');dialog.apply_button.click()
    assert dialog.saved_id==identifier and len(rows())==1 and rows()[0]['name']=='수정한 첫 기록'
    assert dialog.fields['code'].text()==rows()[0]['code']
    dialog.next_button.click()
    assert dialog.isVisible() and not dialog.record and dialog.fields['name'].text()==''
    assert not window.navigation.changed(dialog) and len(rows())==1
    dialog.fields['name'].setText('둘째 기록');dialog.apply_button.click()
    assert dialog.saved_id!=identifier and len(rows())==2
    assert len({row['code'] for row in rows()})==2 and seen[-1]==dialog.saved_id
    dialog.reject();assert not dialog.isVisible() and len(rows())==2


@pytest.mark.parametrize('kind',['product','supplier'])
def test_invalid_apply_or_next_keeps_input_and_does_not_reset(desktop,kind):
    app,store,window=desktop
    dialog=ProductDialog(store,parent=window) if kind=='product' else SupplierDialog(window)
    dialog.show();app.processEvents();dialog.fields['phone' if kind=='supplier' else 'barcode'].setText('12345')
    dialog.next_button.click()
    assert dialog.isVisible() and not dialog.saved_id and dialog.error_label.text()
    assert dialog.fields['phone' if kind=='supplier' else 'barcode'].text()=='12345'


def test_apply_refreshes_catalog_without_closing_editor(desktop):
    app,store,window=desktop;window.open_page('products');page=window.current_page;seen=[]
    page.product_saved.connect(seen.append)
    dialog=ProductDialog(store,parent=page);dialog.saved.connect(page._product_saved)
    dialog.show();app.processEvents();dialog.fields['name'].setText('즉시 표시 상품');dialog.apply_button.click()
    assert dialog.isVisible() and page.grid.rowCount()==1 and seen==[dialog.saved_id]
