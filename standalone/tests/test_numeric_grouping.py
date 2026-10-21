from decimal import Decimal
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pos2.number_edit import GroupedNumberEdit,grouped_number
from pos2.workflow_ui import TradeDialog,ProductPicker
from pos2.purchase_payment_ui import PurchasePaymentDialog
from test_continuous_product_picker import desktop


@pytest.mark.parametrize('raw,expected',[
    ('',''),('100','100'),('1000','1,000'),('1000000','1,000,000'),
    ('1000.050','1,000.050'),('-1000000.125','-1,000,000.125'),
    ('1,000,000.00','1,000,000.00'),('1000.','1,000.'),('.5','.5'),
    ('nan','nan'),('not numeric','not numeric')])
def test_grouping_preserves_fraction_and_does_not_round_or_hide_invalid_values(raw,expected):
    assert grouped_number(raw)==expected


def test_live_keyboard_grouping_selection_undo_redo_cursor_and_separator_deletion(desktop):
    app,_,_,_=desktop
    field=GroupedNumberEdit();field.show();field.activateWindow();field.setFocus();app.processEvents()
    try:
        QTest.keyClicks(field,'1000000');assert field.text()=='1,000,000' and field.cursorPosition()==9
        QTest.keySequence(field,QKeySequence('Ctrl+Z'));assert field.text()=='100,000'
        QTest.keySequence(field,QKeySequence('Ctrl+Y'));assert field.text()=='1,000,000'
        field.setText('1234567.890');field.setCursorPosition(2)  # just after the first comma
        QTest.keyClick(field,Qt.Key.Key_Backspace);assert field.text()=='234,567.890'
        field.selectAll();QTest.keyClicks(field,'1000.005');assert field.text()=='1,000.005'
        field.setCursorPosition(3);QTest.keyClicks(field,'2');assert field.text()=='10,200.005'
        field.setText('1000');field.setCursorPosition(1)
        QTest.keyClick(field,Qt.Key.Key_Delete);assert field.text()=='100'
        field.selectAll();QTest.keyClicks(field,'1000000');assert field.text()=='1,000,000'
    finally:field.close();field.deleteLater();app.processEvents()


def test_purchase_amounts_quantity_and_scan_increment_remain_exact(desktop):
    app,s,w,ids=desktop
    supplier=s.catalog_product(ids[0])['supplier_id']
    trade=TradeDialog(w);trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.apply_picked_products([(s.catalog_product(ids[0]),None)])
    row=trade.line_rows[0];row['qty'].setText('999')
    trade.scan_barcode('1');assert row['qty'].text()=='1,000'
    row['price'].setText('1000.50');row['sale_price'].setText('1500')
    assert row['price'].text()=='1,000.50' and row['sale_price'].text()=='1,500'
    assert row['total'].text()=='1,000,500.00' and row['barcode'].text()=='1'
    row['line_memo'].setText('1234567');assert row['line_memo'].text()=='1234567'
    identifier=s.post_document(trade.payload());posted=s.document(identifier)
    assert posted['total']==Decimal('1000500.00') and posted['lines'][0]['input_qty']=='1000.000'
    payment=PurchasePaymentDialog(w,identifier)
    assert payment.components['cash'].text()=='1,000,500.00'
    assert payment.target_amount.text()=='1,000,500.00'
    payment.account.setCurrentText('001234567');assert payment.account.currentText()=='001234567'


def test_picker_footer_is_text_only_and_search_open_default_stays_enabled(desktop):
    app,_,window,_=desktop
    picker=ProductPicker(TradeDialog(window));picker.show();app.processEvents()
    assert picker.keep_open.isChecked()
    assert len(picker.text_only_buttons)==7
    for button in picker.text_only_buttons:
        assert button.text() and button.icon().isNull()
