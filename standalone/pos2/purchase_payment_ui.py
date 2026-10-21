"""Payment management opened directly over a posted purchase document."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QTabWidget, QVBoxLayout,QWidget)

from .currency import public_input as money
from .permissions import can_action
from .widgets import DataGrid, FormDialog, action, date_field, won
from .workflow_ui import _confirm, _date, _warn

from .payment_finance import METHODS,DISCOUNTS


class PurchasePaymentDialog(QDialog):
    menu_key = 'payments'
    read_permissions = ('trade',)

    def __init__(self, window, document_id=None, parent=None, partner_id=None):
        super().__init__(parent or window)
        self.window, self.store, self.document_id = window, window.store, document_id
        self.partner_id=partner_id
        self.snapshot = None
        self.saved_id = None
        self.changed = False
        self._saving = False
        self._fixed_query_header = False
        self._sy_no_home_button = True
        self.setWindowTitle('외상매입 결제')
        self.resize(1050, 820)
        self.setMinimumSize(850, 610)
        body = QVBoxLayout(self)
        body.setSpacing(8)
        info = QGroupBox('거래처 정보')
        grid = QGridLayout(info)
        self.info = {}
        for row, entries in enumerate(((('공급사', 'supplier'), ('은행', 'bank')),
                (('매입전표', 'number'), ('예금주', 'account_holder')),
                (('담당자', 'user'), ('입금계좌', 'account')))):
            for column, (label, key) in enumerate(entries):
                field = QLineEdit()
                field.setReadOnly(True)
                field.setAccessibleName(label)
                self.info[key] = field
                grid.addWidget(QLabel(label), row, column*2)
                grid.addWidget(field, row, column*2+1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        body.addWidget(info)
        panels = QHBoxLayout()
        target = QGroupBox('결제 대상 · 할인')
        form = QFormLayout(target)
        self.figures = {}
        self.figure_captions={}
        for key, label in (('total', '매입금액'), ('cash_paid', '기결제금액'),
                ('document_balance', '전표 미지급액'), ('balance', '공급사 전체 잔액'), ('cap', '이번 결제 가능액')):
            field = QLabel('0.00')
            field.setAlignment(Qt.AlignmentFlag.AlignRight)
            if key in {'document_balance', 'cap'}:
                field.setStyleSheet('font-weight:600;color:#9A423D;')
            self.figures[key] = field
            form.addRow(label, field)
            self.figure_captions[key]=form.labelForField(field)
        self.discounts={}
        for method in ('dc','rebate','coupon','other_discount'):
            field=QLineEdit('0');field.setAlignment(Qt.AlignmentFlag.AlignRight)
            field.setAccessibleName(METHODS[method]+' 할인액');self.discounts[method]=field
            form.addRow(METHODS[method],field);field.textChanged.connect(self.recalculate)
        self.discount_total=QLabel('0');self.settlement_total=QLabel('0')
        form.addRow('할인 소계',self.discount_total);form.addRow('결제 총합계',self.settlement_total)
        rates=QHBoxLayout();self.dc_rate=QLineEdit('0');self.dc_rate.setMaximumWidth(65)
        rates.addWidget(self.dc_rate);rates.addWidget(QLabel('%'));rates.addWidget(action('D/C율 적용',self.apply_dc_rate));form.addRow('조회 가능액 기준',rates)
        panels.addWidget(target, 1)
        inputs = QGroupBox('지급액 입력')
        form = QFormLayout(inputs)
        self.date = date_field()
        self.date.setMaximumDate(self.date.date())
        form.addRow('결제일', self.date)
        self.components = {}
        for method in ('transfer','card','cash','bill'):
            caption=METHODS[method]
            field = QLineEdit('0')
            field.setAlignment(Qt.AlignmentFlag.AlignRight)
            field.setAccessibleName(caption+' 지급액')
            self.components[method] = field
            form.addRow(caption, field)
            field.textChanged.connect(self.recalculate)
        self.bill_number=QLineEdit();self.bill_number.setPlaceholderText('어음 입력 시 필수 · 중복번호 불가')
        self.bill_due=date_field();self.bill_bank=QLineEdit()
        form.addRow('어음번호',self.bill_number);form.addRow('어음 만기일',self.bill_due);form.addRow('어음 은행',self.bill_bank)
        self.bill_number.setMaxLength(80);self.bill_bank.setMaxLength(100)
        self.paid_total = QLabel('0.00')
        self.remaining = QLabel('0.00')
        for label in (self.paid_total, self.remaining):
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.paid_total.setStyleSheet('font-weight:600;color:#24538D;')
        form.addRow('지급 합계 (어음 포함)', self.paid_total)
        form.addRow('결제 후 전표 잔액', self.remaining)
        panels.addWidget(inputs, 1)
        body.addLayout(panels)
        memo_row = QHBoxLayout()
        memo_row.addWidget(QLabel('결제 메모'))
        self.memo = QLineEdit()
        self.memo.setMaxLength(300)
        self.memo.setPlaceholderText('실제 지급한 내역을 기록합니다. 송금·카드 승인은 하지 않습니다.')
        memo_row.addWidget(self.memo, 1)
        body.addLayout(memo_row)
        self.tabs = QTabWidget()
        self.items_grid = DataGrid(['상품명', '규격', '수량', '단위', '매입단가', '매입금액'])
        self.payments_grid = DataGrid(['번호', '결제일', '금액', '결제방법', '담당자', '상태', '메모'])
        for grid in (self.items_grid, self.payments_grid):
            grid.menu_key = 'payments'
            grid.read_permissions = ('trade',)
        self.tabs.addTab(self.items_grid, '매입기록 · 품목')
        self.tabs.addTab(self.payments_grid, '결제 이력')
        body.addWidget(self.tabs, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        body.addWidget(self.error)
        controls = QHBoxLayout()
        self.refresh_button = action('잔액 다시 조회', lambda: self.refresh(True))
        self.edit_button = action('선택 결제 수정', self.edit_payment)
        self.void_button = action('선택 결제 취소', self.void_payment)
        for button in (self.refresh_button, self.edit_button, self.void_button):
            controls.addWidget(button)
        controls.addStretch()
        body.addLayout(controls)
        self._sy_pinned_footer=QWidget(self)
        footer=QHBoxLayout(self._sy_pinned_footer);footer.setContentsMargins(8,6,8,6);footer.addStretch()
        self.save_button = action('결제처리', self.save, True)
        self.save_button.setAutoDefault(False)
        self._sy_close_button = action('닫기', self.reject)
        footer.addWidget(self.save_button)
        footer.addWidget(self._sy_close_button)
        body.addWidget(self._sy_pinned_footer)
        self.date.dateChanged.connect(lambda *_: self.refresh())
        self.tabs.currentChanged.connect(self.update_controls)
        self.payments_grid.itemSelectionChanged.connect(self.update_controls)
        self.payments_grid.itemDoubleClicked.connect(self.edit_payment)
        self.refresh(True)

    def apply_dc_rate(self):
        if not self.snapshot:return
        try:
            from decimal import ROUND_HALF_UP
            rate=Decimal(self.dc_rate.text())
            if not rate.is_finite() or not 0<=rate<=100:raise ValueError('D/C율은 0~100%로 입력하세요.')
            discount=(self.snapshot['cap']*rate/100).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            self.discounts['dc'].setText(str(discount))
            # Do not silently alter other payment components.
        except (ValueError,ArithmeticError) as exc:self.error.setText(str(exc))

    def reject(self):
        from .navigation import confirm_dialog_exit
        if confirm_dialog_exit(self):
            super().reject()

    def refresh(self, reset=False):
        try:
            if self.document_id is not None:
                self.snapshot = self.store.purchase_payment_context(self.document_id, _date(self.date))
                self.partner_id=self.snapshot['partner']['id']
            else:self.snapshot=self.store.payment_context(self.partner_id,_date(self.date))
            self.finance_snapshot=self.store.payment_context(self.partner_id,_date(self.date),self.document_id)
            data, document = self.snapshot, self.snapshot['document']
            party = data['partner']
            document=document or dict(number='전체 미지급 · 초기외상 → 오래된 전표순',total=data['as_of'],cash_paid=0,balance=data['cap'],lines=[],payments=[])
            if self.document_id is None:
                self.figure_captions['total'].setText('조회일 잔액')
                for key in ('cash_paid','document_balance'):
                    self.figures[key].hide();self.figure_captions[key].hide()
            values = dict(supplier=party['code']+' · '+party['name'], number=document['number'],
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
                method = party.get('settlement_method', 'cash')
                for key, field in self.components.items():
                    field.setText(str(data['cap'] if key == method else 0))
                for field in self.discounts.values():field.setText('0')
            if self.document_id is None:
                self.items_grid.setHorizontalHeaderLabels(['배분 대상','거래일','미지급액','단위','단가','이번 지급'])
                items=[]
                if data['opening']:items.append(['초기 외상',party['opening_date'],data['opening'],'','',''])
                items.extend([r['number'],r['date'],r['balance'],'','',''] for r in data['documents'])
                self.items_grid.fill(items)
                payments=self.store.supplier_payment_history(_date(self.date),_date(self.date),self.partner_id)
                self.payments_grid.fill([[r['id'],r['date'],r['amount'],METHODS.get(r['method'],r['method']),r['user_name'],'취소' if r['voided'] else '유효',r['memo']] for r in payments],payments)
            self.recalculate()
            self.update_controls()
            if reset and self.changed:
                from .navigation import mark_saved
                mark_saved(self)
        except (ValueError, PermissionError) as exc:
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
        if not self.snapshot:
            return
        try:
            paid = sum((money(field.text() or '0') for field in self.components.values()), Decimal(0))
            discount=sum((money(field.text() or '0') for field in self.discounts.values()),Decimal(0));total=paid+discount
            self.paid_total.setText(won(paid)+' 원');self.discount_total.setText(won(discount)+' 원');self.settlement_total.setText(won(total)+' 원')
            self.remaining.setText(won((self.snapshot.get('document') or {'balance':self.snapshot['cap']})['balance']-total)+' 원')
            valid = 0 < total <= self.snapshot['cap']
            self.error.setText('수기 장부 기록입니다. 할인은 현금 지급이 아니며, 어음 지급은 별도 만기 장부에서 기록합니다.' if valid else
                '지급 합계를 결제 가능액 이내로 입력하세요.' if self.snapshot['cap'] else '추가 결제 가능한 잔액이 없습니다. 기존 결제 이력을 확인하세요.')
            self.save_button.setEnabled(valid and not self._saving and can_action(self.store.actor, 'payments', 'create'))
        except ValueError as exc:
            self.error.setText(str(exc))
            self.save_button.setEnabled(False)

    def update_controls(self, *_):
        row = self.payments_grid.selected() if self.tabs.currentIndex() == 1 else None
        eligible = bool(self.document_id is not None and self.snapshot and row and not row['voided'] and not row.get('supplier_settlement_id')
            and row['date'] == date.today().isoformat())
        can_delete = can_action(self.store.actor, 'payments', 'delete')
        self.void_button.setEnabled(eligible and can_delete)
        self.edit_button.setEnabled(eligible and row['method'] in {'cash','transfer','card'} and can_delete and can_action(self.store.actor, 'payments', 'create'))
        note = '여러 전표에 배분한 공급사 묶음결제는 매입결제에서 전체 배분을 확인한 뒤 수정·취소하세요.' if row and (self.document_id is None or row.get('supplier_settlement_id')) else '취소되지 않은 당일 결제만 수정·취소할 수 있습니다. 어음·할인은 취소 후 다시 등록합니다.'
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
            detail = ' · '.join(METHODS[k]+' '+won(v)+'원' for k, v in values.items() if v)
            if not _confirm(self, '매입 결제 등록', f"{self.snapshot['partner']['name']}\n{detail}\n결제 총합계 {won(total)}원을 기록할까요?\n어음은 발행 부채로 남고, 할인은 현금 지급에 포함되지 않습니다.\n실제 송금이나 카드 승인은 하지 않습니다."):
                return
            self._saving = True
            attempted = True
            self.save_button.setEnabled(False)
            if self.document_id is not None and not any(values[k] for k in DISCOUNTS|{'bill'}):
                result = self.store.add_purchase_payments(self.document_id, {k:v for k,v in values.items() if k in {'cash','transfer','card'}}, _date(self.date), self.memo.text(), self.snapshot['state'])
                self.saved_id = result['payment_ids'][0]
            else:
                bill=dict(number=self.bill_number.text(),due_date=_date(self.bill_due),bank=self.bill_bank.text()) if values['bill'] else None
                result=self.store.register_supplier_payment(self.partner_id,values,_date(self.date),self.memo.text(),self.finance_snapshot['state'],self.document_id,bill)
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
        if not row or row['voided'] or row['date'] != date.today().isoformat():
            raise ValueError('결제 이력에서 취소되지 않은 당일 결제를 선택하세요.')
        if row['supplier_settlement_id']:
            raise ValueError('공급사 묶음결제는 기존 결제관리에서 전체 배분을 확인하세요.')
        return row

    def edit_payment(self, *_):
        try:
            row = self.selected_payment()
            dialog = FormDialog('매입 결제 수정 · 원래 이력 보존', self)
            value = dialog.field('amount', '결제금액', str(row['amount']))
            method = dialog.combo('method', '결제방법', [(v, k) for k, v in METHODS.items()])
            method.setCurrentIndex(method.findData(row['method']))
            memo = dialog.field('memo', '메모', row['memo'])
            reason = dialog.field('reason', '수정 사유 *')
            expected = {key: row[key] for key in ('date', 'amount', 'method', 'memo')}
            def apply():
                try:
                    self.store.replace_supplier_payment('payment', row['id'], value.text(), method.currentData(), memo.text(), reason.text(), expected)
                    self.changed = True
                    dialog.accept()
                except (ValueError, PermissionError) as exc:dialog.error(exc)
            dialog.finish(apply)
            if dialog.exec():self.refresh(True)
        except (ValueError, PermissionError) as exc:_warn(self, exc)

    def void_payment(self):
        try:
            row = self.selected_payment()
            reason, accepted = QInputDialog.getText(self, '매입 결제 취소', '취소 사유 (이력 보존)')
            if accepted and _confirm(self, '매입 결제 취소', f"{won(row['amount'])}원 결제 기록을 취소하고 잔액을 복원할까요?\n실제 송금·카드 승인을 취소하지는 않습니다."):
                self.store.void_supplier_payment(row['id'], reason)
                self.changed = True
                self.refresh(True)
        except (ValueError, PermissionError) as exc:_warn(self, exc)


def open_payment(window, document_id, parent=None):
    """One guarded route shared by the purchasing list and document footer."""
    if not window.verify_payment_entry():
        return False
    dialog = PurchasePaymentDialog(window, document_id, parent)
    dialog.exec()
    return dialog.changed
