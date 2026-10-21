"""Approved default sounds with optional private, per-PC user overrides."""
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
        if kind not in {'draw','open','login','warning','click','context'}:raise ValueError('알 수 없는 프로그램 효과음입니다.')
        self.kind=kind;self.settings=settings if settings is not None else QSettings('SY-POS',{'draw':'LuckyDrawSound','open':'LuckyOpenSound','login':'LoginSound','warning':'WarningSound','click':'MouseClickSound','context':'ContextMenuSound'}[kind])
        self.root=Path(root) if root else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'lucky-audio'/kind
        self.player=None;self.output=None;self.last_problem=''
        self.effect=None;self._mouse_prepared=None;self._mouse_effect=False
        self.problem.connect(self._remember_problem)
    def _remember_problem(self,message):self.last_problem=message
    @property
    def enabled(self):return self.settings.value('enabled',True,type=bool)
    @property
    def volume(self):return max(0,min(100,self.settings.value('volume',20,type=int)))
    @property
    def custom_source(self):return Path(self.settings.value('source','',type=str)) if self.settings.value('source','',type=str) else None
    @property
    def source(self):
        custom=self.custom_source
        if custom is not None and custom.is_file() and not custom.is_symlink():return custom
        from .audio_defaults import default_source
        return default_source(self.kind)
    def description(self):
        from .audio_defaults import SOUNDS
        custom=self.custom_source;source=self.source
        if custom is not None and source==custom:return '사용자 파일 · '+self.settings.value('display_name',custom.name,type=str)+' · 이 PC에만 저장'
        if source is not None:
            prefix='선택한 파일이 없어 기본음 사용 · ' if custom is not None else '기본음 자동 적용 · '
            return prefix+SOUNDS[self.kind][2]+' · '+source.name
        return '기본 사운드가 없습니다. ZIP 전체를 다시 풀거나 MP3/WAV를 선택하세요.'
    def use_default(self):
        self.stop();self.settings.remove('source');self.settings.remove('display_name');self.settings.sync();self.last_problem=''
        if self.kind in {'click','context'}:self.prepare_mouse()
    def set_enabled(self,value):
        self.settings.setValue('enabled',bool(value));self.settings.sync()
        if not value:self.stop()
        elif self.kind in {'click','context'}:self.prepare_mouse()
    def set_volume(self,value):
        self.settings.setValue('volume',max(0,min(100,int(value))));self.settings.sync()
        if self.output:self.output.setVolume(self.volume/100)
        if self.effect:self.effect.setVolume(self.volume/100)
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
        if self.kind in {'click','context'}:self.prepare_mouse()
        return target

    def _media_player(self):
        if self.player is None:
            from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
            self.player=QMediaPlayer(self);self.output=QAudioOutput(self);self.player.setAudioOutput(self.output)
            self.player.errorOccurred.connect(lambda *_:self.problem.emit('사운드 재생을 확인하세요: '+self.player.errorString()))

    def prepare_mouse(self):
        """Load once before input; replay never changes the source or queues a cue."""
        if self.kind not in {'click','context'} or not self.enabled or not self.volume:return False
        if QApplication.instance().platformName() in {'offscreen','minimal'}:return False
        try:
            source=self.source
            if source is None:return False
            info=source.stat();key=(str(source),info.st_mtime_ns,info.st_size)
            if key==self._mouse_prepared:return True
            from PySide6.QtMultimedia import QSoundEffect,QMediaDevices
            if not QMediaDevices.audioOutputs():return False
            from .audio_defaults import mouse_pcm_source
            pcm=mouse_pcm_source(self.kind,source)
            if pcm is not None:
                if self.player:self.player.stop()
                if self.effect is None:
                    self.effect=QSoundEffect(self)
                    self.effect.setLoopCount(1)
                self.effect.setVolume(self.volume/100)
                self.effect.setSource(QUrl.fromLocalFile(str(pcm)))
                self._mouse_effect=True
            else:
                # Custom WAVs can be preloaded directly; custom MP3s retain
                # their own content and use a persistent prepared media player.
                if source.suffix.lower()=='.wav':
                    if self.player:self.player.stop()
                    if self.effect is None:
                        self.effect=QSoundEffect(self);self.effect.setLoopCount(1)
                    self.effect.setVolume(self.volume/100)
                    self.effect.setSource(QUrl.fromLocalFile(str(source)))
                    self._mouse_effect=True
                else:
                    if self.effect:self.effect.stop()
                    self._media_player();self.player.stop()
                    self.player.setSource(QUrl.fromLocalFile(str(source)))
                    self.output.setVolume(self.volume/100);self._mouse_effect=False
            self._mouse_prepared=key
            return True
        except (RuntimeError,OSError,ImportError) as exc:
            self.problem.emit(str(exc));return False
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
        if self.kind in {'click','context'}:
            if not self.prepare_mouse():return False
            if self._mouse_effect:
                from PySide6.QtMultimedia import QSoundEffect
                if self.effect.status()!=QSoundEffect.Status.Ready:return False
                self.effect.setVolume(self.volume/100);self.effect.play()
            else:
                from PySide6.QtMultimedia import QMediaPlayer
                if self.player.mediaStatus() not in {QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.BufferedMedia,QMediaPlayer.MediaStatus.EndOfMedia}:
                    return False
                self.output.setVolume(self.volume/100);self.player.setPosition(0);self.player.play()
            self.last_problem='';return True
        source=self.source
        if source is None:self.problem.emit('기본 사운드가 없습니다. ZIP 전체를 다시 풀거나 MP3/WAV를 선택하세요.');return False
        if not source.is_file() or source.is_symlink():self.problem.emit('선택한 사운드가 없습니다. 파일을 다시 선택하세요.');return False
        try:
            from PySide6.QtMultimedia import QMediaDevices
            if not QMediaDevices.audioOutputs():self.problem.emit('사용 가능한 오디오 출력 장치가 없습니다.');return False
            self._media_player()
            # One player: replace the previous clip rather than overlap it.
            self.last_problem='';self.player.stop();self.player.setSource(QUrl.fromLocalFile(str(source)));self.output.setVolume(self.volume/100);self.player.play();return True
        except (RuntimeError,OSError,ImportError) as exc:self.problem.emit(str(exc));return False
    def stop(self):
        if self.player:self.player.stop()
        if self.effect:self.effect.stop()


