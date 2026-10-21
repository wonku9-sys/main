from datetime import date, timedelta

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox

from pos2.payment_ui import SupplierPaymentDialog, SupplierPaymentsPage
from pos2.store import Store


@pytest.fixture
def shop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "settlement.db")
    store.setup_admin("owner", "관리자", "Owner-Password-2026!")
    supplier = store.save_partner({"kind": "supplier", "code": "S01", "name": "서영 축산", "opening_balance": 1000, "opening_date": "2025-01-01"})
    other = store.save_partner({"kind": "supplier", "code": "S02", "name": "매입 없는 공급사", "opening_date": "2025-01-01"})
    product = store.save_product({"name": "삼겹살", "supplier_id": supplier, "purchase_price": 100})
    first = store.post_document({"kind": "purchase", "date": "2025-01-10", "partner_id": supplier, "lines": [{"product_id": product, "qty": "10", "unit_price": 100}], "paid": 0})
    second = store.post_document({"kind": "purchase", "date": "2025-02-10", "partner_id": supplier, "lines": [{"product_id": product, "qty": "20", "unit_price": 100}], "paid": 0})
    window = QMainWindow()
    window.store, window.messages = store, []
    window.notify = window.messages.append
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)
    yield app, store, window, supplier, other, product, first, second
    for widget in app.topLevelWidgets():
        widget.close()
    store.close()


def test_initial_debt_then_oldest_documents_allocation_and_single_history_row(shop):
    _, store, _, supplier, _, _, first, second = shop
    initial = store.supplier_outstanding(supplier)
    assert initial["cap"] == 4000 and initial["opening"] == 1000
    payment = store.settle_supplier(supplier, 2500, date.today(), "transfer", "월 결제", initial["state"])
    detail = store.supplier_settlement_detail(payment)
    assert detail["opening_amount"] == 1000
    assert [(r["document_id"], r["amount"]) for r in detail["allocations"]] == [(first, 1000), (second, 500)]
    assert store.document(first)["balance"] == 0
    assert store.document(second)["balance"] == 1500
    assert store.partners("supplier", "S01")[0]["balance"] == 1500
    ledger = store.ledger(supplier)
    assert ledger["charge"] == 4000 and ledger["payment"] == 2500 and ledger["closing"] == 1500
    history = store.supplier_payment_history("2025-01-01", date.today(), supplier)
    assert len(history) == 1 and history[0]["type"] == "settlement" and history[0]["amount"] == 2500
    # Idempotent UI snapshot prevents a double click from becoming another payment.
    with pytest.raises(ValueError, match="바뀌었"):
        store.settle_supplier(supplier, 100, date.today(), expected_state=initial["state"])
    assert store.supplier_outstanding(supplier)["cap"] == 1500


def test_period_carry_only_suppliers_with_purchases_and_all_reset(shop):
    store, supplier, other = shop[1], shop[3], shop[4]
    rows = store.supplier_summary("2025-02-01", "2025-02-28", only_purchases=True)
    assert len(rows) == 1 and rows[0]["id"] == supplier
    assert (rows[0]["opening"], rows[0]["purchase"], rows[0]["closing"]) == (2000, 2000, 4000)
    assert len(store.supplier_summary("2025-02-01", "2025-02-28")) == 2
    assert store.supplier_summary("2025-02-01", "2025-02-28", "S02")[0]["id"] == other


@pytest.mark.parametrize("value,when,method", [(4001, "2025-03-01", "cash"), (1, "2024-12-31", "cash"), (2001, "2025-01-15", "transfer"), (0, "2025-03-01", "cash"), (-1, "2025-03-01", "cash"), (1, "2025-03-01", "unsupported")])
def test_invalid_or_date_excessive_payment_has_no_partial_effect(shop, value, when, method):
    store = shop[1]
    with pytest.raises(ValueError):
        store.settle_supplier(shop[3], value, when, method)
    assert store.db.execute("SELECT COUNT(*) FROM supplier_settlements").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    assert store.supplier_outstanding(shop[3])["cap"] == 4000


