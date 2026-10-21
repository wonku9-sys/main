"""Cache correctness after catalog and stock changes in the optimized build."""
import pytest
from decimal import Decimal
from PySide6.QtWidgets import QApplication
from pos2.app import MainWindow
from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'cache.db')
    store.setup_admin('owner', '관리자', 'Owner-Password-2026!')
    supplier = store.save_partner(dict(kind='supplier', name='공급사'))
    product = store.save_product(dict(name='상품', supplier_id=supplier,
                                     purchase_price=100, sale_price=200))
    yield app, store, supplier, product
    store.close()


def test_stock_movement_invalidates_catalog_and_window_cache(shop):
    _, store, supplier, product = shop
    # Exercise the real window method without opening unrelated desktop services.
    class Cache:
        cached_products = MainWindow.cached_products
    window = Cache()
    window.store = store
    first = window.cached_products()
    assert window.cached_products() is first
    revision = store.catalog_revision()
    document = store.post_document(dict(kind='purchase', date='2026-10-20',
        partner_id=supplier, lines=[dict(product_id=product, qty='2', unit_price=100)]))
    assert store.catalog_revision() != revision
    assert Decimal(window.cached_products()[0]['stock_qty']) == 2
    assert window.cached_products()[0]['_edit_token'] != first[0]['_edit_token']
    store.cancel_document(document, '캐시 회귀 검사')
    assert Decimal(window.cached_products()[0]['stock_qty']) == 0


def test_failed_reload_does_not_mark_stale_cache_as_current(shop, monkeypatch):
    _, store, supplier, product = shop
    class Cache:
        cached_products = MainWindow.cached_products
    window = Cache()
    window.store = store
    window.cached_products()
    store.save_product(dict(name='수정 상품'), product)
    original = store.products
    def fail():
        raise RuntimeError('temporary read failure')
    monkeypatch.setattr(store, 'products', fail)
    with pytest.raises(RuntimeError):
        window.cached_products()
    monkeypatch.setattr(store, 'products', original)
    assert window.cached_products()[0]['name'] == '수정 상품'


def test_cached_products_rechecks_login(shop):
    _, store, _, _ = shop
    class Cache:
        cached_products = MainWindow.cached_products
    window = Cache()
    window.store = store
    window.cached_products()
    store.logout()
    with pytest.raises(PermissionError):
        window.cached_products()


def test_requirements_include_all_project_runtime_dependencies():
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    dependencies = tomllib.loads((root/'pyproject.toml').read_text())['project']['dependencies']
    assert set(dependencies) <= set((root/'requirements.txt').read_text().splitlines())


def test_catalog_revision_is_allowed_for_shared_clients():
    from pos2.shared_protocol import READS
    assert 'catalog_revision' in READS
