"""Exact currency, offline PDF menus, supplier metadata and private desk."""
from datetime import date
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from pos2.store import Store
from pos2.offline_menus import REPORT_VIEWS, SALES_VIEWS, BASIC_VIEWS, MEMBER_VIEWS


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shop(tmp_path):
    store=Store(tmp_path/"v230.db")
    store.setup_admin("owner","관리자","Owner-Strong-2026!")
    supplier=store.save_partner({"kind":"supplier","name":"청정축산","code":"S001"})
    customer=store.save_partner({"kind":"customer","name":"방문 고객","code":"C001"})
    product=store.save_product({"name":"삼겹살","barcode":"203203","base_unit":"g","price_basis":100,"purchase_price":"1880.25","sale_price":"3800.75","supplier_id":supplier,"tax_mode":"exempt","specification":"국내산"})
    yield store,supplier,customer,product
    store.close()


def purchase(shop,quantity="10100",price="1650.00",paid=0):
    store,supplier,_,product=shop
    return store.post_document({"kind":"purchase","date":"2026-10-19","partner_id":supplier,"lines":[{"product_id":product,"qty":quantity,"unit_price":price}],"paid":paid})


def sale(shop,quantity="100",price="3800.75",member_id=None):
    store,_,customer,product=shop
    total=(Decimal(quantity)*Decimal(price)/100).quantize(Decimal("0.01"))
    return store.post_document({"kind":"sale","date":"2026-10-19","partner_id":customer,"member_id":member_id,"lines":[{"product_id":product,"qty":quantity,"unit_price":price}],"paid":str(total)})


def test_g_purchase_100g_price_and_cents_stored_exactly(shop):
    store,_,_,product=shop
    identifier=purchase(shop)
    record=store.document(identifier)
    assert record["total"]==Decimal("166650.00")
    assert record["lines"][0]["price_basis"]==100
    assert record["lines"][0]["base_qty"]=="10100.000"
    assert store.db.execute("SELECT total FROM documents WHERE id=?",(identifier,)).fetchone()[0]==16665000
    assert next(r for r in store.products() if r["id"]==product)["stock_cost"]==Decimal("166650.00")


def test_cents_partial_payment_and_fifo_balance(shop):
    store,supplier,_,_=shop
    identifier=purchase(shop,"1","1234.56",paid="2.01")
    assert store.document(identifier)["total"]==Decimal("12.35")
    assert store.document(identifier)["balance"]==Decimal("10.34")
    store.settle_supplier(supplier,"10.33","2026-10-19","cash")
    assert store.document(identifier)["balance"]==Decimal("0.01")
    store.settle_supplier(supplier,"0.01","2026-10-19","transfer")
    assert store.document(identifier)["balance"]==Decimal("0.00")


def test_rounding_setting_snapshots_does_not_rewrite_old_documents(shop):
    store,_,_,_=shop
    first=purchase(shop,"1","1250.00")
    store.save_settings({"rounding_mode":"won"})
    second=purchase(shop,"1","1250.00")
    assert store.document(first)["total"]==Decimal("12.50")
    assert store.document(second)["total"]==Decimal("13.00")
    assert store.document(first)["rounding_mode"]=="decimal"
    assert store.document(second)["rounding_mode"]=="won"


def test_kg_catalog_accepts_g_input_without_changing_old_basis(shop):
    store,supplier,_,_=shop
    p=store.save_product({"name":"기존 kg 상품","base_unit":"kg","purchase_price":10000,"sale_price":20000})
    identifier=store.post_document({"kind":"purchase","date":"2026-10-19","partner_id":supplier,"lines":[{"product_id":p,"qty":"10100","gram_input":True,"unit_price":"1650.00"}]})
    record=store.document(identifier)
    assert record["total"]==166650
    assert record["lines"][0]["base_qty"]=="10.100"
    assert record["lines"][0]["unit_name"]=="g"
    assert next(r for r in store.products() if r["id"]==p)["base_unit"]=="kg"


