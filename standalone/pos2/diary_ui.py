"""Separated personal desk: encrypted diary and ordinary work records."""
from datetime import date
import time

from PySide6.QtCore import QEvent, QTimer, Qt, QDate
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QTextEdit, QVBoxLayout, QWidget,QCheckBox,QSlider,QLineEdit,QCalendarWidget,QGridLayout,QMenu

from .widgets import Page, FormDialog, DataGrid, action, date_field
from .navigation import mark_saved, confirm_dialog_exit, ask_unsaved


class DiaryPage(Page):
    def __init__(self,window):
        super().__init__(window,"나의 일기장","내 마음과 하루를 기록하는 공간 · 첫 잠금 해제 후 같은 로그인 동안 다시 열기")
        panel=QWidget();panel.setObjectName('diaryEntryPanel')
        panel.setStyleSheet("QWidget#diaryEntryPanel {background:#F5F0FA;border-radius:14px;}")
        layout=QVBoxLayout(panel); layout.setContentsMargins(40,40,40,40)
        heading=QLabel("오늘의 마음을 담는 공간"); heading.setStyleSheet("font-size:25px;font-weight:700;color:#72558A;")
        from .personal_icons import personal_heading
        layout.addLayout(personal_heading(heading,'diary',52))
        layout.addWidget(QLabel("나의 일기장 · 열기 / 암호 변경 / 이메일 복구"))
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
        from .independent_windows import active_personal
        if active_personal(self,'diary'):return
        from .private_session import cached_key
        cached=cached_key(self.store,"diary")
        if cached is not None:
            self.show_diary(cached);return
        try: exists=self.store.diary_exists()
        except (ValueError,PermissionError) as exc:self.fail(exc);return
        dialog=FormDialog("일기장 잠금 해제" if exists else "처음 사용하는 일기장 · 암호 설정",self)
        guide=QLabel("나의 일기장\n개인 일기장 암호를 한 번 입력하면 같은 로그인 중에는 다시 묻지 않습니다." if exists else "나의 일기장\n처음 사용할 개인 일기장 암호를 설정해 주세요.");guide.setWordWrap(True);dialog.body.insertWidget(1,guide)
        password=dialog.field("password","일기장 암호 (8~128자)",password=True)
        confirm=dialog.field("confirm","암호 확인",password=True) if not exists else None
        notice=QLabel("로그인 암호와 다른 암호를 권장합니다.\n잊은 암호는 관리자도 복구할 수 없습니다."); notice.setWordWrap(True); dialog.body.addWidget(notice)
        if exists:dialog.body.addWidget(action('일기장 암호 찾기 · 이메일 인증',self.reset_email))
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
            self.show_diary(holder.pop("key"))
        password.clear()
        if confirm:confirm.clear()

    def show_diary(self,key):
        from .independent_windows import show_personal
        editor=DiaryDialog(self.store,key,self)
        show_personal(self,'diary',editor)

    def change_password(self):
        dialog=FormDialog("일기장 암호 변경",self)
        dialog.body.insertWidget(1,QLabel("나의 일기장 · 현재 암호를 확인한 뒤 새 개인 암호로 변경합니다."))
        old=dialog.field("old","현재 일기장 암호",password=True)
        new=dialog.field("new","새 일기장 암호 (8~128자)",password=True)
        confirm=dialog.field("confirm","새 암호 확인",password=True)
        def submit():
            try:self.store.change_diary_password(old.text(),new.text(),confirm.text());dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.finish(submit);changed=dialog.exec()==QDialog.DialogCode.Accepted
        for field in dialog.fields.values():field.clear()
        if changed:self.store.lock_diary()
        return changed


