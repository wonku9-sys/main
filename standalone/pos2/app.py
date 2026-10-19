"""Standalone desktop entry point, designed independently from the PDF workflow."""
from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QDate, QLockFile, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QScrollArea, QStackedWidget, QStyle, QToolBar, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from . import __version__
from .font_support import font_family, verify_glyphs
from .store import Store
from .widgets import DataGrid, FormDialog, Page, ScanField, action, date_field, won


STYLE = """
* { outline:none; }
QWidget { color:#243A48; font-size:12px; }
QMainWindow, QDialog { background:#F4F6F8; }
QLabel { background:transparent; }
QMenuBar { background:#FFFFFF; padding:4px 10px; border-bottom:1px solid #D8E0E6; }
QMenuBar::item { padding:5px 12px; }
QMenuBar::item:selected, QMenu::item:selected { background:#E5F2EC; color:#1C6654; }
QMenu { background:white; padding:5px; border:1px solid #D5DFE5; }
QMenu::item { padding:8px 22px 8px 12px; }
QToolBar { background:white; border-bottom:1px solid #D9E2E6; padding:6px 9px; spacing:4px; }
QToolButton { border:1px solid transparent; border-radius:5px; padding:5px 9px; background:transparent; }
QToolButton:hover, QToolButton:checked { background:#EAF3EF; border-color:#C9DFD3; }
#navPanel { background:#FFFFFF; border-right:1px solid #D7E0E5; }
#brand { font-size:21px; font-weight:750; color:#173D43; }
#independent { font-size:11px; color:#9C6F37; }
#navTree { background:transparent; border:0; }
#navTree::item { padding:7px 6px; border-radius:4px; }
#navTree::item:selected { background:#E6F1EB; color:#175B4C; }
#navTree::item:hover { background:#F2F6F4; }
#pageTitle, #dialogTitle { font-size:22px; font-weight:700; color:#173F49; }
#muted { color:#778996; font-size:11px; }
#notice { color:#8A652A; background:#FFF3D9; border:1px solid #EFDCB4; padding:7px 12px; }
#workspaceHeader { background:#FFFFFF; border-bottom:1px solid #DCE4E8; }
#section { background:white; border:1px solid #DBE3E8; border-radius:8px; }
#metric { background:white; border:1px solid #DAE5E2; border-radius:8px; padding:16px; }
#metricValue { color:#206B58; font-size:26px; font-weight:700; }
QPushButton { background:white; border:1px solid #CCD9DF; border-radius:5px; padding:7px 12px; min-height:19px; }
QPushButton:hover { background:#EDF4F1; border-color:#AFC9BD; }
QPushButton:disabled { color:#A4B0B7; background:#F1F4F5; }
#primary { background:#256E5B; color:white; border-color:#256E5B; font-weight:600; }
#primary:hover { background:#1B5948; }
#danger { color:#AD5149; background:#FFF5F2; border-color:#EACAC2; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit { background:white; border:1px solid #CFDCE2; border-radius:4px; padding:5px 7px; min-height:22px; selection-background-color:#D8ECE2; selection-color:#163F36; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border:1px solid #438B75; }
QLineEdit:read-only { background:#EFF3F5; color:#708592; }
QComboBox::drop-down { border:0; width:23px; }
QComboBox QAbstractItemView { background:white; selection-background-color:#DDEEE5; }
QTableWidget { background:white; alternate-background-color:#F8FAFB; gridline-color:#E3E9ED; border:1px solid #DCE4E8; selection-background-color:#DEEEE6; selection-color:#194E3E; }
QTableWidget::item { padding:5px 8px; }
QHeaderView::section { background:#EDF2F5; color:#526F7D; font-weight:600; border:0; border-bottom:1px solid #D4E0E5; border-right:1px solid #DEE7EB; padding:8px; }
QTabWidget::pane { background:white; border:1px solid #D9E3E8; border-radius:5px; }
QTabBar::tab { padding:10px 14px; color:#7E929C; background:transparent; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#226E55; border-bottom:2px solid #2A8064; font-weight:600; }
QGroupBox { background:white; border:1px solid #D9E4E8; border-radius:6px; margin-top:14px; padding-top:15px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; font-weight:600; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:#EFF3F5; width:10px; }
QScrollBar::handle:vertical { background:#BECED5; border-radius:4px; min-height:25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QStatusBar { color:#81939E; font-size:10px; }
"""

