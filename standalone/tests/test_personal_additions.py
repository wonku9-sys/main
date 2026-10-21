"""Attachment confidentiality, deletion, backup and original daily greetings."""
import pytest
from PySide6.QtWidgets import QApplication
from pos2.store import Store
from pos2.personal_attachments import ATTACHMENT_LIMIT


@pytest.fixture(params=['household','diary'])
def private(tmp_path,request):
    s=Store(tmp_path/'personal.db');s.setup_admin('owner','관리자','Owner-Strong-2026!');kind=request.param
    if kind=='household':
        s.setup_household('Private-2026!','Private-2026!');key=s.unlock_household('Private-2026!')
        identifier=s.save_household_entry(key,dict(date='2026-01-01',kind='expense',title='기록',amount='1.25'))
    else:
        s.setup_diary('Private-2026!','Private-2026!');key=s.unlock_diary('Private-2026!')
        identifier=s.save_diary_entry(key,dict(date='2026-01-01',title='개인 일기',body='내용'))
    yield s,key,kind,identifier
    s.close()


def test_attachment_encrypted_roundtrip_backup_and_delete(private):
    s,k,kind,record=private;payload=b'%PDF-1.4 Personal secret receipt content'
    identifier=s.add_personal_attachment(k,kind,'entry',record,'개인영수증.pdf',payload)
    row=s.db.execute('SELECT * FROM personal_attachments WHERE id=?',(identifier,)).fetchone()
    assert payload not in row['ciphertext'] and '개인영수증'.encode() not in row['metadata']
    assert s.personal_attachments(k,kind,'entry',record)[0]['name']=='개인영수증.pdf'
    assert s.personal_attachment_data(k,kind,'entry',record,identifier)==payload
    backup=s.create_backup();s.delete_personal_attachment(k,kind,'entry',record,identifier)
    assert s.personal_attachments(k,kind,'entry',record)==[]
    s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!')
    with pytest.raises(ValueError):s.personal_attachments(k,kind,'entry',record)
    k=getattr(s,'unlock_'+kind)('Private-2026!')
    assert s.personal_attachment_data(k,kind,'entry',record,identifier)==payload
    getattr(s,'delete_'+kind+'_entry')(k,record)
    assert s.db.execute('SELECT count(*) FROM personal_attachments').fetchone()[0]==0


def test_attachment_limits_wrong_key_and_record_are_enforced(private):
    s,k,kind,record=private
    for name,data in [('bad.exe',b'file'),('empty.pdf',b''),('large.pdf',b'x'*(ATTACHMENT_LIMIT+1))]:
        with pytest.raises(ValueError):s.add_personal_attachment(k,kind,'entry',record,name,data)
    with pytest.raises(ValueError):s.add_personal_attachment(bytearray(32),kind,'entry',record,'image.png',b'png')
    with pytest.raises(ValueError):s.add_personal_attachment(k,kind,'entry','unknown','image.png',b'png')
    identifier=s.add_personal_attachment(k,kind,'entry',record,'C:\\folder\\photo.jpg',b'photo')
    assert s.personal_attachments(k,kind,'entry',record)[0]['name']=='photo.jpg'
    s.db.execute('UPDATE personal_attachments SET ciphertext=randomblob(50) WHERE id=?',(identifier,))
    with pytest.raises(ValueError):s.personal_attachment_data(k,kind,'entry',record,identifier)
    getattr(s,'lock_'+kind)()
    with pytest.raises(ValueError):s.personal_attachments(k,kind,'entry',record)


def test_vehicle_no_cost_logs_and_expense_metadata_remain_distinct(tmp_path):
    s=Store(tmp_path/'cars.db');s.setup_admin('owner','관리자','Owner-Strong-2026!');s.setup_household();k=s.unlock_household()
    try:
        car=s.save_household_vehicle(k,dict(name='가족 자동차',next_service_date='2026-11-01',next_service_km='15000'))
        log=s.save_household_vehicle_log(k,dict(vehicle_id=car,date='2026-01-01',title='타이어 무상 점검',log_kind='inspection',odometer='10000.5',distance='21.5',place='정비소',memo='이상 없음'))
        attached=s.add_personal_attachment(k,'household','vehicle_log',log,'점검표.pdf',b'Inspection document')
        assert s.household_dashboard(k,'2026-01-01','2026-01-31')['expense_total']==0
        assert len(s.household_vehicle_logs(k,car,'2026-01-01','2026-01-31'))==1
        with pytest.raises(ValueError):s.save_household_entry(k,dict(date='2026-01-01',kind='expense',title='보험',amount='10.25',vehicle_id=car,vehicle_type='insurance',insurance_start='2026-12-31',insurance_end='2026-01-01'))
        s.save_household_entry(k,dict(date='2026-01-01',kind='expense',title='보험',amount='10.25',vehicle_id=car,vehicle_type='insurance',vehicle_vendor='보험사',vehicle_detail='자동차 종합보험',insurance_start='2026-01-01',insurance_end='2026-12-31'))
        assert s.household_dashboard(k,'2026-01-01','2026-01-31')['expense_total']==10.25
        s.delete_household_vehicle_log(k,log)
        assert s.db.execute('SELECT 1 FROM personal_attachments WHERE id=?',(attached,)).fetchone() is None
    finally:s.close()


def test_login_encouragement_never_immediately_repeats_and_reopens(tmp_path):
    s=Store(tmp_path/'quote.db');s.setup_admin('owner','관리자','Owner-Strong-2026!')
    try:
        prior=s.inspiration(True)
        for _ in range(50):
            current=s.inspiration(True);assert current!=prior;assert s.inspiration()==current;prior=current
        app=QApplication.instance() or QApplication([])
        from pos2.inspiration import InspirationDialog
        from pos2.attachment_ui import AttachmentDialog
        dialog=InspirationDialog(s);dialog.show();app.processEvents();assert not dialog.grab().isNull();dialog.accept();dialog.deleteLater();app.processEvents()
    finally:s.close()
