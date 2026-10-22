"""Exercise real worksheet context commands through draft/post/reopen."""
from time import monotonic

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QPushButton

from test_purchase_import import shop
from test_purchase_table_input import sample_table, copied, save_table
from pos2.localization import install_korean_ui
from pos2.purchase_clipboard import PurchasePasteDialog
from pos2.purchase_import_ui import PurchaseImportDialog
from pos2.workflow_ui import TradeDialog, TradesPage


def context_cell(trade,field,app):
    QTest.mouseClick(field,Qt.MouseButton.RightButton);app.processEvents()
    menu=trade.table._product_menu
    assert menu.isVisible()
    editor=next(a.menu() for a in menu.actions() if a.text()=='셀 편집')
    command=next(a for a in editor.actions() if a.objectName()=='edit-paste')
    return menu,command


@pytest.mark.parametrize('accept',[False,True])
def test_native_cell_paste_uses_the_same_table_review_and_cancel_is_atomic(shop,monkeypatch,accept):
    app,store,supplier,product,_,host,_=shop;install_korean_ui(app)
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.show();app.processEvents();before=trade.payload()
    QApplication.clipboard().setText(copied(sample_table()))
    reviews=[]
    def review(dialog):
        reviews.append(dialog);return QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected
    monkeypatch.setattr(PurchasePasteDialog,'exec',review)
    menu,command=context_cell(trade,trade.line_rows[0]['qty'],app)
    assert command.isEnabled();command.trigger();menu.close()
    assert len(reviews)==1
    if accept:
        assert len(trade.payload()['lines'])==1
        assert trade.payload()['lines'][0]['product_id']==product
        assert trade.purchase_summary['total'].text()=='1,500.00'
    else:assert trade.payload()==before
    assert not store.documents() and not store.stock_events()


def test_scalar_native_paste_edits_only_the_clicked_cell_and_readonly_blocks_paste(shop,monkeypatch):
    app,store,supplier,product,_,host,_=shop;install_korean_ui(app)
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.apply_picked_products([(trade.product_map[product],None)]);trade.show();app.processEvents()
    row=trade.line_rows[0];before=row['price'].text()
    trade.table.choose_cell(0,trade.line_columns.index('price'))
    row['qty'].selectAll();QApplication.clipboard().setText('2.125')
    monkeypatch.setattr(PurchasePasteDialog,'exec',lambda _:pytest.fail('Single value must not open table import'))
    menu,command=context_cell(trade,row['qty'],app);command.trigger();menu.close()
    assert row['qty'].text()=='2.125' and row['price'].text()==before
    identifier=store.post_document(trade.payload())
    store.save_user(dict(code='readonly',name='조회 직원',password='Read-Only-2026!',role='staff',permissions=['trade','deny:purchases.edit']))
    store.login('readonly','Read-Only-2026!')
    posted=TradeDialog(host,'purchase',store.document(identifier));assert posted.readonly
    posted.show();app.processEvents();row=posted.line_rows[0];old=row['qty'].text()
    QApplication.clipboard().setText('99')
    menu,command=context_cell(posted,row['qty'],app)
    editor=next(a.menu() for a in menu.actions() if a.text()=='셀 편집')
    for item in editor.actions():
        if item.objectName() in {'edit-undo','edit-redo','edit-cut','edit-paste','edit-delete'}:assert not item.isEnabled()
    assert not command.isEnabled();command.trigger();menu.close()
    assert row['qty'].text()==old and store.document(identifier)['lines'][0]['input_qty']=='2.125'


