"""Actual manual-card bookkeeping and unobtrusive, opt-in seasonal presentation."""
from datetime import date,timedelta
from decimal import Decimal
from types import SimpleNamespace
from time import monotonic
import sqlite3,time
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtWidgets import QApplication,QMessageBox
from pos2.store import Store
from pos2.app import MainWindow
from pos2.payment_ui import SupplierPaymentDialog
from pos2.payment_access_ui import PaymentAccessDialog
from pos2.appearance import apply_theme,special_day,SEASONS
from pos2.ambient_effects import weather_kind

PASSWORD='Payment-Skin-Test-2026!'


@pytest.fixture
def shop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    from pos2.popup_policy import install_popup_policy
    install_popup_policy(app)
    store=Store(tmp_path/'test.db');store.setup_admin('owner','시험 관리자',PASSWORD)
    supplier=store.save_partner(dict(kind='supplier',name='가상 공급사',opening_balance='10.25',opening_date=date.today().isoformat(),bank='시험은행',account='시험계좌',account_holder='시험 예금주'))
    product=store.save_product(dict(name='가상 상품',base_unit='개',tracked=False,tax_mode='taxable'))
    purchase=store.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,paid='0',lines=[dict(product_id=product,qty='2',unit_price='50.25')]))
    window=MainWindow(store);window.show();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    yield app,store,window,supplier,purchase
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close();apply_theme('default')


def test_manual_card_reduces_supplier_debt_is_not_transfer_and_does_not_move_cash(shop):
    _,s,_,supplier,purchase=shop;before=s.cash_expected(date.today().isoformat())['expected_cash']
    snapshot=s.supplier_outstanding(supplier);group=s.settle_supplier(supplier,'60.50',date.today().isoformat(),'card','수기 카드 승인내역을 보고 입력',snapshot['state'])
    detail=s.supplier_settlement_detail(group);assert detail['method']=='card' and detail['opening_amount']==Decimal('10.25')
    assert s.document(purchase)['balance']==Decimal('50.25') and s.cash_expected(date.today().isoformat())['expected_cash']==before
    row=s.supplier_summary(date.today().isoformat(),date.today().isoformat())[0]
    assert row['card_payment']==Decimal('60.50') and row['cash_payment']==row['transfer_payment']==0
    assert s.supplier_payment_history(date.today().isoformat(),date.today().isoformat())[0]['method']=='card'
    with pytest.raises(ValueError,match='바뀌었'):s.settle_supplier(supplier,'1',date.today().isoformat(),'card',expected_state=snapshot['state'])
    backup=s.create_backup();s.void_supplier_settlement(group,'카드 수기 입력 정정')
    assert s.supplier_outstanding(supplier)['balance']==Decimal('110.75')
    s.restore_backup(backup,PASSWORD);s.login('owner',PASSWORD)
    assert not s.supplier_settlement_detail(group)['voided'] and s.supplier_outstanding(supplier)['balance']==Decimal('50.25')


def test_payment_summary_matches_existing_ledger_without_per_supplier_queries(shop):
    _,s,_,supplier,purchase=shop
    s.add_payment(purchase,'10.25',date.today().isoformat(),'transfer')
    s.settle_supplier(supplier,'10.25',date.today().isoformat(),'card')
    statements=[];s.db.set_trace_callback(statements.append)
    rows=s.supplier_summary(date.today().isoformat(),date.today().isoformat());s.db.set_trace_callback(None)
    assert sum(x.lstrip().upper().startswith(('SELECT','WITH')) for x in statements)<12
    ledger=s.ledger(supplier,date.today().isoformat(),date.today().isoformat())
    assert rows[0]['opening']==ledger['opening'] and rows[0]['payment']==ledger['payment'] and rows[0]['closing']==ledger['closing']


def test_same_day_payment_replace_is_atomic_keeps_history_and_rejects_stale_input(shop):
    _,s,_,supplier,_=shop
    original=s.settle_supplier(supplier,'60.50',date.today().isoformat(),'card','원래 메모')
    before=s.supplier_settlement_detail(original)
    expected={k:before[k] for k in ('date','amount','method','memo')}
    with pytest.raises(ValueError,match='초과'):
        s.replace_supplier_payment('settlement',original,'999999','transfer','실패','금액 정정',expected)
    assert not s.supplier_settlement_detail(original)['voided']
    assert s.supplier_outstanding(supplier)['balance']==Decimal('50.25')
    replacement=s.replace_supplier_payment('settlement',original,'40.25','transfer','정정 메모','수기 금액 오류',expected)
    assert s.supplier_settlement_detail(original)['voided']
    assert s.supplier_settlement_detail(replacement)['amount']==Decimal('40.25')
    assert s.supplier_outstanding(supplier)['balance']==Decimal('70.50')
    with pytest.raises(ValueError,match='유효한'):
        s.replace_supplier_payment('settlement',original,'20','cash','','중복 입력',expected)


