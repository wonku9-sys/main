"""Capture the real Qt screens with isolated sample data (no business DB)."""
import argparse
from pathlib import Path
import tempfile

from PySide6.QtGui import QFont
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from seoyoung_pos.app import MainWindow, STYLE
from seoyoung_pos.demo import populate_demo
from seoyoung_pos.dialogs import LoginBackdrop, LoginDialog, ProductDialog, DocumentDialog
from seoyoung_pos.service import POSService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont("Noto Sans CJK KR", 10))
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory(prefix="pos-screens-") as scratch:
        service = POSService(Path(scratch) / "demo.db")
        populate_demo(service)
        member = service.save_member({"code": "M0001", "name": "김서영", "phone": "010-0000-1234", "memo": "샘플 단골 고객"})
        service.adjust_member_points(member, 1200, "샘플 포인트 적립")
        product = service.list_products("삼겹살")[0]
        first = QDate.currentDate().addDays(1 - QDate.currentDate().day())
        service.save_promotion({"product_id": product["id"], "title": "주말 한돈 행사", "date_from": first.toString("yyyy-MM-dd"), "date_to": first.addMonths(1).addDays(-1).toString("yyyy-MM-dd"), "sale_price": 19800, "active": True})
        window = MainWindow(service, service.path, demo=True)
        window.show()
        captured = 0
        for page in ("dashboard", "products", "purchases", "inventory", "ledger", "stocktake", "analysis", "members", "promotions"):
            window.navigate(page)
            app.processEvents()
            assert window.grab().save(str(args.output / f"{page}.png"))
            captured += 1
        product = service.list_products("삼겹살")[0]
        service.save_product({**product, "category_mid": "냉장육", "category_small": "삼겹살",
                              "receipt_name": "국내산 삼겹살", "warehouse": "냉장 1창고",
                              "shelf": "A-03", "keywords": "구이, 냉장, 한돈", "box_quantity": "12.000"}, product["id"])
        product = next(row for row in service.list_products() if row["id"] == product["id"])
        dialog = ProductDialog(service, product, parent=window)
        dialog.show()
        app.processEvents()
        assert dialog.grab().save(str(args.output / "product-detail.png"))
        dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        assert dialog.grab().save(str(args.output / "product-purchase-info.png"))
        dialog.tabs.setCurrentIndex(4)
        app.processEvents()
        assert dialog.grab().save(str(args.output / "product-changes.png"))
        dialog.close()
        registration = ProductDialog(service, parent=window)
        registration.show()
        app.processEvents()
        assert registration.grab().save(str(args.output / "product-new.png"))
        registration.close()
        doc = DocumentDialog(service, "purchase", document_id=service.list_documents("purchase")[0]["id"], parent=window)
        doc.show()
        app.processEvents()
        assert doc.grab().save(str(args.output / "purchase-detail.png"))
        doc.close()
        window.close()
        service.close()
        empty = POSService(Path(scratch) / "initial.db")
        backdrop = LoginBackdrop()
        backdrop.show()
        login = LoginDialog(empty, backdrop)
        login.show()
        app.processEvents()
        assert login.grab().save(str(args.output / "first-run.png"))
        login.close()
        empty.close()
        service = POSService(Path(scratch) / "demo.db")
        login = LoginDialog(service, backdrop)
        login.show()
        app.processEvents()
        assert backdrop.grab().save(str(args.output / "login-workspace.png"))
        # The modal itself is a separate native window; capture it separately too.
        assert login.grab().save(str(args.output / "login.png"))
        login.close()
        backdrop.close()
        service.close()
    print(f"{captured + 8} screenshots captured in {args.output}")


if __name__ == "__main__":
    main()
