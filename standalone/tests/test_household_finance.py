"""Real encrypted cashbook flows; no banks, clipboard monitoring or SMS calls."""
from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication

from pos2.store import Store
from pos2.household_parse import parse_notification,normalize_tags


@pytest.fixture
def book(tmp_path):
    store=Store(tmp_path/'finance.db');store.setup_admin('owner','관리자','Owner-Strong-2026!')
    store.setup_household('Private-2026!','Private-2026!');key=store.unlock_household('Private-2026!')
    yield store,key
    store.close()


def account(store,key,name,amount='0.00'):
    return store.save_household_account(key,dict(name=name,bank='테스트은행',opening_date='2026-01-01',opening_balance=amount))


def entry(store,key,**data):
    return store.save_household_entry(key,dict(date='2026-01-10',kind='expense',title='생활비',category='생활',amount='10.25',**data))


def test_balances_transfer_has_zero_income_expense_impact(book):
    s,k=book;a=account(s,k,'급여 통장','1000.25');b=account(s,k,'저축 통장','-10.50')
    entry(s,k,account_id=a)
    transfer=s.save_household_transfer(k,dict(date='2026-01-11',from_account=a,to_account=b,amount='100.33'))
    data=s.household_dashboard(k,'2026-01-01','2026-01-31')
    balances={r['id']:r['balance'] for r in data['accounts']}
    assert balances[a]==Decimal('889.67') and balances[b]==Decimal('89.83')
    assert data['balance']==Decimal('979.50') and data['expense_total']==Decimal('10.25') and data['income_total']==0
    assert s.household_report(k,'2026-01-01','2026-01-31',account_id=a)['closing_balance']==Decimal('889.67')
    s.delete_household_transfer(k,transfer)
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['balance']==Decimal('979.50')


def test_opening_later_in_period_is_balance_not_income(book):
    s,k=book;s.save_household_account(k,dict(name='신규',opening_date='2026-02-15',opening_balance='100.50'))
    r=s.household_report(k,'2026-02-01','2026-02-28')
    assert r['opening_balance']==0 and r['closing_balance']==Decimal('100.50') and r['income_total']==0
    assert r['rows'][0]['kind']=='opening'
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['balance']==0


def test_opening_immutable_after_usage_and_archived_balance_retained(book):
    s,k=book;a=account(s,k,'사용 통장','123.45');entry(s,k,account_id=a)
    old=s.household_accounts(k)[0]
    with pytest.raises(ValueError,match='시작 잔액'):s.save_household_account(k,dict(old,opening_balance='999.00'),a)
    s.save_household_account(k,dict(old,active=False),a)
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['balance']==Decimal('113.20')
    with pytest.raises(ValueError,match='보관'):entry(s,k,account_id=a)


def test_transaction_cannot_predate_account_and_invalid_transfer_is_atomic(book):
    s,k=book;a=account(s,k,'통장','50.00')
    with pytest.raises(ValueError):s.save_household_entry(k,dict(date='2025-12-31',kind='income',title='이전',amount=1,account_id=a))
    with pytest.raises(ValueError):s.save_household_transfer(k,dict(date='2026-01-11',from_account=a,to_account=a,amount='1.25'))
    assert s.household_transfers(k)==[]
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['balance']==50


def test_vehicle_cost_is_same_cashbook_entry_edit_delete_updates_both(book):
    s,k=book;a=account(s,k,'생활 통장','100000.00')
    car=s.save_household_vehicle(k,dict(name='가족 자동차',plate='12가3456',model='승용차'))
    expense=entry(s,k,account_id=a,vehicle_id=car,vehicle_type='fuel',liters='25.123',odometer='12345.6')
    rows=s.household_vehicle_history(k,car,'2026-01-01','2026-01-31')
    assert len(rows)==1 and rows[0]['id']==expense and rows[0]['amount']==Decimal('10.25')
    assert s.db.execute('SELECT count(*) FROM household_entries').fetchone()[0]==1
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['vehicles'][0]['expense_total']==Decimal('10.25')
    s.save_household_entry(k,dict(rows[0],amount='15.35'),expense)
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['expense_total']==Decimal('15.35')
    s.delete_household_entry(k,expense)
    assert s.household_vehicle_history(k,car,'2026-01-01','2026-01-31')==[]
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['balance']==Decimal('100000.00')


