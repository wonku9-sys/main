"""Destructive reset fail-closed checks and non-closing, explained quote history."""
from datetime import date
from pathlib import Path
import sqlite3
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton
from pos2.store import Store
from pos2.factory_reset import PRESERVED_TABLES,BUSINESS_TABLES,private_digest

ADMIN='Owner-Test-Password-2026!'
RESET='Reset-Only-Test-Password-2026!'


@pytest.fixture
def shop(tmp_path):
    s=Store(tmp_path/'data-v2'/'test.db');s.setup_admin('owner','시험 관리자',ADMIN)
    s.save_settings({'store_name':'초기화 시험점','business_no':'123-45-67890'})
    s.configure_reset_authority(ADMIN,'wonku9',RESET,RESET)
    supplier=s.save_partner(dict(kind='supplier',name='시험 공급사'))
    product=s.save_product(dict(name='시험 상품',purchase_price='100.25',sale_price='150.50'))
    s.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,paid='100.25',lines=[dict(product_id=product,qty='1',unit_price='100.25')]))
    s.save_member(dict(code='M1',name='시험 회원'))
    s.save_desk_event(dict(date='2026-10-20',time='09:00',title='보존 일정'))
    s.save_work_log(dict(date='2026-10-20',title='보존 업무일지',body='보존 내용'))
    s.setup_diary('Diary-Test-2026!','Diary-Test-2026!');dk=s.unlock_diary('Diary-Test-2026!')
    diary=s.save_diary_entry(dk,dict(date='2026-10-20',title='보존 일기',body='개인 비밀'))
    s.add_personal_attachment(dk,'diary','entry',diary,'보존.pdf',b'%PDF-private-test')
    s.setup_household('Household-Test-2026!','Household-Test-2026!');hk=s.unlock_household('Household-Test-2026!')
    s.save_household_entry(hk,dict(date='2026-10-20',kind='expense',title='보존 가계부',amount='12.25'))
    s.inspiration(True)
    yield s
    s.close()


@pytest.mark.parametrize('field,value',[('admin','wrong'),('identifier','other'),('identifier','다른아이디'),('password','wrong'),('phrase','초기화')])
def test_wrong_auth_or_confirmation_never_resets_or_creates_backup(shop,field,value):
    s=shop;before=s.business_reset_plan();private=private_digest(s.db);files=s.backup_files();revision=s.audit_revision()
    values=dict(admin=ADMIN,identifier='wonku9',password=RESET,phrase='업무자료 초기화');values[field]=value
    with pytest.raises(ValueError):s.reset_business_data(values['admin'],values['identifier'],values['password'],values['phrase'])
    assert s.business_reset_plan()==before and private_digest(s.db)==private
    assert s.backup_files()==files and s.audit_revision()==revision


def test_business_reset_preserves_all_private_rows_credentials_and_real_protection_backup(shop):
    s=shop;before=private_digest(s.db);other=Store(s.path);other.login('owner',ADMIN)
    try:
        result=s.reset_business_data(ADMIN,'wonku9',RESET,'업무자료 초기화')
        assert result['business_reset'] and result['private_preserved'] and s.actor is None
        assert Path(result['safety_backup']).is_file() and Path(result['source_snapshot']).is_file()
        assert private_digest(s.db)==before
        with pytest.raises(PermissionError):other.products()
        s.login('owner',ADMIN)
        assert all(v==0 for v in s.business_reset_plan().values())
        assert s.store_profile()['store_name']=='SY POS' and s.store_profile()['business_no']==''
        assert s.work_logs('2026-10-20','2026-10-20')[0]['body']=='보존 내용'
        dk=s.unlock_diary('Diary-Test-2026!');diary=s.diary_entries(dk)[0];assert diary['body']=='개인 비밀'
        attachment=s.personal_attachments(dk,'diary','entry',diary['id'])[0]
        assert s.personal_attachment_data(dk,'diary','entry',diary['id'],attachment['id'])==b'%PDF-private-test'
        hk=s.unlock_household('Household-Test-2026!');assert s.household_report(hk,'2026-10-20','2026-10-20')['rows'][0]['title']=='보존 가계부'
        info=s.inspect_backup(result['safety_backup']);assert info['counts']['products']==1 and info['counts']['documents']==1
        assert s.reset_authority_configured()
    finally:other.close()