SECTIONS = [
    ("1. 기초관리", [("products", "상품장 · 확장단위", "catalog"), ("categories", "상품 분류", "catalog"), ("suppliers", "공급사", "catalog"), ("customers", "판매처", "catalog"), ("labels", "라벨 출력", "catalog")]),
    ("2. 매입 · 판매", [("purchases", "매입장 · 매입반품", "trade"), ("payments", "결제관리 · 공급사 지급", "trade"), ("sales", "매출장 · 고객반품", "trade"), ("ledger", "거래처 원장", "trade")]),
    ("3. 재고관리", [("inventory", "현재고 · 입출고", "inventory"), ("counts", "실사 입력 · 적용", "inventory"), ("closings", "현금 · 월재고 마감", ("inventory", "trade"))]),
    ("4. 회원 · 행사", [("members", "회원 · 포인트", "loyalty"), ("promotions", "특매 그룹", "loyalty"), ("prices", "가격 변경 예약", "loyalty"), ("gifts", "사은품 교환", "loyalty")]),
    ("5. 조회 · 보고서", [("overview", "업무 현황", "reports"), ("reports", "일 · 월 · 상세 집계", "reports"), ("commission", "공급사 판매 수수료", "reports")]),
    ("6. 관리자 모드", [("users", "사용자 · 접근권한", "admin"), ("settings", "매장 설정 · 백업", "admin")]),
]


