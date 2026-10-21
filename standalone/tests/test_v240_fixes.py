"""Weather, email, session and calendar fixes: all providers/delivery mocked."""
from datetime import datetime, timezone, timedelta
import json
import re
import secrets
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QCalendarWidget, QTableView, QMessageBox, QLabel

from pos2.store import Store
from pos2.online_info import DEFAULT_ONLINE, KST, fetch_online, kma_grid

PASSWORD='Owner-Strong-2026!'


@pytest.fixture
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def shop(tmp_path,monkeypatch):
    key=secrets.token_bytes(32)
    def protect(raw):
        nonce=secrets.token_bytes(12);return nonce+AESGCM(key).encrypt(nonce,raw,b'test-only')
    monkeypatch.setattr('pos2.windows_secrets.protect',protect)
    monkeypatch.setattr('pos2.windows_secrets.unprotect',lambda raw:AESGCM(key).decrypt(raw[:12],raw[12:],b'test-only'))
    s=Store(tmp_path/'fixes.db');s.setup_admin('owner','관리자',PASSWORD)
    s.save_mail_settings(dict(host='smtp.example.com',port=465,mode='ssl',username='sender@example.com',sender='sender@example.com',password='Test-App-Secret!'))
    instant=[1792400000];monkeypatch.setattr('pos2.email_recovery.time.time',lambda:instant[0])
    yield s,instant
    s.close()


def otp(job):return re.search(r'일회용 인증번호: (\d{8})',job._body)[1]


def verified(s,job):
    code=otp(job);s.complete_email_delivery(job.identifier,job._receipt,True);s.verify_recovery_email(job.identifier,code)


def weather_xml(x=60,y=127,temp='17.5',issued='202610191100'):
    return f'<wid><header><tm>{issued}</tm><x>{x}</x><y>{y}</y></header><body><data><day>0</day><hour>12</hour><temp>{temp}</temp><sky>3</sky><pty>0</pty></data></body></wid>'.encode()


def test_kma_official_grid_fallback_and_no_other_weather_source(monkeypatch):
    assert kma_grid(37.5665,126.978)==(60,127)
    assert kma_grid(35.1796,129.0756)==(98,76)
    monkeypatch.setattr('pos2.online_info.time.time',lambda:datetime(2026,10,19,11,30,tzinfo=KST).timestamp())
    calls=[]
    def read(url):
        calls.append(url)
        if 'www.weather.go.kr' in url:raise HTTPError(url,503,'temporary',{},None)
        if 'www.kma.go.kr' in url:return weather_xml()
        assert 'timeapi.io' in url
        return b'{"dateTime":"2026-10-19T11:30:00+09:00"}'
    monkeypatch.setattr('pos2.online_info._read',read)
    assert fetch_online(DEFAULT_ONLINE)=={'disabled':True} and calls==[]
    result=fetch_online(dict(DEFAULT_ONLINE,enabled=True))
    assert result['weather']=='구름 많음 · 17.5°C' and result['weather_source']=='기상청 동네예보'
    assert result['weather_at']=='10/19 12:00' and result['weather_issued']=='10/19 11:00'
    assert result['clock']==datetime(2026,10,19,11,30,tzinfo=KST).timestamp()
    assert len(calls)==3 and not any('met.no' in x or 'open-meteo' in x or 'ipapi' in x or 'weatheri' in x for x in calls)


@pytest.mark.parametrize('raw',[b'<html>unavailable</html>',b'<!DOCTYPE a [<!ENTITY x "bad">]><wid/>',weather_xml(temp='NaN'),weather_xml(x=61),weather_xml(issued='202001011100')])
def test_invalid_forecast_never_fabricates_weather_and_clock_is_independent(monkeypatch,raw):
    monkeypatch.setattr('pos2.online_info.time.time',lambda:datetime(2026,10,19,11,30,tzinfo=KST).timestamp())
    monkeypatch.setattr('pos2.online_info._read',lambda url:b'{"dateTime":"2026-10-19T11:30:00"}' if 'timeapi.io' in url else raw)
    result=fetch_online(dict(DEFAULT_ONLINE,enabled=True))
    assert result['weather_error'] and 'weather' not in result and 'clock' in result
    assert 'www.weather.go.kr' in result['weather_details']


