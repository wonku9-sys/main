"""Thread exit is not GUI completion; guard the intervening queued-signal gap."""
from time import monotonic
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget
from shiboken6 import isValid
from pos2.store import Store
from pos2.payment_access_ui import PaymentAccessDialog
from pos2.background_store import StoreTask

PASSWORD='Completion-Strong-2026!'


@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'completion.db');store.setup_admin('owner','관리자',PASSWORD)
    parent=QWidget();parent.store=store;dialogs=[]
    yield app,store,parent,dialogs
    for dialog in dialogs:
        if dialog.worker and isValid(dialog.worker):dialog.worker.wait(10000)
    app.processEvents()
    for dialog in dialogs:dialog.close();dialog.deleteLater()
    parent.close();parent.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_cancel_and_resubmit_blocked_until_gui_finished_delivery(desktop):
    app,store,parent,dialogs=desktop;actor=dict(store.actor)
    dialog=PaymentAccessDialog(parent);dialogs.append(dialog);dialog.show();app.processEvents()
    dialog.password.setText(PASSWORD);dialog.submit();original=dialog.worker
    assert original.wait(10000) and not original.isRunning()
    # Deliberately do not drain GUI signals: the password check has returned,
    # but its success/finished slots have not yet accepted the dialog.
    assert dialog.busy and not dialog.buttons.isEnabled()
    dialog.reject();assert dialog.isVisible()
    assert not dialog.close() and dialog.isVisible()
    dialog.password.setText('wrong');dialog.submit();assert dialog.worker is original
    deadline=monotonic()+10
    while dialog.busy and monotonic()<deadline:QTest.qWait(10)
    assert not dialog.busy and dialog.verified and not dialog.isVisible() and not dialog.password.text()
    assert store.actor==actor


def test_finished_worker_deleted_before_queued_cleanup_does_not_poison_registry(desktop):
    app,store,_,_=desktop
    owner=QObject();worker=StoreTask(owner,store,'verify_payment_access',(PASSWORD,));worker.start()
    assert worker.wait(10000)
    owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not isValid(worker)
    assert worker not in app._sy_catalog_workers
    assert all(isValid(task) for task in app._sy_catalog_workers)
