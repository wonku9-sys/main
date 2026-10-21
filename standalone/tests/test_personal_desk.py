"""Recurring calendar, encrypted family health and private popup regression tests."""
from datetime import date
from decimal import Decimal
import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox
from pos2.store import Store
from pos2.recurrence import validate_rule,occurrences,counter,lunar_date

PASSWORD='Owner-Strong-2026!'

@pytest.fixture
def store(tmp_path):
    result=Store(tmp_path/'personal.db');result.setup_admin('owner','관리자',PASSWORD)
    result.save_popup_sound_enabled(False)
    yield result
    result.close()

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

def rule(**extra):return dict(calendar='solar',repeat='yearly',event_kind='birthday',base_year=2000,month=10,day=20,leap=False,lead_days=2,leap_fallback=True,**extra)

def event(store,data=None):
    payload=rule();payload.update(data or {})
    return store.save_desk_event(dict(payload,title='생일을 기억해요',notes='케이크 준비',time='09:00',alarm=True))

def test_household_memo_can_exist_without_money_is_encrypted_and_replaced(store):
    store.setup_household('Private-Cash-2026!','Private-Cash-2026!');key=store.unlock_household('Private-Cash-2026!')
    identifier=store.save_household_memo(key,'2026-10-19','메모만 저장한 날')
    assert store.household_memos(key)[0]['body']=='메모만 저장한 날'
    assert store.save_household_memo(key,'2026-10-19','수정된 메모')==identifier
    assert store.db.execute('SELECT COUNT(*) FROM household_entries').fetchone()[0]==0
    raw=store.db.execute('SELECT ciphertext FROM household_memos').fetchone()[0]
    assert '수정된 메모'.encode() not in raw and b'2026-10-19' not in raw
    store.lock_household()
    with pytest.raises(ValueError):store.household_memos(key)

def test_theme_and_sound_preferences_are_independent_and_validated(store):
    store.save_personal_theme('diary','forest');store.save_personal_theme('household','rose')
    assert store.personal_theme('diary')=='forest' and store.personal_theme('household')=='rose'
    with pytest.raises(ValueError):store.save_personal_theme('diary','https://remote-background')
    store.save_popup_sound_enabled(True);assert store.popup_sound_enabled()
    store.save_user({'code':'staff','name':'직원','role':'staff','password':PASSWORD,'permissions':[]});store.login('staff',PASSWORD)
    assert store.personal_theme('diary')=='lavender' and store.personal_theme('household')=='cream'

def test_solar_yearly_anniversary_counter_and_feb29_policy():
    value=rule();assert occurrences(value,date(2026,1,1),date(2027,12,31))==[date(2026,10,20),date(2027,10,20)]
    assert '만 26세' in counter(value,date(2026,10,20))
    value.update(month=2,day=29)
    assert occurrences(value,date(2026,1,1),date(2026,12,31))==[date(2026,2,28)]

def test_lunar_conversion_new_year_chuseok_and_yearly_offline():
    assert lunar_date(2026,1,1)==date(2026,2,17)
    assert lunar_date(2026,8,15)==date(2026,9,25)
    value=rule();value.update(calendar='lunar',base_year=2025,month=8,day=15)
    assert occurrences(value,date(2026,1,1),date(2026,12,31))==[date(2026,9,25)]
    assert lunar_date(2026,1,1,True) is None # Converter must not silently ignore an invalid leap month.

def test_lunar_leap_month_can_skip_or_use_normal_month():
    value=rule();value.update(calendar='lunar',base_year=2023,month=2,day=1,leap=True)
    validate_rule(value)
    value['leap_fallback']=False;assert occurrences(value,date(2026,1,1),date(2026,12,31))==[]
    value['leap_fallback']=True;assert occurrences(value,date(2026,1,1),date(2026,12,31))==[lunar_date(2026,2,1)]

@pytest.mark.parametrize('changes',[{'calendar':'bad'},{'base_year':2051,'calendar':'lunar'},{'month':13},{'lead_days':366},{'event_kind':'unknown'}])
def test_bad_anniversary_settings_rejected(changes):
    data=rule();data.update(changes)
    with pytest.raises(ValueError):validate_rule(data)

