"""Visible SY POS identity. Legacy data paths and cryptographic AAD stay stable."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

NAME = "SY POS"
LOGO = Path(__file__).resolve().parent / "assets" / "sy-monogram.png"


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
    panel.setStyleSheet("QFrame#syBrand {background:#FAF8F3;border:1px solid #E5DECC;border-radius:12px;} QLabel {background:transparent;border:0;color:#214A40;}")
    layout=QHBoxLayout(panel);layout.setContentsMargins(6,2,12,2);layout.setSpacing(0)
    logo=QLabel();logo.setObjectName("syLogo");logo.setAccessibleName("SY 이미지 로고")
    logo.setPixmap(QPixmap(str(LOGO)).scaled(120 if large else 108,80 if large else 72,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pos=QLabel("POS");pos.setStyleSheet(f"font-size:{29 if large else 27}px;font-weight:700;letter-spacing:2px;color:#214A40;")
    layout.addWidget(logo);layout.addWidget(pos);layout.addStretch()
    panel.setToolTip("SY POS · 나의 매장과 일상을 담는 독립형 데스크")
    return panel
