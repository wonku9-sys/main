from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QLineEdit
from pos2.store import Store
from pos2.shared_ui import SharedRefresh


def test_refresh_defers_dirty_form_and_recovers_offline_without_erasing():
    app=QApplication.instance() or QApplication([]);parent=QWidget();parent.shared_notice=QLabel(parent)
    edited=QLineEdit('저장 전 입력',parent);dirty=[True];calls=[]
    parent.store=SimpleNamespace(is_shared_client=False)
    parent.navigation=SimpleNamespace(changed=lambda _:dirty[0]);parent.current_page=SimpleNamespace(refresh=lambda:calls.append('refreshed'))
    parent.notify=lambda message:calls.append(message)
    worker=SharedRefresh(parent);worker.timer.stop()
    worker.finished({'revision':['epoch',1]},None);worker.finished({'revision':['epoch',2]},None)
    assert not any(r=='refreshed' for r in calls) and edited.text()=='저장 전 입력' and worker.changed
    worker.finished(None,ConnectionError('기준 PC 꺼짐'))
    assert edited.text()=='저장 전 입력' and not parent.shared_notice.isHidden()
    dirty[0]=False;worker.finished({'revision':['epoch',2]},None)
    assert 'refreshed' in calls and not worker.changed and parent.shared_notice.isHidden()
    worker.stop();parent.deleteLater();app.processEvents()


def test_restore_requires_host_sharing_stopped(tmp_path):
    s=Store(tmp_path/'host.db');s.setup_admin('owner','관리자','Owner-Strong-2026!')
    try:
        backup=s.create_backup();s._shared_host_running=True
        with pytest.raises(ValueError,match='단독 사용'):s.restore_backup(backup,'Owner-Strong-2026!')
    finally:s.close()

def test_numeric_private_owner_ids_are_never_reused_after_delete_or_restore(tmp_path):
    s=Store(tmp_path/'owners.db');s.setup_admin('owner','관리자','Owner-Strong-2026!')
    try:
        backup=s.create_backup()
        first=s.save_user(dict(code='first',name='이전 직원',password='First-Strong-2026!',role='staff',permissions=[]));s.delete_user(first)
        second=s.save_user(dict(code='second',name='새 직원',password='Second-Strong-2026!',role='staff',permissions=[]));assert second>first
        s.restore_backup(backup,'Owner-Strong-2026!');s.login('owner','Owner-Strong-2026!')
        third=s.save_user(dict(code='third',name='복원 후 직원',password='Third-Strong-2026!',role='staff',permissions=[]));assert third>second
    finally:s.close()
