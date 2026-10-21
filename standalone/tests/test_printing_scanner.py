import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QPushButton, QVBoxLayout

from pos2.labels import LabelSize, barcode_bits, label_image, label_printer, print_labels
from pos2.widgets import DataGrid, ScanField


@pytest.fixture(scope="module")
def app():
    result = QApplication.instance() or QApplication([])
    yield result
    for widget in result.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    result.processEvents()


def test_usb_hid_scan_retains_leading_zeros_and_cannot_submit_dialog(app):
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    field = ScanField()
    save = QPushButton("저장")
    save.setDefault(True)
    save.clicked.connect(dialog.accept)
    layout.addWidget(field)
    layout.addWidget(save)
    seen = []
    field.scanned.connect(seen.append)
    dialog.show()
    field.setFocus()
    QTest.keyClicks(field, "0012345678905")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert seen == ["0012345678905"]
    assert dialog.isVisible()
    assert dialog.result() != QDialog.DialogCode.Accepted
    QTest.keyClick(field, Qt.Key.Key_Tab)
    assert seen == ["0012345678905", "0012345678905"]
    dialog.close()


def test_ean_checksum_and_auto_fallback_preserve_registered_number(app):
    bits, kind = barcode_bits("4006381333931")
    assert kind == "EAN-13"
    assert len(bits) == 95
    assert bits.startswith("101") and bits.endswith("101")
    assert barcode_bits("0012345678905")[1] == "Code 128"
    with pytest.raises(ValueError, match="검증 숫자"):
        barcode_bits("0012345678906", "ean13")
    for invalid in ("", "한글바코드", "a\nb"):
        with pytest.raises(ValueError):
            barcode_bits(invalid)


@pytest.mark.parametrize("value", ["4006381333931", "0012345678905", "SKU-0000123"])
def test_rendered_labels_decode_to_exact_scan_value(app, value):
    import zxingcpp
    image = label_image({"barcode": value, "name": "국내산 삼겹살", "unit": "kg", "price": 28000, "origin": "대한민국"}, LabelSize(60, 40))
    # ZXing reads a true rendered image, not the encoder's input text.
    rgb = image.convertToFormat(image.Format.Format_RGB888)
    pixels = rgb.constBits().cast("B", shape=(rgb.height(), rgb.width(), 3))
    result = zxingcpp.read_barcode(pixels)
    assert result is not None
    assert result.text == value


def test_label_pdf_size_copies_and_no_job_on_invalid_symbol(app, tmp_path):
    target = tmp_path / "라벨.pdf"
    size = LabelSize(40, 30)
    printer = label_printer(size, target)
    print_labels(printer, [{"barcode": "4006381333931", "name": "한돈", "price": 10000, "unit": "kg"}], size, copies=2)
    assert target.read_bytes().startswith(b"%PDF-")
    assert target.stat().st_size > 1000
    invalid = tmp_path / "invalid.pdf"
    with pytest.raises(ValueError):
        print_labels(label_printer(size, invalid), [{"barcode": "한글"}], size)
    assert not invalid.exists()


@pytest.mark.parametrize("x,y", [(10, 0), (-10, 0), (0, 10), (0, -10)])
def test_offset_cannot_clip_barcode_or_text_or_start_print_job(app, tmp_path, x, y):
    output = tmp_path / "clipped.pdf"
    size = LabelSize(60, 40, x, y)
    with pytest.raises(ValueError, match="용지 밖"):
        print_labels(label_printer(size, output), [{"barcode": "4006381333931"}], size)
    assert not output.exists()


@pytest.mark.parametrize("x,y", [(2, 1), (-2, -1)])
def test_valid_alignment_offsets_still_decode(app, x, y):
    import zxingcpp
    image = label_image({"barcode": "4006381333931"}, LabelSize(60, 40, x, y))
    rgb = image.convertToFormat(image.Format.Format_RGB888)
    pixels = rgb.constBits().cast("B", shape=(rgb.height(), rgb.width(), 3))
    assert zxingcpp.read_barcode(pixels).text == "4006381333931"


def test_report_pdf_and_numeric_formula_safe_excel(app, tmp_path, monkeypatch):
    grid = DataGrid(["상품", "수량", "금액"])
    grid.fill([["=HYPERLINK(악성)", Decimal("1.250"), 12345], ["<script>&한글", Decimal("2"), -50]])
    output = tmp_path / "현재조회.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(output), ""))
    grid.export(title="조회")
    sheet = load_workbook(output).active
    assert sheet["A2"].data_type == "s"
    assert sheet["B2"].value == 1.25
    assert sheet["C2"].value == 12345
    assert "<script>" not in grid.document_html("<업무>")
    assert "&lt;script&gt;" in grid.document_html()
    pdf = grid.to_pdf(tmp_path / "보고서.pdf", "현재 조회", "거래기간: 2026-10")
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert pdf.stat().st_size > 1000
