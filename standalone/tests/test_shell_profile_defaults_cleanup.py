"""Four fixed shell lines, certificate layout and narrowly scoped reset actions."""
from hashlib import sha256
import json
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QPoint,Qt
from PySide6.QtGui import QStatusTipEvent
from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton
from pos2.app import MainWindow,STYLE,menu_caption
from pos2.query_bar import QUERY_BAR_HEIGHT
from pos2.settings_defaults import SettingsDefaultsDialog,stage_defaults
from pos2.retired_games import registered_copies,delete_registered_copies
from pos2.store import Store


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);previous=app.styleSheet();app.setStyleSheet(STYLE)
    store=Store(tmp_path/'desktop.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    store.save_settings({'store_name':'서영 테스트점','business_no':'123-45-67890','representative':'점포 대표','business_type':'소매,도매','business_category':'슈퍼마켓','phone':'010-0000-0000','address':'예시 주소'})
    window=MainWindow(store);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    yield app,store,window
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close();app.setStyleSheet(previous)


def test_four_lines_native_identity_plain_menu_unboxed_icons_and_fixed_query(desktop):
    app,store,window=desktop;revision=store.audit_revision()
    roots=[a for a in window.menuBar().actions() if a.isVisible()]
    assert roots and all(a.text()[0].isdigit() and a.menu() is not None for a in roots)
    assert all(a.icon().isNull() for a in roots)
    assert 'QToolBar#mainToolbar QToolButton {background:transparent;border:0;' in STYLE
    assert 'QMenuBar::item {background:transparent;border:0;' in STYLE
    assert [a.text() for a in window.toolbar.actions() if not a.isSeparator()][:6]==['이전','다음','첫화면','달력','상품장','매입전표']
    assert not window.findChild(type(window.scrollers['home']),'accountHeaderScroll').isVisible()
    for width,height in ((940,640),(1280,850),(1500,930)):
        window.resize(width,height);app.processEvents();position=None
        for key in ('products','purchases','settings','store_profile'):
            assert window.open_page(key);app.processEvents();bar=window.query_bar
            assert window.selected_menu.text()==menu_caption(key) and menu_caption(key) in window.windowTitle()
            assert '서영 테스트점' in window.windowTitle() and not window.windowIcon().isNull()
            assert bar.height()==window.sidebar_heading.height()==QUERY_BAR_HEIGHT
            assert bar.mapTo(window,QPoint()).y()==window.sidebar_heading.mapTo(window,QPoint()).y()
            assert window.toolbar.geometry().bottom()<bar.mapTo(window,QPoint()).y()
            assert not bar.context.isVisible() and not bar.description.isVisible()
            origin=bar.query_button.mapTo(window,QPoint())
            if position is None:position=origin
            assert origin==position
            assert abs(bar.query_button.mapTo(bar,bar.query_button.rect().center()).x()-bar.rect().center().x())<=1
    assert store.audit_revision()==revision


def test_account_actions_calendar_and_lower_status_help_are_real(desktop):
    app,store,window=desktop;revision=store.audit_revision()
    window.account_actions['관리자 설정'].trigger();assert window.current_key=='settings'
    window.open_page('purchases')
    next(a for a in window.toolbar.actions() if a.text()=='달력').trigger();app.processEvents()
    assert window.current_key=='home' and window.current_page.calendar.hasFocus()
    tool=next(a for a in window.toolbar.actions() if a.text()=='상품장')
    QCoreApplication.sendEvent(window,QStatusTipEvent(tool.statusTip()))
    assert '상품' in window.statusBar().currentMessage()
    assert store.audit_revision()==revision


def test_profile_name_is_unchanged_and_certificate_fields_save_exactly(desktop):
    app,store,window=desktop;window.open_page('store_profile');page=window.current_page;app.processEvents()
    assert page.title=='점포 등록정보' and window.items['store_profile'].text(0)=='점포 등록정보'
    grid=page.registration_grid
    assert grid.indexOf(page.fields['store_name'])>=0
    assert page.fields['business_type'].mapTo(page,QPoint()).y()==page.fields['store_name'].mapTo(page,QPoint()).y()
    assert page.fields['business_no'].mapTo(page,QPoint()).y()==page.fields['business_category'].mapTo(page,QPoint()).y()
    assert page.fields['phone'].mapTo(page,QPoint()).y()==page.fields['representative'].mapTo(page,QPoint()).y()
    assert page.fields['address'].width()>page.fields['store_name'].width()
    assert len(page.fields)==12
    page.fields['store_name'].setText('수정 점포');page.fields['bank'].setText('예시 은행');assert page.save()
    assert store.store_profile()['store_name']=='수정 점포' and store.store_profile()['bank']=='예시 은행'
    assert '수정 점포' in window.windowTitle()


def test_defaults_cancel_and_stage_do_not_write_or_wipe_business_identity(desktop):
    _,store,window=desktop;window.open_page('settings');page=window.current_page
    store.save_settings({'rounding_mode':'won','allow_negative_stock':False,'earn_bps':250,'point_min':500,'point_step':50,'point_enabled':False})
    page.refresh();before=store.settings();revision=store.audit_revision();profile=store.store_profile()
    dialog=SettingsDefaultsDialog(page);assert not dialog.apply_button.isEnabled()
    dialog.boxes['points'].setChecked(True);assert dialog.apply_button.isEnabled();dialog.reject()
    assert store.settings()==before and store.audit_revision()==revision
    stage_defaults(page,['calculation','points','backup'])
    assert store.settings()==before and store.audit_revision()==revision
    assert page.fields['earn_bps'].text()=='100' and page.rounding_mode.currentData()=='decimal'
    assert not page.restore_sounds.isChecked()
    page.save()
    assert store.settings()['earn_bps']==100 and store.settings()['allow_negative_stock'] is True
    assert store.store_profile()==profile and store.users_count()==1
    with pytest.raises(ValueError):stage_defaults(page,['business_data'])


def registered_fixture(tmp_path):
    root=tmp_path/'approved-games';root.mkdir();original=tmp_path/'original.nes';original.write_bytes(b'NES\x1a'+bytes(16396))
    digest=sha256(original.read_bytes()).hexdigest();copy=root/'roms'/digest[:16]/'original.nes';copy.parent.mkdir(parents=True);copy.write_bytes(original.read_bytes())
    manifest={'games':{digest:{'platform':'nes','filename':copy.name,'title':'테스트','scores':[{'score':123,'name':'예시','date':'2026-10-21'}]}},'emulators':{'nes':str(tmp_path/'external.exe')}}
    (root/'library.json').write_text(json.dumps(manifest),encoding='utf-8')
    return root,original,copy


def test_retired_cleanup_deletes_only_registered_copy_and_keeps_original_manifest_scores(tmp_path):
    root,original,copy=registered_fixture(tmp_path);manifest=(root/'library.json').read_bytes()
    extra=copy.parent/'not-registered.nes';extra.write_bytes(b'unrelated')
    assert len(registered_copies(root))==1
    assert delete_registered_copies(root)==['original.nes']
    assert not copy.exists() and original.exists() and extra.exists()
    assert (root/'library.json').read_bytes()==manifest
    assert delete_registered_copies(root)==[]


def test_cleanup_changed_payload_symlink_and_path_escape_fail_closed(tmp_path):
    root,original,copy=registered_fixture(tmp_path);payload=copy.read_bytes();copy.write_bytes(b'changed'+payload)
    with pytest.raises(ValueError):delete_registered_copies(root)
    assert copy.exists() and original.exists()
    copy.write_bytes(payload);copy.unlink()
    try:copy.symlink_to(original)
    except (OSError,NotImplementedError):pytest.skip('Symlinks are unavailable on this platform')
    with pytest.raises(ValueError):delete_registered_copies(root)
    assert original.exists()
    with pytest.raises(ValueError):delete_registered_copies(tmp_path)


def test_lucky_numbers_retains_drawing_without_arcade_entry(desktop):
    app,_,window=desktop
    from pos2.lucky_numbers import LuckyNumbersDialog
    dialog=LuckyNumbersDialog();dialog.show();app.processEvents()
    assert not [b for b in dialog.findChildren(QPushButton) if any(word in b.text() for word in ('오락실','게임','ROM'))]
    dialog.page.draw_five();dialog.page.finish_draw()
    assert len(dialog.page.results)==5 and all(len(set(row))==6 for row in dialog.page.results)
    dialog.close();assert not dialog.page.timer.isActive()


def test_main_x_cancel_keeps_window_and_yes_runs_exit_backup_once(desktop,monkeypatch):
    _,store,window=desktop;window._backup_runtime_enabled=True;calls=[]
    monkeypatch.setattr(store,'backup_on_exit',lambda:calls.append('backup'))
    prompts=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *args:(prompts.append(args[2]),QMessageBox.StandardButton.No)[1])
    assert not window.close() and window.isVisible() and not calls
    assert 'SY POS를 종료하시겠습니까?' in prompts[0] and '\n\n' in prompts[0] and '\\n' not in prompts[0] and not window._exit_confirmed
    monkeypatch.setattr(QMessageBox,'question',lambda *_:QMessageBox.StandardButton.Yes)
    assert window.close() and not window.isVisible() and calls==['backup'] and window._exit_confirmed


def test_exit_confirmation_real_dialog_defaults_to_no_and_dialog_x_cancels(desktop,monkeypatch):
    from PySide6.QtCore import QTimer
    app,store,window=desktop;window._backup_runtime_enabled=True;calls=[];dialogs=[]
    monkeypatch.setattr(store,'backup_on_exit',lambda:calls.append('backup'))
    def dismiss():
        box=app.activeModalWidget()
        assert isinstance(box,QMessageBox)
        dialogs.append(box.text())
        assert box.defaultButton()==box.button(QMessageBox.StandardButton.No)
        box.close()
    QTimer.singleShot(0,dismiss)
    assert not window.close()
    assert window.isVisible() and not calls and len(dialogs)==1 and not window._exit_confirmed