def test_individual_supplier_payment_replace_and_wrong_snapshot_leave_original(shop):
    _,s,_,supplier,purchase=shop
    payment=s.add_payment(purchase,'25.25',date.today().isoformat(),'card','첫 기록')
    row=next(r for r in s.supplier_payment_history(date.today().isoformat(),date.today().isoformat()) if r['id']==payment)
    expected={k:row[k] for k in ('date','amount','method','memo')}
    with pytest.raises(ValueError,match='바뀌었'):
        s.replace_supplier_payment('payment',payment,'10','cash','','정정',{**expected,'amount':'24'})
    new_id=s.replace_supplier_payment('payment',payment,'20.25','cash','수정','기록 정정',expected)
    records=s.supplier_payment_history(date.today().isoformat(),date.today().isoformat())
    assert next(r for r in records if r['id']==payment)['voided']
    assert next(r for r in records if r['id']==new_id)['amount']==Decimal('20.25')
    assert s.document(purchase)['balance']==Decimal('80.25')


def test_payment_access_wrong_password_keeps_identity_and_async_success(shop):
    app,s,window,_,_=shop;actor=dict(s.actor)
    with pytest.raises(ValueError):s.verify_payment_access('wrong')
    assert s.actor==actor
    dialog=PaymentAccessDialog(window);dialog.show();dialog.password.setText(PASSWORD);dialog.submit();deadline=monotonic()+10
    while dialog.busy and monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents();assert not dialog.busy and dialog.verified and dialog.result()==dialog.DialogCode.Accepted and not dialog.password.text() and s.actor==actor
    assert dialog.fields['code'].isReadOnly()


def test_payment_workspace_real_tabs_card_menu_supplier_bank_and_details(shop):
    app,s,window,supplier,purchase=shop;window.open_page('payments');page=window.current_page;app.processEvents()
    assert [page.tabs.tabText(i) for i in range(4)]==['외상매입현황','공급사별 거래내역','매입결제현황','매입 상세내역']
    assert not any(a.text()=='카드 수기결제' for a in page.payment_toolbar.actions())
    from pos2.purchase_payment_ui import PurchasePaymentDialog
    payment=PurchasePaymentDialog(window,partner_id=supplier);assert 'card' in payment.components
    assert page.start.isVisible() and page.search.isVisible()
    page.supplier_list.selectRow(0);app.processEvents();assert page.partner.currentData()==supplier and page.bank_fields['bank'].text()=='시험은행'
    page.tabs.setCurrentIndex(1)
    page.ledger_grid.selectRow(next(i for i in range(page.ledger_grid.rowCount()) if (page.ledger_grid.item(i,0).data(Qt.ItemDataRole.UserRole) or {}).get('document_id')))
    page.detail();assert page.tabs.currentIndex()==3 and page.purchase_detail_grid.rowCount()==1
    dialog=SupplierPaymentDialog(window,supplier);assert dialog.method.findData('card')>=0


def test_seasonal_skin_persistence_default_restore_and_random_does_not_change_data(shop):
    app,s,window,_,_=shop;window.open_page('settings');page=window.current_page;before=s.products();revision=s.audit_revision()
    for mode in SEASONS:
        resolved=apply_theme(mode);assert resolved==mode and app._sy_skin==mode
        from PySide6.QtGui import QPalette
        from pos2.appearance import COLORS
        assert window.palette().color(QPalette.ColorRole.Window).name().upper()==COLORS[mode][0]
    assert s.audit_revision()==revision and s.products()==before
    choices={apply_theme('random') for _ in range(8)};assert choices<=set(SEASONS) and len(choices)>1
    page.appearance_theme.setCurrentIndex(page.appearance_theme.findData('winter'));page.save()
    assert s.appearance_preferences()['theme']=='winter' and app._sy_skin=='winter'
    from pos2.settings_defaults import stage_defaults
    stage_defaults(page,['appearance']);assert s.appearance_preferences()['theme']=='winter'
    page.save();assert s.appearance_preferences()==dict(theme='default',holiday=False,snow=False,weather=False)


def test_holidays_lunar_date_and_effects_bounded_pause_no_forecast_requests(shop):
    app,s,window,_,_=shop
    from pos2.recurrence import lunar_date
    buddha=lunar_date(2026,4,8);assert special_day(buddha)=='buddha' and special_day(date(2026,12,25))=='christmas'
    assert apply_theme('summer',True,date(2026,12,25))=='christmas'
    ambient=window.ambient_effects
    assert not ambient.animation.isActive() and not ambient.clock.isActive() and not ambient.overlay.isVisible()
    ambient.configure(dict(theme='default',holiday=True,snow=True,weather=True));app.processEvents();ambient.refresh()
    assert ambient.animation.interval()==100 and ambient.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert weather_kind({'weather':'눈 · -1.0°C'})=='snow' and weather_kind({'weather':'비/눈 · 2.0°C'})=='snow'
    ambient.update_weather({'weather':'맑음 · 20.0°C'});assert ambient.badge.kind=='sun' and not ambient.animation.isActive()
    ambient.update_weather({'weather':'비 · 10.0°C'});assert ambient.badge.kind=='rain'
    event=QEvent(QEvent.Type.KeyPress);ambient.eventFilter(window,event);assert not ambient.animation.isActive()
    ambient.forecast_at=monotonic()-1801;ambient.prefs['snow']=False;ambient.refresh();assert not ambient.badge.isVisible()
    window.showMinimized();app.processEvents();ambient.refresh();assert not ambient.animation.isActive()
    ambient.stop()
