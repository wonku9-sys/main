"""Payment management opened directly over a posted purchase document."""
from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeySequence, QShortcut, QIcon
from PySide6.QtWidgets import (QDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QTabWidget, QVBoxLayout,QWidget,QComboBox)

from .currency import public_input as money
from .permissions import can_action
from .widgets import DataGrid, FormDialog, action, date_field, won
from .workflow_ui import _confirm, _date, _warn

from .payment_finance import METHODS,DISCOUNTS
from .number_edit import GroupedNumberEdit


class PurchasePaymentDialog(QDialog):
    menu_key = 'payments'
    read_permissions = ('trade',)

    def __init__(self, window, document_id=None, parent=None, partner_id=None, pending=None, plan=None, editing=None):
        super().__init__(parent or window)
        self.window, self.store, self.document_id = window, window.store, document_id
        self.partner_id, self.pending, self.plan, self.editing = partner_id, pending, plan, editing
        if editing:self.partner_id=editing['plan']['partner_id']
        self.snapshot = None
        self.saved_id = None
        self.changed = self._saving = self._target_explicit = False
        self._loading = True
        self._fixed_query_header = False
        self._sy_no_home_button = True
        self._reserved_function_keys = {'F5'}
        self.setWindowTitle('외상매입 결제')
        self.resize(1100, 700)
        self.setMinimumSize(850, 610)
        body = QVBoxLayout(self); body.setSpacing(6)
        info = QGroupBox('거래처정보'); grid = QGridLayout(info)
        self.info = {}
        entries = ((('거래처', 'supplier'), ('은행', 'bank')),
                   (('담당자 / 매입전표', 'number'), ('예금주', 'account_holder')),
                   (('현재잔액', 'current_balance'), ('입금계좌', 'account')))
        for row, items in enumerate(entries):
            for col, (caption, key) in enumerate(items):
                field = QLineEdit(); field.setReadOnly(True); field.setAccessibleName(caption)
                self.info[key] = field
                grid.addWidget(QLabel(caption), row, col*2); grid.addWidget(field, row, col*2+1)
        self.info['user'] = QLineEdit(self); self.info['user'].hide()
        grid.setColumnStretch(1, 1); grid.setColumnStretch(3, 1); body.addWidget(info)
        panels = QHBoxLayout()
        target = QGroupBox('결제대상'); form = QFormLayout(target)
        self.figures = {}; self.figure_captions = {}
        for key, caption in (('total', '매입금액'), ('cash_paid', '기결제금액'),
                ('document_balance', '전표 미지급액'), ('balance', '공급사 잔액'), ('cap', '조회잔액')):
            field = QLabel('0'); field.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.figures[key] = field; self.figure_captions[key] = QLabel(caption, target)
            if key == 'cap': form.addRow(self.figure_captions[key], field)
            else: field.hide(); self.figure_captions[key].hide()
        self.target_amount = GroupedNumberEdit('0'); self.target_amount.setAccessibleName('결제대상액')
        self.target_amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.payment_rate = QLineEdit('100'); self.payment_rate.setMaximumWidth(55)
        self.rate_button = action('적용', self.apply_payment_rate)
        rate = QHBoxLayout(); rate.addWidget(self.payment_rate); rate.addWidget(QLabel('%')); rate.addWidget(self.rate_button)
        line = QHBoxLayout(); line.addWidget(self.target_amount, 1); line.addWidget(QLabel('결제율')); line.addLayout(rate)
        form.addRow('결제대상액', line)
        self.discounts = {}
        self.dc_rate = QLineEdit('0'); self.dc_rate.setMaximumWidth(55)
        self.dc_button = action('적용', self.apply_dc_rate)
        self.rate_button.setIcon(QIcon());self.dc_button.setIcon(QIcon())
        for method in ('dc', 'rebate', 'coupon', 'other_discount'):
            field = GroupedNumberEdit('0'); field.setAlignment(Qt.AlignmentFlag.AlignRight)
            field.setAccessibleName(METHODS[method]+' 할인액'); self.discounts[method] = field
            if method == 'dc':
                row = QHBoxLayout(); row.addWidget(field, 1); row.addWidget(QLabel('결제DC율'))
                row.addWidget(self.dc_rate); row.addWidget(QLabel('%')); row.addWidget(self.dc_button)
                form.addRow('[할인] D/C', row)
            else: form.addRow(METHODS[method], field)
            field.textChanged.connect(self.recalculate)
        self.discount_total = QLabel('0'); self.payable_total = QLabel('0'); self.settlement_total = QLabel('0')
        form.addRow('할인소계', self.discount_total); form.addRow('지급할금액', self.payable_total)
        form.addRow('결제총합계', self.settlement_total)
        panels.addWidget(target, 1)
        inputs = QGroupBox('지급액입력'); form = QFormLayout(inputs)
        self.date = date_field(); self.date.setMaximumDate(self.date.date())
        self.hour = QComboBox(); self.minute = QComboBox()
        for n in range(24): self.hour.addItem(('오전' if n<12 else '오후')+f' {n%12 or 12:02d}시', n)
        for n in range(60): self.minute.addItem(f'{n:02d}분', n)
        clock = datetime.now(); self.hour.setCurrentIndex(clock.hour); self.minute.setCurrentIndex(clock.minute)
        row = QHBoxLayout(); row.addWidget(self.date); row.addWidget(self.hour); row.addWidget(self.minute)
        form.addRow('결제일시', row)
        self.account = QComboBox(); self.account.setEditable(True)
        self.account.setAccessibleName('인출금계좌'); self.account.addItem('--인출금계좌--', '')
        own = self.store.store_profile()
        if own.get('account'):
            value = ' · '.join(own.get(k, '') for k in ('bank', 'account', 'account_holder') if own.get(k))
            self.account.addItem(value, value)
        self.account.setToolTip('매장 계좌 또는 직접 입력한 인출계좌를 결제 이력에 보관합니다. 실제 송금은 하지 않습니다.')
        self.components = {}
        for method in ('transfer', 'card', 'cash', 'bill'):
            field = GroupedNumberEdit('0'); field.setAlignment(Qt.AlignmentFlag.AlignRight)
            field.setAccessibleName(METHODS[method]+' 지급액'); self.components[method] = field
            if method == 'transfer':
                row = QHBoxLayout(); row.addWidget(field, 1); row.addWidget(self.account, 2); form.addRow('[지급] 계좌이체', row)
            else: form.addRow(METHODS[method], field)
            field.textChanged.connect(self.recalculate)
        self.bill_fields = QWidget(); bill_form = QFormLayout(self.bill_fields); bill_form.setContentsMargins(0, 0, 0, 0)
        self.bill_number = QLineEdit(); self.bill_number.setMaxLength(80)
        self.bill_number.setPlaceholderText('어음번호 필수 · 기존 번호 재사용 불가')
        self.bill_due = date_field(); self.bill_bank = QLineEdit(); self.bill_bank.setMaxLength(100)
        bill_form.addRow('어음번호', self.bill_number); bill_form.addRow('만기일', self.bill_due); bill_form.addRow('어음 은행', self.bill_bank)
        form.addRow(self.bill_fields)
        self.paid_total = QLabel('0'); self.remaining = QLabel('0')
        form.addRow('실지급금액', self.paid_total); form.addRow('결제 후 전표 잔액', self.remaining)
        panels.addWidget(inputs, 1); body.addLayout(panels)
        for field in (self.discount_total, self.payable_total, self.settlement_total, self.paid_total, self.remaining):
            field.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.memo = QLineEdit(); self.memo.setMaxLength(300)
        self.memo.setAccessibleName('결제 메모')
        self.memo.setPlaceholderText('메모 · 실제 송금·카드 승인 없이 장부에 기록합니다. (최대 300자)')
        body.addWidget(self.memo)
        self.tabs = QTabWidget()
        self.items_grid = DataGrid(['상품명', '규격', '수량', '단위', '매입단가', '매입금액'])
        self.payments_grid = DataGrid(['번호', '결제일', '금액', '결제방법', '담당자', '상태', '메모'])
        for grid in (self.items_grid, self.payments_grid):
            grid.menu_key = 'payments'; grid.read_permissions = ('trade',)
        self.tabs.addTab(self.items_grid, '매입기록 · 품목'); self.tabs.addTab(self.payments_grid, '결제 이력')
        self.tabs.setMinimumHeight(130); self.tabs.hide(); body.addWidget(self.tabs, 1)
        self.error = QLabel(); self.error.setWordWrap(True); body.addWidget(self.error)
        self._sy_pinned_footer = QWidget(self)
        footer = QHBoxLayout(self._sy_pinned_footer); footer.setContentsMargins(0, 2, 0, 2)
        self.history_button = action('매입·결제 이력', self.toggle_history)
        self.refresh_button = action('잔액 재조회(F5)', lambda: self.refresh(True))
        self.edit_button = action('선택 결제 수정', self.edit_payment)
        self.void_button = action('전표삭제', self.void_payment)
        self.void_button.setToolTip('선택한 결제 기록만 취소합니다. 매입전표와 품목은 삭제하지 않습니다.')
        self.edit_button.hide()
        self.save_button = action('결제수정' if editing else '결제처리', self.save, True)
        self.save_button.setAutoDefault(False)
        self.cancel_button = action('취소', self.reject)
        self._sy_close_button = self.cancel_button
        for button in (self.history_button, self.refresh_button, self.edit_button, self.void_button): footer.addWidget(button)
        footer.addStretch(); footer.addWidget(self.save_button); footer.addWidget(self.cancel_button)
        body.addWidget(self._sy_pinned_footer)
        QShortcut(QKeySequence('F5'), self, activated=lambda: self.refresh(True))
        self.date.dateChanged.connect(lambda *_: self.refresh())
        self.target_amount.textChanged.connect(self.target_changed)
        self.tabs.currentChanged.connect(self.update_controls)
        self.payments_grid.itemSelectionChanged.connect(self.update_controls)
        self.payments_grid.itemDoubleClicked.connect(self.edit_payment)
        self._loading = False
        self.refresh(True)
        if plan: self.load_plan(plan)
        if editing:
            self.load_plan(editing['plan']);self.refresh()
            if not editing['editable']:
                for field in (self.date,self.hour,self.minute,self.target_amount,self.payment_rate,self.dc_rate,self.account,self.memo,self.bill_number,self.bill_due,self.bill_bank,*self.components.values(),*self.discounts.values(),self.rate_button,self.dc_button):field.setEnabled(False)

    def toggle_history(self):
        self.tabs.setVisible(not self.tabs.isVisible())
        self.edit_button.setVisible(self.tabs.isVisible())
        if self.tabs.isVisible(): self.resize(self.width(), max(self.height(), 850))

    def target_changed(self):
        if not self._loading: self._target_explicit = True
        self.recalculate()

    def load_plan(self, plan):
        self._loading = True
        stamp = datetime.strptime(plan['datetime'], '%Y-%m-%d %H:%M:%S')
        self.date.setDate(QDate(stamp.year, stamp.month, stamp.day))
        self.hour.setCurrentIndex(stamp.hour); self.minute.setCurrentIndex(stamp.minute)
        self.account.setCurrentText(plan['account'] or '--인출금계좌--')
        self.memo.setText(plan['memo'])
        for key, field in {**self.components, **self.discounts}.items(): field.setText(str(plan['components'].get(key, 0)))
        if plan['bill']:
            self.bill_number.setText(plan['bill']['number']); self.bill_bank.setText(plan['bill']['bank'])
            self.bill_due.setDate(QDate.fromString(plan['bill']['due_date'], 'yyyy-MM-dd'))
        self.target_amount.setText(str(plan['target']))
        self._target_explicit = True; self._loading = False; self.recalculate()

    def apply_payment_rate(self):
        if not self.snapshot: return
        try:
            rate = money(self.payment_rate.text())
            if rate > 100: raise ValueError('결제율은 0~100%로 입력하세요.')
            from decimal import ROUND_HALF_UP
            target = (self.snapshot['cap']*rate/100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.target_amount.setText(str(target)); self.fill_cash_remainder()
        except ValueError as exc: self.error.setText(str(exc))

    def fill_cash_remainder(self):
        try:
            target = money(self.target_amount.text())
            others = sum((money(f.text() or '0') for k, f in {**self.components, **self.discounts}.items() if k != 'cash'), Decimal(0))
            if others > target: raise ValueError('다른 지급액·할인이 결제대상액을 초과합니다.')
            self.components['cash'].setText(str(target-others))
        except ValueError as exc: self.error.setText(str(exc))

    def apply_dc_rate(self):
        if not self.snapshot:return
        try:
            from decimal import ROUND_HALF_UP
            rate=Decimal(self.dc_rate.text())
            if not rate.is_finite() or not 0<=rate<=100:raise ValueError('D/C율은 0~100%로 입력하세요.')
            discount=(money(self.target_amount.text())*rate/100).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            self._target_explicit=True
            self.discounts['dc'].setText(str(discount))
            self.fill_cash_remainder()
        except (ValueError,ArithmeticError) as exc:self.error.setText(str(exc))

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()

    def refresh(self, reset=False):
        if self._loading:return
        try:
            self._loading=True
            if self.pending is not None:
                self.store.require_menu('purchases');self.store.require_menu('payments')
                outstanding=self.store.supplier_outstanding(self.partner_id,_date(self.date))
                document=dict(number='저장 전 · 담당자 '+self.pending['staff'],total=self.pending['total'],cash_paid=Decimal(0),balance=self.pending['total'],lines=self.pending['lines'],payments=[])
                self.snapshot=dict(document=document,partner=outstanding['partner'],cap=self.pending['total'],balance=outstanding['balance'],user_name=self.store.actor['name'])
                if _date(self.date)<self.pending['date']:raise ValueError('결제일은 매입일보다 빠를 수 없습니다.')
            elif self.document_id is not None:
                self.snapshot = self.store.purchase_payment_context(self.document_id, _date(self.date))
                self.partner_id=self.snapshot['partner']['id']
            else:self.snapshot=self.store.payment_context(self.partner_id,_date(self.date))
            if self.pending is None:self.finance_snapshot=self.store.payment_context(self.partner_id,_date(self.date),self.document_id)
            if self.editing:
                fresh=self.store.purchase_payment_batch(self.editing['payment_ids'][0],self.editing.get('source_type','payment'))
                if fresh['state']!=self.editing['state']:raise ValueError('결제 이력이 바뀌었습니다. 창을 닫고 다시 선택하세요.')
                self.snapshot['cap']=fresh['cap']
            data, document = self.snapshot, self.snapshot['document']
            party = data['partner']
            document=document or dict(number='전체 미지급 · 초기외상 → 오래된 전표순',total=data['as_of'],cash_paid=0,balance=data['cap'],lines=[],payments=[])
            if self.document_id is None:
                self.figure_captions['total'].setText('조회일 잔액')
                for key in ('cash_paid','document_balance'):
                    self.figures[key].hide();self.figure_captions[key].hide()
            values = dict(supplier=party['code']+' · '+party['name'], number=data['user_name']+' / '+document['number'],current_balance=won(data['balance']),
                user=data['user_name'], bank=party['bank'], account=party['account'], account_holder=party['account_holder'])
            for key, field in self.info.items():
                field.setText(values[key])
            for key, field in self.figures.items():
                value = document['balance'] if key == 'document_balance' else document[key] if key in {'total', 'cash_paid'} else data[key]
                field.setText(won(value)+' 원')
            self.items_grid.fill([[r['product_name'], r.get('specification', ''), r['input_qty'],
                r['unit_name'], r['unit_price'], r['total']] for r in document['lines']], document['lines'])
            payments = document['payments']
            self.payments_grid.fill([[r['id'], r['date'], r['amount'], METHODS.get(r['method'], r['method']),
                r['user_name'], '취소' if r['voided'] else '공급사 묶음배분' if r['supplier_settlement_id'] else '유효',
                r['memo']] for r in payments], payments)
            if reset:
                self._target_explicit=False
                method = party.get('settlement_method', 'cash')
                for key, field in self.components.items():
                    field.setText(str(data['cap'] if key == method else 0))
                for field in self.discounts.values():field.setText('0')
            if self.document_id is None and self.pending is None:
                self.items_grid.setHorizontalHeaderLabels(['배분 대상','거래일','미지급액','단위','단가','이번 지급'])
                items=[]
                if data['opening']:items.append(['초기 외상',party['opening_date'],data['opening'],'','',''])
                items.extend([r['number'],r['date'],r['balance'],'','',''] for r in data['documents'])
                self.items_grid.fill(items)
                payments=self.store.supplier_payment_history(_date(self.date),_date(self.date),self.partner_id)
                self.payments_grid.fill([[r['id'],r['date'],r['amount'],METHODS.get(r['method'],r['method']),r['user_name'],'취소' if r['voided'] else '유효',r['memo']] for r in payments],payments)
            self._loading=False
            self.recalculate()
            self.update_controls()
            if reset and self.changed:
                from .navigation import mark_saved
                mark_saved(self)
        except (ValueError, PermissionError) as exc:
            self._loading=False
            self.snapshot = None
            self.save_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.void_button.setEnabled(False)
            self.items_grid.fill([])
            self.payments_grid.fill([])
            for field in self.info.values():field.clear()
            for field in self.figures.values():field.setText('—')
            self.error.setText(str(exc))

    def recalculate(self, *_):
        if self._loading or not self.snapshot:
            return
        try:
            paid = sum((money(field.text() or '0') for field in self.components.values()), Decimal(0))
            discount=sum((money(field.text() or '0') for field in self.discounts.values()),Decimal(0));total=paid+discount
            self.bill_fields.setVisible(money(self.components['bill'].text() or '0')>0)
            if not self._target_explicit:
                self.target_amount.blockSignals(True);self.target_amount.setText(str(total));self.target_amount.blockSignals(False)
            target=money(self.target_amount.text() or '0')
            self.payable_total.setText(won(target-discount)+' 원')
            self.paid_total.setText(won(paid)+' 원');self.discount_total.setText(won(discount)+' 원');self.settlement_total.setText(won(total)+' 원')
            self.remaining.setText(won((self.snapshot['cap'] if self.editing else (self.snapshot.get('document') or {'balance':self.snapshot['cap']})['balance'])-total)+' 원')
            closed=bool(self.pending is None and self.finance_snapshot.get('payment_closed'))
            valid = 0 < total <= self.snapshot['cap'] and total==target and not closed and (not self.editing or self.editing['editable'])
            self.error.setText('수기 장부 기록입니다. 할인은 현금 지급이 아니며, 어음 지급은 별도 만기 장부에서 기록합니다.' if valid else
                '실지급금액 + 할인소계가 결제대상액과 같아야 하며, 조회잔액을 초과할 수 없습니다.' if self.snapshot['cap'] else '추가 결제 가능한 잔액이 없습니다. 기존 결제 이력을 확인하세요.')
            self.save_button.setEnabled(valid and not self._saving and can_action(self.store.actor, 'payments', 'create'))
            if closed:self.error.setText(self.finance_snapshot['closed_through']+'까지 MIS 결제 월마감되어 수정·등록할 수 없습니다. 이력은 보존됩니다.')
            elif self.editing and not self.editing['editable']:self.error.setText(self.editing['edit_reason'])
        except ValueError as exc:
            self.error.setText(str(exc))
            self.save_button.setEnabled(False)

    def update_controls(self, *_):
        if self._loading:return
        row = self.payments_grid.selected() if self.tabs.currentIndex() == 1 else None
        eligible=False
        if self.snapshot and row and not row['voided']:
            try:
                source_type=row.get('type','payment');identifier=row['id']
                if row.get('supplier_settlement_id'):source_type='settlement';identifier=row['supplier_settlement_id']
                eligible=self.store.purchase_payment_batch(identifier,source_type)['editable']
            except (ValueError,PermissionError,ConnectionError):pass
        can_delete = can_action(self.store.actor, 'payments', 'delete')
        self.void_button.setEnabled((eligible or bool(self.editing and self.editing['editable'])) and can_delete or self.pending is not None and bool(self.plan))
        if self.pending is not None:self.void_button.setToolTip('아직 저장하지 않은 상세 결제 입력만 지웁니다. 장부·매입품목은 변경하지 않습니다.')
        self.edit_button.setEnabled(eligible and can_delete and can_action(self.store.actor, 'payments', 'create'))
        note = '선택한 결제 묶음을 수정·취소합니다. 매입전표는 삭제하지 않습니다. 마감 기간·지급 완료 어음은 변경할 수 없습니다.'
        self.edit_button.setToolTip(note)
        self.void_button.setToolTip(note)

    def save(self):
        if self.saved_id or self._saving or not self.snapshot:
            return
        attempted = False
        try:
            values = {key: money(field.text() or '0') for key, field in {**self.components,**self.discounts}.items()}
            total = sum(values.values())
            if not 0 < total <= self.snapshot['cap']:
                raise ValueError('결제금액을 입력해주시기 바랍니다.' if not total else '결제 가능 잔액 이내의 지급액을 입력하세요.')
            from .purchase_payment_plan import normalize_plan
            bill=dict(number=self.bill_number.text(),due_date=_date(self.bill_due),bank=self.bill_bank.text()) if values['bill'] else None
            plan=normalize_plan(dict(partner_id=self.partner_id,target=self.target_amount.text(),components=values,
                datetime=_date(self.date)+f' {self.hour.currentData():02d}:{self.minute.currentData():02d}:00',
                account='' if self.account.currentText()=='--인출금계좌--' else self.account.currentText(),memo=self.memo.text(),bill=bill))
            if self.pending is not None:
                if _date(self.date)<self.pending['date']:raise ValueError('결제일은 매입일보다 빠를 수 없습니다.')
                self.plan=plan;self.changed=True
                from .navigation import mark_saved
                mark_saved(self);self.accept();return
            detail = ' · '.join(METHODS[k]+' '+won(v)+'원' for k, v in values.items() if v)
            if not _confirm(self, '매입 결제 등록', f"{self.snapshot['partner']['name']}\n{detail}\n결제 총합계 {won(total)}원을 기록할까요?\n어음은 발행 부채로 남고, 할인은 현금 지급에 포함되지 않습니다.\n실제 송금이나 카드 승인은 하지 않습니다."):
                return
            self._saving = True
            attempted = True
            self.save_button.setEnabled(False)
            if self.editing:
                reason,ok=QInputDialog.getText(self,'결제수정','수정 사유 (원래 결제 이력은 보존됩니다.)')
                if not ok:
                    attempted=False;self._saving=False;self.recalculate();return
                result=self.store.replace_purchase_payment_batch(self.editing['payment_ids'][0],plan,self.editing['state'],reason,self.editing.get('source_type','payment'))
            else:
                result=self.store.register_supplier_payment(self.partner_id,values,_date(self.date),self.memo.text(),self.finance_snapshot['state'],self.document_id,bill,plan)
            self.saved_id=result['records'][0]['id']
            self.changed = True
            from .navigation import mark_saved
            mark_saved(self)
            self.accept()
        except (ValueError, PermissionError) as exc:
            self.error.setText(str(exc))
        finally:
            self._saving = False
            if attempted and not self.saved_id:self.recalculate_after_error()

    def recalculate_after_error(self):
        # Do not silently refresh the optimistic token after an error. The user
        # must explicitly inspect the changed balance and retry.
        self.save_button.setEnabled(False)

    def selected_payment(self):
        row = self.payments_grid.selected() if self.tabs.currentIndex() == 1 else None
        if not row or row['voided']:
            raise ValueError('결제 이력에서 취소되지 않은 결제를 선택하세요.')
        if row.get('supplier_settlement_id'):return dict(row,source_type='settlement',batch_id=row['supplier_settlement_id'])
        return dict(row,source_type=row.get('type','payment'),batch_id=row['id'])

    def edit_payment(self, *_):
        try:
            row = self.selected_payment()
            batch = self.store.purchase_payment_batch(row['batch_id'],row['source_type'])
            dialog = PurchasePaymentDialog(self.window, batch['document_id'], self, editing=batch)
            if dialog.exec() and dialog.changed:
                self.changed = True; self.refresh(True)
        except (ValueError, PermissionError) as exc: _warn(self, exc)

    def void_payment(self):
        try:
            if self.pending is not None:
                if _confirm(self,'상세 결제 입력 지우기','저장 전 결제 입력만 지울까요? 매입 상품은 유지됩니다.'):
                    self.plan=None;self.changed=True
                    from .navigation import mark_saved
                    mark_saved(self);self.accept()
                return
            row=None if self.editing else self.selected_payment()
            batch = self.editing or self.store.purchase_payment_batch(row['batch_id'],row['source_type'])
            reason, accepted = QInputDialog.getText(self, '결제전표 삭제 · 이력 보존', '취소 사유 (매입전표는 삭제하지 않습니다.)')
            if accepted and _confirm(self, '결제전표 취소', f"{won(money(batch['plan']['target']))}원 결제 묶음을 취소하고 잔액을 복원할까요?\\n매입전표·품목은 보존되며 실제 송금·카드 승인은 취소하지 않습니다."):
                self.store.void_purchase_payment_batch(batch['payment_ids'][0], batch['state'], reason,batch.get('source_type','payment'))
                self.changed = True
                if self.editing:
                    from .navigation import mark_saved
                    mark_saved(self); self.accept()
                else: self.refresh(True)
        except (ValueError, PermissionError) as exc: _warn(self, exc)


def open_payment(window, document_id, parent=None):
    """One guarded route shared by the purchasing list and document footer."""
    if not window.verify_payment_entry():
        return False
    dialog = PurchasePaymentDialog(window, document_id, parent)
    dialog.exec()
    return dialog.changed
