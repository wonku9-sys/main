"""Realistic printer/workbook artwork without clipping or command changes."""
from hashlib import sha256

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from pos2 import menu_icons as icons
from pos2.widgets import output_icon


def test_output_artwork_has_integrity_and_complete_nonoverlapping_source_regions():
    app=QApplication.instance() or QApplication([])
    image=icons._output_atlas_image()
    assert image is not None and image.size()==QSize(1774,887)
    assert image.format()==QImage.Format.Format_ARGB32_Premultiplied
    assert sha256(icons.OUTPUT_ATLAS.read_bytes()).hexdigest()==icons.OUTPUT_ATLAS_SHA256
    assert icons.OUTPUT_RECTS[0][0]+icons.OUTPUT_RECTS[0][2]<icons.OUTPUT_RECTS[1][0]
    for x,y,w,h in icons.OUTPUT_RECTS:
        assert x>=0 and y>=0 and x+w<=image.width() and y+h<=image.height()
        # All four sides have alpha-free margins: neither object is cut in half.
        assert all(image.pixelColor(px,py).alpha()<20 for px in range(x,x+w) for py in (y,y+h-1))
        assert all(image.pixelColor(px,py).alpha()<20 for py in range(y,y+h) for px in (x,x+w-1))
    from package_source import source_files
    assert icons.OUTPUT_ATLAS in set(source_files())


def test_output_buttons_use_cached_realistic_icons_and_preserve_size_help_and_click():
    app=QApplication.instance() or QApplication([])
    calls=[];buttons=[]
    try:
        for text,key,family in (('인쇄','Ctrl+P','printer'),('엑셀 저장','Ctrl+E','excel')):
            assert icons.family(family)==family
            button=output_icon(text,lambda checked=False,label=text:calls.append(label));buttons.append(button)
            assert button.icon().cacheKey()==icons.menu_icon(family).cacheKey()
            assert button.iconSize()==QSize(28,28) and button.size()==QSize(36,32)
            assert button.isFlat() and not button.text() and key in button.toolTip()
            image=button.icon().pixmap(QSize(108,108)).toImage()
            assert image.width()==108 and image.height()==108
            for x,y in ((0,0),(107,0),(0,107),(107,107)):
                assert image.pixelColor(x,y).alpha()==0
            button.click()
        assert calls==['인쇄','엑셀 저장']
        assert buttons[0].icon().cacheKey()!=buttons[1].icon().cacheKey()
    finally:
        for button in buttons:button.deleteLater()


def test_missing_dedicated_artwork_falls_back_to_the_existing_icons(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    with monkeypatch.context() as patch:
        patch.setattr(icons,'OUTPUT_ATLAS',tmp_path/'missing.png')
        icons._output_atlas_image.cache_clear();icons._family_icon.cache_clear()
        assert icons._output_atlas_image() is None
        assert all(not icons._family_icon(key).isNull() for key in icons.OUTPUT_KEYS)
    icons._output_atlas_image.cache_clear();icons._family_icon.cache_clear()
