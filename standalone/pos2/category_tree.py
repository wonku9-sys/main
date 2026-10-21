"""Compact three-level folder tree, with dotted branches and +/- controls."""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QProxyStyle, QStyle, QTreeWidget


class CategoryTreeStyle(QProxyStyle):
    def __init__(self, parent):
        super().__init__("Fusion")
        self.setParent(parent)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorBranch:
            return super().drawPrimitive(element, option, painter, widget)
        painter.save()
        rect, flags = option.rect, option.state
        x, y = rect.center().x(), rect.center().y()
        painter.setPen(QPen(QColor("#A9B4B9"), 1, Qt.PenStyle.DotLine))
        if flags & QStyle.StateFlag.State_Sibling:
            painter.drawLine(x, rect.top(), x, rect.bottom())
        elif flags & QStyle.StateFlag.State_Item:
            painter.drawLine(x, rect.top(), x, y)
        if flags & QStyle.StateFlag.State_Item:
            painter.drawLine(x, y, rect.right(), y)
        if flags & QStyle.StateFlag.State_Children:
            painter.setPen(QColor("#8E9B9F"))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(QRect(x - 4, y - 4, 8, 8))
            painter.setPen(QColor("#4D5E65"))
            painter.drawLine(x - 2, y, x + 2, y)
            if not flags & QStyle.StateFlag.State_Open:
                painter.drawLine(x, y - 2, x, y + 2)
        painter.restore()


def folder_icon(level, active=True):
    color = ("#EDCF45", "#B8BEC4", "#A6CB5B")[level - 1] if active else "#D5DADC"
    pixmap = QPixmap(19, 17)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(color).darker(140))
    painter.setBrush(QColor(color).lighter(120))
    painter.drawRoundedRect(2, 3, 7, 5, 1, 1)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(2, 6, 15, 9, 1.5, 1.5)
    painter.end()
    return QIcon(pixmap)


class CategoryTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyle(CategoryTreeStyle(self))
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setUniformRowHeights(True)
        self.setIndentation(20)
        self.setStyleSheet("QTreeWidget::item { padding:2px 4px; min-height:20px; }")
