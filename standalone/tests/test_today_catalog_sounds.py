from datetime import date,timedelta
from types import SimpleNamespace
import wave
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QDate
from PySide6.QtWidgets import QApplication,QMessageBox
from pos2.app import MainWindow
from pos2.catalog_ui import ProductsPage,ProductDialog
from pos2.ui_sounds import write_cue,TONES
from pos2.store import Store

@pytest.fixture
def shop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);store=Store(tmp_path/'today.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    window=MainWindow(store);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    yield app,store,window
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()

def test_today_default_purchase_sales_reports_and_manual_range(shop):
    _,store,window=shop
    for key in ('purchases','sales','purchase_suppliers','purchase_categories','purchase_products','purchase_documents','purchase_statement','sales_realtime','sales_category','sales_supplier','sales_product','sales_daily','sales_monthly','sales_held','sales_cancelled'):
        window.open_page(key);page=window.current_page
        assert page.start.date()==QDate.currentDate() and page.end.date()==QDate.currentDate(),key
        page.start.setDate(QDate.currentDate().addDays(-7));page.refresh();assert page.start.date()==QDate.currentDate().addDays(-7)
    editor=ProductDialog(store,parent=window)
    for enabled,start,end in editor.history_filters.values():assert enabled.isChecked() and start.date()==end.date()==QDate.currentDate()

def test_product_catalog_nested_tax_stock_date_filters_and_scan_reset(shop):
    _,store,window=shop
    a=store.save_product(dict(name='정육 상품',barcode='12345',category='식품',category_mid='정육',category_small='한우',tax_mode='taxable'))
    store.save_product(dict(name='과일',barcode='54321',category='식품',category_mid='청과',category_small='사과',tax_mode='exempt',tracked=False))
    page=ProductsPage(window);page.category.setCurrentIndex(page.category.findData('식품'));page.middle_filter.setCurrentIndex(page.middle_filter.findData('정육'))
    assert page.grid.rowCount()==1 and page.grid.item(0,0).data(256)['id']==a
    page.middle_filter.setCurrentIndex(0);page.tax_filter.setCurrentIndex(page.tax_filter.findData('exempt'));assert page.grid.rowCount()==1
    page.tracked_filter.setCurrentIndex(page.tracked_filter.findData(True));assert page.grid.rowCount()==0
    page.scan_barcode('12345');assert page.grid.rowCount()==1 and page.period_filter.currentIndex()==0
    page.search.clear();page.period_filter.setCurrentIndex(page.period_filter.findData('created_at'));assert page.grid.rowCount()==2
    page.period_end.setDate(QDate.currentDate().addDays(-1));assert page.grid.rowCount()==0

def test_effect_cues_are_local_short_waves_and_setting_persists(shop,tmp_path):
    app,store,window=shop
    for kind in TONES:
        target=tmp_path/(kind+'.wav');write_cue(target,kind)
        with wave.open(str(target),'rb') as wav:assert wav.getnchannels()==1 and wav.getnframes()/wav.getframerate()<.2
    window.open_page('settings');page=window.current_page;page.sound_enabled.setChecked(False)
    assert not store.popup_sound_enabled() and not window.sounds.play('menu')
    page.sound_enabled.setChecked(True);assert store.popup_sound_enabled()
    store.save_popup_sound_enabled(False);page.refresh();assert not page.sound_enabled.isChecked()

def test_success_sound_only_after_commit_and_never_after_failed_write(shop):
    app,store,window=shop;calls=[];store._ui_sound_callback=calls.append
    identifier=store.save_product({'name':'저장'});assert calls==['save']
    store.save_product({'name':'수정'},identifier);assert calls[-1]=='edit'
    before=list(calls)
    with pytest.raises(ValueError):store.save_product({'name':''},identifier)
    assert calls==before
    store.delete_product(identifier);assert calls[-1]=='delete'
