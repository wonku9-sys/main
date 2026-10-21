"""Visible SY POS identity. Legacy data paths and cryptographic AAD stay stable."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

NAME = "SY POS"
LOGO = Path(__file__).resolve().parent / "assets" / "sy-monogram.png"
WORDMARK = LOGO.with_name('sy-pos-wordmark-3d.png')

LOGIN_CHOICES_STYLE = '''
QFrame#loginChoices {
    background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #243C48,stop:1 #35515D);
    border-radius:18px;
}
QLabel {background:transparent;color:#EDF3F1;}
QPushButton {
    text-align:left;color:#EDF3F1;background:#365563;border:1px solid #5D7982;
    border-radius:12px;padding:14px;
}
QPushButton:hover {background:#426571;border-color:#819FA5;}
QPushButton:focus {border:1px solid #B9CCC6;}
QPushButton:checked {color:#244B42;background:#CADCD2;border:1px solid #9FB9AD;}
QPushButton:checked:hover {background:#D5E5DB;border-color:#AFC7BA;}
'''


@lru_cache(maxsize=1)
def wordmark_image():
    """Load once, preserving transparent edges during high-DPI downsampling."""
    image = QImage(str(WORDMARK))
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def wordmark_pixmap(large=False):
    return _wordmark_pixmap(bool(large))


@lru_cache(maxsize=2)
def _wordmark_pixmap(large):
    # Supply 2x pixels without increasing logical layout size on HiDPI screens.
    width, height = (216, 72) if large else (156, 52)
    pixmap = QPixmap.fromImage(wordmark_image()).scaled(
        width * 2, height * 2, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    pixmap.setDevicePixelRatio(2)
    return pixmap


def spin_button_style():
    folder=LOGO.parent.as_posix()
    return f'''
    QSpinBox,QDoubleSpinBox {{padding-right:29px;min-height:26px;}}
    QSpinBox::up-button,QDoubleSpinBox::up-button {{subcontrol-origin:border;subcontrol-position:top right;width:26px;background:#E8EFE9;border-left:1px solid #BDCDC1;border-bottom:1px solid #BDCDC1;border-top-right-radius:5px;}}
    QSpinBox::down-button,QDoubleSpinBox::down-button {{subcontrol-origin:border;subcontrol-position:bottom right;width:26px;background:#E8EFE9;border-left:1px solid #BDCDC1;border-bottom-right-radius:5px;}}
    QSpinBox::up-button:hover,QSpinBox::down-button:hover,QDoubleSpinBox::up-button:hover,QDoubleSpinBox::down-button:hover {{background:#CDE0D1;}}
    QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {{image:url("{folder}/step-up.svg");width:14px;height:10px;}}
    QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {{image:url("{folder}/step-down.svg");width:14px;height:10px;}}
    '''


def app_icon():
    return QIcon(str(LOGO))


def brand_widget(parent=None, large=False):
    panel=QFrame(parent)
    panel.setObjectName("syBrand")
    panel.setStyleSheet("QFrame#syBrand {background:transparent;border:0;} QLabel {background:transparent;border:0;color:#214A40;}")
    layout=QHBoxLayout(panel);layout.setContentsMargins(8,0,8,0);layout.setSpacing(0)
    logo=QLabel();logo.setObjectName("syLogo");logo.setAccessibleName("SY POS 3D 로고")
    logo.setPixmap(wordmark_pixmap(large))
    logo.setFixedSize(216 if large else 156,72 if large else 52)
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(logo)
    panel.setFixedSize(232 if large else 172,72 if large else 52)
    panel.setAccessibleName("SY POS 3D 로고")
    panel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.setToolTip("SY POS · 나의 매장과 일상을 담는 독립형 데스크")
    return panel
