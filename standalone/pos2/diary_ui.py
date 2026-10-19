"""Separated personal desk: encrypted diary and ordinary work records."""
from datetime import date
import time

from PySide6.QtCore import QEvent, QTimer, Qt, QDate
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QTextEdit, QVBoxLayout, QWidget,QCheckBox,QSlider

from .widgets import Page, FormDialog, DataGrid, action, date_field
from .navigation import mark_saved, confirm_dialog_exit, ask_unsaved


class DiaryPage(Page):
    def __init__(self,window):
        super().__init__(window,"나만의 보안 일기장","로그인 + 별도 일기장 암호 · 제목과 본문 AES-256-GCM 암호화 저장")
        panel=QWidget(); panel.setStyleSheet("background:#F5F0FA;border-radius:14px;")
        layout=QVBoxLayout(panel); layout.setContentsMargins(40,40,40,40)
        heading=QLabel("오늘의 마음을 담는 공간"); heading.setStyleSheet("font-size:25px;font-weight:700;color:#72558A;")
        layout.addWidget(heading)
        note=QLabel("업무와 잠시 떨어져 나만의 기록을 남겨보세요.\n\n이 일기장은 별도 암호를 입력해야 열립니다.\n백업에도 암호화된 내용만 저장되며, 관리자가 로그인 암호를 바꾸더라도 일기장 암호는 바뀌지 않습니다.\n\n이메일 복구를 미리 등록하면 인증번호와 최초 복구 메일의 복구키로 암호를 재설정할 수 있습니다. 기존 암호와 복구키를 모두 잃으면 내용 복구가 불가능합니다."); note.setWordWrap(True)
        layout.addWidget(note); layout.addWidget(action("암호 입력 · 일기장 열기",self.open_diary,primary=True))
        layout.addWidget(action("일기장 암호 변경",self.change_password))
        layout.addWidget(action("일기장 이메일 복구 등록",self.enable_email))
        layout.addWidget(action("일기장 암호 찾기 · 이메일 인증",self.reset_email))
        self.body.addWidget(panel); self.body.addStretch()

    def refresh(self):self.store.require_menu("diary")

    def enable_email(self):
        from .email_ui import EmailCodeDialog
        EmailCodeDialog(self.store,"diary_enable",self).exec()

    def reset_email(self):
        from .email_ui import EmailCodeDialog
        EmailCodeDialog(self.store,"diary_reset",self).exec()

    def open_diary(self):
        try: exists=self.store.diary_exists()
        except (ValueError,PermissionError) as exc:self.fail(exc);return
        dialog=FormDialog("일기장 잠금 해제" if exists else "처음 사용하는 일기장 · 암호 설정",self)
        password=dialog.field("password","일기장 암호 (8~128자)",password=True)
        confirm=dialog.field("confirm","암호 확인",password=True) if not exists else None
        notice=QLabel("로그인 암호와 다른 암호를 권장합니다.\n잊은 암호는 관리자도 복구할 수 없습니다."); notice.setWordWrap(True); dialog.body.addWidget(notice)
        holder={}
        def submit():
            try:
                if not exists:self.store.setup_diary(password.text(),confirm.text())
                holder["key"]=self.store.unlock_diary(password.text())
                password.clear()
                if confirm:confirm.clear()
                dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc);password.clear()
        dialog.finish(submit)
        if dialog.exec() and holder.get("key"):
            editor=DiaryDialog(self.store,holder.pop("key"),self)
            try:editor.exec()
            finally:editor.wipe();editor.deleteLater()
        password.clear()
        if confirm:confirm.clear()

    def change_password(self):
        dialog=FormDialog("일기장 암호 변경",self)
        old=dialog.field("old","현재 일기장 암호",password=True)
        new=dialog.field("new","새 일기장 암호 (8~128자)",password=True)
        confirm=dialog.field("confirm","새 암호 확인",password=True)
        def submit():
            try:self.store.change_diary_password(old.text(),new.text(),confirm.text());dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.finish(submit);dialog.exec()
        for field in dialog.fields.values():field.clear()
        self.store.lock_diary()


