"""Personal entry cards must not paint over primary-button backgrounds."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint,Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton

from pos2.appearance import COLORS,apply_theme
from pos2.diary_ui import DiaryPage
from pos2.household_ui import HouseholdPage


def contrast(a,b):
    def luminance(color):
        rgb=[value/255 for value in (color.red(),color.green(),color.blue())]
        linear=[value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4 for value in rgb]
        return sum(value*weight for value,weight in zip(linear,(.2126,.7152,.0722)))
    low,high=sorted((luminance(a),luminance(b)))
    return (high+.05)/(low+.05)


@pytest.mark.parametrize('page_type',[DiaryPage,HouseholdPage])
@pytest.mark.parametrize('theme',tuple(COLORS))
def test_primary_entry_text_contrasts_with_actual_painted_background(page_type,theme):
    app=QApplication.instance() or QApplication([])
    page=page_type(SimpleNamespace(store=None));page.resize(1100,720)
    try:
        apply_theme(theme if theme not in ('buddha','christmas') else 'default',resolved=theme)
        page.show();app.processEvents()
        button=page.findChild(QPushButton,'primary')
        for state in ('normal','hover','focus','disabled'):
            button.setEnabled(state!='disabled')
            if state=='hover':QTest.mouseMove(button,button.rect().center())
            else:QTest.mouseMove(page,QPoint(2,2))
            if state=='focus':button.setFocus(Qt.FocusReason.TabFocusReason)
            else:button.clearFocus()
            app.processEvents()
            image=button.grab().toImage()
            background=image.pixelColor(8,image.height()//2)
            group=QPalette.ColorGroup.Disabled if state=='disabled' else QPalette.ColorGroup.Active
            foreground=button.palette().color(group,QPalette.ColorRole.ButtonText)
            assert contrast(foreground,background)>=4.5,(page_type.__name__,theme,state,foreground.name(),background.name())
    finally:
        page.close();page.deleteLater();app.processEvents();apply_theme('default')
