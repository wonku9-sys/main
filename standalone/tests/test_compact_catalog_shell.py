"""Photo-guided compact filter panels, working secondary actions and readable lists."""
import os
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtWidgets import QApplication,QPushButton,QAbstractItemView,QScrollArea
from pos2.app import MainWindow
from pos2.store import Store


@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([])
    from pos2.popup_policy import install_popup_policy
    install_popup_policy(app)
    store=Store(tmp_path/'compact.db');store.setup_admin('owner','관리자','Compact-Strong-2026!')
    supplier=store.save_partner(dict(kind='supplier',name='직관적인 공급사',phone='041-123-4567',contact='담당자'))
    store.save_product(dict(name='상품명 우선 표시',barcode='00001234',supplier_id=supplier,base_unit='개',purchase_price=1000,sale_price=1500))
    window=MainWindow(store);window.resize(1280,850);window.show();app.processEvents()
    yield app,store,window,supplier
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


@pytest.mark.parametrize('key,columns',[('products',[1,4,5,6,7,8]),('suppliers',[0,1,2,3,5,6])])
def test_compact_lists_keep_logical_fields_and_preserve_read_only(desktop,key,columns):
    app,store,window,_=desktop;revision=store.audit_revision()
    window.open_page(key);page=window.current_page;app.processEvents()
    assert [page.grid.horizontalHeader().logicalIndex(i) for i in range(6)]==columns
    assert page.grid.reference_layout and page.grid.item(0,1).background().color().name()=='#eeefcf'
    assert page.grid.editTriggers()==QAbstractItemView.EditTrigger.NoEditTriggers
    assert page.filter_panel.height()<160
    assert not [b for b in page.findChildren(QPushButton) if b.isVisible() and '조회' in b.text()]
    if key=='products':
        assert not page.category_panel.isVisible()
        toggle=next(a for a in page.more_actions.menu().actions() if a.text()=='분류 트리 보기')
        toggle.trigger();assert page.category_panel.isVisible()
        toggle.trigger();assert not page.category_panel.isVisible()
    assert store.audit_revision()==revision
    captures=os.environ.get('SY_TEST_CAPTURE_DIR')
    if captures:
        target=Path(captures);target.mkdir(parents=True,exist_ok=True)
        window.grab().save(str(target/f'rc34-compact-{key}.png'))


def test_secondary_menu_retains_permission_and_calls_original_button(desktop):
    app,store,window,_=desktop;window.open_page('products');page=window.current_page
    source=page.more_actions._source_controls[0];entry=page.more_actions.menu().actions()[0]
    called=[];source.clicked.connect(lambda *_:called.append('edit'))
    page.grid.clearSelection();page.grid.setCurrentCell(-1,-1)
    source.setEnabled(False);page.more_actions.menu().aboutToShow.emit()
    assert not entry.isEnabled();entry.trigger();assert not called
    source.setEnabled(True);page.more_actions.menu().aboutToShow.emit();entry.trigger()
    assert called==['edit']


def test_catalog_supplier_filters_and_scan_still_work_after_rebuild(desktop):
    app,store,window,supplier=desktop
    window.open_page('products');page=window.current_page
    page.supplier.setCurrentIndex(page.supplier.findData(supplier));assert page.grid.rowCount()==1
    page.search.setText('없는 상품');page.refresh();assert page.grid.rowCount()==0
    page.scan_barcode('00001234');assert page.grid.rowCount()==1
    page.focus_scan();app.processEvents();assert page.scan.hasFocus() and page.scan.isVisible()
    window.open_page('suppliers');page=window.current_page;page.search.setText('직관적인')
    assert page.grid.rowCount()==1
    page.search.setText('없는 공급사');assert page.grid.rowCount()==0


def test_four_toolbar_groups_are_ordered_without_extra_commands(desktop):
    app,store,window,_=desktop;groups=[[]]
    for entry in window.toolbar.actions():
        if entry is window.toolbar_brand_action:continue
        if entry.isSeparator():groups.append([])
        else:groups[-1].append(entry.text())
    assert groups==[['이전','다음'],['첫화면','달력'],['상품장','매입전표','판매조회'],['F8 스캔']]


@pytest.mark.parametrize('font_px',[14,18,22])
def test_supplier_compact_rows_never_clip_native_font(desktop,font_px):
    app,_,window,_=desktop;window.open_page('suppliers');page=window.current_page
    # App-wide QSS overrides setFont(), so force the actual rendered size.
    page.grid.setStyleSheet(page.grid.styleSheet()+f'QTableWidget{{font-size:{font_px}px;}}')
    app.processEvents();assert page.grid.font().pixelSize()==font_px
    page.set_row_density(True);small=page.grid.verticalHeader().defaultSectionSize()
    assert small>=page.grid.fontMetrics().height()+6
    assert small>=page.grid.verticalHeader().minimumSectionSize()
    page.set_row_density(False)
    assert page.grid.verticalHeader().defaultSectionSize()>=max(38,small)


def test_opened_editor_actions_stay_fixed_and_no_duplicate_home(desktop):
    app,store,window,_=desktop
    from pos2.widgets import FormDialog
    from pos2.supplier_ui import SupplierDialog
    window.navigation.enable()
    generic=FormDialog('입력창',window);generic.field('name','내용','')
    for i in range(15):generic.field(f'extra{i}',f'항목{i}','')
    generic.finish(lambda:None);generic.show();generic.resize(500,400);app.processEvents()
    scroll=generic.findChild(QScrollArea,'popupScroll')
    assert scroll is not None and not scroll.isAncestorOf(generic.buttons)
    assert not hasattr(generic,'_home_button')
    for button in generic.buttons.buttons():
        assert button.isVisible() and generic.rect().contains(button.mapTo(generic,button.rect().bottomRight()))
    generic.close()
    supplier=SupplierDialog(window);supplier.show();supplier.resize(900,680);app.processEvents()
    assert not hasattr(supplier,'_home_button')
    for button in supplier.buttons.buttons():
        if button.isVisible():assert supplier.rect().contains(button.mapTo(supplier,button.rect().bottomRight()))
    captures=os.environ.get('SY_TEST_CAPTURE_DIR')
    if captures:
        target=Path(captures);target.mkdir(parents=True,exist_ok=True)
        supplier.grab().save(str(target/'rc34-supplier-editor.png'))
