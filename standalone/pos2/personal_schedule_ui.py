"""Local anniversaries and explicit copy-only message drafts. No SMS delivery."""
from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (QApplication, QCalendarWidget, QDialog, QHBoxLayout,
    QLabel, QMessageBox, QTextEdit, QVBoxLayout)
from .widgets import DataGrid, FormDialog, action


def message_draft(record):
    return f"{record['date']} {record.get('time','09:00')}\n{record['title']}\n{record.get('counter','')}\n{record.get('notes','')}".strip()


def open_message_draft(record,parent=None):
    dialog=FormDialog('기념일 문자 초안 · 복사 전용',parent)
    body=QTextEdit(message_draft(record));dialog.body.addWidget(body)
    notice=QLabel('휴대폰으로 자동 발송하지 않으며 요금도 발생하지 않습니다.\n내용을 확인해 복사한 뒤 휴대폰의 문자 앱 등에 붙여넣어 직접 보내세요.\n복사한 내용은 PC 클립보드에 남으니 개인정보를 확인하세요.');notice.setWordWrap(True);dialog.body.addWidget(notice)
    def copy():QApplication.clipboard().setText(body.toPlainText());QMessageBox.information(dialog,'문자 초안','클립보드에 복사했습니다. 실제 문자는 발송하지 않았습니다.')
    dialog.body.addWidget(action('내용 복사',copy));dialog.finish(dialog.accept)
    dialog.buttons.button(dialog.buttons.StandardButton.Save).setText('닫기')
    dialog.exec();body.clear();dialog.deleteLater()


class PersonalScheduleDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.marked=[];self.setWindowTitle('📅 나의 달력 · 기념일 · 알림');self.resize(970,720)
        self.layout=QVBoxLayout(self);self.layout.addWidget(QLabel('생일·결혼기념일·제사 · 양력/음력 · 매년 반복 알림'))
        self.calendar=QCalendarWidget();self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader);self.layout.addWidget(self.calendar,1)
        self.grid=DataGrid(['날짜·시각','일정·기념일','경과일·주년','알림','내용']);self.layout.addWidget(self.grid,1)
        row=QHBoxLayout()
        for title,callback in [('일정·기념일 추가',self.add),('수정',self.edit),('삭제',self.delete),('문자 초안 · 복사',self.draft),('닫기',self.reject)]:row.addWidget(action(title,callback))
        self.layout.addLayout(row)
        note=QLabel('날짜를 선택해 추가하세요. 목록은 선택한 달의 일정입니다. 알림은 프로그램 실행 중 팝업으로 표시됩니다.\n종료 중 놓친 알림은 다음 실행 때 확인합니다. 문자 자동 발송은 하지 않습니다.\n일정은 첫화면과 함께 사용하며 별도 가계부 암호로 암호화되지 않으니 비밀 금융정보는 적지 마세요.');note.setWordWrap(True);self.layout.addWidget(note)
        self.calendar.currentPageChanged.connect(self.refresh);self.grid.cellDoubleClicked.connect(lambda *_:self.edit())
        self.timer=QTimer(self);self.timer.setInterval(15000);self.timer.timeout.connect(self.alerts);self.timer.start();self.refresh()
    def refresh(self,*_):
        first=QDate(self.calendar.yearShown(),self.calendar.monthShown(),1);last=QDate(first.year(),first.month(),first.daysInMonth())
        records=self.store.desk_events(first.toString('yyyy-MM-dd'),last.toString('yyyy-MM-dd'))
        self.grid.fill([[r['date']+' '+r['time'],r['title'],r.get('counter',''),'완료' if r['done'] else '알림' if r['alarm'] else '',r['notes']] for r in records],records)
        for value in self.marked:self.calendar.setDateTextFormat(value,QTextCharFormat())
        self.marked=[]
        for record in records:
            value=QDate.fromString(record['date'],'yyyy-MM-dd');style=QTextCharFormat();style.setBackground(QColor('#F5DFC0'));style.setFontWeight(700);self.calendar.setDateTextFormat(value,style);self.marked.append(value)
    def editor(self,record=None):
        from .home_ui import ScheduleDialog
        dialog=ScheduleDialog(self.store,self.calendar.selectedDate().toString('yyyy-MM-dd'),record,self)
        if dialog.exec():self.refresh()
        dialog.title.clear();dialog.notes.clear();dialog.deleteLater()
    def add(self):self.editor()
    def edit(self):
        record=self.grid.selected()
        if record:self.editor(record)
    def delete(self):
        record=self.grid.selected()
        if record and QMessageBox.question(self,'일정 삭제','선택한 일정과 매년 반복 알림을 삭제할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_desk_event(record['id']);self.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'일정 삭제',str(exc))
    def draft(self):
        record=self.grid.selected()
        if record:open_message_draft(record,self)
        else:QMessageBox.information(self,'일정 선택','문자 초안을 만들 일정을 먼저 선택하세요.')
    def alerts(self):
        if not self.isVisible() or QApplication.activeModalWidget() is not self:return
        try:
            records=self.store.due_desk_alerts()
            if records:
                from .alert_ui import ScheduleAlertDialog
                ScheduleAlertDialog(records,self).exec();self.refresh()
        except (ValueError,PermissionError) as exc:self.timer.stop();QMessageBox.warning(self,'알림 확인',str(exc))
    def reject(self):self.timer.stop();self.grid.fill([]);super().reject()
