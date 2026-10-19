"""Private popup for diet, treatment, appointments and pharmacy purchases."""
from datetime import date
import time
from PySide6.QtCore import QEvent,QTimer,QTime
from PySide6.QtWidgets import QApplication,QDialog,QHBoxLayout,QLabel,QComboBox,QCheckBox,QTextEdit,QTimeEdit,QVBoxLayout,QMessageBox,QLineEdit
from .widgets import DataGrid,FormDialog,action,date_field,won
from .health import HEALTH_TYPES
from .personal_themes import apply_theme


def scrub_health(dialog):
    """An idle parent must not leave a child health editor visible or cached."""
    for child in reversed(dialog.findChildren(QDialog)):
        if isinstance(child,HealthDialog) or child.property('private_health'):
            if hasattr(child,'wipe'):child.wipe()
            for control in child.findChildren(QTextEdit)+child.findChildren(QLineEdit):control.clear()
            if isinstance(child,HealthDialog):child.grid.fill([]);child.timer.stop()
            guard=getattr(child,'_navigation_guard',None)
            if guard:guard.snapshots.pop(child,None)
            QDialog.reject(child)


class HealthDialog(QDialog):
    def __init__(self,store,kind,key,parent):
        super().__init__(parent);self.store,self.kind,self.key=store,kind,key;self.resize(1060,680);self.setWindowTitle('나의 건강·병원 기록')
        self.setProperty('private_health',True);self.body=QVBoxLayout(self)
        title=QLabel('건강한 하루를 위한 작은 기록');title.setStyleSheet('font-size:22px;font-weight:600;');self.body.addWidget(title)
        tools=QHBoxLayout();self.start=date_field(date.today().replace(day=1));self.end=date_field();self.category=QComboBox();self.category.addItem('전체 기록','')
        for key,label in HEALTH_TYPES.items():self.category.addItem(label,key)
        for widget in (self.start,QLabel('~'),self.end,self.category):tools.addWidget(widget)
        tools.addWidget(action('조회',self.refresh));self.body.addLayout(tools)
        self.subject=QComboBox();self.subject.addItem('가족 전체','');tools.insertWidget(4,self.subject);self.subject.currentIndexChanged.connect(self.refresh)
        self.grid=DataGrid(['날짜·시각','대상','종류','내용','병원·약국','키 cm','체중 kg','성장 나이','금액','알림','설명']);self.body.addWidget(self.grid,1)
        self.total=QLabel();self.body.addWidget(self.total)
        buttons=QHBoxLayout()
        for label,callback in [('기록 추가',self.add),('수정',self.edit),('삭제',self.delete),('주간·월간 리포트',self.report),('조용한 명상',self.meditation),('사진·문서 첨부',self.attach),('닫기',self.reject)]:buttons.addWidget(action(label,callback))
        self.body.addLayout(buttons)
        note=QLabel('진료·약국 금액은 별도 참고 기록이며 가계부 잔액이나 매장 장부에 자동 합산하지 않습니다.\n예약 알림의 날짜·시각과 “개인 일정” 제목만 첫화면에 저장하며 병명·병원·설명은 표시하지 않습니다. 의료 판단을 제공하지 않습니다.');note.setWordWrap(True);self.body.addWidget(note)
        self.grid.cellDoubleClicked.connect(lambda *_:self.edit());apply_theme(self,store.personal_theme(kind));self.refresh()
        self.last_activity=time.monotonic();self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.check_idle);self.timer.start();QApplication.instance().installEventFilter(self)
        QTimer.singleShot(500,self.alerts)
    def refresh(self):
        rows=self.store.health_entries(self.kind,self.key,self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'),self.category.currentData())
        selected=self.subject.currentData();self.subject.blockSignals(True);self.subject.clear();self.subject.addItem('가족 전체','')
        for person in sorted({r.get('subject','나') for r in rows}):self.subject.addItem(person,person)
        self.subject.setCurrentIndex(max(0,self.subject.findData(selected)));self.subject.blockSignals(False)
        if self.subject.currentData():rows=[r for r in rows if r.get('subject','나')==self.subject.currentData()]
        self.grid.fill([[r['date']+' '+r['time'],r.get('subject','나'),HEALTH_TYPES[r['category']],r['title'],r['place'],r.get('height',''),r['weight'],growth_age(r.get('birth_date',''),r['date']),r['amount'],'예약' if r['alarm'] else '',r['notes']] for r in rows],rows)
        self.total.setText('선택 기간 기록 금액 합계 '+won(sum(r['amount'] for r in rows))+'원')
    def editor(self,record=None,initial=None):
        record=record or {};identifier=record.get('id');record=dict(initial or {},**record);dialog=FormDialog('건강·병원 기록',self);dialog.resize(720,730);dialog.setProperty('private_health',True)
        category=dialog.combo('category','기록 종류',[(v,k) for k,v in HEALTH_TYPES.items()],record.get('category','health'))
        subject=dialog.field('subject','대상 (나·아이 이름 등)',record.get('subject','나'))
        born=date_field(record.get('birth_date'));has_birth=QCheckBox('생년월일 입력 · 성장 나이 표시');has_birth.setChecked(bool(record.get('birth_date')));dialog.form.addRow(has_birth);dialog.form.addRow('생년월일',born);born.setEnabled(has_birth.isChecked());has_birth.toggled.connect(born.setEnabled)
        when=date_field(record.get('date'));clock=QTimeEdit(QTime.fromString(record.get('time','09:00'),'HH:mm'));clock.setDisplayFormat('HH:mm');dialog.form.addRow('날짜',when);dialog.form.addRow('시각',clock)
        title=dialog.field('title','내용 *',record.get('title',''));place=dialog.field('place','병원·약국',record.get('place',''));weight=dialog.field('weight','체중 kg (선택)',record.get('weight',''));amount=dialog.field('amount','진료·구매 금액 (원)',record.get('amount','0.00'))
        height=dialog.field('height','키 cm (선택)',record.get('height',''))
        alarm=QCheckBox('병원 예약 알림');alarm.setChecked(record.get('alarm',False));dialog.form.addRow(alarm)
        from .health_tracking import TRACKING_FIELDS,MEAL_SLOTS
        tracking={name:dialog.field(name,label,record.get(name,'')) for name,(label,maximum,categories) in TRACKING_FIELDS.items()}
        slot=dialog.combo('meal_slot','식사 구분',[(v,k) for k,v in MEAL_SLOTS.items()],record.get('meal_slot','breakfast'))
        extra={name:dialog.field(name,label,','.join(str(v) for v in record.get(name,[])) if name in {'routine_days','supplement_days','supplement_times'} else record.get(name,'')) for name,label in [
            ('food_items','식단·음식·양'),('exercise_type','운동·요가 종류'),('routine_days','루틴 요일 (월,수,금 또는 1,3,5)'),('goal_date','목표일 (YYYY-MM-DD, 선택)'),
            ('sleep_start','잠든 시각 HH:MM · 기록일 기준'),('sleep_end','깬 시각 HH:MM · 빠르면 다음 날로 계산'),
            ('supplement_dose','제품·의료진 안내에 따른 복용 메모'),('supplement_times','알림 시각 (09:00,18:30)'),('supplement_days','알림 요일 (1=월 ~ 7=일)'),('supplement_end','알림 종료일 (YYYY-MM-DD, 선택)')]}
        if not record.get('supplement_times'):extra['supplement_times'].setText('09:00')
        if not record.get('supplement_days'):extra['supplement_days'].setText('1,2,3,4,5,6,7')
        notes=QTextEdit(record.get('notes',''));notes.setPlaceholderText('식사·운동, 치료 내용, 약 구매 내역 등');dialog.body.addWidget(notes,1)
        def mode():
            current=category.currentData();enabled=current in {'appointment','supplement'};alarm.setEnabled(enabled);alarm.setText('프로그램 내 복용 확인 알림' if current=='supplement' else '병원 예약 알림')
            if not enabled:alarm.setChecked(False)
            for name,widget in tracking.items():dialog.form.setRowVisible(widget,current in TRACKING_FIELDS[name][2])
            dialog.form.setRowVisible(slot,current in {'meal','diet_plan'})
            groups={'food_items':{'meal','diet_plan'},'exercise_type':{'exercise','routine'},'routine_days':{'routine'},'goal_date':{'goal'},'sleep_start':{'sleep'},'sleep_end':{'sleep'},'supplement_dose':{'supplement','supplement_taken'},'supplement_times':{'supplement'},'supplement_days':{'supplement'},'supplement_end':{'supplement'}}
            for name,widget in extra.items():dialog.form.setRowVisible(widget,current in groups[name])
        category.currentIndexChanged.connect(mode);mode()
        def save():
            try:
                data={'category':category.currentData(),'date':when.date().toString('yyyy-MM-dd'),'time':clock.time().toString('HH:mm'),'title':title.text(),'place':place.text(),'weight':weight.text(),'height':height.text(),'subject':subject.text(),'birth_date':born.date().toString('yyyy-MM-dd') if has_birth.isChecked() else '','amount':amount.text(),'notes':notes.toPlainText(),'alarm':alarm.isChecked(),'meal_slot':slot.currentData()}
                data.update({name:control.text() for name,control in {**tracking,**extra}.items()})
                self.store.save_health_entry(self.kind,self.key,data,identifier);dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.scroll_form();dialog.finish(save);apply_theme(dialog,self.store.personal_theme(self.kind))
        if dialog.exec():self.refresh()
        for control in dialog.findChildren(QTextEdit)+dialog.findChildren(QLineEdit):control.clear()
        guard=getattr(dialog,'_navigation_guard',None)
        if guard:guard.snapshots.pop(dialog,None)
        dialog.deleteLater()
    def add(self):self.editor()
    def report(self):
        from .health_report_ui import HealthReportDialog
        dialog=HealthReportDialog(self.store,self.kind,self.key,self)
        try:dialog.exec()
        finally:dialog.wipe();dialog.deleteLater()
    def meditation(self):
        from .health_report_ui import MeditationDialog
        dialog=MeditationDialog(self)
        try:
            if dialog.exec():self.editor(initial=dict(category='meditation',title='조용한 명상',duration_minutes=dialog.recorded_minutes))
        finally:dialog.timer.stop();dialog.deleteLater()
    def attach(self):
        record=self.grid.selected()
        if not record:QMessageBox.information(self,'건강 기록 선택','먼저 기록을 저장하고 선택하세요.');return
        from .attachment_ui import attachments
        attachments(self.store,self.key,self.kind,'health',record['id'],self)
    def alerts(self):
        from .health_report_ui import show_health_alerts
        show_health_alerts(self.store,self.kind,self.key,self)
    def edit(self):
        row=self.grid.selected()
        if row:self.editor(row)
    def delete(self):
        row=self.grid.selected()
        if row and QMessageBox.question(self,'기록 삭제','선택한 건강 기록과 연결된 예약 알림을 삭제할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.store.delete_health_entry(self.kind,self.key,row['id']);self.refresh()
    def eventFilter(self,watched,event):
        if event.type() in {QEvent.Type.KeyPress,QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,QEvent.Type.Wheel} and (watched is self or isinstance(watched,QDialog) and self.isAncestorOf(watched) or hasattr(watched,'parentWidget') and self.isAncestorOf(watched)):self.last_activity=time.monotonic()
        return False
    def check_idle(self):
        self.alerts()
        if time.monotonic()-self.last_activity>=300:self.reject()
    def reject(self):
        from .attachment_ui import scrub_attachments
        scrub_attachments(self)
        scrub_health(self);self.grid.fill([]);self.total.clear();self.timer.stop();QApplication.instance().removeEventFilter(self);QDialog.reject(self)


def growth_age(born,on):
    if not born:return ''
    first,last=date.fromisoformat(born),date.fromisoformat(on)
    months=(last.year-first.year)*12+last.month-first.month-(last.day<first.day)
    return f'{months//12}세 {months%12}개월 · {(last-first).days+1:,}일째'