def test_yearly_alert_once_each_year_and_never_regresses_to_old_missed_year(store,monkeypatch):
    monkeypatch.setattr('pos2.offline_features.now',lambda:'2026-01-01T00:00:00')
    identifier=event(store)
    assert store.due_desk_alerts('2026-10-18T08:59')==[]
    assert store.due_desk_alerts('2026-10-18T09:00')[0]['id']==identifier
    assert store.due_desk_alerts('2026-10-20T09:00')==[]
    assert store.due_desk_alerts('2027-10-18T09:00')[0]['date']=='2027-10-20'
    assert store.due_desk_alerts('2028-01-01T09:00')==[]
    assert store.due_desk_alerts('2028-10-18T09:00')[0]['date']=='2028-10-20'

def test_missed_recurrences_emit_latest_only_and_completed_series_stop(store,monkeypatch):
    monkeypatch.setattr('pos2.offline_features.now',lambda:'2026-01-01T00:00:00')
    identifier=event(store)
    alerts=store.due_desk_alerts('2029-10-20T12:00');assert len(alerts)==1 and alerts[0]['date']=='2029-10-20'
    assert store.due_desk_alerts('2029-10-20T12:01')==[]
    store.save_desk_event({'done':True},identifier)
    assert store.due_desk_alerts('2030-10-20T12:00')==[]

def test_once_event_lead_alert_and_edit_base_date_not_occurrence(store):
    identifier=event(store,{'repeat':'once','base_year':2026,'month':10,'day':20})
    assert store.due_desk_alerts('2026-10-18T09:00')[0]['id']==identifier
    assert store.due_desk_alerts('2026-10-20T09:00')==[]

@pytest.mark.parametrize('kind',['diary','household'])
def test_health_growth_pharmacy_exact_amount_encryption_and_no_ledger_effect(store,kind):
    getattr(store,'setup_'+kind)('Private-Key-2026!','Private-Key-2026!');key=getattr(store,'unlock_'+kind)('Private-Key-2026!')
    data={'category':'growth','date':'2026-10-19','title':'아이 성장','subject':'우리 아이','birth_date':'2023-10-19','height':'96.7','weight':'14.23','amount':'12.34','notes':'비밀 성장 메모'}
    identifier=store.save_health_entry(kind,key,data)
    row=store.health_entries(kind,key,'2026-10-01','2026-10-31')[0]
    assert row['amount']==Decimal('12.34') and row['height']=='96.7' and row['subject']=='우리 아이'
    raw=store.db.execute('SELECT ciphertext FROM personal_health_entries WHERE id=?',(identifier,)).fetchone()[0]
    assert '비밀 성장 메모'.encode() not in raw and '우리 아이'.encode() not in raw and b'2023-10-19' not in raw
    assert store.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==0
    assert store.db.execute('SELECT COUNT(*) FROM household_entries').fetchone()[0]==0
    getattr(store,'lock_'+kind)()
    with pytest.raises(ValueError):store.health_entries(kind,key,'2026-10-01','2026-10-31')

def test_health_appointment_alarm_is_generic_and_updated_deleted_atomically(store):
    store.setup_household();key=store.unlock_household()
    data={'category':'appointment','date':'2026-10-19','time':'10:00','title':'민감한 치료','place':'비밀 병원','notes':'민감한 병명','alarm':True}
    identifier=store.save_health_entry('household',key,data)
    event_id=store.db.execute('SELECT alarm_event_id FROM personal_health_entries').fetchone()[0]
    alarm=store.desk_events('2026-10-19','2026-10-19')[0]
    assert alarm['title']=='개인 일정 알림' and '민감' not in repr(alarm) and '비밀' not in repr(alarm)
    with pytest.raises(ValueError):store.save_health_entry('household',key,dict(data,weight='bad'),identifier)
    assert store.db.execute('SELECT id FROM desk_events').fetchone()[0]==event_id
    store.delete_health_entry('household',key,identifier)
    assert store.desk_events('2026-10-19','2026-10-19')==[]

