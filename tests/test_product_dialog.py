"""Photo-layout product form: real saves, live stock, history and Apply flow."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent, QPoint
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QScrollArea

from seoyoung_pos import app as app_module
from seoyoung_pos.app import STYLE, MainWindow
from seoyoung_pos.dialogs import ProductDialog
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
def store(application, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: errors.append(text))
    service = POSService(tmp_path / "products.db")
    service.create_initial_admin("admin", "관리자", "admin-test-pass")
    service.login("admin", "admin-test-pass")
    supplier = service.save_partner({"kind": "supplier", "code": "S001", "name": "테스트 축산"})
    yield service, supplier, errors
    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    service.close()


def test_photo_groups_tabs_and_apply_save_without_duplicate_products(application, store):
    service, supplier, errors = store
    dialog = ProductDialog(service)
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "상품정보", "매입정보", "판매정보", "재고정보", "변경로그",
    ]
    dialog.fields["code"].setText("P001")
    dialog.fields["name"].setText("국내산 삼겹살")
    dialog.fields["category"].setText("정육")
    dialog.fields["category_mid"].setText("돈육")
    dialog.fields["category_small"].setText("삼겹살")
    dialog.fields["receipt_name"].setText("한돈삼겹")
    dialog.fields["capacity"].setText("500")
    dialog.fields["unit_capacity"].setText("g/팩")
    dialog.fields["warehouse"].setText("냉장1")
    dialog.fields["shelf"].setText("A-03")
    dialog.fields["keywords"].setText("원육키워드")
    dialog.box_quantity.setText("12.500")
    dialog.tax_type.setCurrentIndex(dialog.tax_type.findData("taxable"))
    dialog.supplier.setCurrentIndex(dialog.supplier.findData(supplier))
    dialog.purchase_price.setText("18800")
    dialog.sale_price.setText("38000")
    assert "50.53%" in dialog.margin_label.text()
    dialog.sale_price.setText("15000")
    assert "-25.33%" in dialog.margin_label.text()
    assert "BC4B3B" in dialog.margin_label.styleSheet()
    dialog.sale_price.setText("38000")
    dialog.show()
    application.processEvents()
    dialog.apply_button.click()
    assert errors == []
    assert dialog.isVisible()  # Apply must not close the product form.
    saved = service.list_products("원육키워드")[0]
    assert saved["receipt_name"] == "한돈삼겹"
    assert saved["category_mid"] == "돈육"
    assert saved["warehouse"] == "냉장1"
    assert saved["box_quantity"] == "12.500"
    assert saved["tax_type"] == "taxable"
    dialog.fields["name"].setText("한돈 삼겹살")
    dialog.apply_button.click()
    assert len(service.list_products()) == 1
    assert service.list_products()[0]["id"] == saved["id"]
    dialog.tabs.setCurrentIndex(4)
    assert dialog.change_table.rowCount() == 2
    text = " ".join(dialog.change_table.item(r, 3).text() for r in range(dialog.change_table.rowCount()))
    assert "국내산 삼겹살 → 한돈 삼겹살" in text
    assert errors == []


def test_live_stock_and_filtered_history_excludes_cancelled_totals(application, store):
    service, supplier, errors = store
    pid = service.save_product({"code": "P001", "name": "한우", "unit": "kg"})
    stale_record = service.list_products()[0]
    for day, qty, price in [("2026-10-01", "2", 1000), ("2026-10-15", "3", 2000)]:
        service.create_document("purchase", supplier, day, [{"product_id": pid, "qty": qty, "unit_price": price}])
    cancelled = service.create_document("purchase", supplier, "2026-10-15", [{"product_id": pid, "qty": "1", "unit_price": 3000}])
    service.cancel_document(cancelled, "중복 등록")
    dialog = ProductDialog(service, stale_record)
    assert isinstance(dialog.stock_quantity_label, QLabel)
    assert dialog.stock_quantity_label.text() == "5 kg"
    assert dialog.stock_cost_label.text() == "8,000 원"
    checked, start, end = dialog.history_filters["purchase"]
    checked.setChecked(True)
    start.setDate(QDate(2026, 10, 15))
    end.setDate(QDate(2026, 10, 15))
    dialog.tabs.setCurrentIndex(1)
    assert dialog.history_tables["purchase"].rowCount() == 2
    assert "정상 수량  3 kg" in dialog.history_totals["purchase"].text()
    assert "6,000 원" in dialog.history_totals["purchase"].text()
    assert "취소 제외" in dialog.history_totals["purchase"].text()
    service.adjust_stock(pid, "-0.500", "실사 차이")
    dialog.tabs.setCurrentIndex(4)
    assert dialog.change_table.item(0, 2).text() == "재고 조정"
    assert "실사 차이" in dialog.change_table.item(0, 3).text()
    assert errors == []


def test_product_staff_sees_own_product_changes_without_admin_audit_access(application, store):
    service, _, errors = store
    pid = service.save_product({"code": "P001", "name": "돈육", "unit": "kg"})
    service.save_user({"username": "catalog", "name": "상품 담당", "password": "catalog-pass", "role": "staff", "permissions": ["products"]})
    service.login("catalog", "catalog-pass")
    with pytest.raises(PermissionError):
        service.audit_log()
    dialog = ProductDialog(service, next(r for r in service.list_products() if r["id"] == pid))
    assert all(not dialog.tabs.isTabEnabled(i) for i in (1, 2, 3))
    assert dialog.tabs.isTabEnabled(4)
    dialog.tabs.setCurrentIndex(4)
    assert dialog.change_table.rowCount() == 1
    assert errors == []


def test_short_product_window_keeps_save_and_all_form_fields_reachable(application, store):
    service, _, errors = store
    dialog = ProductDialog(service)
    dialog.resize(900, 680)
    dialog.show()
    application.processEvents()
    scroller = dialog.tabs.widget(0)
    assert isinstance(scroller, QScrollArea)
    scroller.verticalScrollBar().setValue(scroller.verticalScrollBar().maximum())
    assert scroller.verticalScrollBar().value() == scroller.verticalScrollBar().maximum()
    save = dialog.button_box.button(QDialogButtonBox.StandardButton.Save)
    bottom = save.mapTo(dialog, QPoint(0, save.height())).y()
    assert bottom < dialog.height()
    assert dialog.fields["name"].mapTo(dialog, QPoint()).x() < dialog.fields["origin"].mapTo(dialog, QPoint()).x()
    assert dialog.purchase_price.mapTo(dialog, QPoint()).x() < dialog.min_stock.mapTo(dialog, QPoint()).x()
    assert errors == []


def test_catalog_refreshes_after_apply_then_cancel(application, store, monkeypatch):
    service, _, errors = store
    service.save_product({"code": "P001", "name": "수정 전 상품", "unit": "kg"})

    class ApplyThenCancelDialog(ProductDialog):
        def exec(self):
            self.fields["name"].setText("적용 후 상품")
            self.apply_changes()
            self.reject()
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(app_module, "ProductDialog", ApplyThenCancelDialog)
    window = MainWindow(service, service.path)
    window.navigate("products")
    page = window.current_page
    page.table.selectRow(0)
    page.edit()
    assert page.table.item(0, 1).text() == "적용 후 상품"
    assert errors == []


def test_new_major_classification_is_available_in_catalog_filter(application, store):
    service, _, errors = store
    service.save_product({"code": "P001", "name": "식육", "category": "사용자 정의 분류"})
    service.save_product({"code": "P002", "name": "양념육", "category": "다른 분류"})
    window = MainWindow(service, service.path)
    window.navigate("products")
    page = window.current_page
    index = page.category.findText("사용자 정의 분류")
    assert index > 0
    page.category.setCurrentIndex(index)
    page.refresh()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "식육"
    assert errors == []