def test_manual_weather_refresh_bypasses_cache_and_shows_source(app,shop,monkeypatch):
    from pos2.home_ui import HomePage
    s,_=shop;s.save_settings({'online_info':dict(DEFAULT_ONLINE,enabled=True)})
    home=HomePage(SimpleNamespace(store=s));home.online_enabled=True;calls=[]
    monkeypatch.setattr('pos2.home_ui.QThreadPool.globalInstance',lambda:SimpleNamespace(start=lambda worker:calls.append(worker)))
    home.online_finished(dict(config=s.online_preferences(),city='서울',weather='맑음 · 17.0°C',weather_at='10/19 12:00',weather_issued='10/19 11:00',weather_source='기상청 동네예보'))
    assert '기상청' in home.weather_source.text()
    home.refresh_online();assert calls==[]
    home.weather_refresh.click();assert len(calls)==1 and home.online_pending and not home.weather_refresh.isEnabled()
    home.online_finished(dict(config=s.online_preferences(),weather_error=True))
    assert '이전 조회' in home.weather.text() and '최신 정보가 아닙니다' in home.weather_source.text()
    home.clock_anchor=(datetime(2026,10,19,23,30,tzinfo=timezone.utc).timestamp(),__import__('time').monotonic())
    home.update_clock();assert '화요일' in home.clock.text() and '오전 08:30' in home.clock.text()
    home.clock_timer.stop();home.online_timer.stop();home.deleteLater();app.processEvents()


def test_recovery_email_change_requires_password_new_code_and_invalidates_old_codes(shop):
    s,clock=shop;verified(s,s.prepare_email_code('bind',email='first@example.com',current_password=PASSWORD));clock[0]+=61
    old=s.prepare_email_code('login_reset','owner',email='first@example.com');old_code=otp(old);s.complete_email_delivery(old.identifier,old._receipt,True);clock[0]+=61
    with pytest.raises(ValueError,match='비밀번호'):s.prepare_email_code('bind',email='new@example.com',current_password='Wrong-Password!')
    change=s.prepare_email_code('bind',email='new@example.com',current_password=PASSWORD)
    assert s.recovery_email_status()['email']=='first@example.com'
    with pytest.raises(ValueError):s.verify_recovery_email(change.identifier,otp(change))
    verified(s,change);assert s.recovery_email_status()['email']=='new@example.com'
    with pytest.raises(ValueError):s.reset_password_by_email(old.identifier,old_code,'Different-Strong-2026!','Different-Strong-2026!')
    clock[0]+=61
    with pytest.raises(ValueError,match='주소'):s.prepare_email_code('login_reset','owner',email='first@example.com')
    fresh=s.prepare_email_code('login_reset','owner',email='new@example.com');assert fresh._recipient=='new@example.com'


def test_email_change_keeps_encrypted_diary_but_requires_new_recovery_enrolment(shop):
    s,clock=shop;verified(s,s.prepare_email_code('bind',email='first@example.com',current_password=PASSWORD));clock[0]+=61
    s.setup_diary('Private-Diary-2026!','Private-Diary-2026!');key=s.unlock_diary('Private-Diary-2026!');s.save_diary_entry(key,dict(date='2026-10-19',title='나의 기록',body='유지해야 할 내용'))
    enrol=s.prepare_email_code('diary_enable',current_password='Private-Diary-2026!');code=otp(enrol);s.complete_email_delivery(enrol.identifier,enrol._receipt,True);s.verify_private_email_recovery('diary',enrol.identifier,code);clock[0]+=61
    before=[tuple(r) for r in s.db.execute('SELECT * FROM diary_entries')]
    verified(s,s.prepare_email_code('bind',email='new@example.com',current_password=PASSWORD))
    assert not s.recovery_email_status()['diary'] and before==[tuple(r) for r in s.db.execute('SELECT * FROM diary_entries')]
    key=s.unlock_diary('Private-Diary-2026!');assert s.diary_entries(key)[0]['body']=='유지해야 할 내용'


def test_email_ui_has_address_and_setup_and_reports_send_failure(app,shop,monkeypatch):
    from pos2.email_ui import EmailCodeDialog, RecoveryEmailDialog
    s,_=shop;messages=[];workers=[]
    monkeypatch.setattr('pos2.email_ui.QThreadPool.globalInstance',lambda:SimpleNamespace(start=lambda worker:workers.append(worker)))
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:messages.append(args[-1]))
    dialog=EmailCodeDialog(s,'bind');dialog.email.setText('owner@example.com');dialog.current.setText(PASSWORD);dialog.send_button.click()
    assert dialog.sending and workers and dialog.email.text()=='owner@example.com'
    dialog.sent(False,'발송 계정 인증에 실패했습니다.')
    assert not dialog.sending and dialog.send_button.isEnabled() and '실패' in dialog.status.text() and not dialog.delivery_ok
    dialog.verify();assert messages and not s.recovery_email_status()['verified']
    dialog.clear_secrets();dialog.deleteLater()
    recovery=RecoveryEmailDialog(s);assert not recovery.email.isReadOnly() and recovery.settings_button.isEnabled();recovery.deleteLater()
    s.logout();reset=EmailCodeDialog(s,'login_reset',user_code='owner');assert reset.email and not reset.email.isReadOnly() and not reset.settings_button.isEnabled();reset.deleteLater();app.processEvents()