class LoginDialog(FormDialog):
    def __init__(self, store, parent=None):
        self.store, self.initial = store, store.users_count() == 0
        if self.initial:
            store.bootstrap_default_admin()
        super().__init__("사용자 확인", parent)
        self.setMinimumWidth(430)
        self.resize(470, 330)
        self.code = self.field("code", "사용자 코드")
        self.name = self.confirm = None
        self.password = self.field("password", "비밀번호", password=True)
        default_available = store.default_login_available()
        self.code.setText("admin" if default_available else "")
        if default_available:
            self.password.setText("1234")
        self.hint = QLabel("초기 아이디: admin / 초기 비밀번호: 1234\n로그인 후 ‘비밀번호 변경’으로 변경해 주세요." if default_available else "설정된 계정과 비밀번호로 로그인하세요.\n변경한 비밀번호는 초기 비밀번호로 되돌아가지 않습니다.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("notice" if default_available else "muted")
        self.body.addWidget(self.hint)
        box = self.finish(self.submit)
        save = box.button(box.StandardButton.Save)
        save.setText("로그인")
        save.setAutoDefault(False)
        save.setDefault(False)
        self.password.returnPressed.connect(self.submit)

    def submit(self):
        try:
            self.store.login(self.code.text(), self.password.text())
            self.accept()
        except (ValueError, PermissionError) as exc:
            self.error(exc)


class OverviewPage(Page):
    def __init__(self, window):
        super().__init__(window, "이번 달 업무 현황", "이번 달 1일~오늘 · 확정된 거래와 반품을 집계합니다.")
        self.metrics = {}
        row = QHBoxLayout()
        for key, title in (("purchase_total", "순매입"), ("sale_total", "순매출"), ("profit", "매출총이익")):
            panel = QFrame()
            panel.setObjectName("metric")
            layout = QVBoxLayout(panel)
            layout.addWidget(QLabel(title))
            number = QLabel("0 원")
            number.setObjectName("metricValue")
            layout.addWidget(number)
            self.metrics[key] = number
            row.addWidget(panel)
        self.body.addLayout(row)
        self.grid = self.table(["일자", "단위", "순매입", "순매출", "매출원가", "매출총이익"])

    def refresh(self):
        today = date.today()
        report = self.store.report(today.replace(day=1).isoformat(), today.isoformat(), "day")
        for key, widget in self.metrics.items():
            widget.setText(f"{won(report['totals'].get(key, 0))} 원")
        self.grid.fill([[r["label"], r["unit"], r["purchase_total"], r["sale_total"], r["cost"], r["profit"]] for r in report["rows"]], report["rows"])


class InventoryPage(Page):
    def __init__(self, window):
        super().__init__(window, "현재고 · 입출고", "기본단위로 환산한 현재 수량과 등록순 이동평균 원가입니다. 확장단위 스캔도 같은 재고를 사용합니다.")
        filters = QHBoxLayout()
        self.search = ScanField()
        self.search.setPlaceholderText("상품코드 · 상품명 · 규격 · 기본/확장 바코드, F8 스캔")
        self.search.scanned.connect(lambda _: self.refresh())
        filters.addWidget(self.search, 1)
        filters.addWidget(action("조회", self.refresh))
        filters.addWidget(action("입출고 이력", self.history))
        self.body.addLayout(filters)
        self.grid = self.table(["코드", "상품", "분류", "현재고", "기본단위", "최소재고", "재고원가액", "관리", "보관 위치"])
        self.total = QLabel()
        self.body.addWidget(self.total)

    def refresh(self):
        from decimal import Decimal
        rows = self.store.products(self.search.text().strip())
        self.grid.fill([[r["code"], r["name"], r["category"], Decimal(r["stock_qty"]), r["base_unit"], Decimal(r["min_qty"]), r["stock_cost"], "관리" if r["tracked"] else "제외", f"{r['warehouse']} / {r['shelf']}"] for r in rows], rows)
        self.total.setText(f"{len(rows):,}개 상품 · 재고 원가액 {won(sum(r['stock_cost'] for r in rows if r['tracked']))} 원")

    def focus_scan(self):
        self.search.setFocus()
        self.search.selectAll()

    def history(self):
        selected = self.grid.selected()
        if not selected:
            return
        from decimal import Decimal
        dialog = FormDialog(f"{selected['name']} · 입출고", self)
        dialog.resize(1000, 630)
        grid = DataGrid(["일자", "구분", "수량 증감", "잔여 수량", "원가 증감", "잔여 원가", "사유"])
        records = self.store.stock_events(selected["id"])
        grid.fill([[r["date"], r["kind"], Decimal(r.get("qty_delta", "0")), Decimal(r.get("balance_qty", "0")), r["cost_delta"], r["balance_cost"], r["reason"]] for r in records], records)
        dialog.body.addWidget(grid, 1)
        dialog.body.addWidget(action("엑셀 저장", lambda: grid.export(dialog, "입출고 이력")))
        dialog.body.addWidget(action("인쇄", lambda: grid.print_pages(dialog, "입출고 이력")))
        dialog.body.addWidget(action("닫기", dialog.reject))
        dialog.exec()


class CommissionPage(Page):
    def __init__(self, window):
        super().__init__(window, "공급사 판매 수수료", "판매 시 기록한 공급사·수수료율 기준입니다. 카드 승인·카드사 정산과 무관한 로컬 판매 수수료입니다.")
        filters = QHBoxLayout()
        self.start = date_field(date.today().replace(day=1).isoformat())
        self.end = date_field()
        filters.addWidget(self.start)
        filters.addWidget(QLabel("~"))
        filters.addWidget(self.end)
        filters.addStretch()
        filters.addWidget(action("조회", self.refresh, primary=True))
        self.body.addLayout(filters)
        self.grid = self.table(["공급사", "순매출", "판매 수수료", "차인지급 기준액"])

    def refresh(self):
        report = self.store.commission_report(self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd"))
        records = report["rows"] if isinstance(report, dict) else report
        self.grid.fill([[r.get("supplier_name", r.get("label", "")), r.get("sale_total", r.get("net_sales", 0)), r.get("commission_fee", r.get("commission", r.get("commission_amount", 0))), r.get("payable", r.get("net_payable", 0))] for r in records], records)


class LabelsPage(Page):
    def __init__(self, window):
        super().__init__(window, "라벨 · 바코드 출력", "상품명·가격·원산지·Code128/EAN13 바코드를 라벨 프린터로 출력합니다.")
        self.body.addWidget(QLabel("USB 리더기: 키보드 입력(HID), 스캔 후 Enter. 프린터: Windows에 설치된 제조사 드라이버 사용."))
        self.body.addWidget(QLabel("기본 60×40mm, 40×30mm 등 사용자 크기·출력 위치·수량 설정. PDF·미리보기로 확인 후 실제 1장 시험 출력을 권장합니다."))
        self.body.addWidget(action("상품 · 확장단위 라벨 선택", self.open_labels, primary=True))
        self.body.addStretch()

    def open_labels(self):
        from .labels import LabelDialog
        LabelDialog(self.store, parent=self).exec()


class MainWindow(QMainWindow):
    def __init__(self, store, demo=False):
        super().__init__()
        self.store, self.demo = store, demo
        self.pages, self.items, self.nav_actions, self.scrollers = {}, {}, {}, {}
        self.current_page, self.current_key = None, None
        self.setWindowTitle(f"서영 POS 독립판 {__version__} · 서버 없는 매장 관리" + (" [체험]" if demo else ""))
        self.resize(1500, 930)
        self.setMinimumSize(1060, 680)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)
        sidebar = QFrame()
        sidebar.setObjectName("navPanel")
        sidebar.setFixedWidth(215)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 20, 10, 14)
        brand = QLabel("서영 POS")
        brand.setObjectName("brand")
        side.addWidget(brand)
        independent = QLabel(f"PDF 새 설계 · 독립판 {__version__}")
        independent.setObjectName("independent")
        side.addWidget(independent)
        self.tree = QTreeWidget()
        self.tree.setObjectName("navTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.itemClicked.connect(lambda item, _: self.open_page(item.data(0, Qt.ItemDataRole.UserRole)) if item.data(0, Qt.ItemDataRole.UserRole) else None)
        side.addWidget(self.tree, 1)
        side.addWidget(QLabel("● 로컬 SQLite · 서버 불필요"))
        side.addWidget(QLabel("자료 저장: data-v2\n기존 프로그램 DB와 별도"))
        layout.addWidget(sidebar)
        right = QVBoxLayout()
        right.setSpacing(0)
        header = QFrame()
        header.setObjectName("workspaceHeader")
        top = QHBoxLayout(header)
        top.setContentsMargins(20, 8, 20, 8)
        self.location = QLabel("독립형 매장 업무")
        top.addWidget(self.location, 1)
        top.addWidget(QLabel(f"{store.actor['name']} · {'관리자 모드' if store.actor['role'] == 'admin' else '일반 사용자'}"))
        self.admin_mode_button = None
        if store.actor["role"] == "admin":
            self.admin_mode_button = action("관리자 설정", lambda: self.open_page("settings"))
            top.addWidget(self.admin_mode_button)
        top.addWidget(action("비밀번호 변경", self.password))
        top.addWidget(action("로그아웃", self.logout))
        right.addWidget(header)
        if demo:
            banner = QLabel("체험 모드 · 실제 거래자료와 분리된 샘플입니다. 스캔·반품·실사·라벨을 시험할 수 있습니다.")
            banner.setObjectName("notice")
            right.addWidget(banner)
        elif store.actor["code"] == "admin" and store.default_login_available():
            banner = QLabel("초기 비밀번호를 사용 중입니다. 상단 ‘비밀번호 변경’에서 새 비밀번호로 변경해 주세요.")
            banner.setObjectName("notice")
            right.addWidget(banner)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        layout.addLayout(right, 1)
        self.toolbar = QToolBar("업무 바로가기", self)
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(self.toolbar)
        for title, entries in SECTIONS:
            allowed = [entry for entry in entries if self.allowed(entry[2])]
            if not allowed:
                continue
            menu = self.menuBar().addMenu(title)
            parent = QTreeWidgetItem(self.tree, [title])
            parent.setExpanded(True)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for key, caption, _permission in allowed:
                item = QTreeWidgetItem(parent, [caption])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                self.items[key] = item
                nav = QAction(caption, self)
                nav.setCheckable(True)
                nav.triggered.connect(lambda checked=False, page=key: self.open_page(page))
                menu.addAction(nav)
                self.nav_actions[key] = nav
        for title, callback, standard in (("상품장", lambda: self.open_page("products"), QStyle.StandardPixmap.SP_FileDialogContentsView), ("매입 등록", lambda: self.new_trade("purchase"), QStyle.StandardPixmap.SP_ArrowDown), ("판매 등록", lambda: self.new_trade("sale"), QStyle.StandardPixmap.SP_ArrowUp), ("F8 스캔", self.focus_scan, QStyle.StandardPixmap.SP_FileDialogDetailedView), ("조회", self.refresh, QStyle.StandardPixmap.SP_BrowserReload), ("엑셀 저장", self.export, QStyle.StandardPixmap.SP_DialogSaveButton), ("인쇄", self.print, QStyle.StandardPixmap.SP_FileIcon)):
            if title == "상품장" and not self.allowed("catalog") or title in ("매입 등록", "판매 등록") and not self.allowed("trade"):
                continue
            tool = QAction(self.style().standardIcon(standard), title, self)
            tool.triggered.connect(callback)
            self.toolbar.addAction(tool)
        for sequence, callback in (("F8", self.focus_scan), ("F5", self.refresh), ("Ctrl+E", self.export), ("Ctrl+P", self.print), ("Ctrl+N", self.new_current)):
            shortcut = QAction(self)
            shortcut.setShortcut(QKeySequence(sequence))
            shortcut.triggered.connect(callback)
            self.addAction(shortcut)
        self.notify(f"새 독립판 DB: {store.path} · F8 바코드  F5 조회  Ctrl+E 엑셀  Ctrl+P 인쇄")
        if self.items:
            self.open_page("overview" if "overview" in self.items else next(iter(self.items)))
        self.maintenance_timer = QTimer(self)
        self.maintenance_timer.setInterval(60 * 60 * 1000)
        self.maintenance_timer.timeout.connect(self.maintain_backups)
        self.maintenance_timer.start()
        QTimer.singleShot(500, self.maintain_backups)

    def maintain_backups(self):
        if not self.isVisible() or QApplication.activeModalWidget() is not None:
            return
        try:
            result = self.store.run_backup_retention()
            if result["deleted"] or result["failed"]:
                message = f"오래된 백업 {len(result['deleted']):,}개를 삭제했습니다.\n최근 생성된 백업 15개는 그대로 보관합니다."
                if result["failed"]:
                    message += f"\n사용 중인 파일 {len(result['failed']):,}개는 삭제하지 못했습니다."
                QMessageBox.information(self, "주간 백업 정리", message)
                if "settings" in self.pages and self.store.actor and self.store.actor["role"] == "admin":
                    self.pages["settings"].refresh_backups()
        except (ValueError, PermissionError, OSError):
            self.notify("백업 정리를 완료하지 못했습니다. 설정에서 백업 폴더를 확인하세요.")

    def closeEvent(self, event):
        self.maintenance_timer.stop()
        super().closeEvent(event)

    def allowed(self, permission):
        actor = self.store.actor
        permissions = (permission,) if isinstance(permission, str) else permission
        return bool(actor and (actor["role"] == "admin" or set(permissions) & set(actor["permissions"])))

    def open_page(self, key):
        if key not in self.items:
            return False
        from .catalog_ui import ProductsPage, CategoriesPage, PartnersPage, UsersPage, SettingsPage
        from .workflow_ui import TradesPage, LedgerPage, CountsPage, ReportPage, ClosingsPage
        from .loyalty_ui import MembersPage, PromotionsPage, PricesPage, GiftsPage
        from .payment_ui import SupplierPaymentsPage
        factories = {"overview": lambda: OverviewPage(self), "products": lambda: ProductsPage(self), "suppliers": lambda: PartnersPage(self, "supplier"), "customers": lambda: PartnersPage(self, "customer"), "purchases": lambda: TradesPage(self, "purchase"), "sales": lambda: TradesPage(self, "sale"), "ledger": lambda: LedgerPage(self), "inventory": lambda: InventoryPage(self), "counts": lambda: CountsPage(self), "closings": lambda: ClosingsPage(self), "members": lambda: MembersPage(self), "promotions": lambda: PromotionsPage(self), "prices": lambda: PricesPage(self), "gifts": lambda: GiftsPage(self), "reports": lambda: ReportPage(self), "commission": lambda: CommissionPage(self), "labels": lambda: LabelsPage(self), "users": lambda: UsersPage(self), "settings": lambda: SettingsPage(self)}
        factories["categories"] = lambda: CategoriesPage(self)
        factories["payments"] = lambda: SupplierPaymentsPage(self)
        try:
            if key not in self.pages:
                page = factories[key]()
                permissions = next(permission for _, entries in SECTIONS for page_key, _, permission in entries if page_key == key)
                page.read_permissions = (permissions,) if isinstance(permissions, str) else permissions
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(page)
                self.pages[key], self.scrollers[key] = page, scroll
                self.stack.addWidget(scroll)
            page = self.pages[key]
            page.refresh()
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "조회 실패", str(exc))
            return False
        self.current_key, self.current_page = key, page
        self.stack.setCurrentWidget(self.scrollers[key])
        self.tree.setCurrentItem(self.items[key])
        self.items[key].parent().setExpanded(True)
        self.location.setText(f"매장 업무  /  {page.title}")
        for page_key, nav in self.nav_actions.items():
            nav.setChecked(page_key == key)
        return True

    def notify(self, text):
        self.statusBar().showMessage(str(text))

    def refresh(self):
        if self.current_page:
            try:
                self.current_page.refresh()
            except (ValueError, PermissionError) as exc:
                QMessageBox.warning(self, "조회", str(exc))

    def new_trade(self, kind):
        if not self.allowed("trade"):
            return
        if self.open_page("purchases" if kind == "purchase" else "sales"):
            self.current_page.new_trade()

    def new_current(self):
        if self.current_key in ("purchases", "sales"):
            self.new_trade("purchase" if self.current_key == "purchases" else "sale")
        elif self.current_page and hasattr(self.current_page, "add"):
            self.current_page.add()

    def focus_scan(self):
        modal = QApplication.activeModalWidget()
        target = modal or self.current_page
        if target and hasattr(target, "focus_scan"):
            target.focus_scan()
        elif target:
            field = target.findChild(ScanField)
            if field:
                field.setFocus()
                field.selectAll()

    def export(self):
        if self.current_page:
            self.current_page.export()

    def print(self):
        if self.current_page:
            self.current_page.print()

    def password(self):
        dialog = FormDialog("내 비밀번호 변경", self)
        old = dialog.field("old", "현재 비밀번호", password=True)
        new = dialog.field("new", "새 비밀번호", password=True)
        confirmation = dialog.field("confirm", "새 비밀번호 확인", password=True)
        def save():
            try:
                if new.text() != confirmation.text():
                    raise ValueError("새 비밀번호 확인이 일치하지 않습니다.")
                self.store.change_password(old.text(), new.text())
                dialog.accept()
            except (ValueError, PermissionError) as exc:
                dialog.error(exc)
        dialog.finish(save)
        dialog.exec()

    def logout(self):
        if QMessageBox.question(self, "로그아웃", "로그아웃하고 프로그램을 종료할까요?") == QMessageBox.StandardButton.Yes:
            self.store.logout()
            self.close()

    def finish_restore(self, result):
        self.maintenance_timer.stop()
        self.setEnabled(False)
        for page in self.pages.values():
            page.hide()
        QMessageBox.information(self, "백업 복원 완료", "백업 자료를 불러왔습니다. 프로그램을 종료합니다.\n다시 실행한 뒤 백업 당시 계정·비밀번호로 로그인하세요.\n\n복원 전 자료의 자동 백업:\n" + result["safety_backup"])
        self.close()
        QApplication.instance().quit()


