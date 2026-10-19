"""Local per-account, per-popup palettes. No remote backgrounds or tracking."""
from PySide6.QtWidgets import QComboBox

THEMES={
    'cream':('포근한 크림','#FFF9F0','#FFFDF8','#F3E6CD','#564B3E'),
    'rose':('살구빛 장미','#FFF3F2','#FFFCFC','#F4DBDF','#684B55'),
    'forest':('초록빛 쉼터','#F1F7F0','#FCFEFA','#D8E7D5','#3D5844'),
    'lavender':('차분한 라벤더','#F5F1FA','#FDFBFF','#E4D9EF','#594768'),
    'night':('고요한 밤','#272B36','#343947','#50586B','#F0EDE7'),
}


def apply_theme(widget,key):
    _,background,paper,border,ink=THEMES[key]
    widget.setStyleSheet(f"""
    QDialog {{background:{background};color:{ink};}}
    QLabel,QCheckBox {{color:{ink};background:transparent;}}
    QFrame#cashCard,QFrame#memoCard {{background:{paper};border:1px solid {border};border-radius:12px;}}
    QTextEdit,QLineEdit,QDateEdit,QTimeEdit,QComboBox,QTableWidget,QCalendarWidget {{background:{paper};color:{ink};border:1px solid {border};border-radius:7px;}}
    QTextEdit {{padding:12px;font-size:15px;}}
    QTableWidget {{alternate-background-color:{background};selection-background-color:{border};selection-color:{ink};}}
    QCalendarWidget QToolButton,QHeaderView::section {{background:{border};color:{ink};}}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{background:{border};}}
    QCalendarWidget QAbstractItemView {{background:{paper};color:{ink};selection-background-color:{border};selection-color:{ink};}}
    QPushButton {{background:{paper};color:{ink};border:1px solid {border};border-radius:7px;padding:7px 12px;}}
    QPushButton:hover {{background:{border};}}
    """)
    for name in ('editor','summary'):
        control=getattr(widget,name,None)
        if hasattr(control,'setStyleSheet'):control.setStyleSheet('')


def theme_picker(store,kind,dialog):
    combo=QComboBox();combo.setToolTip('이 계정의 화면 분위기를 즉시 저장합니다. 일기장과 가계부는 따로 설정됩니다.')
    for key,value in THEMES.items():combo.addItem(value[0],key)
    combo.setCurrentIndex(combo.findData(store.personal_theme(kind)))
    apply_theme(dialog,combo.currentData())
    def change():
        store.save_personal_theme(kind,combo.currentData());apply_theme(dialog,combo.currentData())
    combo.currentIndexChanged.connect(change)
    return combo
