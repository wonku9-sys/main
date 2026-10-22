from datetime import date
from decimal import Decimal
import json
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtTest import QTest
from pos2.store import Store
from pos2.workflow_ui import TradeDialog


@pytest.fixture
def shop(tmp_path):
    store=Store(tmp_path/'prices.db');store.setup_admin('owner','가격 검사','Owner-Price-2026!')
    supplier=store.save_partner(dict(kind='supplier',name='이력 공급사'))
    product=store.save_product(dict(name='대파',barcode='001234',base_unit='개',purchase_price=5900,sale_price=9900))
    yield store,supplier,product
    store.close()


def post(shop,when,price,sale=None,**extra):
    store,supplier,product=shop
    line=dict(product_id=product,qty=extra.pop('qty',2),unit_price=price,**extra)
    if sale is not None:line['sale_price']=sale
    return store.post_document(dict(kind='purchase',date=when,partner_id=supplier,lines=[line]))


def test_exact_historical_prices_cutoff_returns_drafts_cancelled_and_legacy_missing_sale(shop):
    s,supplier,p=shop
    first=post(shop,'2026-05-07',4500,5500); latest=post(shop,'2026-06-18',5900,9900)
    post(shop,'2026-07-01',7000,11000)
    draft=s.save_draft(dict(kind='purchase',date='2026-06-19',partner_id=supplier,lines=[dict(product_id=p,qty=1,unit_price=99999)]))
    s.post_document(dict(kind='purchase_return',date='2026-06-18',partner_id=supplier,source_id=latest,
        lines=[dict(product_id=p,source_line_id=s.document(latest)['lines'][0]['id'],qty=1)]))
    s.db.execute('DELETE FROM document_entry WHERE document_id=?',(first,));s.db.commit()
    before=s.documents();audit=s.audit_revision()
    result=s.purchase_price_history(p,'2026-06-18')
    assert [r['document_id'] for r in result['records']]==[latest,first]
    assert result['records'][0]['purchase_price']==Decimal('5900.00')
    assert result['records'][0]['sale_price']==Decimal('9900.00')
    assert result['records'][1]['sale_price'] is None
    assert s.documents()==before and s.audit_revision()==audit and s.document(draft)['status']=='draft'
    assert result['barcode']=='001234' and result['basis']=='개당'


def test_unit_normalization_pack_grams_and_exact_decimal(shop):
    s,supplier,_=shop
    p=s.save_product(dict(name='중량 상품',base_unit='kg',purchase_price='1234.56',sale_price='2000.50'))
    unit=s.save_unit(dict(product_id=p,name='박스',factor=5,purchase_price='6000.25',sale_price='9000.50'))
    bundle=(s,supplier,p)
    first=post(bundle,'2026-06-17','1234.56','2000.50')
    packet=post(bundle,'2026-06-18','6000.25','9000.50',unit_id=unit)
    grams=post(bundle,'2026-06-19','125.55','200.05',gram_input=True,qty=100)
    base=s.purchase_price_history(p,'2026-06-19')
    assert [r['purchase_price'] for r in base['records']]==[Decimal('1255.50'),Decimal('1200.05'),Decimal('1234.56')]
    assert base['records'][1]['sale_price']==Decimal('1800.10')
    g=s.purchase_price_history(p,'2026-06-19',gram_input=True)
    assert g['basis']=='100g당' and g['records'][0]['purchase_price']==Decimal('125.55')
    pack=s.purchase_price_history(p,'2026-06-19',unit)
    assert pack['basis']=='박스당' and pack['records'][1]['purchase_price']==Decimal('6000.25')
    with pytest.raises(ValueError):s.purchase_price_history(p,'2026-06-19',999999)


def test_actual_right_panel_f11_row_switch_date_and_no_write(shop,monkeypatch):
    app=QApplication.instance() or QApplication([]);s,supplier,p=shop
    from pos2.popup_policy import install_popup_policy
    install_popup_policy(app)
    first=post(shop,'2026-05-07',4500,5500); latest=post(shop,'2026-06-18',5900,9900)
    other=s.save_product(dict(name='다른 상품',base_unit='개'))
    host=QMainWindow();host.store=s;host.notify=lambda *_:None
    trade=TradeDialog(host,'purchase');trade.show();app.processEvents()
    try:
        trade.apply_picked_products([(trade.product_map[p],None),(trade.product_map[other],None)])
        trade.table.setCurrentCell(0,3)
        trade.date.setDateTime(trade.date.dateTime().fromString('2026-06-18 12:00','yyyy-MM-dd HH:mm'))
        before=s.documents();trade.activateWindow();app.processEvents()
        QTest.keyClick(trade,Qt.Key.Key_F11);app.processEvents();panel=trade.price_panel
        assert panel.isVisible() and trade.tax_info_button.isChecked() and panel.history.rowCount()==2
        assert '대파' in panel.product_label.text() and '001234' in panel.barcode_label.text()
        assert panel.history.item(0,0).text()=='2026-06-18'
        assert panel.history.item(0,1).text()=='5,900.00'
        assert panel.history.item(0,1).background().color().name()=='#ffe3df'
        if trade.height()>=760:
            assert trade.rect().contains(trade.purchase_summary['total'].mapTo(trade,trade.purchase_summary['total'].rect().bottomRight()))
        assert trade.rect().contains(trade.post_button.mapTo(trade,trade.post_button.rect().bottomRight()))
        assert not trade.isFullScreen()
        trade.table.setCurrentCell(1,3);panel.refresh()
        assert '다른 상품' in panel.product_label.text() and panel.history.rowCount()==0
        trade.table.setCurrentCell(0,3);panel.refresh()
        trade.detail_tabs.setCurrentIndex(1);app.processEvents();assert not panel.isVisible()
        trade.detail_tabs.setCurrentIndex(0);app.processEvents();assert panel.isVisible()
        trade.tax_info();assert not panel.isVisible() and not trade.tax_info_button.isChecked()
        assert s.documents()==before
    finally:
        trade.reject();trade.deleteLater();host.close();host.deleteLater();app.processEvents()


def test_promotion_prices_and_purchase_only_permission(shop):
    s,supplier,p=shop
    post(shop,'2026-06-18',5900,9900)
    promo=s.save_promotion(dict(title='주말 행사',start='2026-06-20',end='2026-06-21',
        items=[dict(product_id=p,purchase_price='4300.25',sale_price='7900.50')]))
    s.save_user(dict(code='buyer',name='매입 직원',role='staff',password='Buyer-Only-2026!',permissions=['trade']))
    s.logout();s.login('buyer','Buyer-Only-2026!')
    data=s.purchase_price_history(p,'2026-06-18')
    assert data['promotions'][0]['purchase_price']==Decimal('4300.25')
    assert data['promotions'][0]['sale_price']==Decimal('7900.50')
    assert data['records'][0]['purchase_price']==Decimal('5900.00')
    s.logout();s.login('owner','Owner-Price-2026!')
    s.save_user(dict(code='blocked',name='제외 직원',role='staff',password='Blocked-Only-2026!',permissions=['trade','deny:purchases']))
    s.logout();s.login('blocked','Blocked-Only-2026!')
    with pytest.raises(PermissionError):s.purchase_price_history(p,'2026-06-18')
