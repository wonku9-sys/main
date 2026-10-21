"""Text + high-contrast tax badges; colour is never the only distinction."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QColor,QPixmap,QPainter,QFont,QIcon

def tax_style(mode):
    return ('과','과세','#B42318','#FFF0EE') if mode=='taxable' else ('면','면세','#167548','#EBF7EF')

def tax_icon(mode):
    letter,caption,foreground,background=tax_style(mode);pixmap=QPixmap(26,26);pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(foreground));painter.drawRoundedRect(QRectF(1,1,24,24),4,4)
    font=QFont();font.setPixelSize(16);font.setBold(True);painter.setFont(font);painter.setPen(QColor('#FFFFFF'));painter.drawText(QRectF(1,1,24,24),Qt.AlignmentFlag.AlignCenter,letter);painter.end();return QIcon(pixmap)

def style_tax_label(label,mode):
    letter,caption,foreground,background=tax_style(mode);label.setText(letter+' · '+caption)
    label.setStyleSheet(f'QLabel{{color:{foreground};background:{background};border:1px solid {foreground};border-radius:5px;padding:5px 10px;font-weight:700;}}')
    label.setToolTip(caption+' 상품 · 색상과 글자를 함께 표시합니다.')
