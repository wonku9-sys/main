"""Keep complete output icons outside the fixed query strip's overflow area."""
import os
from pathlib import Path
import subprocess
import sys

if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from pos2.menu_icons import menu_icon


@pytest.mark.parametrize('size',(28,38,56))
def test_output_artwork_keeps_a_transparent_guard_on_every_edge(size):
    app=QApplication.instance() or QApplication([])
    for key in ('printer','excel'):
        image=menu_icon(key).pixmap(QSize(size,size)).toImage()
        assert image.size()==QSize(size,size)
        assert all(image.pixelColor(x,y).alpha()==0 for x in range(size) for y in (0,size-1))
        assert all(image.pixelColor(x,y).alpha()==0 for y in range(size) for x in (0,size-1))


@pytest.mark.parametrize('scale',('1','1.25','1.5','2'))
def test_output_icons_survive_real_qt_style_overflow_and_fractional_dpi(scale):
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_SCALE_FACTOR=scale,
             QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--dpi-probe'],
                          cwd=Path(__file__).resolve().parents[1],env=env,
                          text=True,capture_output=True,timeout=40)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'PASS unclipped output' in result.stdout


def dpi_probe():
    from PySide6.QtCore import QPoint,QRect
    from PySide6.QtWidgets import QStyle,QStyleOptionButton
    from pos2.app import STYLE
    from pos2.appearance import apply_theme
    from pos2.font_support import regular_font
    from pos2.menu_help import MenuHelpStyle
    from pos2.popup_policy import install_popup_policy
    from pos2.query_bar import QueryBar
    from pos2.widgets import action,output_icon
    app=QApplication([]);install_popup_policy(app)
    app.setStyle(MenuHelpStyle());app.setFont(regular_font(10));app.setStyleSheet(STYLE)
    apply_theme('default')
    bar=QueryBar('잘림 검사',lambda:None)
    outputs=[output_icon(text,lambda:None) for text in ('인쇄','엑셀 저장')]
    for button in outputs:bar.add_output(button)
    others=[action('긴 작업 메뉴 '+str(i),lambda:None) for i in range(4)]
    for button in others:bar.actions.addWidget(button)
    for theme in ('default','spring','winter'):
        apply_theme(theme)
        for width in (380,700,1000):
            bar.resize(width,38);bar.show();app.processEvents();app.processEvents()
            assert abs(bar.devicePixelRatioF()-float(os.environ['QT_SCALE_FACTOR']))<.01
            assert bar.height()==38 and bar.action_scroll.horizontalScrollBar().maximum()>0
            assert bar.action_scroll.viewport().height()>=28
            for button in outputs:
                assert button.isVisible() and button.size()==QSize(36,32)
                assert not bar.action_scroll.isAncestorOf(button)
                rect=QRect(button.mapTo(bar,QPoint()),button.size())
                assert bar.rect().contains(rect),(theme,width,rect)
                assert bar.output_panel.rect().contains(QRect(button.pos(),button.size()))
                option=QStyleOptionButton();button.initStyleOption(option)
                contents=button.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,option,button)
                assert contents.width()>=button.iconSize().width()+4
                assert contents.height()>=button.iconSize().height()+4
            for button in others:
                y=button.mapTo(bar.action_scroll.viewport(),QPoint()).y()
                assert 0<=y and y+button.height()<=bar.action_scroll.viewport().height()
            center=bar.query_button.mapTo(bar,bar.query_button.rect().center()).x()
            assert abs(center-bar.rect().center().x())<=1
            for button in outputs:
                button.setFocus();button.setDown(True);app.processEvents();button.setDown(False)
                button.setEnabled(False);app.processEvents();assert button.height()==32
                button.setEnabled(True)
            if len(sys.argv)>2:
                folder=Path(sys.argv[2]);folder.mkdir(parents=True,exist_ok=True)
                assert bar.grab().save(str(folder/f'query-{theme}-{width}.png'))
    bar.close()
    print('PASS unclipped output: full 28px icons, 32px buttons, overflow, 380/700/1000px, three skins')


if __name__=='__main__':
    dpi_probe()
