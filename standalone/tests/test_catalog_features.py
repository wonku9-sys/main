from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from pos2.store import Store
from pos2.catalog_ui import CategoriesPage, CategoryDialog, ProductDialog, ProductsPage
from pos2.workflow_ui import ProductPicker, TradeDialog


@pytest.fixture
def shop(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "data.db")
    store.setup_admin("owner", "관리자", "Owner-Password-2026!")
    window = SimpleNamespace(store=store, notify=lambda _: None)
    yield app, store, window
    for widget in app.topLevelWidgets():
        widget.close()
    store.close()


def record(store, identifier):
    return next(row for row in store.products() if row["id"] == identifier)


def test_automatic_codes_are_sequential_persistent_and_never_reuse_deleted_code(shop):
    _, store, _ = shop
    one = store.save_product({"name": "삼겹살"})
    two = store.save_product({"name": "목살"})
    assert record(store, one)["code"] == "P00001"
    assert record(store, two)["code"] == "P00002"
    store.delete_product(two)
    store.save_product({"name": "기존 코드", "code": "P00100"})
    three = store.save_product({"name": "등심"})
    assert record(store, three)["code"] == "P00101"
    store.save_product({"name": "삼겹살 수정"}, one)
    assert record(store, one)["code"] == "P00001"
    with pytest.raises(ValueError):
        store.save_product({"name": "중복", "code": "P00001"})
    other = Store(store.path)
    try:
        other.login("owner", "Owner-Password-2026!")
        new = other.save_product({"name": "재실행 후"})
        assert record(other, new)["code"] == "P00102"
    finally:
        other.close()


def test_concurrent_connections_allocate_codes_atomically_without_duplicates(shop):
    _, store, _ = shop
    def create(index):
        connection = Store(store.path)
        try:
            connection.login("owner", "Owner-Password-2026!")
            identifier = connection.save_product({"name": f"상품 {index}"})
            return record(connection, identifier)["code"]
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=4) as executor:
        codes = list(executor.map(create, range(12)))
    assert sorted(codes) == [f"P{index:05d}" for index in range(1, 13)]


@pytest.mark.parametrize("search", ["P00001", "0012345678905", "삼겹", "500g", "냉장", "0000999999999"])
def test_searches_code_barcode_name_specification_and_expanded_barcode(shop, search):
    _, store, _ = shop
    product = store.save_product({"name": "한돈 삼겹살", "barcode": "0012345678905", "specification": "냉장 500g"})
    store.save_product({"name": "목살", "specification": "1kg"})
    store.save_unit({"product_id": product, "name": "팩", "factor": "0.5", "barcode": "0000999999999"})
    assert [r["id"] for r in store.products(search)] == [product]
    assert [r["id"] for r in store.trade_products(search)] == [product]


def test_hierarchical_category_rename_updates_products_and_protects_used_deletion(shop):
    _, store, _ = shop
    root = store.save_category({"name": "정육"})
    middle = store.save_category({"name": "돈육", "parent_id": root})
    leaf = store.save_category({"name": "삼겹", "parent_id": middle})
    product = store.save_product({"name": "삼겹살", "category": "정육", "category_mid": "돈육", "category_small": "삼겹"})
    with pytest.raises(ValueError, match="하위"):
        store.delete_category(root)
    with pytest.raises(ValueError, match="상품"):
        store.delete_category(leaf)
    with pytest.raises(ValueError, match="소분류"):
        store.save_category({"name": "4단계", "parent_id": leaf})
    with pytest.raises(ValueError):
        store.save_category({"name": "돈육", "parent_id": root})
    store.save_category({"name": "국산 돈육"}, middle)
    assert record(store, product)["category_mid"] == "국산 돈육"
    assert next(r for r in store.categories() if r["id"] == leaf)["path"] == ["정육", "국산 돈육", "삼겹"]
    assert any(r["action"] == "category_rename" for r in store.product_audit(product))


