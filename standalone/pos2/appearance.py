"""Subdued seasonal skins; financial warning/amount colors remain semantic."""
import re
import secrets

THEMES={'default':'기본 · 쿨그레이/세이지','spring':'봄 · 연녹색/꽃빛','summer':'여름 · 시원한 청록','autumn':'가을 · 차분한 황토/베이지','winter':'겨울 · 푸른 회색','random':'실행 시 랜덤 · 봄/여름/가을/겨울'}
COLORS={
    'default':('#E2E8E8','#D2DDE3','#D6E2D6','#DDE6E4','#ABB7BD','#F0F4F4'),
    'spring':('#DFE5D9','#E4DAE0','#CBD7C0','#D0D9CC','#ACB5A8','#F0F1E8'),
    'summer':('#D8E4E3','#D1DEE1','#BDD4D0','#CBDADB','#A1AFB2','#E9EEEA'),
    'autumn':('#E4DFD3','#D8CEC2','#D9CCAE','#DAD2C3','#B5AB9D','#EFEBDF'),
    'winter':('#DAE0E7','#CBD2DF','#C4CDDB','#CFD7DF','#A5ADB8','#E9ECF0'),
    'buddha':('#E4E0CF','#D8CCD9','#DCCDAA','#DBD5C8','#B3AA9C','#EFEBDE'),
    'christmas':('#DCE3D8','#D8C8CC','#BDD0BA','#D1DACD','#A3AEA3','#EAEEE4'),
}
SEASONS=('spring','summer','autumn','winter')
GROUPS=(('#D9DED8','#DCE1DA','#DCE3D9','#D9E0D5','#DCE4D8','#DDE2DC','#DCE3DA'),
        ('#C6CAD0','#DBDDD8','#DADDD7','#D0D6D0','#E1E7DE'),
        ('#D9DEBF','#D7DDBC','#E1E6CC','#D4DCBC'),
        ('#D9DFD6','#D6DED3','#DDE5D8','#DFE6DC','#D1DBCC','#D6DED4'),
        ('#A7ABA8','#A6ABAB','#A7ABA7','#A8AFAA'),
        ('#EFF2EC','#F1F3ED','#E8EDDF','#ECF0E8','#E9EFE4'))


def valid_theme(theme):
    if theme not in THEMES:raise ValueError('기본·계절·랜덤 스킨 중 하나를 선택하세요.')
    return theme


def recolor(css,theme):
    if theme not in COLORS:return css
    mapping={source.upper():color for sources,color in zip(GROUPS,COLORS[theme]) for source in sources}
    return re.sub(r'#[0-9a-fA-F]{6}',lambda m:mapping.get(m[0].upper(),m[0]),css)


def palette_css(css):
    """Resolve decorative colors through Qt's palette, not thousands of QSS resets."""
    roles=('window','button','midlight','alternate-base','mid','base')
    mapping={source.upper():'palette('+role+')' for sources,role in zip(GROUPS,roles) for source in sources}
    return re.sub(r'#[0-9a-fA-F]{6}',lambda m:mapping.get(m[0].upper(),m[0]),css)


def apply_widget(widget):
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance()
    if app is None or getattr(app,'_sy_applying_skin',False):return
    current=widget.styleSheet()
    if not current:return
    previous=getattr(widget,'_sy_skin_css',None)
    if previous!=current:widget._sy_base_css=current
    base=getattr(widget,'_sy_base_css',current);updated=palette_css(base)
    if updated!=current:
        app._sy_applying_skin=True
        try:widget.setStyleSheet(updated)
        finally:app._sy_applying_skin=False
    widget._sy_skin_css=updated


def refresh_widget_palette(widget):
    """QSS keeps per-widget palettes; refresh visible widgets once per skin."""
    from PySide6.QtWidgets import QApplication,QWidget
    app=QApplication.instance();generation=getattr(app,'_sy_palette_generation',0)
    if not generation or getattr(widget,'_sy_palette_generation',None)==generation or getattr(app,'_sy_polishing_palette',False):return
    app._sy_polishing_palette=True
    try:
        widget._sy_palette_generation=generation
        style=widget.style();style.unpolish(widget);widget.setPalette(app.palette());style.polish(widget);QWidget.update(widget)
    finally:app._sy_polishing_palette=False


def special_day(on):
    if (on.month,on.day)==(12,25):return 'christmas'
    if 1900<=on.year<=2050:
        from .recurrence import lunar_date
        if on==lunar_date(on.year,4,8):return 'buddha'
    return None


def apply_theme(mode,holiday=False,on=None,resolved=None):
    from PySide6.QtWidgets import QApplication
    from .app import STYLE
    from .branding import spin_button_style
    from PySide6.QtGui import QColor,QPalette
    valid_theme(mode);app=QApplication.instance()
    from datetime import date
    previous=getattr(app,'_sy_base_skin',None)
    base=resolved or (secrets.choice([key for key in SEASONS if key!=previous]) if mode=='random' else mode)
    theme=(special_day(on or date.today()) if holiday else None) or base
    app._sy_base_skin=base
    app._sy_skin=theme;app._sy_skin_mode=mode;app._sy_applying_skin=True
    try:
        palette=QPalette(app.palette())
        colors=COLORS.get(theme,tuple(sources[0] for sources in GROUPS))
        for role,color in zip((QPalette.ColorRole.Window,QPalette.ColorRole.Button,QPalette.ColorRole.Midlight,QPalette.ColorRole.AlternateBase,QPalette.ColorRole.Mid,QPalette.ColorRole.Base),colors):palette.setColor(role,QColor(color))
        # Subtle, skin-relative hover light rather than a dazzling fixed white.
        hover_base=QColor(colors[0]);palette.setColor(QPalette.ColorRole.Light,QColor(
            *(round(value*.82+255*.18) for value in (hover_base.red(),hover_base.green(),hover_base.blue()))))
        app.setPalette(palette)
        app._sy_palette_generation=getattr(app,'_sy_palette_generation',0)+1
        stylesheet=palette_css(STYLE+spin_button_style())
        if app.styleSheet()!=stylesheet:app.setStyleSheet(stylesheet)
    finally:app._sy_applying_skin=False
    # Each local stylesheet is converted once; further skin changes only emit
    # palette updates. New popups use the same palette on their first polish.
    if not getattr(app,'_sy_palette_locals_ready',False):
        for widget in app.allWidgets():apply_widget(widget)
        app._sy_palette_locals_ready=True
    from PySide6.QtWidgets import QWidget
    for root in app.topLevelWidgets():
        if root.isVisible():
            for widget in [root]+root.findChildren(QWidget):
                if widget.isVisible():refresh_widget_palette(widget)
    return theme
