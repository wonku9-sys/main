"""Korean desktop workspace. All business writes go through POSService."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, QDate, QTimer, QSize, QRectF
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .dialogs import DocumentDialog, LoginDialog, PartnerDialog, PartnerPicker, PasswordDialog, ProductDialog, UserDialog
from .export import export_workbook
from .service import POSService


TEAL = "#008C82"
NAV_ITEMS = [
    ("dashboard", "대시보드", "overview", "reports"),
    ("products", "상품장", "box", "products"),
    ("suppliers", "공급사 관리", "truck", "partners"),
    ("customers", "판매처 관리", "people", "partners"),
    ("purchases", "매입전표", "download", "purchases"),
    ("sales", "매출전표", "upload", "sales"),
    ("inventory", "재고 현황", "layers", "inventory"),
    ("reports", "거래 분석", "chart", "reports"),
    ("users", "사용자 관리", "people", "users"),
    ("settings", "설정 · 백업", "settings", "settings"),
]

STYLE = """
* { outline: none; }
QWidget { color: #25354B; font-size: 13px; }
QMainWindow, #workspace, #page, #pageScroller { background: #F3F6FA; }
#pageScroller { border: none; }
QLabel { background: transparent; }
#sidebar { background: #122238; border: none; }
#brandMark { background: #00A99A; color: white; font-size: 26px; font-weight: 800; border-radius: 12px; }
#brandName { color: #FFFFFF; font-size: 21px; font-weight: 700; }
#brandCaption { color: #8C9DB5; font-size: 11px; }
#sideSection { color: #71859F; font-size: 10px; font-weight: 700; padding: 14px 12px 8px; }
#navButton { background: transparent; color: #AABAD0; text-align: left; border: none; border-radius: 8px; padding: 11px 14px; font-size: 13px; }
#navButton:hover { background: #1C324C; color: white; }
#navButton:checked { background: #174344; color: #6DE0D0; font-weight: 700; border-left: 3px solid #32C9B8; }
#sidebarFoot { color: #7E94AF; font-size: 11px; }
#sidebarBadge { color: #64D7C4; background: #193F43; border-radius: 6px; padding: 7px 10px; font-size: 11px; }
#topbar { background: white; border-bottom: 1px solid #E3E9F1; }
#topbarTitle { color: #14283F; font-weight: 700; font-size: 14px; }
#localBadge { color: #007C71; background: #E7F6F1; padding: 6px 10px; border-radius: 12px; font-size: 11px; }
#avatar { background: #EAF0F8; color: #345377; border-radius: 16px; font-size: 13px; font-weight: 700; }
#userName { color: #233950; font-weight: 600; }
#userRole { color: #8390A2; font-size: 11px; }
#pageTitle { color: #152B42; font-size: 27px; font-weight: 750; }
#eyebrow { color: #8694A8; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
#pageSubtitle, #mutedLabel, #dialogSubtitle { color: #8190A4; font-size: 12px; }
#card, #filterCard, #tableCard, #chartCard { background: white; border: 1px solid #E2E8F0; border-radius: 12px; }
#cardLabel { color: #7E8DA2; font-size: 12px; }
#metricValue { color: #172F47; font-size: 28px; font-weight: 750; }
#metricPositive { color: #008C82; font-size: 28px; font-weight: 750; }
#metricDanger { color: #D56850; font-size: 28px; font-weight: 750; }
#metricHint { color: #8A98AB; font-size: 11px; }
#sectionTitle { font-size: 15px; font-weight: 700; color: #243B53; }
#resultCount { color: #008C82; background: #EAF7F3; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }
#tableFooter { background: #F8FAFC; border-top: 1px solid #E6ECF2; border-radius: 0px; }
#footerTotal { color: #1E3B54; font-size: 15px; font-weight: 700; }
#emptyLabel { color: #8B99AA; padding: 24px; background: #FBFCFE; }
#demoBanner { background: #FFF2D5; color: #94621D; border: 1px solid #F5D999; border-radius: 6px; padding: 8px 12px; }
#hintCard { background: #E9F5F3; border: 1px solid #D3E9E3; border-radius: 10px; }
#statusbar { color: #93A0B1; font-size: 10px; background: #F3F6FA; }
QPushButton { background: white; color: #43546A; border: 1px solid #DCE4EE; border-radius: 7px; padding: 8px 13px; min-height: 20px; font-weight: 500; }
QPushButton:hover { background: #F1F6FA; border-color: #BCCBD9; }
QPushButton:pressed { background: #E5EDF5; }
QPushButton:disabled { color: #A7B1C0; background: #F1F4F7; border-color: #E7EBF0; }
#primaryButton { background: #008C82; color: white; border-color: #008C82; font-weight: 700; }
#primaryButton:hover { background: #00796F; border-color: #00796F; }
#dangerButton { background: #FFF4F2; color: #BC4B3B; border-color: #F1D3CD; }
#linkButton { color: #008C82; border: none; background: transparent; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit { background: #FFFFFF; border: 1px solid #DCE4EE; border-radius: 6px; padding: 7px 9px; min-height: 20px; selection-background-color: #CCEBE5; selection-color: #173A36; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus { border: 1px solid #14A597; }
QLineEdit:read-only { background: #F4F7FA; color: #7E8BA0; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #DFF2ED; selection-color: #165E55; padding: 5px; }
QTableWidget { border: none; background: white; alternate-background-color: #FAFCFE; gridline-color: #EDF1F5; selection-background-color: #E7F5F1; selection-color: #1A665D; border-radius: 0px; }
QTableWidget::item { padding: 8px 12px; border-bottom: 1px solid #EEF2F6; }
QTableWidget::item:selected { background: #E4F4EF; color: #185E55; }
QHeaderView::section { background: #F7F9FC; color: #7D8CA0; font-weight: 600; padding: 12px 10px; border: none; border-bottom: 1px solid #E3EAF2; }
QTableCornerButton::section { background: #F7F9FC; border: none; }
QScrollBar:vertical { background: #F5F7FA; width: 9px; border: none; }
QScrollBar::handle:vertical { background: #C5CFDC; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar:horizontal { background: #F5F7FA; height: 9px; }
QScrollBar::handle:horizontal { background: #C5CFDC; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QDialog { background: #F7F9FC; }
#dialogHeader { background: white; border-bottom: 1px solid #E5EBF2; }
#dialogTitle { font-size: 23px; font-weight: 700; color: #173148; }
#totalValue { font-size: 24px; font-weight: 750; color: #008C82; }
QTabWidget::pane { border: 1px solid #E1E8F0; background: white; border-radius: 8px; }
QTabBar::tab { background: transparent; color: #8090A5; padding: 12px 17px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #008C82; border-bottom: 2px solid #008C82; font-weight: 700; }
QGroupBox { background: white; border: 1px solid #E0E7EF; border-radius: 8px; margin-top: 14px; padding-top: 15px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0px 5px; color: #41556B; font-weight: 600; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QToolTip { background: #14263E; color: white; border: none; padding: 7px; }
"""


def icon(name, color="#9DB0C8"):
    paths = {
        "overview": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        "box": '<path d="m12 3 9 5v9l-9 5-9-5V8Z M3 8l9 5 9-5 M12 13v9 M7 5.8l9 5"/>',
        "truck": '<path d="M3 6h11v12H3z M14 10h4l3 4v4h-7 M3 18h2m4 0h6m4 0h2"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
        "people": '<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3 M16 4a3 3 0 0 1 0 6 M18 14a6 6 0 0 1 3 5v2"/>',
        "download": '<path d="M12 3v12m-5-5 5 5 5-5 M4 16v5h16v-5"/>',
        "upload": '<path d="M12 16V4m-5 5 5-5 5 5 M4 16v5h16v-5"/>',
        "layers": '<path d="m12 3 10 5-10 5L2 8z M2 13l10 5 10-5 M2 18l10 5 10-5"/>',
        "chart": '<path d="M3 3v18h18 M7 17v-6m5 6V6m5 11V9"/>',
        "settings": '<circle cx="12" cy="12" r="4"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/>',
        "plus": '<path d="M12 5v14M5 12h14"/>',
        "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
        "refresh": '<path d="M20 10a8 8 0 0 0-14-5L3 8m0-6v6h6 M4 14a8 8 0 0 0 14 5l3-3m0 6v-6h-6"/>',
    }
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths.get(name, paths["box"])}</svg>'
    pix = QPixmap(24, 24)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    return QIcon(pix)


def label(text, name=None):
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    return result


def button(text, callback, primary=False, danger=False, glyph=None):
    result = QPushButton(text)
    if primary:
        result.setObjectName("primaryButton")
    elif danger:
        result.setObjectName("dangerButton")
    if glyph:
        result.setIcon(icon(glyph, "#FFFFFF" if primary else TEAL))
        result.setIconSize(QSize(17, 17))
    result.clicked.connect(callback)
    return result


def money(value):
    return f"{int(value or 0):,}"


def quantity(value):
    return f"{Decimal(str(value or 0)):,.3f}".rstrip("0").rstrip(".")


class SortItem(QTableWidgetItem):
    def __init__(self, value, numeric=False, emphasis=None):
        text = money(value) if isinstance(value, int) and not isinstance(value, bool) else (quantity(value) if isinstance(value, Decimal) else str(value if value is not None else "—"))
        super().__init__(text)
        self.sort_value = value
        self.setData(Qt.ItemDataRole.UserRole + 2, value)
        if numeric or isinstance(value, (int, float, Decimal)):
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if emphasis:
            self.setForeground(QColor(emphasis))
            font = self.font()
            font.setBold(True)
            self.setFont(font)

    def __lt__(self, other):
        try:
            return self.sort_value < other.sort_value
        except TypeError:
            return self.text() < other.text()


class DataTable(QTableWidget):
    def __init__(self, headers):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(44)
        self.horizontalHeader().setDefaultSectionSize(128)
        self.horizontalHeader().setMinimumSectionSize(70)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSortingEnabled(True)
        self.setMinimumHeight(150)

    def populate(self, rows, records=None, numeric=(), emphasized=None):
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = SortItem(value, c in numeric, (emphasized or {}).get(c))
                self.setItem(r, c, item)
            if records and row:
                self.item(r, 0).setData(Qt.ItemDataRole.UserRole, records[r])
        self.setSortingEnabled(True)

    def selected(self):
        if self.currentRow() < 0:
            return None
        item = self.item(self.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def export_rows(self):
        return [[self.item(r, c).data(Qt.ItemDataRole.UserRole + 2) if self.item(r, c) else "" for c in range(self.columnCount())] for r in range(self.rowCount())]


class Page(QWidget):
    def __init__(self, window, title, subtitle, code):
        super().__init__()
        self.setObjectName("page")
        self.window = window
        self.service = window.service
        self.title = title
        self.code = code
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(28, 25, 28, 16)
        self.body.setSpacing(18)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(label(f"SEOYOUNG POS   /   {code.upper()}", "eyebrow"))
        titles.addWidget(label(title, "pageTitle"))
        titles.addWidget(label(subtitle, "pageSubtitle"))
        heading.addLayout(titles)
        heading.addStretch()
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        heading.addLayout(self.actions)
        self.body.addLayout(heading)
        self.search = None
        self.table = None

    def add_export(self):
        self.actions.addWidget(button("엑셀 내보내기", self.export, glyph="download"))

    def filter_frame(self):
        frame = QFrame()
        frame.setObjectName("filterCard")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(10)
        self.body.addWidget(frame)
        return layout

    def search_field(self, placeholder):
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(180)
        self.search.returnPressed.connect(self.refresh)
        return self.search

    def table_frame(self, headers, title):
        frame = QFrame()
        frame.setObjectName("tableCard")
        layout = QVBoxLayout(frame)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        topline = QHBoxLayout()
        topline.setContentsMargins(18, 14, 18, 14)
        topline.addWidget(label(title, "sectionTitle"))
        self.count_label = label("0건", "resultCount")
        topline.addWidget(self.count_label)
        topline.addStretch()
        topline.addWidget(label("열 머리글을 눌러 정렬 · 열 너비 조절 가능", "mutedLabel"))
        layout.addLayout(topline)
        self.table = DataTable(headers)
        layout.addWidget(self.table, 1)
        self.empty = label("조회된 자료가 없습니다. 검색 조건을 확인하거나 새 자료를 등록하세요.", "emptyLabel")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        foot = QFrame()
        foot.setObjectName("tableFooter")
        self.foot_layout = QHBoxLayout(foot)
        self.foot_layout.setContentsMargins(18, 13, 18, 13)
        self.foot_layout.addWidget(label("조회 결과 합계", "mutedLabel"))
        self.foot_layout.addStretch()
        self.total_label = label("0건", "footerTotal")
        self.foot_layout.addWidget(self.total_label)
        layout.addWidget(foot)
        self.body.addWidget(frame, 1)
        return self.table

    def results(self, count, total=None):
        self.count_label.setText(f"{count:,}건")
        self.empty.setVisible(count == 0)
        self.total_label.setText(total if total is not None else f"{count:,}건")

    def selected(self):
        result = self.table.selected() if self.table else None
        if result is None:
            QMessageBox.information(self, "자료 선택", "표에서 처리할 자료를 먼저 선택하세요.")
        return result

    def perform(self, operation):
        try:
            operation()
            self.refresh()
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "처리할 수 없습니다", str(exc))

    def export(self):
        if not self.table or self.table.rowCount() == 0:
            QMessageBox.information(self, "엑셀 내보내기", "내보낼 조회 결과가 없습니다.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "조회 결과를 엑셀로 저장", f"서영POS_{self.title}_{date.today().isoformat()}.xlsx", "Excel 통합문서 (*.xlsx)")
        if filename:
            if not filename.lower().endswith(".xlsx"):
                filename += ".xlsx"
            try:
                export_workbook(filename, self.title, [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())], self.table.export_rows())
                self.window.show_message(f"엑셀 저장 완료 · {filename}")
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "저장 실패", str(exc))

    def refresh(self):
        pass


class PartnersPage(Page):
    def __init__(self, window, kind):
        self.kind = kind
        noun = "공급사" if kind == "supplier" else "판매처"
        super().__init__(window, f"{noun} 관리", f"거래처 정보와 미결제 잔액을 한곳에서 관리합니다.", "partners")
        self.add_export()
        self.actions.addWidget(button(f"{noun} 등록", self.add, primary=True, glyph="plus"))
        filters = self.filter_frame()
        filters.addWidget(self.search_field(f"{noun}명, 코드, 전화번호 검색"), 1)
        filters.addWidget(button("조회", self.refresh, primary=True, glyph="search"))
        filters.addWidget(button("정보 수정", self.edit))
        filters.addWidget(button("삭제", self.delete, danger=True))
        doc_kind = "purchase" if kind == "supplier" else "sale"
        if self.service.has_permission("purchases" if kind == "supplier" else "sales"):
            filters.addWidget(button("매입등록" if kind == "supplier" else "매출등록", lambda: self.window.new_document(doc_kind), glyph="plus"))
        self.table_frame(["코드", noun + "명", "사업자등록번호", "담당자", "전화번호", "미결제 잔액", "은행 · 계좌", "메모"], f"{noun} 목록")
        self.table.setColumnWidth(1, 230)
        self.table.setColumnWidth(6, 210)
        self.table.cellDoubleClicked.connect(self.edit)

    def refresh(self):
        records = self.service.list_partners(self.kind, self.search.text().strip())
        rows = [[r["code"], r["name"], r.get("business_no", ""), r.get("contact", ""), r.get("phone", ""), r.get("balance", 0), f'{r.get("bank", "")} {r.get("account", "")}'.strip(), r.get("memo", "")] for r in records]
        self.table.populate(rows, records, emphasized={5: "#C2684F"})
        self.results(len(records), f"미결제 잔액   {money(sum(r.get('balance', 0) for r in records))} 원")

    def add(self):
        if PartnerDialog(self.service, self.kind, parent=self).exec():
            self.refresh()

    def edit(self, *_):
        row = self.selected()
        if row and PartnerDialog(self.service, self.kind, row, parent=self).exec():
            self.refresh()

    def delete(self):
        row = self.selected()
        if row and QMessageBox.question(self, "거래처 삭제", f"‘{row['name']}’을(를) 삭제하시겠습니까?\n거래 이력이 있는 거래처는 삭제할 수 없습니다.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.service.delete_partner(row["id"]))


class ProductsPage(Page):
    def __init__(self, window):
        super().__init__(window, "상품장", "상품의 매입가, 판매가, 재고와 거래 이력을 정확하게 관리합니다.", "products")
        self.add_export()
        self.actions.addWidget(button("새 상품 등록", self.add, primary=True, glyph="plus"))
        filters = self.filter_frame()
        filters.addWidget(self.search_field("상품명, 상품코드, 바코드 검색"), 2)
        self.supplier = QComboBox()
        self.supplier.setMinimumWidth(170)
        filters.addWidget(self.supplier, 1)
        self.category = QComboBox()
        self.category.addItems(["전체 분류", "돈육", "한우", "수입육", "계육", "기타"])
        filters.addWidget(self.category)
        self.low = QCheckBox("최소재고 이하")
        filters.addWidget(self.low)
        filters.addWidget(button("조회", self.refresh, primary=True, glyph="search"))
        self.table_frame(["상품코드", "상품명", "분류", "규격 · 원산지", "바코드", "공급사", "매입단가", "판매단가", "현재고", "단위", "상태"], "전체 상품")
        self.table.horizontalHeader().setMinimumSectionSize(55)
        for column, width in enumerate((85, 170, 65, 140, 100, 160, 95, 95, 85, 60, 80)):
            self.table.setColumnWidth(column, width)
        self.table.cellDoubleClicked.connect(self.edit)
        self.foot_layout.insertWidget(1, button("선택 상품 수정 · 이력", self.edit))
        self.foot_layout.insertWidget(2, button("선택 상품 삭제", self.delete, danger=True))

    def refresh(self):
        selected = self.supplier.currentData()
        self.supplier.blockSignals(True)
        self.supplier.clear()
        self.supplier.addItem("전체 공급사", None)
        for partner in self.service.list_partners("supplier"):
            self.supplier.addItem(partner["name"], partner["id"])
        idx = self.supplier.findData(selected)
        self.supplier.setCurrentIndex(max(0, idx))
        self.supplier.blockSignals(False)
        records = self.service.list_products(self.search.text().strip(), self.supplier.currentData(), "" if self.category.currentIndex() == 0 else self.category.currentText(), self.low.isChecked())
        rows = [[r["code"], r["name"], r.get("category", ""), f'{r.get("specification", "")} · {r.get("origin", "")}', r.get("barcode", ""), r.get("supplier_name", "") or "미지정", r["purchase_price"], r["sale_price"], Decimal(str(r["stock_qty"])), r["unit"], "판매중" if r.get("active", True) else "판매중지"] for r in records]
        self.table.populate(rows, records, numeric=(8,), emphasized={1: "#255B79", 8: TEAL})
        self.results(len(records), f"{len(records):,}개 상품   ·   재고금액 {money(sum(r['stock_cost'] for r in records))} 원 (이동평균 원가)")

    def add(self):
        if ProductDialog(self.service, parent=self).exec():
            self.refresh()

    def edit(self, *_):
        row = self.selected()
        if row and ProductDialog(self.service, row, parent=self).exec():
            self.refresh()

    def delete(self):
        row = self.selected()
        if row and QMessageBox.question(self, "상품 삭제", f"‘{row['name']}’ 상품을 삭제하시겠습니까?\n거래·재고 이력이 있는 상품은 판매중지로 전환하세요.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.service.delete_product(row["id"]))


class DocumentsPage(Page):
    def __init__(self, window, kind):
        self.kind = kind
        noun = "매입" if kind == "purchase" else "매출"
        super().__init__(window, f"{noun}전표", f"{noun} 내역과 결제 현황을 확인하고 미결제 금액을 정산합니다.", kind)
        self.add_export()
        self.actions.addWidget(button(f"{noun}등록", lambda: window.new_document(kind), primary=True, glyph="plus"))
        filters = self.filter_frame()
        self.start = QDateEdit(QDate.currentDate().addDays(1 - QDate.currentDate().day()))
        self.end = QDateEdit(QDate.currentDate())
        for field in (self.start, self.end):
            field.setCalendarPopup(True)
            field.setDisplayFormat("yyyy-MM-dd")
            field.setFixedWidth(135)
        filters.addWidget(self.start)
        filters.addWidget(label("—", "mutedLabel"))
        filters.addWidget(self.end)
        self.partner = QComboBox()
        self.partner.setMinimumWidth(150)
        filters.addWidget(self.partner, 1)
        self.status = QComboBox()
        self.status.addItems(["전체 상태", "미결제", "결제완료", "취소"])
        filters.addWidget(self.status)
        filters.addWidget(self.search_field("전표번호 · 메모"), 1)
        filters.addWidget(button("조회", self.refresh, primary=True, glyph="search"))
        self.table_frame(["전표번호", "거래일자", "공급사" if kind == "purchase" else "판매처", "품목수", f"{noun} 합계", "결제금액", "미결제 잔액", "상태", "담당자", "메모"], f"{noun} 내역")
        self.table.horizontalHeader().setMinimumSectionSize(60)
        for column, width in enumerate((165, 110, 190, 65, 110, 110, 120, 85, 100, 150)):
            self.table.setColumnWidth(column, width)
        self.table.cellDoubleClicked.connect(self.detail)
        self.foot_layout.insertWidget(1, button("전표 상세 · 정산", self.detail))

    def refresh(self):
        if self.start.date() > self.end.date():
            QMessageBox.warning(self, "기간 확인", "시작일은 종료일보다 늦을 수 없습니다.")
            return
        selected = self.partner.currentData()
        self.partner.clear()
        self.partner.addItem("전체 공급사" if self.kind == "purchase" else "전체 판매처", None)
        for p in self.service.list_partners("supplier" if self.kind == "purchase" else "customer"):
            self.partner.addItem(p["name"], p["id"])
        self.partner.setCurrentIndex(max(0, self.partner.findData(selected)))
        records = self.service.list_documents(self.kind, self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd"), self.partner.currentData(), self.search.text().strip())
        if self.status.currentIndex() == 1:
            records = [r for r in records if r["status"] != "cancelled" and r["balance"] > 0]
        elif self.status.currentIndex() == 2:
            records = [r for r in records if r["status"] != "cancelled" and r["balance"] == 0]
        elif self.status.currentIndex() == 3:
            records = [r for r in records if r["status"] == "cancelled"]
        rows = [[r["number"], r["date"], r["partner_name"], r.get("items_count", 0), r["total"], r["paid"], r["balance"], "취소" if r["status"] == "cancelled" else ("미결제" if r["balance"] else "결제완료"), r.get("user_name", ""), r["memo"]] for r in records]
        self.table.populate(rows, records, emphasized={4: "#1B3D55", 6: "#C2684F"})
        active = [r for r in records if r["status"] != "cancelled"]
        self.results(len(records), f"합계 {money(sum(r['total'] for r in active))} 원     결제 {money(sum(r['paid'] for r in active))} 원     미결제 {money(sum(r['balance'] for r in active))} 원")

    def detail(self, *_):
        row = self.selected()
        if row:
            DocumentDialog(self.service, self.kind, document_id=row["id"], parent=self).exec()
            self.refresh()


class InventoryPage(Page):
    def __init__(self, window):
        super().__init__(window, "재고 현황", "입출고에 따른 재고 변동을 확인하고 실사 수량을 반영합니다.", "inventory")
        self.add_export()
        self.actions.addWidget(button("재고 조정", self.adjust, primary=True, glyph="layers"))
        filters = self.filter_frame()
        filters.addWidget(self.search_field("상품명, 코드, 바코드 검색"), 1)
        self.low = QCheckBox("최소재고 이하만 보기")
        filters.addWidget(self.low)
        filters.addWidget(button("조회", self.refresh, primary=True, glyph="search"))
        filters.addWidget(button("입출고 이력", self.history))
        self.table_frame(["상품코드", "상품명", "분류", "현재고", "단위", "최소재고", "재고상태", "등록 매입가", "재고금액 (이동평균)"], "상품별 재고")
        self.table.horizontalHeader().setMinimumSectionSize(55)
        for column, width in enumerate((100, 240, 90, 120, 60, 110, 110, 120, 170)):
            self.table.setColumnWidth(column, width)
        self.table.cellDoubleClicked.connect(self.history)

    def refresh(self):
        records = self.service.list_stock(self.search.text().strip())
        if self.low.isChecked():
            records = [r for r in records if Decimal(str(r["stock_qty"])) <= Decimal(str(r["min_stock"]))]
        rows = []
        for r in records:
            qty = Decimal(str(r["stock_qty"]))
            minimum = Decimal(str(r["min_stock"]))
            rows.append([r["code"], r["name"], r.get("category", ""), qty, r["unit"], Decimal(str(r["min_stock"])), "재고 부족" if qty <= minimum else "정상", r["purchase_price"], r["stock_cost"]])
        self.table.populate(rows, records, numeric=(3, 5), emphasized={3: TEAL})
        self.results(len(records), f"{len(records):,}개 상품   ·   재고금액 {money(sum(r[8] for r in rows))} 원 (이동평균 원가)")

    def adjust(self):
        row = self.selected()
        if not row:
            return
        delta, accepted = QInputDialog.getText(self, "재고 조정", f"{row['name']} · 현재 {quantity(row['stock_qty'])} {row['unit']}\n증감할 수량을 입력하세요. 예: 2.500 또는 -1.250")
        if not accepted:
            return
        reason, accepted = QInputDialog.getText(self, "조정 사유", "실사 차이, 폐기 등 구체적인 사유를 입력하세요.")
        if accepted:
            self.perform(lambda: self.service.adjust_stock(row["id"], delta, reason))

    def history(self, *_):
        row = self.selected()
        if not row:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{row['name']} · 입출고 이력")
        dialog.resize(960, 570)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.addWidget(label(f"{row['name']} · 입출고 이력", "dialogTitle"))
        table = DataTable(["일시", "유형", "증감 수량", "변동 후 재고", "전표번호", "사유"])
        movements = self.service.list_stock_movements(row["id"])
        names = {"purchase": "매입", "sale": "매출", "adjustment": "재고조정", "cancel_purchase": "매입취소", "cancel_sale": "매출취소"}
        table.populate([[m.get("date", m.get("at", "")), names.get(m["kind"], m["kind"]), Decimal(str(m["qty"])), Decimal(str(m.get("balance_qty", "0"))), m.get("document_number", "") or "—", m.get("reason", "")] for m in movements])
        table.setColumnWidth(0, 180)
        layout.addWidget(table)
        layout.addWidget(button("닫기", dialog.accept))
        dialog.exec()


class MetricCard(QFrame):
    def __init__(self, title, hint, tone="normal"):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 17)
        layout.setSpacing(9)
        layout.addWidget(label(title, "cardLabel"))
        self.value = label("0", {"normal": "metricValue", "positive": "metricPositive", "danger": "metricDanger"}[tone])
        layout.addWidget(self.value)
        self.hint = label(hint, "metricHint")
        layout.addWidget(self.hint)

    def set_value(self, value, suffix="원"):
        self.value.setText(f"{money(value)} {suffix}")


class TradeChart(QWidget):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.setMinimumHeight(175)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, rows):
        self.rows = rows[-10:]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        left, right, top, bottom = 64, 18, 18, 30
        plot_width, plot_height = max(1, width-left-right), max(1, height-top-bottom)
        peak = max([max(r.get("sale_total", 0), r.get("purchase_total", 0)) for r in self.rows] or [0])
        scale = max(peak, 10000)
        painter.setFont(QFont(QApplication.font().family(), 9))
        for i in range(4):
            y = top + plot_height * i / 3
            painter.setPen(QPen(QColor("#EDF1F6"), 1))
            painter.drawLine(int(left), int(y), int(width-right), int(y))
            painter.setPen(QColor("#97A4B6"))
            painter.drawText(QRectF(0, y-8, left-10, 18), Qt.AlignmentFlag.AlignRight, f"{scale*(1-i/3)/10000:,.0f}만")
        if not self.rows:
            painter.setPen(QColor("#91A0B2"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "조회 기간에 거래 내역이 없습니다.")
            return
        step = plot_width / len(self.rows)
        bar_width = min(25, step * .26)
        painter.setPen(Qt.PenStyle.NoPen)
        for i, row in enumerate(self.rows):
            x = left + step*(i+.5)
            for offset, key, color in [(-bar_width-2, "purchase_total", "#D7E7F3"), (2, "sale_total", "#16A396")]:
                bar_height = plot_height * row.get(key, 0) / scale
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(QRectF(x+offset, top+plot_height-bar_height, bar_width, max(0, bar_height)), 3, 3)
            painter.setPen(QColor("#8B9AAE"))
            painter.drawText(QRectF(x-step/2, height-25, step, 20), Qt.AlignmentFlag.AlignCenter, row.get("date", "")[5:].replace("-", "/"))
            painter.setPen(Qt.PenStyle.NoPen)


class DashboardPage(Page):
    def __init__(self, window):
        super().__init__(window, "매장의 오늘을 한눈에", "입고부터 판매, 미결제 잔액까지. 필요한 숫자를 빠르게 확인하세요.", "overview")
        self.actions.addWidget(button("새로고침", self.refresh, glyph="refresh"))
        if self.service.has_permission("purchases"):
            self.actions.addWidget(button("매입등록", lambda: window.new_document("purchase"), glyph="plus"))
        if self.service.has_permission("sales"):
            self.actions.addWidget(button("매출등록", lambda: window.new_document("sale"), primary=True, glyph="plus"))
        card_row = QHBoxLayout()
        card_row.setSpacing(16)
        self.metrics = {}
        for key, title, hint, tone in [
            ("sale_total", "이번 달 매출", "취소 전표를 제외한 매출 합계", "positive"),
            ("purchase_total", "이번 달 매입", "취소 전표를 제외한 매입 합계", "normal"),
            ("receivable", "받을 금액", "전체 기간 · 판매처 미수금", "danger"),
            ("payable", "지급할 금액", "전체 기간 · 공급사 미지급금", "normal"),
        ]:
            card = MetricCard(title, hint, tone)
            self.metrics[key] = card
            card_row.addWidget(card, 1)
        self.body.addLayout(card_row)
        middle = QHBoxLayout()
        middle.setSpacing(16)
        chart_card = QFrame()
        chart_card.setObjectName("chartCard")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(20, 18, 20, 12)
        chart_heading = QHBoxLayout()
        chart_heading.addWidget(label("매입 · 매출 흐름", "sectionTitle"))
        chart_heading.addStretch()
        chart_heading.addWidget(label("● 매입", "mutedLabel"))
        legend = label("● 매출")
        legend.setStyleSheet("color: #008C82; font-size: 11px;")
        chart_heading.addWidget(legend)
        chart_layout.addLayout(chart_heading)
        self.chart = TradeChart()
        chart_layout.addWidget(self.chart, 1)
        middle.addWidget(chart_card, 3)
        stock_card = QFrame()
        stock_card.setObjectName("chartCard")
        stock_layout = QVBoxLayout(stock_card)
        stock_layout.setContentsMargins(20, 18, 20, 18)
        stock_layout.setSpacing(13)
        stock_layout.addWidget(label("재고 체크", "sectionTitle"))
        self.stock_info = label("", "metricValue")
        self.stock_info.setStyleSheet("font-size: 23px;")
        stock_layout.addWidget(self.stock_info)
        self.low_info = label("", "mutedLabel")
        stock_layout.addWidget(self.low_info)
        self.stock_value = label("", "mutedLabel")
        self.stock_value.setWordWrap(True)
        stock_layout.addWidget(self.stock_value)
        stock_layout.addStretch()
        if self.service.has_permission("inventory"):
            stock_layout.addWidget(button("재고 현황 확인 →", lambda: window.navigate("inventory")))
        middle.addWidget(stock_card, 1)
        self.body.addLayout(middle, 1)
        self.table_frame(["구분", "전표번호", "거래일자", "거래처", "거래금액", "미결제 잔액", "상태"], "최근 거래 내역")
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(3, 240)
        self.table.cellDoubleClicked.connect(self.detail)

    def refresh(self):
        today = date.today()
        summary = self.service.dashboard(today.replace(day=1).isoformat(), today.isoformat())
        for key, card in self.metrics.items():
            card.set_value(summary.get(key, 0))
        self.stock_info.setText(f"{summary.get('product_count', 0):,}개 상품")
        self.low_info.setText(f"최소재고 이하  {summary.get('low_stock_count', 0):,}개")
        self.stock_value.setText(f"재고자산 {money(summary.get('stock_value', 0))} 원\n이동평균 원가 기준")
        report = self.service.report(today.replace(day=1).isoformat(), today.isoformat())
        self.chart.set_data(report.get("daily", []))
        records = sorted(self.service.list_documents("purchase") + self.service.list_documents("sale"), key=lambda r: (r["date"], r["id"]), reverse=True)[:8]
        rows = [["매입" if r["kind"] == "purchase" else "매출", r["number"], r["date"], r["partner_name"], r["total"], r["balance"], "취소" if r["status"] == "cancelled" else ("미결제" if r["balance"] else "결제완료")] for r in records]
        self.table.populate(rows, records, emphasized={5: "#C2684F"})
        self.results(len(records), f"이번 달 기준   {today.replace(day=1).isoformat()} — {today.isoformat()}")

    def detail(self, *_):
        row = self.selected()
        if row:
            DocumentDialog(self.service, row["kind"], document_id=row["id"], parent=self).exec()
            self.refresh()


class ReportsPage(Page):
    def __init__(self, window):
        super().__init__(window, "거래 분석", "기간별 매입과 매출, 원가와 결제 흐름을 확인합니다.", "reports")
        self.add_export()
        filters = self.filter_frame()
        filters.addWidget(label("조회 기간", "mutedLabel"))
        self.start = QDateEdit(QDate.currentDate().addDays(1-QDate.currentDate().day()))
        self.end = QDateEdit(QDate.currentDate())
        for field in (self.start, self.end):
            field.setCalendarPopup(True)
            field.setDisplayFormat("yyyy-MM-dd")
            field.setFixedWidth(150)
        filters.addWidget(self.start)
        filters.addWidget(label("—", "mutedLabel"))
        filters.addWidget(self.end)
        filters.addStretch()
        filters.addWidget(button("조회", self.refresh, primary=True, glyph="search"))
        cards = QHBoxLayout()
        self.metrics = {}
        for key, title, hint, tone in [("purchase_total", "기간 매입", "거래일 기준", "normal"), ("sale_total", "기간 매출", "거래일 기준", "positive"), ("profit", "매출이익", "이동평균 매출원가 차감 · 조정 제외", "positive")]:
            self.metrics[key] = MetricCard(title, hint, tone)
            cards.addWidget(self.metrics[key])
        self.body.addLayout(cards)
        self.table_frame(["거래일자", "매입 합계", "매출 합계", "매입 결제액", "매출 수금액"], "일자별 거래 요약")
        self.table.setColumnWidth(0, 190)

    def refresh(self):
        if self.start.date() > self.end.date():
            QMessageBox.warning(self, "기간 확인", "시작일은 종료일보다 늦을 수 없습니다.")
            return
        report = self.service.report(self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd"))
        summary = report["summary"]
        for key, metric in self.metrics.items():
            metric.set_value(summary.get(key, 0))
        records = report["daily"]
        self.table.populate([[r["date"], r.get("purchase_total", 0), r.get("sale_total", 0), r.get("paid_purchase", 0), r.get("paid_sale", 0)] for r in records], emphasized={2: TEAL})
        self.results(len(records), f"매입 {money(summary.get('purchase_total', 0))} 원   ·   매출 {money(summary.get('sale_total', 0))} 원")


class UsersPage(Page):
    def __init__(self, window):
        super().__init__(window, "사용자 관리", "계정과 업무별 접근 권한을 설정합니다. 관리자만 변경할 수 있습니다.", "users")
        self.actions.addWidget(button("사용자 등록", self.add, primary=True, glyph="plus"))
        filters = self.filter_frame()
        filters.addWidget(label("현재 로그인 계정과 마지막 관리자 계정은 삭제할 수 없습니다.", "mutedLabel"))
        filters.addStretch()
        filters.addWidget(button("정보 · 권한 수정", self.edit))
        filters.addWidget(button("사용자 삭제", self.delete, danger=True))
        self.table_frame(["아이디", "사용자 이름", "역할", "접근 권한"], "등록 사용자")
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 130)
        self.table.cellDoubleClicked.connect(self.edit)

    def refresh(self):
        records = self.service.list_users()
        names = {p: name for _, name, _, p in NAV_ITEMS}
        self.table.populate([[r["username"] + (" (로그인 중)" if r["id"] == self.service.user["id"] else ""), r["name"], "관리자" if r["role"] == "admin" else "일반 사용자", "모든 업무" if r["role"] == "admin" else " · ".join(names.get(p, p) for p in r.get("permissions", [])) or "권한 없음"] for r in records], records)
        self.results(len(records))

    def add(self):
        if UserDialog(self.service, parent=self).exec():
            self.refresh()

    def edit(self, *_):
        row = self.selected()
        if row and UserDialog(self.service, row, parent=self).exec():
            self.window.rebuild_navigation()

    def delete(self):
        row = self.selected()
        if row and QMessageBox.question(self, "사용자 삭제 확인", f"‘{row['name']} ({row['username']})’ 계정을 삭제하시겠습니까?\n현재 계정과 마지막 관리자는 보호됩니다.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.service.delete_user(row["id"]))


class SettingsPage(Page):
    def __init__(self, window):
        super().__init__(window, "설정 · 백업", "거래자료를 백업하고 계정과 주요 변경 이력을 확인합니다.", "settings")
        self.actions.addWidget(button("데이터베이스 백업", self.backup, primary=True, glyph="download"))
        info = QFrame()
        info.setObjectName("card")
        layout = QVBoxLayout(info)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.addWidget(label("데이터 보관 위치", "sectionTitle"))
        path_label = label(str(window.database_path))
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        layout.addWidget(label("SQLite · 자동 저장 · 외부 서버 연결 없음\n백업은 SQLite 온라인 백업으로 생성하고 무결성을 검사합니다.", "mutedLabel"))
        row = QHBoxLayout()
        row.addWidget(button("내 비밀번호 변경", self.password))
        row.addStretch()
        row.addWidget(label(f"서영 POS {__version__} · Windows 10 / 11 x64", "mutedLabel"))
        layout.addLayout(row)
        self.body.addWidget(info)
        self.table_frame(["일시", "사용자", "작업", "대상", "자료 ID", "변경 내용"], "주요 변경 이력")
        self.table.setColumnWidth(0, 210)
        self.table.setColumnWidth(5, 460)
        self.foot_layout.insertWidget(1, button("새로고침", self.refresh, glyph="refresh"))

    def refresh(self):
        records = self.service.audit_log()
        self.table.populate([[r["at"], r["username"], r["action"], r["entity"], r.get("entity_id", ""), r["detail"]] for r in records], records)
        self.results(len(records))

    def password(self):
        PasswordDialog(self.service, parent=self).exec()
        self.refresh()

    def backup(self):
        filename, _ = QFileDialog.getSaveFileName(self, "거래자료 백업", f"서영POS_백업_{date.today().isoformat()}.db", "SQLite 데이터베이스 (*.db)")
        if filename:
            if not filename.lower().endswith(".db"):
                filename += ".db"
            try:
                self.service.backup(filename)
                self.window.show_message(f"백업 완료 · {filename}")
                self.refresh()
            except (OSError, ValueError, PermissionError) as exc:
                QMessageBox.warning(self, "백업 실패", str(exc))


class MainWindow(QMainWindow):
    def __init__(self, service, database_path, demo=False):
        super().__init__()
        self.service = service
        self.database_path = Path(database_path)
        self.demo = demo
        self.pages = {}
        self.page_scrollers = {}
        self.nav_buttons = {}
        self.current_page = None
        self.setWindowTitle(f"서영 POS · 매입 · 매출 · 재고 관리{' [데모]' if demo else ''}")
        self.resize(1510, 960)
        self.setMinimumSize(1080, 660)
        self.setWindowIcon(icon("box", TEAL))
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 26, 14, 20)
        side.setSpacing(5)
        brand = QHBoxLayout()
        brand.setContentsMargins(9, 0, 0, 15)
        mark = label("S", "brandMark")
        mark.setFixedSize(43, 43)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(mark)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(label("서영 POS", "brandName"))
        texts.addWidget(label("STORE MANAGEMENT", "brandCaption"))
        brand.addLayout(texts)
        side.addLayout(brand)
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(5)
        side.addLayout(self.nav_layout)
        side.addStretch()
        side.addWidget(label("  ●   오프라인 매장 운영", "sidebarBadge"))
        side.addSpacing(12)
        side.addWidget(label(f"  SEOYOUNG POS  /  v{__version__}\n  내 매장의 데이터를 내 기기에", "sidebarFoot"))
        layout.addWidget(sidebar)
        workspace = QWidget()
        workspace.setObjectName("workspace")
        work = QVBoxLayout(workspace)
        work.setContentsMargins(0, 0, 0, 0)
        work.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(76)
        top = QHBoxLayout(topbar)
        top.setContentsMargins(28, 12, 28, 12)
        self.breadcrumb = label("매장 관리 워크스페이스", "topbarTitle")
        top.addWidget(self.breadcrumb)
        top.addStretch()
        top.addWidget(label("● 로컬 데이터베이스", "localBadge"))
        top.addSpacing(18)
        avatar = label((service.user.get("name") or "관")[0], "avatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(34, 34)
        top.addWidget(avatar)
        user_texts = QVBoxLayout()
        user_texts.setSpacing(1)
        self.user_label = label(service.user["name"], "userName")
        self.role_label = label("관리자" if service.user["role"] == "admin" else "일반 사용자", "userRole")
        user_texts.addWidget(self.user_label)
        user_texts.addWidget(self.role_label)
        top.addLayout(user_texts)
        top.addSpacing(8)
        top.addWidget(button("비밀번호", self.change_password))
        top.addWidget(button("로그아웃", self.logout))
        work.addWidget(topbar)
        if demo:
            banner = label("데모 모드  ·  샘플 자료가 표시됩니다. 실제 매장 데이터와 별도로 저장합니다.", "demoBanner")
            banner.setContentsMargins(12, 0, 12, 0)
            work.addWidget(banner)
        self.stack = QStackedWidget()
        work.addWidget(self.stack, 1)
        self.status = label("", "statusbar")
        self.status.setContentsMargins(28, 5, 28, 9)
        work.addWidget(self.status)
        layout.addWidget(workspace, 1)
        self.rebuild_navigation()
        for sequence, callback in [("F5", self.refresh), ("Ctrl+F", self.focus_search), ("Ctrl+E", self.export_current), ("Ctrl+N", self.new_current)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(callback)
            self.addAction(action)

    def rebuild_navigation(self):
        previous = self.current_page.code if self.current_page else None
        while self.nav_layout.count():
            item = self.nav_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.pages.clear()
        self.page_scrollers.clear()
        self.nav_buttons.clear()
        self.current_page = None
        for key, title, glyph, permission in NAV_ITEMS:
            if not self.service.has_permission(permission):
                continue
            if key in ("dashboard", "products", "users"):
                self.nav_layout.addWidget(label("워크스페이스" if key == "dashboard" else ("업무 관리" if key == "products" else "관리자"), "sideSection"))
            nav = QPushButton(title)
            nav.setObjectName("navButton")
            nav.setIcon(icon(glyph))
            nav.setIconSize(QSize(19, 19))
            nav.setCheckable(True)
            nav.clicked.connect(lambda checked=False, page_key=key: self.navigate(page_key))
            self.nav_buttons[key] = nav
            self.nav_layout.addWidget(nav)
        self.user_label.setText(self.service.user["name"])
        self.role_label.setText("관리자" if self.service.user["role"] == "admin" else "일반 사용자")
        if self.nav_buttons:
            self.navigate(previous if previous in self.nav_buttons else next(iter(self.nav_buttons)))
        else:
            screen = QWidget()
            layout = QVBoxLayout(screen)
            message = label("접근 가능한 업무가 없습니다. 관리자에게 권한 설정을 요청하세요.", "pageTitle")
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            message.setWordWrap(True)
            layout.addWidget(message)
            self.stack.addWidget(screen)
        self.show_message(f"자동 저장  ·  {self.database_path}     |     F5 조회   Ctrl+N 등록   Ctrl+F 검색   Ctrl+E 엑셀")

    def navigate(self, key):
        if key not in self.nav_buttons:
            return
        if key not in self.pages:
            factories = {
                "dashboard": lambda: DashboardPage(self), "products": lambda: ProductsPage(self),
                "suppliers": lambda: PartnersPage(self, "supplier"), "customers": lambda: PartnersPage(self, "customer"),
                "purchases": lambda: DocumentsPage(self, "purchase"), "sales": lambda: DocumentsPage(self, "sale"),
                "inventory": lambda: InventoryPage(self), "reports": lambda: ReportsPage(self),
                "users": lambda: UsersPage(self), "settings": lambda: SettingsPage(self),
            }
            self.pages[key] = factories[key]()
            scroller = QScrollArea()
            scroller.setObjectName("pageScroller")
            scroller.setWidgetResizable(True)
            scroller.setFrameShape(QFrame.Shape.NoFrame)
            scroller.setWidget(self.pages[key])
            self.page_scrollers[key] = scroller
            self.stack.addWidget(scroller)
        page = self.pages[key]
        try:
            page.refresh()
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "조회할 수 없습니다", str(exc))
            return
        self.current_page = page
        self.stack.setCurrentWidget(self.page_scrollers[key])
        self.breadcrumb.setText(f"매장 관리   /   {page.title}")
        for item_key, nav in self.nav_buttons.items():
            nav.setChecked(item_key == key)

    def new_document(self, kind):
        picker = PartnerPicker(self.service, "supplier" if kind == "purchase" else "customer", parent=self)
        if picker.exec() and picker.selected:
            dialog = DocumentDialog(self.service, kind, partner=picker.selected, parent=self)
            if dialog.exec():
                self.show_message("전표가 저장되었습니다. 재고와 미결제 잔액에 반영했습니다.")
            self.refresh()

    def new_current(self):
        if isinstance(self.current_page, DocumentsPage):
            self.new_document(self.current_page.kind)
        elif hasattr(self.current_page, "add"):
            self.current_page.add()

    def refresh(self):
        if self.current_page:
            try:
                self.current_page.refresh()
            except (ValueError, PermissionError) as exc:
                QMessageBox.warning(self, "조회할 수 없습니다", str(exc))

    def focus_search(self):
        if self.current_page and self.current_page.search:
            self.current_page.search.setFocus()
            self.current_page.search.selectAll()

    def export_current(self):
        if self.current_page:
            self.current_page.export()

    def show_message(self, text):
        self.status.setText(text)

    def change_password(self):
        PasswordDialog(self.service, parent=self).exec()

    def logout(self):
        self.service.logout()
        self.hide()
        if LoginDialog(self.service, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.rebuild_navigation()
            self.show()
        else:
            self.close()


def default_data_dir(demo=False):
    if demo:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
        return base / "SeoyoungPOS-Demo"
    if getattr(sys, "frozen", False):
        portable = Path(sys.executable).resolve().parent / "data"
        try:
            portable.mkdir(exist_ok=True)
            with tempfile.TemporaryFile(dir=portable):
                pass
            return portable
        except OSError:
            pass
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "SeoyoungPOS"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "SeoyoungPOS"


def main(argv=None):
    from .extended_ui import install
    install()

    parser = argparse.ArgumentParser(description="서영 POS — 오프라인 매입·매출·재고 관리")
    parser.add_argument("--data-dir", type=Path, help="SQLite 자료 폴더 (기본값: 사용자 자료 폴더 또는 포터블 data)")
    parser.add_argument("--demo", action="store_true", help="실제 자료와 분리된 샘플 데이터로 실행")
    parser.add_argument("--smoke-test", action="store_true", help="임시 데모로 데이터/화면 시작을 검증한 후 종료")
    parser.add_argument("--screenshot", type=Path, help="시작 화면을 PNG로 저장")
    args = parser.parse_args(argv)
    scratch = tempfile.TemporaryDirectory(prefix="seoyoung-smoke-") if args.smoke_test and not args.data_dir else None
    demo = args.demo or args.smoke_test
    data_dir = Path(scratch.name) if scratch else args.data_dir or default_data_dir(demo)
    # An explicit directory is still partitioned in demo mode so it can never
    # add demo transactions to the production DB in that same directory.
    db_path = data_dir / ("seoyoung-demo.db" if demo else "seoyoung.db")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("서영 POS")
    app.setOrganizationName("SeoyoungPOS")
    app.setStyle("Fusion")
    app.setFont(QFont("Malgun Gothic" if sys.platform == "win32" else "Noto Sans CJK KR", 10))
    app.setStyleSheet(STYLE)
    service = None
    try:
        service = POSService(db_path)
        if demo:
            from .demo import populate_demo
            populate_demo(service)
        elif LoginDialog(service).exec() != QDialog.DialogCode.Accepted:
            return 0
        window = MainWindow(service, db_path, demo)
        if app.platformName() != "offscreen" and app.primaryScreen():
            available = app.primaryScreen().availableGeometry()
            window.resize(min(1510, available.width() - 30), min(960, available.height() - 45))
        window.show()
        if args.smoke_test or args.screenshot:
            def verify():
                try:
                    if args.smoke_test:
                        assert len(service.list_products()) == 12, "Demo product count mismatch"
                        assert len(service.list_documents("purchase")) == 12, "Demo purchase count mismatch"
                        assert len(service.list_documents("sale")) == 7, "Demo sales count mismatch"
                        reopened = POSService(db_path)
                        try:
                            reopened.login("demo", "Demo-2026!")
                            assert len(reopened.list_documents("sale")) == 7, "Committed SQLite data missing"
                        finally:
                            reopened.close()
                        for key in list(window.nav_buttons):
                            window.navigate(key)
                            assert window.current_page is window.pages[key], f"Page failed: {key}"
                        window.navigate("dashboard")
                        app.processEvents()
                    if args.screenshot:
                        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                        if not window.grab().save(str(args.screenshot), "PNG"):
                            raise OSError("스크린샷 저장 실패")
                    if args.smoke_test:
                        print("PASS: SQLite persistence, demo purchase/sale data, 10 desktop pages and Qt startup", flush=True)
                        app.exit(0)
                except Exception as exc:
                    print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr, flush=True)
                    app.exit(1)
            QTimer.singleShot(350, verify)
        result = app.exec()
        return result
    except Exception as exc:
        if args.smoke_test:
            import traceback
            traceback.print_exc()
        else:
            QMessageBox.critical(None, "서영 POS 시작 실패", f"프로그램을 시작하지 못했습니다.\n{exc}\n\n데이터 위치: {db_path}")
        return 1
    finally:
        if service:
            service.close()
        if scratch:
            scratch.cleanup()
