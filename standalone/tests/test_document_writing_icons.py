from hashlib import sha256
import pytest
from PySide6.QtCore import QRectF,QSize
from PySide6.QtWidgets import QApplication
from pos2.menu_icons import DOCUMENT_ASSET,DOCUMENT_SHA256,DOCUMENT_KEYS,_document_image,family,menu_icon


@pytest.mark.parametrize('key,caption',zip(DOCUMENT_KEYS,('견적서','거래명세서','주문서')))
def test_document_menu_and_writing_buttons_use_matching_artwork(key,caption):
    app=QApplication.instance() or QApplication([])
    assert family(key)==family(caption)==family('새 '+caption+' 작성')==key
    assert not menu_icon(key).pixmap(QSize(32,32)).isNull()
    assert menu_icon(key).cacheKey()==menu_icon(caption).cacheKey()


def test_document_artwork_is_complete_transparent_and_packaged():
    assert sha256(DOCUMENT_ASSET.read_bytes()).hexdigest()==DOCUMENT_SHA256
    image=_document_image()
    assert image is not None and image.hasAlphaChannel() and image.width()==3*image.height()
    from package_source import source_files
    assert DOCUMENT_ASSET in set(source_files())
    app=QApplication.instance() or QApplication([])
    icons=[menu_icon(key) for key in DOCUMENT_KEYS]
    assert len({icon.cacheKey() for icon in icons})==3
    for icon in icons:
        image=icon.pixmap(32,32).toImage()
        assert image.pixelColor(0,0).alpha()==0


def test_connection_icons_match_captions_and_keep_distinct_artwork():
    from pos2.menu_icons import CONNECTION_ASSET,CONNECTION_SHA256,CONNECTION_KEYS,CONNECTION_CAPTIONS,_connection_image
    app=QApplication.instance() or QApplication([])
    assert sha256(CONNECTION_ASSET.read_bytes()).hexdigest()==CONNECTION_SHA256
    assert _connection_image() is not None
    from package_source import source_files
    assert CONNECTION_ASSET in set(source_files())
    for caption,key in CONNECTION_CAPTIONS.items():
        assert family(caption)==key
        assert menu_icon(caption).cacheKey()==menu_icon(key).cacheKey()
    assert len({menu_icon(key).cacheKey() for key in CONNECTION_KEYS})==5


def test_real_connection_dialog_buttons_have_matching_icons_and_explanations(tmp_path):
    from PySide6.QtWidgets import QPushButton
    from pos2.shared_ui import NetworkSettingsDialog
    from pos2.menu_icons import CONNECTION_CAPTIONS
    app=QApplication.instance() or QApplication([])
    dialog=NetworkSettingsDialog(tmp_path/'connection.json')
    try:
        buttons={button.text():button for button in dialog.findChildren(QPushButton)}
        for caption in CONNECTION_CAPTIONS:
            if caption=='기존 PC 인증키 생성':continue  # older caption alias
            button=buttons[caption]
            assert button.icon().cacheKey()==menu_icon(caption).cacheKey()
            assert len(button.toolTip())>len(caption) and button.toolTip()==button.statusTip()
    finally:dialog.deleteLater();app.processEvents()
