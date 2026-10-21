"""Supplier management layouts based on manual pp.72–76 and supplied screens."""
from decimal import Decimal

from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QScrollArea, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget, QFrame

from .catalog_ui import EntryDialog, ProductDialog
from .permissions import can_action
from .suppliers import GROUP_KINDS, PROFILE_TEXT
from .widgets import DataGrid, Page, action, date_field, won, action_menu, reference_grid


def confirm(parent, title, message):
    return QMessageBox.question(parent, title, message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


class SupplierDialog(QDialog):
    saved = Signal(int)
    def __init__(self, window, record=None):
        super().__init__(window)
        self.store, self.record, self.saved_id = window.store, record or {}, None
        self.store.require_menu("suppliers")
        self.readonly = not can_action(self.store.actor, "suppliers", "edit" if record else "create")
        self.setWindowTitle("공급사 등록정보" if record else "새 공급사 등록")
        self.setObjectName('supplierDialog')
        self._sy_no_home_button=True;self._fixed_query_header=True
        self.resize(900,760)
        self.setStyleSheet('''QDialog#supplierDialog QLineEdit,QDialog#supplierDialog QComboBox,QDialog#supplierDialog QSpinBox,QDialog#supplierDialog QDoubleSpinBox,QDialog#supplierDialog QDateEdit{min-width:0;min-height:20px;padding:3px 5px;}
            QDialog#supplierDialog QGroupBox{border-radius:3px;margin-top:10px;padding-top:9px;}
            QDialog#supplierDialog QPushButton{min-height:20px;padding:4px 8px;}
            QDialog#supplierDialog QTabBar::tab{padding:6px 8px;}''')
        self.fields = {}
        body = QVBoxLayout(self)
        body.setContentsMargins(10,8,10,8);body.setSpacing(5)
        self.tabs = QTabWidget()
        body.addWidget(self.tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        grid = QGridLayout(contents)
        grid.setContentsMargins(6,6,6,6);grid.setSpacing(6)
        self.tabs.addTab(scroll, "공급사 기본정보")
        scroll.setWidget(contents)
        def group(title, row, column):
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setContentsMargins(8,5,8,7);form.setSpacing(4)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            grid.addWidget(box, row, column)
            return form
        def fields(form, pairs):
            for key, label in pairs:
                field = QLineEdit(str(self.record.get(key, "")))
                field.setReadOnly(self.readonly)
                self.fields[key] = field
                form.addRow(label, field)
        base = group("사업자 기본정보", 0, 0)
        fields(base, (("code", "공급사코드"), ("name", "공급사명 *"), ("business_no", "사업자번호"), ("business_type", "업태"), ("business_item", "업종 · 취급상품"), ("representative", "대표자"), ("representative_mobile", "대표자 휴대폰")))
        self.fields["code"].setPlaceholderText("비워두면 저장 시 자동 생성")
        self.active = QCheckBox("유효 공급사")
        self.active.setChecked(bool(self.record.get("active", True)))
        base.addRow(self.active)
        contact = group("담당자 · 연락처", 0, 1)
        fields(contact, (("contact", "담당자"), ("phone", "전화"), ("fax", "팩스"), ("mobile", "휴대폰"), ("email", "이메일"), ("postal_code", "우편번호"), ("address", "주소"), ("homepage", "홈페이지 (참고)")))
        trade = group("거래 · 결제 조건", 1, 0)
        self.mode = QComboBox()
        self.mode.addItem("직영 (직매입)", "direct")
        self.mode.addItem("수수료 공급사", "commission")
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.record.get("supplier_mode", "direct"))))
        self.commission = QDoubleSpinBox()
        self.commission.setRange(0, 100)
        self.commission.setDecimals(2)
        self.commission.setSuffix(" %")
        self.commission.setValue(self.record.get("commission_bps", 0) / 100)
        self.method = QComboBox()
        self.method.addItem("현금", "cash")
        self.method.addItem("계좌이체", "transfer")
        self.method.setCurrentIndex(max(0, self.method.findData(self.record.get("settlement_method", "cash"))))
        self.settlement_group = QComboBox()
        self.settlement_group.addItem("미지정", None)
        for row in self.store.supplier_groups("settlement"):
            self.settlement_group.addItem(row["name"], row["id"])
        self.settlement_group.setCurrentIndex(max(0, self.settlement_group.findData(self.record.get("settlement_group_id"))))
        self.settlement_day = QSpinBox()
        self.settlement_day.setRange(0, 31)
        self.settlement_day.setSpecialValueText("미지정")
        self.settlement_day.setValue(self.record.get("settlement_day", 0))
        for label, field in (("거래유형", self.mode), ("판매 수수료율", self.commission), ("결제방법", self.method), ("결제유형", self.settlement_group), ("약정 결제일 (참고)", self.settlement_day)):
            trade.addRow(label, field)
        note = QLabel("수수료 변경은 이후 거래에만 적용합니다. 약정일·결제유형은 관리용 분류이며 자동 송금하지 않습니다.")
        note.setWordWrap(True)
        trade.addRow(note)
        bank = group("계좌 · 시작 외상잔액", 1, 1)
        fields(bank, (("bank", "은행명"), ("account", "계좌번호"), ("account_holder", "예금주"), ("opening_balance", "시작 외상잔액 (원)")))
        if not record:
            self.fields["opening_balance"].setText("0")
        self.opening_date = date_field(self.record.get("opening_date"))
        bank.addRow("시작 잔액 기준일", self.opening_date)
        bank.addRow(QLabel(f"현재 외상잔액: {won(self.record.get('balance', 0))}원"))
        self.memo = QTextEdit(self.record.get("memo", ""))
        self.memo.setAcceptRichText(False)
        self.memo.setMaximumHeight(100)
        grid.addWidget(QLabel("메모"), 2, 0)
        grid.addWidget(self.memo, 3, 0, 1, 2)
        warning = QLabel("오프라인 지원: 직영·수수료, 현금·이체. 온라인 발주 암호·서버·임대 정산·카드/포인트별 추가 수수료·부가세 별도 입력은 포함하지 않습니다.")
        warning.setWordWrap(True)
        grid.addWidget(warning, 4, 0, 1, 2)
        self.products_grid = DataGrid(["상품코드", "상품명", "규격", "바코드", "매입단가", "판매단가", "유효"])
        self.products_grid.read_permissions = ("catalog",)
        product_panel = QWidget()
        product_body = QVBoxLayout(product_panel)
        if self.record:
            products = self.store.products(supplier_id=self.record["id"])
            self.products_grid.fill([[p["code"], p["name"], p["specification"], p["barcode"], p["purchase_price"], p["sale_price"], "유효" if p["active"] else "무효"] for p in products], products)
        product_body.addWidget(self.products_grid, 1)
        product_tools = QHBoxLayout()
        product_tools.addWidget(action("엑셀 저장", lambda: self.products_grid.export(self, "공급사 상품목록")))
        product_tools.addWidget(action("인쇄", lambda: self.products_grid.print_pages(self, "공급사 상품목록")))
        product_body.addLayout(product_tools)
        self.tabs.addTab(product_panel, "공급사 상품목록 조회")
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#AD5149;")
        body.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self._sy_pinned_footer=self.buttons
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("닫기")
        self.apply_button = self.buttons.addButton('적용', QDialogButtonBox.ButtonRole.ApplyRole)
        self.apply_button.clicked.connect(self.apply_changes)
        self.apply_button.setToolTip('입력 내용을 즉시 저장하고 창을 유지합니다. 같은 공급사를 계속 수정할 수 있습니다.')
        self.next_button = self.buttons.addButton('저장 후 다음 공급사', QDialogButtonBox.ButtonRole.ActionRole)
        self.next_button.clicked.connect(self.next_record)
        self.next_button.setEnabled(not self.readonly and can_action(self.store.actor, 'suppliers', 'create'))
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        for button in self.buttons.buttons():button.setAutoDefault(False)
        body.addWidget(self.buttons)
        if self.readonly:
            for control in (self.active, self.mode, self.commission, self.method, self.settlement_group, self.settlement_day, self.opening_date, self.memo):
                control.setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            self.apply_button.setEnabled(False)

    def save(self, close=True):
        try:
            values = {key: field.text() for key, field in self.fields.items()}
            values.update(kind="supplier", active=self.active.isChecked(), supplier_mode=self.mode.currentData(), commission_bps=int(Decimal(str(self.commission.value())) * 100),
                          settlement_method=self.method.currentData(), settlement_group_id=self.settlement_group.currentData(), settlement_day=self.settlement_day.value(),
                          opening_date=self.opening_date.date().toString("yyyy-MM-dd"), memo=self.memo.toPlainText())
            self.saved_id = self.store.save_partner(values, self.record.get("id"))
            self.record = next(row for row in self.store.partners('supplier') if row['id']==self.saved_id)
            self.fields['code'].setText(self.record['code'])
            from .navigation import mark_saved
            mark_saved(self)
            self.error_label.clear()
            self.saved.emit(self.saved_id)
            if close:self.accept()
            return True
        except (ValueError, PermissionError) as exc:
            self.error_label.setText(str(exc))
            return False

    def apply_changes(self):
        if self.save(False):
            self.error_label.setText('저장되었습니다. 계속 수정하거나 ‘저장 후 다음 공급사’를 누르세요.')

    def next_record(self):
        if not can_action(self.store.actor, 'suppliers', 'create'):
            self.error_label.setText('새 공급사를 등록할 권한이 없습니다.');return
        if not self.save(False):return
        self.record = {}; self.saved_id = None
        for key, field in self.fields.items():field.setText('0' if key=='opening_balance' else '')
        self.active.setChecked(True); self.mode.setCurrentIndex(0); self.commission.setValue(0)
        self.method.setCurrentIndex(0); self.settlement_group.setCurrentIndex(0); self.settlement_day.setValue(0)
        self.opening_date.setDate(QDate.currentDate()); self.memo.clear(); self.products_grid.fill([])
        self.setWindowTitle('새 공급사 등록'); self.tabs.setCurrentIndex(0)
        from .navigation import mark_saved
        mark_saved(self)
        self.error_label.setText('이전 공급사를 저장했습니다. 다음 공급사를 입력하세요.')
        self.fields['name'].setFocus()

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()


class SupplierGroupsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.store, self.group_id, self.members, self.loaded_kind = window.store, None, [], "settlement"
        self.readonly = not can_action(self.store.actor, "suppliers", "edit")
        self.fields = {}
        self.setWindowTitle("공급사 그룹관리")
        self.resize(1000, 670)
        body = QVBoxLayout(self)
        columns = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        self.kind = QComboBox()
        for key, label in GROUP_KINDS.items():
            self.kind.addItem(label, key)
        left.addWidget(self.kind)
        self.groups = DataGrid(["코드", "그룹명", "순번", "공급사 수"])
        left.addWidget(self.groups, 1)
        controls = QHBoxLayout()
        for label, callback in (("추가", self.add), ("수정", self.edit), ("삭제", self.delete)):
            button = action(label, callback)
            button.setEnabled(not self.readonly)
            controls.addWidget(button)
        left.addLayout(controls)
        self.label = QLabel("왼쪽에서 그룹을 선택하세요.")
        right.addWidget(self.label)
        self.suppliers = DataGrid(["소속", "코드", "공급사명", "유형", "상태"])
        right.addWidget(self.suppliers, 1)
        columns.addLayout(left, 2)
        columns.addLayout(right, 3)
        body.addLayout(columns, 1)
        note = QLabel("오른쪽에서 공급사를 체크한 뒤 ‘그룹소속 저장’을 누르세요. 결제유형은 공급사당 하나, 일반그룹은 여러 개 지정할 수 있습니다.")
        note.setWordWrap(True)
        body.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("그룹소속 저장")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not self.readonly)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        body.addWidget(self.buttons)
        self.kind.currentIndexChanged.connect(self.change_kind)
        self.groups.itemSelectionChanged.connect(self.select_group)
        self.refresh()

    def checked_members(self):
        return sorted(self.suppliers.item(row, 0).data(Qt.ItemDataRole.UserRole)["id"] for row in range(self.suppliers.rowCount()) if self.suppliers.item(row, 0).checkState() == Qt.CheckState.Checked)

    def refresh(self):
        rows = self.store.supplier_groups(self.loaded_kind)
        self.groups.blockSignals(True)
        self.groups.fill([[r["code"], r["name"], r["sort_order"], r["member_count"]] for r in rows], rows)
        self.groups.blockSignals(False)
        if rows:
            index = next((i for i in range(self.groups.rowCount()) if self.groups.item(i, 0).data(Qt.ItemDataRole.UserRole)["id"] == self.group_id), 0)
            self.groups.selectRow(index)
        else:
            self.group_id, self.members = None, []
            self.suppliers.fill([])
            from .navigation import mark_saved
            mark_saved(self)

    def allow_change(self):
        from .navigation import confirm_dialog_exit
        return confirm_dialog_exit(self)

    def change_kind(self, *_):
        target = self.kind.currentData()
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(self.kind.findData(self.loaded_kind))
        self.kind.blockSignals(False)
        if not self.allow_change():
            return
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(self.kind.findData(target))
        self.kind.blockSignals(False)
        self.loaded_kind, self.group_id = target, None
        self.refresh()

    def select_group(self):
        row = self.groups.selected()
        if not row:
            return
        if row["id"] != self.group_id and not self.allow_change():
            self.groups.blockSignals(True)
            for index in range(self.groups.rowCount()):
                if self.groups.item(index, 0).data(Qt.ItemDataRole.UserRole)["id"] == self.group_id:
                    self.groups.selectRow(index)
                    break
            self.groups.blockSignals(False)
            return
        self.group_id = row["id"]
        self.members = self.store.supplier_group_members(self.group_id)
        self.label.setText(f"{row['name']} · 소속 공급사 선택")
        parties = self.store.partners("supplier")
        self.suppliers.fill([["", p["code"], p["name"], "직영" if p["supplier_mode"] == "direct" else "수수료", "유효" if p["active"] else "무효"] for p in parties], parties)
        for index in range(self.suppliers.rowCount()):
            item = self.suppliers.item(index, 0)
            party = item.data(Qt.ItemDataRole.UserRole)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if party["id"] in self.members else Qt.CheckState.Unchecked)
            if self.readonly:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        from .navigation import mark_saved
        mark_saved(self)

    def editor(self, row=None):
        if not self.allow_change():
            return
        dialog = EntryDialog("공급사 그룹 수정" if row else "공급사 그룹 추가", self)
        dialog.field("code", "코드", (row or {}).get("code", ""))
        dialog.field("name", "그룹명", (row or {}).get("name", ""))
        dialog.field("sort_order", "순번", (row or {}).get("sort_order", 0))
        result = []
        dialog.finish(lambda: result.append(self.store.save_supplier_group({**dialog.values(), "kind": self.loaded_kind}, (row or {}).get("id"))))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.group_id = result[0]
            self.refresh()

    def add(self):
        self.editor()

    def edit(self):
        row = self.groups.selected()
        if row:
            self.editor(row)

    def delete(self):
        row = self.groups.selected()
        if row and self.allow_change() and confirm(self, "그룹 삭제", f"'{row['name']}' 그룹을 삭제할까요? 공급사 자료는 삭제하지 않습니다."):
            try:
                self.store.delete_supplier_group(row["id"])
                self.group_id = None
                self.refresh()
            except (ValueError, PermissionError) as exc:
                QMessageBox.warning(self, "삭제할 수 없습니다", str(exc))

    def save(self):
        if self.group_id is None:
            return False
        try:
            self.store.set_supplier_group_members(self.group_id, self.checked_members(), self.members)
            self.members = self.checked_members()
            from .navigation import mark_saved
            mark_saved(self)
            self.label.setText("그룹 소속을 저장했습니다.")
            return True
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "저장할 수 없습니다", str(exc))
            return False

    def reject(self):
        if self.allow_change():
            super().reject()