def test_real_paste_review_then_ui_draft_post_and_reopen_preserve_units_amount_and_memo(shop,monkeypatch):
    app,store,supplier,product,_,host,_=shop
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.show();app.processEvents();errors=[];reviews=[]
    original=PurchasePasteDialog.exec
    def review(dialog):
        def apply():
            try:
                assert QApplication.activeModalWidget() is dialog
                button=next(b for b in dialog.findChildren(QPushButton) if b.text()=='적용')
                QTest.mouseClick(button,Qt.MouseButton.LeftButton);reviews.append(True)
            except BaseException as exc:errors.append(exc);dialog.reject()
        QTimer.singleShot(0,dialog,apply)
        return original(dialog)
    monkeypatch.setattr(PurchasePasteDialog,'exec',review)
    monkeypatch.setattr('pos2.workflow_ui._confirm',lambda *_:True)
    monkeypatch.setattr('pos2.workflow_ui._warn',lambda _,exc:pytest.fail(str(exc)))
    QApplication.clipboard().setText(copied(sample_table()))
    QTest.keyClick(trade.line_rows[0]['barcode'],Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
    assert reviews==[True] and not errors and not store.documents()
    QTest.mouseClick(trade.draft_button,Qt.MouseButton.LeftButton);app.processEvents()
    identifier=trade.saved_id
    assert store.document(identifier)['status']=='draft' and trade.isVisible() and not store.stock_events()
    QTest.mouseClick(trade.post_button,Qt.MouseButton.LeftButton);app.processEvents()
    record=store.document(identifier)
    assert record['status']=='posted' and record['total']==1500 and not trade.isVisible()
    assert store.products()[0]['stock_qty']=='0.125' and not record['payments']
    reopened=TradeDialog(host,'purchase',record)
    row=reopened.line_rows[0]
    assert row['unit'].currentData()=='grams' and row['line_memo'].text()=='연속 입력'
    assert row['sale_price'].text()=='2,500.00' and row['total'].text()=='1,500.00'
    assert reopened.payload()['lines'][0]['gram_input']


def test_import_file_buttons_open_the_registered_draft_via_actual_purchase_page(shop,monkeypatch):
    app,store,supplier,_,_,host,path=shop
    source=path/'표.xlsx';save_table(source,sample_table());sequence=[]
    monkeypatch.setattr(QFileDialog,'getOpenFileNames',lambda *_:([str(source)],'매입 자료'))
    monkeypatch.setattr(QMessageBox,'question',lambda *_:QMessageBox.StandardButton.Yes)
    monkeypatch.setattr('pos2.workflow_ui._warn',lambda _,exc:pytest.fail(str(exc)))
    def finished(dialog):
        until=monotonic()+8
        while dialog._busy and monotonic()<until:QTest.qWait(10)
        assert not dialog._busy and not (dialog.worker and dialog.worker.isRunning())
    def importer(dialog):
        dialog.supplier.setCurrentIndex(dialog.supplier.findData(supplier))
        dialog.show();QTest.mouseClick(dialog.open_button,Qt.MouseButton.LeftButton);finished(dialog)
        assert len(dialog.files)==1 and not dialog.files[0]['error']
        assert dialog.commit_button.isEnabled() and not dialog.open_draft_button.isEnabled()
        item=dialog.file_grid.item(0,0);item.setCheckState(Qt.CheckState.Unchecked)
        assert not dialog.commit_button.isEnabled()
        item.setCheckState(Qt.CheckState.Checked);sequence.append('분석')
        QTest.mouseClick(dialog.commit_button,Qt.MouseButton.LeftButton);finished(dialog)
        assert dialog.open_draft_button.isEnabled();sequence.append('초안 등록')
        QTest.mouseClick(dialog.open_draft_button,Qt.MouseButton.LeftButton)
        assert dialog.result()==QDialog.DialogCode.Accepted
        return dialog.result()
    def voucher(dialog):
        assert dialog.record['status']=='draft' and dialog.record['total']==1500
        assert dialog.line_rows[0]['unit'].currentData()=='grams'
        sequence.append('실제 매입창 열기');dialog.reject();return QDialog.DialogCode.Rejected
    monkeypatch.setattr(PurchaseImportDialog,'exec',importer)
    monkeypatch.setattr(TradeDialog,'exec',voucher)
    page=TradesPage(host,'purchase');page.import_excel()
    assert sequence==['분석','초안 등록','실제 매입창 열기']
    assert len(store.documents())==1 and not store.stock_events()
