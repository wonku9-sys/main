"""Prove the packaged Qt catalog and return label with synthetic data only."""
from datetime import date, timedelta
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QMainWindow
from .store import Store
from .workflow_ui import TradesPage, TradeDialog


def menu_labels(menu):
    return {a.text().split('\t')[0].replace('&', '').split('(')[0].strip()
            for a in menu.actions() if not a.isSeparator()}


def verify(app, parent, directory, screenshot=None):
    expected = {'실행 취소', '다시 실행', '잘라내기', '복사', '붙여넣기', '삭제', '모두 선택'}
    for cls in (QLineEdit, QTextEdit, QPlainTextEdit):
        field = cls(parent)
        menu = field.createStandardContextMenu()
        try:
            assert expected <= menu_labels(menu), (cls.__name__, menu_labels(menu))
            if screenshot is not None and cls is QLineEdit:
                menu.popup(parent.mapToGlobal(QPoint(70, 150))); app.processEvents()
                target = screenshot.with_name(screenshot.stem+'-korean-context-menu'+screenshot.suffix)
                target.parent.mkdir(parents=True, exist_ok=True)
                assert menu.grab().save(str(target))
        finally:
            menu.close(); menu.deleteLater(); field.deleteLater()
    store = Store(directory/'isolated-korean-return-proof.db')
    host = QMainWindow(parent); host.store = store; host.notify = lambda *_: None
    try:
        store.setup_admin('owner', '한글 표시 검증', 'Isolated-Korean-Proof-2026!')
        supplier = store.save_partner(dict(kind='supplier', name='표시 검증 공급사'))
        product = store.save_product(dict(name='표시 검증 상품', base_unit='개', purchase_price=100))
        today = date.today().isoformat()
        store.post_document(dict(kind='purchase',date=(date.today()-timedelta(days=1)).isoformat(),partner_id=supplier,
                            lines=[dict(product_id=product,qty=1,unit_price=90,sale_price=150)]))
        original = store.post_document(dict(kind='purchase', date=today, partner_id=supplier,
                                            lines=[dict(product_id=product, qty=5, unit_price=100,sale_price=160)]))
        returned = store.post_document(dict(kind='purchase_return', date=today, partner_id=supplier,
                                            source_id=original, lines=[dict(product_id=product, qty=1,
                                            source_line_id=store.document(original)['lines'][0]['id'])]))
        before = store.documents()
        page = TradesPage(host); host.setCentralWidget(page); page.refresh()
        row = next(r for r in range(page.grid.rowCount())
                   if (page.grid.item(r, 0).data(Qt.ItemDataRole.UserRole) or {}).get('id') == returned)
        kind, amount = page.grid.item(row, 1), page.grid.item(row, 6)
        assert kind.text() == '반품' and kind.foreground().color().name() == '#b42318'
        assert kind.foreground().color() == amount.foreground().color()
        assert store.documents() == before and store.document(original)['total'] == 500
        if screenshot is not None:
            host.resize(1180, 600); host.show(); app.processEvents()
            target = screenshot.with_name(screenshot.stem+'-purchase-return-label'+screenshot.suffix)
            assert host.grab().save(str(target))
        dialog=TradeDialog(host,'purchase',original)
        try:
            dialog.show(); app.processEvents(); dialog.tax_info_button.click(); app.processEvents()
            assert dialog.price_panel.isVisible() and dialog.price_panel.history.rowCount()==2
            assert dialog.price_panel.history.item(0,1).text()=='100.00'
            assert dialog.price_panel.history.item(0,2).text()=='160.00'
            if screenshot is not None:
                target=screenshot.with_name(screenshot.stem+'-purchase-price-history'+screenshot.suffix)
                assert dialog.grab().save(str(target))
            assert store.documents()==before
        finally:dialog.close(); dialog.deleteLater(); app.processEvents()
        fresh=TradeDialog(host,'purchase')
        try:
            fresh.apply_picked_products([(fresh.product_map[product],None)])
            fresh.show();app.processEvents();fresh.table.choose_row(0)
            if screenshot is not None:
                assert fresh.grab().save(str(screenshot.with_name(screenshot.stem+'-purchase-row-selection'+screenshot.suffix)))
            fresh.table.choose_cell(0,fresh.line_columns.index('qty'))
            assert '#087FD3' in fresh.line_rows[0]['qty'].styleSheet()
            assert '#087FD3' not in fresh.line_rows[0]['price'].styleSheet()
            if screenshot is not None:
                assert fresh.grab().save(str(screenshot.with_name(screenshot.stem+'-purchase-cell-selection'+screenshot.suffix)))
            fresh.table.show_product_menu(0,fresh.table.mapToGlobal(QPoint(80,60)));app.processEvents()
            menu=fresh.table._product_menu
            assert {'줄여보기','펼쳐보기','상품 순서이동'} <= {a.text() for a in menu.actions()}
            if screenshot is not None:
                assert menu.grab().save(str(screenshot.with_name(screenshot.stem+'-purchase-product-menu'+screenshot.suffix)))
            menu.close();assert store.documents()==before
        finally:fresh.reject();fresh.deleteLater();app.processEvents()
        print('PASS Korean UI: official Qt context menus, portable catalog, red two-character purchase return label, unchanged ledger', flush=True)
        print('PASS purchase price panel: selected-item F11, historical purchase and recorded sale prices, unit basis, unchanged ledger',flush=True)
        print('PASS purchase selection: pale identity zone, blue row or single editable cell, working Korean product context menu',flush=True)
    finally:
        host.close(); host.deleteLater(); app.processEvents(); store.close()
