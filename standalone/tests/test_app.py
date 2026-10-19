import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from pos2.app import LoginDialog, MainWindow
from pos2.store import Store


@pytest.fixture
def context(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)
    store = Store(tmp_path / "new-standalone.db")
    yield app, store
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()


def login_staff(store, permission):
    store.setup_admin("owner", "관리자", "Owner-Password-2026!")
    store.save_user({"code": "staff", "name": "직원", "password": "Staff-Password-2026!", "role": "staff", "permissions": [permission]})
    store.login("staff", "Staff-Password-2026!")


def test_first_admin_enter_moves_to_confirmation_without_implicit_submit(context):
    app, store = context
    dialog = LoginDialog(store)
    dialog.show()
    dialog.code.setText("owner")
    dialog.name.setText("매장 관리자")
    dialog.password.setText("Owner-Password-2026!")
    dialog.password.setFocus()
    QTest.keyClick(dialog.password, Qt.Key.Key_Return)
    assert store.users_count() == 0
    assert dialog.isVisible()
    dialog.confirm.setText("Owner-Password-2026!")
    QTest.keyClick(dialog.confirm, Qt.Key.Key_Return)
    assert store.users_count() == 1
    assert store.actor["role"] == "admin"


@pytest.mark.parametrize("permission,keys", [
    ("catalog", {"products", "suppliers", "customers", "labels"}),
    ("trade", {"purchases", "sales", "ledger", "closings"}),
    ("inventory", {"inventory", "counts", "closings"}),
    ("reports", {"overview", "reports", "commission"}),
    ("loyalty", {"members", "promotions", "prices", "gifts"}),
])
def test_scoped_menus_and_all_allowed_pages_refresh(context, permission, keys):
    app, store = context
    login_staff(store, permission)
    window = MainWindow(store)
    assert set(window.items) == keys
    for key in keys:
        assert window.open_page(key)
    assert not window.open_page("settings")
    if permission in {"trade", "inventory"}:
        page = window.pages["closings"]
        assert page.tabs.isTabEnabled(0) == (permission == "trade")
        assert page.tabs.isTabEnabled(1) == (permission == "inventory")


def test_toolbar_new_trade_uses_supplier_picker_workflow(context, monkeypatch):
    app, store = context
    login_staff(store, "trade")
    window = MainWindow(store)
    assert window.open_page("purchases")
    called = []
    monkeypatch.setattr(window.pages["purchases"], "new_trade", lambda: called.append("supplier-picker"))
    window.new_trade("purchase")
    assert called == ["supplier-picker"]
