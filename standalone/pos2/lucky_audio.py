"""Per-PC draw sound. User recordings never enter the source/release package."""
from hashlib import sha256
from pathlib import Path
import sqlite3
import wave
from PySide6.QtCore import QObject,QSettings,QStandardPaths,QSaveFile,QIODevice,QUrl,Signal,Qt
from PySide6.QtWidgets import QApplication


class DrawSound(QObject):
    problem=Signal(str)
    def __init__(self,parent=None,settings=None,root=None,kind='draw'):
        super().__init__(parent)
        if kind not in {'draw','open','login','warning'}:raise ValueError('알 수 없는 프로그램 효과음입니다.')
        self.kind=kind;self.settings=settings if settings is not None else QSettings('SY-POS',{'draw':'LuckyDrawSound','open':'LuckyOpenSound','login':'LoginSound','warning':'WarningSound'}[kind])
        self.root=Path(root) if root else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'lucky-audio'/kind
        self.player=None;self.output=None
    @property
    def enabled(self):return self.settings.value('enabled',True,type=bool)
    @property
    def volume(self):return max(0,min(100,self.settings.value('volume',20,type=int)))
    @property
    def source(self):return Path(self.settings.value('source','',type=str)) if self.settings.value('source','',type=str) else None
    def set_enabled(self,value):
        self.settings.setValue('enabled',bool(value));self.settings.sync()
        if not value:self.stop()
    def set_volume(self,value):
        self.settings.setValue('volume',max(0,min(100,int(value))));self.settings.sync()
        if self.output:self.output.setVolume(self.volume/100)
    def register(self,source):
        source=Path(source)
        if not source.is_file() or source.is_symlink() or not 16<=source.stat().st_size<=10*1024*1024:raise ValueError('16바이트~10MB의 MP3 또는 WAV 파일을 선택하세요.')
        with source.open('rb') as stream:header=stream.read(12)
        if source.suffix.lower()=='.mp3':
            if not (header[:3]==b'ID3' or header[0]==255 and header[1]&0xe0==0xe0):raise ValueError('MP3 파일 헤더를 확인하세요.')
        elif source.suffix.lower()=='.wav':
            try:
                with wave.open(str(source),'rb') as sound:
                    if sound.getnchannels() not in (1,2) or sound.getnframes()==0:raise ValueError('재생 가능한 WAV 파일이 아닙니다.')
            except (wave.Error,EOFError):raise ValueError('WAV 파일 헤더를 확인하세요.') from None
        else:raise ValueError('MP3 또는 WAV 파일을 선택하세요.')
        payload=source.read_bytes();digest=sha256(payload).hexdigest()
        if self.root.is_symlink():raise ValueError('사운드 보관 경로에 링크를 사용할 수 없습니다.')
        self.root.mkdir(parents=True,exist_ok=True);target=self.root/(digest+source.suffix.lower())
        if target.is_symlink():raise ValueError('사운드 보관 경로에 링크를 사용할 수 없습니다.')
        output=QSaveFile(str(target))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(payload)!=len(payload) or not output.commit():raise OSError('사운드를 저장하지 못했습니다.')
        self.stop();self.settings.setValue('source',str(target));self.settings.setValue('display_name',source.name);self.settings.sync()
        return target
    def allowed(self):
        if not self.enabled or not self.volume:return False
        # Respect the current logged-in account's master effects switch too.
        for widget in QApplication.topLevelWidgets():
            controller=getattr(widget,'sounds',None)
            if widget.isVisible() and controller is not None and hasattr(controller,'store'):
                try:
                    if not controller.store.popup_sound_enabled():return False
                except (sqlite3.Error,ValueError,PermissionError,RuntimeError):return False
        return True
    def play(self):
        if not self.allowed():self.stop();return False
        app=QApplication.instance()
        if app.platformName() in {'offscreen','minimal'}:return False
        source=self.source
        if source is None:return False
        if not source.is_file() or source.is_symlink():self.problem.emit('선택한 사운드가 없습니다. 파일을 다시 선택하세요.');return False
        try:
            from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput,QMediaDevices
            if not QMediaDevices.audioOutputs():self.problem.emit('사용 가능한 오디오 출력 장치가 없습니다.');return False
            if self.player is None:
                self.player=QMediaPlayer(self);self.output=QAudioOutput(self);self.player.setAudioOutput(self.output)
                self.player.errorOccurred.connect(lambda *_:self.problem.emit('사운드 재생을 확인하세요: '+self.player.errorString()))
            # One player: replace the previous clip rather than overlap it.
            self.player.stop();self.player.setSource(QUrl.fromLocalFile(str(source)));self.output.setVolume(self.volume/100);self.player.play();return True
        except (RuntimeError,OSError) as exc:self.problem.emit(str(exc));return False
    def stop(self):
        if self.player:self.player.stop()


