"""Keep the familiar voucher layout while distinguishing audited revisions."""
from decimal import InvalidOperation, Decimal
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QPushButton
from .widgets import DataGrid, reference_grid


def configure_revision(trade):
    context = trade.amend_context
    trade.revision_grid = DataGrid(['수정일시', '수정자', '수정 사유', '변경 전 매입일', '변경 후 매입일', '변경 전 합계', '변경 후 합계'])
    reference_grid(trade.revision_grid)
    refresh_revision_history(trade)
    trade.detail_tabs.addTab(trade.revision_grid, '수정 이력')
    if not trade.amending:
        trade.explanation.setText(context['reason'] or '다른 작업에서 변경된 전표입니다. 닫고 최신 전표를 다시 여세요.')
        trade.explanation.show()
        return
    trade.draft_button.hide()
    trade.shortcut_apply.setEnabled(False)
    trade.paid.setReadOnly(True)
    trade.method.setEnabled(False)
    trade.date.setMinimumDate(QDate.fromString(context['minimum_date'], 'yyyy-MM-dd'))
    trade.date.setMaximumDate(QDate.fromString(context['maximum_date'], 'yyyy-MM-dd'))
    trade.post_button.setToolTip('기존 전표번호·결제 기록을 유지하고 변경 전후와 수정 사유를 함께 저장합니다.\n단축키: Alt+S')
    trade.explanation.setText('확정 매입 수정 · 달력상 3개월 이내 · 원번호/결제/변경 전후 보존 · 수정 사유 필수'
                              + ('\n'+context['stock_reason'] if not context['stock_editable'] else ''))
    trade.explanation.show()
    if not context['stock_editable']:
        for field in (trade.date, trade.partner, trade.pick_button, trade.member, trade.scan, trade.add_button,
                      trade.search_button, trade.quote_button, trade.table, trade.new_product_button, trade.catalog_button,
                      trade.batch_button, trade.edit_line_button, trade.remove_line_button):
            field.setEnabled(False)
        for shortcut in (trade.shortcut_product, trade.shortcut_date, trade.shortcut_delete,
                         trade.shortcut_supplier, trade.shortcut_edit, trade.shortcut_new_product):
            shortcut.setEnabled(False)
        for shortcut in trade.purchase_shortcuts:
            if shortcut.key().toString() in {'Alt+Up', 'Alt+Down', 'Ctrl+I'}: shortcut.setEnabled(False)
        for button in trade.findChildren(QPushButton):
            if button.text() in {'위로', '아래로'}: button.setEnabled(False)
    trade._purchase_revision_initial = trade.payload()


def refresh_revision_history(trade):
    rows = trade.store.purchase_revisions(trade.record['id'])
    trade.revision_grid.fill([[r['at'], r['user_name'], r['reason'], r['before']['document']['date'],
                              r['after']['document']['date'], Decimal(str(r['before']['document']['total'])),
                              Decimal(str(r['after']['document']['total']))] for r in rows], rows)


def save_revision(trade, post, close):
    from .workflow_ui import _confirm, _warn
    if not post:
        return _warn(trade, '확정 전표는 초안으로 되돌리지 않습니다. 수정 사유를 입력하고 저장하세요.')
    try:
        reason = trade.revision_reason.text().strip()
        if not reason: raise ValueError('수정 사유를 입력하세요.')
        if not _confirm(trade, '확정 매입전표 수정', '기존 결제는 유지하고 전표·재고·공급사 잔액과 수정 이력을 함께 반영할까요?'):
            return
        payload = trade.payload()
        payload['_expected_token'] = trade.record['_edit_token']
        changes = trade.check_catalog_prices() if trade.amend_context['stock_editable'] else []
        if changes is None: return
        payload['catalog_updates'] = changes
        trade.saved_id = trade.store.revise_purchase(trade.record['id'], payload, trade.amend_context['state'], reason)
        from .navigation import mark_saved
        mark_saved(trade)
        if close: trade.accept()
        else:
            trade.record = trade.store.document(trade.saved_id)
            trade.amend_context = trade.store.purchase_edit_context(trade.saved_id)
            trade.revision_reason.clear()
            refresh_revision_history(trade)
            trade._purchase_revision_initial = trade.payload()
            mark_saved(trade)
    except (ValueError, PermissionError, InvalidOperation) as exc:
        _warn(trade, exc)
