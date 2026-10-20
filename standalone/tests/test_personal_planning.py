"""PDF/Word-reference additions: precise amounts, vault separation and live UI."""
from datetime import date
from decimal import Decimal
import sqlite3
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QDate,QCoreApplication,QEvent,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox,QLabel
from pos2.store import Store
from pos2.recovery import SCHEMA_VERSION

PW='Owner-Strong-2026!'

@pytest.fixture
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def book(tmp_path):
    s=Store(tmp_path/'new-planning.db');s.setup_admin('owner','관리자',PW);s.setup_household('Private-2026!','Private-2026!');k=s.unlock_household('Private-2026!')
    yield s,k
    s.close()

def account(s,k,name='생활 통장',balance='1000.50',**extra):
    return s.save_household_account(k,dict(name=name,opening_date='2026-01-01',opening_balance=balance,**extra))

def entry(s,k,**values):
    data=dict(date='2026-01-15',kind='expense',title='생활비',category='식비',amount='10.25');data.update(values)
    return s.save_household_entry(k,data)

def test_financial_overview_has_no_transfer_or_goal_double_count(book):
    s,k=book;a=account(s,k);b=account(s,k,'적금','-200.25');deposit=account(s,k,'묶인 예금','300.75',account_type='deposit')
    entry(s,k,account_id=a);s.save_household_transfer(k,dict(date='2026-01-16',from_account=a,to_account=deposit,amount='100.05'))
    s.save_household_plan(k,dict(kind='asset',name='전세 보증금',amount='10000.25',asset_type='property',date='2026-01-01'))
    s.save_household_plan(k,dict(kind='debt',name='남은 대출',amount='5000.75',date='2026-01-01'))
    s.save_household_plan(k,dict(kind='goal',name='비상금',amount='2000',saved_amount='99999',account_id=a,target_date='2026-12-31'))
    r=s.household_financial_overview(k,'2026-01-01','2026-01-31')
    assert r['cash_assets']==Decimal('890.20') and r['locked_assets']==Decimal('10401.05')
    assert r['debt_total']==Decimal('5201.00') and r['net_assets']==Decimal('6090.25')
    assert r['goals'][0]['saved_amount']==Decimal('890.20') and r['goals'][0]['gap']==Decimal('1109.80')
    assert r['expense_total']==Decimal('10.25')
    assert b!=deposit

def test_budget_cashflow_and_annual_report_preserve_hundredths(book):
    s,k=book;entry(s,k,category='교육',amount='100.25');entry(s,k,category='세금공과금',amount='10.05');entry(s,k,category='저축',amount='20.25');entry(s,k,amount='5.55')
    s.save_household_plan(k,dict(kind='category_budget',name='교육',month='2026-01',amount='100.00'))
    s.save_household_budget(k,'2026-01','150.55')
    r=s.household_financial_overview(k,'2026-01-01','2026-01-31')
    assert r['necessary_total']==Decimal('105.80') and r['living_total']==Decimal('5.55')
    assert r['category_budgets'][0]['available_total']==Decimal('-.25') and r['category_budgets'][0]['percent']==Decimal('100.25')
    annual=s.household_annual_report(k,2026)
    assert len(annual)==12 and annual[0]['expense_total']==Decimal('136.10') and annual[0]['available_total']==Decimal('14.45')

def test_forecast_month_end_and_end_dates_are_not_real_postings(book):
    s,k=book;account(s,k,balance='1000.25')
    s.save_household_plan(k,dict(kind='forecast',name='예상 월급',amount='100.10'))
    s.save_household_fixed_cost(k,dict(title='월 고정비',amount='30.05',monthly_day=31,start_date='2026-01-01',end_date='2026-02-28'))
    count=s.db.execute('SELECT count(*) FROM household_entries').fetchone()[0]
    r=s.household_cash_forecast(k,'2026-01-31',3)
    assert r[0]['projected_balance']==Decimal('1070.30') and r[1]['projected_balance']==Decimal('1170.40')
    assert s.db.execute('SELECT count(*) FROM household_entries').fetchone()[0]==count
    with pytest.raises(ValueError):s.household_cash_forecast(k,'2026-01-31',13)