def test_default_category_is_three_levels_and_reopening_is_idempotent(shop):
    store,_,_,product=shop
    record=next(r for r in store.products() if r["id"]==product)
    assert tuple(record[k] for k in ("category","category_mid","category_small"))==("미분류","미분류","신상품")
    count=store.db.execute("SELECT COUNT(*) FROM product_categories").fetchone()[0]
    store._init_catalog()
    assert store.db.execute("SELECT COUNT(*) FROM product_categories").fetchone()[0]==count


def test_supplier_profile_and_groups_persist_and_move_settlement_group(shop):
    store,supplier,_,_=shop
    groups=store.supplier_groups("settlement")
    store.save_partner({"mobile":"010-1234-5678","fax":"041-111-2222","address":"아산시","representative":"홍길동","settlement_method":"transfer","settlement_group_id":groups[0]["id"]},supplier)
    record=next(r for r in store.partners("supplier") if r["id"]==supplier)
    assert record["mobile"]=="010-1234-5678" and record["settlement_method"]=="transfer"
    store.set_supplier_group_members(groups[1]["id"],[supplier])
    assert not store.supplier_group_members(groups[0]["id"])
    assert store.supplier_group_members(groups[1]["id"])==[supplier]


def test_bulk_update_is_atomic_and_audit_contains_previous_price(shop):
    store,_,_,product=shop
    with pytest.raises(ValueError):store.bulk_update_products([product,99999],{"sale_price":"1.25"})
    assert next(r for r in store.products() if r["id"]==product)["sale_price"]==Decimal("3800.75")
    store.bulk_update_products([product],{"sale_price":"4000.25","origin":"국내산"})
    changes=store.basic_records("product_changes")
    assert any("3800.75" in r["detail"] and "4000.25" in r["detail"] for r in changes)


@pytest.mark.parametrize("key",list(REPORT_VIEWS)+list(SALES_VIEWS))
def test_every_report_submenu_aggregates_actual_posted_data_and_filters(shop,key):
    store,supplier,_,_=shop
    purchase(shop,"500","1000")
    sale(shop,"200","2000")
    report=store.offline_report(key,"2026-10-01","2026-10-31",supplier)
    if "commission" in key:
        assert report["totals"]["sale_total"]==0
    else:
        assert report["totals"]["sale_total"]==Decimal("4000.00")
        assert report["totals"]["purchase_total"]==(0 if key in SALES_VIEWS else Decimal("5000.00"))
        assert store.offline_report(key,"2026-10-01","2026-10-31",search="없는 품목")["rows"]==[]


@pytest.mark.parametrize("group",["supplier","category","product","document","statement"])
def test_all_purchase_status_views_include_g_and_cents(shop,group):
    store,supplier,_,_=shop
    purchase(shop,"1","1234.56")
    report=store.purchase_status("2026-10-19","2026-10-19",group,supplier)
    assert report["rows"][0]["unit"]=="g"
    assert report["rows"][0]["purchase_qty"]=="1.000"
    assert report["totals"]["net_total"]==Decimal("12.35")


def test_quotation_is_editable_and_has_no_stock_ledger_or_point_side_effects(shop):
    store,_,customer,product=shop
    before=[store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("documents","payments","stock_events","point_entries")]
    data={"date":"2026-10-19","partner_id":customer,"lines":[{"product_id":product,"qty":"101","unit_price":"10.25"}]}
    identifier=store.save_sales_form("quotation",data)
    assert store.sales_form(identifier)["total"]==Decimal("10.35")
    data["lines"][0]["unit_price"]="20.50"
    store.save_sales_form("quotation",data,identifier)
    assert store.sales_form(identifier)["total"]==Decimal("20.71")
    assert before==[store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("documents","payments","stock_events","point_entries")]


def test_statement_snapshots_original_prices_without_posting_twice(shop):
    store,_,_,product=shop
    purchase(shop,"200","1000")
    document=sale(shop,"100","1234.56")
    before=store.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    identifier=store.save_sales_form("statement",{"date":"2026-10-19","source_ids":[document]})
    store.save_product({"name":"새 상품명","sale_price":"9999.99"},product)
    paper=store.sales_form(identifier)
    assert paper["lines"][0]["product_name"]=="삼겹살"
    assert paper["lines"][0]["unit_price"]==Decimal("1234.56")
    assert store.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]==before


