"""Private ROM library and explicit, user-chosen external emulator launching."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QFileDialog,QMessageBox
from .rom_library import RomLibrary
from .widgets import action,DataGrid,FormDialog


class RomLibraryDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.library=RomLibrary();self.setWindowTitle('내 게임 · 승인된 NES / SNES / 오락실 ROM');self.resize(1050,720)
        layout=QVBoxLayout(self)
        help=QLabel('① 보유 ROM 등록 → ② 기종별 실행기 EXE 선택 → ③ 게임 실행\n첨부된 게임 6종의 이름을 미리 표시합니다. ROM·실행기는 공개 배포 파일에 포함하지 않습니다. 원본 파일은 이동·변경하지 않고 이 Windows 사용자 게임 폴더에 복사합니다.');help.setWordWrap(True);layout.addWidget(help)
        tools=QHBoxLayout();tools.addWidget(action('ROM 여러 개 등록',self.register,primary=True))
        for title,kind in (('NES 실행기 선택','nes'),('SNES 실행기 선택','snes'),('오락실 MAME 선택','arcade')):tools.addWidget(action(title,lambda checked=False,kind=kind:self.emulator(kind)))
        layout.addLayout(tools);self.grid=DataGrid(['게임','기종','ROM 상태','실행 요청 횟수','수동 최고점수','최근 실행 요청']);layout.addWidget(self.grid,1)
        self.grid.setColumnWidth(0,300);self.grid.setColumnWidth(2,180)
        actions=QHBoxLayout();actions.addWidget(action('선택 게임 실행',self.play,primary=True));actions.addWidget(action('점수 직접 기록',self.score));actions.addWidget(action('새로고침',self.refresh));actions.addWidget(action('이 창 닫기',self.close));layout.addLayout(actions)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        links=QHBoxLayout();links.addWidget(action('NES 실행기 공식 안내',lambda:QDesktopServices.openUrl(QUrl('https://fceux.com/web/download.html'))));links.addWidget(action('SNES 실행기 공식 안내',lambda:QDesktopServices.openUrl(QUrl('https://www.snes9x.com/'))));links.addWidget(action('MAME 공식 안내',lambda:QDesktopServices.openUrl(QUrl('https://www.mamedev.org/release.html'))));layout.addLayout(links)
        warning=QLabel('실제 게임은 별도 실행기 창에서 열립니다. 실행기 설치·설정·ROM 버전·필요한 BIOS/부모 ROM에 따라 실행되지 않을 수 있습니다. 키 설정·저장 상태·원작 점수는 실행기에서 관리하며 SY POS는 점수를 자동 추출하지 않습니다. 승인된 파일만 등록하고 출처를 신뢰할 수 있는 실행기를 선택하세요.');warning.setWordWrap(True);layout.addWidget(warning);self.refresh()
    def refresh(self):
        try:
            rows=self.library.rows();self.grid.fill([[r['title'],{'nes':'NES','snes':'SNES','arcade':'오락실'}[r['platform']],'등록됨' if r['registered'] else '이 PC에서 등록 필요',r.get('plays',0),r.get('best',0),r.get('last_played','')] for r in rows],rows)
            config=self.library.load()['emulators'];self.status.setText('NES: '+config.get('nes','미설정')+'\nSNES: '+config.get('snes','미설정')+'\n오락실: '+config.get('arcade','미설정'))
        except (ValueError,OSError) as exc:self.status.setText(str(exc))
    def register(self):
        names,_=QFileDialog.getOpenFileNames(self,'보유 게임 파일 등록','','게임 ROM (*.nes *.smc *.sfc *.zip)')
        errors=[];count=0
        for name in names:
            try:self.library.register(name);count+=1
            except (ValueError,OSError) as exc:errors.append(str(exc))
        self.refresh();self.status.setText(f'{count}개 등록·확인 완료'+('\n'+'\n'.join(errors) if errors else ''))
    def emulator(self,kind):
        name,_=QFileDialog.getOpenFileName(self,'신뢰할 수 있는 실행기 EXE 선택','','Windows 실행 파일 (*.exe)')
        if not name:return
        if QMessageBox.question(self,'외부 프로그램 선택','이 파일을 게임 실행기로 사용할까요?\n'+name+'\n출처와 배포 라이선스를 확인하세요.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:self.library.set_emulator(kind,name);self.refresh()
        except (ValueError,OSError) as exc:self.status.setText(str(exc))
    def play(self):
        row=self.grid.selected()
        if not row:return
        try:
            program,args=self.library.command(row['digest'])
            if QMessageBox.question(self,'외부 게임 실행',row['title']+'\n선택한 실행기를 시작할까요?\n'+program,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            self.library.launch(row['digest']);self.refresh();self.status.setText('외부 실행기를 시작했습니다. 실제 게임 실행 결과는 실행기 창에서 확인하세요.')
        except (ValueError,OSError) as exc:self.status.setText(str(exc))
    def score(self):
        row=self.grid.selected()
        if not row or not row['registered']:self.status.setText('등록된 게임을 선택하세요.');return
        dialog=FormDialog('원작 게임 점수 수동 기록',self);name=dialog.field('name','별명','플레이어');score=dialog.field('score','점수 (정수)','0')
        def save():
            try:self.library.record_score(row['digest'],name.text(),int(score.text()));dialog.accept();self.refresh()
            except (ValueError,OSError) as exc:dialog.error(exc)
        dialog.finish(save);dialog.exec()
