"""Original ambient score/cache tests; no physical speaker is required."""
import wave
from hashlib import sha256
from PySide6.QtWidgets import QApplication
import pytest

from pos2.calm_music import daily_score,render_music
from pos2.store import Store


def test_31_day_seasonal_scores_are_deterministic_and_distinct():
    for month in (1,4,7,10):
        scores=[daily_score(day,month) for day in range(1,32)]
        assert len({(r["chords"],r["bell"]) for r in scores})==31
        assert scores[0]==daily_score(1,month)
    assert daily_score(1,1)["chords"]!=daily_score(1,7)["chords"]


def test_wave_cache_is_valid_quiet_and_reused(tmp_path):
    path=render_music(tmp_path/"music-cache",19,10,duration=.5,sample_rate=8000)
    original=path.stat().st_mtime_ns
    with wave.open(str(path),"rb") as sound:
        assert sound.getframerate()==8000 and sound.getnchannels()==1
        assert sound.getsampwidth()==2 and sound.getnframes()==4000
        assert any(sound.readframes(4000))
    assert render_music(path.parent,19,10,duration=.5,sample_rate=8000).stat().st_mtime_ns==original
    second=render_music(path.parent,20,10,duration=.5,sample_rate=8000)
    assert sha256(path.read_bytes()).digest()!=sha256(second.read_bytes()).digest()


def test_music_settings_are_per_user_and_backup_safe(tmp_path):
    store=Store(tmp_path/"music.db");store.setup_admin("owner","관리자","Owner-Strong-2026!")
    try:
        assert store.diary_music_preferences()=={"enabled":True,"volume":6}
        store.save_diary_music_preferences(False,3)
        assert store.diary_music_preferences()=={"enabled":False,"volume":3}
        with pytest.raises(ValueError):store.save_diary_music_preferences(True,100)
    finally:store.close()


def test_locked_diary_stops_music_and_wipes_text(tmp_path):
    app=QApplication.instance() or QApplication([])
    from pos2.diary_ui import DiaryDialog
    store=Store(tmp_path/"diary-music.db");store.setup_admin("owner","관리자","Owner-Strong-2026!")
    try:
        store.setup_diary("Private-Diary-2026!","Private-Diary-2026!")
        store.save_diary_music_preferences(False,6)
        key=store.unlock_diary("Private-Diary-2026!")
        dialog=DiaryDialog(store,key)
        dialog.music.start()
        assert dialog.music.active
        dialog.wipe()
        assert not dialog.music.active and not dialog.music.timer.isActive()
        assert bytes(key)==bytes(32)
        dialog.deleteLater();app.processEvents()
    finally:store.close()
