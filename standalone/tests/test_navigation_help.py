from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QDate
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QStyle, QPushButton

from pos2.app import MainWindow
from pos2.catalog_ui import ProductDialog
from pos2.menu_help import MENU_HELP, MenuHelpStyle
from pos2.store import Store
from pos2.workflow_ui import TradeDialog, PurchaseSourcePicker


@pytest.fixture
def shop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "navigation.db")
    store.setup_admin("owner", "관리자", "Owner-Password-2026!")
    supplier = store.save_partner({"code": "S1", "kind": "supplier", "name": "공급사"})
    product = store.save_product({"name": "삼겹살", "barcode": "000012345", "supplier_id": supplier, "purchase_price": 1000})
    window = MainWindow(store)
    window.show()
    window.navigation.enable()
    monkeypatch.setattr("pos2.navigation.ask_unsaved", lambda *_: QMessageBox.StandardButton.Cancel)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr("pos2.workflow_ui._warn", lambda *_: None)
    yield app, store, window, supplier, product
    window.navigation.suspended = True
    window.navigation.disable()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()


@pytest.mark.parametrize("choice,leaves,saved", [
    (QMessageBox.StandardButton.Cancel, False, False),
    (QMessageBox.StandardButton.Discard, True, False),
    (QMessageBox.StandardButton.Save, True, True),
])
def test_settings_home_save_discard_and_cancel(shop, monkeypatch, choice, leaves, saved):
    _, store, window, *_ = shop
    window.open_page("settings")
    window.current_page.fields["store_name"].setText("변경된 매장")
    monkeypatch.setattr("pos2.navigation.ask_unsaved", lambda *_: choice)
    assert window.go_home() == leaves
    assert (window.current_key == "home") == leaves
    assert (store.settings()["store_name"] == "변경된 매장") == saved


def test_invalid_settings_cannot_be_saved_by_home_navigation(shop, monkeypatch):
    _, _, window, *_ = shop
    window.open_page("settings")
    page = window.current_page
    page.fields["point_step"].setText("invalid")
    monkeypatch.setattr("pos2.navigation.ask_unsaved", lambda *_: QMessageBox.StandardButton.Save)
    assert not window.go_home()
    assert window.current_page is page


def test_modal_product_home_button_saves_and_returns_home(shop, monkeypatch):
    app, store, window, *_ = shop
    window.open_page("products")
    dialog = ProductDialog(store, parent=window)
    dialog.show()
    app.processEvents()
    assert dialog._home_button.text() == "첫화면"
    dialog.fields["name"].setText("목살")
    monkeypatch.setattr("pos2.navigation.ask_unsaved", lambda *_: QMessageBox.StandardButton.Save)
    dialog._home_button.click()
    app.processEvents()
    assert not dialog.isVisible() and window.current_key == "home"
    assert any(row["name"] == "목살" for row in store.products())


def test_modal_close_and_escape_do_not_discard_work(shop):
    app, store, window, *_ = shop
    dialog = ProductDialog(store, parent=window)
    dialog.show()
    app.processEvents()
    dialog.fields["name"].setText("닫기 취소")
    dialog.reject()
    assert dialog.isVisible()
    assert not dialog.close()
    assert dialog.isVisible() and len(store.products()) == 1


def test_save_on_home_keeps_trade_as_draft_without_posting(shop, monkeypatch):
    app, store, window, supplier, product = shop
    dialog = TradeDialog(window)
    dialog.partner.setCurrentIndex(dialog.partner.findData(supplier))
    dialog.show()
    app.processEvents()
    dialog.scan_barcode("000012345")
    dialog.line_rows[0]["qty"].setText("3")
    monkeypatch.setattr("pos2.navigation.ask_unsaved", lambda *_: QMessageBox.StandardButton.Save)
    dialog._home_button.click()
    app.processEvents()
    assert store.document(dialog.saved_id)["status"] == "draft"
    assert Decimal(store.products()[0]["stock_qty"]) == 0
    assert not store.db.execute("SELECT 1 FROM payments").fetchone()
    assert window.current_key == "home"


def test_filter_changes_are_not_edit_work(shop, monkeypatch):
    _, _, window, *_ = shop
    window.open_page("purchases")
    window.current_page.search.setText("검색은 저장하지 않음")
    def unexpected(*_):
        raise AssertionError("조회 필터에 저장 팝업 금지")
    monkeypatch.setattr("pos2.navigation.ask_unsaved", unexpected)
    assert window.go_home()


