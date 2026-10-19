"""Driver-based label printing, with real Code128/EAN13 barcode symbols."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import isfinite
from pathlib import Path

from barcode import Code128, EAN13
from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QFont, QImage, QPageLayout, QPageSize, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
)

from .widgets import DataGrid, action, amount, won
from .font_support import font_family,regular_font


def barcode_bits(value, mode="auto"):
    if mode not in {"auto", "code128", "ean13"}:
        raise ValueError("지원하지 않는 바코드 형식입니다.")
    value = str(value)
    if not value or len(value) > 80 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError("라벨 바코드는 1~80자의 영문·숫자·ASCII 기호여야 합니다.")
    valid_ean = len(value) == 13 and value.isascii() and value.isdigit() and int(value[-1]) == (-sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value[:12]))) % 10
    if mode == "ean13" and not valid_ean:
        raise ValueError("EAN-13은 검증 숫자가 올바른 13자리 바코드만 출력합니다.")
    # Many scanners normalize EAN-13 starting with 0 to 12-digit UPC-A. Code128
    # preserves the exact registered code in automatic mode, including zeros.
    use_ean = valid_ean and mode != "code128" and (mode == "ean13" or not value.startswith("0"))
    symbol = EAN13(value[:12]) if use_ean else Code128(value)
    encoded = symbol.build()[0]
    return encoded, "EAN-13" if use_ean else "Code 128"


@dataclass(frozen=True)
class LabelSize:
    width: float = 60.0
    height: float = 40.0
    offset_x: float = 0.0
    offset_y: float = 0.0

    def validate(self):
        if not all(isfinite(v) for v in (self.width, self.height, self.offset_x, self.offset_y)):
            raise ValueError("라벨 크기와 위치는 유한한 숫자로 지정하세요.")
        if not 30 <= self.width <= 150 or not 20 <= self.height <= 150:
            raise ValueError("라벨 크기는 가로 30~150mm, 세로 20~150mm로 지정하세요.")
        if abs(self.offset_x) > 10 or abs(self.offset_y) > 10:
            raise ValueError("출력 위치 보정은 ±10mm 이내로 지정하세요.")


def paint_label(painter, item, size, mode="auto"):
    """Painter coordinates are millimetres; no OS-dependent bitmap fonts/barcodes."""
    size.validate()
    value = str(item.get("barcode", ""))
    bits, _ = barcode_bits(value, mode)
    available = size.width - 5
    module = available / (len(bits) + 20)  # Quiet zones remain 10 modules each.
    if module < 0.19:
        raise ValueError("바코드가 너무 깁니다. 라벨 폭을 넓히거나 더 짧은 바코드를 등록하세요.")
    # The content includes the full barcode quiet zones. Offsets compensate a
    # small driver alignment error; they must never silently clip a symbol.
    if (2.5 + size.offset_x < 0 or size.width - 2.5 + size.offset_x > size.width
            or 1.5 + size.offset_y < 0 or size.height * .94 + size.offset_y > size.height):
        raise ValueError("위치 보정으로 글자·바코드·여백이 용지 밖으로 나갑니다. 보정값을 줄이세요.")
    painter.save()
    painter.translate(size.offset_x, size.offset_y)
    painter.fillRect(QRectF(0, 0, size.width, size.height), Qt.GlobalColor.white)
    font = regular_font()
    font.setPixelSize(3 if size.height >= 30 else 2)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(Qt.GlobalColor.black)
    painter.drawText(QRectF(2.5, 1.5, size.width - 5, size.height * .19), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(item.get("name", "")))
    font.setPixelSize(4 if size.height >= 30 else 3)
    painter.setFont(font)
    painter.drawText(QRectF(2.5, size.height * .22, size.width - 5, size.height * .18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{won(item.get('price', 0))}원 / {item.get('unit', '')}")
    font.setPixelSize(2)
    font.setBold(False)
    painter.setFont(font)
    painter.drawText(QRectF(2.5, size.height * .39, size.width - 5, size.height * .12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(item.get("origin", "")))
    start_x = 2.5 + 10 * module
    top, height = size.height * .53, size.height * .26
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.GlobalColor.black)
    for index, bit in enumerate(bits):
        if bit == "1":
            painter.drawRect(QRectF(start_x + index * module, top, module, height))
    painter.setPen(Qt.GlobalColor.black)
    painter.drawText(QRectF(2.5, size.height * .80, size.width - 5, size.height * .14), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, value)
    painter.restore()


def label_image(item, size=LabelSize(), mode="auto"):
    size.validate()
    image = QImage(round(size.width * 10), round(size.height * 10), QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    try:
        painter.scale(10, 10)
        paint_label(painter, item, size, mode)
    finally:
        painter.end()
    return image


def label_printer(size, pdf_path=None):
    size.validate()
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setResolution(300)
    if pdf_path is not None:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(pdf_path))
    printer.setFullPage(True)
    page = QPageSize(QSizeF(size.width, size.height), QPageSize.Unit.Millimeter, "서영 사용자 라벨", QPageSize.SizeMatchPolicy.ExactMatch)
    printer.setPageSize(page)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    return printer


def print_labels(printer, items, size, copies=1, mode="auto"):
    if not items or not 1 <= int(copies) <= 1000 or len(items) * int(copies) > 5000:
        raise ValueError("출력할 상품을 선택하고 총 라벨 수를 5,000장 이하로 지정하세요.")
    # Validate all symbols before starting a physical print job.
    for item in items:
        label_image(item, size, mode)
    actual = printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter)
    if abs(actual.width() - size.width) > 1 or abs(actual.height() - size.height) > 1:
        raise ValueError("프린터의 용지 크기가 지정한 라벨 크기와 다릅니다. 드라이버에서 같은 크기로 설정하세요.")
    painter = QPainter()
    if not painter.begin(printer):
        raise OSError("프린터 출력 장치를 시작하지 못했습니다. 드라이버와 연결 상태를 확인하세요.")
    try:
        first = True
        for item in items:
            for _ in range(int(copies)):
                if not first and not printer.newPage():
                    raise OSError("다음 라벨 페이지를 출력하지 못했습니다.")
                first = False
                painter.save()
                painter.scale(printer.resolution() / 25.4, printer.resolution() / 25.4)
                paint_label(painter, item, size, mode)
                painter.restore()
    finally:
        painter.end()


class LabelDialog(QDialog):
    def __init__(self, store, product_ids=None, parent=None):
        super().__init__(parent)
        self.store = store
        store._require("catalog")
        self.setWindowTitle("상품 라벨 · 바코드 출력 · SY POS 독립판")
        self.resize(1000, 760)
        self.body = QVBoxLayout(self)
        heading = QLabel("라벨 출력")
        heading.setObjectName("dialogTitle")
        self.body.addWidget(heading)
        hint = QLabel("Windows에 설치된 프린터 드라이버를 사용합니다. 실제 라벨 크기·간격을 드라이버에도 동일하게 설정하고 먼저 1장 시험 출력하세요.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        self.body.addWidget(hint)
        options = QHBoxLayout()
        self.width, self.height = QDoubleSpinBox(), QDoubleSpinBox()
        for field, value, low in ((self.width, 60, 30), (self.height, 40, 20)):
            field.setRange(low, 150)
            field.setDecimals(1)
            field.setSuffix(" mm")
            field.setValue(value)
        self.copies = QSpinBox()
        self.copies.setRange(1, 1000)
        self.copies.setValue(1)
        self.mode = QComboBox()
        for title, value in (("자동(EAN-13 / Code 128)", "auto"), ("Code 128", "code128"), ("EAN-13", "ean13")):
            self.mode.addItem(title, value)
        self.x, self.y = QDoubleSpinBox(), QDoubleSpinBox()
        for field in (self.x, self.y):
            field.setRange(-10, 10)
            field.setDecimals(1)
            field.setSuffix(" mm")
        for text, field in (("가로", self.width), ("세로", self.height), ("상품당 장수", self.copies), ("바코드", self.mode), ("X 보정", self.x), ("Y 보정", self.y)):
            options.addWidget(QLabel(text))
            options.addWidget(field)
        self.body.addLayout(options)
        self.grid = DataGrid(["상품", "출력 단위", "바코드", "라벨 가격", "원산지"])
        products = store.products(active_only=True)
        selected = set(product_ids or [])
        self.items = []
        for product in products:
            if selected and product["id"] not in selected:
                continue
            if product["barcode"]:
                quote = store.quote(product["id"], date.today().isoformat())
                self.items.append({"product_id": product["id"], "name": product["name"], "barcode": product["barcode"], "price": quote["price"], "unit": "100g" if product.get("price_basis") == 100 else product["base_unit"], "origin": product["origin"]})
            for unit in store.units(product["id"]):
                if unit["barcode"] and unit.get("active", True):
                    self.items.append({"product_id": product["id"], "name": product["name"], "barcode": unit["barcode"], "price": unit["sale_price"], "unit": unit["name"], "origin": product["origin"]})
        self.grid.fill([[r["name"], r["unit"], r["barcode"], r["price"], r["origin"]] for r in self.items], self.items)
        self.grid.setSelectionMode(DataGrid.SelectionMode.ExtendedSelection)
        self.grid.setColumnWidth(0, 230)
        self.grid.setColumnWidth(2, 180)
        self.body.addWidget(self.grid, 1)
        self.preview = QLabel("목록에서 라벨을 선택하세요.")
        self.preview.setMinimumHeight(210)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.preview)
        self.grid.itemSelectionChanged.connect(self.update_preview)
        for field in (self.width, self.height, self.x, self.y):
            field.valueChanged.connect(self.update_preview)
        self.mode.currentIndexChanged.connect(self.update_preview)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("선택한 행만 출력합니다. 미등록 바코드 상품은 표시하지 않습니다."), 1)
        footer.addWidget(action("미리보기", self.preview_pages))
        footer.addWidget(action("PDF 저장", self.save_pdf))
        footer.addWidget(action("프린터 인쇄", self.print, primary=True))
        footer.addWidget(action("닫기", self.reject))
        self.body.addLayout(footer)
        if self.grid.rowCount():
            self.grid.selectRow(0)

    def size_spec(self):
        return LabelSize(self.width.value(), self.height.value(), self.x.value(), self.y.value())

    def selected_items(self):
        return [self.grid.item(index.row(), 0).data(Qt.ItemDataRole.UserRole) for index in self.grid.selectionModel().selectedRows()]

    def update_preview(self, *_):
        item = self.grid.selected()
        if not item:
            return
        try:
            image = label_image(item, self.size_spec(), self.mode.currentData())
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(600, 250, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except (ValueError, OSError) as exc:
            self.preview.setText(str(exc))

    def preview_pages(self):
        try:
            self.store._require("catalog")
        except PermissionError as exc:
            QMessageBox.warning(self, "라벨 출력 권한", str(exc))
            self.grid.fill([])
            return
        if not self.selected_items():
            QMessageBox.information(self, "라벨 선택", "인쇄할 라벨 행을 선택하세요.")
            return
        printer = label_printer(self.size_spec())
        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle("라벨 인쇄 미리보기")
        dialog.resize(900, 720)
        def paint(target):
            try:
                self.store._require("catalog")
                print_labels(target, self.selected_items(), self.size_spec(), self.copies.value(), self.mode.currentData())
            except (ValueError, OSError, PermissionError) as exc:
                QMessageBox.warning(self, "라벨 확인", str(exc))
        dialog.paintRequested.connect(paint)
        dialog.exec()

    def save_pdf(self):
        try:
            self.store._require("catalog")
        except PermissionError as exc:
            QMessageBox.warning(self, "라벨 출력 권한", str(exc))
            self.grid.fill([])
            return
        filename, _ = QFileDialog.getSaveFileName(self, "라벨 PDF 저장", "서영_상품라벨.pdf", "PDF (*.pdf)")
        if not filename:
            return
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        try:
            self.store._require("catalog")
            print_labels(label_printer(self.size_spec(), filename), self.selected_items(), self.size_spec(), self.copies.value(), self.mode.currentData())
        except (ValueError, OSError, PermissionError) as exc:
            QMessageBox.warning(self, "라벨 저장 실패", str(exc))

    def print(self):
        try:
            self.store._require("catalog")
            if not QPrinterInfo.availablePrinters():
                raise ValueError("설치된 프린터가 없습니다. Windows에서 제조사 드라이버를 설치한 뒤 다시 실행하세요.")
            printer = label_printer(self.size_spec())
            dialog = QPrintDialog(printer, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.store._require("catalog")
            print_labels(printer, self.selected_items(), self.size_spec(), self.copies.value(), self.mode.currentData())
        except (ValueError, OSError, PermissionError) as exc:
            QMessageBox.warning(self, "라벨 인쇄 실패", str(exc))
