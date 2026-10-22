from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt, QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from test_payment_finance import shop
from pos2.workflow_ui import TradeDialog
from pos2.purchase_clipboard import parse_purchase_clipboard, PurchasePasteDialog
from pos2.purchase_amendments import three_month_cutoff


def test_four_column_exact_parser_preserves_zeroes_and_decimals():
    rows=parse_purchase_clipboard('바코드\t수량\t매입단가\t판매단가\r\n"001234"\t1.125\t"1,000.25"\t2000.50\r\n')
    assert rows==[dict(barcode='001234',qty='1.125',unit_price='1000.25',sale_price='2000.50')]


@pytest.mark.parametrize('value',['1\t1\t2','1\t0\t2\t3','1\t1.0001\t2\t3','1\t1\t-1\t3','1\t1\tNaN\t3','1\t1\t1.001\t3','\t1\t2\t3'])
def test_invalid_four_column_paste(value):
    with pytest.raises(ValueError):parse_purchase_clipboard(value)


def test_actual_ctrl_v_into_cell_appends_exact_independent_rows_without_posting(shop,monkeypatch):
    app,s,w,supplier,product,_=shop
    s.save_product(dict(barcode='00001234'),product)
    trade=TradeDialog(w);trade.partner.setCurrentIndex(trade.partner.findData(supplier));trade.show();app.processEvents()
    monkeypatch.setattr(PurchasePasteDialog,'exec',lambda _:QDialog.DialogCode.Accepted)
    QApplication.clipboard().setText('00001234\t2.5\t10.25\t15\n00001234\t1\t9\t20')
    before=s.audit_revision();field=trade.line_rows[0]['barcode'];field.setFocus()
    QTest.keyClick(field,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier);app.processEvents()
    lines=trade.payload()['lines']
    assert len(lines)==2 and [r['unit_price'] for r in lines]==['10.25','9.00']
    assert [r['sale_price'] for r in lines]==['15.00','20.00']
    assert s.audit_revision()==before
    assert trade.purchase_summary['total'].text()=='34.63'


def test_cancel_paste_or_bad_later_barcode_preserves_original_sheet(shop,monkeypatch):
    _,s,w,supplier,product,_=shop;s.save_product(dict(barcode='0001'),product)
    trade=TradeDialog(w);trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    from pos2.purchase_clipboard import paste_purchase
    monkeypatch.setattr(PurchasePasteDialog,'exec',lambda _:QDialog.DialogCode.Rejected)
    QApplication.clipboard().setText('0001\t2\t10\t15');before=trade.payload();paste_purchase(trade)
    assert trade.payload()==before
    errors=[];monkeypatch.setattr('pos2.workflow_ui._warn',lambda _,error:errors.append(str(error)))
    QApplication.clipboard().setText('0001\t2\t10\t15\nUNKNOWN\t1\t2\t3');paste_purchase(trade)
    assert trade.payload()==before and '2행' in errors[0]


def test_new_purchase_date_calendar_uses_three_month_bounds(shop):
    _,s,w,_,_,_=shop;trade=TradeDialog(w)
    assert trade.date.minimumDate()==QDate.fromString(three_month_cutoff(),'yyyy-MM-dd')
    assert trade.date.maximumDate()==QDate.currentDate()
