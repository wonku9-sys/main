"""Real raster assets, high-DPI menus and an explicitly named delivery variant."""
from hashlib import sha256
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor,QImage,QPainter
from pos2.menu_icons import ATLAS,ATLAS_KEYS,ATLAS_SHA256,_atlas_image,menu_icon,family


def test_actual_transparent_30_icon_asset_is_complete_and_high_resolution():
    app=QApplication.instance() or QApplication([])
    atlas=_atlas_image()
    assert atlas is not None and atlas.hasAlphaChannel() and atlas.size()==QSize(1374,1145)
    assert atlas.format()==QImage.Format.Format_ARGB32_Premultiplied
    assert sha256(ATLAS.read_bytes()).hexdigest()==ATLAS_SHA256
    assert len(ATLAS_KEYS)==len(set(ATLAS_KEYS))==30
    images=[]
    from pos2.menu_icons import _family_icon
    for key in ATLAS_KEYS:
        icon=_family_icon(key);pix=icon.pixmap(QSize(108,108))
        assert not pix.isNull() and pix.width()==108 and pix.height()==108
        image=pix.toImage();assert image.pixelColor(0,0).alpha()<20
        images.append(bytes(image.constBits()))
    assert len(set(images))==30


def test_icon_corners_use_the_actual_skin_background_not_a_white_backplate():
    app=QApplication.instance() or QApplication([])
    for background in ('#D2DDE3','#D6E2D6','#CBD2DF','#D8CEC2'):
        canvas=QImage(36,36,QImage.Format.Format_ARGB32_Premultiplied);canvas.fill(QColor(background))
        painter=QPainter(canvas);painter.drawPixmap(0,0,menu_icon('상품장').pixmap(QSize(36,36)));painter.end()
        for x,y in ((0,0),(35,0),(0,35),(35,35)):
            color=canvas.pixelColor(x,y);expected=QColor(background)
            assert max(abs(color.red()-expected.red()),abs(color.green()-expected.green()),abs(color.blue()-expected.blue()))<=2


def test_payment_actions_are_visually_distinct_not_identical_coin_icons():
    app=QApplication.instance() or QApplication([])
    labels=('결제처리','카드 수기결제','당일 결제 정정','선택 결제 취소','계좌이체')
    assert [family(label) for label in labels]==['money','card','edit','waste','transfer']
    assert len({menu_icon(label).cacheKey() for label in labels})==5


def test_package_name_preserves_current_version_and_the_requested_icon3d_suffix():
    from package_source import NAME,source_files
    from pos2 import __version__
    assert NAME==f'SY-POS-v{__version__}-source-아이콘3d.zip'
    names={file.name for file in source_files()}
    assert {'menu-icons-3d.png','MENU_ICONS_3D.md','sy-pos-wordmark-3d.png','output-icons-real3d.png','OUTPUT_ICONS_3D.md','diary-real3d.png','household-real3d.png','PERSONAL_ICONS_3D.md'}<=names


def test_source_archive_and_checksum_support_the_korean_suffix(tmp_path):
    from package_source import package
    from zipfile import ZipFile
    archive=package(tmp_path)
    checksum=archive.with_suffix(archive.suffix+'.sha256').read_text(encoding='utf-8')
    assert checksum==f'{sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n'
    with ZipFile(archive) as stream:
        assert stream.testzip() is None
        assert 'SY-POS-source/standalone/pos2/assets/menu-icons-3d.png' in stream.namelist()
        assert 'SY-POS-source/standalone/pos2/assets/sy-pos-wordmark-3d.png' in stream.namelist()
        assert 'SY-POS-source/standalone/pos2/assets/output-icons-real3d.png' in stream.namelist()
        assert 'SY-POS-source/standalone/pos2/assets/diary-real3d.png' in stream.namelist()
        assert 'SY-POS-source/standalone/pos2/assets/household-real3d.png' in stream.namelist()
        assert not any(name.lower().endswith(('.db','.key','.dat','.idx')) for name in stream.namelist())