def test_all_menu_surfaces_have_specific_hover_help(shop):
    _, _, window, *_ = shop
    assert set(window.items) == set(MENU_HELP)
    for key, item in window.items.items():
        assert item.toolTip(0) == MENU_HELP[key]
        assert window.nav_actions[key].toolTip() == MENU_HELP[key]
        assert window.nav_actions[key].associatedObjects()
    assert all(action.toolTip() for action in window.toolbar.actions())
    buttons = window.pages["home"].links.findChildren(QPushButton)
    assert len(buttons) == 7 and all(button.toolTip() for button in buttons)
    assert all(button.toolTip() for button in window.personal_panel.findChildren(QPushButton))
    style = MenuHelpStyle()
    assert style.styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay) == 700
    style.deleteLater()


def test_purchase_names_filters_and_checkbox_same_window_return(shop, monkeypatch):
    app, store, window, supplier, product = shop
    original = store.post_document({"kind": "purchase", "date": date.today().isoformat(), "partner_id": supplier, "lines": [{"product_id": product, "qty": 5, "unit_price": 1000}]})
    window.open_page("purchases")
    page = window.current_page
    assert page.title == window.items["purchases"].text(0) == "매입전표"
    def choose(picker):
        picker.record = store.document(original)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PurchaseSourcePicker, "exec", choose)
    monkeypatch.setattr("pos2.workflow_ui._confirm", lambda *_: True)
    dialog = TradeDialog(window)
    dialog.partner.setCurrentIndex(dialog.partner.findData(supplier))
    dialog.return_mode.setChecked(True)
    assert dialog.is_return and dialog.kind == "purchase_return"
    assert dialog.source["id"] == original and dialog.paid_caption.text() == "환불금액"
    assert dialog.line_rows[0]["qty"].text() == "0"
    assert not dialog.line_rows[0]["price"].isEnabled() or dialog.line_rows[0]["price"].isReadOnly()
    dialog.line_rows[0]["qty"].setText("2")
    dialog.save(True)
    result = store.document(dialog.saved_id)
    assert result["kind"] == "purchase_return" and result["source_id"] == original
    assert store.document(original)["balance"] == 3000
    page.type_filter.setCurrentIndex(page.type_filter.findData("purchase_return"))
    assert page.grid.rowCount() == 1
    page.type_filter.setCurrentIndex(page.type_filter.findData("purchase"))
    assert page.grid.rowCount() == 1
    page.type_filter.setCurrentIndex(0)
    assert page.grid.rowCount() == 2


def test_cancel_return_source_picker_preserves_purchase_inputs(shop, monkeypatch):
    _, _, window, supplier, product = shop
    dialog = TradeDialog(window)
    dialog.partner.setCurrentIndex(dialog.partner.findData(supplier))
    dialog.scan_barcode("000012345")
    monkeypatch.setattr(PurchaseSourcePicker, "exec", lambda *_: QDialog.DialogCode.Rejected)
    dialog.return_mode.setChecked(True)
    assert not dialog.is_return and not dialog.return_mode.isChecked()
    assert dialog.line_rows[0]["product"].currentData() == product


def test_purchase_apply_keeps_window_open_then_save_posts_same_document(shop, monkeypatch):
    app, store, window, supplier, product = shop
    dialog = TradeDialog(window)
    dialog.partner.setCurrentIndex(dialog.partner.findData(supplier))
    dialog.show()
    dialog.scan_barcode("000012345")
    dialog.draft_button.click()
    assert dialog.isVisible() and dialog.saved_id
    original_id = dialog.saved_id
    assert store.document(original_id)["status"] == "draft"
    assert not window.navigation.changed(dialog)
    dialog.line_rows[0]["qty"].setText("3")
    assert window.navigation.changed(dialog)
    monkeypatch.setattr("pos2.workflow_ui._confirm", lambda *_: True)
    dialog.post_button.click()
    assert dialog.saved_id == original_id and not dialog.isVisible()
    assert len(store.documents()) == 1
    assert store.document(original_id)["status"] == "posted"
    assert Decimal(store.products()[0]["stock_qty"]) == 3


def test_product_memo_changes_are_protected(shop):
    app, store, window, *_ = shop
    dialog = ProductDialog(store, parent=window)
    dialog.show()
    app.processEvents()
    dialog.memo.setPlainText("메모도 저장 확인")
    assert window.navigation.changed(dialog)
    dialog.reject()
    assert dialog.isVisible()
