"""Shared widgets for the independently designed offline desktop application."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from .font_support import font_family


def won(value):
    return f"{int(value or 0):,}"


def amount(value):
    value = Decimal(str(value or 0))
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def date_field(value=None):
    field = QDateEdit()
    field.setCalendarPopup(True)
    field.setDisplayFormat("yyyy-MM-dd")
    parsed = QDate.fromString(str(value), "yyyy-MM-dd") if value else QDate.currentDate()
    field.setDate(parsed if parsed.isValid() else QDate.currentDate())
    field.setMinimumWidth(124)
    return field


def action(text, callback, primary=False, danger=False):
    result = QPushButton(text)
    result.setObjectName("primary" if primary else "danger" if danger else "action")
    result.clicked.connect(callback)
    return result


READ_PERMISSIONS = {
    "ProductsPage": ("catalog",), "PartnersPage": ("catalog",),
    "ProductDialog": ("catalog",), "LabelsPage": ("catalog",),
    "LabelDialog": ("catalog",), "PartnerPicker": ("catalog", "trade"),
    "UsersPage": ("admin",), "SettingsPage": ("admin",),
    "MembersPage": ("loyalty",), "MemberDialog": ("loyalty",),
    "PromotionsPage": ("loyalty",), "PromotionDialog": ("loyalty",),
    "PricesPage": ("loyalty",), "GiftsPage": ("loyalty",),
    "TradesPage": ("trade",), "LedgerPage": ("trade",), "TradeDialog": ("trade",),
    "CountsPage": ("inventory",), "CountEditor": ("inventory",),
    "InventoryPage": ("inventory",), "ReportPage": ("reports",),
    "ReportsPage": ("reports",), "OverviewPage": ("reports",),
    "CommissionPage": ("reports",), "ClosingsPage": ("inventory", "trade"),
}


def _output_context(widget, parent=None):
    """Use the nearest explicit grid/view policy, with safe class fallbacks.

    Temporary print grids may be parentless, so their supplied dialog is also
    searched. A known Store without a view policy still requires a live login.
    Unbound grids remain useful for tests and non-business utility documents.
    """
    candidates, seen = [], set()
    for start in (widget, parent):
        current = start
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            candidates.append(current)
            current = current.parentWidget() if isinstance(current, QWidget) else None
    store = owner = None
    permissions = None
    for candidate in candidates:
        if store is None and getattr(candidate, "store", None) is not None:
            store, owner = candidate.store, candidate
        if permissions is None:
            explicit = getattr(candidate, "read_permissions", None)
            if explicit is not None:
                permissions = (explicit,) if isinstance(explicit, str) else tuple(explicit)
                owner = candidate
            else:
                for cls in type(candidate).__mro__:
                    if cls.__name__ in READ_PERMISSIONS:
                        permissions, owner = READ_PERMISSIONS[cls.__name__], candidate
                        break
    return store, permissions or (), owner


def _clear_output_cache(widget, owner):
    grids = []
    for candidate in (widget, owner):
        if isinstance(candidate, DataGrid):
            grids.append(candidate)
        if isinstance(candidate, QWidget):
            grids.extend(candidate.findChildren(DataGrid))
    seen = set()
    for grid in grids:
        if id(grid) in seen:
            continue
        seen.add(id(grid))
        blocked = grid.blockSignals(True)
        try:
            grid.fill([])
        finally:
            grid.blockSignals(blocked)


def authorize_output(widget, parent=None):
    """Re-read account state immediately before exporting or painting output."""
    store, permissions, owner = _output_context(widget, parent)
    if store is None:
        return True
    try:
        store._require(*permissions)
        return True
    except PermissionError as exc:
        _clear_output_cache(widget, owner)
        target = parent if isinstance(parent, QWidget) else widget if isinstance(widget, QWidget) else None
        QMessageBox.warning(target, "출력 권한 확인", f"{exc}\n조회 자료를 지웠습니다. 다시 로그인하거나 접근 권한을 확인하세요.")
        return False


def export_rows(parent, title, headers, rows, access_widget=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    context = access_widget if access_widget is not None else parent
    if not authorize_output(context, parent):
        return None
    if not rows:
        QMessageBox.information(parent, "엑셀 저장", "조회된 자료가 없습니다.")
        return None
    filename, _ = QFileDialog.getSaveFileName(parent, "조회 결과 저장", f"서영독립판_{title}_{date.today().isoformat()}.xlsx", "Excel 통합문서 (*.xlsx)")
    if not filename:
        return None
    # The native file chooser runs a nested event loop. Another administrator
    # may have disabled this account while it was open.
    if not authorize_output(context, parent):
        return None
    path = Path(filename)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    try:
        book = Workbook()
        sheet = book.active
        sheet.title = "조회 자료"
        sheet.append(list(headers))
        for values in rows:
            sheet.append([float(v) if isinstance(v, Decimal) else v for v in values])
        for row in sheet.iter_rows():
            for cell in row:
                # User-supplied text must never become a spreadsheet formula.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                elif isinstance(cell.value, (int, float)):
                    cell.number_format = "#,##0.###"
                cell.alignment = Alignment(vertical="center")
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="21485F")
            cell.font = Font(color="FFFFFF", bold=True)
        for column in range(1, len(headers) + 1):
            sheet.column_dimensions[get_column_letter(column)].width = min(44, max(14, len(str(headers[column - 1])) * 2 + 6))
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        if not authorize_output(context, parent):
            return None
        book.save(path)
        return path
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, "저장 실패", str(exc))
        return None


class Cell(QTableWidgetItem):
    def __init__(self, value):
        self.value = value
        text = won(value) if isinstance(value, int) and not isinstance(value, bool) else amount(value) if isinstance(value, Decimal) else str(value if value is not None else "")
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole + 1, value)
        if isinstance(value, (int, float, Decimal)):
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if value < 0:
                self.setForeground(QColor("#BA5247"))

    def __lt__(self, other):
        try:
            return self.value < other.value
        except (TypeError, AttributeError):
            return self.text() < other.text()


class DataGrid(QTableWidget):
    def __init__(self, headers):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.verticalHeader().setDefaultSectionSize(34)
        self.horizontalHeader().setMinimumSectionSize(55)
        self.horizontalHeader().setDefaultSectionSize(125)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSortingEnabled(True)
        self.setMinimumHeight(150)

    def fill(self, rows, records=None):
        self.setSortingEnabled(False)
        self.clearContents()
        self.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                item = Cell(value)
                if column == 0 and records is not None:
                    item.setData(Qt.ItemDataRole.UserRole, records[row_index])
                self.setItem(row_index, column, item)
        self.setSortingEnabled(True)

    def selected(self):
        row = self.currentRow()
        item = self.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def export_rows(self):
        return [[self.item(r, c).data(Qt.ItemDataRole.UserRole + 1) if self.item(r, c) else "" for c in range(self.columnCount())] for r in range(self.rowCount())]

    def export(self, parent=None, title="조회"):
        if not authorize_output(self, parent):
            return None
        return export_rows(parent or self, title, [self.horizontalHeaderItem(c).text() for c in range(self.columnCount())], self.export_rows(), access_widget=self)

    def document_html(self, title="조회", info=""):
        from html import escape
        headers = "".join(f"<th>{escape(self.horizontalHeaderItem(c).text())}</th>" for c in range(self.columnCount()))
        rows = []
        for values in self.export_rows():
            cells = []
            for value in values:
                content = won(value) if isinstance(value, int) else amount(value) if isinstance(value, Decimal) else str(value if value is not None else "")
                cells.append(f"<td>{escape(content)}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return f"<html><head><style>body{{font-size:9pt;color:#172e40}}h1{{font-size:18pt}}table{{border-collapse:collapse;width:100%}}th{{background:#e7edf2}}td,th{{border:1px solid #aebfca;padding:5px}}p{{color:#526879}}</style></head><body><h1>{escape(title)}</h1><p>서영 POS 독립판 · {date.today().isoformat()} · {self.rowCount():,}건<br>{escape(info).replace(chr(10), '<br>')}</p><table cellspacing='0' cellpadding='4'><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"

    def _paint_document(self, printer, title, info, parent=None):
        if not authorize_output(self, parent):
            return False
        document = QTextDocument()
        document.setDefaultFont(QFont(font_family(), 9))
        document.setHtml(self.document_html(title, info))
        if not authorize_output(self, parent):
            return False
        document.print_(printer)
        return True

    def to_pdf(self, filename, title="조회", info=""):
        if not authorize_output(self):
            return None
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(filename))
        if self.columnCount() > 7:
            printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        if self._paint_document(printer, title, info):
            return Path(filename)
        return None

    def print_pages(self, parent=None, title="조회", info=""):
        if not authorize_output(self, parent):
            return None
        if not self.rowCount():
            QMessageBox.information(parent or self, "인쇄", "인쇄할 조회 결과가 없습니다.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if self.columnCount() > 7:
            printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        preview = QPrintPreviewDialog(printer, parent or self)
        preview.setWindowTitle(f"{title} · 인쇄 미리보기")
        preview.resize(1100, 780)
        def paint(target):
            if not self._paint_document(target, title, info, parent):
                preview.reject()
        preview.paintRequested.connect(paint)
        preview.exec()


class Page(QWidget):
    def __init__(self, window, title, description=""):
        super().__init__()
        self.window, self.store, self.title = window, window.store, title
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 15)
        self.body.setSpacing(12)
        heading = QHBoxLayout()
        labels = QVBoxLayout()
        name = QLabel(title)
        name.setObjectName("pageTitle")
        labels.addWidget(name)
        hint = QLabel(description)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        labels.addWidget(hint)
        heading.addLayout(labels, 1)
        self.actions = QHBoxLayout()
        heading.addLayout(self.actions)
        self.body.addLayout(heading)
        self.grids = []

    def table(self, headers):
        result = DataGrid(headers)
        if not self.grids:
            self.actions.addWidget(action("엑셀 저장", self.export))
            self.actions.addWidget(action("인쇄", self.print))
        self.body.addWidget(result, 1)
        self.grids.append(result)
        return result

    def notify(self, text):
        if hasattr(self.window, "notify"):
            self.window.notify(text)
        else:
            QMessageBox.information(self, "서영 POS 독립판", text)

    def fail(self, error):
        QMessageBox.warning(self, "처리할 수 없습니다", str(error))

    def export(self):
        if authorize_output(self) and self.grids:
            self.grids[0].export(self, self.title)

    def refresh(self):
        pass

    def print(self):
        if authorize_output(self) and self.grids:
            self.grids[0].print_pages(self, self.title)


class ScanField(QLineEdit):
    """USB HID input: a scan terminator cannot activate a dialog's Save button."""
    scanned = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxLength(80)
        self.setPlaceholderText("바코드 스캔 후 Enter · F8")
        self.setClearButtonEnabled(True)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            value = self.text().strip("\r\n\t ")
            if value:
                self.scanned.emit(value)
            event.accept()
            return
        super().keyPressEvent(event)

    def event(self, event):
        # QWidget normally consumes Tab for focus traversal before keyPressEvent.
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab and self.text().strip():
            self.keyPressEvent(event)
            return True
        return super().event(event)


class FormDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} · 서영 POS 독립판")
        self.resize(570, 440)
        self.setMinimumWidth(460)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(22, 20, 22, 18)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        self.body.addWidget(heading)
        self.form = QFormLayout()
        self.form.setVerticalSpacing(11)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.body.addLayout(self.form)
        self.fields = {}

    def field(self, key, label, value="", password=False):
        result = QLineEdit(str(value if value is not None else ""))
        if password:
            result.setEchoMode(QLineEdit.EchoMode.Password)
        self.fields[key] = result
        self.form.addRow(label, result)
        return result

    def combo(self, key, label, choices, current=None):
        result = QComboBox()
        for text, value in choices:
            result.addItem(text, value)
        result.setCurrentIndex(max(0, result.findData(current)))
        self.fields[key] = result
        self.form.addRow(label, result)
        return result

    def finish(self, callback):
        self.body.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(callback)
        self.buttons.rejected.connect(self.reject)
        self.body.addWidget(self.buttons)
        return self.buttons

    def error(self, exc):
        QMessageBox.warning(self, "입력 확인", str(exc))