def test_group_tags_and_ranking_do_not_duplicate_totals(book):
    s,k=book;a=account(s,k,owner='배우자');entry(s,k,account_id=a,payee='우리 마트',tags=['여행','가족']);entry(s,k,amount='3.45',payee='약국',category='의료')
    tags=s.household_custom_report(k,'2026-01-01','2026-01-31','tag')
    assert tags['expense_total']==Decimal('13.70') and sum(r['amount'] for r in tags['rows'])==Decimal('23.95')
    payees=s.household_custom_report(k,'2026-01-01','2026-01-31','payee',search='우리 마트');assert len(payees['entries'])==1
    owners=s.household_custom_report(k,'2026-01-01','2026-01-31','owner');assert {r['name'] for r in owners['rows']}=={'본인','배우자'}
    assert s.household_custom_report(k,'2026-01-01','2026-01-31','top_amount')['rows'][0]['amount']==Decimal('10.25')
    assert len(s.household_report(k,'2026-01-01','2026-01-31',search='#가족')['rows'])==1

def test_splits_are_atomic_keep_total_and_source_attachment(book):
    s,k=book;i=entry(s,k,amount='100.25');f=s.add_personal_attachment(k,'household','entry',i,'영수증.txt',b'receipt')
    with pytest.raises(ValueError,match='합계'):s.split_household_entry(k,i,[dict(category='식비',title='장보기',amount='20.20'),dict(category='생활',title='생활용품',amount='80')])
    assert len(s.household_report(k,'2026-01-01','2026-01-31')['rows'])==1
    ids=s.split_household_entry(k,i,[dict(category='식비',title='장보기',amount='20.20'),dict(category='생활',title='생활용품',amount='80.05')])
    assert ids[0]==i and len(set(ids))==2
    assert s.household_report(k,'2026-01-01','2026-01-31')['expense_total']==Decimal('100.25')
    assert s.personal_attachment_data(k,'household','entry',i,f)==b'receipt'
    with pytest.raises(ValueError,match='이미 나눈'):s.split_household_entry(k,i,[dict(category='식비',title='다시',amount='10'),dict(category='식비',title='다시',amount='10.20')])

def test_plans_encrypted_own_account_only_and_backup_restores(book):
    s,k=book;goal=s.save_household_plan(k,dict(kind='goal',name='비밀 여행 자금',amount='555.25',saved_amount='10.75',target_date='2026-12-31'))
    rows=s.db.execute('SELECT ciphertext FROM household_plans').fetchall();assert all('비밀 여행 자금'.encode() not in bytes(r[0]) for r in rows)
    backup=s.create_backup();s.delete_household_plan(k,goal);assert not s.household_plans(k)
    s.restore_backup(backup,PW);s.login('owner',PW)
    with pytest.raises(ValueError):s.household_plans(k)
    fresh=s.unlock_household('Private-2026!');assert s.household_plans(fresh)[0]['amount']==Decimal('555.25')
    s.save_user(dict(code='other',name='다른 사용자',password='Different-2026!',role='staff',permissions=[]));s.login('other','Different-2026!');s.setup_household();other=s.unlock_household();assert s.household_plans(other)==[]

def test_real_210_backup_without_new_tables_upgrades(book):
    s,k=book;backup=s.create_backup();db=sqlite3.connect(backup)
    try:
        for name in ('household_plans','work_log_files','work_log_details'):db.execute('DROP TABLE '+name)
        db.execute('PRAGMA user_version=210');db.commit()
    finally:db.close()
    assert s.inspect_backup(backup)['schema_version']==210
    s.restore_backup(backup,PW);s.login('owner',PW);assert s.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
    fresh=s.unlock_household('Private-2026!');assert s.household_plans(fresh)==[]

def test_planning_and_diary_ui_wipe_private_fields(app,book,monkeypatch):
    from pos2.household_ui import HouseholdDialog
    from pos2.diary_ui import DiaryDialog
    s,k=book;s.save_popup_sound_enabled(False);s.save_diary_music_preferences(False,0)
    d=HouseholdDialog(s,k);d.refresh();assert d.finances.planning.count()==8
    for i in range(8):d.finances.planning.setCurrentIndex(i);assert d.finances.planning.active_grid() is not None
    d.reject();assert not any(k) and not d.finances.planning.cards[0].text();d.deleteLater()
    s.setup_diary('Diary-Only-2026!','Diary-Only-2026!');key=s.unlock_diary('Diary-Only-2026!');diary=DiaryDialog(s,key)
    diary.title.setText('작은 감사');diary.tags.setText('#가족 #희망');diary.bookmark.setChecked(True);diary.insert_template();assert diary.save()
    diary.search.setText('#가족');assert diary.entries.rowCount()==1;assert '1편' in diary.stats.text()
    diary.search.setText('없는 검색');assert diary.entries.rowCount()==0
    diary.reject();assert not any(key) and diary.search.text()=='' and diary.stats.text()=='';diary.deleteLater();app.processEvents()

