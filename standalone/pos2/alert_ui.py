"""High-visibility, readable schedule popup without exposing private health text."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QDialog,QFrame,QHBoxLayout,QLabel,QScrollArea,QVBoxLayout,QWidget
from .widgets import action
from .personal_icons import personal_icon


class ScheduleAlertDialog(QDialog):
    def __init__(self,records,parent=None):
        super().__init__(parent);self.setWindowTitle('기억할 일정이 있어요 · 일정 알림');self.resize(700,510)
        self.setStyleSheet('QDialog {background:#FFFBF3;} #alertBanner {background:#E9A632;border-radius:12px;} #alertTitle {font-size:25px;font-weight:700;color:#382E1B;} #alertCard {background:white;border:1px solid #E8D8BB;border-left:5px solid #D8962D;border-radius:8px;} QLabel {color:#4E493E;} QPushButton {padding:12px 20px;border-radius:9px;}')
        layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,20);layout.setSpacing(16)
        banner=QFrame();banner.setObjectName('alertBanner');head=QHBoxLayout(banner);head.setContentsMargins(18,18,18,18)
        icon=QLabel();icon.setPixmap(personal_icon('worklog').pixmap(44,44));head.addWidget(icon)
        title=QLabel('기억할 일정이 있어요');title.setObjectName('alertTitle');head.addWidget(title,1);layout.addWidget(banner)
        scroll=QScrollArea();scroll.setWidgetResizable(True);container=QWidget();cards=QVBoxLayout(container)
        for record in records:
            card=QFrame();card.setObjectName('alertCard');body=QVBoxLayout(card);body.setContentsMargins(16,14,16,14)
            when=QLabel(f"{record['date']}  ·  {record['time']}");when.setStyleSheet('color:#A66C16;font-size:15px;font-weight:600;');body.addWidget(when)
            heading=QLabel(record['title']);heading.setTextFormat(Qt.TextFormat.PlainText);heading.setWordWrap(True);heading.setStyleSheet('font-size:20px;font-weight:650;');body.addWidget(heading)
            detail=QLabel(record['notes'][:1000]);detail.setTextFormat(Qt.TextFormat.PlainText);detail.setWordWrap(True);body.addWidget(detail)
            if record.get('counter'):body.addWidget(QLabel(record['counter']))
            cards.addWidget(card)
        cards.addStretch();scroll.setWidget(container);layout.addWidget(scroll,1)
        note=QLabel('닫아도 일정은 첫화면 달력에 남습니다. 해마다 반복 일정은 다음 해에 다시 알려드립니다.');note.setWordWrap(True);layout.addWidget(note)
        close=action('확인했어요',self.accept,primary=True);layout.addWidget(close)
    def showEvent(self,event):
        super().showEvent(event);QApplication.alert(self)