def test_private_memos_health_and_anniversaries_backup_restore(store,monkeypatch):
    monkeypatch.setattr('pos2.offline_features.now',lambda:'2026-01-01T00:00:00')
    store.setup_household('Private-Key-2026!','Private-Key-2026!');key=store.unlock_household('Private-Key-2026!')
    store.save_household_memo(key,'2026-10-19','복원 메모');store.save_health_entry('household',key,{'title':'복원 건강','date':'2026-10-19','category':'growth'})
    event(store);store.save_personal_theme('household','forest');backup=store.create_backup()
    store.restore_backup(backup,PASSWORD);store.login('owner',PASSWORD);key=store.unlock_household('Private-Key-2026!')
    assert store.household_memos(key)[0]['body']=='복원 메모'
    assert store.health_entries('household',key,'2026-10-01','2026-10-31')[0]['title']=='복원 건강'
    assert store.desk_events('2027-10-01','2027-10-31')[0]['date']=='2027-10-20'
    assert store.personal_theme('household')=='forest'

def test_cashbook_popup_calendar_theme_and_memo_save(app,store,monkeypatch):
    from pos2.household_ui import HouseholdDialog
    store.setup_household();key=store.unlock_household();dialog=HouseholdDialog(store,key)
    try:
        assert dialog.isWindow() and dialog.calendar is not None
        dialog.memo.setPlainText('날짜별 자유 메모');assert dialog.save()
        dialog.select_day(QDate(2026,11,3));assert dialog.memo_date=='2026-11-03' and dialog.memo.toPlainText()==''
        dialog.theme.setCurrentIndex(dialog.theme.findData('rose'));assert store.personal_theme('household')=='rose'
        dialog.memo.setPlainText('취소 보호')
        monkeypatch.setattr('pos2.household_ui.ask_unsaved',lambda *_:QMessageBox.StandardButton.Cancel)
        dialog.reject();assert not dialog.closed_securely
        monkeypatch.setattr('pos2.household_ui.ask_unsaved',lambda *_:QMessageBox.StandardButton.Save)
        dialog.reject();assert dialog.closed_securely and not any(key)
        key=store.unlock_household();assert store.household_memos(key,'2026-11-03')[0]['body']=='취소 보호'
    finally:dialog.wipe();dialog.deleteLater();app.processEvents()

def test_login_shortcuts_do_not_bypass_password_or_private_lock(app,tmp_path,monkeypatch):
    from pos2.app import LoginDialog
    monkeypatch.setattr(QMessageBox,'warning',lambda *_:QMessageBox.StandardButton.Ok)
    store=Store(tmp_path/'first-login.db')
    try:
        dialog=LoginDialog(store);dialog.choose_target('diary');dialog.submit()
        assert store.actor is None # Public initial credential is insufficient.
        dialog.new_password.setText(PASSWORD);dialog.new_confirm.setText(PASSWORD);dialog.submit()
        assert dialog.selected_target=='diary' and dialog.result()==QDialog.DialogCode.Accepted
        assert not store.default_login_available() and not store.diary_exists()
        dialog.deleteLater();app.processEvents()
    finally:store.close()

def test_health_popup_scrubs_children_on_parent_lock(app,store):
    from pos2.diary_ui import DiaryDialog
    from pos2.health_ui import HealthDialog,growth_age
    store.setup_diary('Private-Key-2026!','Private-Key-2026!');key=store.unlock_diary('Private-Key-2026!');store.save_diary_music_preferences(False,6)
    parent=DiaryDialog(store,key);health=HealthDialog(store,'diary',key,parent)
    assert growth_age('2023-10-19','2026-10-19').startswith('3세 0개월')
    parent.wipe();assert health.grid.rowCount()==0 and not health.timer.isActive() and not any(key)
    parent.deleteLater();app.processEvents()

def test_schedule_popup_saves_lunar_rule_and_closes_normally(app,store):
    from pos2.home_ui import ScheduleDialog
    dialog=ScheduleDialog(store,'2026-10-19');dialog.title.setText('음력 생일')
    dialog.calendar_type.setCurrentIndex(dialog.calendar_type.findData('lunar'))
    for control,value in zip(dialog.lunar_fields,(2026,8,15)):control.setValue(value)
    dialog.repeat.setCurrentIndex(dialog.repeat.findData('yearly'));dialog.save()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert store.desk_events('2026-09-01','2026-09-30')[0]['date']=='2026-09-25'
    dialog.deleteLater();app.processEvents()
