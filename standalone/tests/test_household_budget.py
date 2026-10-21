from datetime import date
from decimal import Decimal
import pytest
from pos2.store import Store


@pytest.fixture
def book(tmp_path):
    s=Store(tmp_path/'budget.db');s.setup_admin('owner','관리자','Owner-Strong-2026!');s.setup_household();k=s.unlock_household()
    yield s,k
    s.close()


def spend(s,k,value,amount,category='식비'):
    return s.save_household_entry(k,dict(date=value,kind='expense',title='지출',category=category,amount=amount))


def test_budget_exact_ratio_includes_all_accounts_excludes_transfers_income_and_future(book):
    s,k=book;s.save_household_budget(k,'2026-02','1000.00')
    a=s.save_household_account(k,dict(name='통장',opening_date='2026-01-01',opening_balance='100000.00'))
    spend(s,k,'2026-02-01','100.25');spend(s,k,'2026-02-15','150.25');spend(s,k,'2026-02-28','900.00')
    s.save_household_entry(k,dict(date='2026-02-15',kind='income',title='급여',amount='999.99'))
    s.save_household_transfer(k,dict(date='2026-02-15',from_account=a,to_account='',amount='1000.00'))
    r=s.household_budget(k,'2026-02-15')
    assert r['amount']==Decimal('1000.00') and r['expense_total']==Decimal('250.50')
    assert r['percent']==Decimal('25.05') and r['balance']==Decimal('749.50')
    s.save_household_budget(k,'2026-02','100.00');r=s.household_budget(k,'2026-02-15')
    assert r['percent']==Decimal('250.50') and r['balance']==Decimal('-150.50')
    s.save_household_budget(k,'2026-02',0);assert s.household_budget(k,'2026-02-15')['percent']==0


def test_comparison_previous_full_month_and_same_elapsed_days_top_category(book):
    s,k=book
    spend(s,k,'2026-01-01','20.25');spend(s,k,'2026-01-31','200.00');spend(s,k,'2026-02-10','30.50');spend(s,k,'2026-02-15','100.75','교통')
    spend(s,k,'2026-02-20','999.00')
    r=s.household_spending_comparison(k,'2026-02-15')
    assert r['expense_total']==Decimal('131.25') and r['previous_total']==Decimal('220.25')
    assert r['comparable_total']==Decimal('20.25') and r['difference']==Decimal('111.00')
    assert r['top_categories'][0]['name']=='교통' and r['top_categories'][0]['amount']==Decimal('100.75')
    assert r['comparable_end']=='2026-01-15'
    assert s.household_spending_comparison(k,'2026-01-15')['percent_change'] is None


def test_comparison_january_rollover_and_february_clamping(book):
    s,k=book;spend(s,k,'2025-12-15','20.00');spend(s,k,'2026-01-15','10.00')
    r=s.household_spending_comparison(k,'2026-01-15');assert r['previous_month']=='2025-12' and r['percent_change']==Decimal('-50.00')
    assert s.household_spending_comparison(k,'2026-03-31')['comparable_end']=='2026-02-28'


def test_monthly_fixed_alerts_fire_once_and_reappear_next_month(book):
    s,k=book;s.save_household_fixed_cost(k,dict(title='보험료',amount='123.45',start_date='2026-01-01',monthly_day='31'))
    assert s.due_household_fixed_alerts(k,'2026-01-30')==[]
    rows=s.due_household_fixed_alerts(k,'2026-01-31');assert len(rows)==1 and rows[0]['amount']==Decimal('123.45')
    assert s.due_household_fixed_alerts(k,'2026-01-31')==[]
    assert s.due_household_fixed_alerts(k,'2026-02-27')==[]
    assert s.due_household_fixed_alerts(k,'2026-02-28')[0]['date']=='2026-02-28'
    assert s.db.execute('SELECT COUNT(*) FROM household_entries').fetchone()[0]==0
    s.lock_household()
    with pytest.raises(ValueError):s.due_household_fixed_alerts(k,'2026-03-31')
    k=s.unlock_household();assert s.due_household_fixed_alerts(k,'2026-04-01')[0]['date']=='2026-03-31'
    assert s.due_household_fixed_alerts(k,'2026-04-01')==[]


def test_budget_and_alert_receipts_survive_backup_and_wrong_keys_fail(book):
    s,k=book;s.save_household_budget(k,'2026-01','123.45');s.save_household_fixed_cost(k,dict(title='통신비',amount='50.50',start_date='2026-01-01',monthly_day='10'))
    assert len(s.due_household_fixed_alerts(k,'2026-01-10'))==1
    backup=s.create_backup();s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!');k=s.unlock_household()
    assert s.household_budget(k,'2026-01-10')['amount']==Decimal('123.45') and s.due_household_fixed_alerts(k,'2026-01-10')==[]
    with pytest.raises(ValueError):s.household_budget(bytearray(32),'2026-01-10')
    for month in ['2026-13','2026-1','no-month']:
        with pytest.raises(ValueError):s.save_household_budget(k,month,'100.00')


def test_local_classification_defaults_custom_override_disable_and_manual_choice(book):
    s,k=book
    assert s.suggest_household_category(k,'행복 주유소 결제','expense')['category']=='차량'
    assert s.suggest_household_category(k,'9월 급여 입금','income')['category']=='급여'
    assert s.suggest_household_category(k,'주유 결제','income')['category']==''
    identifier=s.save_household_category_rule(k,dict(category='여행 차량',keywords='행복 주유소, 렌터카',priority='1',kind='expense'))
    assert s.suggest_household_category(k,'행복 주유소 결제','expense')['category']=='여행 차량'
    old=next(r for r in s.household_category_rules(k) if r['id']==identifier)
    s.save_household_category_rule(k,dict(old,active=False),identifier)
    assert s.suggest_household_category(k,'행복 주유소 결제','expense')['category']=='차량'
    default=next(r for r in s.household_category_rules(k) if r.get('builtin')=='fuel')
    s.save_household_category_rule(k,dict(default,active=False),default['id'])
    assert s.suggest_household_category(k,'행복 주유소 결제','expense')['category']==''
    s.save_household_category_rule(k,dict(category='교통비',keywords='택시',priority='5',kind='expense'))
    first=s.save_household_entry(k,dict(date='2026-01-01',kind='expense',title='택시 결제',amount='10.25',category='기타',auto_category=True))
    second=s.save_household_entry(k,dict(date='2026-01-01',kind='expense',title='택시 결제',amount='20.25',category='직접 분류',auto_category=True))
    rows={r['id']:r for r in s.household_report(k,'2026-01-01','2026-01-31')['rows']}
    assert rows[first]['category']=='교통비' and rows[second]['category']=='직접 분류'


def test_budget_bar_caps_only_drawing_and_comparison_marks_largest(book):
    from PySide6.QtWidgets import QApplication
    from pos2.household_ui import HouseholdDialog
    app=QApplication.instance() or QApplication([]);s,k=book;today=date.today().isoformat()
    s.save_household_budget(k,today[:7],'100.00');spend(s,k,today,'125.50','가장 큰 분류')
    dialog=HouseholdDialog(s,k);dialog.show();app.processEvents()
    try:
        assert dialog.budget_bar.value()==10000
        assert '125.50%' in dialog.budget_label.text() and '초과 25.50원' in dialog.budget_label.text()
        assert '가장 큰 분류' in dialog.comparison.text()
    finally:dialog.wipe();dialog.close();dialog.deleteLater();app.processEvents()
