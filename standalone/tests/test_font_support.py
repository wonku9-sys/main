from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from pos2.font_support import font_family, verify_glyphs


def test_bundled_korean_and_latin_font_has_real_glyphs():
    app = QApplication.instance() or QApplication([])
    font = verify_glyphs()
    assert "Noto Sans KR" in font_family()
    metrics = QFontMetrics(font)
    assert metrics.horizontalAdvance("서영 POS 12345") > 0
    assert app is not None
