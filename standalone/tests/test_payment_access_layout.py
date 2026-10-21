"""Short payment reauthentication fits at once and has only Confirm/Cancel."""
from time import monotonic
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint,QRect,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QPushButton,QScrollArea,QWidget

from pos2.appearance import apply_theme
from pos2.payment_access_ui import PaymentAccessDialog
from pos2.popup_policy import install_popup_policy
from pos2.store import Store
from pos2.widgets import FormDialog

PASSWORD='Payment-Layout-2026!'


@pytest.fixture
def shop(tmp_path):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app);apply_theme('default')
    store=Store(tmp_path/'layout.db');store.setup_admin('admin','관리자',PASSWORD)
    window=QWidget();window.store=store;dialogs=[]
    def create():
        dialog=PaymentAccessDialog(window);dialogs.append(dialog);return dialog
    yield app,store,create
    for dialog in dialogs:
        if dialog.worker and dialog.worker.isRunning():dialog.worker.wait(10000)
        app.processEvents();dialog.close();dialog.deleteLater()
    window.close();window.deleteLater();app.processEvents();store.close()


def assert_visible_inside(dialog,widget):
    assert widget.isVisible()
    assert dialog.rect().contains(QRect(widget.mapTo(dialog,QPoint()),widget.size()))


@pytest.mark.parametrize('font_px',[14,18,22])
def test_all_fields_message_and_buttons_fit_without_scroll_or_duplicate_close(shop,font_px):
    app,_,create=shop;dialog=create()
    dialog.setStyleSheet(dialog.styleSheet()+f'QLabel,QLineEdit,QPushButton {{font-size:{font_px}px;}}')
    dialog.show();app.processEvents()
    assert dialog.findChild(QScrollArea,'popupScroll') is None
    assert {b.text() for b in dialog.findChildren(QPushButton)}=={'확인','취소'}
    for widget in (*dialog.fields.values(),dialog.message,*dialog.buttons.buttons()):assert_visible_inside(dialog,widget)
    assert dialog.message.height()>=dialog.message.heightForWidth(dialog.message.width())
    dialog.resize(380,260);app.processEvents()
    for button in dialog.buttons.buttons():assert_visible_inside(dialog,button)
    assert dialog.fields['name'].isReadOnly() and dialog.fields['code'].isReadOnly()


def test_small_work_area_keeps_confirmation_footer_outside_fallback_scroll(shop,monkeypatch):
    app,_,create=shop;dialog=create()
    monkeypatch.setattr(dialog,'screen',lambda:SimpleNamespace(availableGeometry=lambda:QRect(0,0,500,300)))
    dialog.show();app.processEvents()
    scroll=dialog.findChild(QScrollArea,'popupScroll')
    assert scroll is not None
    assert not scroll.isAncestorOf(dialog.buttons)
    assert {b.text() for b in dialog.findChildren(QPushButton)}=={'확인','취소'}
    for button in dialog.buttons.buttons():assert_visible_inside(dialog,button)


def test_invalid_password_stays_open_and_correct_confirm_closes_without_identity_change(shop):
    app,store,create=shop;dialog=create();actor=dict(store.actor);dialog.show();app.processEvents()
    for password,accepted in [('incorrect',False),(PASSWORD,True)]:
        dialog.password.setText(password)
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Save),Qt.MouseButton.LeftButton)
        deadline=monotonic()+10
        while not dialog.buttons.isEnabled() and monotonic()<deadline:QTest.qWait(10)
        app.processEvents()
        assert dialog.buttons.isEnabled() and not dialog.password.text()
        assert dialog.verified==accepted and dialog.isVisible()!=accepted
        assert store.actor==actor
        if not accepted:assert dialog.message.text() and not dialog.result()
    assert dialog.result()==dialog.DialogCode.Accepted


@pytest.mark.parametrize('route',['cancel','escape','ctrl_w','x'])
def test_cancel_routes_close_only_this_confirmation(shop,route):
    app,_,create=shop;dialog=create();dialog.show();app.processEvents()
    if route=='cancel':QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel),Qt.MouseButton.LeftButton)
    elif route=='escape':QTest.keyClick(dialog,Qt.Key.Key_Escape)
    elif route=='ctrl_w':QTest.keyClick(dialog,Qt.Key.Key_W,Qt.KeyboardModifier.ControlModifier)
    else:dialog.close()
    app.processEvents();assert not dialog.isVisible() and dialog.result()==dialog.DialogCode.Rejected


def test_close_shortcuts_do_not_bypass_inflight_authentication_guard(shop):
    app,_,create=shop;dialog=create();dialog.show();app.processEvents()
    dialog.worker=SimpleNamespace(isRunning=lambda:True)
    dialog.reject();assert not dialog.close()
    dialog._popup_close_action.trigger();app.processEvents();assert dialog.isVisible()
    dialog.worker=None


def test_other_forms_keep_scroll_and_close_footer(shop):
    app,_,_=shop;dialog=FormDialog('다른 입력창');dialog.field('memo','메모');dialog.finish(dialog.accept)
    try:
        dialog.show();app.processEvents()
        assert dialog.findChild(QScrollArea,'popupScroll') is not None
        assert dialog._popup_close_button.isVisible() and dialog._popup_close_button.text()=='이 창 닫기'
    finally:dialog.close();dialog.deleteLater();app.processEvents()
