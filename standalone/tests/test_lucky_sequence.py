"""Each automatic timeout reveals exactly one ball without blocking Qt."""
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pos2.lucky_numbers import LuckyNumbersDialog


@pytest.fixture
def lucky(monkeypatch):
    app=QApplication.instance() or QApplication([])
    dialog=LuckyNumbersDialog();page=dialog.page
    monkeypatch.setattr(page.open_sound,'play',lambda:None)
    monkeypatch.setattr(page.draw_sound,'play',lambda:None)
    monkeypatch.setattr('pos2.lucky_numbers.secrets.choice',lambda pool:pool[-1])
    dialog.show();app.processEvents()
    yield app,dialog,page
    dialog.close();dialog.deleteLater();app.processEvents()


def visible_count(page):
    return sum(label.text()!='?' for row in page.rows for label in row)


@pytest.mark.parametrize('method,total,ticks',[
    ('draw',1,60),('draw_six',6,16),('draw_five',30,8),
])
def test_auto_reveals_one_ball_per_deadline(lucky,method,total,ticks):
    _,_,p=lucky
    getattr(p,method)()
    assert p.pending_balls==total and p.draw_ticks==ticks and visible_count(p)==0
    for count in range(1,total+1):
        for _ in range(ticks-1):p.animate()
        assert visible_count(p)==count-1
        p.animate()
        assert visible_count(p)==count and p.pending_balls==total-count
        assert p.timer.isActive()==(count<total)
        assert p.machine.running==(count<total)
        if count<total:
            assert not any(b.isEnabled() for b in (p.draw_button,p.six_button,p.five_button))
    for row in p.results:
        assert row==sorted(row) and len(set(row))==6 and all(1<=n<=45 for n in row)
    p.finish_draw();p.animate()
    assert visible_count(p)==total


def test_partial_line_preserved_and_five_mode_is_faster_even_for_last_line(lucky):
    _,_,p=lucky
    p.draw();p.finish_draw();first=p.drawn[0]
    p.draw_six();assert p.pending_balls==5
    for _ in range(5):p.finish_draw()
    assert len(p.results)==1 and first in p.results[0]
    original=list(p.results[0]);p.draw_five()
    for _ in range(18):p.finish_draw()
    assert len(p.results)==4 and p.timer.isActive()
    p.stop_draw();p.draw_five()
    assert p.pending_balls==6 and p.draw_ticks<p.SIX_TICKS and p.results[0]==original
    for _ in range(6):p.finish_draw()
    assert len(p.results)==5 and not p.timer.isActive()


@pytest.mark.parametrize('cancel',['hide','close','reset'])
def test_interrupt_does_not_reveal_late_balls_and_can_resume(lucky,cancel):
    app,dialog,p=lucky
    p.draw_five()
    for _ in range(8):p.finish_draw()
    completed=list(p.results[0]);partial=list(p.drawn)
    if cancel=='reset':p.reset(False)
    else:getattr(dialog,cancel)()
    assert not p.timer.isActive() and not p.pending_balls and not p.machine.running
    expected=0 if cancel=='reset' else 8
    for _ in range(100):p.animate();p.finish_draw()
    assert visible_count(p)==expected
    if cancel!='reset':assert p.results==[completed] and p.drawn==partial
    dialog.show();app.processEvents();p.draw_five()
    for _ in range(30-expected):p.finish_draw()
    assert len(p.results)==5 and visible_count(p)==30


def test_repeated_commands_do_not_restart_or_change_speed(lucky):
    _,_,p=lucky
    p.draw_five();p.finish_draw();p.animate()
    before=(p.pending_balls,p.ticks,p.draw_ticks,list(p.drawn))
    p.draw();p.draw_six();p.draw_five();p.machine.clicked.emit()
    assert (p.pending_balls,p.ticks,p.draw_ticks,p.drawn)==before


def test_real_qt_timer_paints_partial_result_and_keeps_ui_responsive(lucky):
    app,_,p=lucky
    callbacks=[]
    from PySide6.QtCore import QTimer
    QTimer.singleShot(40,lambda:callbacks.append('responsive'))
    p.draw_six()
    for _ in range(180):
        if visible_count(p):break
        QTest.qWait(10)
    assert callbacks==['responsive'] and visible_count(p)==1
    assert not p.results and p.timer.isActive()
    assert [label.text() for label in p.rows[0]]==['45','?','?','?','?','?']
    app.processEvents()
