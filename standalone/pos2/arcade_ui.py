"""Keyboard/mouse arcade popups and atomic local high-score records."""
import json
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QElapsedTimer,QStandardPaths,QSaveFile,QIODevice,QRectF,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QPolygonF,QFont
from PySide6.QtWidgets import QApplication,QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QTabWidget
from .widgets import action,DataGrid
from .arcade import Blocks,Gomoku,Shooter,Jumper,Bubbles,Raccoon

GAMES={'blocks':('🧱 블록 퍼즐 · 테트리스 방식',Blocks,'← → 이동 · ↑ 회전 · ↓ 내리기 · Space 즉시 낙하'), 'gomoku':('⚫ 오목',Gomoku,'마우스 클릭으로 흑돌 놓기 · 컴퓨터와 자유 오목 (5개 이상)'), 'shooter':('🚀 우주 슈팅',Shooter,'← → 또는 A/D 이동 · Space 발사 (누르고 있기)')}
GAMES.update(jumper=('🏃 점프 어드벤처',Jumper,'← → / A D 이동 · ↑ / W / Space 점프 · 코인·적·3개 스테이지'),bubbles=('🫧 버블 아케이드',Bubbles,'← → 이동 · ↑ 점프 · Space / Z 버블 발사 · 갇힌 버블에 닿아 터뜨리기'))
GAMES['raccoon']=('🦝 너구리 · 과일 사다리',Raccoon,'← → / A D 이동 · ↑ ↓ / W S 사다리 · Space 점프 · 과일 모두 모으기 · 5개 스테이지 (자체 제작)')
COLORS=('#68D8EC','#7898FF','#E5B863','#E8D462','#79C99F','#B69BE8','#EB8D9A')


def paint_raccoon(owner,p):
    game=owner.game;p.fillRect(QRectF(0,0,500,600),QColor('#142D35'))
    for x,top,bottom in game.ladders:
        p.setPen(QPen(QColor('#D7B575'),5));p.drawLine(QPointF(x-12,top),QPointF(x-12,bottom));p.drawLine(QPointF(x+12,top),QPointF(x+12,bottom))
        p.setPen(QPen(QColor('#D7B575'),3))
        for y in range(top+7,bottom,14):p.drawLine(QPointF(x-12,y),QPointF(x+12,y))
    for x,y,width in game.platforms:
        p.fillRect(QRectF(x,y,width,14),QColor('#628579'));p.fillRect(QRectF(x,y,width,4),QColor('#B0DB91'))
    for i,(x,y) in enumerate(game.fruits):
        p.setPen(QPen(QColor('#F8D99A'),1));p.setBrush(QColor(('#F08F81','#E4BD65','#A695DB')[i%3]));p.drawEllipse(QPointF(x,y),9,10)
        p.setPen(QPen(QColor('#9AE08E'),3));p.drawLine(QPointF(x,y-8),QPointF(x+5,y-14))
    for enemy in game.enemies:
        x,y=enemy['x'],enemy['y'];p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#BC7590'));p.drawRoundedRect(QRectF(x,y,26,30),7,7)
        p.setBrush(QColor('#10232E'));p.drawEllipse(QPointF(x+7,y+9),3,3);p.drawEllipse(QPointF(x+19,y+9),3,3)
    if not game.invincible or int(game.invincible*10)%2:
        x,y=game.x,game.y;p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#B0A9A1'));p.drawEllipse(QRectF(x-12,y+16,25,14))
        p.setPen(QPen(QColor('#404449'),3));p.drawLine(QPointF(x-7,y+17),QPointF(x-7,y+28));p.drawLine(QPointF(x,y+16),QPointF(x,y+29))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#B0A9A1'));p.drawRoundedRect(QRectF(x,y+10,26,24),8,8)
        p.drawEllipse(QPointF(x+4,y+2),6,7);p.drawEllipse(QPointF(x+22,y+2),6,7);p.drawEllipse(QRectF(x-2,y-1,30,23))
        p.setBrush(QColor('#39454A'));p.drawRoundedRect(QRectF(x,y+5,26,9),4,4);p.setBrush(QColor('#FFF3CF'));p.drawEllipse(QPointF(x+7,y+9),2,2);p.drawEllipse(QPointF(x+19,y+9),2,2)
        p.setBrush(QColor('#283438'));p.drawEllipse(QPointF(x+13,y+17),3,2)
    p.setPen(QColor('#F4D993'));p.drawText(QRectF(12,10,475,30),Qt.AlignmentFlag.AlignLeft,f'STAGE {game.stage}     LIFE {game.lives}     TIME {max(0,int(game.time_left))}     FRUIT {len(game.fruits)}')


