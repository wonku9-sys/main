"""Install Qt's own Korean widget strings, including standard context menus."""
from pathlib import Path
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator


def korean_catalog_path():
    if getattr(sys, 'frozen', False):
        return Path(__file__).with_name('translations') / 'qtbase_ko.qm'
    return Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / 'qtbase_ko.qm'


def install_korean_ui(app):
    """Keep the translator alive for the entire app, independent of Windows language."""
    QLocale.setDefault(QLocale('ko_KR'))
    existing = getattr(app, '_sy_korean_translator', None)
    if existing is not None:
        return existing
    translator = QTranslator(app)
    if not translator.load(str(korean_catalog_path())):
        raise RuntimeError('한국어 메뉴 번역 파일을 읽을 수 없습니다. 프로그램 ZIP 전체를 다시 압축 해제하세요.')
    if not app.installTranslator(translator):
        raise RuntimeError('한국어 메뉴 번역을 적용할 수 없습니다.')
    app._sy_korean_translator = translator
    return translator
