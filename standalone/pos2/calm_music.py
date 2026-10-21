"""Original offline ambient performances: 31 daily variants, seasonal timbres.

No downloaded recording, copyrighted tune, external audio stream or lyrics.
Generated audio is a disposable cache, never part of a business backup.
"""
from array import array
from datetime import date
import math
from pathlib import Path
import random
import sys
import tempfile
import wave

from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,QUrl,Signal


def daily_score(day,month):
    if not 1<=day<=31 or not 1<=month<=12:raise ValueError("음악 날짜를 확인하세요.")
    season=(month%12)//3
    rng=random.Random(day+season*97)
    roots=[0,3,5,4,0,5,1,4]
    rng.shuffle(roots)
    scale=(0,2,4,5,7,9,11)
    transposition=(-3,0,-5,-2)[season]
    chords=[]
    for root in roots:
        notes=[48+transposition+scale[(root+offset)%7]+12*((root+offset)//7) for offset in (0,2,4,6)]
        chords.append(tuple(notes))
    return {"day":day,"season":("겨울","봄","여름","가을")[season],"chords":tuple(chords),"bell":rng.choice((0,2,4,7,9)),"seed":day+season*97}


def render_music(cache,day,month,duration=64,sample_rate=16000):
    score=daily_score(day,month)
    cache=Path(cache)
    if cache.is_symlink():raise ValueError("음악 캐시 폴더를 확인하세요.")
    cache.mkdir(parents=True,exist_ok=True)
    target=cache/f"calm-{score['season']}-{day:02d}-v1.wav"
    count=int(duration*sample_rate)
    if target.is_file() and not target.is_symlink():
        try:
            with wave.open(str(target),"rb") as source:
                if source.getnframes()==count and source.getframerate()==sample_rate:return target
        except (OSError,wave.Error,EOFError):pass
    frequencies=[tuple(440*2**((note-69)/12) for note in chord) for chord in score["chords"]]
    bell=440*2**((72+score["bell"]-69)/12)
    output=array("h")
    bar_length=duration/len(frequencies)
    for index in range(count):
        moment=index/sample_rate
        bar=min(len(frequencies)-1,int(moment/bar_length));position=moment-bar*bar_length
        blend=(1-math.cos(math.pi*min(1,position/2)))/2
        value=0.0
        for chord,gain in ((frequencies[bar],blend),(frequencies[(bar-1)%len(frequencies)],1-blend)):
            for frequency in chord:
                phase=2*math.pi*frequency*moment
                value+=gain*(math.sin(phase)+0.12*math.sin(phase*2))/4
        pluck=position-bar_length*.4
        if pluck>=0:value+=.055*math.exp(-pluck*1.25)*math.sin(2*math.pi*bell*pluck)
        envelope=min(1,moment/1.5,(duration-moment)/1.5)
        output.append(int(max(-1,min(1,value*.20*envelope))*32767))
    if sys.byteorder!="little":output.byteswap()
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix="calm-",suffix=".wav",dir=cache,delete=False) as handle:temporary=Path(handle.name)
        with wave.open(str(temporary),"wb") as destination:
            destination.setnchannels(1);destination.setsampwidth(2);destination.setframerate(sample_rate);destination.writeframes(output.tobytes())
        temporary.replace(target)
        return target
    finally:
        if temporary and temporary.exists():temporary.unlink()


class MusicSignals(QObject):
    ready=Signal(str,str)


class MusicWorker(QRunnable):
    def __init__(self,cache,current):
        super().__init__();self.cache,self.current=cache,current;self.signals=MusicSignals()
    def run(self):
        try:path=render_music(self.cache,self.current.day,self.current.month)
        except (OSError,ValueError,wave.Error):self.signals.ready.emit("","음악을 준비하지 못했습니다. 무음으로 이용할 수 있습니다.")
        else:self.signals.ready.emit(str(path),f"{daily_score(self.current.day,self.current.month)['season']}의 고요 · {self.current.day:02d}/31")


class DiaryMusic(QObject):
    status=Signal(str)
    def __init__(self,store,parent):
        super().__init__(parent);self.store=store;self.sound=None;self.active=False;self.waiting=False
        self.preferences=store.diary_music_preferences()
        self.day=date.today();self.path=None
        self.timer=QTimer(self);self.timer.setInterval(60_000);self.timer.timeout.connect(self.check_day)
    def start(self):
        self.active=True;self.timer.start()
        if not self.preferences["enabled"] or not self.preferences["volume"]:
            self.status.emit("배경음악 꺼짐");return
        if self.path:self.play();return
        if self.waiting:return
        cache=(self.store.path.parent if self.store.path else Path(tempfile.gettempdir())/"seoyoung-pos-demo")/"music-cache"
        self.waiting=True;self.status.emit("오늘의 잔잔한 음악을 준비하고 있습니다…")
        self.worker=MusicWorker(cache,self.day);self.worker.signals.ready.connect(self.prepared)
        QThreadPool.globalInstance().start(self.worker)
    def prepared(self,path,title):
        self.waiting=False
        if not self.active:return
        self.path=path or None;self.title=title
        if path:self.play()
        else:self.status.emit(title)
    def play(self):
        if not self.active or not self.preferences["enabled"] or not self.preferences["volume"]:return
        try:
            if self.sound is None:
                from PySide6.QtMultimedia import QSoundEffect
                self.sound=QSoundEffect(self);self.sound.setLoopCount(QSoundEffect.Loop.Infinite)
            self.sound.setVolume(self.preferences["volume"]/100)
            self.sound.setSource(QUrl.fromLocalFile(str(self.path)));self.sound.play()
            self.status.emit(getattr(self,"title","오늘의 잔잔한 음악"))
        except (RuntimeError,ImportError,AttributeError):self.status.emit("이 PC에서 소리를 재생할 수 없습니다. 무음으로 이용하세요.")
    def configure(self,enabled,volume):
        self.store.save_diary_music_preferences(enabled,volume)
        self.preferences={"enabled":enabled,"volume":volume}
        if self.sound:self.sound.stop()
        if self.active:self.start()
    def check_day(self):
        if date.today()!=self.day:
            self.day=date.today();self.path=None
            if self.sound:self.sound.stop()
            self.start()
    def stop(self):
        self.active=False;self.timer.stop()
        if self.sound:self.sound.stop()
