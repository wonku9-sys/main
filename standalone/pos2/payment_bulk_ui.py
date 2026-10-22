"""MGR supplier bulk payments: prepare (F5), add rows (F6), confirm (F9)."""
import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from uuid import uuid4

from PySide6.QtCore import QDateTime, QEvent, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QDateTimeEdit, QDialog,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QSpinBox, QVBoxLayout)

from .currency import public_input
from .number_edit import GroupedNumberEdit
from .payment_finance import DISCOUNTS, METHODS
from .purchase_payment_plan import normalize_plan
from .trade_sheet import EntrySheet
from .widgets import action, won


def parse_supplier_clipboard(value):
    """Exactly code/payment-amount, preserving leading zeroes and quoted cells."""
    if not isinstance(value, str) or len(value) > 200000:
        raise ValueError('붙여넣기 자료가 너무 큽니다. 최대 500행입니다.')
    try: rows = list(csv.reader(StringIO(value), delimiter='\t', strict=True))
    except csv.Error: raise ValueError('엑셀 셀의 따옴표/줄바꿈 형식을 확인하세요.') from None
    if rows and [v.strip() for v in rows[0]] in (['공급사코드', '지급금액'], ['공급사코드', '금액']): rows.pop(0)
    rows = [r for r in rows if any(v.strip() for v in r)]
    if not 1 <= len(rows) <= 500: raise ValueError('공급사코드·지급금액 두 열을 1~500행 복사하세요.')
    result = []
    for i, row in enumerate(rows, 1):
        if len(row) != 2 or not row[0].strip(): raise ValueError(f'{i}행: 공급사코드·지급금액 두 열이 필요합니다.')
        try: value = public_input(row[1], positive=True)
        except ValueError as exc: raise ValueError(f'{i}행: {exc}') from None
        result.append((row[0].strip(), str(value)))
    return result