@pytest.mark.parametrize('bad',[dict(vehicle_type='unknown'),dict(vehicle_type='insurance',liters='1'),dict(liters='NaN'),dict(odometer='-1'),dict(liters='1.0001'),dict(kind='income')])
def test_invalid_vehicle_metadata_never_posts(book,bad):
    s,k=book;car=s.save_household_vehicle(k,dict(name='자동차'))
    data=dict(date='2026-01-10',title='주유',kind='expense',amount='123.45',vehicle_id=car,vehicle_type='fuel');data.update(bad)
    with pytest.raises(ValueError):s.save_household_entry(k,data)
    assert s.db.execute('SELECT count(*) FROM household_entries').fetchone()[0]==0


def fixed(s,k,**data):
    payload=dict(title='자동차 보험',category='보험',amount='123.45',monthly_day='31',start_date='2026-01-01');payload.update(data)
    return s.save_household_fixed_cost(k,payload)


def test_fixed_month_end_exactly_once_receipt_survives_entry_deletion(book):
    s,k=book;a=account(s,k,'자동이체');car=s.save_household_vehicle(k,dict(name='보험 차량'))
    rule=fixed(s,k,account_id=a,vehicle_id=car,vehicle_type='insurance')
    assert s.apply_household_fixed_costs(k,'2026-03-31')==3
    rows=s.household_vehicle_history(k,car,'2026-01-01','2026-03-31')
    assert [r['date'] for r in rows]==['2026-01-31','2026-02-28','2026-03-31']
    assert s.apply_household_fixed_costs(k,'2026-03-31')==0
    assert s.household_dashboard(k,'2026-01-01','2026-03-31')['expense_total']==Decimal('370.35')
    s.delete_household_entry(k,rows[0]['id'])
    assert s.apply_household_fixed_costs(k,'2026-03-31')==0
    assert len(s.household_vehicle_history(k,car,'2026-01-01','2026-03-31'))==2
    original=s.household_fixed_costs(k)[0];s.save_household_fixed_cost(k,dict(original,amount='200.99'),rule)
    assert s.apply_household_fixed_costs(k,'2026-04-30')==1
    assert s.household_report(k,'2026-04-01','2026-04-30')['expense_total']==Decimal('200.99')
    assert s.household_report(k,'2026-02-01','2026-02-28')['expense_total']==Decimal('123.45')


def test_fixed_stopping_range_and_locked_vault(book):
    s,k=book;rule=fixed(s,k,monthly_day='15',start_date='2026-02-16',end_date='2026-03-31')
    assert s.apply_household_fixed_costs(k,'2026-02-28')==0
    assert s.apply_household_fixed_costs(k,'2026-04-30')==1
    old=s.household_fixed_costs(k)[0];s.save_household_fixed_cost(k,dict(old,active=False),rule)
    assert s.apply_household_fixed_costs(k,'2026-10-01')==0
    s.lock_household()
    with pytest.raises(ValueError):s.apply_household_fixed_costs(k,'2026-10-01')


def test_fixed_no_future_posting_and_invalid_later_rule_rolls_back_all(book):
    s,k=book;fixed(s,k)
    with pytest.raises(ValueError):s.apply_household_fixed_costs(k,'2099-01-01')
    fixed(s,k,start_date='1900-01-01')
    with pytest.raises(ValueError,match='10년'):s.apply_household_fixed_costs(k,'2026-03-31')
    assert s.db.execute('SELECT count(*) FROM household_entries').fetchone()[0]==0
    assert s.db.execute('SELECT count(*) FROM household_fixed_runs').fetchone()[0]==0


def test_accounts_cars_rules_and_tags_encrypted_and_private(book):
    s,k=book;a=account(s,k,'금융비밀통장');car=s.save_household_vehicle(k,dict(name='비밀차량',plate='12가3456'))
    fixed(s,k,title='비밀보험계약',account_id=a)
    entry(s,k,account_id=a,vehicle_id=car,vehicle_type='repair',tags='#비밀여행 #가족 #비밀여행')
    records=s.household_report(k,'2026-01-01','2026-01-31',search='비밀여행')['rows']
    assert len(records)==1 and records[0]['tags']==['비밀여행','가족']
    assert all(word.encode() not in s.path.read_bytes() for word in ['금융비밀통장','비밀차량','12가3456','비밀보험계약','비밀여행'])
    s.save_user(dict(code='other',name='다른 사용자',password='Other-Strong-2026!',role='staff',permissions=[]))
    s.login('other','Other-Strong-2026!');s.setup_household();other=s.unlock_household()
    assert s.household_accounts(other)==[] and s.household_vehicles(other)==[] and s.household_fixed_costs(other)==[]
    with pytest.raises(ValueError):s.household_dashboard(k,'2026-01-01','2026-01-31')


