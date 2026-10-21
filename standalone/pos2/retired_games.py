"""Remove only verified, formerly registered ROM copies; never source files."""
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
from PySide6.QtCore import QStandardPaths,QThread,QTimer
from PySide6.QtWidgets import QDialog,QLabel,QMessageBox,QProgressBar,QVBoxLayout


def library_root():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'approved-games'


def _plain(path):
    if path.is_symlink() or getattr(path,'is_junction',lambda:False)():
        raise ValueError('게임 보관 경로의 링크·연결 폴더는 삭제하지 않습니다.')


def registered_copies(root=None):
    root=Path(root) if root is not None else library_root()
    if not root.is_absolute() or root.name!='approved-games':raise ValueError('전용 게임 보관 폴더만 정리할 수 있습니다.')
    _plain(root)
    if not root.exists():return []
    manifest=root/'library.json';_plain(manifest)
    if not manifest.exists():return []
    if not manifest.is_file() or manifest.stat().st_size>5_000_000:raise ValueError('게임 등록 목록을 안전하게 읽을 수 없습니다.')
    try:
        data=json.loads(manifest.read_text(encoding='utf-8'));games=data['games']
        if not isinstance(games,dict) or len(games)>100:raise ValueError()
        result=[];seen=set()
        for digest,row in games.items():
            if not re.fullmatch('[0-9a-f]{64}',digest) or not isinstance(row,dict):raise ValueError()
            name=row.get('filename');platform=row.get('platform')
            allowed={'nes':{'.nes'},'snes':{'.smc','.sfc'},'arcade':{'.zip'}}
            if not isinstance(name,str) or not name or any(c in name for c in '/\\:') or any(ord(c)<32 for c in name):raise ValueError()
            if platform not in allowed or Path(name).suffix.lower() not in allowed[platform]:raise ValueError()
            directory=root/'roms'/digest[:16];target=directory/name
            for part in (root/'roms',directory,target):_plain(part)
            if not target.exists():continue
            info=target.stat()
            if not stat.S_ISREG(info.st_mode) or not 16<=info.st_size<=128*1024*1024:raise ValueError()
            if target not in seen:result.append((target,digest));seen.add(target)
        return result
    except (ValueError,KeyError,TypeError,UnicodeError):
        raise ValueError('게임 등록 목록이 올바르지 않아 파일을 삭제하지 않았습니다.') from None


def delete_registered_copies(root=None):
    """Validate the entire target set before unlinking even one managed copy."""
    candidates=registered_copies(root);verified=[]
    for path,digest in candidates:
        before=path.stat();check=sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):check.update(block)
        if check.hexdigest()!=digest:raise ValueError('등록 당시와 달라진 게임 파일이 있습니다. 어떤 파일도 삭제하지 않았습니다.')
        verified.append((path,before.st_ino,before.st_size,before.st_mtime_ns))
    deleted=[]
    try:
        for path,inode,size,mtime in verified:
            for part in (path.parents[2],path.parents[1],path.parent,path):_plain(part)
            current=path.stat()
            if (current.st_ino,current.st_size,current.st_mtime_ns)!=(inode,size,mtime):raise ValueError('확인 중 파일이 변경됐습니다.')
            path.unlink();deleted.append(path.name)
    except (OSError,ValueError) as exc:
        raise ValueError(f'사본 {len(deleted)}개 삭제 후 중단했습니다: {exc}') from exc
    # Keep library.json (including scores) and all external emulator/source paths.
    return deleted


class _CleanupWorker(QThread):
    def __init__(self,root,parent):super().__init__(parent);self.root=root;self.deleted=[];self.error=''
    def run(self):
        try:self.deleted=delete_registered_copies(self.root)
        except (OSError,ValueError) as exc:self.error=str(exc)


class _CleanupProgress(QDialog):
    def __init__(self,root,parent):
        super().__init__(parent);self.setWindowTitle('등록 게임 파일 삭제');self.resize(460,130)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('등록 사본의 무결성을 확인한 뒤 삭제합니다. 원본과 점수는 보존합니다.'))
        bar=QProgressBar();bar.setRange(0,0);layout.addWidget(bar)
        self.worker=_CleanupWorker(root,self);self.worker.finished.connect(self.accept)
        QTimer.singleShot(0,self,self.worker.start)
    def reject(self):
        if self.worker.isFinished():super().reject()
    def closeEvent(self,event):
        if not self.worker.isFinished():event.ignore()
        else:super().closeEvent(event)


def offer_cleanup(parent,only_if_present=False):
    if only_if_present and not parent.isVisible():return
    root=library_root()
    try:rows=registered_copies(root)
    except (OSError,ValueError) as exc:QMessageBox.warning(parent,'게임 파일 정리 확인',str(exc));return
    if not rows:
        if not only_if_present:QMessageBox.information(parent,'등록 게임 파일 삭제','삭제할 등록 게임 사본이 없습니다.')
        return
    text=(f'미니 오락실은 제거되었으며 행운의 숫자 추첨만 유지합니다.\n\n'
          f'전용 보관 폴더에 복사 등록된 게임 {len(rows)}개를 삭제할까요?\n{root}\n\n'
          '원래 보관하던 ROM·외부 실행기·점수·업무자료는 삭제하지 않습니다.\n삭제된 사본은 프로그램에서 되돌릴 수 없습니다.')
    if QMessageBox.question(parent,'등록 게임 사본 삭제 확인',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
    dialog=_CleanupProgress(root,parent);dialog.exec()
    if dialog.worker.error:QMessageBox.warning(parent,'게임 파일 삭제 중단',dialog.worker.error)
    else:QMessageBox.information(parent,'게임 파일 삭제 완료',f'등록 사본 {len(dialog.worker.deleted)}개를 삭제했습니다. 원본·외부 실행기·점수는 보존했습니다.')
