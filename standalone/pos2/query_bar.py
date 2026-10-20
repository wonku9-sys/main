"""One conspicuous, non-scrolling query position for every business view."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter,QPalette
from PySide6.QtWidgets import QFrame,QHBoxLayout,QGridLayout,QLabel,QWidget,QSizePolicy
from .widgets import action


class QueryContext(QLabel):
    """Keep the full accessible title without pushing the central action away."""
    def setText(self,text):
        super().setText(text);self.setToolTip(text)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        text=self.fontMetrics().elidedText(self.text(),Qt.TextElideMode.ElideRight,self.contentsRect().width())
        painter.drawText(self.contentsRect(),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)
        painter.end()


class QueryBar(QFrame):
    def __init__(self,caption,callback,parent=None,home=None,close=None):
        super().__init__(parent);self.setObjectName('fixedQueryBar')
        self.setStyleSheet('''QFrame#fixedQueryBar {background:#FFFFFF;border-bottom:1px solid #D8E3DB;}
            QPushButton#queryButton {color:#243B30;background:#F6CE63;border:1px solid #C39734;border-radius:8px;font-size:15px;font-weight:700;padding:8px 24px;min-height:24px;}
            QPushButton#queryButton:hover {color:#1A3024;background:#FFDA78;border-color:#A77919;}
            QPushButton#queryButton:pressed {color:#1A3024;background:#E6B94C;}
            QPushButton#queryButton:focus {border:2px solid #315F49;}
            QPushButton#queryButton:disabled {color:#536457;background:#E3E8E3;border-color:#B9C9BE;}
        ''')
        layout=QGridLayout(self);layout.setContentsMargins(14,6,14,6);layout.setHorizontalSpacing(10)
        # Symmetric side columns keep the button at the bar's actual midpoint,
        # even when only the popup has home/close controls or a title is long.
        left,right=QWidget(self),QWidget(self)
        for panel in (left,right):panel.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        left_layout,right_layout=QHBoxLayout(left),QHBoxLayout(right)
        for row in (left_layout,right_layout):row.setContentsMargins(0,0,0,0);row.setSpacing(10)
        self.home_button=action('첫화면',home) if home else None
        if self.home_button:left_layout.addWidget(self.home_button)
        self.context=QueryContext(caption);self.context.setTextFormat(Qt.TextFormat.PlainText);self.context.setToolTip(caption)
        self.context.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.context.setStyleSheet('color:#285442;font-weight:600;');left_layout.addWidget(self.context,1)
        right_layout.addStretch()
        self.query_button=action('조회 (F5)',callback);self.query_button.setObjectName('queryButton')
        self.query_button.setMinimumWidth(140)
        self.query_button.setToolTip('현재 화면의 검색어·분류·공급사·기간 조건으로 조회합니다. 저장하지 않은 편집은 먼저 확인합니다.\n단축키: F5')
        self.close_button=action('이 창 닫기',close) if close else None
        if self.close_button:right_layout.addWidget(self.close_button)
        layout.addWidget(left,0,0);layout.addWidget(self.query_button,0,1,Qt.AlignmentFlag.AlignCenter);layout.addWidget(right,0,2)
        layout.setColumnStretch(0,1);layout.setColumnStretch(2,1)
