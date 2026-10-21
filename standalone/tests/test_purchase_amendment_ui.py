from decimal import Decimal
import os
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMainWindow
from test_purchase_amendments import shop, TODAY, payload, save
from pos2.workflow_ui import TradeDialog


@pytest.fixture
def desktop(shop, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from pos2.popup_policy import install_popup_policy
    install_popup_policy(app)
    window = QMainWindow(); window.store = shop[0]; window.notify = lambda *_: None
    warnings = []
    monkeypatch.setattr('pos2.workflow_ui._warn', lambda _, error: warnings.append(str(error)))
    monkeypatch.setattr('pos2.workflow_ui._confirm', lambda *_: True)
    yield app, window, warnings
    for widget in app.topLevelWidgets(): widget.close(); widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()


def test_posted_purchase_edit_save_keeps_identity_and_history(shop, desktop, monkeypatch):
    from PySide6.QtCore import QDate
    # A connected PC's own clock must not silently clamp the host's trade date.
    class HostCalendar:
        fromString = staticmethod(QDate.fromString)
    monkeypatch.setattr('pos2.purchase_amendment_ui.QDate', HostCalendar)
    s, _, _, identifier = shop; app, window, warnings = desktop
    trade = TradeDialog(window, 'purchase', identifier); trade.show(); app.processEvents()
    trade.check_catalog_prices = lambda: []
    assert trade.amending and not trade.readonly
    assert trade.date.maximumDate().toString('yyyy-MM-dd') == trade.amend_context['maximum_date']
    assert trade.post_button.isVisible() and not trade.draft_button.isVisible()
    assert trade.revision_reason.isVisible() and trade.explanation.isVisible()
    trade.resize(1000, 600); app.processEvents()
    assert trade._sy_pinned_footer.isAncestorOf(trade.revision_reason)
    assert trade.rect().contains(trade.revision_reason.mapTo(trade, trade.revision_reason.rect().bottomRight()))
    assert trade.payload()['paid'] == '0' and trade.paid.isReadOnly()
    assert trade.payload()['lines'][0]['line_id'] == s.document(identifier)['lines'][0]['id']
    trade.line_rows[0]['qty'].setText('12.5'); trade.save(True, False)
    assert warnings == ['수정 사유를 입력하세요.'] and s.document(identifier)['total'] == 100
    warnings.clear(); trade.revision_reason.setText('실제 입고 수량 확인'); trade.save(True, False)
    assert not warnings and trade.isVisible() and trade.saved_id == identifier
    assert s.document(identifier)['total'] == 125 and trade.revision_grid.rowCount() == 1
    assert not trade.revision_reason.text()
    captures = os.environ.get('SY_TEST_CAPTURE_DIR')
    if captures:
        target = Path(captures); target.mkdir(parents=True, exist_ok=True)
        trade.grab().save(str(target/'rc35-purchase-revision.png'))
        trade.detail_tabs.setCurrentWidget(trade.revision_grid); app.processEvents()
        trade.grab().save(str(target/'rc35-purchase-revision-history.png'))


def test_revision_cannot_be_saved_as_draft_or_pay_unsaved_changes(shop, desktop, monkeypatch):
    s, _, _, identifier = shop; _, window, warnings = desktop
    trade = TradeDialog(window, 'purchase', identifier)
    trade.save(False)
    assert '초안으로 되돌리지' in warnings[-1] and s.document(identifier)['status'] == 'posted'
    monkeypatch.setattr('pos2.purchase_payment_ui.open_payment', lambda *_: (_ for _ in ()).throw(AssertionError('Must not open with unsaved changes')))
    trade.line_rows[0]['qty'].setText('12'); trade.payment_input()
    assert '먼저 저장' in warnings[-1] and not s.purchase_revisions(identifier)


def test_after_sale_only_memo_and_staff_edit_not_stock_shortcuts(shop, desktop):
    s, _, product, identifier = shop; app, window, warnings = desktop
    customer = s.save_partner(dict(kind='customer', name='판매처'))
    s.post_document(dict(kind='sale', date=TODAY, partner_id=customer, lines=[dict(product_id=product, qty=1, unit_price=20)]))
    trade = TradeDialog(window, 'purchase', identifier); trade.show(); app.processEvents()
    assert trade.amending and not trade.table.isEnabled() and not trade.date.isEnabled()
    assert not trade.shortcut_product.isEnabled() and not trade.shortcut_delete.isEnabled()
    assert trade.memo.isEnabled() and trade.entry_staff.isEnabled()
    trade.check_catalog_prices = lambda: []
    trade.memo.setText('품목 변경 없이 담당 확인'); trade.revision_reason.setText('메모 보완')
    trade.save(True)
    assert not warnings and s.document(identifier)['memo'] == '품목 변경 없이 담당 확인'


def test_zero_voucher_reopen_is_editable_and_shows_revision(shop, desktop):
    s, _, _, identifier = shop; _, window, _ = desktop
    data = payload(s, identifier); data['lines'] = []; save(s, identifier, data)
    trade = TradeDialog(window, 'purchase', identifier)
    assert trade.amending and trade.revision_grid.rowCount() == 1
    assert trade.payload()['lines'] == [] and trade.record['total'] == 0


def test_payment_updates_revision_snapshot_only_when_no_unsaved_changes(shop, desktop, monkeypatch):
    s, _, _, identifier = shop; _, window, warnings = desktop
    trade = TradeDialog(window, 'purchase', identifier); previous = trade.amend_context['state']
    def pay(*_):
        s.add_payment(identifier, 10, TODAY, 'card'); return True
    monkeypatch.setattr('pos2.purchase_payment_ui.open_payment', pay)
    trade.payment_input()
    assert not warnings and trade.amend_context['state'] != previous
    assert trade.payload()['paid'] == '0' and Decimal(trade.paid.text()) == 10
    trade.check_catalog_prices = lambda: []
    trade.line_rows[0]['qty'].setText('12'); trade.revision_reason.setText('결제 후 수량 확인')
    trade.save(True)
    assert not warnings and s.document(identifier)['balance'] == 110


def test_revision_output_distinguishes_saved_and_unsaved_and_zero_voucher(shop, desktop):
    from pos2.purchase_output import purchase_record, purchase_workbook
    s, _, product, identifier = shop; _, window, _ = desktop
    s.save_product(dict(name='새 상품명', tax_mode='taxable'), product)
    trade = TradeDialog(window, 'purchase', identifier)
    record = purchase_record(trade)
    assert record['status'] == 'posted' and record['lines'][0]['product_name'] == '수정 상품'
    assert record['lines'][0]['tax_mode'] == 'exempt'
    trade.line_rows[0]['qty'].setText('12')
    record = purchase_record(trade)
    assert record['status'] == 'draft' and '미저장 수정안' in record['number']
    assert s.document(identifier)['total'] == 100
    data = payload(s, identifier); data['lines'] = []; save(s, identifier, data)
    empty = TradeDialog(window, 'purchase', identifier)
    record = purchase_record(empty)
    assert record['total'] == 0 and record['status'] == 'posted'
    assert purchase_workbook(record).active.max_row > 1
