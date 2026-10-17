"""Business invariants: monetary precision, authorization and atomic persistence."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import tempfile
import unittest

from seoyoung_pos.service import POSService
from seoyoung_pos.security import hash_password, verify_password


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.service = POSService(self.path)
        self.admin = self.service.create_initial_admin("admin", "관리자", "secure-test-pass")
        self.service.login("admin", "secure-test-pass")
        self.supplier = self.service.save_partner({"kind": "supplier", "code": "S001", "name": "서영 공급사"})
        self.customer = self.service.save_partner({"kind": "customer", "code": "C001", "name": "서영 고객"})
        self.product = self.service.save_product({"code": "P001", "name": "국내산 삼겹살", "unit": "kg", "purchase_price": 18000, "sale_price": 28000, "min_stock": "2.500", "supplier_id": self.supplier})

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def document(self, kind="purchase", qty="10.000", price=18000, paid=0):
        return self.service.create_document(kind, self.supplier if kind == "purchase" else self.customer,
                                            "2026-10-17", [{"product_id": self.product, "qty": qty, "unit_price": price}], paid=paid)

    def test_persistence_and_readable_backup(self):
        document_id = self.document(qty="1.250", price=18000)
        backup = Path(self.temp.name) / "backup.sqlite3"
        self.service.backup(backup)
        with self.assertRaises(ValueError):
            self.service.backup(backup)
        self.service.close()
        self.service = POSService(self.path)
        self.service.login("admin", "secure-test-pass")
        self.assertEqual(self.service.get_document(document_id)["total"], 22500)
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "1.250")
        restored = POSService(backup)
        restored.login("admin", "secure-test-pass")
        self.assertEqual(restored.get_document(document_id)["total"], 22500)
        restored.close()

    def test_passwords_are_salted_and_never_exposed(self):
        encoded = self.service.db.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotIn("secure-test-pass", encoded)
        self.assertTrue(verify_password("secure-test-pass", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))
        self.assertNotEqual(encoded, hash_password("secure-test-pass"))
        self.assertNotIn("password_hash", self.service.list_users()[0])
        self.service.change_password("secure-test-pass", "changed-password")
        with self.assertRaises(ValueError):
            self.service.login("admin", "secure-test-pass")
        self.service.login("ADMIN", "changed-password")
        audit = str(self.service.audit_log())
        self.assertNotIn("secure-test-pass", audit)
        self.assertNotIn("changed-password", audit)
        self.assertNotIn("pbkdf2_sha256$", audit)

    def test_failed_login_clears_previous_session(self):
        self.assertIsNotNone(self.service.user)
        with self.assertRaises(ValueError):
            self.service.login("admin", "wrong-password")
        self.assertIsNone(self.service.user)
        with self.assertRaises(PermissionError):
            self.service.list_users()

    def test_permissions_refresh_from_database_and_protect_admin_settings(self):
        staff = self.service.save_user({"username": "staff", "name": "직원", "password": "staff-password", "role": "staff", "permissions": ["products"]})
        self.service.login("staff", "staff-password")
        self.assertTrue(self.service.has_permission("products"))
        self.assertEqual(len(self.service.list_products()), 1)
        with self.assertRaises(PermissionError):
            self.document()
        with self.assertRaises(PermissionError):
            self.service.list_users()
        with self.assertRaises(PermissionError):
            self.service.backup(Path(self.temp.name) / "notallowed.sqlite3")
        self.service.login("admin", "secure-test-pass")
        with self.assertRaises(ValueError):
            self.service.save_user({"username": "staff", "name": "직원", "role": "staff", "permissions": ["users"]}, staff)
        self.service.save_user({"username": "staff", "name": "직원", "role": "staff", "permissions": []}, staff)
        self.service.login("staff", "staff-password")
        self.assertFalse(self.service.has_permission("products"))
        self.service.logout()
        with self.assertRaises(PermissionError):
            self.service.list_products()

    def test_current_and_last_admin_are_protected(self):
        with self.assertRaises(ValueError):
            self.service.delete_user(self.admin["id"])
        with self.assertRaises(ValueError):
            self.service.save_user({"username": "admin", "name": "관리자", "role": "staff", "permissions": []}, self.admin["id"])
        other = self.service.save_user({"username": "other", "name": "다른 관리자", "password": "another-password", "role": "admin"})
        self.service.delete_user(other)
        self.assertEqual(self.service.users_count(), 1)
        with self.assertRaises(ValueError):
            self.service.create_initial_admin("new", "신규", "another-password")

    def test_exact_amounts_and_strict_quantity_precision(self):
        document_id = self.document(qty="0.125", price=1004)
        document = self.service.get_document(document_id)
        self.assertEqual(document["total"], 126)  # 125.5 -> 126, not binary float rounding.
        self.assertEqual(document["items"][0]["qty"], "0.125")
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "0.125")
        for qty in ("0", "-1", "0.0001", "NaN", "Infinity", "1e999999999"):
            with self.subTest(qty=qty), self.assertRaises(ValueError):
                self.document(qty=qty)
        with self.assertRaises(ValueError):
            self.document(price="1.5")
        with self.assertRaises(ValueError):
            self.document(qty="1", price=1, paid=2)

    def test_sale_cost_profit_and_cancellation_restore_stock(self):
        self.document(qty="2", price=1000)
        self.document(qty="2", price=2000)
        sale = self.document(kind="sale", qty="1.500", price=3000)
        self.assertEqual(self.service.get_document(sale)["total"], 4500)
        self.assertEqual(self.service.get_document(sale)["items"][0]["cost"], 2250)
        self.assertEqual(self.service.dashboard()["profit"], 2250)
        self.assertEqual(self.service.dashboard()["stock_value"], 3750)
        self.service.cancel_document(sale, "중복 입력")
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "4.000")
        self.assertEqual(self.service.dashboard()["profit"], 0)
        self.assertEqual(self.service.dashboard()["stock_value"], 6000)
        with self.assertRaises(ValueError):
            self.service.cancel_document(sale, "재취소")

    def test_insufficient_stock_rolls_back_entire_document(self):
        self.document(qty="1")
        count_before = len(self.service.list_documents("sale"))
        moves_before = len(self.service.list_stock_movements())
        with self.assertRaises(ValueError):
            self.service.create_document("sale", self.customer, "2026-10-17", [
                {"product_id": self.product, "qty": ".500", "unit_price": 28000},
                {"product_id": self.product, "qty": ".600", "unit_price": 28000},
            ])
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "1.000")
        self.assertEqual(len(self.service.list_documents("sale")), count_before)
        self.assertEqual(len(self.service.list_stock_movements()), moves_before)

    def test_invalid_late_line_rolls_back_purchase_and_audit(self):
        audit_before = len(self.service.audit_log())
        with self.assertRaises(ValueError):
            self.service.create_document("purchase", self.supplier, "2026-10-17", [
                {"product_id": self.product, "qty": "1", "unit_price": 1000},
                {"product_id": 99999, "qty": "1", "unit_price": 1000},
            ])
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "0.000")
        self.assertEqual(len(self.service.list_documents("purchase")), 0)
        self.assertEqual(len(self.service.audit_log()), audit_before)

    def test_payments_prevent_overpayment_and_cancellation_and_report_by_payment_date(self):
        doc = self.document(qty="1", price=1000, paid=250)
        self.assertEqual(self.service.list_partners("supplier")[0]["balance"], 750)
        self.service.add_payment(doc, 500, "2026-10-18", "계좌 이체")
        self.assertEqual(self.service.get_document(doc)["paid"], 750)
        self.assertEqual(self.service.dashboard()["payable"], 250)
        with self.assertRaises(ValueError):
            self.service.add_payment(doc, 251, "2026-10-18")
        with self.assertRaises(ValueError):
            self.service.add_payment(doc, 1, "2026-10-16")
        with self.assertRaises(ValueError):
            self.service.cancel_document(doc, "입력 오류")
        report = self.service.report("2026-10-18", "2026-10-18")
        self.assertEqual(report["daily"][0]["paid_purchase"], 500)
        self.assertEqual(report["summary"]["purchase_total"], 0)
        self.assertEqual(report["summary"]["payable"], 250)  # Outstanding is a current balance.

    def test_purchase_cancellation_is_atomic_when_stock_was_sold(self):
        doc = self.document(qty="1", price=1000)
        self.document(kind="sale", qty=".500", price=2000)
        with self.assertRaises(ValueError):
            self.service.cancel_document(doc, "잘못된 매입")
        self.assertEqual(self.service.get_document(doc)["status"], "posted")
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "0.500")
        self.assertEqual(self.service.dashboard()["stock_value"], 500)

    def test_purchase_cancellation_preserves_valuation_after_later_sales(self):
        cheap = self.document(qty="10", price=100)
        self.document(qty="10", price=200)
        sale = self.document(kind="sale", qty="10", price=400)
        # Quantity alone would permit cancellation but would leave 500 won with zero stock.
        with self.assertRaises(ValueError):
            self.service.cancel_document(cheap, "과거 매입 취소")
        self.assertEqual(self.service.dashboard()["stock_value"], 1500)
        self.service.cancel_document(sale, "매출 취소 후 매입 정정")
        self.service.cancel_document(cheap, "매입 취소")
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "10.000")
        self.assertEqual(self.service.dashboard()["stock_value"], 2000)

    def test_later_negative_adjustment_prevents_old_purchase_cancellation(self):
        doc = self.document(qty="10", price=100)
        self.document(qty="10", price=200)
        self.service.adjust_stock(self.product, "-1", "폐기")
        with self.assertRaises(ValueError):
            self.service.cancel_document(doc, "매입 정정")
        self.assertEqual(self.service.get_document(doc)["status"], "posted")
        self.assertEqual(self.service.dashboard()["stock_value"], 2850)

    def test_unit_and_supplier_kind_cannot_corrupt_existing_stock(self):
        self.document()
        with self.assertRaises(ValueError):
            self.service.save_product({"code": "P001", "name": "국내산 삼겹살", "unit": "g"}, self.product)
        self.assertEqual(self.service.list_stock()[0]["unit"], "kg")
        with self.assertRaises(ValueError):
            self.service.save_product({"code": "P002", "name": "잘못된 공급사 상품", "supplier_id": self.customer})
        with self.assertRaises(ValueError):
            self.service.save_partner({"kind": "customer", "code": "S001", "name": "변경"}, self.supplier)

    def test_backdated_documents_use_posting_order_for_cost_and_business_date_for_report(self):
        self.document(qty="10", price=100)
        self.service.create_document("purchase", self.supplier, "2026-10-01", [{"product_id": self.product, "qty": "10", "unit_price": 200}])
        sale = self.service.create_document("sale", self.customer, "2026-10-02", [{"product_id": self.product, "qty": "1", "unit_price": 300}])
        self.assertEqual(self.service.get_document(sale)["items"][0]["cost"], 150)
        report = self.service.report("2026-10-01", "2026-10-02")
        self.assertEqual(report["summary"]["purchase_total"], 2000)
        self.assertEqual(report["summary"]["sale_total"], 300)
        self.assertEqual(report["summary"]["profit"], 150)

    def test_concurrent_sales_cannot_oversell_same_stock(self):
        self.document(qty="1", price=1000)
        barrier = Barrier(2)
        def sell():
            other = POSService(self.path)
            try:
                other.login("admin", "secure-test-pass")
                barrier.wait(timeout=10)
                try:
                    return other.create_document("sale", self.customer, "2026-10-17", [{"product_id": self.product, "qty": ".750", "unit_price": 2000}])
                except ValueError as exc:
                    return str(exc)
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: sell(), range(2)))
        self.assertEqual(sum(isinstance(result, int) for result in outcomes), 1)
        self.assertTrue(any(isinstance(result, str) and "재고가 부족" in result for result in outcomes))
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "0.250")
        self.assertEqual(len(self.service.list_documents("sale")), 1)

    def test_concurrent_payments_cannot_overpay(self):
        doc = self.document(qty="1", price=1000)
        barrier = Barrier(2)
        def settle():
            other = POSService(self.path)
            try:
                other.login("admin", "secure-test-pass")
                barrier.wait(timeout=10)
                try:
                    other.add_payment(doc, 750, "2026-10-17")
                    return True
                except ValueError as exc:
                    return str(exc)
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: settle(), range(2)))
        self.assertEqual(sum(result is True for result in outcomes), 1)
        self.assertEqual(self.service.get_document(doc)["paid"], 750)
        self.assertEqual(len(self.service.get_document(doc)["payments"]), 1)

    def test_adjustment_and_history_and_history_deletion_protection(self):
        self.service.adjust_stock(self.product, "2.125", "최초 실사")
        self.service.adjust_stock(self.product, "-.125", "폐기")
        self.assertEqual(self.service.list_stock()[0]["stock_qty"], "2.000")
        self.assertEqual(self.service.list_stock_movements()[0]["balance_qty"], "2.000")
        self.assertEqual(self.service.dashboard()["stock_value"], 36000)
        with self.assertRaises(ValueError):
            self.service.adjust_stock(self.product, "-3", "과다 차감")
        with self.assertRaises(ValueError):
            self.service.delete_product(self.product)
        self.document()
        self.assertEqual(self.service.product_history(self.product, "purchase")[0]["qty"], "10.000")
        with self.assertRaises(ValueError):
            self.service.delete_partner(self.supplier)

    def test_duplicate_codes_and_invalid_partner_do_not_leak_database_errors(self):
        with self.assertRaises(ValueError):
            self.service.save_product({"code": "P001", "name": "중복"})
        with self.assertRaises(ValueError):
            self.service.create_document("purchase", self.customer, "2026-10-17", [{"product_id": self.product, "qty": "1", "unit_price": 1000}])
        with self.assertRaises(ValueError):
            self.service.create_document("purchase", self.supplier, "2026-02-30", [{"product_id": self.product, "qty": "1", "unit_price": 1000}])


if __name__ == "__main__":
    unittest.main()