def paint_platforms(owner,p):
    game=owner.game;camera=getattr(game,'camera',0);p.save();p.translate(-camera,0)
    if owner.kind=='jumper':
        p.fillRect(QRectF(camera,0,500,600),QColor('#A5D4D3'))
        for x in range(0,2700,300):
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#75AE9D'));p.drawPolygon(QPolygonF([QPointF(x-100,580),QPointF(x+130,250),QPointF(x+330,580)]))
    for x,y,width in game.platforms:
        p.setPen(QPen(QColor('#6DA9A1'),1));p.setBrush(QColor('#397D73' if owner.kind=='bubbles' else '#B18D63'));p.drawRoundedRect(QRectF(x,y,width,22),3,3)
        p.fillRect(QRectF(x,y,width,5),QColor('#8EE2B2'))
    if owner.kind=='jumper':
        for x,y in game.coins:p.setBrush(QColor('#F2CB5D'));p.setPen(QPen(QColor('#B78C24'),2));p.drawEllipse(QPointF(x,y),9,12)
        p.setPen(QPen(QColor('#405B70'),4));p.drawLine(QPointF(2560,580),QPointF(2560,350));p.setBrush(QColor('#8059A5'));p.drawPolygon(QPolygonF([QPointF(2560,350),QPointF(2610,370),QPointF(2560,390)]))
        enemies=[(enemy[0],enemy[1]) for enemy in game.enemies]
    else:enemies=[(enemy['x'],enemy['y']) for enemy in game.enemies]
    for x,y in enemies:
        p.setPen(QPen(QColor('#884C64'),1));p.setBrush(QColor('#DE849D'));p.drawRoundedRect(QRectF(x,y,27,30),9,9);p.setBrush(QColor('#152B3E'));p.drawEllipse(QPointF(x+8,y+9),2,3);p.drawEllipse(QPointF(x+19,y+9),2,3)
    if not game.invincible or int(game.invincible*10)%2:
        p.setPen(QPen(QColor('#204E64'),2));p.setBrush(QColor('#5BADC9'));p.drawRoundedRect(QRectF(game.x,game.y,26,34),5,5)
        p.setBrush(QColor('#E4FAF3'));p.drawRoundedRect(QRectF(game.x+4,game.y+4,18,13),3,3);p.setBrush(QColor('#23415C'));p.drawEllipse(QPointF(game.x+17,game.y+10),2,3)
    if owner.kind=='bubbles':
        for orb in game.orbs:
            p.setPen(QPen(QColor('#EBBFE3' if orb['captured'] else '#9FE4ED'),2));p.setBrush(QColor(195,160,230,95) if orb['captured'] else QColor(125,210,225,65));p.drawEllipse(QPointF(orb['x'],orb['y']),17,17)
            if orb['captured']:p.setPen(QColor('#F2DE95'));p.drawText(QRectF(orb['x']-12,orb['y']-12,24,24),Qt.AlignmentFlag.AlignCenter,'★')
    p.restore();p.setPen(QColor('#173B48' if owner.kind=='jumper' else '#F1D88F'));p.drawText(QRectF(15,8,460,28),Qt.AlignmentFlag.AlignLeft,f'STAGE {game.stage}     LIFE {game.lives}')


