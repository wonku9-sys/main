"""One conspicuous, non-scrolling query position for every business view."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame,QHBoxLayout,QLabel
from .widgets import action

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
        layout=QHBoxLayout(self);layout.setContentsMargins(14,6,14,6);layout.setSpacing(10)
        if home:layout.addWidget(action('첫화면',home))
        self.context=QLabel(caption);self.context.setTextFormat(Qt.TextFormat.PlainText)
        self.context.setStyleSheet('color:#285442;font-weight:600;');layout.addWidget(self.context,1)
        self.query_button=action('조회 (F5)',callback);self.query_button.setObjectName('queryButton')
        self.query_button.setMinimumWidth(140)
        self.query_button.setToolTip('현재 화면의 검색어·분류·공급사·기간 조건으로 조회합니다. 저장하지 않은 편집은 먼저 확인합니다.\n단축키: F5')
        layout.addWidget(self.query_button)
        if close:layout.addWidget(action('이 창 닫기',close))
