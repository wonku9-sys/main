"""Optional ISO date text with a real calendar and eight-digit normalization."""
from PySide6.QtCore import QDate,QPoint
from PySide6.QtWidgets import QCalendarWidget,QLineEdit,QMenu,QWidgetAction
from .menu_icons import menu_icon


class DateInput(QLineEdit):
    def __init__(self,value='',parent=None):
        super().__init__(str(value or ''),parent)
        self.setPlaceholderText('2026-10-20 또는 20261020')
        self.setMaxLength(10);self.setClearButtonEnabled(True)
        button=self.addAction(menu_icon('calendar'),QLineEdit.ActionPosition.TrailingPosition)
        button.setToolTip('달력에서 년·월·일 선택');button.triggered.connect(self.open_calendar)
        self.textChanged.connect(self.normalize);self.normalize()
    def normalize(self,*_):
        raw=self.text().strip()
        if len(raw)==8 and raw.isascii() and raw.isdigit():
            date=QDate.fromString(raw,'yyyyMMdd')
            if date.isValid():self.setText(date.toString('yyyy-MM-dd'))
    def open_calendar(self):
        menu=QMenu(self);calendar=QCalendarWidget(menu);calendar.setGridVisible(True)
        selected=QDate.fromString(self.text().strip(),'yyyy-MM-dd');calendar.setSelectedDate(selected if selected.isValid() else QDate.currentDate())
        item=QWidgetAction(menu);item.setDefaultWidget(calendar);menu.addAction(item)
        def choose(date):self.setText(date.toString('yyyy-MM-dd'));menu.close()
        calendar.clicked.connect(choose)
        self._calendar_menu=menu;menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.mapToGlobal(QPoint(0,self.height())))
