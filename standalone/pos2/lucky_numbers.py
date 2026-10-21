"""Offline entertainment only: six unique, uniformly random numbers 1..45."""
from pathlib import Path
import secrets
from types import SimpleNamespace
from PySide6.QtCore import Qt,QTimer,Signal,QRectF,QPointF,QElapsedTimer
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QLinearGradient,QRadialGradient,QPainterPath,QImage
from PySide6.QtWidgets import QApplication,QDialog,QFrame,QHBoxLayout,QLabel,QMessageBox,QVBoxLayout,QWidget,QCheckBox,QSlider,QFileDialog
from .widgets import Page,action

COLORS=('#D2A845','#6599BF','#D47D86','#8996A4','#709D7C')


def ball_color(number):return COLORS[min((number-1)//10,4)]


class LuckyMachine(QWidget):
    clicked=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.frame=0;self._running=False;self.number=None
        self.image=QImage(str(Path(__file__).resolve().parent/'assets'/'lucky-machine-realistic.png'))
        from .lucky_physics import BallMotion
        self.motion=BallMotion();self.elapsed=QElapsedTimer();self.idle_elapsed=0
        self.motion_timer=QTimer(self);self.motion_timer.setInterval(16);self.motion_timer.timeout.connect(self.advance_motion)
        self.setMinimumSize(340,350);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('행운의 숫자 추첨기 · 클릭하면 한 개 추첨')
    @property
    def running(self):return self._running
    @running.setter
    def running(self,value):
        self._running=bool(value);self.idle_elapsed=0
        if self.isVisible() and not self.motion_timer.isActive():self.elapsed.start();self.motion_timer.start()
    def showEvent(self,event):
        self.idle_elapsed=0;self.elapsed.start();self.motion_timer.start();super().showEvent(event)
    def hideEvent(self,event):
        self.motion_timer.stop();super().hideEvent(event)
    def advance_motion(self):
        seconds=min(.05,self.elapsed.restart()/1000)
        self.motion.advance(seconds,self.running);self.frame+=1;self.update()
        if not self.running:
            self.idle_elapsed+=seconds
            if self.idle_elapsed>=5:self.motion_timer.stop()
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.clicked.emit()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale=min(self.width()/420,self.height()/400);p.translate((self.width()-420*scale)/2,(self.height()-400*scale)/2);p.scale(scale,scale)
        font=QFont(p.font());font.setBold(True)
        def rounded(rect,colors,radius=8):
            gradient=QLinearGradient(rect.topLeft(),rect.bottomRight())
            for position,color in colors:gradient.setColorAt(position,QColor(color))
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(gradient);p.drawRoundedRect(rect,radius,radius)
        def ball(x,y,radius,number,angle=0):
            color=QColor(ball_color(number));gradient=QRadialGradient(QPointF(x-radius*.35,y-radius*.45),radius*1.6)
            gradient.setColorAt(0,color.lighter(180));gradient.setColorAt(.4,color);gradient.setColorAt(1,color.darker(180))
            p.setPen(QPen(color.darker(130),.7));p.setBrush(gradient);p.drawEllipse(QRectF(x-radius,y-radius,radius*2,radius*2))
            p.save();p.translate(x,y);p.rotate(angle)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#FDFDF6'));p.drawEllipse(QRectF(-radius*.6,-radius*.55,radius*1.2,radius*1.2))
            p.setPen(QColor('#24313A'));font.setPixelSize(round(radius*.95));p.setFont(font);p.drawText(QRectF(-radius,-radius*.9,radius*2,radius*2),Qt.AlignmentFlag.AlignCenter,str(number));p.restore()
        if not self.image.isNull():
            # Original generated product-render asset; numbers remain live UI,
            # never baked into a decorative photograph or fetched online.
            p.drawImage(QRectF(50,0,320,400),self.image)
            for particle in sorted(self.motion.balls,key=lambda b:b.y):ball(207+particle.x,142+particle.y,self.motion.ball_radius,particle.number,particle.angle)
            p.setPen(QPen(QColor(255,255,255,100),4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.setBrush(Qt.BrushStyle.NoBrush);p.drawArc(QRectF(100,38,211,211),58*16,66*16)
            rounded(QRectF(177,298,59,21),((0,'#091419'),(1,'#253B3B')),2)
            p.setPen(QColor('#D7F8DF'));font.setPixelSize(10);p.setFont(font);p.drawText(QRectF(177,298,59,21),Qt.AlignmentFlag.AlignCenter,'MIXING' if self.running else f'{self.number:02d}' if self.number else 'READY')
            if self.number:ball(308,299,16,self.number)
            return
        # Soft stage lighting, chrome structure and a glass mixing chamber.
        stage=QRadialGradient(QPointF(204,164),193);stage.setColorAt(0,QColor('#FFFFFF'));stage.setColorAt(1,QColor('#EAF2ED'))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(stage);p.drawRoundedRect(QRectF(14,4,392,357),28,28)
        shadow=QRadialGradient(QPointF(210,343),146);shadow.setColorAt(0,QColor(25,50,44,90));shadow.setColorAt(1,QColor(25,50,44,0))
        p.setBrush(shadow);p.drawEllipse(QRectF(63,326,294,31))
        chrome=((0,'#7D929D'),(.2,'#EFF5F7'),(.45,'#A4B5BE'),(.62,'#F8FCFD'),(1,'#6C8391'))
        for x in (106,286):rounded(QRectF(x,176,23,128),chrome,9)
        outlet=QPainterPath();outlet.moveTo(305,183);outlet.cubicTo(363,181,360,228,337,254)
        p.setPen(QPen(QColor('#738A96'),18,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.setBrush(Qt.BrushStyle.NoBrush);p.drawPath(outlet)
        p.setPen(QPen(QColor('#E5EFF3'),10,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.drawPath(outlet)
        glass=QRadialGradient(QPointF(168,79),220);glass.setColorAt(0,QColor('#FFFFFF'));glass.setColorAt(.55,QColor('#D6E8ED'));glass.setColorAt(1,QColor('#7EA6B1'))
        p.setBrush(glass);p.setPen(QPen(QColor('#839FA9'),3));p.drawEllipse(QRectF(86,17,248,248))
        p.setPen(QPen(QColor('#F4FAFC'),2));p.setBrush(Qt.BrushStyle.NoBrush);p.drawEllipse(QRectF(92,23,236,236))
        p.save();p.translate(210,141);p.rotate(self.frame*11 if self.running else -22)
        for angle in (0,120,240):
            p.save();p.rotate(angle);rounded(QRectF(-6,-78,12,86),chrome,5);p.restore()
        p.restore()
        p.setBrush(QColor('#A3BAC2'));p.setPen(QPen(QColor('#E8F3F6'),2));p.drawEllipse(QRectF(197,128,26,26))
        for particle in sorted(self.motion.balls,key=lambda b:b.y):ball(210+particle.x,141+particle.y,self.motion.ball_radius,particle.number,particle.angle)
        # Reflection stays over the balls, as on the front of real glass.
        p.setPen(QPen(QColor(255,255,255,210),7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.setBrush(Qt.BrushStyle.NoBrush);p.drawArc(QRectF(101,32,218,218),52*16,77*16)
        p.setPen(QPen(QColor(255,255,255,95),3));p.drawArc(QRectF(111,42,198,198),-55*16,52*16)
        rounded(QRectF(93,280,234,57),((0,'#385C64'),(.45,'#18363F'),(1,'#0C232D')),13)
        rounded(QRectF(88,332,244,10),chrome,4)
        rounded(QRectF(170,291,80,32),((0,'#0B1F24'),(1,'#24454A')),5)
        p.setPen(QColor('#D7F8DF'));font.setPixelSize(15);p.setFont(font);p.drawText(QRectF(170,292,80,29),Qt.AlignmentFlag.AlignCenter,'MIXING' if self.running else f'{self.number:02d}' if self.number else 'READY')
        p.setPen(QColor('#D2BE83'));font.setPixelSize(9);p.setFont(font);p.drawText(QRectF(98,296,67,22),Qt.AlignmentFlag.AlignCenter,'SY LUCKY')
        p.setBrush(QColor('#7CE1A6' if self.running else '#B8C6CB'));p.setPen(Qt.PenStyle.NoPen);p.drawEllipse(QRectF(299,299,10,10))
        rounded(QRectF(316,253,43,14),chrome,4)
        if self.number:ball(337,242,20,self.number)
        p.setPen(QColor('#547264'));font.setPixelSize(13);p.setFont(font);p.drawText(QRectF(0,370,420,23),Qt.AlignmentFlag.AlignCenter,'공을 섞는 중…' if self.running else '추첨기 클릭 · 한 개씩 뽑기')


class LuckyNumbersPage(Page):
    def __init__(self,window):
        super().__init__(window,'행운의 숫자','한 개씩 또는 자동으로 · 1~45 중 6개씩 5줄 · 로그인·인터넷 불필요')
        self.remaining=list(range(1,46));self.drawn=[];self.results=[];self.ticks=0;self.batch_rows=0
        row=QHBoxLayout();self.machine=LuckyMachine();self.machine.clicked.connect(self.draw);row.addWidget(self.machine,1)
        panel=QFrame();panel.setObjectName('luckyResults');panel.setStyleSheet('QFrame#luckyResults{background:#F5FAF6;border:1px solid #D8E7DD;border-radius:16px;}')
        reference=QVBoxLayout(panel);reference.setContentsMargins(16,18,16,18);reference.setSpacing(14)
        title=QLabel('나의 행운 번호 · 5줄');title.setStyleSheet('font-size:19px;font-weight:700;color:#285F50;');reference.addWidget(title)
        self.rows=[]
        for i in range(5):
            line=QHBoxLayout();line.setSpacing(6);tag=QLabel(chr(65+i));tag.setFixedWidth(22);tag.setStyleSheet('color:#547264;font-weight:700;');line.addWidget(tag)
            values=[]
            for j in range(6):
                item=QLabel('?');item.setAlignment(Qt.AlignmentFlag.AlignCenter);item.setFixedSize(44,44);item.setAccessibleName(f'{i+1}번째 줄 {j+1}번째 번호');values.append(item);line.addWidget(item)
            line.addStretch();reference.addLayout(line);self.rows.append(values)
        hint=QLabel('한 줄에 6개 · 완성된 번호는 오름차순으로 표시합니다.');hint.setWordWrap(True);hint.setStyleSheet('color:#547264;');reference.addWidget(hint);reference.addStretch();row.addWidget(panel,1);self.body.addLayout(row,1)
        controls=QHBoxLayout();self.draw_button=action('1개씩 뽑기',self.draw,primary=True);controls.addWidget(self.draw_button)
        self.six_button=action('6개 한 번에 뽑기',self.draw_six);controls.addWidget(self.six_button)
        self.five_button=action('5줄 자동 채우기',self.draw_five);controls.addWidget(self.five_button);controls.addStretch();self.body.addLayout(controls)
        tools=QHBoxLayout();tools.addWidget(action('새 추첨',lambda:self.reset()));self.copy_button=action('번호 복사',self.copy);tools.addWidget(self.copy_button);tools.addStretch();self.body.addLayout(tools)
        from .lucky_audio import DrawSound
        self.draw_sound=DrawSound(self);audio=QHBoxLayout();self.sound_enabled=QCheckBox('추첨 사운드');self.sound_enabled.setChecked(self.draw_sound.enabled);self.sound_enabled.toggled.connect(self.draw_sound.set_enabled);audio.addWidget(self.sound_enabled)
        audio.addWidget(action('사운드 파일 선택',lambda:self.choose_sound()));audio.addWidget(action('소리 미리 듣기',self.draw_sound.play));audio.addWidget(QLabel('음량'))
        self.sound_volume=QSlider(Qt.Orientation.Horizontal);self.sound_volume.setRange(0,100);self.sound_volume.setValue(self.draw_sound.volume);self.sound_volume.setMaximumWidth(130);self.sound_volume.valueChanged.connect(self.draw_sound.set_volume);audio.addWidget(self.sound_volume);audio.addStretch();self.body.addLayout(audio)
        self.sound_status=QLabel();self.sound_status.setWordWrap(True);self.sound_status.setText(self.sound_description());self.body.addWidget(self.sound_status);self.draw_sound.problem.connect(self.sound_status.setText)
        self.open_sound=DrawSound(self,kind='open');opening=QHBoxLayout();self.open_sound_enabled=QCheckBox('메뉴 열기 사운드');self.open_sound_enabled.setChecked(self.open_sound.enabled);self.open_sound_enabled.toggled.connect(self.open_sound.set_enabled);opening.addWidget(self.open_sound_enabled)
        opening.addWidget(action('열기 사운드 선택',lambda:self.choose_sound('open')));opening.addWidget(action('열기 소리 미리 듣기',self.open_sound.play));opening.addWidget(QLabel('음량'))
        self.open_sound_volume=QSlider(Qt.Orientation.Horizontal);self.open_sound_volume.setRange(0,100);self.open_sound_volume.setValue(self.open_sound.volume);self.open_sound_volume.setMaximumWidth(130);self.open_sound_volume.valueChanged.connect(self.open_sound.set_volume);opening.addWidget(self.open_sound_volume);opening.addStretch();self.body.addLayout(opening)
        self.open_sound_status=QLabel(self.sound_description('open'));self.open_sound_status.setWordWrap(True);self.open_sound.problem.connect(self.open_sound_status.setText);self.body.addWidget(self.open_sound_status)
        self.result=QLabel();self.result.setWordWrap(True);self.body.addWidget(self.result)
        note=QLabel('재미용 무작위 번호이며 당첨을 예측하거나 확률을 높이지 않습니다. 각 줄 안에서는 중복이 없고, 줄 사이에는 같은 번호가 나올 수 있습니다. 실제 복권 구매·결제와 연결되지 않으며 결과는 파일에 저장하지 않습니다.');note.setWordWrap(True);note.setStyleSheet('color:#8A7753;background:#FFF5E0;padding:10px;border-radius:8px;');self.body.addWidget(note)
        self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.animate);self.update_result()
    def refresh(self):self.update_result()
    def sound_description(self,kind='draw'):
        sound=self.draw_sound if kind=='draw' else self.open_sound
        return ('추첨 소리: ' if kind=='draw' else '열기 소리: ')+sound.description()
    def choose_sound(self,kind='draw'):
        name,_=QFileDialog.getOpenFileName(self,'내 PC에서만 사용할 추첨 사운드 선택','','오디오 파일 (*.mp3 *.wav)')
        if not name:return
        sound=self.draw_sound if kind=='draw' else self.open_sound;status=self.sound_status if kind=='draw' else self.open_sound_status
        try:sound.register(name);status.setText(self.sound_description(kind))
        except (ValueError,OSError) as exc:status.setText(str(exc))
    def showEvent(self,event):
        super().showEvent(event)
        # Popup accessibility wrapping can reparent/show the page twice in one
        # event cycle. Play only once, after the final visible layout settles.
        if not getattr(self,'_open_sound_pending',False):
            self._open_sound_pending=True;QTimer.singleShot(0,self,self.play_open_sound)
    def play_open_sound(self):
        self._open_sound_pending=False
        if self.isVisible():self.open_sound.play()
    def hideEvent(self,event):self.draw_sound.stop();self.open_sound.stop();super().hideEvent(event)
    def draw(self):
        self.start_draw(0)
    def draw_six(self):self.start_draw(1)
    def draw_five(self):self.start_draw(5-len(self.results))
    def start_draw(self,batch_rows):
        if self.timer.isActive() or len(self.results)>=5:return
        self.open_sound.stop()
        if len(self.drawn)==6:self.remaining=list(range(1,46));self.drawn=[]
        self.batch_rows=batch_rows;self.ticks=0;self.machine.running=True;self.machine.number=None;self.timer.start();self.update_result()
    def animate(self):
        self.ticks+=1
        if self.ticks>=60:self.finish_draw()
    def finish_draw(self):
        if not self.timer.isActive() or len(self.results)>=5:return
        self.timer.stop()
        for index in range(max(1,self.batch_rows)):
            if index:self.remaining=list(range(1,46));self.drawn=[]
            count=6-len(self.drawn) if self.batch_rows else 1
            for _ in range(count):
                number=secrets.choice(self.remaining);self.remaining.remove(number);self.drawn.append(number)
            if len(self.drawn)==6:self.results.append(sorted(self.drawn))
        self.batch_rows=0;self.machine.running=False;self.machine.number=self.drawn[-1];self.machine.update();self.update_result()
        self.draw_sound.play() # One cue when the result appears, also for a batch.
    def update_result(self):
        for i,items in enumerate(self.rows):
            values=self.results[i] if i<len(self.results) else self.drawn if i==len(self.results) and len(self.drawn)<6 else []
            for j,item in enumerate(items):
                value=values[j] if j<len(values) else None;item.setText(str(value) if value else '?')
                item.setStyleSheet(f"font-size:20px;font-weight:700;border-radius:22px;background:{ball_color(value) if value else '#E7EEE8'};color:{'#FFFFFF' if value else '#9CAC9F'};")
        complete=len(self.results)==5;enabled=not complete and not self.timer.isActive()
        for button in (self.draw_button,self.six_button,self.five_button):button.setEnabled(enabled)
        self.copy_button.setEnabled(bool(self.results));self.draw_button.setText('5줄 추첨 완료' if complete else '1개씩 뽑기')
        pending=len(self.drawn) if len(self.drawn)<6 else 0
        self.result.setText('5줄 추첨 완료 · 새 추첨을 누르면 다시 시작합니다.' if complete else f'{len(self.results)} / 5줄 완성 · '+(f'다음 줄 {pending} / 6개 · ' if pending else '')+'한 개씩 또는 자동으로 뽑아 보세요.')
    def reset(self,confirm=True):
        if confirm and (self.drawn or self.results) and QMessageBox.question(self,'새 추첨','현재 5줄의 번호를 모두 지우고 새로 뽑을까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.timer.stop();self.draw_sound.stop();self.remaining=list(range(1,46));self.drawn=[];self.results=[];self.batch_rows=0;self.machine.running=False;self.machine.number=None;self.machine.update();self.update_result()
    def copy(self):
        if self.results:QApplication.clipboard().setText('행운의 숫자 (재미용)\n'+'\n'.join(f'{chr(65+i)}: '+', '.join(map(str,values)) for i,values in enumerate(self.results)))


class LuckyNumbersDialog(QDialog):
    def __init__(self):
        super().__init__(None);self.setWindowTitle('행운의 숫자 · SY POS');self.resize(970,760)
        self.setWindowModality(Qt.WindowModality.NonModal)
        layout=QVBoxLayout(self);self.page=LuckyNumbersPage(SimpleNamespace(store=None));layout.addWidget(self.page);layout.addWidget(action('닫기',self.close))
    def closeEvent(self,event):self.page.timer.stop();self.page.draw_sound.stop();self.page.open_sound.stop();self.page.machine.running=False;self.page.update_result();event.accept()
    def reject(self):self.close()


def open_lucky_numbers(parent=None):
    from shiboken6 import isValid
    app=QApplication.instance();dialog=getattr(app,'_sy_lucky_window',None)
    if dialog is None or not isValid(dialog):
        dialog=LuckyNumbersDialog();app._sy_lucky_window=dialog
    dialog.showNormal();dialog.raise_();dialog.activateWindow()
    if not getattr(app,'_sy_retired_games_checked',False):
        app._sy_retired_games_checked=True
        from .retired_games import offer_cleanup
        QTimer.singleShot(0,dialog,lambda:offer_cleanup(dialog,only_if_present=True))
    return dialog
