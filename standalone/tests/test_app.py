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


def test_first_admin_login_has_default_hint_and_enter_authenticates(context):
    app, store = context
    dialog = LoginDialog(store)
    dialog.show()
    assert dialog.code.text() == "admin" and dialog.password.text() == "1234"
    assert "1234" in dialog.hint.text() and "변경" in dialog.hint.text()
    assert store.users_count() == 1 and store.actor is None
    dialog.password.setFocus()
    QTest.keyClick(dialog.password, Qt.Key.Key_Return)
    assert store.users_count() == 1
    assert store.actor["role"] == "admin" and store.actor["code"] == "admin"


def test_default_admin_hash_mode_and_password_change_never_resets_on_restart(context):
    app, store = context
    dialog = LoginDialog(store)
    dialog.submit()
    assert store.actor["code"] == "admin" and store.actor["role"] == "admin"
    stored = store.db.execute("SELECT password_hash FROM users WHERE code='admin'").fetchone()[0]
    assert stored.startswith("scrypt$") and stored != "1234"
    window = MainWindow(store)
    assert window.admin_mode_button is not None
    assert {"users", "settings", "payments"} <= set(window.items)
    window.admin_mode_button.click()
    assert window.current_key == "settings"
    store.change_password("1234", "Local-Only-Password-2026!")
    assert not store.default_login_available()
    again = LoginDialog(store)
    assert not again.initial and again.password.text() == "" and "1234" not in again.hint.text()
    assert store.users_count() == 1
    with pytest.raises(ValueError):
        store.login("admin", "1234")
    store.login("admin", "Local-Only-Password-2026!")


def test_existing_custom_admin_is_never_overwritten_by_default_login(context):
    _, store = context
    store.setup_admin("wonku9", "기존 관리자", "Existing-Local-Password-2026!")
    assert not store.bootstrap_default_admin()
    dialog = LoginDialog(store)
    assert not dialog.initial and dialog.password.text() == ""
    assert store.users_count() == 1
    store.login("wonku9", "Existing-Local-Password-2026!")
    assert store.actor["code"] == "wonku9"


@pytest.mark.parametrize("permission,keys", [
    ("catalog", {"products", "categories", "suppliers", "customers", "labels"}),
    ("trade", {"purchases", "payments", "sales", "ledger", "closings"}),
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
