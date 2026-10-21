"""Exact reference aggregates, bounded navigation and real supplier drilldown."""
from datetime import date
from decimal import Decimal
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtWidgets import QApplication,QMessageBox
from pos2.store import Store
from pos2.app import MainWindow


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'views.db');store.setup_admin('owner','시험 관리자','Reference-Only-2026!')
    supplier=store.save_partner(dict(kind='supplier',code='S1',name='가상 공급사'))
    empty=store.save_partner(dict(kind='supplier',code='S2',name='거래 없는 공급사'))
    products=[store.save_product(dict(name=f'가상상품{i}',base_unit=unit,category='시험 분류',tracked=False,tax_mode='taxable')) for i,unit in enumerate(('개','kg'))]
    purchase=store.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,paid='0',lines=[dict(product_id=p,qty='1',unit_price='.05') for p in products]))
    window=MainWindow(store);window.resize(1280,850);window.show();app.processEvents()
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:pytest.fail(str(args[2])))
    yield app,store,window,supplier,empty,purchase
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_supplier_and_line_vat_use_identical_per_line_rounding_and_mixed_units(desktop):
    _,s,_,supplier,_,_=desktop;today=date.today().isoformat()
    report=s.purchase_status(today,today,'supplier',supplier);lines=s.purchase_status_lines(today,today,'supplier',supplier)
    row=report['rows'][0]
    assert row['net_total']==Decimal('.10') and row['vat']==sum(r['vat'] for r in lines)==0
    assert row['total_supply_value']==sum(r['supply_value'] for r in lines)==Decimal('.10')
    assert row['net_qty']=='' and {r['unit'] for r in row['quantities']}=={'개','g'}


def test_all_five_reference_views_render_current_records_and_nonselectable_subtotals(desktop):
    app,s,window,supplier,empty,purchase=desktop
    bar_position=window.toolbar.pos()
    for key in ('purchase_suppliers','purchase_categories','purchase_products','purchase_documents','purchase_statement'):
        assert window.open_page(key);app.processEvents();page=window.current_page
        assert page.grid.rowCount()>0 and window.toolbar.pos()==bar_position
        for row in range(page.grid.rowCount()):
            item=page.grid.item(row,0)
            if item.data(Qt.ItemDataRole.UserRole) is None:assert not item.flags() & Qt.ItemFlag.ItemIsSelectable
        if key=='purchase_suppliers':
            assert page.supplier_documents.rowCount()==1
            page.zero_suppliers.setChecked(True);page.refresh()
            assert page.grid.rowCount()==len(page._filter_data['suppliers']), [page.grid.item(r,0).data(Qt.ItemDataRole.UserRole) for r in range(page.grid.rowCount())]
        if key=='purchase_statement':assert page.invoice_comparison.rowCount()==1
    assert len(s.documents(status='posted'))==1


def test_returns_reconcile_between_purchase_views_and_filter_exclusion(desktop):
    _,s,window,supplier,_,purchase=desktop;today=date.today().isoformat();original=s.document(purchase)
    line=original['lines'][0]
    s.post_document(dict(kind='purchase_return',date=today,partner_id=supplier,source_id=purchase,paid='0',lines=[dict(product_id=line['product_id'],source_line_id=line['id'],qty='1')]))
    summary=s.purchase_status(today,today,'supplier',supplier)['rows'][0]
    lines=s.purchase_status_lines(today,today,'document',supplier)
    assert summary['net_total']==sum(r['net_total'] for r in lines)==Decimal('.05')
    window.open_page('purchase_documents');page=window.current_page
    page.kind.setCurrentIndex(page.kind.findData('purchase_return'));page.refresh()
    assert page.grid.rowCount()==2 and page.grid.item(0,9).text()=='-0.05'
    page.returns.setChecked(False);page.refresh();assert page.grid.rowCount()==0