def login_sound():
    app=QApplication.instance();sound=getattr(app,'_sy_login_sound',None)
    if sound is None:app._sy_login_sound=sound=DrawSound(app,kind='login')
    return sound


def warning_sound():
    app=QApplication.instance();sound=getattr(app,'_sy_warning_sound',None)
    if sound is None:app._sy_warning_sound=sound=DrawSound(app,kind='warning')
    return sound


def mouse_sound(kind):
    if kind not in {'click','context'}:raise ValueError('마우스 효과음을 확인하세요.')
    app=QApplication.instance();key='_sy_'+kind+'_sound';sound=getattr(app,key,None)
    if sound is None:
        sound=DrawSound(app,kind=kind);setattr(app,key,sound);sound.prepare_mouse()
    return sound


def prewarm_mouse_sounds():
    for kind in ('click','context'):
        mouse_sound(kind).prepare_mouse()


def login_sound_settings(parent=None):
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QCheckBox,QLabel,QSlider,QFileDialog,QGroupBox,QScrollArea,QWidget
    from .widgets import action
    from .ui_sounds import public_sound_settings
    dialog=QDialog(parent);dialog.setWindowTitle('프로그램 사운드 설정');dialog.resize(720,680);layout=QVBoxLayout(dialog)
    app=QApplication.instance()
    def lucky_sound(kind):
        attribute='_sy_settings_'+kind+'_sound';sound=getattr(app,attribute,None)
        if sound is None:sound=DrawSound(app,kind=kind);setattr(app,attribute,sound)
        return sound
    sounds=[(login_sound(),'로그인','로그인 성공 사운드'),(warning_sound(),'경고','메시지 경고·알림 사운드'),(mouse_sound('click'),'왼쪽 클릭','왼쪽 클릭 소리'),(mouse_sound('context'),'오른쪽 메뉴','오른쪽 메뉴 소리'),(lucky_sound('open'),'메뉴 열기','행운의 숫자 메뉴 열기'),(lucky_sound('draw'),'공 추첨','행운의 숫자 공 추첨')]
    scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();groups=QVBoxLayout(content);scroll.setWidget(content);layout.addWidget(scroll,1)
    for sound,caption,title in sounds:
        group=QGroupBox(title);section=QVBoxLayout(group);enabled=QCheckBox('사용');enabled.setChecked(sound.enabled);enabled.toggled.connect(sound.set_enabled)
        label=QLabel(sound.last_problem or sound.description());label.setWordWrap(True);sound.problem.connect(label.setText)
        def choose(checked=False,sound=sound,label=label,caption=caption):
            name,_=QFileDialog.getOpenFileName(dialog,caption+' 사운드 선택','','오디오 파일 (*.mp3 *.wav)')
            if not name:return
            try:sound.register(name);label.setText(sound.description())
            except (ValueError,OSError) as exc:label.setText(str(exc))
        def restore(checked=False,sound=sound,label=label):sound.use_default();label.setText(sound.description())
        def preview(checked=False,sound=sound,label=label):
            if not sound.allowed():label.setText('사용·음량·환경설정의 전체 효과음 설정을 확인하세요.');return
            if sound.play():label.setText('미리 듣기 재생 요청 · '+sound.description())
            elif QApplication.instance().platformName() in {'offscreen','minimal'}:label.setText('화면 검사 환경에서는 오디오를 재생하지 않습니다.')
        row=QHBoxLayout();row.addWidget(enabled);row.addWidget(action(caption+' 사운드 파일 선택',choose));row.addWidget(action('미리 듣기',preview));row.addWidget(action('기본음으로 복원',restore));row.addWidget(QLabel('음량'))
        volume=QSlider(Qt.Orientation.Horizontal);volume.setRange(0,100);volume.setValue(sound.volume);volume.valueChanged.connect(sound.set_volume);row.addWidget(volume);section.addLayout(row);section.addWidget(label);groups.addWidget(group)
    public=QCheckBox('로그인 전 팝업·경고·마우스 효과음');public.setChecked(public_sound_settings().value('enabled',True,type=bool))
    def public_toggle(value):
        settings=public_sound_settings();settings.setValue('enabled',value);settings.sync()
        player=getattr(QApplication.instance(),'_sy_public_cue',None)
        if not value and player:player.stop()
    public.toggled.connect(public_toggle);layout.addWidget(public)
    note=QLabel('제공된 MP3 6개가 기본음으로 자동 적용됩니다. 직접 선택한 MP3/WAV만 이 PC에 별도로 보관합니다. 로그인 후 효과음은 환경설정의 전체 효과음 설정을 따릅니다.');note.setWordWrap(True);layout.addWidget(note)
    layout.addWidget(action('이 창 닫기',dialog.accept));dialog.finished.connect(lambda *_:[sound.stop() for sound,_,_ in sounds]);dialog.exec()
