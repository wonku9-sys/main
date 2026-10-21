"""Reference four-region workspace and the real keyboard purchasing sequence."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPushButton

from pos2.app import MainWindow, STYLE
from pos2.popup_policy import install_popup_policy
from pos2.store import Store
from pos2.workflow_ui import PartnerPicker, ProductPicker, TradeDialog, PurchaseBatchDialog, TradeDetailDialog


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    previous_style=app.styleSheet();app.setStyleSheet(STYLE)
    store=Store(tmp_path/'workspace.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    supplier=store.save_partner(dict(kind='supplier',code='S01',name='우유 공급사'))
    second=store.save_partner(dict(kind='supplier',code='S02',name='다른 공급사'))
    store.save_partner(dict(kind='supplier',code='S03',name='무효 공급사',active=False))
    product=store.save_product(dict(name='우유',barcode='001122',supplier_id=supplier,base_unit='개',purchase_price=100,sale_price=150,tax_mode='taxable'))
    other=store.save_product(dict(name='다른상품',supplier_id=second,base_unit='개',purchase_price=200,sale_price=300))
    untracked=store.save_product(dict(name='미관리 상품',supplier_id=supplier,tracked=False))
    inactive=store.save_product(dict(name='무효 상품',supplier_id=supplier,active=False))
    unit=store.save_unit(dict(product_id=product,name='6개 묶음',barcode='006600',factor=6,purchase_price=550,sale_price=800))
    window=MainWindow(store);window.resize(1280,850);window.show();window.navigation.enable();app.processEvents()
    warnings=[]
    monkeypatch.setattr('pos2.workflow_ui._warn',lambda parent,error:warnings.append(str(error)))
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    yield app,store,window,dict(supplier=supplier,second=second,product=product,other=other,untracked=untracked,inactive=inactive,unit=unit),warnings
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close();app.setStyleSheet(previous_style)


def press(app,widget,sequence):
    widget.activateWindow();app.processEvents();QTest.keySequence(widget,QKeySequence(sequence));app.processEvents()


def test_top_and_left_menus_only_change_workspace_keep_shell_and_collapsed_sidebar(desktop):
    app,_,window,_,_=desktop
    def expanded():return [window.tree.topLevelItem(i).isExpanded() for i in range(window.tree.topLevelItemCount())]
    assert not any(expanded()) and not window.popup_menus
    assert all(window.tree.topLevelItem(i).text(0)!='첫화면' for i in range(window.tree.topLevelItemCount()))
    assert window.items['home'].treeWidget() is None
    window.open_page('purchases')
    next(action for action in window.toolbar.actions() if action.text()=='첫화면').trigger()
    assert window.current_key=='home' and window.tree.currentItem() is None
    assert window.previous_menu() and window.current_key=='purchases'
    assert window.next_menu() and window.current_key=='home'
    toolbar_position=window.toolbar.pos();toolbar_size=window.toolbar.size()
    before=expanded()
    for title,key in (('상품장','products'),('매입전표','purchases'),('판매조회','sales')):
        next(action for action in window.toolbar.actions() if action.text()==title).trigger();app.processEvents()
        assert window.current_key==key and not window.popup_windows
        assert expanded()==before and window.toolbar.pos()==toolbar_position and window.toolbar.size()==toolbar_size
        assert window.stack.currentWidget() is window.page_surfaces[key]
    assert not window.location.isVisible() and not window.navigation_bar.isVisible()
    assert not [b for b in window.findChildren(QPushButton) if b.isVisible() and b.text()=='첫화면']
    parent=window.items['purchases'].parent();parent.setExpanded(True);app.processEvents()
    before=expanded();scroll=window.tree.verticalScrollBar().value()
    window.open_page('products');app.processEvents()
    assert expanded()==before and window.tree.verticalScrollBar().value()==scroll
    window.open_page('purchases');app.processEvents()
    page=window.current_page;bar=page.header
    assert abs(bar.query_button.mapTo(bar,bar.query_button.rect().center()).x()-bar.rect().center().x())<=1
    assert page.new_button.mapTo(window,QPoint()).y()>=bar.mapTo(window,QPoint(0,bar.height())).y()
    assert page.new_button.mapTo(page,page.new_button.rect().topRight()).x()>=page.width()-30
    assert bar.isAncestorOf(page.partner_filter) and bar.isAncestorOf(page.partner_lookup)
    assert page.partner_lookup.width()==36
    assert window.tree.findChild(QLabel,'syLogo') is None and window.findChild(QLabel,'independent') is None
    assert window.toolbar.findChild(QLabel,'syLogo') is not None
    assert not window.windowIcon().isNull()
    assert '2-01. 매입전표' in window.windowTitle() and 'SY POS' in window.windowTitle()
    assert window.selected_menu.text()=='2-01. 매입전표'


def test_supplier_picker_lists_all_then_cached_name_code_search_and_rechecks_validity(desktop,monkeypatch):
    app,store,window,ids,_=desktop
    monkeypatch.setattr(store,'partners',lambda *_:pytest.fail('Supplier picker must not compute financial profiles'))
    picker=PartnerPicker(window,'supplier');picker.show();app.processEvents()
    assert picker.grid.rowCount()==2 and picker.search.hasFocus()
    original=store.trade_partners;calls=[]
    monkeypatch.setattr(store,'trade_partners',lambda *args,**kwargs:(calls.append(1),original(*args,**kwargs))[1])
    picker.search.setText('S02');assert picker.grid.rowCount()==1 and picker.grid.item(0,0).text()=='다른 공급사'
    picker.search.setText('우유');assert picker.grid.rowCount()==1 and not calls
    press(app,picker.search,'Down');assert picker.grid.hasFocus()
    press(app,picker.grid,'Return');assert picker.selected_record['id']==ids['supplier'] and not picker.isVisible()
    assert len(calls)==1
    stale=PartnerPicker(window,'supplier');stale.search.setText('S02');store.save_partner(dict(active=False),ids['second'])
    stale.choose();assert stale.selected_record is None and '다시 선택' in stale.notice.text()


def test_sidebar_single_click_accordion_and_executed_page_history(desktop):
    app,_,window,_,_=desktop
    roots=[window.tree.topLevelItem(index) for index in range(window.tree.topLevelItemCount()) if window.tree.topLevelItem(index).childCount()]
    for root in roots:
        window.tree.scrollToItem(root);app.processEvents()
        rect=window.tree.visualItemRect(root)
        QTest.mouseClick(window.tree.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(rect.left()+60,rect.center().y()))
        app.processEvents()
        assert root.isExpanded()
        assert sum(other.isExpanded() for other in roots)==1
    for key in ('products','purchases','sales'):assert window.open_page(key)
    assert window.previous_menu() and window.current_key=='purchases'
    assert window.previous_menu() and window.current_key=='products'
    assert window.next_menu() and window.current_key=='purchases'


def test_payment_supplier_picker_uses_payment_permission_not_purchase_permission(desktop,monkeypatch):
    _,store,window,ids,_=desktop
    store.save_user(dict(code='payment-only',name='결제 직원',role='staff',password='Payment-Password-2026!',permissions=['trade','deny:purchases']))
    store.logout();store.login('payment-only','Payment-Password-2026!')
    from pos2.payment_ui import SupplierPaymentsPage
    page=SupplierPaymentsPage(window)
    observed=[]
    def choose(picker):
        observed.append(picker.menu_key)
        picker.search.setText('S01');picker.choose()
        assert picker.selected_record['id']==ids['supplier']
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PartnerPicker,'exec',choose)
    page.pick_partner()
    assert observed==['payments'] and page.partner.currentData()==ids['supplier']
    denied=PartnerPicker(window,'supplier')
    assert denied.grid.rowCount()==0 and not denied.choose_button.isEnabled()


def test_supplier_cancel_never_constructs_voucher_or_writes_data(desktop,monkeypatch):
    _,store,window,_,_=desktop;window.open_page('purchases');revision=store.audit_revision()
    monkeypatch.setattr(PartnerPicker,'exec',lambda self:QDialog.DialogCode.Rejected)
    monkeypatch.setattr(TradeDialog,'__init__',lambda *_:pytest.fail('Voucher created after cancelled supplier selection'))
    window.current_page.new_button.click()
    assert not store.documents() and store.audit_revision()==revision


def test_real_supplier_voucher_f5_f4_space_check_enter_close_and_draft_sequence(desktop,monkeypatch):
    app,store,window,ids,warnings=desktop
    window.open_page('purchases');sequence=[];errors=[];base_exec=QDialog.exec
    def modal_run(dialog,callback):
        def run():
            try:callback(dialog)
            except BaseException as exc:errors.append(exc);dialog.done(QDialog.DialogCode.Rejected)
        QTimer.singleShot(0,dialog,run)
        return base_exec(dialog)
    def supplier_step(dialog):
        sequence.append('supplier');assert QApplication.activeModalWidget() is dialog
        dialog.search.setText('S01');press(app,dialog.search,'Return')
        assert not dialog.isVisible()
    def product_step(picker):
        sequence.append('products');assert picker.supplier_only.isChecked()
        picker.keep_open.setChecked(True)
        picker.search.setText('우유');press(app,picker,'F5');assert picker.grid.hasFocus()
        press(app,picker.grid,'Space');assert picker.applied_batches==0 and len(picker.checked)==1
        press(app,picker.grid,'Return');assert picker.applied_batches==1 and picker.isVisible()
        press(app,picker,'F4');assert picker.search.hasFocus()
        press(app,picker,'F7');assert not picker.supplier_only.isChecked()
        picker.search.setText('다른상품');press(app,picker,'F5')
        press(app,picker,'F8');assert len(picker.checked)==1
        press(app,picker,'F9');assert not picker.checked
        picker.check_all_button.click();press(app,picker.grid,'Return');assert picker.applied_batches==2
        press(app,picker,'F4');picker.expanded_units.setChecked(True);picker.search.setText('006600');press(app,picker,'F5')
        press(app,picker.grid,'Space');press(app,picker.grid,'Return');assert picker.applied_batches==3
        assert not [b for b in picker.findChildren(QPushButton) if b.text()=='첫화면']
        picker.close();assert not picker.isVisible()
    def voucher_step(dialog):
        sequence.append('voucher');assert dialog.partner.currentData()==ids['supplier']
        press(app,dialog,'F5')
        assert {(r['product'].currentData(),r['unit'].currentData()) for r in dialog.line_rows}=={(ids['product'],None),(ids['other'],None),(ids['product'],ids['unit'])}
        assert not store.documents() and not store.db.execute('SELECT 1 FROM payments').fetchone()
        press(app,dialog,'F6');assert dialog.line_rows[dialog.table.currentRow()]['qty'].hasFocus()
        press(app,dialog,'Ctrl+B');assert dialog.scan.hasFocus()
        press(app,dialog,'Alt+A');assert store.document(dialog.saved_id)['status']=='draft'
        assert all(Decimal(p['stock_qty'])==0 for p in store.products())
        dialog.close()
    monkeypatch.setattr(PartnerPicker,'exec',lambda dialog:modal_run(dialog,supplier_step))
    monkeypatch.setattr(ProductPicker,'exec',lambda dialog:modal_run(dialog,product_step))
    monkeypatch.setattr(TradeDialog,'exec',lambda dialog:modal_run(dialog,voucher_step))
    window.current_page.new_button.click()
    assert not errors,errors
    assert not warnings,warnings
    assert sequence==['supplier','voucher','products']
    assert len(store.documents())==1 and window.current_page.grid.rowCount()==2


def test_unit_inactive_tracking_filters_and_exact_pack_quantity_no_implicit_post(desktop):
    app,store,window,ids,warnings=desktop
    trade=TradeDialog(window);trade.partner.setCurrentIndex(trade.partner.findData(ids['supplier']))
    picker=ProductPicker(trade);picker.set_apply_callback(trade.apply_picked_products)
    picker.include_inactive.setChecked(True);picker.search.setText('무효');picker.choose()
    assert warnings and picker.applied_batches==0 and not trade.line_rows[0]['product'].currentData()
    picker.include_inactive.setChecked(False);picker.search.clear();picker.tracked_only.setChecked(True)
    assert ids['untracked'] not in {r['id'] for r in picker.matches}
    picker.search.setText('006600');assert not picker.matches
    picker.expanded_units.setChecked(True);assert len(picker.matches)==1
    picker.choose();row=trade.line_rows[0]
    assert row['unit'].currentData()==ids['unit'] and row['factor'].text()=='6' and row['price'].text()=='550.00'
    row['qty'].setText('2');assert row['base_qty'].text()=='12 개' and row['total'].text()=='1,100.00'
    assert not store.documents()


def test_bulk_editor_validation_is_all_or_nothing_and_reorder_keeps_unit_values(desktop):
    _,store,window,ids,warnings=desktop
    trade=TradeDialog(window);trade.apply_picked_products([(store.catalog_product(ids['product']),ids['unit']),(store.catalog_product(ids['other']),None)])
    bulk=PurchaseBatchDialog(trade);bulk.inputs[0][1].setText('2.500');bulk.inputs[1][1].setText('-1');bulk.apply_values()
    assert trade.line_rows[0]['qty'].text()=='1' and warnings and not bulk.applied
    bulk.inputs[1][1].setText('3');bulk.apply_values();assert bulk.applied
    trade.table.setCurrentCell(0,3);trade.move_line(1)
    assert trade.line_rows[1]['unit'].currentData()==ids['unit'] and trade.line_rows[1]['qty'].text()=='2.500'
    assert trade.line_rows[1]['total'].text()=='1,375.00' and not store.documents()


def test_output_icons_hover_help_and_click_call_real_commands(desktop,monkeypatch):
    app,_,window,_,_=desktop;window.open_page('purchases');page=window.current_page;calls=[]
    from pos2.widgets import DataGrid
    monkeypatch.setattr(DataGrid,'export',lambda self,*_:calls.append('export'))
    monkeypatch.setattr(DataGrid,'print_pages',lambda self,*_:calls.append('print'))
    for name,key in (('outputSaveIcon','Ctrl+E'),('outputPrintIcon','Ctrl+P')):
        button=page.header.findChild(QPushButton,name)
        assert button and not button.text() and button.accessibleName() and key in button.toolTip() and not button.icon().isNull()
        button.click()
    assert calls==['export','print']
    assert not any(action.text() in {'엑셀 저장','인쇄'} for action in window.toolbar.actions())
    assert {'엑셀 저장','인쇄'}<=window.common_shortcut_actions.keys()
    window.setFocus();press(app,window,'Ctrl+E');press(app,window,'Ctrl+P')
    assert calls==['export','print','export','print']


def test_journal_reference_columns_totals_sort_and_real_modified_dates(desktop):
    _,store,window,ids,_=desktop;today=date.today();yesterday=today-timedelta(days=1)
    documents=[]
    for when,quantity in ((yesterday,1),(today,2)):
        documents.append(store.post_document(dict(kind='purchase',date=when.isoformat(),partner_id=ids['supplier'],lines=[dict(product_id=ids['product'],qty=quantity,unit_price=100)],paid=50)))
    window.open_page('purchases');page=window.current_page
    assert page.grid.rowCount()==2  # one actual document + an unselectable total
    page.start.setDate(QDate(yesterday.year,yesterday.month,yesterday.day));page.refresh()
    assert page.grid.rowCount()==3
    assert [page.grid.horizontalHeaderItem(i).text() for i in range(11)]==['No.','구분','유형','코드','공급사','입고일시','매입합계','결제금액','외상매입','메모','수정일시']
    for column in (0,4,6,10):
        for order in (Qt.SortOrder.AscendingOrder,Qt.SortOrder.DescendingOrder):
            page.grid.sortItems(column,order)
            assert page.grid.item(2,0).data(Qt.ItemDataRole.UserRole) is None
            assert page.grid.item(2,6).data(Qt.ItemDataRole.UserRole+1)==Decimal(300)
    changes=store.purchase_journal_dates(yesterday.isoformat(),today.isoformat())
    assert {r['document_id'] for r in changes}==set(documents) and all(r['modified_at'] for r in changes)
    page.grid.setCurrentCell(2,0);assert page.grid.selected() is None