def test_member_profile_points_views_and_tax_reference(shop):
    store,_,_,_=shop
    member=store.save_member({"code":"M00001","name":"회원","mobile":"010-3333-4444","address":"천안시","company":"식당","business_no":"123-45-67890"})
    purchase(shop,"200","1000")
    document=sale(shop,"100","2000",member)
    assert store.members("010-3333")[0]["company"]=="식당"
    store.adjust_points(member,12,"수동 확인")
    rows=store.member_view("member_points","2020-01-01","2030-12-31",member)
    assert type(rows[0]["point_balance"]) is int
    identifier=store.save_sales_form("tax_reference",{"date":"2026-10-19","source_ids":[document]})
    assert store.sales_form(identifier)["member"]["business_no"]=="123-45-67890"


def test_schedule_private_alert_once_and_reschedule(shop):
    store,_,_,_=shop
    identifier=store.save_desk_event({"date":"2026-10-19","time":"09:00","title":"발주","notes":"메모","alarm":True})
    assert store.due_desk_alerts("2026-10-19T08:59")==[]
    assert store.due_desk_alerts("2026-10-19T09:00")[0]["title"]=="발주"
    assert store.due_desk_alerts("2026-10-20T10:00")==[]
    store.save_desk_event({"time":"11:00"},identifier)
    assert store.due_desk_alerts("2026-10-19T11:00")[0]["id"]==identifier
    store.save_user({"code":"other","name":"직원","password":"Other-Strong-2026!","role":"staff","permissions":[]})
    store.login("other","Other-Strong-2026!")
    assert store.desk_events("2026-10-01","2026-10-31")==[]
    with pytest.raises(ValueError):store.save_desk_event({"title":"다른 사람 수정"},identifier)


def test_diary_encryption_lock_and_other_account_isolation(shop):
    store,_,_,_=shop
    store.setup_diary("Separate-Diary-2026!","Separate-Diary-2026!")
    key=store.unlock_diary("Separate-Diary-2026!")
    identifier=store.save_diary_entry(key,{"date":"2026-10-19","title":"비밀 제목","body":"민감한 개인 이야기","mood":"평온"})
    assert store.diary_entries(key)[0]["body"]=="민감한 개인 이야기"
    store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw=store.path.read_bytes()
    for secret in ("비밀 제목","민감한 개인 이야기","Separate-Diary-2026!"):
        assert secret.encode() not in raw
    store.lock_diary()
    with pytest.raises(ValueError):store.diary_entries(key)
    key=store.unlock_diary("Separate-Diary-2026!")
    store.save_user({"code":"other","name":"직원","password":"Other-Strong-2026!","role":"staff","permissions":[]})
    store.login("other","Other-Strong-2026!")
    with pytest.raises(ValueError):store.save_diary_entry(key,{"date":"2026-10-19","title":"공격"},identifier)


def test_diary_wrong_password_rate_limit_and_password_change(shop):
    store,_,_,_=shop
    store.setup_diary("Separate-Diary-2026!","Separate-Diary-2026!")
    key=store.unlock_diary("Separate-Diary-2026!")
    store.save_diary_entry(key,{"date":"2026-10-19","title":"일기","body":"보존 확인"})
    store.change_diary_password("Separate-Diary-2026!","New-Diary-Strong!","New-Diary-Strong!")
    key=store.unlock_diary("New-Diary-Strong!")
    assert store.diary_entries(key)[0]["body"]=="보존 확인"
    for _ in range(5):
        with pytest.raises(ValueError):store.unlock_diary("Wrong-Password!")
    with pytest.raises(ValueError,match="5분"):store.unlock_diary("New-Diary-Strong!")