def test_future_date_and_changed_permission_are_rejected(shop):
    store = shop[1]
    with pytest.raises(ValueError, match="미래"):
        store.settle_supplier(shop[3], 1, date.today() + timedelta(days=1))
    store.save_user({"code": "staff", "name": "직원", "password": "Staff-Password-2026!", "role": "staff", "permissions": ["catalog"]})
    store.login("staff", "Staff-Password-2026!")
    with pytest.raises(PermissionError):
        store.settle_supplier(shop[3], 1, date.today())
    with pytest.raises(PermissionError):
        store.supplier_payment_history("2025-01-01", date.today())


def test_failed_second_allocation_rolls_back_opening_group_payments_and_audit(shop, monkeypatch):
    store = shop[1]
    insert = store._insert_trade_payment
    calls = []
    def fail_second(*args):
        calls.append(args[0])
        if len(calls) == 2:
            raise ValueError("injected allocation failure")
        return insert(*args)
    monkeypatch.setattr(store, "_insert_trade_payment", fail_second)
    with pytest.raises(ValueError, match="injected"):
        store.settle_supplier(shop[3], 3500, date.today())
    assert store.db.execute("SELECT COUNT(*) FROM supplier_settlements").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    assert store.supplier_outstanding(shop[3])["cap"] == 4000
    assert not store.db.execute("SELECT 1 FROM audit WHERE action='supplier_settlement'").fetchone()


def test_group_cannot_be_partially_voided_and_whole_same_day_void_restores_all_debt(shop):
    store = shop[1]
    group = store.settle_supplier(shop[3], 2500, date.today(), "transfer")
    detail = store.supplier_settlement_detail(group)
    with pytest.raises(ValueError, match="묶음"):
        store.void_payment(detail["allocations"][0]["id"], "부분 취소 금지")
    store.void_supplier_settlement(group, "중복 입력 정정")
    assert store.supplier_outstanding(shop[3])["cap"] == 4000
    assert store.ledger(shop[3])["payment"] == 0
    history = store.supplier_payment_history("2025-01-01", date.today())
    assert len(history) == 1 and history[0]["voided"]
    assert not store.supplier_payment_history("2025-01-01", date.today(), include_voided=False)
    with pytest.raises(ValueError, match="이미 취소"):
        store.void_supplier_settlement(group, "또 취소")


def test_past_payment_cannot_be_changed_and_closed_cash_blocks_registration(shop):
    store = shop[1]
    group = store.settle_supplier(shop[3], 100, date.today() - timedelta(days=1), "transfer")
    with pytest.raises(ValueError, match="당일"):
        store.void_supplier_settlement(group, "지난 날짜")
    store.cash_close({"date": date.today(), "opening_cash": 0, "counted_cash": 0})
    with pytest.raises(ValueError, match="마감"):
        store.settle_supplier(shop[3], 100, date.today(), "cash")
    store.settle_supplier(shop[3], 100, date.today(), "transfer")


def test_supplier_summary_and_legacy_payment_refund_history_include_real_returns(shop):
    store, supplier, first = shop[1], shop[3], shop[6]
    store.add_payment(first, 1000, "2025-01-11", "transfer")
    source = store.document(first)
    store.post_document({"kind": "purchase_return", "date": "2025-01-12", "partner_id": supplier, "source_id": first, "lines": [{"product_id": shop[5], "source_line_id": source["lines"][0]["id"], "qty": "2"}], "paid": 200, "method": "transfer"})
    rows = store.supplier_payment_history("2025-01-01", "2025-01-31", supplier)
    assert sorted(r["amount"] for r in rows) == [-200, 1000]
    assert store.supplier_summary("2025-01-01", "2025-01-31", partner_id=supplier)[0]["payment"] == 800
    assert store.supplier_outstanding(supplier)["cap"] == 3000


