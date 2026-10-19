"""Exercise actual Qt pages and dialogs against SQLite without a display server."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QMessageBox, QTabWidget

from seoyoung_pos.app import MainWindow, NAV_ITEMS, STYLE
from seoyoung_pos.demo import populate_demo
from seoyoung_pos.dialogs import (
    DocumentDialog, LoginDialog, PartnerDialog, PartnerPicker, PasswordDialog,
    ProductDialog, UserDialog,
)
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
def messages(monkeypatch):
    recorded = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, text, *_args: recorded.append((title, text)))
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, title, text, *_args: recorded.append((title, text)))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)
    return recorded


@pytest.fixture
def service(tmp_path):
    instance = POSService(tmp_path / "test.db")
    yield instance
    instance.close()


@pytest.fixture
def demo_service(service):
    populate_demo(service)
    return service


@pytest.fixture
def window(application, demo_service, tmp_path, messages):
    result = MainWindow(demo_service, tmp_path / "test.db", demo=True)
    result.show()
    application.processEvents()
    yield result
    result.close()
    result.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def table_records(table):
    return [table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(table.rowCount())]


def fill_partner(service, kind, code, name):
    dialog = PartnerDialog(service, kind)
    dialog.fields["code"].setText(code)
    dialog.fields["name"].setText(name)
    dialog.fields["contact"].setText("홍담당")
    dialog.fields["bank"].setText("서영은행")
    dialog.fields["account"].setText("123-456")
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    return next(record for record in service.list_partners(kind) if record["id"] == dialog.saved_id)


def select_product(dialog, product_id, qty="1.250", price="18800", row=0):
    combo = dialog.items.cellWidget(row, 0)
    combo.setCurrentIndex(combo.findData(product_id))
    dialog.items.cellWidget(row, 2).setText(qty)
    dialog.items.cellWidget(row, 3).setText(price)


def submit_nested(application, action, fill=None):
    """Use the real nested Qt event loop; guard against unattended modal hangs."""
    failures = []
    guard = QTimer()
    guard.setSingleShot(True)

    def timeout():
        failures.append("nested dialog timed out")
        if application.activeModalWidget():
            application.activeModalWidget().reject()

    def submit():
        modal = application.activeModalWidget()
        try:
            assert modal is not None
            if fill:
                fill(modal)
            box = modal.findChild(QDialogButtonBox)
            assert box is not None
            box.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException as error:
            failures.append(repr(error))
            if modal:
                modal.reject()

    guard.timeout.connect(timeout)
    guard.start(3000)
    QTimer.singleShot(0, submit)
    action()
    guard.stop()
    assert not failures


def test_admin_navigates_and_renders_every_business_page(window, application, messages):
    assert set(window.nav_buttons) == {item[0] for item in NAV_ITEMS}
    for key, nav in window.nav_buttons.items():
        nav.click()
        application.processEvents()
        assert window.current_page is window.pages[key]
        assert window.stack.currentWidget() is window.page_scrollers[key]
        assert window.page_scrollers[key].widget() is window.pages[key]
        assert nav.isChecked()
        assert not window.grab().isNull()
    for width, height in ((1366, 768), (1080, 660)):
        window.resize(width, height)
        application.processEvents()
        assert (window.width(), window.height()) == (width, height)
        for key in window.nav_buttons:
            window.navigate(key)
            application.processEvents()
            scroller = window.page_scrollers[key]
            assert scroller.viewport().width() > 0
            assert scroller.viewport().height() > 0
            scrollbar = scroller.horizontalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            assert scrollbar.value() == scrollbar.maximum()
    assert messages == []


def test_catalog_filters_totals_and_numeric_sorting(window, demo_service, messages):
    window.navigate("products")
    page = window.current_page
    page.search.setText("돼지")
    page.search.returnPressed.emit()
    expected = demo_service.list_products("돼지")
    assert {record["id"] for record in table_records(page.table)} == {record["id"] for record in expected}
    assert len(expected) == 5
    amount = sum(record["stock_cost"] for record in expected)
    assert f"{amount:,} 원" in page.total_label.text()
    page.search.clear()
    page.refresh()
    for column in (7, 8):
        page.table.sortItems(column, Qt.SortOrder.AscendingOrder)
        actual = [page.table.item(row, column).sort_value for row in range(page.table.rowCount())]
        assert actual == sorted(actual)
    supplier = demo_service.list_partners("supplier")[0]
    page.supplier.setCurrentIndex(page.supplier.findData(supplier["id"]))
    page.low.setChecked(True)
    page.refresh()
    expected = demo_service.list_products(supplier_id=supplier["id"], low_stock=True)
    assert {record["id"] for record in table_records(page.table)} == {record["id"] for record in expected}
    assert messages == []


def test_document_filters_and_report_reconcile_with_service(window, demo_service, messages):
    window.navigate("purchases")
    page = window.current_page
    page.start.setDate(QDate.currentDate().addDays(-40))
    page.status.setCurrentIndex(1)
    page.refresh()
    supplier = demo_service.list_partners("supplier")[0]
    page.partner.setCurrentIndex(page.partner.findData(supplier["id"]))
    page.refresh()
    expected = demo_service.list_documents("purchase", partner_id=supplier["id"])
    expected = [record for record in expected if record["status"] == "posted" and record["balance"] > 0]
    assert {record["id"] for record in table_records(page.table)} == {record["id"] for record in expected}
    assert f"미결제 {sum(record['balance'] for record in expected):,} 원" in page.total_label.text()
    window.navigate("reports")
    report_page = window.current_page
    report_page.start.setDate(QDate.currentDate().addDays(-40))
    report_page.refresh()
    expected_report = demo_service.report(report_page.start.date().toString("yyyy-MM-dd"), report_page.end.date().toString("yyyy-MM-dd"))
    for key, card in report_page.metrics.items():
        assert card.value.text() == f"{expected_report['summary'][key]:,} 원"
    assert report_page.table.rowCount() == len(expected_report["daily"])
    assert messages == []


def test_staff_navigation_and_product_history_access(application, demo_service, tmp_path, messages):
    demo_service.save_user({"username": "catalog", "name": "상품 담당", "password": "catalog-pass", "role": "staff", "permissions": ["products"]})
    demo_service.login("catalog", "catalog-pass")
    window = MainWindow(demo_service, tmp_path / "test.db")
    try:
        assert set(window.nav_buttons) == {"products"}
        original = window.current_page
        window.navigate("settings")
        assert window.current_page is original
        dialog = ProductDialog(demo_service, demo_service.list_products()[0])
        tabs = dialog.findChild(QTabWidget)
        assert all(not tabs.isTabEnabled(index) for index in (1, 2, 3))
        assert messages == []
    finally:
        window.close()
        window.deleteLater()
        application.processEvents()


def test_initial_login_and_business_dialogs_persist(application, service, messages):
    login = LoginDialog(service)
    login.username.setText("admin")
    login.name.setText("서영 관리자")
    login.password.setText("admin-password")
    login.confirm.setText("admin-password")
    login.submit()
    assert login.result() == QDialog.DialogCode.Accepted
    supplier = fill_partner(service, "supplier", "S001", "서영 정육")
    customer = fill_partner(service, "customer", "C001", "서영 식당")
    supplier_edit = PartnerDialog(service, "supplier", supplier)
    supplier_edit.fields["phone"].setText("02-1234-5678")
    supplier_edit.save()
    assert service.list_partners("supplier")[0]["phone"] == "02-1234-5678"
    picker = PartnerPicker(service, "supplier")
    picker.search.setText("홍담당")
    picker.choose()
    assert picker.selected["id"] == supplier["id"]
    product = ProductDialog(service)
    product.fields["code"].setText("P001")
    product.fields["name"].setText("국내산 삼겹살")
    product.purchase_price.setText("18800")
    product.sale_price.setText("38000")
    product.supplier.setCurrentIndex(product.supplier.findData(supplier["id"]))
    product.save()
    assert product.result() == QDialog.DialogCode.Accepted
    product_id = product.saved_id
    purchase = DocumentDialog(service, "purchase", supplier)
    select_product(purchase, product_id)
    assert purchase.total_label.text() == "23,500 원"
    assert purchase.balance_label.text() == "23,500 원"
    purchase.save()
    assert purchase.result() == QDialog.DialogCode.Accepted
    sale = DocumentDialog(service, "sale", customer)
    select_product(sale, product_id, "0.250", "38000")
    sale.paid.setText("1000")
    sale.save()
    assert sale.result() == QDialog.DialogCode.Accepted
    assert service.get_document(sale.saved_id)["total"] == 9500
    assert service.list_products()[0]["stock_qty"] == "1.000"
    edit = ProductDialog(service, service.list_products()[0])
    edit.fields["specification"].setText("냉장 · 구이용")
    edit.load_history(1)
    edit.load_history(2)
    edit.load_history(3)
    assert [edit.history_tables[key].rowCount() for key in ("purchase", "sale", "stock")] == [1, 1, 2]
    edit.save()
    assert service.list_products()[0]["specification"] == "냉장 · 구이용"
    view = DocumentDialog(service, "sale", document_id=sale.saved_id)
    submit_nested(application, view.add_payment)
    assert view.changed
    assert service.get_document(sale.saved_id)["paid"] == 9500
    assert view.balance_label.text() == "0 원"
    assert view.payments_table.rowCount() == 2
    assert messages == []


def test_document_half_up_rounding_and_actual_cancel_modal(application, demo_service, messages):
    supplier = demo_service.list_partners("supplier")[0]
    product_id = demo_service.list_products()[0]["id"]
    document = DocumentDialog(demo_service, "purchase", supplier)
    select_product(document, product_id, "0.001", "1500")
    assert document.total_label.text() == "2 원"
    document.save()
    before_cancel = Decimal(demo_service.list_products()[0]["stock_qty"])
    view = DocumentDialog(demo_service, "purchase", document_id=document.saved_id)
    submit_nested(application, view.cancel_document, lambda modal: modal.findChild(QLineEdit).setText("오입력 취소"))
    assert view.changed
    assert view.balance_label.text() == "0 원"
    assert not view.cancel_button.isEnabled()
    assert demo_service.get_document(document.saved_id)["status"] == "cancelled"
    assert Decimal(demo_service.list_products()[0]["stock_qty"]) == before_cancel - Decimal("0.001")
    assert messages == []


def test_user_dialog_and_password_change(application, demo_service, messages):
    user = UserDialog(demo_service)
    user.username.setText("employee")
    user.name.setText("매입 직원")
    user.password.setText("employee-pass")
    for key, check in user.permissions.items():
        check.setChecked(key == "purchases")
    user.save()
    assert user.result() == QDialog.DialogCode.Accepted
    saved = next(record for record in demo_service.list_users() if record["username"] == "employee")
    assert saved["permissions"] == ["purchases"]
    edit = UserDialog(demo_service, saved)
    edit.name.setText("매입 팀장")
    edit.save()
    assert next(record for record in demo_service.list_users() if record["id"] == saved["id"])["name"] == "매입 팀장"
    password = PasswordDialog(demo_service)
    password.old.setText("Demo-2026!")
    password.new.setText("new-admin-pass")
    password.confirm.setText("new-admin-pass")
    password.save()
    assert password.result() == QDialog.DialogCode.Accepted
    demo_service.logout()
    assert demo_service.login("demo", "new-admin-pass")["role"] == "admin"
    assert messages == []


def test_delete_actions_confirm_and_preserve_protected_records(window, demo_service, messages):
    unused_product = demo_service.save_product({"code": "UNUSED", "name": "삭제할 상품", "unit": "개"})
    window.navigate("products")
    page = window.current_page
    page.search.setText("UNUSED")
    page.refresh()
    page.table.selectRow(0)
    page.delete()
    assert all(record["id"] != unused_product for record in demo_service.list_products())
    unused_partner = demo_service.save_partner({"kind": "supplier", "code": "UNUSED", "name": "삭제할 공급사"})
    window.navigate("suppliers")
    page = window.current_page
    page.search.setText("UNUSED")
    page.refresh()
    page.table.selectRow(0)
    page.delete()
    assert all(record["id"] != unused_partner for record in demo_service.list_partners("supplier"))
    assert messages == []
    window.navigate("users")
    window.current_page.table.selectRow(0)
    window.current_page.delete()
    assert demo_service.users_count() == 1
    assert len(messages) == 1
    assert "로그인" in messages[0][1]


def test_new_product_code_auto_button_preserves_barcode_and_manual_entry(application, service, messages):
    service.create_initial_admin("admin", "관리자", "secure-test-pass")
    service.login("admin", "secure-test-pass")

    dialog = ProductDialog(service)
    assert dialog.findChild(QLineEdit, "product_code").text() == ""
    button = dialog.findChild(
        __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton,
        "product_auto_code_button",
    )
    assert button is not None
    dialog.fields["barcode"].setText("8801234123456")
    button.click()
    assert dialog.fields["code"].text() == "000001"
    assert dialog.fields["barcode"].text() == "8801234123456"
    dialog.fields["name"].setText("자동코드 상품")
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert service.list_products(search="000001")[0]["barcode"] == "8801234123456"

    second = ProductDialog(service)
    second.auto_code_button.click()
    assert second.fields["code"].text() == "000002"
    second.fields["code"].setText("MANUAL-123")
    second.auto_code_button.click()
    assert second.fields["code"].text() == "MANUAL-123"
    assert any("이미 상품코드" in message for _, message in messages)
    dialog.deleteLater()
    second.deleteLater()