def test_invalid_category_cascades_but_keeps_existing_product_history(shop):
    _, store, _ = shop
    root = store.save_category({"name": "정육"})
    child = store.save_category({"name": "한우", "parent_id": root})
    product = store.save_product({"name": "등심", "category": "정육", "category_mid": "한우"})
    store.save_category({"name": "정육", "active": False}, root)
    assert all(not r["active"] for r in store.categories())
    with pytest.raises(ValueError, match="상위"):
        store.save_category({"name": "한우", "active": True}, child)
    with pytest.raises(ValueError, match="무효"):
        store.save_product({"name": "새 상품", "category": "정육"})
    store.save_product({"sale_price": 10000}, product)
    assert record(store, product)["sale_price"] == 10000


def test_product_code_readonly_status_dropdown_and_registered_category_only(shop):
    _, store, window = shop
    root = store.save_category({"name": "정육"})
    middle = store.save_category({"name": "돈육", "parent_id": root})
    store.save_category({"name": "삼겹", "parent_id": middle})
    dialog = ProductDialog(store)
    assert dialog.fields["code"].isReadOnly()
    assert [dialog.product_status.itemText(i) for i in range(3)] == ["유효", "무효", "퇴출대상"]
    dialog.fields["name"].setText("한돈 삼겹살")
    for key, value in (("category", "정육"), ("category_mid", "돈육"), ("category_small", "삼겹")):
        dialog.fields[key].setText(value)
        assert not dialog.fields[key].isEditable()
    dialog.product_status.setCurrentIndex(2)
    assert dialog.save(False)
    assert dialog.fields["code"].text() == "P00001"
    assert record(store, dialog.saved_id)["retirement_target"]
    page = ProductsPage(window)
    page.status_filter.setCurrentIndex(page.status_filter.findData("퇴출대상"))
    assert page.grid.rowCount() == 1
    dialog.product_status.setCurrentIndex(1)
    assert dialog.save(False)
    assert not record(store, dialog.saved_id)["active"]
    page.status_filter.setCurrentIndex(page.status_filter.findData("무효"))
    assert page.grid.rowCount() == 1
    fresh = ProductDialog(store)
    fresh.fields["name"].setText("임의 분류 금지")
    fresh.fields["category"].setText("등록하지 않은 분류")
    assert not fresh.save(False)
    assert "먼저 등록" in fresh.error_label.text()


def test_category_tree_context_menu_search_selection_and_expand_collapse(shop):
    _, store, window = shop
    root = store.save_category({"name": "정육"})
    middle = store.save_category({"name": "돈육", "parent_id": root})
    leaf = store.save_category({"name": "삼겹", "parent_id": middle})
    other = store.save_category({"name": "야채"})
    page = CategoriesPage(window)
    assert page.root.text(0) == "전체분류"
    assert page.items[leaf].parent() is page.items[middle]
    page.tree.setCurrentItem(page.items[middle])
    entries = {entry.text(): entry for entry in page.make_context_menu().actions()}
    assert {"분류 추가", "분류 삭제", "분류 등록정보 / 수정", "분류를 무효화", "분류를 유효화", "하위분류 보기", "하위분류 감추기"} <= set(entries)
    entries["하위분류 감추기"].trigger()
    assert not page.items[middle].isExpanded()
    entries["하위분류 보기"].trigger()
    assert page.items[middle].isExpanded()
    page.search.setText("삼겹")
    assert not page.items[leaf].isHidden() and not page.items[root].isHidden()
    assert page.items[other].isHidden()
    dialog = CategoryDialog(store, select=True)
    dialog.page.search.setText("돈육")
    dialog.page.tree.setCurrentItem(dialog.page.items[leaf])
    dialog.choose()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.record["path"] == ["정육", "돈육", "삼겹"]
    assert dialog.page.tree.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu


def test_trade_product_picker_finds_spec_and_expanded_unit_without_posting(shop):
    _, store, _ = shop
    product = store.save_product({"name": "삼겹살", "specification": "500g", "barcode": "0012345678905"})
    unit = store.save_unit({"product_id": product, "name": "팩", "factor": "0.5", "barcode": "0000999999999"})
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    parent.store = store
    picker = ProductPicker(parent)
    picker.search.setText("500g")
    assert picker.grid.rowCount() == 1
    picker.search.setText("0000999999999")
    picker.choose()
    assert picker.record["id"] == product and picker.unit_id == unit
    assert not store.documents()