def test_unexpected_mail_worker_failure_still_emits_result(app):
    from pos2.email_ui import MailWorker
    class Job:
        def send(self):raise RuntimeError('do not expose internal exception')
    worker=MailWorker(Job());results=[];worker.signals.finished.connect(lambda ok,message:results.append((ok,message)));worker.run()
    assert results and results[0][0] is False and 'do not expose' not in results[0][1]


@pytest.mark.parametrize('kind',['diary','household'])
def test_private_popup_close_retains_one_session_but_logout_or_explicit_lock_wipes(app,shop,kind):
    from pos2.private_session import cached_key
    from pos2.diary_ui import DiaryDialog
    from pos2.household_ui import HouseholdDialog
    s,_=shop;getattr(s,'setup_'+kind)('Private-Key-2026!','Private-Key-2026!')
    if kind=='diary':s.save_diary_music_preferences(False,6)
    key=getattr(s,'unlock_'+kind)('Private-Key-2026!')
    cls=DiaryDialog if kind=='diary' else HouseholdDialog
    first=cls(s,key);first.reject();assert not any(key) and cached_key(s,kind) is not None
    reopened=cls(s,cached_key(s,kind));reopened.lock_close();assert cached_key(s,kind) is None
    assert first.findChild(QLabel,'dialogTitle').text() if kind=='diary' else first.findChild(QLabel,'personalHeading').text()=='나의 가계부'
    reopened.deleteLater();first.deleteLater()
    from pos2.private_session import remember_key
    key=getattr(s,'unlock_'+kind)('Private-Key-2026!');remember_key(s,kind,key);held=s._private_session_keys[kind];s.logout()
    assert not any(held) and not s._private_session_keys
    s.login('owner',PASSWORD);assert cached_key(s,kind) is None
    app.processEvents()


def test_calendar_right_click_resolves_real_day_including_other_month(app):
    from pos2.calendar_actions import calendar_date_at,attach_calendar_menu
    c=QCalendarWidget();c.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader);c.setFirstDayOfWeek(Qt.DayOfWeek.Monday);c.setCurrentPage(2026,10);c.show();app.processEvents();view=c.findChild(QTableView,'qt_calendar_calendarview')
    point=view.visualRect(view.model().index(1,0)).center();assert calendar_date_at(c,point)==QDate(2026,9,28)
    point=view.visualRect(view.model().index(5,6)).center();assert calendar_date_at(c,point)==QDate(2026,11,1)
    selected=[];attach_calendar_menu(c,lambda day,pos:selected.append(day));view.viewport().customContextMenuRequested.emit(point);assert selected==[QDate(2026,11,1)]
    c.close();c.deleteLater();app.processEvents()


def test_calendar_day_query_alarm_toggle_edit_delete_are_real(app,shop,monkeypatch):
    from pos2.calendar_actions import DayScheduleDialog
    s,_=shop;item=s.save_desk_event(dict(date='2026-10-19',time='09:00',title='할 일',notes='확인'))
    s.save_desk_event(dict(date='2026-10-20',time='09:00',title='다른 날짜'))
    d=DayScheduleDialog(s,'2026-10-19');assert d.grid.rowCount()==1;d.grid.selectRow(0);d.toggle_alarm();assert s.desk_events('2026-10-19','2026-10-19')[0]['alarm']
    d.grid.selectRow(0);d.toggle_done();assert s.desk_events('2026-10-19','2026-10-19')[0]['done']
    monkeypatch.setattr(QMessageBox,'question',lambda *_:QMessageBox.StandardButton.Yes);d.grid.selectRow(0);d.delete();assert not s.desk_events('2026-10-19','2026-10-19') and len(s.desk_events('2026-10-20','2026-10-20'))==1
    d.deleteLater();app.processEvents()


def test_sy_logo_and_brand_are_real_images(app):
    from pos2.branding import LOGO,app_icon,brand_widget
    from PySide6.QtGui import QImage
    image=QImage(str(LOGO));assert not image.isNull() and image.hasAlphaChannel() and image.pixelColor(0,0).alpha()==0
    widget=brand_widget();assert not widget.findChild(QLabel,'syLogo').pixmap().isNull() and not app_icon().isNull();widget.deleteLater();app.processEvents()