class DiaryDialog(FormDialog):
    def __init__(self,store,key,parent=None):
        super().__init__("나의 하루 · 보안 일기장",parent)
        self.store,self.key=store,key
        self.resize(1080,820);self.setMinimumSize(800,600)
        self.identifier=None;self.selecting=False;self.closed_securely=False
        self.title=self.field("title","제목")
        self.date=date_field();self.mood=QComboBox();self.mood.addItems(["평온","행복","고마움","설렘","지침","속상함","기타"])
        self.form.addRow("날짜",self.date);self.form.addRow("오늘의 마음",self.mood)
        from .calm_music import DiaryMusic
        self.music=DiaryMusic(store,self)
        music_row=QHBoxLayout();self.music_enabled=QCheckBox("잔잔한 음악");self.music_enabled.setChecked(self.music.preferences["enabled"])
        self.music_volume=QSlider(Qt.Orientation.Horizontal);self.music_volume.setRange(0,30);self.music_volume.setValue(self.music.preferences["volume"]);self.music_volume.setMaximumWidth(160)
        self.music_label=QLabel("일기장을 열면 낮은 음량으로 재생됩니다.");self.music_label.setWordWrap(True)
        music_row.addWidget(self.music_enabled);music_row.addWidget(QLabel("작게"));music_row.addWidget(self.music_volume);music_row.addWidget(self.music_label,1);self.body.addLayout(music_row)
        self.music.status.connect(self.music_label.setText)
        self.music_enabled.toggled.connect(self.configure_music);self.music_volume.sliderReleased.connect(self.configure_music)
        row=QHBoxLayout()
        self.entries=DataGrid(["날짜","제목","마음"]);self.entries.setMinimumWidth(300)
        self.entries.itemSelectionChanged.connect(self.select_entry)
        row.addWidget(self.entries,1)
        self.editor=QTextEdit();self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("오늘 어떤 하루를 보내셨나요?\n작은 순간과 마음을 천천히 적어보세요.")
        self.editor.setStyleSheet("QTextEdit {background:#FFFCF5;border:1px solid #E5D9E9;border-radius:10px;padding:18px;font-size:15px;}")
        row.addWidget(self.editor,2);self.body.addLayout(row,1)
        tools=QHBoxLayout();tools.addWidget(action("새 일기",self.new_entry));tools.addWidget(action("일기 삭제",self.delete_entry,danger=True))
        tools.addWidget(action('건강·병원 기록',self.health));tools.addStretch();tools.addWidget(QLabel("5분 미사용 시 암호화 저장 후 잠금 · 인쇄·엑셀 내보내기 없음"));self.body.addLayout(tools)
        self.finish(self.save)
        from .personal_themes import theme_picker
        self.theme=theme_picker(store,'diary',self);self.form.addRow('화면 분위기',self.theme)
        from .popup_sound import sound_checkbox
        self.popup_sound=sound_checkbox(store);self.form.addRow(self.popup_sound)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("잠그고 닫기")
        self.last_activity=time.monotonic()
        self.lock_timer=QTimer(self);self.lock_timer.setInterval(5000);self.lock_timer.timeout.connect(self.check_idle);self.lock_timer.start()
        QApplication.instance().installEventFilter(self)
        self.refresh_entries();self.saved_snapshot=self.snapshot()

    def snapshot(self):return self.identifier,self.title.text(),self.date.date().toString("yyyy-MM-dd"),self.mood.currentText(),self.editor.toPlainText()

    def health(self):
        from .health_ui import HealthDialog
        dialog=HealthDialog(self.store,'diary',self.key,self)
        try:dialog.exec()
        finally:dialog.reject();dialog.deleteLater()

    def showEvent(self,event):
        super().showEvent(event);self.music.start()
        from .popup_sound import play_popup
        play_popup(self.store,True)

    def configure_music(self,*_):
        try:self.music.configure(self.music_enabled.isChecked(),self.music_volume.value())
        except (ValueError,PermissionError) as exc:self.music.stop();self.music_label.setText(str(exc))

    def changed(self):return self.snapshot()!=self.saved_snapshot

    def confirm_change(self):
        if not self.changed():return True
        choice=ask_unsaved(self)
        if choice==QMessageBox.StandardButton.Cancel:return False
        if choice==QMessageBox.StandardButton.Save:return self.save()
        return choice==QMessageBox.StandardButton.Discard

    def refresh_entries(self):
        rows=self.store.diary_entries(self.key)
        self.selecting=True
        self.entries.fill([[r["date"],r["title"],r["mood"]] for r in rows],rows)
        self.selecting=False

    def select_entry(self):
        if self.selecting:return
        row=self.entries.selected()
        if row and self.confirm_change():
            self.identifier=row["id"];self.title.setText(row["title"])
            from PySide6.QtCore import QDate
            self.date.setDate(QDate.fromString(row["date"],"yyyy-MM-dd"));self.mood.setCurrentText(row["mood"]);self.editor.setPlainText(row["body"])
            self.saved_snapshot=self.snapshot();mark_saved(self)

    def new_entry(self):
        if not self.confirm_change():return
        self.identifier=None;self.title.clear();self.editor.clear();self.date.setDate(QDate.currentDate());self.mood.setCurrentIndex(0)
        self.saved_snapshot=self.snapshot();mark_saved(self)

    def save(self):
        try:
            self.identifier=self.store.save_diary_entry(self.key,{"date":self.date.date().toString("yyyy-MM-dd"),"title":self.title.text() or "제목 없음","body":self.editor.toPlainText(),"mood":self.mood.currentText()},self.identifier)
            self.saved_snapshot=self.snapshot();mark_saved(self);self.refresh_entries();return True
        except (ValueError,PermissionError) as exc:self.error(exc);return False

    def delete_entry(self):
        if self.identifier and QMessageBox.question(self,"일기 삭제","이 일기를 삭제할까요? 프로그램 안에서는 되돌릴 수 없습니다.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:
                self.store.delete_diary_entry(self.key,self.identifier)
                self.saved_snapshot=self.snapshot();self.new_entry();self.refresh_entries()
            except (ValueError,PermissionError) as exc:self.error(exc)

    def eventFilter(self,watched,event):
        if event.type() in {QEvent.Type.KeyPress,QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,QEvent.Type.Wheel} and isinstance(watched,QWidget) and (watched is self or self.isAncestorOf(watched)):
            self.last_activity=time.monotonic()
        return False

    def check_idle(self):
        if time.monotonic()-self.last_activity>=300:
            self.hide()
            if self.changed() and not self.save():QMessageBox.warning(self,"일기 자동 잠금","일기를 저장하지 못했습니다. 저장장치 상태를 확인하세요. 개인 정보 보호를 위해 창을 잠급니다.")
            self.wipe();QDialog.reject(self)

    def wipe(self):
        if self.closed_securely:return
        from .popup_sound import play_popup
        play_popup(self.store,False)
        self.closed_securely=True;self.lock_timer.stop();self.music.stop();QApplication.instance().removeEventFilter(self)
        from .health_ui import scrub_health
        scrub_health(self)
        self.key[:]=bytes(len(self.key));self.store.lock_diary()
        self.selecting=True;self.entries.fill([]);self.title.clear();self.editor.clear();self.saved_snapshot=None
        guard=getattr(self,"_navigation_guard",None)
        if guard:guard.snapshots.pop(self,None)

    def reject(self):
        if self.closed_securely:
            QDialog.reject(self);return
        guard=getattr(self,"_navigation_guard",None)
        if guard:
            if not confirm_dialog_exit(self):return
        elif not self.confirm_change():return
        self.wipe();QDialog.reject(self)


class WorkLogPage(Page):
    def __init__(self,window):
        super().__init__(window,"나의 업무일지","날짜별 업무와 인수인계 기록 · 이 계정의 기록만 표시됩니다. 별도 암호화하지 않으므로 개인 일기는 보안 일기장을 사용하세요.")
        self.menu_key="worklog"
        row=QHBoxLayout();self.start,self.end=date_field(date.today().replace(day=1)),date_field()
        from PySide6.QtWidgets import QLineEdit
        self.search=QLineEdit();self.search.setPlaceholderText("제목 · 업무 내용 검색")
        for control in (self.start,QLabel("~"),self.end,self.search):row.addWidget(control)
        for label,callback in (("조회",self.refresh),("새 업무일지",self.add),("수정",self.edit),("삭제",self.delete)):row.addWidget(action(label,callback))
        self.body.addLayout(row)
        self.grid=self.table(["날짜","제목","업무 내용","수정 일시"]);self.grid.cellDoubleClicked.connect(lambda *_:self.edit())

    def refresh(self):
        rows=self.store.work_logs(self.start.date().toString("yyyy-MM-dd"),self.end.date().toString("yyyy-MM-dd"),self.search.text())
        self.grid.fill([[r["date"],r["title"],r["body"],r["updated_at"]] for r in rows],rows)

    def editor(self,record=None):
        record=record or {}
        dialog=FormDialog("업무일지",self);dialog.resize(780,680)
        title=dialog.field("title","제목 *",record.get("title",""));date=date_field(record.get("date"));dialog.form.addRow("업무일",date)
        body=QTextEdit();body.setPlainText(record.get("body",""));body.setPlaceholderText("오늘 처리한 업무, 확인할 일, 인수인계 내용을 기록하세요.");dialog.body.addWidget(body,1)
        def save():
            try:self.store.save_work_log({"date":date.date().toString("yyyy-MM-dd"),"title":title.text(),"body":body.toPlainText()},record.get("id"));dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.finish(save)
        if dialog.exec():self.refresh()

    def add(self):self.editor()
    def edit(self):
        row=self.grid.selected()
        if row:self.editor(row)
    def delete(self):
        row=self.grid.selected()
        if row and QMessageBox.question(self,"업무일지 삭제","선택한 업무일지를 삭제할까요?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_work_log(row["id"]);self.refresh()
            except (ValueError,PermissionError) as exc:self.fail(exc)
