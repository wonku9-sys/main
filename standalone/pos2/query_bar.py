"""One conspicuous, non-scrolling query position for every business view."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter,QPalette,QColor,QLinearGradient,QPen
from PySide6.QtWidgets import QFrame,QHBoxLayout,QVBoxLayout,QGridLayout,QLabel,QWidget,QSizePolicy,QScrollArea,QPushButton
from .widgets import action

QUERY_BAR_HEIGHT=38


class QueryContext(QLabel):
    """Keep the full accessible title without pushing the central action away."""
    def setText(self,text):
        super().setText(text);self.setToolTip(text);self.setStatusTip(text)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        rect=self.contentsRect().adjusted(4,0,-4,0)
        badge=self.property('menuBadge')
        if badge:
            gradient=QLinearGradient(0,0,0,self.height());gradient.setColorAt(0,QColor('#EDF4FB'));gradient.setColorAt(.5,QColor('#D6E4F4'));gradient.setColorAt(1,QColor('#B6CDE5'))
            painter.setPen(QPen(QColor('#8DA6BF')));painter.setBrush(gradient);painter.drawRoundedRect(self.rect().adjusted(0,0,-1,-1),2,2)
            painter.setPen(QColor('#253B58'));font=painter.font();font.setBold(True);painter.setFont(font)
        text=self.fontMetrics().elidedText(self.text(),Qt.TextElideMode.ElideRight,rect.width())
        painter.drawText(rect,(Qt.AlignmentFlag.AlignCenter if badge else Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter),text)
        painter.end()


class QueryBar(QFrame):
    """The page-title row, pinned below (never inside) the navigation strip."""
    def __init__(self,caption,callback,parent=None,description=''):
        super().__init__(parent);self.setObjectName('fixedQueryBar')
        self.setStyleSheet('''QFrame#fixedQueryBar {background:#C6CAD0;border-top:1px solid #98A1A8;border-bottom:1px solid #87939C;}
            QFrame#fixedQueryBar QPushButton {padding:2px 5px;min-height:20px;}
            QFrame#fixedQueryBar QComboBox {padding:2px 5px;min-height:20px;}
            QPushButton#queryButton {color:#243B30;background:#F6CE63;border:1px solid #C39734;border-radius:3px;font-size:14px;font-weight:600;padding:2px 13px;min-height:20px;}
            QPushButton#queryButton:hover {color:#1A3024;background:#FFDA78;border-color:#A77919;}
            QPushButton#queryButton:pressed {color:#1A3024;background:#E6B94C;}
            QPushButton#queryButton:focus {border:2px solid #315F49;}
            QPushButton#queryButton:disabled {color:#536457;background:#E3E8E3;border-color:#B9C9BE;}
        ''')
        self.setFixedHeight(QUERY_BAR_HEIGHT)
        # Keep the 38px strip fixed while providing the 32px output buttons
        # their full height inside the frame's two 1px borders.
        layout=QGridLayout(self);layout.setContentsMargins(8,2,8,2);layout.setHorizontalSpacing(8)
        # Symmetric side columns keep the button at the bar's actual midpoint,
        # even when the title is long or the action count varies by menu.
        left,right=QWidget(self),QWidget(self)
        for panel in (left,right):panel.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        left_layout,right_layout=QVBoxLayout(left),QHBoxLayout(right)
        for row in (left_layout,right_layout):row.setContentsMargins(0,0,0,0);row.setSpacing(3)
        self.context=QueryContext(caption);self.context.setTextFormat(Qt.TextFormat.PlainText);self.context.setToolTip(caption)
        self.context.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.context.setObjectName('pageTitle');self.context.setStyleSheet('color:#285442;font-size:17px;font-weight:600;');left_layout.addWidget(self.context,1)
        self.description=QueryContext(description);self.description.setToolTip(description)
        self.description.setObjectName('muted');self.description.setMinimumWidth(0)
        self.description.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        left_layout.addWidget(self.description,1)
        self.left_layout=left_layout
        # Overflow stays reachable without growing a side column and pushing
        # the central query away from the geometric centre on narrow screens.
        self.action_scroll=QScrollArea(right);self.action_scroll.setFrameShape(QFrame.Shape.NoFrame)
        from PySide6.QtGui import QColor
        palette=self.action_scroll.palette();palette.setColor(QPalette.ColorRole.Window,QColor('#C6CAD0'));self.action_scroll.setPalette(palette)
        self.action_scroll.viewport().setPalette(palette)
        self.action_scroll.setWidgetResizable(True);self.action_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.action_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.action_scroll.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        # A native ~14px horizontal bar used to consume half this fixed-height
        # strip, clipping even 20px action icons. Keep a usable slim track.
        self.action_scroll.setStyleSheet('''QScrollArea{background:transparent;border:0;}
            QScrollBar:horizontal{height:4px;background:palette(window);margin:0;}
            QScrollBar::handle:horizontal{background:palette(mid);min-width:20px;}
            QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}
            QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}''')
        actions=QWidget();actions.setPalette(palette);actions.setAutoFillBackground(True)
        self.actions=QHBoxLayout(actions);self.actions.setContentsMargins(0,0,0,0);self.actions.setSpacing(4)
        self.actions.addStretch();self.action_scroll.setWidget(actions);right_layout.addWidget(self.action_scroll,1)
        # Print/Excel stay at the right edge, never inside a scrolling viewport.
        self.output_panel=QWidget(right);self.output_panel.setObjectName('fixedOutputIcons')
        self.output_panel.setStyleSheet('QWidget#fixedOutputIcons{background:transparent;border:0;}')
        self.output_panel.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred)
        self.output_actions=QHBoxLayout(self.output_panel)
        self.output_actions.setContentsMargins(0,0,0,0);self.output_actions.setSpacing(4)
        right_layout.addWidget(self.output_panel);self.output_panel.hide()
        self.query_button=action('조회 (F5)',callback);self.query_button.setObjectName('queryButton')
        self.query_button.setMinimumWidth(110)
        self.query_button.setToolTip('현재 화면의 검색어·분류·공급사·기간 조건으로 조회합니다. 저장하지 않은 편집은 먼저 확인합니다.\n단축키: F5')
        self.query_button.setStatusTip(self.query_button.toolTip())
        layout.addWidget(left,0,0);layout.addWidget(self.query_button,0,1,Qt.AlignmentFlag.AlignCenter);layout.addWidget(right,0,2)
        layout.setColumnStretch(0,1);layout.setColumnStretch(2,1)

    def add_output(self,button):
        self.output_actions.addWidget(button)
        self.output_panel.show()

    def set_query(self,callback):
        self.query_button.clicked.disconnect()
        self.query_button.clicked.connect(callback)


class NavigationBar(QFrame):
    """Home/context/close stay separate from the menu's title/query row."""
    def __init__(self,caption,parent=None,home=None,close=None):
        super().__init__(parent);self.setObjectName('pageNavigationBar')
        self.setStyleSheet('QFrame#pageNavigationBar {background:#FFFFFF;border-bottom:1px solid #D8E3DB;}')
        row=QHBoxLayout(self);row.setContentsMargins(14,6,14,6)
        self.home_button=action('첫화면',home) if home else None
        if self.home_button:row.addWidget(self.home_button)
        self.context=QueryContext(caption);self.context.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        row.addWidget(self.context,1)
        self.close_button=action('이 창 닫기',close) if close else None
        if self.close_button:row.addWidget(self.close_button)


class PageSurface(QWidget):
    """Keep the title/query row fixed while only the body scrolls."""
    def __init__(self,page,scroll,callback):
        super().__init__();self.page=page
        page.body.removeWidget(page.header)
        page.header.set_query(callback)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        if hasattr(page,'payment_chrome'):
            page.body.removeWidget(page.payment_chrome);layout.addWidget(page.payment_chrome)
        layout.addWidget(page.header);layout.addWidget(scroll,1)
        # Only remove redundant page-wide refresh buttons. Dialog/subreport
        # queries (different callback owners) retain their independent meaning.
        for button in page.findChildren(QPushButton):
            reference=getattr(button,'_sy_query_handler',None)
            handler=reference() if reference else None
            if getattr(handler,'__self__',None) is page and getattr(handler,'__name__','')=='refresh' and '조회' in button.text():
                button.hide()
