"""Private weekly/monthly reports and an optional quiet meditation timer."""
from datetime import date,timedelta
from decimal import Decimal
import time
from PySide6.QtCore import Qt,QTimer,QPointF
from PySide6.QtGui import QColor,QPainter,QPen
from PySide6.QtWidgets import (QApplication,QComboBox,QDialog,QHBoxLayout,QLabel,QMessageBox,
    QSpinBox,QTabWidget,QVBoxLayout,QWidget)
from .widgets import DataGrid,action,date_field
from .health_tracking import MEAL_SLOTS


class WeightTrend(QWidget):
    def __init__(self,parent=None):super().__init__(parent);self.points=[];self.setMinimumHeight(180)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.fillRect(self.rect(),QColor('#FFFCF7'));p.setPen(QColor('#456A5C'))
        p.drawText(12,22,'체중 변화 · 한 사람을 선택하면 표시합니다')
        if not self.points:p.drawText(16,70,'선택 기간의 체중 기록이 없습니다.');return
        points=self.points[-40:];weights=[float(r['weight']) for r in points];low=min(weights)-.5;span=max(weights)-low+.5
        coordinates=[]
        for index,record in enumerate(points):
            x=55+(self.width()-110)*index/max(1,len(points)-1);y=45+(self.height()-85)*(1-(float(record['weight'])-low)/span);coordinates.append(QPointF(x,y))
        p.setPen(QPen(QColor('#789E8A'),2))
        for start,end in zip(coordinates,coordinates[1:]):p.drawLine(start,end)
        for point in coordinates:p.setBrush(QColor('#789E8A'));p.drawEllipse(point,3,3)
        p.setPen(QColor('#456A5C'));p.drawText(10,45,f'{max(weights):.2f}kg');p.drawText(10,self.height()-30,f'{min(weights):.2f}kg')
        p.drawText(55,self.height()-8,points[0]['date']);p.drawText(max(55,self.width()-110),self.height()-8,points[-1]['date'])


class HealthReportDialog(QDialog):
    def __init__(self,store,kind,key,parent=None):
        super().__init__(parent);self.store,self.kind,self.key=store,kind,key;self.setProperty('private_health',True);self.setWindowTitle('주간·월간 건강 리포트 · 직접 입력 기준');self.resize(1050,760)
        body=QVBoxLayout(self);controls=QHBoxLayout();self.period=QComboBox();self.period.addItems(['최근 7일','이번 달','직접 기간'])
        self.start,self.end=date_field(date.today()-timedelta(days=6)),date_field();self.subject=QComboBox();self.subject.addItem('가족 전체','')
        for widget in (self.period,self.start,QLabel('~'),self.end,self.subject):controls.addWidget(widget)
        controls.addWidget(action('조회',self.refresh));body.addLayout(controls)
        self.summary=QLabel();self.summary.setWordWrap(True);body.addWidget(self.summary)
        self.tabs=QTabWidget();body.addWidget(self.tabs,1)
        self.daily=self.grid('일별 합계',['날짜','섭취 kcal','단백질 g','탄수화물 g','지방 g','당류 g','나트륨 mg','수분 ml','운동 분','수면 시간','명상 분'])
        self.people=self.grid('체중·목표',['대상','최근 측정일','최근 체중 kg','목표 kg','목표일','하루 수분 목표 ml','하루 참고 kcal'])
        self.trend=WeightTrend();self.tabs.addTab(self.trend,'체중 그래프')
        self.plans=self.grid('식단 계획표',['날짜','대상','끼니','식단·내용','계획 kcal','단백질 g','탄수화물 g','지방 g'])
        self.routines=self.grid('운동·요가 루틴',['대상','이름','운동 종류','요일','계획 분','세트','횟수','설명'])
        self.metrics=self.grid('건강·수면·마음',['날짜','대상','종류','내용','혈압','맥박','혈당','수면 시간','스트레스 0~10','허리 cm','설명'])
        note=QLabel('직접 기록한 수치만 합산합니다. 식단 계획·루틴은 실제 섭취·운동 합계에서 제외합니다. 기록하지 않은 날은 합계에 더하지 않습니다.\n칼로리·영양소·소모량은 음식·기기 자료를 직접 확인해 입력하세요. 목표는 사용자가 정한 참고값이며 의료·영양 처방이나 진단이 아닙니다.');note.setWordWrap(True);body.addWidget(note);body.addWidget(action('닫기',self.reject))
        self.period.currentIndexChanged.connect(self.period_changed);self.subject.currentIndexChanged.connect(self.refresh);self.refresh()
    def grid(self,title,headers):
        grid=DataGrid(headers);self.tabs.addTab(grid,title);return grid
    def period_changed(self,index):
        if index<2:self.start.setDate(date.today()-timedelta(days=6) if index==0 else date.today().replace(day=1));self.end.setDate(date.today())
        self.refresh()
    def refresh(self,*_):
        start,end=self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd')
        try:
            data=self.store.health_report(self.kind,self.key,start,end,self.subject.currentData() or '')
            selected=self.subject.currentData();self.subject.blockSignals(True);self.subject.clear();self.subject.addItem('가족 전체','')
            history=self.store.health_entries(self.kind,self.key,'1900-01-01',end)
            for person in sorted({r['subject'] for r in history}):self.subject.addItem(person,person)
            self.subject.setCurrentIndex(max(0,self.subject.findData(selected)));self.subject.blockSignals(False)
            totals=data['totals'];self.summary.setText(f"선택 {data['day_count']}일 · 섭취 {totals['calories']:,.2f} kcal · 단백질 {totals['protein_g']:,.2f}g · 탄수화물 {totals['carbs_g']:,.2f}g · 지방 {totals['fat_g']:,.2f}g\n수분 {totals['water_ml']:,.0f}ml · 운동 {totals['duration_minutes']:,.1f}분 · 수면 {totals['sleep_hours']:,.2f}시간 · 명상 {totals['meditation_minutes']:,.1f}분")
            self.daily.fill([[r['date'],*(r[k] for k in ('calories','protein_g','carbs_g','fat_g','sugar_g','sodium_mg','water_ml','duration_minutes','sleep_hours','meditation_minutes'))] for r in data['daily']])
            self.people.fill([[r[k] for k in ('subject','date','weight','target_weight','goal_date','target_water_ml','target_calories')] for r in data['people']])
            subjects={r['subject'] for r in data['weights']};self.trend.points=data['weights'] if len(subjects)<=1 else [];self.trend.update()
            self.plans.fill([[r['date'],r['subject'],MEAL_SLOTS.get(r.get('meal_slot'),''),r.get('food_items') or r['title'],*(r.get(k,'') for k in ('calories','protein_g','carbs_g','fat_g'))] for r in data['plans']])
            self.routines.fill([[r['subject'],r['title'],r.get('exercise_type',''),','.join('월화수목금토일'[v-1] for v in r.get('routine_days',[])),r.get('duration_minutes',''),r.get('sets',''),r.get('reps',''),r['notes']] for r in data['routines']])
            from .health import HEALTH_TYPES
            self.metrics.fill([[r['date'],r['subject'],HEALTH_TYPES[r['category']],r['title'],r.get('systolic','')+('/'+r['diastolic'] if r.get('diastolic') else ''),r.get('pulse',''),r.get('glucose',''),r.get('sleep_hours',''),r.get('stress_level',''),r.get('waist_cm',''),r['notes']] for r in data['metrics']])
        except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'건강 리포트',str(exc))
    def wipe(self):
        for grid in self.findChildren(DataGrid):grid.fill([])
        self.summary.clear();self.subject.blockSignals(True);self.subject.clear();self.subject.blockSignals(False);self.trend.points=[];self.trend.update()
    def reject(self):self.wipe();super().reject()


class MeditationDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setProperty('private_health',True);self.setWindowTitle('잠시 쉬어 가는 조용한 명상');self.resize(470,360)
        body=QVBoxLayout(self);note=QLabel('편안한 자세로 자연스럽게 호흡해 보세요.\n호흡을 억지로 참거나 조절하지 않아도 됩니다.\n불편하면 언제든 중단하세요.');note.setWordWrap(True);body.addWidget(note)
        self.minutes=QSpinBox();self.minutes.setRange(1,60);self.minutes.setValue(5);self.minutes.setSuffix('분');body.addWidget(self.minutes)
        self.clock=QLabel('준비되면 시작하세요');self.clock.setStyleSheet('font-size:28px;');body.addWidget(self.clock)
        self.elapsed=0.0;self.anchor=None;self.recorded_minutes='0';row=QHBoxLayout();row.addWidget(action('시작·일시정지',self.toggle));row.addWidget(action('종료 후 기록하기',self.record));row.addWidget(action('닫기',self.reject));body.addLayout(row)
        self.timer=QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.tick)
    def toggle(self):
        if self.anchor is not None:self.elapsed+=time.monotonic()-self.anchor;self.anchor=None;self.timer.stop()
        else:self.minutes.setEnabled(False);self.anchor=time.monotonic();self.timer.start()
        self.tick()
    def tick(self):
        elapsed=self.elapsed+(time.monotonic()-self.anchor if self.anchor is not None else 0);left=max(0,int(self.minutes.value()*60-elapsed));self.clock.setText(f'{left//60:02}:{left%60:02}')
        if left==0 and self.anchor is not None:self.elapsed=elapsed;self.anchor=None;self.timer.stop();QMessageBox.information(self,'명상 마침','잠시 쉬어 가는 시간을 마쳤습니다. 원하면 기록으로 남겨 보세요.')
    def record(self):
        elapsed=self.elapsed+(time.monotonic()-self.anchor if self.anchor is not None else 0)
        if elapsed<1:QMessageBox.information(self,'명상 기록','시작한 뒤 기록할 수 있습니다.');return
        self.recorded_minutes=str((Decimal(str(elapsed))/60).quantize(Decimal('0.001')));self.timer.stop();self.accept()
    def reject(self):self.timer.stop();super().reject()


def show_health_alerts(store,kind,key,parent):
    if not parent.isVisible() or QApplication.activeModalWidget() is not parent:return
    previous=getattr(parent,'_last_health_alert',0)
    if time.monotonic()-previous<60:return
    parent._last_health_alert=time.monotonic()
    try:rows=store.due_health_alerts(kind,key)
    except (ValueError,PermissionError):return
    if rows:
        message='\n'.join(r['time']+' · '+r['title']+' · '+r['dose'] for r in rows)
        QMessageBox.information(parent,'비타민·영양제 복용 확인',message+'\n\n실제 복용 여부를 확인하고 중복 복용하지 마세요. 의약품·영양제의 복용량과 주의사항은 의료진·제품 안내를 따르세요. 지난 날짜의 복용을 권하지 않습니다.')
