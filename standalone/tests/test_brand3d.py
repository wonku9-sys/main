"""The same offline, transparent 3D wordmark in the scan toolbar and login."""
from hashlib import sha256

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel

from pos2.app import LoginDialog, MainWindow
from pos2.branding import WORDMARK, wordmark_image, wordmark_pixmap
from pos2.store import Store


def test_wordmark_is_a_real_transparent_offline_high_resolution_asset():
    app = QApplication.instance() or QApplication([])
    image = wordmark_image()
    assert not image.isNull() and image.hasAlphaChannel()
    assert image.width() == 2172 and image.height() == 724
    assert image.format() == QImage.Format.Format_ARGB32_Premultiplied
    assert sha256(WORDMARK.read_bytes()).hexdigest() == '60fba2d4721ac0c999a23d1655b3d5cfd9189e05531fb6fd6a262efebe5a8797'
    for x, y in ((0, 0), (2171, 0), (0, 723), (2171, 723)):
        assert image.pixelColor(x, y).alpha() == 0
    for large, width, height in ((False, 156, 52), (True, 216, 72)):
        pixmap = wordmark_pixmap(large)
        assert not pixmap.isNull() and pixmap.devicePixelRatio() == 2
        assert pixmap.width() / 2 == width and pixmap.height() / 2 == height
        assert wordmark_pixmap(large).cacheKey() == pixmap.cacheKey()
    from package_source import source_files
    assert WORDMARK in set(source_files())


def test_toolbar_logo_follows_scan_and_login_uses_the_same_wordmark(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'brand.db')
    store.setup_admin('owner', '관리자', 'Owner-Password-2026!')
    window = MainWindow(store)
    login = LoginDialog(store)
    try:
        window.show(); app.processEvents()
        actions = window.toolbar.actions()
        scan = next(action for action in actions if action.text() == 'F8 스캔')
        assert actions[actions.index(scan) + 1] is window.toolbar_brand_action
        logo = window.toolbar_brand.findChild(QLabel, 'syLogo')
        assert logo.accessibleName() == 'SY POS 3D 로고'
        assert logo.graphicsEffect() is None # Reflections are baked in, not an animated filter.
        assert logo.pixmap().cacheKey() == wordmark_pixmap().cacheKey()
        assert window.toolbar_brand.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert 'background:transparent' in window.toolbar_brand.styleSheet()
        for width, height in ((940, 640), (1180, 800), (1500, 930), (1900, 1000), (940, 640)):
            window.resize(width, height); app.processEvents()
            scan_rect = window.toolbar.actionGeometry(scan)
            logo_rect = window.toolbar.actionGeometry(window.toolbar_brand_action)
            assert not logo_rect.isEmpty() and logo_rect.left() >= scan_rect.right()
            assert window.toolbar.rect().contains(logo_rect)
            assert window.toolbar_brand.isVisible()
            # The logo, not merely its expanding action, is centered between
            # the last scan button and the toolbar's right edge on every resize.
            center=logo.mapTo(window.toolbar,logo.rect().center()).x()
            target=(scan_rect.right()+window.toolbar.rect().right())/2
            assert abs(center-target)<=3,(width,center,target)
            assert window.toolbar_brand_space.width()>=window.toolbar_brand.width()
        login.show(); app.processEvents()
        choices = login.findChild(QLabel, 'syLogo')
        assert choices.pixmap().cacheKey() == wordmark_pixmap(True).cacheKey()
        panel = login.findChild(type(window.toolbar_brand), 'loginChoices')
        assert panel.rect().contains(choices.mapTo(panel, QPoint()))
        assert panel.rect().contains(choices.mapTo(panel, choices.rect().bottomRight()))
        assert login.code.isVisible() and login.password.isVisible()
        assert set(login.login_choices) == {'home', 'household', 'diary'}
        from pos2.branding import LOGIN_CHOICES_STYLE
        assert '#243C48' in LOGIN_CHOICES_STYLE and '#365563' in LOGIN_CHOICES_STYLE
        assert '#CADCD2' in LOGIN_CHOICES_STYLE and '#EEE9D8' not in panel.styleSheet()
        for key in ('diary','household','home'):
            login.login_choices[key].click();app.processEvents()
            assert login.selected_target==key
            assert sum(button.isChecked() for button in login.login_choices.values())==1
            assert login.login_choices[key].isChecked()
            assert {'home':'매장 업무 로그인','household':'가계부로 로그인','diary':'일기장으로 로그인'}[key]==login.buttons.button(login.buttons.StandardButton.Save).text()
    finally:
        login.reject(); login.deleteLater()
        window.navigation.suspended = True
        window.navigation.disable()
        window.close(); window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents(); store.close()