def login_sound():
    app=QApplication.instance();sound=getattr(app,'_sy_login_sound',None)
    if sound is None:app._sy_login_sound=sound=DrawSound(app,kind='login')
    return sound


def warning_sound():
    app=QApplication.instance();sound=getattr(app,'_sy_warning_sound',None)
    if sound is None:app._sy_warning_sound=sound=DrawSound(app,kind='warning')
    return sound


def login_sound_settings(parent=None):
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QCheckBox,QLabel,QSlider,QFileDialog
    from .widgets import action
    from .ui_sounds import public_sound_settings
    sound=login_sound();dialog=QDialog(parent);dialog.setWindowTitle('로그인·경고·시작화면 소리 설정');dialog.resize(640,540)
    layout=QVBoxLayout(dialog);enabled=QCheckBox('로그인 성공 사운드');enabled.setChecked(sound.enabled);enabled.toggled.connect(sound.set_enabled);layout.addWidget(enabled)
    label=QLabel(sound.settings.value('display_name','로그인 MP3 파일을 선택하세요.',type=str));label.setWordWrap(True);layout.addWidget(label)
    def choose():
        name,_=QFileDialog.getOpenFileName(dialog,'로그인 성공 사운드 선택','','오디오 파일 (*.mp3 *.wav)')
        if not name:return
        try:sound.register(name);label.setText(sound.settings.value('display_name','',type=str))
        except (ValueError,OSError) as exc:label.setText(str(exc))
    row=QHBoxLayout();row.addWidget(action('로그인 사운드 파일 선택',choose));row.addWidget(action('미리 듣기',sound.play));layout.addLayout(row)
    volume=QSlider(Qt.Orientation.Horizontal);volume.setRange(0,100);volume.setValue(sound.volume);volume.valueChanged.connect(sound.set_volume);layout.addWidget(QLabel('로그인 사운드 음량'));layout.addWidget(volume)
    warning=warning_sound();warning_enabled=QCheckBox('메시지 경고·알림 사운드');warning_enabled.setChecked(warning.enabled);warning_enabled.toggled.connect(warning.set_enabled);layout.addWidget(warning_enabled)
    warning_label=QLabel(warning.settings.value('display_name','파일 미선택: 짧은 기본 경고음 사용',type=str));warning_label.setWordWrap(True);layout.addWidget(warning_label)
    def choose_warning():
        name,_=QFileDialog.getOpenFileName(dialog,'메시지 경고·알림 사운드 선택','','오디오 파일 (*.mp3 *.wav)')
        if not name:return
        try:warning.register(name);warning_label.setText(warning.settings.value('display_name','',type=str))
        except (ValueError,OSError) as exc:warning_label.setText(str(exc))
    warning_row=QHBoxLayout();warning_row.addWidget(action('경고 사운드 파일 선택',choose_warning));warning_row.addWidget(action('경고 소리 미리 듣기',warning.play));layout.addLayout(warning_row)
    warning_volume=QSlider(Qt.Orientation.Horizontal);warning_volume.setRange(0,100);warning_volume.setValue(warning.volume);warning_volume.valueChanged.connect(warning.set_volume);layout.addWidget(QLabel('경고 사운드 음량'));layout.addWidget(warning_volume)
    public=QCheckBox('로그인 전 팝업·경고 효과음');public.setChecked(public_sound_settings().value('enabled',True,type=bool))
    def public_toggle(value):
        settings=public_sound_settings();settings.setValue('enabled',value);settings.sync()
        player=getattr(QApplication.instance(),'_sy_public_cue',None)
        if not value and player:player.stop()
    public.toggled.connect(public_toggle);layout.addWidget(public)
    note=QLabel('선택한 MP3/WAV는 이 PC에만 보관됩니다. 로그인 후 팝업·경고음은 환경설정의 전체 효과음 설정을 따릅니다.');note.setWordWrap(True);layout.addWidget(note)
    layout.addWidget(action('이 창 닫기',dialog.accept));dialog.finished.connect(lambda *_:(sound.stop(),warning.stop()));dialog.exec()