def test_new_settlement_is_preserved_and_restored_with_other_business_data(shop):
    store = shop[1]
    group = store.settle_supplier(shop[3], 2500, date.today(), "transfer")
    backup = store.create_backup()
    store.void_supplier_settlement(group, "백업 후 변경")
    store.restore_backup(backup, "Owner-Password-2026!")
    store.login("owner", "Owner-Password-2026!")
    assert not store.supplier_settlement_detail(group)["voided"]
    assert store.supplier_outstanding(shop[3])["cap"] == 1500
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_payment_page_menu_drilldown_current_tab_export_and_real_dialog_commit(shop, monkeypatch):
    app, store, window, supplier = shop[:4]
    page = SupplierPaymentsPage(window)
    page.start.setDate(QDate(2025, 2, 1))
    page.end.setDate(QDate.currentDate())
    page.refresh()
    assert page.grid.rowCount() == 2
    page.only_purchases.setChecked(True)
    assert page.grid.rowCount() == 1
    page.grid.selectRow(0)
    page.drill_down()
    assert page.partner.currentData() == supplier and page.tabs.currentIndex() == 1
    assert page.ledger_grid.rowCount() == 1
    captured = []
    monkeypatch.setattr(page.ledger_grid, "export", lambda *args: captured.append("ledger"))
    page.export()
    assert captured == ["ledger"]
    dialog = SupplierPaymentDialog(window, supplier)
    assert dialog.amount.text() == "4000.00" and dialog.grid.rowCount() == 3
    dialog.amount.setText("2500")
    dialog.method.setCurrentIndex(1)
    monkeypatch.setattr("pos2.payment_ui._confirm", lambda *_: True)
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.saved_id
    page.refresh()
    assert page.history_grid.rowCount() == 1
    assert "1,500" in page.summary.text()
    # Repeated queued clicks cannot register the same dialog twice.
    dialog.save()
    assert len(store.supplier_payment_history("2025-01-01", date.today())) == 1


def test_payment_popup_cancel_and_stale_snapshot_have_no_hidden_commit(shop, monkeypatch):
    store, supplier = shop[1], shop[3]
    dialog = SupplierPaymentDialog(shop[2], supplier)
    monkeypatch.setattr("pos2.payment_ui._confirm", lambda *_: False)
    dialog.save()
    assert not dialog.saved_id
    assert store.supplier_payment_history("2025-01-01", date.today()) == []
    store.settle_supplier(supplier, 100, date.today(), "transfer")
    monkeypatch.setattr("pos2.payment_ui._confirm", lambda *_: True)
    dialog.amount.setText("100")
    dialog.save()
    assert not dialog.saved_id and "다시 조회" in dialog.error.text()


def test_group_void_is_atomic_when_one_allocation_would_invalidate_a_refund(shop):
    store, supplier, product = shop[1], shop[3], shop[5]
    group = store.settle_supplier(supplier, 4000, date.today(), "transfer")
    source = store.document(shop[7])
    store.post_document({"kind": "purchase_return", "date": date.today(), "partner_id": supplier, "source_id": source["id"], "lines": [{"product_id": product, "source_line_id": source["lines"][0]["id"], "qty": "1"}], "paid": 100, "method": "transfer"})
    with pytest.raises(ValueError, match="환불"):
        store.void_supplier_settlement(group, "환불된 결제 취소 불가")
    assert not store.supplier_settlement_detail(group)["voided"]
    assert all(not row["voided"] for row in store.supplier_settlement_detail(group)["allocations"])


def test_bad_settlement_backup_is_rejected_without_replacing_current_data(shop, tmp_path):
    import sqlite3
    store = shop[1]
    group = store.settle_supplier(shop[3], 2000, date.today(), "transfer")
    file = tmp_path / "bad-allocation.db"
    store.backup(file)
    db = sqlite3.connect(file)
    try:
        db.execute("UPDATE supplier_settlements SET amount=amount+1 WHERE id=?", (group,))
        db.commit()
    finally:
        db.close()
    with pytest.raises(ValueError, match="배분"):
        store.restore_backup(file, "Owner-Password-2026!")
    assert store.supplier_outstanding(shop[3])["cap"] == 2000
    assert len(store.supplier_payment_history("2025-01-01", date.today())) == 1


def test_no_purchase_supplier_can_settle_initial_debt_only(shop):
    store = shop[1]
    partner = store.save_partner({"kind": "supplier", "name": "기초 외상만", "opening_balance": 500, "opening_date": "2025-01-01"})
    group = store.settle_supplier(partner, 300, date.today(), "transfer")
    assert not store.supplier_settlement_detail(group)["allocations"]
    assert store.supplier_outstanding(partner)["cap"] == 200
    assert store.ledger(partner)["closing"] == 200