def data_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data-v2"
    root = Path(os.environ.get("LOCALAPPDATA", os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))))
    return root / "SeoyoungPOS-Standalone" / "data-v2"


def main(argv=None):
    parser = argparse.ArgumentParser(description="서영 POS 독립판 · 서버 없는 오프라인 매장 업무")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("서영 POS 독립판")
    app.setOrganizationName("SeoyoungStandalone")
    app.setStyle("Fusion")
    try:
        app.setFont(QFont(font_family(), 10))
    except RuntimeError as exc:
        if args.smoke_test:
            raise
        QMessageBox.critical(None, "글꼴 파일 오류", str(exc))
        return 1
    app.setStyleSheet(STYLE)
    scratch = tempfile.TemporaryDirectory(prefix="seoyoung-v2-") if args.smoke_test else None
    directory = Path(scratch.name) if scratch else args.data_dir or data_directory()
    is_demo = args.demo or args.smoke_test
    path = directory / ("seoyoung-standalone-demo.db" if is_demo else "seoyoung-standalone-v2.db")
    store, backdrop, window, process_lock = None, None, None, None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        process_lock = QLockFile(str(path) + ".lock")
        process_lock.setStaleLockTime(0)
        if not process_lock.tryLock(0):
            raise ValueError("이 장부를 사용하는 프로그램이 이미 실행 중입니다. 기존 창을 종료한 뒤 다시 실행하세요.")
        store = Store(path)
        if is_demo:
            from .demo import seed
            seed(store)
        else:
            backdrop = QMainWindow()
            backdrop.setWindowTitle("서영 POS 독립판 · 사용자 확인")
            backdrop.resize(1400, 900)
            for section, _ in SECTIONS:
                backdrop.menuBar().addMenu(section).setEnabled(False)
            backdrop.show()
            if LoginDialog(store, backdrop).exec() != QDialog.DialogCode.Accepted:
                return 0
        window = MainWindow(store, is_demo)
        if app.platformName() != "offscreen" and app.primaryScreen():
            available = app.primaryScreen().availableGeometry()
            window.resize(min(1500, available.width() - 20), min(930, available.height() - 35))
        window.show()
        if backdrop:
            backdrop.close()
        if args.smoke_test or args.screenshot:
            def verify():
                try:
                    if args.smoke_test:
                        verify_glyphs()
                        assert len(store.products()) == 6
                        assert len(store.documents(status="posted")) >= 9
                        for key in window.items:
                            assert window.open_page(key), f"Desktop page unavailable: {key}"
                        assert not any(key.startswith("seoyoung_pos") for key in sys.modules), "Legacy program imported"
                        from .demo import DEMO_CODE, DEMO_PASSWORD
                        reopened = Store(path)
                        try:
                            reopened.login(DEMO_CODE, DEMO_PASSWORD)
                            assert len(reopened.products()) == 6
                            assert len(reopened.documents(status="posted")) >= 9
                        finally:
                            reopened.close()
                        backup_file = store.create_backup()
                        store.save_member({"code": "SMOKE-RESTORE", "name": "복원 검증용 임시 회원"})
                        restored = store.restore_backup(backup_file, DEMO_PASSWORD)
                        assert Path(restored["safety_backup"]).is_file()
                        store.login(DEMO_CODE, DEMO_PASSWORD)
                        assert not store.members("SMOKE-RESTORE")
                    window.open_page("products")
                    app.processEvents()
                    if args.screenshot:
                        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                        assert window.grab().save(str(args.screenshot))
                        if args.smoke_test:
                            from .workflow_ui import ProductPicker, TradeDialog
                            def capture(suffix, widget):
                                widget.show()
                                app.processEvents()
                                target = args.screenshot.with_name(args.screenshot.stem + suffix + args.screenshot.suffix)
                                assert widget.grab().save(str(target))
                            purchase = TradeDialog(window, "purchase")
                            first = store.products()[0]
                            purchase.partner.setCurrentIndex(purchase.partner.findData(first["supplier_id"]))
                            for product in store.products(supplier_id=first["supplier_id"]):
                                purchase.scan_barcode(product["barcode"])
                            purchase.paid.setText("5000")
                            assert "미지급잔액" in purchase.balance_label.text()
                            capture("-purchase", purchase)
                            picker = ProductPicker(purchase)
                            assert picker.supplier_only.isChecked()
                            assert 0 < picker.grid.rowCount() < len(store.products())
                            capture("-product-search", picker)
                            picker.close()
                            purchase.close()
                            window.open_page("categories")
                            capture("-categories", window)
                            window.open_page("settings")
                            assert window.current_page.backup_grid.rowCount() >= 2
                            capture("-backup", window)
                            window.open_page("payments")
                            capture("-payments", window)
                            fresh_login_store = Store(directory / "smoke-login.db")
                            try:
                                first_login = LoginDialog(fresh_login_store, window)
                                assert first_login.code.text() == "admin" and "1234" in first_login.hint.text()
                                capture("-login", first_login)
                                first_login.submit()
                                assert fresh_login_store.actor["code"] == "admin"
                                fresh_login_store.change_password("1234", "Smoke-Admin-2026!")
                                assert not fresh_login_store.default_login_available()
                                first_login.close()
                            finally:
                                fresh_login_store.close()
                    if args.smoke_test:
                        print(f"PASS standalone-v2: {len(window.items)} desktop pages, returns, expanded units, persistence, backup restore, no legacy imports", flush=True)
                        app.exit(0)
                except BaseException:
                    import traceback
                    traceback.print_exc()
                    app.exit(1)
            QTimer.singleShot(250, verify)
        return app.exec()
    except BaseException as exc:
        if args.smoke_test:
            import traceback
            traceback.print_exc()
        else:
            QMessageBox.critical(None, "독립판 실행 오류", f"{exc}\n\n새 자료 위치: {path}\n기존 프로그램의 데이터 파일을 지정하지 마세요.")
        return 1
    finally:
        if window:
            window.close()
            window.deleteLater()
        if backdrop:
            backdrop.close()
        if store:
            store.close()
        if process_lock:
            process_lock.unlock()
        if scratch:
            scratch.cleanup()
