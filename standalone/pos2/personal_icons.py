"""Small original vector-style icons, rendered offline with Qt."""
from PySide6.QtCore import QRectF,Qt
from PySide6.QtGui import QColor,QIcon,QPainter,QPen,QPixmap


def personal_icon(kind):
    if kind=='lucky_numbers':
        from .menu_icons import menu_icon
        return menu_icon(kind)
    pix=QPixmap(48,48);pix.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    colors={'household':('#F9E8D4','#9E7247'),'diary':('#EEE3F7','#856399'),'worklog':('#E2EFEA','#517D6F'),'home':('#DFEFE9','#4F806F')}
    background,ink=colors.get(kind,colors['worklog']);painter.setBrush(QColor(background));painter.setPen(Qt.PenStyle.NoPen);painter.drawRoundedRect(QRectF(1,1,46,46),12,12)
    painter.setPen(QPen(QColor(ink),2.2));painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind=='household':
        painter.drawRoundedRect(QRectF(10,14,29,23),4,4);painter.drawRoundedRect(QRectF(28,21,13,10),2,2);painter.drawPoint(33,26);painter.drawLine(13,13,34,10)
    elif kind=='home':
        painter.drawLine(9,23,24,10);painter.drawLine(24,10,39,23);painter.drawRect(14,23,20,15);painter.drawRect(22,28,6,10)
    else:
        painter.drawRoundedRect(QRectF(12,10,26,29),3,3);painter.drawLine(18,11,18,39)
        for y in (19,25,31):painter.drawLine(23,y,32,y)
    painter.end();return QIcon(pix)