class ScoreBook:
    def __init__(self,path=None):self.path=Path(path) if path else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'mini-arcade'/'scores.json'
    def rows(self):
        if not self.path.exists():return []
        if self.path.is_symlink() or self.path.stat().st_size>1_000_000:raise ValueError('게임 점수 파일을 안전하게 읽을 수 없습니다.')
        try:
            rows=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(rows,list) or any(not isinstance(row,dict) or row.get('game') not in GAMES or type(row.get('score')) is not int or not 0<=row['score']<=1_000_000_000 or not all(isinstance(row.get(key),str) for key in ('name','date','result')) for row in rows):raise ValueError()
            return rows[:200+len(GAMES)]
        except (ValueError,UnicodeError):raise ValueError('점수 파일이 손상되었습니다. 기존 파일은 덮어쓰지 않습니다.') from None
    def add(self,game,name,score,result):
        if game not in GAMES or type(score) is not int or not 0<=score<=1_000_000_000:raise ValueError('점수 값을 확인하세요.')
        rows=self.rows();rows.insert(0,dict(game=game,name=str(name).strip()[:24] or '플레이어',score=score,result=str(result)[:40],date=datetime.now().astimezone().isoformat(timespec='seconds')))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        output=QSaveFile(str(self.path));payload=json.dumps(rows[:200],ensure_ascii=False).encode('utf-8')
        retained=rows[:200]
        for game_kind in GAMES:
            best=max((row for row in rows if row['game']==game_kind),key=lambda row:row['score'],default=None)
            if best is not None and best not in retained:retained.append(best)
        payload=json.dumps(retained,ensure_ascii=False).encode('utf-8')
        if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(payload)!=len(payload) or not output.commit():raise OSError('게임 점수를 저장하지 못했습니다.')


