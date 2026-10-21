"""Personal shortcuts share the clear, offline 3D menu artwork."""


def personal_icon(kind):
    from .menu_icons import menu_icon
    return menu_icon(kind)


def personal_badge(kind,size=44):
    """Unboxed, HiDPI title decoration sharing the same cached shortcut art."""
    from PySide6.QtCore import QSize,Qt
    from PySide6.QtWidgets import QLabel
    label=QLabel();label.setObjectName(kind+'3dBadge')
    label.setAccessibleName({'diary':'일기장 3D 아이콘','household':'가계부 3D 아이콘'}[kind])
    pixmap=personal_icon(kind).pixmap(QSize(size*2,size*2));pixmap.setDevicePixelRatio(2)
    label.setPixmap(pixmap);label.setFixedSize(size,size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet('QLabel{background:transparent;border:0;padding:0;}')
    return label


def personal_heading(title,kind,size=44):
    from PySide6.QtWidgets import QHBoxLayout
    row=QHBoxLayout();row.setContentsMargins(0,0,0,0);row.setSpacing(10)
    row.addWidget(personal_badge(kind,size));row.addWidget(title,1)
    return row
