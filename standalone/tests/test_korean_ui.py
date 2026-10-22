"""Official Qt translations, real context actions and presentation-only returns."""
import gc
from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QDoubleSpinBox,
                              QLineEdit, QPlainTextEdit, QSpinBox, QTextEdit, QMainWindow)
from pos2.localization import install_korean_ui, korean_catalog_path
from pos2.korean_ui_smoke import menu_labels
from pos2.workflow_ui import KINDS, PurchaseJournalGrid, TradesPage
from pos2.store import Store


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    install_korean_ui(application)
    yield application
    for widget in application.topLevelWidgets():
        widget.close(); widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_translator_persists_and_is_installed_only_once(app):
    first = install_korean_ui(app)
    assert install_korean_ui(app) is first and korean_catalog_path().is_file()
    gc.collect()
    field = QLineEdit(); menu = field.createStandardContextMenu()
    assert {'복사', '붙여넣기', '모두 선택'} <= menu_labels(menu)
    menu.deleteLater(); field.deleteLater()


@pytest.mark.parametrize('cls', [QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit])
def test_actual_context_event_opens_korean_menu(app, cls):
    field = cls(); field.resize(280, 100); field.show(); app.processEvents()
    observed = []
    def inspect():
        menu = QApplication.activePopupWidget()
        if menu is not None:
            observed.append(menu_labels(menu)); menu.close()
    QTimer.singleShot(0, field, inspect)
    target = field.viewport() if isinstance(field, (QTextEdit, QPlainTextEdit)) else field
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(12, 12), target.mapToGlobal(QPoint(12, 12)))
    QApplication.sendEvent(target, event); app.processEvents()
    assert observed and {'잘라내기', '복사', '붙여넣기'} <= observed[0], observed
    assert not any(word in ' '.join(observed[0]) for word in ('Undo', 'Copy', 'Paste', 'Step', 'Select'))


def test_editable_combo_and_standard_copy_paste_keep_working(app):
    box = QComboBox(); box.setEditable(True); field = box.lineEdit()
    field.setText('선두0 001234'); field.selectAll()
    menu = field.createStandardContextMenu()
    next(a for a in menu.actions() if a.text().startswith('복사')).trigger()
    assert app.clipboard().text() == '선두0 001234'
    field.clear(); menu.deleteLater(); menu = field.createStandardContextMenu()
    next(a for a in menu.actions() if a.text().startswith('붙여넣기')).trigger()
    assert field.text() == '선두0 001234'
    menu.deleteLater(); box.deleteLater()


def test_frozen_catalog_uses_explicit_packaged_location(monkeypatch):
    import pos2.localization as localization
    monkeypatch.setattr(localization.sys, 'frozen', True, raising=False)
    assert korean_catalog_path() == Path(localization.__file__).with_name('translations')/'qtbase_ko.qm'


def test_zero_and_cancelled_returns_are_red_without_coloring_purchases_or_summary(app):
    grid = PurchaseJournalGrid(['No.', '구분', '유형', '코드', '공급사', '입고일시', '매입합계'])
    records = [{'id': 1, 'kind': 'purchase_return', 'status': 'cancelled'},
               {'id': 2, 'kind': 'purchase'}, None]
    grid.fill([[1, KINDS['purchase_return'], '', '', '', '', Decimal('0')],
               [2, KINDS['purchase'], '', '', '', '', Decimal('100')],
               ['', '', '', '', '합계', '', Decimal('100')]], records)
    grid.sortItems(0, Qt.SortOrder.AscendingOrder)
    assert grid.item(0, 1).text() == '반품'
    assert grid.item(0, 1).foreground().color().name() == '#b42318'
    assert grid.item(1, 1).foreground().color().name() != '#b42318'
    assert grid.item(2, 1).foreground().color().name() == '#2258a0'
    assert grid.export_rows()[0][1] == '반품'
    grid.sortItems(1, Qt.SortOrder.DescendingOrder)
    assert any(grid.item(r, 0).data(Qt.ItemDataRole.UserRole) == records[0] and
               grid.item(r, 1).text() == '반품' for r in range(grid.rowCount()))
    grid.deleteLater()


def test_live_journal_return_text_color_filters_and_ledger_are_preserved(app, tmp_path):
    store = Store(tmp_path/'korean.db'); host = QMainWindow(); host.store = store; host.notify = lambda *_: None
    try:
        store.setup_admin('owner', '표시 검사', 'Owner-Korean-2026!')
        supplier = store.save_partner(dict(kind='supplier', name='표시 공급사'))
        product = store.save_product(dict(name='표시 상품', base_unit='개'))
        today = date.today().isoformat()
        original = store.post_document(dict(kind='purchase', date=today, partner_id=supplier,
                                            lines=[dict(product_id=product, qty=5, unit_price=100)]))
        returned = store.post_document(dict(kind='purchase_return', date=today, partner_id=supplier, source_id=original,
                                            lines=[dict(product_id=product, qty=1, source_line_id=store.document(original)['lines'][0]['id'])]))
        before = store.documents(); page = TradesPage(host); page.refresh()
        row = next(r for r in range(page.grid.rowCount()) if (page.grid.item(r,0).data(Qt.ItemDataRole.UserRole) or {}).get('id') == returned)
        assert page.grid.item(row,1).text() == '반품'
        assert page.grid.item(row,1).foreground().color() == page.grid.item(row,6).foreground().color()
        assert page.grid.item(row,1).foreground().color().name() == '#b42318'
        page.type_filter.setCurrentIndex(page.type_filter.findData('purchase_return'))
        page.refresh(); assert page.grid.rowCount() == 2
        assert page.grid.item(0,0).data(Qt.ItemDataRole.UserRole)['kind'] == 'purchase_return'
        assert page.grid.export_rows()[0][1] == '반품'
        assert store.documents() == before and store.products()[0]['stock_qty'] == '4.000'
    finally:
        host.close(); host.deleteLater(); page.deleteLater() if 'page' in locals() else None
        app.processEvents(); store.close()
