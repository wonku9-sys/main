"""PDF pp.12–15: compulsory supplier, checked selection, exact entry, save."""
from datetime import date
from decimal import Decimal
import sqlite3

import pytest
from PySide6.QtCore import QCoreApplication,QDateTime,QEvent,Qt,QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QMainWindow,QMessageBox,QPushButton

from pos2.store import Store
from pos2.workflow_ui import PartnerPicker,ProductPicker,TradeDialog,TradesPage,PurchasePriceCheckDialog
from pos2.popup_policy import install_popup_policy


@pytest.fixture
def shop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    store=Store(tmp_path/'manual.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    supplier=store.save_partner(dict(kind='supplier',name='참고 공급사',code='S01'))
    product=store.save_product(dict(name='사과',base_unit='개',supplier_id=supplier,purchase_price='30',sale_price='50'))
    unit=store.save_unit(dict(product_id=product,name='상자',factor='10',purchase_price='280',sale_price='450'))
    window=QMainWindow();window.store=store;window.notify=lambda *_:None
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    warnings=[];monkeypatch.setattr('pos2.workflow_ui._warn',lambda _,error:warnings.append(str(error)))
    yield app,store,window,supplier,product,unit,warnings
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def data(shop,**changes):
    result=dict(kind='purchase',date=date.today().isoformat(),partner_id=shop[3],
        lines=[dict(product_id=shop[4],qty='3',unit_price='33.33',amount_override='100')])
    result.update(changes);return result


def test_manual_amount_roundtrip_draft_post_return_and_metadata(shop):
    _,store,window,supplier,product,_,_=shop
    payload=data(shop,entry_datetime=date.today().isoformat()+' 09:12:00',entry_staff='입고 담당')
    payload['lines'][0].update(sale_price='60',line_memo='직접금액')
    draft=store.save_draft(payload)
    loaded=TradeDialog(window,'purchase',draft)
    assert loaded.date.dateTime().toString('HH:mm')=='09:12' and loaded.entry_staff.text()=='입고 담당'
    row=loaded.line_rows[0]
    assert row['total'].text()=='100.00' and row['sale_price'].text()=='60.00'
    assert row['line_memo'].text()=='직접금액' and row['amount_override']==100
    payload=loaded.payload();payload['_expected_token']=store.document(draft)['_edit_token']
    store.post_document(payload,draft)
    posted=store.document(draft)
    assert posted['total']==100 and store.products()[0]['stock_qty']=='3.000'
    assert store.products()[0]['purchase_price']==30 and store.products()[0]['sale_price']==50
    for count,expected in [('1',Decimal('33.33')),('2',Decimal('66.67'))]:
        returned=store.post_document(dict(kind='purchase_return',date=date.today().isoformat(),partner_id=supplier,
            source_id=draft,lines=[dict(product_id=product,qty=count,source_line_id=posted['lines'][0]['id'])]))
        assert store.document(returned)['total']==expected
    assert store.products()[0]['stock_qty']=='0.000' and store.products()[0]['stock_cost']==0


def test_explicit_catalog_selection_is_atomic_and_unchecked_by_default(shop):
    _,store,window,_,product,_,_=shop
    payload=data(shop);payload['lines'][0]['sale_price']='60'
    change=dict(product_id=product,unit_id=None,name='사과',unit='개',old_purchase_price=30,old_sale_price=50,purchase_price='33.33',sale_price=60)
    dialog=PurchasePriceCheckDialog(window,[change])
    assert dialog.selected_updates()==[]
    dialog.checks[0]['sale_price'].setChecked(True)
    payload['catalog_updates']=dialog.selected_updates()
    identifier=store.post_document(payload)
    assert store.document(identifier)['total']==100
    assert store.products()[0]['purchase_price']==30 and store.products()[0]['sale_price']==60
    before=store.document(identifier);stock=store.products()[0]['stock_qty']
    with pytest.raises(ValueError,match='다른 작업'):
        store.post_document(payload)  # stale old sale price
    assert len(store.documents())==1 and store.products()[0]['stock_qty']==stock
    assert store.document(identifier)==before


@pytest.mark.parametrize('bad',[
    dict(unit_price='33.32'),dict(amount_override='-1'),dict(amount_override='nan'),dict(factor_override='0'),dict(factor_override='0.0001'),
])
def test_invalid_manual_values_never_change_stock_or_payments(shop,bad):
    payload=data(shop);payload['lines'][0].update(bad)
    with pytest.raises(ValueError):shop[1].post_document(payload)
    assert shop[1].documents()==[] and shop[1].products()[0]['stock_qty']=='0.000'
    assert not shop[1].db.execute('SELECT 1 FROM payments').fetchone()


def test_space_doubleclick_check_then_enter_confirms_once(shop):
    app,store,window,supplier,*_=shop
    trade=TradeDialog(window);trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    picker=ProductPicker(trade);picker.set_apply_callback(trade.apply_picked_products)
    picker.show();picker.activateWindow();app.processEvents()
    QTest.keyClick(picker.search,Qt.Key.Key_Down)
    assert picker.grid.hasFocus()
    QTest.keyClick(picker.grid,Qt.Key.Key_Space)
    assert len(picker.checked)==1 and picker.applied_batches==0 and store.documents()==[]
    QTest.keyClick(picker.grid,Qt.Key.Key_Space);assert not picker.checked
    picker.grid.cellDoubleClicked.emit(0,2);assert len(picker.checked)==1
    QTest.keyClick(picker.grid,Qt.Key.Key_Return);app.processEvents()
    assert not picker.isVisible() and picker.applied_batches==1
    assert len([r for r in trade.line_rows if r['product'].currentData()])==1


def test_real_nested_supplier_product_amount_save_price_check_sequence(shop,monkeypatch):
    app,store,window,supplier,product,_,warnings=shop
    page=TradesPage(window,'purchase');sequence=[];errors=[];original=QDialog.exec
    def press(widget,key):
        widget.activateWindow();app.processEvents();QTest.keySequence(widget,QKeySequence(key));app.processEvents()
    def modal(dialog,step):
        def run():
            try:step(dialog)
            except BaseException as exc:errors.append(exc);dialog.done(QDialog.DialogCode.Rejected)
        QTimer.singleShot(0,dialog,run);return original(dialog)
    def supplier_step(dialog):
        sequence.append('공급사 선택');assert QApplication.activeModalWidget() is dialog
        dialog.search.setText('S01');press(dialog.search,'Return')
    def product_step(dialog):
        sequence.append('상품검색');dialog.search.setText('사과');press(dialog.search,'Down')
        press(dialog.grid,'Space');sequence.append('상품 체크');assert not dialog.applied_batches
        press(dialog.grid,'Return');sequence.append('상품 확인')
    def price_step(dialog):
        sequence.append('매입상품 체크');assert dialog.selected_updates()==[]
        dialog.checks[0]['sale_price'].setChecked(True);dialog.confirm_button.click()
    def voucher_step(dialog):
        sequence.append('새 매입전표');assert dialog.partner.currentData()==supplier
        press(dialog,'F5');row=dialog.line_rows[0]
        dialog.date.setDateTime(QDateTime.fromString(date.today().isoformat()+' 10:35:00','yyyy-MM-dd HH:mm:ss'))
        row['qty'].setText('3');row['total'].setFocus();row['total'].selectAll();QTest.keyClicks(row['total'],'100')
        assert row['price'].text()=='33.33' and row['amount_override']==100
        row['sale_price'].setText('60');row['line_memo'].setText('순서 확인');sequence.append('수량·금액 입력')
        assert not store.documents();dialog.post_button.click();sequence.append('저장 완료')
    monkeypatch.setattr(PartnerPicker,'exec',lambda d:modal(d,supplier_step))
    monkeypatch.setattr(ProductPicker,'exec',lambda d:modal(d,product_step))
    monkeypatch.setattr(TradeDialog,'exec',lambda d:modal(d,voucher_step))
    monkeypatch.setattr(PurchasePriceCheckDialog,'exec',lambda d:modal(d,price_step))
    monkeypatch.setattr('pos2.workflow_ui._confirm',lambda *_:(sequence.append('저장 확인'),True)[1])
    page.new_trade()
    assert not errors,errors
    assert not warnings,warnings
    assert sequence==['공급사 선택','새 매입전표','상품검색','상품 체크','상품 확인','수량·금액 입력','저장 확인','매입상품 체크','저장 완료']
    document=store.document(store.documents()[0]['id']);assert document['total']==100 and document['status']=='posted'
    reopened=TradeDialog(window,'purchase',document)
    assert reopened.date.dateTime().toString('HH:mm')=='10:35' and reopened.line_rows[0]['line_memo'].text()=='순서 확인'
    assert store.products()[0]['sale_price']==60 and store.products()[0]['purchase_price']==30


def test_schema215_upgrade_keeps_protection_backup_and_validates_current_backup(shop,tmp_path):
    from pos2.recovery import _validate_database
    _,store,_,*_=shop
    path=tmp_path/'previous.db';store.db.backup(sqlite3.connect(path))
    with sqlite3.connect(path) as old:old.execute('DROP TABLE document_entry');old.execute('PRAGMA user_version=215')
    upgraded=Store(path)
    try:
        assert upgraded.migration_backup_path and upgraded.db.execute('PRAGMA user_version').fetchone()[0]==216
        _validate_database(upgraded.db)
        with sqlite3.connect(upgraded.migration_backup_path) as before:
            assert before.execute('PRAGMA user_version').fetchone()[0]==215
            _validate_database(before)
    finally:upgraded.close()