class GameSurface(QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.setMinimumSize(310,350);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def geometry_scale(self):
        width,height=(500,500) if self.owner.kind=='gomoku' else (500,600)
        scale=min(self.width()/width,self.height()/height)
        return scale,(self.width()-width*scale)/2,(self.height()-height*scale)/2
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#0D1428'));p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale,ox,oy=self.geometry_scale();p.translate(ox,oy);p.scale(scale,scale);game=self.owner.game
        p.setClipRect(QRectF(0,0,500,500 if self.owner.kind=='gomoku' else 600))
        def block(x,y,color,size=26):
            p.setPen(QPen(QColor(color).lighter(140),1));p.setBrush(QColor(color));p.drawRoundedRect(QRectF(x,y,size-2,size-2),3,3)
        if self.owner.kind=='blocks':
            p.setPen(QColor('#25324B'))
            for y,row in enumerate(game.board):
                for x,value in enumerate(row):
                    if value:block(120+x*26,35+y*26,COLORS[value-1])
                    else:p.drawRect(QRectF(120+x*26,35+y*26,25,25))
            if not game.over:
                for x,y in game.cells:block(120+(game.x+x)*26,35+(game.y+y)*26,COLORS[game.kind])
            p.setPen(QColor('#E6CF8F'));p.drawText(QRectF(30,563,440,25),Qt.AlignmentFlag.AlignCenter,f'LEVEL {game.level}     LINES {game.lines}')
        elif self.owner.kind=='gomoku':
            p.fillRect(QRectF(13,13,474,474),QColor('#D7B574'));p.setPen(QPen(QColor('#70522F'),1))
            for i in range(15):p.drawLine(QPointF(26+i*32,26),QPointF(26+i*32,474));p.drawLine(QPointF(26,26+i*32),QPointF(474,26+i*32))
            for y,row in enumerate(game.board):
                for x,value in enumerate(row):
                    if value:
                        p.setBrush(QColor('#202434' if value==1 else '#FAF8EC'));p.setPen(QPen(QColor('#626577'),1));p.drawEllipse(QPointF(26+x*32,26+y*32),13,13)
            if game.last:
                x,y=game.last;p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor('#C64941'),2));p.drawEllipse(QPointF(26+x*32,26+y*32),5,5)
        elif self.owner.kind in {'jumper','bubbles'}:
            paint_platforms(self.owner,p)
        elif self.owner.kind=='raccoon':paint_raccoon(self.owner,p)
        else:
            p.setPen(QColor('#61789C'))
            for i in range(70):p.drawPoint((i*127)%500,(i*83+int(self.owner.elapsed_seconds*18))%600)
            p.setPen(Qt.PenStyle.NoPen)
            for x,y in game.enemies:
                p.setBrush(QColor(COLORS[int(y//38)%7]));p.drawPolygon(QPolygonF([QPointF(x-16,y+9),QPointF(x-12,y-7),QPointF(x-5,y-13),QPointF(x,y-4),QPointF(x+5,y-13),QPointF(x+12,y-7),QPointF(x+16,y+9),QPointF(x+5,y+5),QPointF(x,y+13),QPointF(x-5,y+5)]))
            p.setBrush(QColor('#72D8DA'))
            if not game.invincible or int(game.invincible*10)%2:p.drawPolygon(QPolygonF([QPointF(game.x,538),QPointF(game.x-18,575),QPointF(game.x,566),QPointF(game.x+18,575)]))
            p.setBrush(QColor('#F5DE7C'))
            for x,y in game.bullets:p.drawRoundedRect(QRectF(x-2,y,4,12),2,2)
            p.setBrush(QColor('#E88D98'))
            for x,y in game.enemy_bullets:p.drawEllipse(QPointF(x,y),4,6)
            p.setPen(QColor('#F2C788'));p.drawText(QRectF(15,8,460,30),Qt.AlignmentFlag.AlignLeft,f'WAVE {game.wave}     LIFE {game.lives}')
        if self.owner.paused or game.over:
            p.fillRect(QRectF(20,210,460,100),QColor(10,16,30,225));p.setPen(QColor('#F7DE96'));font=QFont(p.font());font.setPixelSize(24);font.setBold(True);p.setFont(font)
            text=('승리!' if getattr(game,'winner',0)==1 or getattr(game,'won',False) else '컴퓨터 승리' if getattr(game,'winner',0)==2 else 'GAME OVER') if game.over else '일시정지 · 계속하려면 P'
            p.drawText(QRectF(20,220,460,70),Qt.AlignmentFlag.AlignCenter,text)
        p.end()
    def keyPressEvent(self,event):
        if event.isAutoRepeat() and event.key() in (Qt.Key.Key_P,Qt.Key.Key_R):return
        self.owner.key(event.key(),True);event.accept()
    def keyReleaseEvent(self,event):
        if not event.isAutoRepeat():self.owner.key(event.key(),False)
        event.accept()
    def mousePressEvent(self,event):
        self.setFocus()
        if self.owner.kind=='gomoku' and event.button()==Qt.MouseButton.LeftButton and not self.owner.paused:
            scale,ox,oy=self.geometry_scale();x=(event.position().x()-ox)/scale;y=(event.position().y()-oy)/scale
            a,b=round((x-26)/32),round((y-26)/32)
            if abs(x-(26+a*32))<=15 and abs(y-(26+b*32))<=15:self.owner.game.human(a,b);self.owner.refresh()


class ArcadeGameDialog(QDialog):
    def __init__(self,kind,book=None,name='플레이어'):
        super().__init__(None);self.kind=kind;self.book=book or ScoreBook();self.player=name;self.saved=False;self.paused=False;self.elapsed_seconds=0;self.game=GAMES[kind][1]()
        self.setWindowTitle(GAMES[kind][0]+' · SY POS 미니 오락실');self.resize(650,810);self.setWindowModality(Qt.WindowModality.NonModal)
        layout=QVBoxLayout(self);title=QLabel(GAMES[kind][0]+'  ·  RETRO ARCADE');title.setStyleSheet('font-size:20px;color:#364D66;font-weight:700');layout.addWidget(title)
        self.score=QLabel();layout.addWidget(self.score);self.surface=GameSurface(self);layout.addWidget(self.surface,1)
        help=QLabel(GAMES[kind][2]+'\nP 일시정지 · R 새 게임 · 창을 옮겨 다른 업무를 하면 자동 일시정지');help.setWordWrap(True);layout.addWidget(help)
        controls=QHBoxLayout();self.pause_button=action('일시정지 / 계속 (P)',self.pause);controls.addWidget(self.pause_button);controls.addWidget(action('새 게임 (R)',self.restart));controls.addWidget(action('이 창 닫기',self.close));layout.addLayout(controls)
        self.status=QLabel('게임 점수는 이 Windows 사용자 PC에만 보관됩니다.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.timer=QTimer(self);self.timer.setInterval(16);self.timer.timeout.connect(self.tick);self.clock=QElapsedTimer();self.clock.start();self.timer.start();self.refresh()
    def save_score(self,reason):
        if self.saved:return
        self.saved=True
        try:self.book.add(self.kind,self.player,int(self.game.score),reason);self.status.setText('점수와 플레이 기록을 저장했습니다.')
        except (ValueError,OSError) as exc:self.status.setText(str(exc));self.saved=False
    def refresh(self):
        self.score.setText(f'점수 {self.game.score:,}  ·  플레이어 {self.player}');self.surface.update()
        if self.game.over:self.timer.stop();self.save_score('승리' if getattr(self.game,'winner',0)==1 or getattr(self.game,'won',False) else '게임 종료')
    def tick(self):
        delta=min(.05,self.clock.restart()/1000)
        if not self.paused:self.elapsed_seconds+=delta;self.game.tick(delta);self.refresh()
    def key(self,key,pressed):
        if pressed and key==Qt.Key.Key_P:self.pause();return
        if pressed and key==Qt.Key.Key_R:self.restart();return
        if self.paused or self.game.over:return
        if self.kind=='blocks' and pressed:
            if key==Qt.Key.Key_Left:self.game.move(-1)
            elif key==Qt.Key.Key_Right:self.game.move(1)
            elif key==Qt.Key.Key_Down:self.game.move(0,1)
            elif key==Qt.Key.Key_Up:self.game.rotate()
            elif key==Qt.Key.Key_Space:self.game.drop()
        elif self.kind=='shooter':
            if key in (Qt.Key.Key_Left,Qt.Key.Key_A):self.game.left=pressed
            elif key in (Qt.Key.Key_Right,Qt.Key.Key_D):self.game.right=pressed
            elif key==Qt.Key.Key_Space:self.game.fire=pressed
        elif self.kind=='raccoon':
            if key in (Qt.Key.Key_Left,Qt.Key.Key_A):self.game.left=pressed
            elif key in (Qt.Key.Key_Right,Qt.Key.Key_D):self.game.right=pressed
            elif key in (Qt.Key.Key_Up,Qt.Key.Key_W):self.game.up=pressed
            elif key in (Qt.Key.Key_Down,Qt.Key.Key_S):self.game.down=pressed
            elif key==Qt.Key.Key_Space:self.game.jump=pressed
        elif self.kind in {'jumper','bubbles'}:
            if key in (Qt.Key.Key_Left,Qt.Key.Key_A):self.game.left=pressed
            elif key in (Qt.Key.Key_Right,Qt.Key.Key_D):self.game.right=pressed
            elif key in (Qt.Key.Key_Up,Qt.Key.Key_W) or key==Qt.Key.Key_Space and self.kind=='jumper':self.game.jump=pressed
            elif key in (Qt.Key.Key_Space,Qt.Key.Key_Z) and self.kind=='bubbles':self.game.fire=pressed
        self.refresh()
    def pause(self):
        self.paused=not self.paused
        self.clear_keys()
        self.clock.restart();self.surface.setFocus();self.refresh()
    def clear_keys(self):
        for name in ('left','right','up','down','jump','fire'):
            if hasattr(self.game,name):setattr(self.game,name,False)
    def restart(self):
        if self.elapsed_seconds>1 or self.game.score:self.save_score('다시 시작')
        self.game=GAMES[self.kind][1]();self.saved=False;self.paused=False;self.elapsed_seconds=0;self.clock.restart();self.timer.start();self.surface.setFocus();self.refresh()
    def changeEvent(self,event):
        from PySide6.QtCore import QEvent
        if event.type()==QEvent.Type.ActivationChange and not self.isActiveWindow() and hasattr(self,'game'):
            self.paused=True
            self.clear_keys()
            self.refresh()
        super().changeEvent(event)
    def closeEvent(self,event):
        self.timer.stop()
        if self.elapsed_seconds>1 or self.game.score:self.save_score('중간 종료')
        super().closeEvent(event)


class ArcadeLobby(QDialog):
    def __init__(self):
        super().__init__(None);self.setWindowTitle('미니 오락실 · SY POS');self.resize(790,620);self.games={};self.book=ScoreBook()
        layout=QVBoxLayout(self);title=QLabel('🕹  SY MINI ARCADE');title.setStyleSheet('font-size:26px;color:#3A4D77;font-weight:700');layout.addWidget(title)
        self.name=QLineEdit('플레이어');self.name.setMaxLength(24);self.name.setPlaceholderText('점수표에 표시할 별명');layout.addWidget(self.name)
        self.rom_button=action('🎮 내 게임 · 마리오 / 보글보글 ROM 등록·실행',self.roms);layout.addWidget(self.rom_button)
        for kind,(title,_,hint) in GAMES.items():
            button=action(title+'  ▶',lambda checked=False,kind=kind:self.launch(kind),primary=True);button.setToolTip(hint);layout.addWidget(button)
        self.note=QLabel('로그인 없이 즐기는 자체 제작 미니게임 · 외부 서버·광고·결제 없음');self.note.setWordWrap(True);layout.addWidget(self.note)
        self.grid=DataGrid(['일시','게임','별명','점수','결과']);layout.addWidget(self.grid,1)
        tools=QHBoxLayout();tools.addWidget(action('점수·최고기록 새로고침',self.refresh));tools.addWidget(action('이 창 닫기',self.close));layout.addLayout(tools);self.refresh()
    def refresh(self):
        try:
            rows=self.book.rows();self.grid.fill([[row['date'][:19].replace('T',' '),GAMES[row['game']][0],row['name'],row['score'],row['result']] for row in rows])
            highs=' · '.join(f'{title} 최고 {max((row["score"] for row in rows if row["game"]==kind),default=0):,}' for kind,(title,_,_) in GAMES.items());self.note.setText(highs+'\n최근 200회 + 게임별 최고기록 보존 · 이 Windows 사용자 PC에만 저장 · 별명은 점수표에 표시됩니다.')
        except (ValueError,OSError) as exc:self.note.setText(str(exc))
    def roms(self):
        from .rom_library_ui import RomLibraryDialog
        self.rom_dialog=RomLibraryDialog(self);self.rom_dialog.setWindowModality(Qt.WindowModality.NonModal);self.rom_dialog.show();return self.rom_dialog
    def launch(self,kind):
        from shiboken6 import isValid
        existing=self.games.get(kind)
        if existing is not None and isValid(existing):
            if not existing.isVisible():existing.player=self.name.text().strip() or '플레이어';existing.restart()
            existing.showNormal();existing.raise_();existing.activateWindow();existing.surface.setFocus();return existing
        game=ArcadeGameDialog(kind,self.book,self.name.text().strip() or '플레이어');self.games[kind]=game
        app=QApplication.instance()
        if not hasattr(app,'_sy_arcade_windows'):app._sy_arcade_windows=[]
        app._sy_arcade_windows.append(game);game.finished.connect(lambda *_:self.refresh());game.show();game.surface.setFocus();return game


def open_arcade():
    from shiboken6 import isValid
    app=QApplication.instance();lobby=getattr(app,'_sy_arcade_lobby',None)
    if lobby is None or not isValid(lobby):app._sy_arcade_lobby=lobby=ArcadeLobby()
    lobby.showNormal();lobby.raise_();lobby.activateWindow();lobby.refresh();return lobby