class DiaryDialog(FormDialog):
    def __init__(self,store,key,parent=None):
        if getattr(store,'is_shared_client',False):store=store.private
        super().__init__("나의 하루 · 보안 일기장",parent)
        from .personal_icons import personal_heading,personal_icon
        heading=self.findChild(QLabel,'dialogTitle');self.body.removeWidget(heading)
        self.body.insertLayout(0,personal_heading(heading,'diary'))
        self.setWindowIcon(personal_icon('diary'))
        self.store,self.key=store,key
        from .private_session import remember_key
        remember_key(store,"diary",key)
        self.resize(1080,820);self.setMinimumSize(800,600)
        self.identifier=None;self.selecting=False;self.closed_securely=False
        self.title=self.field("title","제목")
        self.date=date_field();self.mood=QComboBox();self.mood.addItems(["평온","행복","고마움","설렘","지침","속상함","기타"])
        self.form.addRow("날짜",self.date);self.form.addRow("오늘의 마음",self.mood)
        self.tags=QLineEdit();self.tags.setPlaceholderText('#가족 #여행 #감사');self.form.addRow('기록 태그',self.tags)
        self.bookmark=QCheckBox('소중한 일기로 표시');self.form.addRow(self.bookmark)
        self.stats=QLabel();self.stats.setWordWrap(True);self.body.addWidget(self.stats)
        searchrow=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('제목 · 본문 · 마음 · #태그 검색');self.only_bookmarked=QCheckBox('소중한 일기만');searchrow.addWidget(self.search,1);searchrow.addWidget(self.only_bookmarked);self.body.addLayout(searchrow)
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
        self.sidebar=QWidget();side=QVBoxLayout(self.sidebar);side.setContentsMargins(0,0,0,0)
        self.calendar=QCalendarWidget();self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader);self.calendar.setMaximumHeight(230);side.addWidget(self.calendar);side.addWidget(self.entries,1);row.addWidget(self.sidebar,1)
        self.editor=QTextEdit();self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("오늘 어떤 하루를 보내셨나요?\n작은 순간과 마음을 천천히 적어보세요.")
        self.editor.setStyleSheet("QTextEdit {background:#FFFCF5;border:1px solid #E5D9E9;border-radius:10px;padding:18px;font-size:15px;}")
        row.addWidget(self.editor,2);self.body.addLayout(row,1)
        writing=QHBoxLayout();self.templates=QComboBox();self.templates.addItems(['감사 일기','하루 돌아보기','건강한 하루','마음 정리']);writing.addWidget(self.templates);writing.addWidget(action('양식 넣기',self.insert_template));writing.addWidget(action('집중 모드',self.toggle_focus));self.word_count=QLabel();writing.addWidget(self.word_count,1);self.body.addLayout(writing)
        self.editor.textChanged.connect(self.update_word_count)
        tools=QHBoxLayout();tools.addWidget(action("새 일기",self.new_entry));tools.addWidget(action("일기 삭제",self.delete_entry,danger=True))
        tools.addWidget(action('건강·병원 기록',self.health));tools.addStretch();tools.addWidget(action("잠그고 닫기",self.lock_close));self.body.addLayout(tools)
        self.body.addWidget(QLabel("같은 로그인 중에는 다시 열 때 암호를 묻지 않습니다. 자리 비움 시 ‘잠그고 닫기’를 사용하세요."))
        tools.insertWidget(2,action('사진·문서 첨부',self.attach))
        tools.insertWidget(3,action('일기장 설정',self.security_settings))
        self.finish(self.save)
        from .personal_themes import theme_picker
        self.theme=theme_picker(store,'diary',self);self.form.addRow('화면 분위기',self.theme)
        from .popup_sound import sound_checkbox
        self.popup_sound=sound_checkbox(store);self.form.addRow(self.popup_sound)
        # Keep the page a writing space: short metadata in two compact rows.
        while self.form.rowCount():
            taken=self.form.takeRow(0)
            if taken.labelItem and taken.labelItem.widget():taken.labelItem.widget().deleteLater()
        self.body.removeItem(self.form)
        metadata=QGridLayout();metadata.setHorizontalSpacing(10);metadata.setVerticalSpacing(8)
        self.title.setPlaceholderText('오늘의 제목');self.date.setToolTip('일기 날짜 · 달력으로 선택');self.mood.setToolTip('오늘의 마음');self.theme.setToolTip('나만의 화면 분위기 선택')
        metadata.addWidget(self.title,0,0,1,3);metadata.addWidget(self.date,0,3);metadata.addWidget(self.mood,0,4)
        metadata.addWidget(self.tags,1,0,1,3);metadata.addWidget(self.bookmark,1,3);metadata.addWidget(self.theme,1,4)
        metadata.setColumnStretch(0,1);self.body.insertLayout(1,metadata);music_row.addWidget(self.popup_sound)
        self.editor.setMinimumHeight(220);self.entries.setMinimumHeight(125)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("닫기 · 로그인 중 잠금 해제 유지")
        self.last_activity=time.monotonic()
        self.lock_timer=QTimer(self);self.lock_timer.setInterval(5000);self.lock_timer.timeout.connect(self.check_idle);self.lock_timer.start()
        QApplication.instance().installEventFilter(self)
        self.refresh_entries();self.saved_snapshot=self.snapshot()
        self.search.textChanged.connect(lambda *_:self.refresh_entries());self.only_bookmarked.toggled.connect(lambda *_:self.refresh_entries());self.calendar.clicked.connect(self.calendar_day);self.update_word_count()

    def snapshot(self):return self.identifier,self.title.text(),self.date.date().toString("yyyy-MM-dd"),self.mood.currentText(),self.editor.toPlainText(),self.tags.text(),self.bookmark.isChecked()

    def security_settings(self):
        """Show settings only when requested, not beside every diary opening."""
        menu=QMenu(self)
        def change():
            if not self.confirm_change():return
            if DiaryPage.change_password(self):
                self._lock_on_close=True;self.wipe();QDialog.reject(self)
        for title,callback in [('일기장 암호 변경',change),('일기장 이메일 복구 등록',lambda:DiaryPage.enable_email(self)),('일기장 암호 찾기 · 이메일 인증',lambda:DiaryPage.reset_email(self))]:menu.addAction(title,callback)
        self._security_menu=menu;menu.popup(QCursor.pos())

    def insert_template(self):
        templates=['오늘 고마웠던 일 3가지\n1. \n2. \n3. \n\n내일 나에게 전하고 싶은 말\n',
                   '오늘의 작은 성취\n\n기억하고 싶은 순간\n\n아쉬웠던 일과 배운 점\n\n내일의 한 걸음\n',
                   '오늘의 몸과 마음\n\n식사·물·운동·잠\n\n나를 돌본 작은 실천\n',
                   '지금 느끼는 감정\n\n그 감정이 찾아온 이유\n\n내가 바꿀 수 있는 것\n\n나에게 해 주고 싶은 말\n']
        self.editor.moveCursor(self.editor.textCursor().MoveOperation.End);self.editor.insertPlainText(('\n\n' if self.editor.toPlainText() else '')+templates[self.templates.currentIndex()])
    def toggle_focus(self):self.sidebar.setVisible(self.sidebar.isHidden());self.editor.setFocus()
    def update_word_count(self):self.word_count.setText(f'{len(self.editor.toPlainText()):,}자 · 저장 버튼으로 암호화 저장')
    def calendar_day(self,day):
        rows=self.store.diary_entries(self.key);row=next((r for r in rows if r['date']==day.toString('yyyy-MM-dd')),None)
        if not self.confirm_change():return
        if row:self.load_entry(row)
        else:self.new_entry(confirmed=True);self.date.setDate(day)

    def attach(self):
        if self.changed() or not self.identifier:
            if QMessageBox.question(self,'일기 저장','일기를 저장한 뒤 파일을 첨부할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            if not self.save():return
        from .attachment_ui import attachments
        attachments(self.store,self.key,'diary','entry',self.identifier,self)

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
        if self.closed_securely:return
        rows=self.store.diary_entries(self.key)
        from PySide6.QtGui import QTextCharFormat,QColor
        for old in getattr(self,'_marked_dates',[]):self.calendar.setDateTextFormat(QDate.fromString(old,'yyyy-MM-dd'),QTextCharFormat())
        self._marked_dates=sorted({r['date'] for r in rows})
        for when in self._marked_dates:
            style=QTextCharFormat();style.setBackground(QColor('#E4D9EF'));style.setToolTip('일기가 있는 날');self.calendar.setDateTextFormat(QDate.fromString(when,'yyyy-MM-dd'),style)
        self.stats.setText(f"내 마음의 기록 {len(rows)}편 · 이번 달 {sum(r['date'][:7]==date.today().strftime('%Y-%m') for r in rows)}편 · 소중한 일기 {sum(bool(r.get('bookmark')) for r in rows)}편")
        query=self.search.text().strip().casefold().removeprefix('#')
        rows=[r for r in rows if (not self.only_bookmarked.isChecked() or r.get('bookmark')) and (not query or query in (r['title']+' '+r['body']+' '+r['mood']+' '+' '.join(r.get('tags',[]))).casefold())]
        self.selecting=True
        self.entries.fill([[r["date"],('★ ' if r.get('bookmark') else '')+r["title"],r["mood"]] for r in rows],rows)
        self.selecting=False

    def select_entry(self):
        if self.selecting:return
        row=self.entries.selected()
        if row and self.confirm_change():
            self.load_entry(row)
    def load_entry(self,row):
        self.identifier=row['id'];self.title.setText(row['title']);self.date.setDate(QDate.fromString(row['date'],'yyyy-MM-dd'));self.mood.setCurrentText(row['mood']);self.editor.setPlainText(row['body']);self.tags.setText(' '.join('#'+t for t in row.get('tags',[])));self.bookmark.setChecked(bool(row.get('bookmark')))
        self.saved_snapshot=self.snapshot();mark_saved(self)

    def new_entry(self,confirmed=False):
        if not confirmed and not self.confirm_change():return
        self.identifier=None;self.title.clear();self.editor.clear();self.tags.clear();self.bookmark.setChecked(False);self.date.setDate(QDate.currentDate());self.mood.setCurrentIndex(0)
        self.saved_snapshot=self.snapshot();mark_saved(self)

    def save(self):
        try:
            self.identifier=self.store.save_diary_entry(self.key,{"date":self.date.date().toString("yyyy-MM-dd"),"title":self.title.text() or "제목 없음","body":self.editor.toPlainText(),"mood":self.mood.currentText(),'tags':self.tags.text(),'bookmark':self.bookmark.isChecked()},self.identifier)
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
        if self.closed_securely:return
        try:self.store._diary_require_key(self.key)
        except (ValueError,PermissionError):
            self._lock_on_close=True;self.wipe();QDialog.reject(self);return
        if not self.closed_securely:
            from .health_report_ui import show_health_alerts
            show_health_alerts(self.store,'diary',self.key,self)
    def lock_close(self):
        self._lock_on_close=True
        try:self.reject()
        finally:self._lock_on_close=False

    def wipe(self):
        if self.closed_securely:return
        from .popup_sound import play_popup
        play_popup(self.store,False)
        self.closed_securely=True;self.lock_timer.stop();self.music.stop();QApplication.instance().removeEventFilter(self)
        from .health_ui import scrub_health
        scrub_health(self)
        from .attachment_ui import scrub_attachments
        scrub_attachments(self)
        self.key[:]=bytes(len(self.key))
        if getattr(self,"_lock_on_close",False):self.store.lock_diary()
        self.selecting=True;self.entries.fill([]);self.title.clear();self.editor.clear();self.tags.clear();self.search.clear();self.stats.clear();self.word_count.clear();self.saved_snapshot=None
        from PySide6.QtGui import QTextCharFormat
        for when in self._marked_dates:self.calendar.setDateTextFormat(QDate.fromString(when,'yyyy-MM-dd'),QTextCharFormat())
        self._marked_dates=[]
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


from .worklog_ui import WorkLogPage
