"""Dedicated private-desk artwork is shared, transparent and display-only."""
from hashlib import sha256

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication,QLabel,QPushButton

from pos2 import menu_icons as icons
from pos2.personal_icons import personal_icon


def test_personal_artwork_is_real_offline_high_resolution_and_packaged():
    app=QApplication.instance() or QApplication([])
    from package_source import source_files
    files=set(source_files())
    for kind,path in icons.PERSONAL_ASSETS.items():
        image=icons._personal_image(kind)
        assert image is not None and image.size()==QSize(1254,1254)
        assert image.format()==QImage.Format.Format_ARGB32_Premultiplied
        assert path in files and sha256(path.read_bytes()).hexdigest()==icons.PERSONAL_SHA256[kind]
        assert icons._personal_image(kind).cacheKey()==image.cacheKey()
    assert icons.family('wallet')==icons.family('household')=='wallet'
    assert personal_icon('diary').cacheKey()!=personal_icon('household').cacheKey()


@pytest.mark.parametrize('size',(18,26,36,44,52,88,108))
def test_private_icons_have_transparent_edges_at_every_used_size(size):
    app=QApplication.instance() or QApplication([])
    for kind in ('diary','household'):
        image=personal_icon(kind).pixmap(QSize(size,size)).toImage()
        assert image.size()==QSize(size,size)
        assert all(image.pixelColor(x,y).alpha()==0 for x in range(size) for y in (0,size-1))
        assert all(image.pixelColor(x,y).alpha()==0 for y in range(size) for x in (0,size-1))


def test_private_headings_login_shortcuts_and_window_icons_use_same_art(tmp_path):
    from pos2.app import MainWindow,LoginDialog
    from pos2.store import Store
    from pos2.diary_ui import DiaryPage,DiaryDialog
    from pos2.household_ui import HouseholdPage,HouseholdDialog
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'private-art.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    store.save_popup_sound_enabled(False);store.save_diary_music_preferences(False,0)
    store.setup_diary('Private-Diary-2026!','Private-Diary-2026!')
    store.setup_household('Private-House-2026!','Private-House-2026!')
    window=MainWindow(store);login=LoginDialog(store)
    pages=(DiaryPage(window),HouseholdPage(window))
    dialogs=(DiaryDialog(store,store.unlock_diary('Private-Diary-2026!'),window),
             HouseholdDialog(store,store.unlock_household('Private-House-2026!'),window))
    try:
        window.show();app.processEvents()
        for kind,page,dialog,title in zip(('diary','household'),pages,dialogs,('일기장','가계부')):
            icon=personal_icon(kind)
            assert login.login_choices[kind].icon().cacheKey()==icon.cacheKey()
            assert window.items[kind].icon(0).cacheKey()==icon.cacheKey()
            shortcut=next(button for button in window.personal_panel.findChildren(QPushButton) if button.text()==title)
            assert shortcut.icon().cacheKey()==icon.cacheKey() and shortcut.iconSize()==QSize(26,26)
            for widget,size in ((page,52),(dialog,44)):
                badge=widget.findChild(QLabel,kind+'3dBadge')
                assert badge is not None and badge.size()==QSize(size,size)
                assert badge.pixmap().devicePixelRatio()==2 and 'background:transparent' in badge.styleSheet()
            assert dialog.windowIcon().cacheKey()==icon.cacheKey()
    finally:
        for dialog in dialogs:dialog.wipe();dialog.deleteLater()
        for page in pages:page.deleteLater()
        login.deleteLater();window.navigation.suspended=True;window.navigation.disable()
        window.close();window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()