def test_private_change_during_final_backup_aborts_instead_of_losing_update(shop,monkeypatch):
    s=shop;original=s.create_backup;calls=[]
    def backup(*args,**kwargs):
        result=original(*args,**kwargs);calls.append(result)
        if len(calls)==2:s.db.execute("UPDATE work_logs SET body='보존해야 하는 동시 변경'")
        return result
    monkeypatch.setattr(s,'create_backup',backup)
    with pytest.raises(ValueError,match='변경'):s.reset_business_data(ADMIN,'wonku9',RESET,'업무자료 초기화')
    assert s.business_reset_plan()['products']==1
    assert s.work_logs('2026-10-20','2026-10-20')[0]['body']=='보존해야 하는 동시 변경'


def test_copy_failure_restores_business_and_private_data_from_protection(shop,monkeypatch):
    import pos2.recovery as recovery
    s=shop;before=private_digest(s.db);original=recovery._copy_database;attempts=[]
    def copy(source,destination,*args,**kwargs):
        attempts.append(1)
        if len(attempts)==1:raise sqlite3.OperationalError('synthetic reset I/O failure')
        return original(source,destination,*args,**kwargs)
    monkeypatch.setattr(recovery,'_copy_database',copy)
    with pytest.raises(ValueError,match='되돌렸'):s.reset_business_data(ADMIN,'wonku9',RESET,'업무자료 초기화')
    assert s.business_reset_plan()['products']==1 and private_digest(s.db)==before and len(attempts)==2


def test_authority_is_salted_not_plaintext_and_cannot_be_overwritten_without_old_secret(shop):
    s=shop;path=s.path.parent/'reset-authority.json';payload=path.read_text()
    assert RESET not in payload and ADMIN not in payload and 'scrypt$16384$8$1$' in payload
    with pytest.raises(ValueError):s.configure_reset_authority(ADMIN,'wonku9','Different-Test-2026!','Different-Test-2026!','wrong')
    assert path.read_text()==payload
    s._shared_host_running=True
    with pytest.raises(ValueError):s.reset_business_data(ADMIN,'wonku9',RESET,'업무자료 초기화')
    s._shared_host_running=False
    s.db.execute('CREATE TABLE future_unclassified_data(value TEXT)')
    with pytest.raises(ValueError,match='구조'):s.reset_business_data(ADMIN,'wonku9',RESET,'업무자료 초기화')


def test_quote_previous_next_explanation_and_single_close_keep_popup_open(shop):
    from pos2.app import MainWindow
    from pos2.inspiration import InspirationDialog,CARDS,WORDS
    from pos2.popup_policy import install_popup_policy
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    window=MainWindow(shop);window.show();window.navigation.enable()
    dialog=InspirationDialog(shop,parent=window);dialog.show();app.processEvents()
    try:
        assert not dialog.previous_button.isEnabled() and dialog.isVisible()
        assert not [b for b in dialog.findChildren(QPushButton) if b.text() in {'첫화면','닫고 시작하기'}]
        assert len([b for b in dialog.findChildren(QPushButton) if b.text()=='닫기'])==1
        first=dialog.phrase.text();dialog.next_button.click();second=dialog.phrase.text()
        assert first!=second and dialog.isVisible() and dialog.history_index==1
        assert not dialog.explanation.isVisible();dialog.explanation_button.click();assert dialog.explanation.isVisible()
        dialog.previous_button.click();assert dialog.phrase.text()==first and not dialog.explanation.isVisible()
        dialog.next_button.click();assert dialog.phrase.text()==second and len(dialog.history)==2
        categories={card['category'] for card in CARDS};assert {'공자','맹자','탈무드의 지혜','영어와 해설','사자성어','고전 명대사'}<=categories
        for i,card in enumerate(CARDS):
            assert card['source'] and card['explanation'] and card['reflection']
            if card['category']=='영어와 해설':
                dialog.history.append(WORDS[i]);dialog.history_index=len(dialog.history)-1;dialog.show_current()
                assert dialog.english.isVisible() and dialog.english.text()==card['english']
                dialog.explanation_button.click();assert dialog.explanation.text()==card['explanation']
                break
        dialog.close_button.click();assert not dialog.isVisible()
    finally:
        window.navigation.suspended=True;window.navigation.disable()
        for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
