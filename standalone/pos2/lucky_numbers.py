"""Offline entertainment only: six unique, uniformly random numbers 1..45."""
import math
from pathlib import Path
import secrets
from types import SimpleNamespace
from PySide6.QtCore import Qt,QTimer,Signal,QRectF
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QImageReader,QPixmap
from PySide6.QtWidgets import QApplication,QDialog,QHBoxLayout,QLabel,QMessageBox,QVBoxLayout,QWidget
from .widgets import Page,action

COLORS=('#D2A845','#6599BF','#D47D86','#8996A4','#709D7C')


def ball_color(number):return COLORS[min((number-1)//10,4)]


class LuckyMachine(QWidget):
    clicked=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.frame=0;self.running=False;self.number=None
        self.setMinimumSize(340,350);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('행운의 숫자 추첨기 · 클릭하면 한 개 추첨')
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.clicked.emit()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale=min(self.width()/420,self.height()/380);p.translate((self.width()-420*scale)/2,(self.height()-380*scale)/2);p.scale(scale,scale)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#E6EFEA'));p.drawEllipse(QRectF(63,320,294,25))
        p.setBrush(QColor('#285F50'));p.drawRoundedRect(QRectF(126,267,168,67),19,19)
        p.setBrush(QColor('#B8A16B'));p.drawRoundedRect(QRectF(145,281,130,16),5,5)
        p.setPen(QColor('#FFF9E9'));font=QFont(p.font());font.setPixelSize(12);font.setBold(True);p.setFont(font);p.drawText(QRectF(126,306,168,20),Qt.AlignmentFlag.AlignCenter,'SY LUCKY MACHINE')
        p.setPen(QPen(QColor('#819F95'),4));p.setBrush(QColor('#F6FBF9'));p.drawEllipse(QRectF(93,25,234,234))
        p.setPen(QPen(QColor('#CFDFD7'),2));p.drawEllipse(QRectF(105,37,210,210))
        for i in range(21):
            angle=(i*2.39996)+(self.frame*.17 if self.running else 0)
            radius=25+(i%6)*13
            x=210+math.cos(angle)*radius;y=146+math.sin(angle)*radius
            if not self.running:y=min(219,y+26)
            p.setPen(QPen(QColor('#FFFFFF'),1));p.setBrush(QColor(COLORS[i%5]));p.drawEllipse(QRectF(x-12,y-12,24,24))
            p.setPen(QColor('#FFFFFF'));font.setPixelSize(10);p.setFont(font);p.drawText(QRectF(x-12,y-12,24,24),Qt.AlignmentFlag.AlignCenter,str(i*2+1))
        p.setPen(QPen(QColor('#FFFFFF'),5));p.drawArc(QRectF(108,40,201,201),35*16,72*16)
        p.setPen(QPen(QColor('#B8A16B'),5));p.drawLine(324,134,352,134);p.drawLine(352,134,352,193)
        p.setBrush(QColor('#285F50'));p.drawEllipse(QRectF(342,181,21,31))
        p.setBrush(QColor('#D7E6DD'));p.setPen(Qt.PenStyle.NoPen);p.drawRoundedRect(QRectF(181,249,58,29),10,10)
        if self.number:
            p.setBrush(QColor(ball_color(self.number)));p.drawEllipse(QRectF(184,244,52,52))
            p.setPen(QColor('#FFFFFF'));font.setPixelSize(25);font.setBold(True);p.setFont(font);p.drawText(QRectF(184,244,52,52),Qt.AlignmentFlag.AlignCenter,str(self.number))
        p.setPen(QColor('#547264'));font.setPixelSize(14);p.setFont(font);p.drawText(QRectF(0,350,420,25),Qt.AlignmentFlag.AlignCenter,'공을 섞는 중…' if self.running else '추첨기를 마우스로 눌러 보세요')


class LuckyNumbersPage(Page):
    def __init__(self,window):
        super().__init__(window,'행운의 숫자','가볍게 즐기는 나만의 추첨 · 1~45 중 중복 없이 6개 · 로그인·인터넷 불필요')
        self.remaining=list(range(1,46));self.drawn=[];self.ticks=0
        row=QHBoxLayout();self.machine=LuckyMachine();self.machine.clicked.connect(self.draw);row.addWidget(self.machine,3)
        reference=QVBoxLayout();photo=QLabel();photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        reader=QImageReader(str(Path(__file__).resolve().parent/'assets'/'lottery-machine.jpg'));reader.setAutoTransform(True)
        photo.setPixmap(QPixmap.fromImage(reader.read()).scaled(225,270,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));reference.addWidget(photo)
        credit=QLabel('참고 사진: National Lottery machine Guinevere\nMatt Brown · CC BY 2.0 · Wikimedia Commons');credit.setWordWrap(True);credit.setStyleSheet('color:#7C8F85;font-size:10px;');reference.addWidget(credit)
        source=QLabel('<a href="https://commons.wikimedia.org/wiki/File:National_Lottery_machine_Guinevere.jpg">사진 출처·라이선스 보기 (인터넷)</a>');source.setOpenExternalLinks(True);source.setWordWrap(True);reference.addWidget(source);reference.addStretch();row.addLayout(reference,1);self.body.addLayout(row)
        slots=QHBoxLayout();self.slots=[]
        for _ in range(6):
            item=QLabel('?');item.setAlignment(Qt.AlignmentFlag.AlignCenter);item.setFixedSize(66,66);self.slots.append(item);slots.addWidget(item)
        slots.addStretch();self.body.addLayout(slots)
        controls=QHBoxLayout();self.draw_button=action('추첨기 돌리기 · 1개 뽑기',self.draw,primary=True);controls.addWidget(self.draw_button)
        controls.addWidget(action('새 추첨',lambda:self.reset()));self.copy_button=action('번호 복사',self.copy);controls.addWidget(self.copy_button);controls.addStretch();self.body.addLayout(controls)
        self.result=QLabel();self.result.setWordWrap(True);self.body.addWidget(self.result)
        note=QLabel('재미용 무작위 번호입니다. 당첨을 예측하거나 확률을 높이지 않습니다. 실제 복권 구매·결제·공식 추첨과 연결되지 않으며 결과는 파일에 저장하지 않습니다.');note.setWordWrap(True);note.setStyleSheet('color:#8A7753;background:#FFF5E0;padding:10px;border-radius:8px;');self.body.addWidget(note)
        self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.animate);self.update_result()
    def refresh(self):self.update_result()
    def draw(self):
        if self.timer.isActive() or len(self.drawn)>=6:return
        self.ticks=0;self.machine.running=True;self.machine.number=None;self.draw_button.setEnabled(False);self.timer.start()
    def animate(self):
        self.machine.frame+=1;self.ticks+=1;self.machine.update()
        if self.ticks>=24:self.finish_draw()
    def finish_draw(self):
        if not self.timer.isActive() or len(self.drawn)>=6:return
        self.timer.stop();number=secrets.choice(self.remaining);self.remaining.remove(number);self.drawn.append(number)
        self.machine.running=False;self.machine.number=number;self.machine.update();self.update_result()
    def update_result(self):
        for i,item in enumerate(self.slots):
            value=self.drawn[i] if i<len(self.drawn) else None;item.setText(str(value) if value else '?')
            item.setStyleSheet(f"font-size:26px;font-weight:700;border-radius:33px;background:{ball_color(value) if value else '#E7EEE8'};color:{'#FFFFFF' if value else '#9CAC9F'};")
        complete=len(self.drawn)==6;self.draw_button.setEnabled(not complete and not self.timer.isActive());self.copy_button.setEnabled(bool(self.drawn))
        self.draw_button.setText('6개 추첨 완료' if complete else f'추첨기 돌리기 · {len(self.drawn)+1}번째 뽑기')
        self.result.setText('완료 · 오름차순: '+', '.join(map(str,sorted(self.drawn))) if complete else f'{len(self.drawn)} / 6개 · 한 번 누를 때마다 한 개씩 나옵니다.')
    def reset(self,confirm=True):
        if confirm and self.drawn and QMessageBox.question(self,'새 추첨','현재 번호를 지우고 새로 뽑을까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.timer.stop();self.remaining=list(range(1,46));self.drawn=[];self.machine.running=False;self.machine.number=None;self.machine.update();self.update_result()
    def copy(self):
        if self.drawn:QApplication.clipboard().setText('행운의 숫자 (재미용): '+', '.join(map(str,sorted(self.drawn))))


class LuckyNumbersDialog(QDialog):
    def __init__(self):
        super().__init__(None);self.setWindowTitle('행운의 숫자 · SY POS');self.resize(970,760)
        self.setWindowModality(Qt.WindowModality.NonModal)
        layout=QVBoxLayout(self);self.page=LuckyNumbersPage(SimpleNamespace(store=None));layout.addWidget(self.page);layout.addWidget(action('닫기',self.close))
    def closeEvent(self,event):self.page.timer.stop();self.page.machine.running=False;self.page.update_result();event.accept()
    def reject(self):self.close()


def open_lucky_numbers(parent=None):
    from shiboken6 import isValid
    app=QApplication.instance();dialog=getattr(app,'_sy_lucky_window',None)
    if dialog is None or not isValid(dialog):
        dialog=LuckyNumbersDialog();app._sy_lucky_window=dialog
    dialog.showNormal();dialog.raise_();dialog.activateWindow();return dialog
