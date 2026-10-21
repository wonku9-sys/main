from datetime import date,timedelta
from decimal import Decimal
import sqlite3
from types import SimpleNamespace
from uuid import uuid4
import pytest
from PySide6.QtWidgets import QApplication,QMessageBox,QDialog,QScrollArea,QDoubleSpinBox,QStyleOptionSpinBox,QStyle
from PySide6.QtCore import Qt,QPoint,QTimer,QEvent
from PySide6.QtTest import QTest
from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    s=Store(tmp_path/'stock.db');s.setup_admin('owner','관리자','Owner-Strong-2026!')
    supplier=s.save_partner({'name':'공급사','kind':'supplier'});customer=s.save_partner({'name':'판매처','kind':'customer'})
    product=s.save_product({'name':'g 기준 상품','base_unit':'g','price_basis':100,'purchase_price':'100','sale_price':'200','tracked':True})
    yield s,supplier,customer,product
    s.close()


def adjust(s,p,kind,quantity,when=None,token=None,**extra):
    return s.post_stock_adjustment(dict(kind=kind,product_id=p,date=when or date.today().isoformat(),qty=quantity,unit_price='100' if kind=='opening' else '0',reason='기초 등록' if kind=='opening' else '유통기한 경과',**extra),token or uuid4().hex)


def trade(s,partner,p,kind,quantity,price):
    return s.post_document({'kind':kind,'partner_id':partner,'date':date.today().isoformat(),'lines':[{'product_id':p,'qty':quantity,'unit_price':price}],'paid':'0'})


def test_opening_purchase_sale_waste_exact_quantity_cost_and_period_assets(shop):
    s,sup,cust,p=shop;old=(date.today()-timedelta(days=40)).isoformat()
    adjust(s,p,'opening','1000',old);trade(s,sup,p,'purchase','500','120');trade(s,cust,p,'sale','200','200');adjust(s,p,'waste','100')
    product=s.products()[0];assert product['stock_qty']=='1200.000' and product['stock_cost']==Decimal('1280.00')
    report=s.inventory_assets(date.today().replace(day=1).isoformat(),date.today().isoformat());row=report['rows'][0]
    assert row['opening_qty']=='1000.000' and row['purchase_qty']=='500.000' and row['sale_qty']=='200.000' and row['waste_qty']=='100.000' and row['closing_qty']=='1200.000'
    assert report['totals']['opening_cost']==Decimal('1000.00') and report['totals']['stock_cost']==Decimal('1280.00')
    comparison=s.inventory_asset_comparison(date.today().isoformat());assert comparison['totals']=={'stock_cost':Decimal('1280.00'),'week_cost':Decimal('1000.00'),'month_cost':Decimal('1000.00')}
    assert comparison['rows'][0]['week_rate']==28 and len(comparison['timeline'])>=29


def test_opening_exactly_once_duplicate_request_and_disposal_oversell_rollback(shop):
    s,_,_,p=shop;token=uuid4().hex
    first=adjust(s,p,'opening','1000',token=token);assert adjust(s,p,'opening','1000',token=token)==first
    with pytest.raises(ValueError):adjust(s,p,'opening','1001',token=token)
    with pytest.raises(ValueError,match='한 번'):adjust(s,p,'opening','1000')
    with pytest.raises(ValueError,match='현재고'):adjust(s,p,'waste','1001')
    assert len(s.stock_adjustments('opening'))==1 and not s.stock_adjustments('waste') and s.products()[0]['stock_qty']=='1000.000'
    disposal=uuid4().hex;first=adjust(s,p,'waste','1000',token=disposal);assert adjust(s,p,'waste','1000',token=disposal)==first
    assert s.products()[0]['stock_qty']=='0.000' and s.products()[0]['stock_cost']==0
    with pytest.raises(sqlite3.IntegrityError):s.db.execute('DELETE FROM stock_adjustments')


def test_stock_adjustment_permissions_closed_period_and_backup(shop):
    s,_,_,p=shop;adjust(s,p,'opening','1000')
    backup=s.create_backup();adjust(s,p,'waste','100');s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!')
    assert s.products()[0]['stock_qty']=='1000.000' and len(s.stock_adjustments('opening'))==1 and not s.stock_adjustments('waste')
    s.save_user({'code':'reader','name':'조회자','password':'Reader-Strong-2026!','role':'staff','permissions':['inventory','deny:stock_waste.create']});s.login('reader','Reader-Strong-2026!')
    with pytest.raises(PermissionError):adjust(s,p,'waste','1')
    assert s.inventory_assets(date.today().isoformat(),date.today().isoformat())['rows']


def test_previous_209_backup_without_new_stock_tables_is_accepted(shop):
    s,_,_,_=shop;backup=s.create_backup();db=sqlite3.connect(backup)
    try:
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'stock_adjustments%'").fetchall():db.execute(f'DROP TRIGGER "{row[0]}"')
        db.execute('DROP TABLE stock_adjustments');db.execute('PRAGMA user_version=209');db.commit()
        db.execute('DROP TABLE member_contact_types');db.commit()
    finally:db.close()
    assert s.inspect_backup(backup)['schema_version']==209
    from pos2.recovery import SCHEMA_VERSION
    s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!');assert s.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
    assert s.stock_adjustments('opening')==[]


def test_stock_views_charts_and_calendar_month_comparison_ui(shop):
    app=QApplication.instance() or QApplication([]);s,_,_,p=shop;adjust(s,p,'opening','1000',(date.today()-timedelta(days=40)).isoformat())
    from pos2.stock_management_ui import StockAdjustmentPage,InventoryAssetsPage
    window=SimpleNamespace(store=s)
    first=StockAdjustmentPage(window,'opening');first.refresh();assert first.grid.rowCount()==1
    report=InventoryAssetsPage(window);report.refresh();assert report.grid.rowCount()==1 and report.category_grid.rowCount()==1 and report.pie.values and len(report.bar.values)==3
    report.show();app.processEvents();assert not report.grab().isNull();report.close();report.deleteLater();first.deleteLater();app.processEvents()