def test_public_lucky_requires_no_store_or_login(app):
    from pos2.lucky_numbers import open_lucky_numbers
    d=open_lucky_numbers();assert not d.isModal()
    for _ in range(6):d.page.draw();d.page.finish_draw()
    assert len(set(d.page.drawn))==6 and all(1<=n<=45 for n in d.page.drawn)
    assert len(d.page.remaining)==39 and d.page.draw_button.isEnabled()
    assert d.page.results==[sorted(d.page.drawn)]
    d.page.copy();assert '행운의 숫자' in app.clipboard().text()
    d.page.reset(False);assert d.page.drawn==[] and len(d.page.remaining)==45;d.close();assert open_lucky_numbers() is d;d.close();d.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()

def test_lucky_single_and_batch_draws_keep_five_rows_without_photo(app):
    from pos2.lucky_numbers import LuckyNumbersDialog
    d=LuckyNumbersDialog();d.show();app.processEvents();p=d.page
    try:
        assert not p.machine.image.isNull() and p.machine.image.hasAlphaChannel()
        labels=p.findChildren(QLabel)
        assert not any(label.pixmap() and not label.pixmap().isNull() for label in labels)
        assert not any(label.openExternalLinks() or '<a ' in label.text() or '사진 출처' in label.text() for label in labels)
        QTest.mouseClick(p.machine,Qt.MouseButton.LeftButton);assert p.timer.isActive()
        p.draw_five();assert p.batch_rows==0  # A second click cannot change a running draw.
        p.finish_draw();assert len(p.drawn)==1 and not p.results
        first=p.drawn[0];p.draw_six();p.finish_draw();assert len(p.results)==1 and first in p.results[0]
        original=list(p.results[0]);p.draw();p.finish_draw();assert len(p.drawn)==1 and p.results[0]==original
        partial=p.drawn[0];p.draw_five();p.finish_draw()
        assert len(p.results)==5 and p.results[0]==original and partial in p.results[1]
        for index,values in enumerate(p.results):
            assert len(values)==len(set(values))==6 and values==sorted(values) and all(1<=n<=45 for n in values)
            assert [label.text() for label in p.rows[index]]==list(map(str,values))
        assert not any(button.isEnabled() for button in (p.draw_button,p.six_button,p.five_button))
        old=[list(values) for values in p.results];p.draw();p.draw_six();p.draw_five();p.finish_draw();assert p.results==old
        p.copy();assert len(app.clipboard().text().splitlines())==6
        p.reset(False);assert p.results==[] and p.drawn==[] and p.draw_button.isEnabled()
        assert all(label.text()=='?' for values in p.rows for label in values)
        p.draw_five();p.finish_draw();assert len(p.results)==5
        d.resize(900,780);app.processEvents();assert not d.grab().isNull()
    finally:d.close();d.deleteLater();app.processEvents()

def test_lucky_close_stops_batch_without_losing_completed_rows(app):
    from pos2.lucky_numbers import LuckyNumbersDialog
    d=LuckyNumbersDialog();p=d.page
    try:
        p.draw_six();p.finish_draw();old=list(p.results[0]);p.draw_five();d.close()
        assert not p.timer.isActive() and not p.machine.running and p.results==[old]
        d.show();p.draw_six();p.finish_draw();assert len(p.results)==2 and p.results[0]==old
    finally:d.close();d.deleteLater();app.processEvents()

def logistics():
    return dict(status='done',category='입출고',customer='예시 고객사',handling_revenue='200000.25',storage_revenue='50000.50',rent_cost='20000.25',management_cost='5000.50',
                capacity='100',occupied='85',workers=[dict(name='작업자',kind='regular',regular_hours='8',overtime_hours='1.25',hourly_rate='10000.25',overtime_factor='1.5')],
                movements=[dict(activity='하역',unit='BOX',qty='500',hours='2'),dict(activity='적치',unit='PLT',qty='13',hours='1.25')])

