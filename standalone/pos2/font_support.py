"""A redistributable Korean font keeps screen, PDF and labels consistent."""
from pathlib import Path
import sys

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics


_family = None


def font_family():
    global _family
    if _family is None:
        source = Path(__file__).resolve().parent / "assets" / "NotoSansKR-Regular.ttf"
        identifier = QFontDatabase.addApplicationFont(str(source))
        families = QFontDatabase.applicationFontFamilies(identifier) if identifier >= 0 else []
        if not families:
            raise RuntimeError("한글 글꼴을 불러오지 못했습니다. ZIP 전체를 다시 압축 해제하고 실행하세요.")
        _family = families[0]
    return _family


def verify_glyphs():
    font = regular_font(10)
    metrics = QFontMetrics(font)
    sample = "서영상품매입매출재고한글ABC0123456789"
    if not all(metrics.inFontUcs4(ord(character)) for character in sample):
        raise RuntimeError("한글/영문 글꼴 출력 검증에 실패했습니다.")
    return font


def regular_font(size=10):
    font=QFont(font_family(),size)
    # A static Regular instance keeps the body weight consistent offline.
    font.setWeight(QFont.Weight.Normal)
    return font


def document_font(size=10):
    """Windows Qt outlines memory-loaded fonts even when embedding is on.

    Installed Malgun Gothic embeds searchable Korean text correctly. Use that
    host font for documents only, retaining the bundled offline UI font and
    its complete Korean fallback if the native family is unavailable.
    """
    if sys.platform=='win32' and 'Malgun Gothic' in QFontDatabase.families():
        font=QFont('Malgun Gothic',size);font.setWeight(QFont.Weight.Normal)
        return font
    return regular_font(size)
