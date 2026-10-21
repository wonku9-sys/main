"""Explicit attachment picker and confirmed plaintext export; never auto-open."""
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QDialog,QFileDialog,QHBoxLayout,QLabel,QMessageBox,QVBoxLayout
from .widgets import DataGrid,action
from .personal_attachments import ATTACHMENT_LIMIT


class AttachmentDialog(QDialog):
    def __init__(self,store,key,kind,record_type,identifier,parent=None):
        super().__init__(parent);self.store,self.key,self.kind,self.record_type,self.identifier=store,key,kind,record_type,identifier
        self.setWindowTitle('사진 · 영수증 · 문서 첨부');self.resize(740,480)
        body=QVBoxLayout(self);self.grid=DataGrid(['파일 이름','크기 (KB)','첨부 시각']);body.addWidget(self.grid,1)
        controls=QHBoxLayout()
        for label,fn in [('파일 첨부',self.add),('파일로 저장',self.export),('첨부 삭제',self.delete),('닫기',self.reject)]:controls.addWidget(action(label,fn))
        body.addLayout(controls)
        note=QLabel('사진·PDF·문서를 암호화하여 장부 안에 보관하고 백업에도 포함합니다. 파일당 10MB, 기록당 20개, 사용자당 200MB까지입니다.\n첨부 원본을 삭제하거나 이동해도 장부의 복사본은 유지됩니다. 가계부 암호 미사용 시 추가 암호 보호는 없습니다.\n자동으로 실행하지 않습니다. 파일로 꺼내면 암호화되지 않으며, 외부 문서는 안전을 확인한 뒤 여세요.');note.setWordWrap(True);body.addWidget(note);self.refresh()
    def refresh(self):
        rows=self.store.personal_attachments(self.key,self.kind,self.record_type,self.identifier)
        self.grid.fill([[r['name'],f"{r['size']/1024:.1f}",r['created_at']] for r in rows],rows)
    def add(self):
        path,_=QFileDialog.getOpenFileName(self,'첨부할 사진·문서 선택','','사진·문서 (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.pdf *.txt *.md *.csv *.xls *.xlsx *.doc *.docx *.hwp *.hwpx *.pptx)')
        if not path:return
        payload=None
        try:
            with open(path,'rb') as stream:payload=stream.read(ATTACHMENT_LIMIT+1)
            self.store.add_personal_attachment(self.key,self.kind,self.record_type,self.identifier,Path(path).name,payload);self.refresh()
        except (ValueError,PermissionError,OSError) as exc:QMessageBox.warning(self,'첨부 실패',str(exc))
        finally:payload=None
    def export(self):
        row=self.grid.selected()
        if not row:return
        if QMessageBox.question(self,'첨부파일 저장 주의','파일을 암호화하지 않은 상태로 꺼냅니다. 이 파일에는 가계부·일기장 암호가 적용되지 않습니다. 저장할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        path,_=QFileDialog.getSaveFileName(self,'첨부파일 저장',row['name'],'모든 파일 (*)')
        if not path:return
        temporary=None;payload=None
        try:
            payload=self.store.personal_attachment_data(self.key,self.kind,self.record_type,self.identifier,row['id'])
            target=Path(path)
            if target.is_symlink():raise ValueError('링크 파일에는 저장하지 않습니다. 다른 파일 이름을 선택하세요.')
            with tempfile.NamedTemporaryFile(dir=target.parent,prefix='attachment-',suffix='.part',delete=False) as stream:
                temporary=Path(stream.name);stream.write(payload)
            temporary.replace(target);QMessageBox.information(self,'첨부파일 저장','선택한 위치에 저장했습니다. 자동으로 실행하지는 않습니다.')
        except (ValueError,PermissionError,OSError) as exc:QMessageBox.warning(self,'저장 실패',str(exc))
        finally:
            payload=None
            if temporary and temporary.exists():temporary.unlink()
    def delete(self):
        row=self.grid.selected()
        if row and QMessageBox.question(self,'첨부 삭제','장부 안의 첨부파일 복사본을 삭제할까요? 원래 파일은 삭제하지 않습니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_personal_attachment(self.key,self.kind,self.record_type,self.identifier,row['id']);self.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'첨부 삭제',str(exc))
    def wipe(self):self.grid.fill([])
    def reject(self):self.wipe();super().reject()


def attachments(store,key,kind,record_type,identifier,parent):
    dialog=AttachmentDialog(store,key,kind,record_type,identifier,parent)
    try:dialog.exec()
    finally:dialog.wipe();dialog.deleteLater()


def scrub_attachments(parent):
    for dialog in parent.findChildren(AttachmentDialog):dialog.wipe();QDialog.reject(dialog)