def test_finance_round_trips_backup_and_key_lock(book):
    s,k=book;a=account(s,k,'복원 통장','500.55');fixed(s,k,account_id=a);s.apply_household_fixed_costs(k,'2026-03-31')
    backup=s.create_backup();s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!')
    with pytest.raises(ValueError):s.household_accounts(k)
    k=s.unlock_household('Private-2026!')
    assert s.household_dashboard(k,'2026-01-01','2026-03-31')['balance']==Decimal('130.20')
    assert s.apply_household_fixed_costs(k,'2026-03-31')==0


def test_real_v208_shape_without_any_new_tables_restores_losslessly(tmp_path):
    from pos2.household_finance import FINANCE_TABLES
    from pos2.diary import _seal
    import json
    old=Store(tmp_path/'prior-v230rc1.db');old.setup_admin('owner','이전 관리자','Owner-Strong-2026!');old.setup_household('Private-2026!','Private-2026!');key=old.unlock_household('Private-2026!')
    content=dict(date='2026-01-01',kind='income',title='이전 가계부',category='급여',amount=12345,memo='원형 보존',created_at='2026-01-01T09:00:00')
    old.db.execute('INSERT INTO household_entries VALUES(?,?,?,?,?)',('old-entry',old.actor['id'],_seal(key,json.dumps(content,ensure_ascii=False).encode(),old._household_aad(old.actor['id'],'old-entry')),content['created_at'],content['created_at']))
    for table in ['personal_attachments','personal_health_receipts','inspiration_history','shared_requests','household_fixed_runs','household_fixed_alerts','household_vehicle_alerts']+['household_'+name for name in FINANCE_TABLES]:old.db.execute('DROP TABLE '+table)
    old.db.execute('PRAGMA user_version=208');old.close()
    current=Store(tmp_path/'new.db');current.setup_admin('target','현재 관리자','Target-Strong-2026!')
    try:
        assert current.inspect_backup(tmp_path/'prior-v230rc1.db')['schema_version']==208
        current.restore_backup(tmp_path/'prior-v230rc1.db','Target-Strong-2026!');current.login('owner','Owner-Strong-2026!');key=current.unlock_household('Private-2026!')
        assert current.household_report(key,'2026-01-01','2026-01-31')['closing_balance']==Decimal('123.45')
        assert current.household_accounts(key)==[]
    finally:current.close()


def test_paste_ignores_balance_and_requires_review_for_ambiguous_cancel():
    p=parse_notification('은행 출금 12,345.67원\n2026/01/10 15:23\n잔액 1,000,000원 #교통',date(2026,1,11))
    assert p['amount']=='12345.67' and p['kind']=='expense' and p['date']=='2026-01-10' and p['tags']==['교통']
    assert parse_notification('입금 1,234원\n잔액 10,000원',date(2026,1,11))['kind']=='income'
    assert parse_notification('승인 1,000원 승인 2,000원')['amount']==''
    assert parse_notification('승인취소 1,234원')['kind']==''
    assert parse_notification('출금 예정 1,234원')['kind']==''
    assert parse_notification('승인 01/10 1000원',date(2026,1,11))['warnings']
    assert parse_notification('아무 숫자도 없음')['amount']==''
    with pytest.raises(ValueError):normalize_tags('#a '*0+ '#'+ 'a'*31)


def test_cashbook_ui_charts_calendar_accounts_vehicle_wipe(book,tmp_path):
    app=QApplication.instance() or QApplication([])
    s,k=book;a=account(s,k,'화면 통장','100.55');car=s.save_household_vehicle(k,dict(name='화면 차량'))
    entry(s,k,account_id=a,vehicle_id=car,vehicle_type='fuel',tags='#가족')
    from pos2.household_ui import HouseholdDialog
    from PySide6.QtCore import QDate
    from pos2.personal_schedule_ui import PersonalScheduleDialog,message_draft
    dialog=HouseholdDialog(s,k);dialog.start.setDate(QDate(2026,1,1));dialog.end.setDate(QDate(2026,1,31));dialog.refresh();dialog.show();app.processEvents()
    assert dialog.finances.count()==6 and dialog.finances.accounts.rowCount()==2
    assert dialog.finances.planning.count()==8
    assert dialog.finances.vehicles.rowCount()==1
    for index in range(5):dialog.finances.setCurrentIndex(index);app.processEvents();assert not dialog.grab().isNull()
    assert len(dialog.finances.pie.values)==1
    schedule=PersonalScheduleDialog(s,dialog);schedule.show();app.processEvents();schedule.reject();schedule.deleteLater()
    assert '생일' in message_draft(dict(date='2026-10-19',title='생일',notes='축하해요'))
    dialog.wipe();assert dialog.finances.pie.values==[] and dialog.finances.vehicles.rowCount()==0 and dialog.calendar.spending=={}
    dialog.close();dialog.deleteLater();app.processEvents()
