from decimal import Decimal
import pytest
from PySide6.QtWidgets import QApplication
from pos2.store import Store


@pytest.fixture
def private(tmp_path):
    s=Store(tmp_path/'health.db');s.setup_admin('owner','관리자','Owner-Strong-2026!');s.setup_household('Health-Private-2026!','Health-Private-2026!');k=s.unlock_household('Health-Private-2026!')
    yield s,k
    s.close()


def record(s,k,category,**extra):
    values=dict(date='2026-01-10',category=category,title='개인 기록',subject='나');values.update(extra)
    return s.save_health_entry('household',k,values)


def test_manual_nutrition_water_exercise_plans_and_goals_are_separate(private):
    s,k=private
    record(s,k,'weight',weight='70.25',height='175');record(s,k,'goal',target_weight='68.5',target_water_ml='1800',target_calories='2000',goal_date='2026-04-01')
    record(s,k,'meal',calories='500.25',protein_g='25.5',carbs_g='60.5',fat_g='15',sodium_mg='300.5',food_items='밥과 반찬',meal_slot='lunch')
    record(s,k,'water',water_ml='250');record(s,k,'water',water_ml='300.5')
    record(s,k,'exercise',exercise_type='요가',duration_minutes='30.5',burned_calories='110')
    record(s,k,'routine',exercise_type='요가',duration_minutes='999',routine_days='월,수,금')
    record(s,k,'diet_plan',calories='9999',protein_g='999',food_items='미래 식단',meal_slot='dinner')
    r=s.health_report('household',k,'2026-01-01','2026-01-31','나')
    assert r['totals']['calories']==Decimal('500.25') and r['totals']['water_ml']==Decimal('550.5')
    assert r['totals']['protein_g']==Decimal('25.5') and r['totals']['duration_minutes']==Decimal('30.5')
    assert r['people'][0]['target_weight']=='68.5' and len(r['weights'])==1
    assert r['routines'][0]['routine_days']==[1,3,5] and len(r['plans'])==1
    assert s.health_report('household',k,'2026-01-01','2026-01-31','아이')['people']==[]


def test_sleep_cross_midnight_meditation_body_photo_and_metrics(private):
    s,k=private
    record(s,k,'sleep',sleep_start='23:30',sleep_end='07:00',sleep_quality='4')
    record(s,k,'meditation',stress_level='6',duration_minutes='10.25')
    record(s,k,'metric',systolic='120',diastolic='80',pulse='72',glucose='90')
    body=record(s,k,'body',waist_cm='80.5',chest_cm='95.2',hip_cm='93',arm_cm='28.5',thigh_cm='52.1')
    attachment=s.add_personal_attachment(k,'household','health',body,'바디체크.jpg',b'Private body photo placeholder')
    assert s.personal_attachment_data(k,'household','health',body,attachment)==b'Private body photo placeholder'
    r=s.health_report('household',k,'2026-01-01','2026-01-31')
    assert r['totals']['sleep_hours']==Decimal('7.50') and r['totals']['meditation_minutes']==Decimal('10.25')
    assert r['totals']['duration_minutes']==0
    s.delete_health_entry('household',k,body)
    assert s.db.execute('SELECT COUNT(*) FROM personal_attachments').fetchone()[0]==0


@pytest.mark.parametrize('category,data',[('meal',{'calories':'NaN'}),('water',{'water_ml':'-1'}),('metric',{'systolic':'120'}),('metric',{'systolic':'70','diastolic':'90'}),('sleep',{'sleep_start':'23:00','sleep_end':'23:00'}),('sleep',{'sleep_start':'bad','sleep_end':'07:00'}),('meditation',{'stress_level':'11'}),('routine',{'routine_days':'8'}),('body',{'waist_cm':'-1'})])
def test_invalid_measurements_never_save(private,category,data):
    s,k=private
    with pytest.raises(ValueError):record(s,k,category,**data)
    assert s.health_entries('household',k,'2026-01-01','2026-01-31')==[]


def test_supplement_reminders_once_today_weekdays_no_retroactive_dose_instruction(private):
    s,k=private
    identifier=record(s,k,'supplement',date='2026-01-01',title='사용자 지정 비타민',alarm=True,supplement_times='09:00,18:00',supplement_days='1,2,3,4,5,6,7',supplement_dose='제품 안내 확인')
    assert s.due_health_alerts('household',k,'2026-01-10T08:59')==[]
    assert len(s.due_health_alerts('household',k,'2026-01-10T09:00'))==1
    assert s.due_health_alerts('household',k,'2026-01-10T09:00')==[]
    assert len(s.due_health_alerts('household',k,'2026-01-10T18:00'))==1
    assert len(s.due_health_alerts('household',k,'2026-01-12T09:00'))==1
    assert s.db.execute('SELECT COUNT(*) FROM desk_events').fetchone()[0]==0
    s.delete_health_entry('household',k,identifier);assert s.db.execute('SELECT COUNT(*) FROM personal_health_receipts').fetchone()[0]==0


def test_health_fields_and_receipts_backup_restore_owner_encryption_and_ui(private):
    app=QApplication.instance() or QApplication([]);s,k=private
    record(s,k,'meal',calories='123.45',food_items='비밀 식단');record(s,k,'weight',weight='70.12')
    backup=s.create_backup();s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!')
    with pytest.raises(ValueError):s.health_report('household',k,'2026-01-01','2026-01-31')
    k=s.unlock_household('Health-Private-2026!')
    from pos2.health_report_ui import HealthReportDialog,MeditationDialog
    from PySide6.QtCore import QDate
    dialog=HealthReportDialog(s,'household',k);dialog.start.setDate(QDate(2026,1,1));dialog.end.setDate(QDate(2026,1,31));dialog.refresh();dialog.show();app.processEvents()
    assert dialog.daily.rowCount()==1 and dialog.people.rowCount()==1
    dialog.period.setCurrentIndex(1);app.processEvents();assert not dialog.grab().isNull();dialog.reject();dialog.deleteLater()
    meditation=MeditationDialog();meditation.toggle();meditation.elapsed=65;meditation.record();assert Decimal(meditation.recorded_minutes)>1;meditation.reject();meditation.deleteLater();app.processEvents()


def test_health_editor_switches_all_typed_forms_without_saving(private,monkeypatch):
    from PySide6.QtWidgets import QDialog
    from pos2.widgets import FormDialog
    from pos2.health_ui import HealthDialog
    from pos2.health import HEALTH_TYPES
    app=QApplication.instance() or QApplication([]);s,k=private;visited=[]
    def inspect(dialog):
        if 'category' in dialog.fields:
            combo=dialog.fields['category']
            for index in range(combo.count()):combo.setCurrentIndex(index);visited.append(combo.currentData());app.processEvents()
        QDialog.reject(dialog);return 0
    monkeypatch.setattr(FormDialog,'exec',inspect)
    dialog=HealthDialog(s,'household',k,None);dialog.editor();assert set(visited)==set(HEALTH_TYPES)
    dialog.reject();dialog.deleteLater();app.processEvents()
