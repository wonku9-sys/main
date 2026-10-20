"""Readable startup action and display-only gravity/collision animation."""
import math
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout
from pos2.app import STYLE
from pos2.inspiration import InspirationDialog
from pos2.lucky_physics import BallMotion
from pos2.personal_themes import THEMES,apply_theme
from pos2.store import Store
from pos2.widgets import action

def contrast(a,b):
    def luminance(color):
        rgb=[getattr(color,key)() for key in ('redF','greenF','blueF')]
        rgb=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in rgb]
        return sum(x*w for x,w in zip(rgb,(.2126,.7152,.0722)))
    values=sorted((luminance(a),luminance(b)));return (values[1]+.05)/(values[0]+.05)

def ratio(button):
    p=button.palette();return contrast(p.color(QPalette.ColorRole.ButtonText),p.color(QPalette.ColorRole.Button))

def test_startup_button_is_readable_enabled_and_closes_popup(tmp_path):
    app=QApplication.instance() or QApplication([]);old=app.styleSheet();app.setStyleSheet(STYLE)
    store=Store(tmp_path/'readability.db');store.setup_admin('owner','관리자','Owner-Strong-2026!');d=InspirationDialog(store)
    try:
        d.show();app.processEvents();button=d.start_button
        assert button.isEnabled() and ratio(button)>=4.5 and button.text()=='닫고 시작하기'
        assert button.palette().color(QPalette.ColorRole.Button).name()=='#215d49'
        button.setFocus();app.processEvents();assert ratio(button)>=4.5
        QTest.mouseMove(button,button.rect().center());app.processEvents();assert ratio(button)>=4.5
        button.setEnabled(False);app.processEvents();assert not button.isEnabled() and ratio(button)>=4.5
        button.setEnabled(True);QTest.mouseClick(button,Qt.MouseButton.LeftButton);app.processEvents()
        assert not d.isVisible() and d.result()==QDialog.DialogCode.Accepted
    finally:d.close();d.deleteLater();store.close();app.setStyleSheet(old);app.processEvents()

@pytest.mark.parametrize('key',THEMES)
def test_personal_themes_keep_action_text_readable(key):
    app=QApplication.instance() or QApplication([]);old=app.styleSheet();app.setStyleSheet(STYLE)
    d=QDialog();layout=QVBoxLayout(d);button=action('저장',lambda:None,primary=True);layout.addWidget(button);apply_theme(d,key)
    try:d.show();app.processEvents();assert ratio(button)>=4.5
    finally:d.close();d.deleteLater();app.setStyleSheet(old);app.processEvents()

def test_ball_motion_bounds_collisions_and_settling_do_not_select_results():
    m=BallMotion(7);assert sorted(b.number for b in m.balls)==list(range(1,46))
    for _ in range(180):m.advance(1/60,True)
    mixed=sum(b.vx*b.vx+b.vy*b.vy for b in m.balls)
    assert min(b.y for b in m.balls)<-30
    for b in m.balls:assert math.hypot(b.x,b.y)<=m.radius-m.ball_radius+1e-8
    for _ in range(480):m.advance(1/60,False)
    assert sum(b.vx*b.vx+b.vy*b.vy for b in m.balls)<mixed*.15
    assert min(b.y for b in m.balls)>-15
    for b in m.balls:
        assert all(math.isfinite(v) for v in (b.x,b.y,b.vx,b.vy,b.angle))
        assert math.hypot(b.x,b.y)<=m.radius-m.ball_radius+1e-8
    for bad in (-1,float('nan'),float('inf')):
        with pytest.raises(ValueError):m.advance(bad,True)

def test_disabled_primary_action_stays_readable_and_cannot_trigger():
    app=QApplication.instance() or QApplication([]);old=app.styleSheet();app.setStyleSheet(STYLE)
    d=QDialog();layout=QVBoxLayout(d);calls=[];button=action('1개씩 뽑기',lambda:calls.append(True),primary=True);layout.addWidget(button)
    try:
        d.show();button.setEnabled(False);app.processEvents()
        assert ratio(button)>=4.5 and button.palette().color(QPalette.ColorRole.Button).name()=='#e0e4df'
        QTest.mouseClick(button,Qt.MouseButton.LeftButton);assert calls==[]
    finally:d.close();d.deleteLater();app.setStyleSheet(old);app.processEvents()

def test_collision_separates_overlapping_balls_and_reflects_velocity():
    m=BallMotion(3);a,b=m.balls[:2];m.balls=[a,b]
    a.x,a.y,a.vx,a.vy=-5,0,80,0;b.x,b.y,b.vx,b.vy=5,0,-80,0
    m.advance(1/120,False)
    assert a.vx<0<b.vx and b.x-a.x>=m.ball_radius*2-1e-6

def test_visible_machine_moves_and_stops_timer_when_closed():
    from pos2.lucky_numbers import LuckyNumbersDialog
    app=QApplication.instance() or QApplication([]);d=LuckyNumbersDialog();d.show();app.processEvents()
    try:
        machine=d.page.machine;before=[(b.x,b.y) for b in machine.motion.balls]
        d.page.draw_six();QTest.qWait(100);app.processEvents()
        assert machine.motion_timer.isActive() and machine.motion.mixing
        assert [(b.x,b.y) for b in machine.motion.balls]!=before
        d.page.finish_draw();assert len(d.page.results)==1 and len(set(d.page.results[0]))==6
        d.close();app.processEvents();assert not machine.motion_timer.isActive() and not d.page.timer.isActive()
    finally:d.close();d.deleteLater();app.processEvents()
