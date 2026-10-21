"""Idle/error Excel importer must close; a live atomic import must finish first."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton
from pos2.catalog_import_ui import CatalogImportDialog
from pos2.popup_policy import install_popup_policy


@pytest.mark.parametrize('route',('button','titlebar','escape','shortcut'))
@pytest.mark.parametrize('failed',(False,True))
def test_idle_importer_closes_from_every_route(route,failed):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    dialog=CatalogImportDialog(SimpleNamespace())
    if failed:dialog.failed('시험용 파일 형식 오류')
    dialog.show();dialog.activateWindow();app.processEvents()
    if route=='button':next(b for b in dialog.findChildren(QPushButton) if b.text()=='이 창 닫기').click()
    elif route=='titlebar':assert dialog.close()
    elif route=='escape':QTest.keyClick(dialog,Qt.Key.Key_Escape)
    else:QTest.keySequence(dialog,QKeySequence('Ctrl+W'))
    app.processEvents();assert not dialog.isVisible()
    dialog.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_running_import_cannot_close_but_failed_or_finished_one_can():
    app=QApplication.instance() or QApplication([]);dialog=CatalogImportDialog(SimpleNamespace())
    running=[True];dialog.worker=SimpleNamespace(isRunning=lambda:running[0]);dialog.show();app.processEvents()
    assert not dialog.close() and dialog.isVisible()
    dialog.reject();assert dialog.isVisible()
    running[0]=False;dialog.failed('잘못된 파일');assert dialog.close();assert not dialog.isVisible()
    dialog.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
