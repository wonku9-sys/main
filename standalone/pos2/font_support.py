"""A redistributable Korean font keeps screen, PDF and labels consistent."""
from pathlib import Path

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
    # Qt 6.8 can register this variable font's named instances only as "Thin".
    # Select its weight axis explicitly so body text remains readable offline.
    font.setVariableAxis(QFont.Tag.fromString('wght'),400)
    return font