def test_logistics_worklog_metrics_units_and_private_files(book):
    s,k=book;i=s.save_work_log(dict(date='2026-10-19',title='입출고 작업',body='확인 사항',details=logistics()))
    r=s.work_log_report('2026-10-01','2026-10-31');metrics=r['records'][0]['metrics']
    assert metrics['labor_cost']==Decimal('98752.47') and metrics['revenue_total']==Decimal('250000.75')
    assert metrics['profit']==Decimal('126247.53') and metrics['occupancy']==Decimal('85.00')
    assert metrics['productivity'][0]['per_hour']==Decimal('250.00') and r['units']=={'BOX':Decimal('500'),'PLT':Decimal('13')}
    f=s.add_work_log_file(i,'현장사진.txt',b'example');assert s.work_log_file_data(i,f)==b'example'
    with pytest.raises(ValueError):s.add_work_log_file(i,'unsafe.exe',b'no')
    backup=s.create_backup();s.delete_work_log(i);assert s.db.execute('SELECT count(*) FROM work_log_files').fetchone()[0]==0
    s.restore_backup(backup,PW);s.login('owner',PW);assert s.work_log_file_data(i,f)==b'example'
    s.save_user(dict(code='other',name='다른 직원',password='Other-Strong-2026!',role='staff',permissions=[]));s.login('other','Other-Strong-2026!')
    assert s.work_logs('2026-10-01','2026-10-31')==[]
    with pytest.raises(ValueError):s.work_log_file_data(i,f)

def test_invalid_logistics_details_roll_back_work_log(book):
    s,k=book;bad=logistics();bad['movements'][0]['unit']='혼합'
    with pytest.raises(ValueError):s.save_work_log(dict(date='2026-10-19',title='저장 금지',details=bad))
    assert s.work_logs('2026-10-01','2026-10-31')==[]

def test_logistics_worklog_ui(app,book):
    from pos2.worklog_ui import WorkLogPage
    s,k=book;s.save_work_log(dict(date=date.today().isoformat(),title='현장 기록',details=logistics()))
    page=WorkLogPage(SimpleNamespace(store=s));page.refresh();page.grid.selectRow(0);page.selection_changed()
    assert page.grid.rowCount()==1 and page.productivity.rowCount()==2 and '85.00%' in page.metrics.text()
    for i in range(3):page.tabs.setCurrentIndex(i);assert page.active_grid()
    page.deleteLater();app.processEvents()

def test_sales_comparison_history_and_refresh_choices(app,book):
    from pos2.offline_ui import OfflineReportPage,SalesHistoryPage
    s,k=book;customer=s.save_partner(dict(kind='customer',name='고객'));product=s.save_product(dict(name='과자',sale_price='100.25',tracked=False))
    for when,price in [('2026-10-19','100.25'),('2026-10-18','50.50'),('2026-10-12','25.25'),('2026-09-19','80.80')]:s.post_document(dict(kind='sale',date=when,partner_id=customer,lines=[dict(product_id=product,qty='1',unit_price=price)]))
    r=s.sales_period_comparison('sales_realtime','2026-10-19','2026-10-19');assert [v['sale_total'] for v in r]==list(map(Decimal,['100.25','50.50','25.25','80.80']))
    assert r[1]['difference']==Decimal('49.75')
    draft=s.save_draft(dict(kind='sale',date='2026-10-19',partner_id=customer,lines=[dict(product_id=product,qty='1',unit_price='2.25')]))
    assert s.sales_history('draft','2026-10-01','2026-10-31')[0]['id']==draft
    p=OfflineReportPage(SimpleNamespace(store=s),'sales_realtime');p.refresh();assert p.refresh_interval.count()==5 and p.comparison.rowCount()==4;p.timer.stop();p.deleteLater()
    history=SalesHistoryPage(SimpleNamespace(store=s),'draft');history.start.setDate(QDate(2026,10,1));history.end.setDate(QDate(2026,10,31));history.refresh();assert history.grid.rowCount()==1;history.deleteLater();app.processEvents()
