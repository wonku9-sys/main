from decimal import Decimal
import pytest
from pos2.store import Store


@pytest.fixture
def car(tmp_path):
    s=Store(tmp_path/'car.db');s.setup_admin('owner','관리자','Owner-Strong-2026!');s.setup_household();k=s.unlock_household();identifier=s.save_household_vehicle(k,{'name':'가족차'})
    yield s,k,identifier
    s.close()


def fuel(s,k,car,when,liters,odo,full):
    return s.save_household_entry(k,dict(date=when,kind='expense',title='주유',amount='50000.25',vehicle_id=car,vehicle_type='fuel',liters=liters,odometer=odo,full_tank=full))


def test_full_to_full_excludes_start_volume_includes_partial_fills(car):
    s,k,c=car;fuel(s,k,c,'2026-01-01','40','1000',True);fuel(s,k,c,'2026-01-05','10','1100',False);fuel(s,k,c,'2026-01-10','30','1500',True)
    r=s.household_vehicle_report(k,c,'2026-01-01','2026-01-31')
    assert r['liters']==Decimal('40') and r['distance']==Decimal('500') and r['km_per_liter']==Decimal('12.50')
    assert r['expense_total']==Decimal('150000.75') and len(r['segments'])==1


def test_unknown_quantity_or_ambiguous_same_day_never_invents_economy(car):
    s,k,c=car;fuel(s,k,c,'2026-01-01','40','1000',True)
    s.save_household_entry(k,dict(date='2026-01-05',kind='expense',title='주유량 모름',amount='1000.25',vehicle_id=c,vehicle_type='fuel'))
    fuel(s,k,c,'2026-01-10','30','1500',True)
    assert s.household_vehicle_report(k,c,'2026-01-01','2026-01-31')['km_per_liter'] is None


def test_insurance_payment_exactly_once_cancel_and_reenter(car):
    s,k,c=car;a=s.save_household_account(k,dict(name='통장',opening_date='2026-01-01',opening_balance='1000.00'))
    task=s.save_household_vehicle_obligation(k,dict(vehicle_id=c,title='자동차 보험',obligation_kind='insurance',due_date='2026-01-10',amount='123.45'))
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['expense_total']==0
    posted=s.complete_household_vehicle_obligation(k,task,'2026-01-10',a)
    assert s.complete_household_vehicle_obligation(k,task,'2026-01-10',a)==posted
    assert s.household_dashboard(k,'2026-01-01','2026-01-31')['balance']==Decimal('876.55')
    with pytest.raises(ValueError):s.delete_household_entry(k,posted)
    s.void_household_vehicle_obligation(k,task);assert s.household_dashboard(k,'2026-01-01','2026-01-31')['balance']==1000
    s.complete_household_vehicle_obligation(k,task,'2026-01-11',a)
    assert s.db.execute('SELECT COUNT(*) FROM household_entries').fetchone()[0]==1


def test_free_inspection_routes_checks_and_mileage_alert(car):
    s,k,c=car
    s.save_household_vehicle_log(k,dict(vehicle_id=c,date='2026-01-01',log_kind='drive',title='출근',odometer='20000',distance='30.25',departure='출발',destination='회사',route='우회로',checks={'tires':'ok','brakes':'needs'}))
    task=s.save_household_vehicle_obligation(k,dict(vehicle_id=c,title='엔진오일 점검',obligation_kind='maintenance',due_km='19999',amount=0))
    assert len(s.due_household_vehicle_alerts(k))==1 and s.due_household_vehicle_alerts(k)==[]
    s.complete_household_vehicle_obligation(k,task,'2026-01-10')
    assert s.db.execute('SELECT COUNT(*) FROM household_entries').fetchone()[0]==0
    assert len(s.household_vehicle_logs(k,c,'2026-01-01','2026-01-31'))==2
    s.void_household_vehicle_obligation(k,task);assert len(s.household_vehicle_logs(k,c,'2026-01-01','2026-01-31'))==1


def test_vehicle_obligations_reports_widgets_and_backup(car):
    from PySide6.QtWidgets import QApplication
    from pos2.vehicle_management_ui import VehicleObligationsDialog,VehicleReportDialog
    app=QApplication.instance() or QApplication([]);s,k,c=car
    s.save_household_vehicle_obligation(k,dict(vehicle_id=c,title='자동차세',obligation_kind='tax',due_date='2026-01-10',amount='123.45'))
    for cls in (VehicleObligationsDialog,VehicleReportDialog):
        d=cls(s,k,c);d.show();app.processEvents();assert not d.grab().isNull();d.reject();d.deleteLater()
    backup=s.create_backup();s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!');k=s.unlock_household()
    assert s.household_vehicle_obligations(k,c)[0]['amount']==Decimal('123.45');app.processEvents()
