"""Synthetic, isolated revision proof run by the actual packaged executable."""
from datetime import date
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from .store import Store
from .workflow_ui import TradeDialog


def verify(app, parent, directory, capture):
    store = Store(directory/'isolated-purchase-revision-proof.db')
    host = QMainWindow(parent); host.store = store; host.notify = lambda *_: None
    dialogs = []
    try:
        store.setup_admin('owner', '수정 검증 관리자', 'Isolated-Revision-Proof-2026!')
        supplier = store.save_partner(dict(kind='supplier', name='수정 검증 공급사'))
        product = store.save_product(dict(name='수정 검증 상품', base_unit='개', purchase_price=10, sale_price=20))
        today = date.today().isoformat()
        def post():
            return store.post_document(dict(kind='purchase', date=today, partner_id=supplier,
                                            lines=[dict(product_id=product, qty=10, unit_price=10)]))
        identifier = post(); store.add_payment(identifier, 30, today, 'card', '격리 수기 결제')
        original = store.document(identifier)
        dialog = TradeDialog(host, 'purchase', identifier); dialogs.append(dialog)
        capture('-purchase-revision', dialog)
        assert dialog.amending and dialog.post_button.isEnabled(), (dialog.amend_context, dialog.readonly, host.isEnabled(), parent.isEnabled())
        dialog.line_rows[0]['qty'].setText('12.5'); dialog.revision_reason.setText('입고 수량 확인')
        confirmations = []
        def confirm():
            box = QApplication.activeModalWidget()
            assert isinstance(box, QMessageBox) and '확정 매입전표 수정' in box.windowTitle()
            confirmations.append(True); box.button(QMessageBox.StandardButton.Yes).click()
        QTimer.singleShot(0, dialog, confirm); dialog.post_button.click(); app.processEvents()
        changed = store.document(identifier)
        assert confirmations and changed['number'] == original['number'] and changed['total'] == 125, (confirmations, changed['total'], dialog.revision_reason.text(), dialog.post_button.isEnabled())
        assert changed['balance'] == 95 and changed['payments'] == original['payments']
        dialog = TradeDialog(host, 'purchase', identifier); dialogs.append(dialog)
        dialog.detail_tabs.setCurrentWidget(dialog.revision_grid)
        capture('-purchase-revision-history', dialog)
        assert dialog.revision_grid.rowCount() == 1
        # This next voucher is latest stock movement and has no payments.
        zero_id = post(); zero = TradeDialog(host, 'purchase', zero_id); dialogs.append(zero)
        zero.show(); app.processEvents()
        for row in list(zero.line_rows): zero.remove_line(row)
        zero.revision_reason.setText('전 품목 삭제 후 원번호 보존')
        QTimer.singleShot(0, zero, confirm); zero.post_button.click(); app.processEvents()
        saved = store.document(zero_id)
        assert saved['status'] == 'posted' and not saved['total'] and not saved['lines']
        empty = TradeDialog(host, 'purchase', zero_id); dialogs.append(empty)
        capture('-purchase-zero-voucher', empty)
        print('PASS purchase revisions: real saved-form editing, retained number and card payment, audit history, zero-line posted voucher', flush=True)
    finally:
        for dialog in dialogs: dialog.close(); dialog.deleteLater()
        app.processEvents(); host.close(); host.deleteLater(); store.close()