class BulkPaymentDialog(QDialog):
    menu_key = 'payments'
    read_permissions = ('trade',)
    KEYS = ('code', 'name', 'datetime', 'method', 'amount', 'discount_method', 'discount', 'account', 'bill_number', 'bill_due', 'memo')

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window, self.store = window, window.store
        self.store._require_capability('payments', 'create')
        self._sy_no_home_button = True
        self._reserved_function_keys = {'F5', 'F6', 'F9'}
        self.rows = []; self.preview = None; self.request_id = str(uuid4()); self.saved_result = None
        self._busy = self._loading = self._outcome_unknown = False
        self.setWindowTitle('결제 일괄등록'); self.resize(1160, 700); self.setMinimumSize(850, 540)
        body = QVBoxLayout(self)
        note = QLabel('지급일·공급사·지급유형·금액 입력 → 입력(F5)으로 검토 → 확정(F9).\n확정 전에는 장부에 반영하지 않습니다. 실제 송금·카드 승인 기능이 아닙니다.')
        note.setWordWrap(True); body.addWidget(note)
        self.suppliers = self.store.payment_filters()['suppliers']
        self.by_code = {r['code']: r for r in self.suppliers}
        top = QHBoxLayout()
        self.date = QDateTimeEdit(QDateTime.currentDateTime()); self.date.setCalendarPopup(True); self.date.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.date.setMaximumDate(date.today()); top.addWidget(QLabel('지급일시')); top.addWidget(self.date)
        self.supplier = QComboBox(); self.supplier.addItem('공급사 선택', None)
        for p in self.suppliers:
            if p['active']: self.supplier.addItem(p['code']+' · '+p['name'], p['code'])
        self.supplier.setMinimumWidth(200); top.addWidget(self.supplier, 1)
        self.method = self.method_combo(False); top.addWidget(self.method)
        self.amount = GroupedNumberEdit('0'); self.amount.setMaximumWidth(150); top.addWidget(self.amount)
        self.input_button = action('입력 (F5)', self.prepare); top.addWidget(self.input_button); body.addLayout(top)
        tools = QHBoxLayout(); self.row_count = QSpinBox(); self.row_count.setRange(1, 500); self.row_count.setValue(1)
        tools.addWidget(QLabel('행 수')); tools.addWidget(self.row_count); tools.addWidget(action('행추가 (F6)', self.add_blanks))
        self.group = QComboBox(); self.group.addItem('공급사 그룹 선택', None)
        for g in self.store.payment_filters()['groups']: self.group.addItem(g['name'], g['id'])
        tools.addWidget(self.group); tools.addWidget(action('그룹 불러오기', self.add_group))
        tools.addWidget(action('엑셀 붙여넣기 (Ctrl+V)', self.paste)); tools.addWidget(action('선택행 삭제', self.remove_selected)); tools.addStretch()
        body.addLayout(tools)
        self.table = EntrySheet(0, len(self.KEYS), self)
        self.table.setHorizontalHeaderLabels(['공급사코드', '공급사명', '지급일시', '지급구분', '지급금액', '할인구분', '할인금액', '인출금계좌', '어음번호', '어음만기일', '메모'])
        self.table.setSelectionMode(self.table.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        for i, width in enumerate((100,160,165,120,120,110,110,170,120,120,200)): self.table.setColumnWidth(i, width)
        self.table.installEventFilter(self); self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu); body.addWidget(self.table, 1)
        self.message = QLabel('적용 예정 리스트를 입력하세요. 코드·금액 두 열을 엑셀에서 복사할 수 있습니다.')
        self.message.setWordWrap(True); body.addWidget(self.message)
        bottom = QHBoxLayout(); bottom.addStretch()
        self.confirm_button = action('확정 (F9)', self.confirm, True); self.confirm_button.setEnabled(False); bottom.addWidget(self.confirm_button); body.addLayout(bottom)
        for control in (self.date,self.supplier,self.method,self.amount):
            if isinstance(control,QDateTimeEdit):control.dateTimeChanged.connect(self.invalidate)
            elif isinstance(control,QComboBox):control.currentIndexChanged.connect(self.invalidate)
            else:control.textChanged.connect(self.invalidate)
        self.shortcuts = []
        for key, callback in (('F5', self.prepare), ('F6', self.add_blanks), ('F9', self.confirm)):
            shortcut = QShortcut(QKeySequence(key), self); shortcut.activated.connect(callback); self.shortcuts.append(shortcut)

    def method_combo(self, discount):
        box = QComboBox()
        for key, title in METHODS.items():
            if (key in DISCOUNTS) == discount: box.addItem(title, key)
        return box

    def invalidate(self, *_):
        if self._loading or self.saved_result or self._outcome_unknown: return
        self.preview = None; self.request_id = str(uuid4()); self.confirm_button.setEnabled(False)
        self.message.setText('입력이 바뀌었습니다. 입력(F5)으로 다시 검토하세요.')

    def add_row(self, code='', amount='0'):
        if len(self.rows) >= 500: raise ValueError('최대 500행까지 입력하세요.')
        row = dict(code=QLineEdit(code), name=QLabel(), datetime=QDateTimeEdit(self.date.dateTime()),
                   method=self.method_combo(False), amount=GroupedNumberEdit(amount), discount_method=self.method_combo(True),
                   discount=GroupedNumberEdit('0'), account=QLineEdit(), bill_number=QLineEdit(), bill_due=QLineEdit(self.date.date().toString('yyyy-MM-dd')), memo=QLineEdit())
        row['method'].setCurrentIndex(row['method'].findData(self.method.currentData()))
        row['datetime'].setCalendarPopup(True); row['datetime'].setDisplayFormat('yyyy-MM-dd HH:mm'); row['datetime'].setMaximumDate(date.today())
        i = len(self.rows); self.rows.append(row); self.table.setRowCount(len(self.rows))
        for c, key in enumerate(self.KEYS):
            field = row[key]; self.table.setCellWidget(i, c, field); field.installEventFilter(self)
            if isinstance(field, QLineEdit): field.textChanged.connect(self.invalidate)
            elif isinstance(field, QComboBox): field.currentIndexChanged.connect(self.invalidate)
            elif isinstance(field, QDateTimeEdit): field.dateTimeChanged.connect(self.invalidate)
        row['code'].textChanged.connect(lambda *_: self.resolve(row)); self.resolve(row); self.invalidate()
        return row

    def resolve(self, row):
        party = self.by_code.get(row['code'].text().strip())
        row['name'].setText(party['name'] if party else '공급사 미등록')

    def add_blanks(self):
        try:
            if len(self.rows)+self.row_count.value() > 500: raise ValueError('최대 500행까지 입력하세요.')
            for _ in range(self.row_count.value()): self.add_row()
        except ValueError as exc: self.message.setText(str(exc))

    def add_group(self):
        try:
            if self.group.currentData() is None: raise ValueError('공급사 그룹을 선택하세요.')
            metadata = self.store.payment_filters()
            members = {m['partner_id'] for m in metadata['memberships'] if m['group_id'] == self.group.currentData()}
            parties = [p for p in self.suppliers if p['id'] in members and p['active']]
            if len(self.rows)+len(parties) > 500: raise ValueError('최대 500행까지 입력하세요.')
            for p in parties: self.add_row(p['code'], self.amount.text())
        except (ValueError, PermissionError) as exc: self.message.setText(str(exc))

    def paste(self):
        try:
            rows = parse_supplier_clipboard(QApplication.clipboard().text())
            if len(self.rows)+len(rows) > 500: raise ValueError('최대 500행까지 입력하세요.')
            for i, (code, _) in enumerate(rows, 1):
                if code not in self.by_code or not self.by_code[code]['active']: raise ValueError(f'{i}행: 유효한 공급사코드가 아닙니다: {code}')
            for code, value in rows: self.add_row(code, value)
        except (ValueError, csv.Error) as exc: self.message.setText(str(exc))

    def eventFilter(self, field, event):
        if event.type() == QEvent.Type.MouseButtonPress and field is not self.table:
            row = next((i for i,r in enumerate(self.rows) if field in r.values()), None)
            if row is not None and not event.modifiers() and row not in self.selected_rows(): self.table.selectRow(row)
        if event.type() == QEvent.Type.ContextMenu and field is not self.table:
            self.context_menu(self.table.mapFromGlobal(event.globalPos())); return True
        if event.type() == QEvent.Type.KeyPress and event.matches(QKeySequence.StandardKey.Paste):
            value = QApplication.clipboard().text()
            if '\t' in value or '\n' in value: self.paste(); return True
        return super().eventFilter(field, event)

    def selected_rows(self):
        selected = {i.row() for i in self.table.selectedIndexes()}
        if not selected and self.table.currentRow() >= 0: selected.add(self.table.currentRow())
        return sorted(selected)

    def remove_selected(self):
        for i in reversed(self.selected_rows()): self.table.removeRow(i); self.rows.pop(i)
        self.invalidate()

    def plans(self):
        result = []
        for i, row in enumerate(self.rows, 1):
            try:
                party = self.by_code.get(row['code'].text().strip())
                if not party or not party['active']: raise ValueError('유효한 공급사코드를 입력하세요.')
                paid = public_input(row['amount'].text() or '0'); discount = public_input(row['discount'].text() or '0')
                components = {row['method'].currentData(): str(paid), row['discount_method'].currentData(): str(discount)}
                result.append(normalize_plan(dict(partner_id=party['id'], target=str(paid+discount), components=components,
                    datetime=row['datetime'].dateTime().toString('yyyy-MM-dd HH:mm:ss'), account=row['account'].text(), memo=row['memo'].text(),
                    bill=dict(number=row['bill_number'].text(), due_date=row['bill_due'].text(), bank=party.get('bank','')) if paid and row['method'].currentData()=='bill' else None)))
            except ValueError as exc: raise ValueError(f'{i}행: {exc}') from None
        return result

    def prepare(self):
        if self.saved_result or self._busy: return
        try:
            if self.supplier.currentData() and public_input(self.amount.text() or '0'):
                self.add_row(self.supplier.currentData(), self.amount.text()); self.amount.setText('0')
            self.preview = self.store.preview_supplier_payments(self.plans())
            self.confirm_button.setEnabled(True)
            self.message.setText(f"검토 완료 · {len(self.rows):,}행 · 지급+할인 {won(self.preview['amount'])}원. 확정(F9) 시 전체를 한 번에 저장합니다.")
        except (ValueError, PermissionError, ConnectionError) as exc:
            self.preview = None; self.confirm_button.setEnabled(False); self.message.setText(str(exc))

    def confirm(self):
        if self.saved_result or self._busy or not self.preview: return
        from .workflow_ui import _confirm
        if not self._outcome_unknown and not _confirm(self, '일괄결제 확정', f"{len(self.rows):,}행, 지급+할인 {won(self.preview['amount'])}원을 장부에 기록할까요? 실제 송금·카드 승인은 하지 않습니다."): return
        self._busy = True; self.confirm_button.setEnabled(False)
        try:
            self.saved_result = self.store.confirm_supplier_payments(self.plans(), self.preview['state'], self.request_id)
            from .navigation import mark_saved
            mark_saved(self); self.accept()
        except ConnectionError as exc:
            # A committed host response may have been lost. Preserve *exactly*
            # the original request and input until the operator retries it.
            from PySide6.QtWidgets import QPushButton
            self._outcome_unknown=True
            self.table.setEnabled(False)
            for field in (self.date,self.supplier,self.method,self.amount,self.row_count,self.group):field.setEnabled(False)
            for button in self.findChildren(QPushButton):
                if button is not self.confirm_button:button.setEnabled(False)
            self.confirm_button.setText('저장 결과 확인 · 재시도 (F9)');self.confirm_button.setEnabled(True)
            self.message.setText('저장 결과를 아직 확인하지 못했습니다. 입력을 보존했습니다. 연결 복구 후 같은 요청을 재시도하세요. 중복 지급은 등록하지 않습니다.\n'+str(exc))
        except (ValueError, PermissionError) as exc:
            self.message.setText(str(exc)); self.preview = None
        finally: self._busy = False

    def context_menu(self, point):
        from PySide6.QtWidgets import QInputDialog
        menu = QMenu(self); indexes = self.selected_rows()
        def change(key, caption):
            if not indexes: return
            if key in {'method','discount_method'}:
                choices = [title for k,title in METHODS.items() if (k in DISCOUNTS)==(key=='discount_method')]
                value, accepted = QInputDialog.getItem(self, caption, caption, choices, 0, False)
            else: value, accepted = QInputDialog.getText(self, caption, caption)
            if not accepted: return
            try:
                if key in {'amount','discount'}: value = str(public_input(value))
                if key=='datetime':
                    stamp=QDateTime.fromString(value,'yyyy-MM-dd HH:mm')
                    if not stamp.isValid() or stamp.date()>self.date.maximumDate(): raise ValueError('지급일시는 yyyy-MM-dd HH:mm 형식으로 입력하세요.')
                if key=='bill_due': date.fromisoformat(value)
                for i in indexes:
                    field = self.rows[i][key]
                    if isinstance(field,QComboBox): field.setCurrentIndex(field.findText(value))
                    elif key=='datetime': field.setDateTime(stamp)
                    else: field.setText(value)
            except ValueError as exc: self.message.setText(str(exc))
        for caption,key in (('선택행 지급구분 변경','method'),('선택행 지급금액 변경','amount'),('선택행 할인구분 변경','discount_method'),('선택행 할인금액 변경','discount'),('인출금계좌 변경','account'),('어음만기일 변경','bill_due'),('지급일시 변경','datetime')):
            entry=menu.addAction(caption,lambda checked=False,k=key,c=caption:change(k,c)); entry.setEnabled(bool(indexes))
        menu.addSeparator(); menu.addAction('선택행 삭제',self.remove_selected)
        self._context_menu=menu; menu.popup(self.table.mapToGlobal(point))

    def reject(self):
        from .navigation import confirm_dialog_exit
        if self._outcome_unknown and not self.saved_result:
            from .workflow_ui import _confirm
            self.message.setText('미확인 저장 요청이 있습니다. 연결을 복구한 뒤 저장 결과 확인 · 재시도(F9)를 눌러주세요.')
            if _confirm(self,'미확인 저장 요청 보존','결과를 확인하지 못했습니다. 이 창을 닫아도 지급을 다시 입력하지 마세요. 공유 연결 메뉴에서 원래 미확인 요청의 결과를 먼저 확인해야 합니다.\n미확인 요청을 보존하고 창을 닫을까요?'):
                super().reject()
            return
        if not self._busy and confirm_dialog_exit(self): super().reject()
