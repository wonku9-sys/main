"""Administrator-only menu/action permission editor (manual pp. 142–145)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem

from .permissions import ACTIONS, MENU_POLICIES, can_action, has_menu
from .widgets import Page, action
from .trade_sheet import EntrySheet


class PermissionsPage(Page):
    def __init__(self, window):
        super().__init__(window, "권한 설정", "관리자만 직원의 메뉴 접근·등록·수정/편집·삭제/취소 권한을 설정합니다. 저장 즉시 다음 작업부터 반영합니다.")
        self.read_permissions = ("admin",)
        self.actions.addWidget(action("권한 저장", self.save, True))
        filters = QHBoxLayout()
        filters.addWidget(QLabel("직원 선택"))
        self.user = QComboBox()
        filters.addWidget(self.user, 1)
        filters.addWidget(action("다시 조회", self.refresh))
        self.body.addLayout(filters)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        self.grid = EntrySheet(0, 5)
        self.grid.setHorizontalHeaderLabels(["업무 메뉴", "조회 · 접근", "등록", "수정 · 편집", "삭제 · 취소"])
        self.grid.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.grid.setColumnWidth(column, 125)
        self.grid.verticalHeader().setDefaultSectionSize(38)
        self.body.addWidget(self.grid, 1)
        self.checks = {}
        self._loaded_user_id = None
        self.user.currentIndexChanged.connect(self.change_user)
        self.refresh()

    def refresh(self):
        guard = getattr(self, "_navigation_guard", None)
        if guard and not guard.allow_leave(self):
            return
        try:
            selected = self.user.currentData()
            self.records = {row["id"]: row for row in self.store.list_users()}
            self.user.blockSignals(True)
            self.user.clear()
            for row in self.records.values():
                self.user.addItem(f"{row['code']} · {row['name']} · {'관리자' if row['role'] == 'admin' else '직원'}{' (중지)' if not row['active'] else ''}", row["id"])
            self.user.setCurrentIndex(max(0, self.user.findData(selected)))
            self.user.blockSignals(False)
            self.load()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def change_user(self, *_):
        target = self.user.currentData()
        guard = getattr(self, "_navigation_guard", None)
        if guard and self._loaded_user_id is not None:
            self.user.blockSignals(True)
            self.user.setCurrentIndex(self.user.findData(self._loaded_user_id))
            self.user.blockSignals(False)
            if not guard.allow_leave(self):
                return
            self.user.blockSignals(True)
            self.user.setCurrentIndex(self.user.findData(target))
            self.user.blockSignals(False)
        self.load()

    def load(self, *_):
        self._loaded_user_id = self.user.currentData()
        record = self.records.get(self.user.currentData())
        self.checks.clear()
        rows = [(key, rule) for key, rule in MENU_POLICIES.items() if (rule[1] or key in {"diary","worklog","household"}) and "admin" not in rule[1]]
        self.grid.setRowCount(len(rows))
        if not record:
            return
        admin = record["role"] == "admin"
        self.note.setText("관리자는 모든 권한을 가집니다. 관리자 역할 변경은 사용자 관리에서 처리하세요." if admin else "체크 해제: 해당 기능 차단. 조회만 체크하면 읽기 전용입니다. 결제 정정은 삭제/취소 후 재등록, 반품은 삭제/취소 권한도 필요합니다.")
        for index, (key, (label, bases, operations)) in enumerate(rows):
            item = QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.grid.setItem(index, 0, item)
            checks = self.checks[key] = {}
            for column, operation in enumerate(("view", "create", "edit", "delete"), 1):
                checkbox = QCheckBox()
                available = operation == "view" or operation in operations
                checkbox.setChecked(has_menu(record, key) if operation == "view" else can_action(record, key, operation) if available else False)
                checkbox.setEnabled(not admin and available and (operation == "view" or has_menu(record, key)))
                if not available:
                    checkbox.setToolTip("이 메뉴에 해당 작업이 없습니다. 확정 이력은 직접 편집하지 않습니다.")
                checks[operation] = checkbox
                self.grid.setCellWidget(index, column, checkbox)
            checks["view"].toggled.connect(lambda checked, key=key: self.toggle_row(key, checked))
        from .navigation import mark_saved
        mark_saved(self)

    def toggle_row(self, key, checked):
        operations = MENU_POLICIES[key][2]
        for operation, box in self.checks[key].items():
            if operation != "view":
                box.setEnabled(checked and operation in operations)

    def save(self):
        try:
            self.store._require("admin")
            user_id = self.user.currentData()
            latest = next((row for row in self.store.list_users() if row["id"] == user_id), None)
            if not latest or latest["role"] == "admin":
                raise ValueError("직원 계정을 선택하세요. 관리자 권한은 이 메뉴에서 제한하지 않습니다.")
            permissions = set()
            for key, checks in self.checks.items():
                _, bases, operations = MENU_POLICIES[key]
                if checks["view"].isChecked():
                    permissions.update(bases)
                else:
                    permissions.add(f"deny:{key}")
                for operation in operations:
                    if not checks[operation].isChecked():
                        permissions.add(f"deny:{key}.{operation}")
            self.store.save_user({"permissions": sorted(permissions)}, user_id)
            self.refresh()
            self.notify("직원 권한을 저장했습니다. 다음 조회·저장·삭제부터 적용됩니다.")
        except (ValueError, PermissionError) as exc:
            self.fail(exc)