class SuppliersPage(Page):
    kind = "supplier"

    def __init__(self, window):
        super().__init__(window, "공급사관리", "PDF p.72~76 · 공급사 추가, 목록 더블클릭 수정, 유효/무효와 그룹별 조회")
        self.body.setContentsMargins(8,8,8,8);self.body.setSpacing(6)
        self.actions.addWidget(action("공급사 추가", self.add, True))
        self.actions.addWidget(action("그룹관리", self.group_manager))
        self.search = QLineEdit()
        self.search.setPlaceholderText("공급사명 · 코드 · 사업자번호 · 전화번호")
        self.status = QComboBox()
        for label, value in (("유효", True), ("무효", False), ("전체 상태", None)):
            self.status.addItem(label, value)
        self.method = QComboBox()
        for label, value in (("전체 결제방법", ""), ("현금", "cash"), ("계좌이체", "transfer")):
            self.method.addItem(label, value)
        self.mode = QComboBox()
        for label, value in (("전체 거래유형", ""), ("직영", "direct"), ("수수료", "commission")):
            self.mode.addItem(label, value)
        self.settlement = QComboBox()
        self.group = QComboBox()
        self.exclude = QCheckBox("선택 그룹 제외")
        self.filter_panel=QFrame();self.filter_panel.setObjectName('compactFilters')
        self.filter_panel.setStyleSheet('QFrame#compactFilters{border:1px solid #A7B3AC;border-radius:0;background:palette(window);} QLineEdit,QComboBox{min-width:0;min-height:20px;padding:3px 5px;}')
        filters=QGridLayout(self.filter_panel);filters.setContentsMargins(6,6,6,6);filters.setSpacing(5)
        for column,widget in enumerate((self.search,self.status,self.method,self.mode)):
            filters.addWidget(widget,0,column);filters.setColumnStretch(column,2 if column==0 else 1)
        filters.addWidget(self.settlement,1,0);filters.addWidget(self.group,1,1);filters.addWidget(self.exclude,1,2,1,2)
        self.body.addWidget(self.filter_panel)
        self.grid = self.table(["코드", "공급사명", "구분", "사업자번호", "대표자", "담당자", "전화", "팩스", "휴대폰", "결제방법", "결제유형", "그룹", "은행명", "계좌번호", "예금주", "현재 외상잔액", "상태"])
        reference_grid(self.grid)
        for visual,logical in enumerate((0,1,2,3,5,6,7,8,4,9,10,11,12,13,14,15,16)):
            self.grid.horizontalHeader().moveSection(self.grid.horizontalHeader().visualIndex(logical),visual)
        self.grid.verticalHeader().setVisible(True)
        for column,width in enumerate((85,210,75,130,90,90,135,120,135)):
            self.grid.setColumnWidth(column,width)
        from PySide6.QtWidgets import QAbstractItemView
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.context_menu)
        self.grid.setToolTip('Ctrl+클릭: 여러 공급사 선택 · Shift+클릭: 범위 선택\n우클릭: 선택 공급사 유효/무효 변경')
        self.summary = QLabel()
        self.body.addWidget(self.summary)
        tools = QHBoxLayout()
        edit=action("등록정보 / 수정",self.edit)
        state = action("유효 / 무효 변경", self.set_active)
        state.setEnabled(can_action(self.store.actor, "suppliers", "edit"))
        self.more_actions=action_menu('추가 기능',[edit,state],self)
        self.actions.addWidget(self.more_actions)
        self.grid.itemDoubleClicked.connect(self.edit)
        self.search.textChanged.connect(self.filter_rows)
        for combo in (self.status, self.method, self.mode, self.settlement, self.group):
            combo.currentIndexChanged.connect(self.filter_rows)
        self.exclude.toggled.connect(self.filter_rows)
        self.refresh()

    def refresh(self):
        self.store.require_menu("suppliers")
        for combo, kind, title in ((self.settlement, "settlement", "전체 결제유형"), (self.group, "general", "전체 그룹")):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(title, None)
            for row in self.store.supplier_groups(kind):
                combo.addItem(row["name"], row["id"])
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)
        self.filter_rows()

    def filter_rows(self, *_):
        if not hasattr(self, "grid"):
            return
        try:
            self.store.require_menu("suppliers")
            rows = self.store.partners("supplier", self.search.text())
            active, method, mode, settlement, group = self.status.currentData(), self.method.currentData(), self.mode.currentData(), self.settlement.currentData(), self.group.currentData()
            rows = [row for row in rows if (active is None or bool(row["active"]) == active) and (not method or row["settlement_method"] == method) and (not mode or row["supplier_mode"] == mode) and (not settlement or row["settlement_group_id"] == settlement) and (not group or (group not in row["group_ids"] if self.exclude.isChecked() else group in row["group_ids"]))]
            self.grid.fill([[p["code"], p["name"], "직영" if p["supplier_mode"] == "direct" else "수수료", p["business_no"], p["representative"], p["contact"], p["phone"], p["fax"], p["mobile"], "현금" if p["settlement_method"] == "cash" else "계좌이체", p["settlement_type"], p["group_names"], p["bank"], p["account"], p["account_holder"], p["balance"], "유효" if p["active"] else "무효"] for p in rows], rows)
            self.summary.setText(f"조회 공급사 {len(rows):,}개 · 현재 외상잔액 합계 {won(sum(row['balance'] for row in rows))}원")
        except (ValueError, PermissionError) as exc:
            self.grid.fill([])
            self.fail(exc)

    def add(self):
        dialog = SupplierDialog(self.window)
        dialog.saved.connect(lambda *_: self.refresh())
        dialog.exec()

    def edit(self, *_):
        row = self.grid.selected()
        if row:
            dialog = SupplierDialog(self.window, row)
            dialog.saved.connect(lambda *_: self.refresh())
            dialog.exec()
            self.refresh()

    def set_active(self):
        rows = self.selected_suppliers()
        if rows:
            self.change_active(not all(row['active'] for row in rows))

    def selected_suppliers(self):
        return [self.grid.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.grid.selectionModel().selectedRows()]

    def change_active(self, active):
        rows = self.selected_suppliers()
        if rows and confirm(self, '공급사 상태 변경', f"선택한 공급사 {len(rows):,}개를 {'유효' if active else '무효'}로 변경할까요? 기존 거래와 잔액은 보존합니다."):
            try:
                self.store.set_suppliers_active([row['id'] for row in rows], active)
                self.refresh()
            except (ValueError, PermissionError) as exc:
                self.fail(exc)

    def context_menu(self, point):
        item = self.grid.itemAt(point)
        if item is None:
            return
        try:
            self.store.require_menu('suppliers')
        except PermissionError as exc:
            self.fail(exc); return
        if not item.isSelected():
            self.grid.selectRow(item.row())
        self.make_context_menu().exec(self.grid.viewport().mapToGlobal(point))

    def make_context_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction('등록정보 / 수정', self.edit)
        menu.addAction('줄여보기', lambda: self.set_row_density(True))
        menu.addAction('펼쳐보기', lambda: self.set_row_density(False))
        for label, columns in (('사람/연락처 보기', (4, 5, 6, 7, 8)), ('계좌정보 보기', (12, 13, 14))):
            entry = menu.addAction(label); entry.setCheckable(True)
            entry.setChecked(all(not self.grid.isColumnHidden(c) for c in columns))
            entry.toggled.connect(lambda shown, cols=columns: [self.grid.setColumnHidden(c, not shown) for c in cols])
        menu.addSeparator()
        editable = bool(self.selected_suppliers()) and can_action(self.store.actor, 'suppliers', 'edit')
        for label, active in (('선택 공급사 유효', True), ('선택 공급사 무효', False)):
            entry = menu.addAction(label, lambda checked=False, value=active: self.change_active(value))
            entry.setEnabled(editable)
        methods = menu.addMenu('선택 공급사 결제방법')
        for label, method in (('현금', 'cash'), ('계좌이체', 'transfer')):
            entry = methods.addAction(label, lambda checked=False, value=method: self.change_payment_method(value))
            entry.setEnabled(editable)
        columns = menu.addMenu('열 선택')
        for column in range(self.grid.columnCount()):
            entry = columns.addAction(self.grid.horizontalHeaderItem(column).text())
            entry.setCheckable(True); entry.setChecked(not self.grid.isColumnHidden(column))
            entry.toggled.connect(lambda shown, c=column: self.grid.setColumnHidden(c, not shown))
        menu.addSeparator()
        menu.addAction('모두 선택', self.grid.selectAll)
        menu.addAction('선택 해제', self.grid.clearSelection)
        return menu

    def set_row_density(self, compact):
        # Native Windows header metrics can require 27px or more. Respect the
        # actual font/style minimum rather than clipping letters to force 25px.
        header=self.grid.verticalHeader()
        height=max(25 if compact else 38,header.minimumSectionSize(),self.grid.fontMetrics().height()+6)
        header.setDefaultSectionSize(height)

    def change_payment_method(self, method):
        rows = self.selected_suppliers()
        label = '현금' if method == 'cash' else '계좌이체'
        if not rows or not confirm(self, '공급사 결제방법', f'선택 공급사 {len(rows)}개의 기본 결제방법을 {label}(으)로 바꿀까요? 기존 결제 이력은 변경하지 않습니다.'):
            return
        try:
            self.store.set_supplier_payment_method([r['id'] for r in rows], method)
            self.refresh()
        except (ValueError, PermissionError) as exc:
            self.fail(exc)

    def group_manager(self):
        SupplierGroupsDialog(self.window).exec()
        self.refresh()
