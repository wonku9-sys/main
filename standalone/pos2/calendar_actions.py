"""Date-aware right-click workflows for desktop and private popup calendars."""
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QMessageBox, QTableView
from .widgets import FormDialog, DataGrid, action


def calendar_date_at(calendar,point):
    view=calendar.findChild(QTableView,"qt_calendar_calendarview")
    if view is None:return QDate()
    index=view.indexAt(point)
    if not index.isValid() or index.row()==0:return QDate()
    if view.model().columnCount()==8 and index.column()==0:return QDate()
    try:day=int(index.data())
    except (ValueError,TypeError):return QDate()
    first=QDate(calendar.yearShown(),calendar.monthShown(),1)
    if index.row()==1 and day>=22:first=first.addMonths(-1)
    elif index.row()>=4 and day<=14:first=first.addMonths(1)
    return QDate(first.year(),first.month(),day)


def attach_calendar_menu(calendar,callback):
    view=calendar.findChild(QTableView,"qt_calendar_calendarview")
    if view is None:return
    viewport=view.viewport();viewport.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    def requested(point):
        selected=calendar_date_at(calendar,point)
        if selected.isValid():callback(selected,viewport.mapToGlobal(point))
    viewport.customContextMenuRequested.connect(requested)
    calendar.setToolTip("날짜 위에서 마우스 오른쪽 버튼: 기록·알림·조회·수정·삭제")


def edit_schedule(store,selected,parent=None,alarm=False,record=None):
    from .home_ui import ScheduleDialog
    dialog=ScheduleDialog(store,selected,record,parent)
    if record is None:dialog.alarm.setChecked(alarm)
    try:return bool(dialog.exec())
    finally:dialog.title.clear();dialog.notes.clear();dialog.deleteLater()


class DayScheduleDialog(FormDialog):
    def __init__(self,store,selected,parent=None,alarms_only=False):
        super().__init__(selected+" · "+("알림 조회·수정" if alarms_only else "기록 조회·수정"),parent)
        self.store,self.selected,self.alarms_only=store,selected,alarms_only;self.resize(880,600)
        self.grid=DataGrid(["시각","일정·메모","알림","완료","내용"]);self.body.addWidget(self.grid,1)
        row=QHBoxLayout()
        for title,callback in (("기록 추가",self.add),("알림 추가",self.add_alarm),("조회·수정",self.edit),("알림 켜기·끄기",self.toggle_alarm),("완료·해제",self.toggle_done),("삭제",self.delete),("문자 초안",self.draft)):
            row.addWidget(action(title,callback,danger=title=="삭제"))
        self.body.addLayout(row)
        note=QLabel("수정·삭제는 선택한 기록에 적용합니다. 반복 일정은 반복 전체에 적용됩니다.\n알림은 프로그램 실행 중 표시되며, 문자 초안은 복사 전용입니다. 일정은 별도 일기장/가계부 암호화 대상이 아닙니다.");note.setWordWrap(True);self.body.addWidget(note)
        self.body.addWidget(action("닫기",self.reject));self.grid.cellDoubleClicked.connect(lambda *_:self.edit());self.refresh()
    def refresh(self):
        try:records=self.store.desk_events(self.selected,self.selected)
        except (ValueError,PermissionError) as exc:self.error(exc);records=[]
        if self.alarms_only:records=[r for r in records if r['alarm']]
        self.grid.fill([[r['time'],r['title'],'켜짐' if r['alarm'] else '꺼짐','완료' if r['done'] else '진행',r['notes']] for r in records],records)
    def add(self):
        if edit_schedule(self.store,self.selected,self):self.refresh()
    def add_alarm(self):
        if edit_schedule(self.store,self.selected,self,alarm=True):self.refresh()
    def edit(self):
        row=self.grid.selected()
        if row and edit_schedule(self.store,self.selected,self,record=row):self.refresh()
    def toggle(self,key):
        row=self.grid.selected()
        if row:
            try:self.store.save_desk_event({key:not row[key]},row['id']);self.refresh()
            except (ValueError,PermissionError) as exc:self.error(exc)
    def toggle_alarm(self):self.toggle('alarm')
    def toggle_done(self):self.toggle('done')
    def delete(self):
        row=self.grid.selected()
        if row and QMessageBox.question(self,"기록 삭제","선택한 기록과 반복 알림을 삭제할까요?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_desk_event(row['id']);self.refresh()
            except (ValueError,PermissionError) as exc:self.error(exc)
    def draft(self):
        row=self.grid.selected()
        if row:
            from .personal_schedule_ui import open_message_draft
            open_message_draft(row,self)


def schedule_menu(store,selected,global_position,parent,refresh,extra=()):
    selected=selected.toString('yyyy-MM-dd') if isinstance(selected,QDate) else selected
    menu=QMenu(parent);header=menu.addAction(selected);header.setEnabled(False);menu.addSeparator()
    for label,callback in extra:menu.addAction(label,callback)
    if extra:menu.addSeparator()
    def add(alarm=False):
        if edit_schedule(store,selected,parent,alarm=alarm):refresh()
    def browse(alarms=False):
        dialog=DayScheduleDialog(store,selected,parent,alarms)
        try:dialog.exec();refresh()
        finally:dialog.grid.fill([]);dialog.deleteLater()
    menu.addAction("일정·메모 기록",lambda:add())
    menu.addAction("알림 설정",lambda:add(True))
    menu.addAction("기록 조회·수정·삭제",lambda:browse())
    menu.addAction("알림 조회·수정·해제",lambda:browse(True))
    menu.exec(global_position)
