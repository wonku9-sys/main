"""Decorative snapshots must not delay dialog results, mutate forms or leak keys."""
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QRect,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QLabel,QVBoxLayout

from pos2.popup_motion import PopupMotion,OPEN_MS,CLOSE_MS,MAX_ACTIVE,scaled_rect
from pos2.popup_policy import install_popup_policy


@pytest.fixture
def motion():
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    previous=app._sy_popup_motion;enabled=app.property('_sy_window_motion_enabled')
    controller=PopupMotion(app,force=True);app._sy_popup_motion=controller
    app.setProperty('_sy_window_motion_enabled',True)
    dialogs=[]
    def create(cls=QDialog):
        dialog=cls();dialog.resize(420,280)
        row=QVBoxLayout(dialog);row.addWidget(QLabel('전환 검사',dialog));dialogs.append(dialog)
        return dialog
    yield app,controller,create
    controller.stop();app._sy_popup_motion=previous
    app.setProperty('_sy_window_motion_enabled',enabled)
    for dialog in dialogs:
        from shiboken6 import isValid
        if isValid(dialog):dialog.close();dialog.deleteLater()
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_open_and_close_animate_only_a_noninteractive_surface_and_keep_results_immediate(motion):
    app,controller,create=motion;dialog=create();dialog.show();app.processEvents()
    geometry=QRect(dialog.geometry());state=controller.active[id(dialog)]
    assert state['opening'] and state['group'].duration()==OPEN_MS
    surface=state['surface'];assert surface is not None
    assert surface.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert not surface.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose)
    assert surface.focusPolicy()==Qt.FocusPolicy.NoFocus
    QTest.qWait(OPEN_MS+70)
    assert id(dialog) not in controller.active and dialog.geometry()==geometry
    assert dialog.windowOpacity()==1 and surface.pixmap.isNull()
    dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and not dialog.isVisible()
    state=controller.active[id(dialog)];assert not state['opening'] and state['group'].duration()==CLOSE_MS
    QTest.qWait(CLOSE_MS+70)
    assert id(dialog) not in controller.active and dialog.geometry()==geometry


def test_login_disappearance_fades_without_scaling_or_delaying_accept(motion):
    class LoginDialog(QDialog):pass
    app,controller,create=motion;dialog=create(LoginDialog);dialog.show();app.processEvents()
    assert id(dialog) not in controller.active
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
    state=controller.active[id(dialog)];group=state['group']
    geometry=next(group.animationAt(i) for i in range(group.animationCount()) if bytes(group.animationAt(i).propertyName())==b'geometry')
    assert geometry.startValue()==geometry.endValue()
    QTest.qWait(CLOSE_MS+70);assert not controller.active


def test_private_close_never_grabs_record_contents_and_clears_opening_snapshot(motion,monkeypatch):
    app,controller,create=motion;dialog=create();dialog.key=bytearray(b'private-key')
    dialog.show();app.processEvents();surface=controller.active[id(dialog)]['surface']
    assert not surface.pixmap.isNull()
    monkeypatch.setattr(dialog,'grab',lambda *_:pytest.fail('Private closing content must never be captured'))
    dialog.key[:]=bytes(len(dialog.key));dialog.accept()
    assert not any(dialog.key) and not dialog.isVisible() and surface.pixmap.isNull()
    assert id(dialog) in controller.active and not controller.active[id(dialog)]['opening']
    QTest.qWait(CLOSE_MS+70);assert not controller.active


def test_cancelled_close_does_not_animate_or_hide_the_original(motion):
    class KeepOpen(QDialog):
        def closeEvent(self,event):event.ignore()
    app,controller,create=motion;dialog=create(KeepOpen);dialog.show();app.processEvents()
    QTest.qWait(OPEN_MS+70)
    assert not dialog.close() and dialog.isVisible() and not controller.active


def test_rapid_show_hide_before_first_frame_does_not_flash_or_keep_snapshots(motion):
    app,controller,create=motion;dialog=create()
    for _ in range(12):dialog.show();dialog.hide()
    app.processEvents()
    assert not controller.active and dialog.windowOpacity()==1 and not dialog.isVisible()


def test_repeated_openings_are_bounded_and_stop_releases_pixels_and_opacity(motion):
    app,controller,create=motion;dialogs=[];surfaces=[]
    for _ in range(MAX_ACTIVE+2):
        dialog=create();dialog.show();app.processEvents();dialogs.append(dialog)
        surfaces.append(controller.active[id(dialog)]['surface'])
        assert len(controller.active)<=MAX_ACTIVE
    controller.stop()
    assert not controller.active and all(dialog.windowOpacity()==1 for dialog in dialogs)
    assert all(surface.pixmap.isNull() for surface in surfaces)


def test_destroyed_or_oversize_windows_do_not_leave_an_invisible_dialog(motion):
    app,controller,create=motion;dialog=create();dialog.show();dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    assert not controller.active
    huge=create();huge.resize(4000,4000)
    assert not controller.show(huge) and huge.windowOpacity()==1


def test_delete_on_close_can_finish_its_safe_decoration_without_retaining_the_dialog(motion):
    from shiboken6 import isValid
    app,controller,create=motion;dialog=create();dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show();app.processEvents();QTest.qWait(OPEN_MS+70)
    key=id(dialog);dialog.accept()
    state=controller.active[key];surface=state['surface']
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not isValid(dialog) and state['ref']() is None and not surface.pixmap.isNull()
    QTest.qWait(CLOSE_MS+70)
    assert key not in controller.active and surface.pixmap.isNull()


def test_disabled_and_reduced_motion_skip_effects(motion,monkeypatch):
    app,controller,create=motion;dialog=create()
    app.setProperty('_sy_window_motion_enabled',False)
    assert not controller.show(dialog) and not controller.hide(dialog)
    app.setProperty('_sy_window_motion_enabled',True);controller.force=False;controller.system_enabled=False
    monkeypatch.setattr(app,'platformName',lambda:'windows')
    assert not controller.allowed(dialog)
    controller.system_enabled=True;assert controller.allowed(dialog)


def test_native_dialogs_are_not_double_animated_and_scale_keeps_the_center(motion):
    from PySide6.QtWidgets import QMessageBox
    _,controller,_=motion;dialog=QMessageBox()
    try:assert not controller.allowed(dialog)
    finally:dialog.deleteLater()
    original=QRect(100,200,600,450);smaller=scaled_rect(original,.97)
    assert smaller.center()==original.center() and smaller.width()<original.width() and smaller.height()<original.height()