def test_independent_menus_are_modeless_and_exit_honours_unsaved_changes(shop,monkeypatch):
    from pos2.app import MainWindow
    from pos2.popup_policy import install_popup_policy
    app=QApplication.instance() or QApplication([]);install_popup_policy(app);s,_,_,_=shop
    window=MainWindow(s,popup_menus=True);window.navigation.enable();window.show()
    assert window.open_page('products') and window.open_page('purchases') and window.open_page('worklog')
    app.processEvents();assert all(not w.isModal() and w.isVisible() for w in window.popup_windows.values())
    for key in ('products','purchases','worklog'):
        assert window.scrollers[key].isVisible() and window.pages[key].isVisible()
        assert window.pages[key].grid.isVisible()
    assert window.popup_windows['worklog'].close()
    assert window.open_page('worklog');app.processEvents()
    assert window.scrollers['worklog'].isVisible() and window.pages['worklog'].grid.isVisible()
    assert len(window.popup_windows)==3;assert window.open_page('products') and len(window.popup_windows)==3
    assert all(not item.icon(0).isNull() for item in window.items.values())
    assert window.open_page('purchases')
    from pos2.workflow_ui import TradeDialog
    editor=TradeDialog(window,'purchase');editor.show();app.processEvents()
    assert editor.parentWidget() is window.popup_windows['purchases'] and editor.windowModality()==Qt.WindowModality.WindowModal
    editor.close();editor.deleteLater();app.processEvents()
    assert window.open_page('settings');settings=window.pages['settings'];settings.fields['store_name'].setText('아직 저장하지 않은 설정')
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Cancel)
    assert not window.popup_windows['settings'].close() and window.popup_windows['settings'].isVisible()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    assert window.close();window.deleteLater();app.processEvents()


def test_popup_maximize_fullscreen_scroll_and_spinner_arrows_work():
    from pos2.popup_policy import install_popup_policy
    from pos2.widgets import FormDialog
    from pos2.branding import spin_button_style
    application=QApplication.instance() or QApplication([]);install_popup_policy(application)
    dialog=FormDialog('긴 입력창');dialog.setStyleSheet(spin_button_style());number=QDoubleSpinBox();number.setRange(0,100);dialog.form.addRow('수수료율',number)
    for i in range(25):dialog.field(str(i),'입력 '+str(i))
    dialog.show();application.processEvents()
    assert dialog.windowFlags()&Qt.WindowType.WindowMaximizeButtonHint and dialog.findChild(QScrollArea,'popupScroll')
    option=QStyleOptionSpinBox();number.initStyleOption(option);rect=number.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,QStyle.SubControl.SC_SpinBoxUp,number)
    QTest.mouseClick(number,Qt.MouseButton.LeftButton,pos=rect.center());assert number.value()>0
    dialog.showMaximized();application.processEvents();assert dialog.isMaximized();dialog.showNormal();dialog.close();dialog.deleteLater();application.processEvents()


def test_member_birthday_direct_entry_calendar_and_mobile_telephone_custom_type(shop):
    from pos2.loyalty_ui import MemberDialog,MembersPage
    application=QApplication.instance() or QApplication([]);s,_,_,_=shop
    dialog=MemberDialog(s);dialog.fields['name'].setText('회원 예시');dialog.fields['mobile'].setText('010-0000-0000');dialog.fields['phone'].setText('02-000-0000');dialog.phone_type.setCurrentText('보호자 직장')
    dialog.birthday_enabled.setChecked(True);dialog.birthday.lineEdit().setText('1977-03-10');dialog.birthday.interpretText();dialog.save()
    member=s.members()[0];assert member['birthday']=='1977-03-10' and member['mobile']=='010-0000-0000' and member['phone']=='02-000-0000' and member['phone_type']=='보호자 직장'
    assert dialog.birthday.calendarPopup() and dialog.birthday.displayFormat()=='yyyy-MM-dd'
    again=MemberDialog(s,member);assert again.birthday.date().toString('yyyy-MM-dd')=='1977-03-10' and again.phone_type.currentText()=='보호자 직장'
    again.birthday_enabled.setChecked(False);again.save();assert s.members()[0]['birthday']==''
    backup=s.create_backup();s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!');assert s.members()[0]['phone_type']=='보호자 직장'
    page=MembersPage(SimpleNamespace(store=s));page.refresh()
    columns={page.grid.horizontalHeaderItem(c).text():c for c in range(page.grid.columnCount())}
    assert page.grid.item(0,columns['휴대폰']).text()=='010-0000-0000' and page.grid.item(0,columns['전화번호']).text()=='02-000-0000'
    dialog.deleteLater();again.deleteLater();page.deleteLater();application.processEvents()


def test_quote_date_numeric_normalization_and_calendar_selection(monkeypatch):
    from pos2.date_input import DateInput
    from PySide6.QtWidgets import QCalendarWidget,QMenu
    from PySide6.QtCore import QDate
    application=QApplication.instance() or QApplication([])
    value=DateInput();value.setText('20261020');assert value.text()=='2026-10-20'
    value.open_calendar();application.processEvents()
    calendar=value._calendar_menu.findChild(QCalendarWidget);assert calendar.selectedDate()==QDate(2026,10,20)
    calendar.clicked.emit(QDate(2027,2,28));assert value.text()=='2027-02-28'
    value.clear();assert value.text()=='';value.deleteLater();application.processEvents()
