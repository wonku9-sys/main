from hashlib import sha256

import pytest
from PySide6.QtCore import QCoreApplication,QDate,QEvent,QSize,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QCalendarWidget,QDateEdit,QToolButton

from pos2.menu_icons import DONE_ASSET,DONE_SHA256,_done_image,family,menu_icon
from pos2.menu_help import MenuHelpStyle
from pos2.widgets import action


@pytest.mark.parametrize('label',['이전','이전 500개','이전 글귀','이전 달','이전달','왼쪽','좌측','←','◀','<','6개월 이전'])
def test_previous_labels_use_left_arrow(label):assert family(label)=='back'


@pytest.mark.parametrize('label',['다음','다음 500명','다음 글귀','다음 달','다음달','오른쪽','우측','→','▶','>','6개월 이후'])
def test_next_labels_use_right_arrow(label):assert family(label)=='forward'


@pytest.mark.parametrize('label',['완료','확인','확인 (0)','완료 (A)','납부·처리 완료','인쇄 완료 표시'])
def test_completion_labels_use_blue_3d_check(label):assert family(label)=='done'


def test_completion_cancel_is_not_a_success_icon_and_copy_is_not_a_report():
    assert family('완료 취소')=='waste' and family('미완료')!='done'
    assert family('글귀 복사')=='copy'


def test_generated_completion_asset_is_transparent_verified_packaged_and_readable():
    app=QApplication.instance() or QApplication([])
    assert sha256(DONE_ASSET.read_bytes()).hexdigest()==DONE_SHA256
    image=_done_image();assert image is not None and image.hasAlphaChannel() and image.width()>=1024
    assert image.pixelColor(0,0).alpha()==0
    from package_source import source_files
    assert DONE_ASSET in set(source_files())
    for edge in (20,28,38,64,128):
        rendered=menu_icon('완료').pixmap(QSize(edge,edge)).toImage()
        assert not rendered.isNull() and rendered.pixelColor(0,0).alpha()==0
        blue=sum(rendered.pixelColor(x,y).alpha()>200 and rendered.pixelColor(x,y).blue()>rendered.pixelColor(x,y).red()*1.15 for x in range(edge) for y in range(edge))
        white=sum(min(rendered.pixelColor(x,y).red(),rendered.pixelColor(x,y).green(),rendered.pixelColor(x,y).blue())>220 and rendered.pixelColor(x,y).alpha()>200 for x in range(edge) for y in range(edge))
        assert blue>edge*edge*.2 and white>edge*edge*.02
    calls=[];button=action('완료',lambda:calls.append(True));button.click()
    assert button.icon().cacheKey()==menu_icon('done').cacheKey() and calls==[True]
    button.deleteLater();app.processEvents()


@pytest.fixture
def calendar_app():
    app=QApplication.instance() or QApplication([]);was_help=isinstance(app.style(),MenuHelpStyle)
    previous=app.style().objectName() or 'Fusion';app.setStyle(MenuHelpStyle())
    yield app
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    app.setStyle(MenuHelpStyle() if was_help else previous)


def check_arrows(calendar,app):
    calendar.setCurrentPage(2026,1);calendar.show();app.processEvents()
    previous=calendar.findChild(QToolButton,'qt_calendar_prevmonth')
    following=calendar.findChild(QToolButton,'qt_calendar_nextmonth')
    def matches(button,kind):
        # An installed global hover policy may be showing the enlarged
        # version under the pointer. Both are the same directional artwork.
        from pos2.menu_icons import _family_icon
        return button.icon().cacheKey() in {menu_icon(kind).cacheKey(),_family_icon(kind).cacheKey()}
    assert matches(previous,'back')
    assert matches(following,'forward')
    assert previous.accessibleName()=='이전 달' and following.accessibleName()=='다음 달'
    QTest.mouseClick(previous,Qt.MouseButton.LeftButton);app.processEvents()
    assert (calendar.yearShown(),calendar.monthShown())==(2025,12)
    QTest.mouseClick(following,Qt.MouseButton.LeftButton);app.processEvents()
    assert (calendar.yearShown(),calendar.monthShown())==(2026,1)
    assert matches(previous,'back')


def test_calendar_arrow_icons_keep_actual_month_and_year_navigation(calendar_app):
    check_arrows(QCalendarWidget(),calendar_app)


def test_date_popup_calendar_uses_the_same_arrows(calendar_app):
    date=QDateEdit(QDate(2026,1,15));date.setCalendarPopup(True);date.show()
    check_arrows(date.calendarWidget(),calendar_app)