def test_backup_restores_supplier_cents_forms_schedule_and_encrypted_diary(shop):
    store,supplier,customer,product=shop
    store.setup_diary("Separate-Diary-2026!","Separate-Diary-2026!")
    key=store.unlock_diary("Separate-Diary-2026!")
    store.save_diary_entry(key,{"date":"2026-10-19","title":"일기","body":"복원 보존"})
    purchase(shop,"1","1234.56")
    paper=store.save_sales_form("quotation",{"date":"2026-10-19","partner_id":customer,"lines":[{"product_id":product,"qty":"1","unit_price":"1234.56"}]})
    store.save_desk_event({"date":"2026-10-19","title":"백업 일정"})
    store.save_partner({"fax":"041-111-2222"},supplier)
    backup=store.create_backup()
    store.restore_backup(backup,"Owner-Strong-2026!")
    store.login("owner","Owner-Strong-2026!")
    assert store.sales_form(paper)["total"]==Decimal("12.35")
    assert store.desk_events("2026-10-19","2026-10-19")[0]["title"]=="백업 일정"
    assert store.partners("supplier")[0]["fax"]=="041-111-2222"
    with pytest.raises(ValueError):store.diary_entries(key)
    key=store.unlock_diary("Separate-Diary-2026!")
    assert store.diary_entries(key)[0]["body"]=="복원 보존"


def test_sidebar_only_purchase_expanded_after_login_and_home(app,shop):
    from pos2.app import MainWindow
    store,_,_,_=shop
    window=MainWindow(store)
    def expanded():return [window.tree.topLevelItem(i).text(0) for i in range(window.tree.topLevelItemCount()) if window.tree.topLevelItem(i).isExpanded()]
    assert expanded()==["2. 매입/발주관리"]
    assert window.items["diary"].treeWidget() is None
    assert window.personal_panel.layout().count()==4
    window.tree.expandAll()
    assert window.go_home()
    assert expanded()==["2. 매입/발주관리"]
    window.close();window.deleteLater()


def test_new_product_popup_applies_without_posting_trade(app,shop):
    from pos2.workflow_ui import TradeDialog,ProductCatalogDialog
    store,supplier,_,_=shop
    from pos2.app import MainWindow
    window=MainWindow(store)
    trade=TradeDialog(window,"purchase")
    trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    popup=ProductCatalogDialog(trade)
    product=store.save_product({"name":"새 정육","base_unit":"g","price_basis":100,"purchase_price":"1200.25","sale_price":"2000.50"})
    popup.page.product_saved.emit(product)
    row=next(r for r in trade.line_rows if r["product"].currentData()==product)
    assert row["qty"].text()=="0"
    assert row["price"].text()=="1200.25"
    assert store.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]==0
    popup.deleteLater();trade.deleteLater();window.close();window.deleteLater()


def test_quotation_editor_calculation_and_save(app,shop):
    from pos2.offline_ui import SalesFormDialog
    store,_,customer,product=shop
    parent=QDialog()
    dialog=SalesFormDialog(SimpleNamespace(store=store),"quotations",parent=parent)
    dialog.date.setDate(QDate(2026,10,19));dialog.partner.setCurrentIndex(dialog.partner.findData(customer))
    row=dialog.rows[0];row["product"].setCurrentIndex(row["product"].findData(product));row["qty"].setText("100");row["price"].setText("1234.56")
    assert row["total"].text()=="1,234.56"
    dialog.save()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert store.sales_form(dialog.saved_id)["total"]==Decimal("1234.56")


def test_diary_dialog_wipes_key_and_contents_when_locked(app,shop):
    from pos2.diary_ui import DiaryDialog
    store,_,_,_=shop
    store.setup_diary("Separate-Diary-2026!","Separate-Diary-2026!")
    key=store.unlock_diary("Separate-Diary-2026!")
    dialog=DiaryDialog(store,key)
    dialog.title.setText("개인 메모");dialog.editor.setPlainText("민감 내용")
    assert dialog.save()
    dialog.wipe()
    assert bytes(key)==bytes(32) and dialog.editor.toPlainText()=="" and dialog.entries.rowCount()==0
    dialog.deleteLater()
