"""All row-based input surfaces share the purchase worksheet's visual contract."""
from pathlib import Path
import os
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox, QDialog, QTableWidgetItem
from pos2.store import Store
from pos2.app import MainWindow
from pos2.trade_sheet import EntrySheet, TradeSheet
from pos2.offline_ui import SalesFormDialog
from pos2.loyalty_ui import PromotionDialog
from pos2.workflow_ui import TradeDialog, CountEditor, PurchaseBatchDialog
from pos2.customer_ui import MemberDialog
from pos2.permission_ui import PermissionsPage


@pytest.fixture
def desktop(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'sheet.db'); store.setup_admin('owner','관리자','Sheet-Strong-2026!')
    supplier = store.save_partner(dict(kind='supplier', name='공급사'))
    product = store.save_product(dict(name='입력표 상품', base_unit='개', purchase_price=1000, sale_price=1500, supplier_id=supplier))
    window = MainWindow(store)
    yield app, store, window, product
    for widget in app.topLevelWidgets(): widget.close(); widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete); app.processEvents(); store.close()


def assert_sheet(table):
    assert isinstance(table, EntrySheet) and table.property('syEntryWorksheet')
    assert table.showGrid() and not table.alternatingRowColors()
    assert '#A4A4A4' in table.styleSheet() and '#E9EACA' in table.styleSheet()
    assert table.verticalHeader().defaultSectionSize() >= 32


def test_entry_sheet_later_editors_are_flat_without_changing_values(desktop):
    app, _, _, _ = desktop
    table = EntrySheet(2,2); field = QLineEdit('0012345'); combo = QComboBox(); combo.addItem('상품',7)
    field.setStyleSheet('padding:8px;border-radius:7px;')
    table.setCellWidget(0,0,field); table.setCellWidget(0,1,combo)
    table.setItem(1,0,QTableWidgetItem('직접 셀 입력')); assert_sheet(table)
    assert field.text() == '0012345' and combo.currentData() == 7
    assert all('border-radius:0px' in w.styleSheet() for w in (field,combo))
    assert table.item(1,0).flags() & Qt.ItemFlag.ItemIsEditable


@pytest.mark.parametrize('kind',['quotation','order'])
def test_commercial_papers_use_continuous_input_sheet_and_keep_exact_calculation(desktop,kind):
    app, store, window, identifier = desktop
    dialog = SalesFormDialog(window,kind+'s')
    assert_sheet(dialog.table)
    row=dialog.rows[0]; row['qty'].setText('2.5'); row['price'].setText('1234.50'); dialog.recalculate()
    assert '3,086.25' in row['total'].text()
    assert not store.documents()  # Visual design never posts stock or money.
    captures=os.environ.get('SY_TEST_CAPTURE_DIR')
    if captures:
        target=Path(captures);target.mkdir(parents=True,exist_ok=True)
        dialog.show();app.processEvents();dialog.grab().save(str(target/f'rc34-{kind}-worksheet.png'))


def test_promotion_stock_count_batch_permissions_and_customer_rows_share_design(desktop):
    app, store, window, identifier = desktop
    promotion=PromotionDialog(store);assert_sheet(promotion.lines)
    count=CountEditor(window);assert_sheet(count.grid)
    assert identifier in count.inputs and not count.inputs[identifier].text()
    trade=TradeDialog(window,'purchase');assert isinstance(trade.table,TradeSheet)
    batch=PurchaseBatchDialog(trade);assert_sheet(batch.table)
    permissions=PermissionsPage(window);assert_sheet(permissions.grid)
    member=MemberDialog(store);assert len(member.findChildren(EntrySheet)) >= 2


def test_worklog_row_tables_use_shared_sheet(desktop,monkeypatch):
    _, store, window, _ = desktop
    from pos2.worklog_ui import WorkLogPage
    inspected=[]
    def inspect(dialog):
        tables=dialog.findChildren(EntrySheet)
        assert len(tables)==2
        for table in tables: assert_sheet(table)
        inspected.append(True);return QDialog.DialogCode.Rejected
    monkeypatch.setattr(QDialog,'exec',inspect)
    WorkLogPage(window).editor()
    assert inspected
