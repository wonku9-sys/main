"""The reference-style login shell stays locked until local authentication."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from seoyoung_pos.app import STYLE
from seoyoung_pos.dialogs import LoginBackdrop, LoginDialog
from seoyoung_pos.service import POSService


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture
def service(tmp_path):
    instance = POSService(tmp_path / "login.db")
    yield instance
    instance.close()


@pytest.fixture
def messages(monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: errors.append(text))
    return errors


def dispose(application, *widgets):
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_backdrop_has_no_unauthenticated_business_actions(application, service):
    backdrop = LoginBackdrop()
    backdrop.show()
    application.processEvents()
    try:
        assert service.user is None
        assert backdrop.locked_menus
        assert all(not menu.isEnabled() for menu in backdrop.locked_menus)
        assert all(not menu.actions() for menu in backdrop.locked_menus)
        assert "서버" not in " ".join(menu.title() for menu in backdrop.locked_menus)
        assert "카드" not in " ".join(menu.title() for menu in backdrop.locked_menus)
        assert "사용자 인증" in backdrop.statusBar().currentMessage()
    finally:
        dispose(application, backdrop)


def test_first_admin_registration_remains_local_and_reachable(application, service, messages):
    backdrop = LoginBackdrop()
    backdrop.resize(1024, 600)
    backdrop.show()
    login = LoginDialog(service, backdrop)
    login.show()
    application.processEvents()
    try:
        assert login.initial
        assert login.frameGeometry().center().manhattanLength() > 0
        assert abs(login.frameGeometry().center().x() - backdrop.frameGeometry().center().x()) <= 2
        assert abs(login.frameGeometry().center().y() - backdrop.frameGeometry().center().y()) <= 2
        save = login.button_box.button(QDialogButtonBox.StandardButton.Save)
        assert login.rect().contains(save.mapTo(login, save.rect().center()))
        assert login.width() <= backdrop.width()
        assert login.height() <= backdrop.height()
        login.username.setText("manager")
        login.name.setText("매장 관리자")
        login.password.setText("standalone-password")
        login.confirm.setText("standalone-password")
        save.click()
        assert login.result() == QDialog.DialogCode.Accepted
        assert service.user["name"] == "매장 관리자"
        assert service.users_count() == 1
        assert messages == []
    finally:
        dispose(application, login, backdrop)


def test_existing_login_failure_and_cancel_do_not_open_session(application, service, messages):
    service.create_initial_admin("manager", "매장 관리자", "standalone-password")
    backdrop = LoginBackdrop()
    backdrop.show()
    login = LoginDialog(service, backdrop)
    login.show()
    application.processEvents()
    try:
        assert not login.initial
        assert login.name.isReadOnly()
        login.username.setText("manager")
        login.password.setText("incorrect-password")
        login.submit()
        assert service.user is None
        assert login.result() != QDialog.DialogCode.Accepted
        assert messages == ["사용자 코드 또는 비밀번호가 올바르지 않습니다."]
        login.button_box.button(QDialogButtonBox.StandardButton.Cancel).click()
        assert login.result() == QDialog.DialogCode.Rejected
        assert service.user is None
        assert all(not menu.isEnabled() for menu in backdrop.locked_menus)
    finally:
        dispose(application, login, backdrop)


def test_existing_login_authenticates_and_shows_real_name(application, service, messages):
    service.create_initial_admin("manager", "실제 사용자", "standalone-password")
    backdrop = LoginBackdrop()
    backdrop.resize(1024, 600)
    backdrop.show()
    login = LoginDialog(service, backdrop)
    login.show()
    application.processEvents()
    try:
        assert login.height() <= backdrop.height()
        assert login.width() <= backdrop.width()
        login.username.setText("manager")
        login.password.setText("standalone-password")
        login.button_box.button(QDialogButtonBox.StandardButton.Save).click()
        assert login.result() == QDialog.DialogCode.Accepted
        assert login.name.text() == "실제 사용자"
        assert service.user["username"] == "manager"
        assert messages == []
    finally:
        dispose(application, login, backdrop)
