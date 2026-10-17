"""Capture the real Qt screens with isolated sample data (no business DB)."""
import argparse
from pathlib import Path
import tempfile

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from seoyoung_pos.app import MainWindow, STYLE
from seoyoung_pos.demo import populate_demo
from seoyoung_pos.dialogs import LoginDialog, ProductDialog, DocumentDialog
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
        window = MainWindow(service, service.path, demo=True)
        window.show()
        for page in ("dashboard", "products", "purchases", "inventory"):
            window.navigate(page)
            app.processEvents()
            assert window.grab().save(str(args.output / f"{page}.png"))
        product = service.list_products("삼겹살")[0]
        dialog = ProductDialog(service, product, parent=window)
        dialog.show()
        app.processEvents()
        assert dialog.grab().save(str(args.output / "product-detail.png"))
        dialog.close()
        doc = DocumentDialog(service, "purchase", document_id=service.list_documents("purchase")[0]["id"], parent=window)
        doc.show()
        app.processEvents()
        assert doc.grab().save(str(args.output / "purchase-detail.png"))
        doc.close()
        window.close()
        service.close()
        empty = POSService(Path(scratch) / "initial.db")
        login = LoginDialog(empty)
        login.show()
        app.processEvents()
        assert login.grab().save(str(args.output / "first-run.png"))
        login.close()
        empty.close()
    print(f"7 screenshots captured in {args.output}")


if __name__ == "__main__":
    main()
