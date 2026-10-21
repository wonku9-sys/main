from datetime import date
from decimal import Decimal
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from pos2.store import Store
from pos2.app import MainWindow
from pos2.shared_protocol import READS

@pytest.fixture
def shop(tmp_path):
    store=Store(tmp_path/'inventory.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    supplier=store.save_partner({'kind':'supplier','name':'정육 공급사','code':'S1'})
    other=store.save_partner({'kind':'supplier','name':'식품 공급사','code':'S2'})
    definitions=[('한우','식품','정육','한우',supplier,'g',100,'12.34','20','taxable'),
                 ('사과','식품','청과','사과',other,'개',1,'100','200','exempt'),
                 ('냉장고','가전','정육','한우',None,'개',1,'500','1000','taxable'),
                 ('무효상품','식품','정육','한우',supplier,'g',100,'10','20','taxable')]
    ids=[]
    for index,(name,a,b,c,sid,unit,basis,buy,sell,tax) in enumerate(definitions):
        ids.append(store.save_product(dict(name=name,category=a,category_mid=b,category_small=c,supplier_id=sid,barcode=str(index+1),base_unit=unit,price_basis=basis,purchase_price=buy,sale_price=sell,tax_mode=tax)))
    for identifier,quantity,price in [(ids[0],'250','10'),(ids[1],'3','80')]:
        p=next(row for row in store.products() if row['id']==identifier)
        store.post_document({'kind':'purchase','date':'2026-01-10','partner_id':p['supplier_id'],'lines':[{'product_id':identifier,'qty':quantity,'unit_price':price}],'paid':'0'})
    store.save_product({'active':False},ids[3])
    yield store,supplier,other,ids
    store.close()

def test_exact_100g_catalog_valuation_vs_average_cost_and_unit_totals(shop):
    store,_,_,ids=shop;report=store.inventory_status()
    assert len(report['products'])==3
    row=next(r for r in report['products'] if r['id']==ids[0])
    assert row['stock_qty']=='250' and row['purchase_total']==Decimal('30.85') and row['stock_cost']==Decimal('25.00')
    assert report['totals']['purchase_total']==Decimal('330.85')
    assert report['totals']['quantities']=={'g':'250','개':'3'}
    assert report['totals']['taxable_total']==Decimal('30.85') and report['totals']['exempt_total']==Decimal('300.00')
    assert report['totals']['supply_value']+report['totals']['vat']==report['totals']['taxable_total']
    average=store.inventory_status(valuation='average')
    assert average['totals']['taxable_total']==Decimal('25.00') and average['totals']['exempt_total']==Decimal('240.00')

def test_category_subtree_products_and_rollup_not_double_counted(shop):
    store,_,_,ids=shop
    report=store.inventory_status(group='categories');assert len(report['rows'])==2
    expanded=store.inventory_status(group='categories',category_path=['식품'],show_children=True)
    assert len(expanded['products'])==2 and expanded['totals']['purchase_total']==Decimal('330.85')
    assert {r['id'] for r in expanded['rows'] if r['row_kind']=='product'}==set(ids[:2])
    assert sum(r['purchase_total'] for r in expanded['rows'])>expanded['totals']['purchase_total']
    middle=store.inventory_status(group='categories',category_path=['식품','정육'])
    assert middle['totals']['item_count']==1
    leaf=store.inventory_status(group='categories',category_path=['식품','정육','한우'])
    assert leaf['rows'][0]['row_kind']=='product' and leaf['rows'][0]['id']==ids[0]

def test_supplier_filters_zero_status_search_and_empty_category(shop):
    store,supplier,_,ids=shop
    assert store.inventory_status(supplier_id=supplier)['totals']['item_count']==1
    assert store.inventory_status(include_inactive=True,supplier_id=supplier)['totals']['item_count']==2
    assert store.inventory_status(stock_filter='zero')['products'][0]['id']==ids[2]
    assert len(store.inventory_status(stock_filter='nonzero')['products'])==2
    assert not store.inventory_status(stock_filter='negative')['products']
    assert store.inventory_status(search='1')['products'][0]['id']==ids[0]
    assert store.inventory_status(supplier_id=0)['products'][0]['id']==ids[2]
    assert not store.inventory_status(category_path=['없는분류'])['products']
    assert store.inventory_status(group='suppliers')['totals']['item_count']==3

def test_month_end_uses_frozen_names_categories_and_cost_not_current_prices(shop):
    store,_,_,ids=shop;close=store.inventory_close('2026-01')
    before=store.inventory_status(group='monthly',month='2026-01',monthly_group='products')
    store.save_product({'name':'이름 변경','purchase_price':'999','sale_price':'9999','category':'새분류','category_mid':'신규','category_small':'상품'},ids[0])
    after=store.inventory_status(group='monthly',month='2026-01',monthly_group='products')
    assert before['rows']==after['rows'] and after['closed_at']
    assert any(row['name']=='한우' and row['path']==['식품'] for row in after['rows'])
    assert all('purchase_price' not in row for row in after['rows'])
    assert after['totals']['stock_cost']==store.inventory_close_detail(close)['stock_cost']
    assert store.inventory_status(group='monthly',month='2025-01')['totals']['item_count']==0

def test_inventory_only_permission_and_menu_denial_and_shared_allowlist(shop):
    store,_,_,ids=shop
    store.save_user({'code':'stock','name':'재고 담당','password':'Staff-Password-2026!','permissions':['inventory','deny:inventory_categories']})
    store.login('stock','Staff-Password-2026!')
    assert store.inventory_status()['totals']['item_count']==3
    with pytest.raises(PermissionError):store.inventory_status(group='categories')
    assert 'inventory_status' in READS
    with pytest.raises(ValueError):store.inventory_status(stock_filter='invalid')

def test_ui_drill_filter_children_month_and_no_inventory_writes(shop,monkeypatch):
    app=QApplication.instance() or QApplication([]);store,_,_,ids=shop
    window=MainWindow(store);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    revision=store.audit_revision();window.open_page('inventory_categories');page=window.current_page
    assert page.grid.rowCount()==2
    page.category.setCurrentIndex(page.category.findData(['식품']));page.children.setChecked(True)
    assert any(r['row_kind']=='product' for r in page.report['rows'])
    page.children.setChecked(False);page.category.setCurrentIndex(page.category.findData(['식품','정육']))
    page.grid.selectRow(0);page.drill();assert page.category.currentData()==['식품','정육','한우']
    window.open_page('inventory_monthly');assert '마감 자료가 없습니다' in window.current_page.summary.text()
    assert store.audit_revision()==revision
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
