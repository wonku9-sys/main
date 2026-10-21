"""Photo-style three-column category search, shortcuts and one-path apply."""
import pytest
from PySide6.QtCore import Qt,QCoreApplication,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QLabel,QMessageBox
from pos2.store import Store
from pos2.catalog_ui import ProductDialog,CategorySearchDialog

@pytest.fixture
def catalog(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);store=Store(tmp_path/'categories.db');store.setup_admin('owner','관리자','Owner-Strong-2026!')
    root=store.save_category({'name':'정육'});mid=store.save_category({'name':'돈육','parent_id':root});leaf=store.save_category({'name':'삼겹살','parent_id':mid})
    other=store.save_category({'name':'가공식품'});middle=store.save_category({'name':'양념류','parent_id':other});sauce=store.save_category({'name':'소스류','parent_id':middle})
    monkeypatch.setattr(QMessageBox,'warning',lambda *_:QMessageBox.StandardButton.Ok)
    yield app,store,(root,mid,leaf,other,middle,sauce)
    for widget in app.topLevelWidgets():
        if isinstance(widget,(ProductDialog,CategorySearchDialog)):widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()

def test_three_filters_and_mouse_shortcuts_focus_correct_edit(catalog):
    app,store,ids=catalog;d=CategorySearchDialog(store);d.show();d.activateWindow();app.processEvents()
    for i,key in enumerate((Qt.Key.Key_F5,Qt.Key.Key_F6,Qt.Key.Key_F7)):
        d.query.setFocus();QTest.keyClick(d,key);app.processEvents();assert d.filters[i].hasFocus()
        d.query.setFocus();QTest.mouseClick(d.focus_buttons[i],Qt.MouseButton.LeftButton);assert d.filters[i].hasFocus()
        QTest.mouseClick(d.filters[i],Qt.MouseButton.LeftButton);assert d.filters[i].hasFocus()
    d.filters[0].setText('정');d.filters[1].setText('돈');d.filters[2].setText('삼겹')
    assert d.grid.rowCount()==1 and d.grid.selected()['id']==ids[2]
    assert [d.grid.item(0,c).text() for c in range(3)]==['정육','돈육','삼겹살']
    d.choose();assert d.result()==QDialog.DialogCode.Accepted and d.record['path']==['정육','돈육','삼겹살']

def test_single_search_button_applies_path_without_saving_product(catalog,monkeypatch):
    app,store,ids=catalog;product=ProductDialog(store);product.show();app.processEvents()
    labels={label.text() for label in product.findChildren(QLabel)};assert '과면세' in labels
    assert all(display.isReadOnly() for display in product.category_displays.values())
    assert all(not product.fields[key].isVisible() for key in product.category_displays)
    def choose(dialog):
        dialog.filters[2].setText('삼겹');dialog.choose();return dialog.result()
    monkeypatch.setattr(CategorySearchDialog,'exec',choose)
    product.classification_button.click()
    assert [product.fields[k].text() for k in ('category','category_mid','category_small')]==['정육','돈육','삼겹살']
    assert [v.text() for v in product.category_displays.values()]==['정육','돈육','삼겹살']
    assert product.saved_id is None and store.products()==[]
    product.fields['name'].setText('검색으로 분류한 새 상품');product.save(False)
    saved=store.products()[0];assert [saved[k] for k in ('category','category_mid','category_small')]==['정육','돈육','삼겹살']

def test_cancel_empty_results_and_inactive_path_do_not_change_product(catalog,monkeypatch):
    _,store,ids=catalog;product=ProductDialog(store);old=[product.fields[k].text() for k in product.category_displays]
    monkeypatch.setattr(CategorySearchDialog,'exec',lambda *_:QDialog.DialogCode.Rejected);product.choose_category('없는 분류')
    assert [product.fields[k].text() for k in product.category_displays]==old
    d=CategorySearchDialog(store,query='찾을 수 없는 검색어');assert d.grid.rowCount()==0;d.choose();assert d.record is None and d.result()!=QDialog.DialogCode.Accepted
    d.query.setText('삼겹');assert d.grid.rowCount()==1
    store.save_category({'active':False,'name':'정육'},ids[0]);d.choose()
    assert d.record is None and d.grid.rowCount()==0
    assert not product.apply_category_id(ids[2]) and [product.fields[k].text() for k in product.category_displays]==old
    assert '무효' in product.error_label.text()

def test_query_only_filters_registered_categories_and_keeps_default(catalog):
    _,store,ids=catalog;before=len(store.categories());d=CategorySearchDialog(store,query='소')
    assert d.grid.rowCount()==1 and d.grid.selected()['id']==ids[5]
    d.filters[0].setText('정육');assert d.grid.rowCount()==0
    assert len(store.categories())==before
    p=ProductDialog(store);assert [p.fields[k].text() for k in p.category_displays]==['미분류','미분류','신상품']
