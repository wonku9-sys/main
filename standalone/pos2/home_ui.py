"""Offline calendar, OS clock and private schedules on the first screen."""
import calendar
from datetime import date, timedelta, datetime, timezone
from hashlib import sha256
import time

from PySide6.QtCore import QDate, QDateTime, Qt, QTimer, QTime, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QTextEdit, QTimeEdit, QVBoxLayout, QWidget, QAbstractItemView,QSpinBox

from .widgets import Page, FormDialog, DataGrid, action, date_field, won
from .navigation import mark_saved
from .menu_help import MENU_HELP, attach_help
from .permissions import has_menu
from .online_info import CITIES, fetch_online


class OnlineSignals(QObject):
    finished = Signal(dict)


class OnlineWorker(QRunnable):
    def __init__(self,config):
        super().__init__(); self.config=config; self.signals=OnlineSignals()

    def run(self):
        try: result=fetch_online(self.config)
        except Exception: result={"weather_error":True,"clock_error":True}
        result["config"] = self.config
        self.signals.finished.emit(result)


class ScheduleDialog(FormDialog):
    def __init__(self,store,selected_date,record=None,parent=None):
        super().__init__("일정 · 메모",parent)
        self.store,self.record = store,record or {}
        self.resize(620,650)
        self.title = self.field("title","제목 *",self.record.get("title",""))
        self.date = date_field(self.record.get("source_date",self.record.get("date",selected_date)))
        self.time = QTimeEdit(QTime.fromString(self.record.get("time","09:00"),"HH:mm")); self.time.setDisplayFormat("HH:mm")
        self.form.addRow("날짜",self.date); self.form.addRow("시각",self.time)
        from .recurrence import KINDS
        self.kind=self.combo('event_kind','기억할 날짜',[(v,k) for k,v in KINDS.items()],self.record.get('event_kind','memo'))
        self.calendar_type=self.combo('calendar','달력 기준',[('양력','solar'),('음력 (한국)','lunar')],self.record.get('calendar','solar'))
        self.repeat=self.combo('repeat','반복',[('한 번만','once'),('해마다 반복','yearly')],self.record.get('repeat','once'))
        lunar_row=QHBoxLayout();self.lunar_fields=[]
        for name,label,minimum,maximum,default in (('base_year','년',1900,2050,self.date.date().year()),('month','월',1,12,self.date.date().month()),('day','일',1,30,self.date.date().day())):
            control=QSpinBox();control.setRange(minimum,maximum);control.setValue(self.record.get(name,default));self.lunar_fields.append(control);lunar_row.addWidget(control);lunar_row.addWidget(QLabel(label))
        self.form.addRow('음력 기준일',lunar_row)
        self.leap=QCheckBox('윤달');self.leap.setChecked(bool(self.record.get('leap')));lunar_row.addWidget(self.leap)
        self.fallback=QCheckBox('윤달이 없는 해에는 같은 평달로 알림');self.fallback.setChecked(bool(self.record.get('leap_fallback',True)));self.form.addRow(self.fallback)
        self.lead=QSpinBox();self.lead.setRange(0,365);self.lead.setSuffix('일 전');self.lead.setValue(self.record.get('lead_days',0));self.form.addRow('미리 알림',self.lead)
        def calendar_mode():
            lunar=self.calendar_type.currentData()=='lunar';self.date.setEnabled(not lunar)
            for control in self.lunar_fields+[self.leap,self.fallback]:control.setEnabled(lunar)
        self.calendar_type.currentIndexChanged.connect(calendar_mode);calendar_mode()
        self.alarm,self.done_box = QCheckBox("이 시각에 알림"),QCheckBox("완료")
        self.alarm.setChecked(bool(self.record.get("alarm"))); self.done_box.setChecked(bool(self.record.get("done")))
        self.form.addRow(self.alarm); self.form.addRow(self.done_box)
        self.notes = QTextEdit(self.record.get("notes","")); self.notes.setPlaceholderText("발주·결제 일정, 해야 할 일, 자유 메모")
        self.body.addWidget(self.notes,1)
        note = QLabel("내 계정의 첫화면에서 알립니다. 해마다 반복하면 매년 알림이 다시 예약됩니다.\n음력 변환은 인터넷 없이 1900~2050년을 지원합니다. 음력 30일이 없는 해는 29일, 양력 2/29는 평년에 2/28로 적용합니다. 제사는 실제 기억할 제사 날짜를 입력하세요(전날로 자동 변경하지 않음).\n생일·결혼 경과일은 원래 날짜를 양력으로 환산한 실제 경과 기준입니다. 완료 표시는 반복 전체를 중지합니다. 종료 중 놓친 알림은 다음 실행 때 최신 건을 표시합니다.")
        note.setWordWrap(True); self.body.addWidget(note)
        self.finish(self.save)

    def save(self):
        try:
            lunar=self.calendar_type.currentData()=='lunar'
            year,month,day=([c.value() for c in self.lunar_fields] if lunar else [self.date.date().year(),self.date.date().month(),self.date.date().day()])
            self.saved_id = self.store.save_desk_event({"date":self.date.date().toString("yyyy-MM-dd"),"time":self.time.time().toString("HH:mm"),"title":self.title.text(),"notes":self.notes.toPlainText(),"alarm":self.alarm.isChecked(),"done":self.done_box.isChecked(),'calendar':self.calendar_type.currentData(),'repeat':self.repeat.currentData(),'event_kind':self.kind.currentData(),'base_year':year,'month':month,'day':day,'leap':self.leap.isChecked(),'leap_fallback':self.fallback.isChecked(),'lead_days':self.lead.value()},self.record.get("id"))
            mark_saved(self); self.accept()
        except (ValueError,PermissionError) as exc: self.error(exc)


class HomePage(Page):
    def __init__(self,window):
        super().__init__(window,"오늘의 매장","인터넷 없이 사용하는 내 매장 데스크 · PC 시간 기준")
        self.month = date.today().replace(day=1)
        self.selected_date = date.today().isoformat()
        header = QHBoxLayout()
        self.clock,self.greeting = QLabel(),QLabel()
        self.clock_source = QLabel("PC 시간 · Windows 설정 기준")
        self.clock.setStyleSheet("font-size:30px; color:#206B58; font-weight:700;")
        self.greeting.setStyleSheet("font-size:15px; color:#617783;")
        header.addWidget(self.greeting,1)
        time_box=QVBoxLayout(); time_box.addWidget(self.clock); time_box.addWidget(self.clock_source)
        header.addLayout(time_box)
        self.body.addLayout(header)
        content = QHBoxLayout()
        left,right = QVBoxLayout(),QVBoxLayout()
        controls = QHBoxLayout()
        controls.addWidget(action("‹",lambda:self.move_month(-1)))
        self.month_title = QLabel(); self.month_title.setStyleSheet("font-size:20px;font-weight:700;")
        controls.addWidget(self.month_title,1)
        controls.addWidget(action("오늘",self.today)); controls.addWidget(action("›",lambda:self.move_month(1)))
        left.addLayout(controls)
        self.calendar = QTableWidget(6,7)
        self.calendar.setHorizontalHeaderLabels(["일","월","화","수","목","금","토"])
        self.calendar.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.calendar.verticalHeader().hide()
        from PySide6.QtWidgets import QHeaderView
        self.calendar.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.calendar.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.calendar.setMinimumHeight(420)
        self.calendar.cellClicked.connect(self.select_day)
        left.addWidget(self.calendar,1)
        self.day_summary = QLabel(); self.day_summary.setWordWrap(True)
        left.addWidget(self.day_summary)
        content.addLayout(left,3)
        fortune = QFrame(); fortune.setObjectName("homeCard")
        fortune_layout = QVBoxLayout(fortune)
        fortune_layout.setContentsMargins(12,10,12,10)
        fortune_layout.addWidget(QLabel("오늘의 한마디 · 재미로만 보세요"))
        self.fortune = QLabel(); self.fortune.setWordWrap(True); self.fortune.setStyleSheet("font-size:17px; line-height:1.5; color:#206B58;")
        fortune_layout.addWidget(self.fortune)
        right.addWidget(fortune)
        weather_panel=QFrame(); weather_panel.setObjectName("homeCard")
        weather_layout=QVBoxLayout(weather_panel)
        weather_layout.setContentsMargins(12,10,12,10)
        self.weather=QLabel("날씨 · 지역을 선택해 주세요"); self.weather.setWordWrap(True); self.weather.setStyleSheet("font-size:18px;color:#356D88;")
        self.weather_source=QLabel("시간대 예보: MET Norway · CC BY 4.0\n인터넷 연결 시 조회 / 자동 위치 조회 없음"); self.weather_source.setObjectName("muted"); self.weather_source.setWordWrap(True)
        weather_layout.addWidget(self.weather); weather_layout.addWidget(self.weather_source)
        weather_tools=QHBoxLayout()
        self.weather_settings=action("지역·표시 설정",self.configure_online)
        self.weather_settings.setEnabled(self.store.actor["role"]=="admin")
        weather_tools.addWidget(self.weather_settings); weather_tools.addWidget(action("새로고침",self.refresh_online))
        weather_layout.addLayout(weather_tools); right.addWidget(weather_panel)
        tools = QHBoxLayout()
        self.event_scope = QComboBox(); self.event_scope.addItem("선택 날짜 일정",False); self.event_scope.addItem("이달의 모든 일정",True)
        self.event_scope.currentIndexChanged.connect(self.refresh_events)
        tools.addWidget(self.event_scope,1); tools.addWidget(action("일정·메모 +",self.add_event,primary=True))
        right.addLayout(tools)
        self.events = DataGrid(["날짜·시각","일정 · 메모","상태"])
        self.events.setMinimumHeight(130)
        self.events.cellDoubleClicked.connect(lambda *_:self.edit_event())
        self.events.itemSelectionChanged.connect(self.preview_event)
        right.addWidget(self.events,1)
        self.event_detail = QLabel("일정과 메모를 선택하면 상세 내용이 표시됩니다."); self.event_detail.setWordWrap(True); self.event_detail.setMaximumHeight(50)
        self.event_detail.setTextFormat(Qt.TextFormat.PlainText)
        right.addWidget(self.event_detail)
        operations = QHBoxLayout()
        operations.addWidget(action("수정",self.edit_event)); operations.addWidget(action("완료·해제",self.toggle_done)); operations.addWidget(action("삭제",self.delete_event,danger=True))
        operations.addWidget(action('문자 초안',self.message_draft))
        right.addLayout(operations)
        alert_note = QLabel("알림은 프로그램 실행 중에 표시됩니다.\n일정·장부는 인터넷이 끊겨도 계속 사용할 수 있습니다."); alert_note.setObjectName("muted"); alert_note.setWordWrap(True)
        right.addWidget(alert_note)
        content.addLayout(right,2)
        self.body.addLayout(content,1)
        self.links = QWidget(); self.links_layout = QGridLayout(self.links)
        self.links_layout.setContentsMargins(0,8,0,0)
        self.body.addWidget(self.links)
        self.clock_timer = QTimer(self); self.clock_timer.setInterval(1000); self.clock_timer.timeout.connect(self.update_clock); self.clock_timer.start()
        self.online_timer=QTimer(self); self.online_timer.setInterval(15*60*1000); self.online_timer.timeout.connect(self.refresh_online)
        self.online_enabled,self.online_pending=False,False
        self.clock_anchor=None
        self.last_online_fetch=None
        self.update_clock()

    def message_draft(self):
        record=self.events.selected()
        if record:
            from .personal_schedule_ui import open_message_draft
            open_message_draft(record,self)
        else:QMessageBox.information(self,'일정 선택','일정을 선택하면 문자 초안을 만들 수 있습니다.')

    def update_clock(self):
        current = QDateTime.currentDateTime()
        if self.clock_anchor and time.monotonic()-self.clock_anchor[1]<3600:
            stamp=self.clock_anchor[0]+time.monotonic()-self.clock_anchor[1]
            self.clock.setText(datetime.fromtimestamp(stamp,timezone.utc).astimezone(timezone(timedelta(hours=9))).strftime("%H:%M:%S"))
            self.clock_source.setText("한국표준시 KST · 인터넷 참고 시각 (TimeAPI)")
        else:
            self.clock.setText(current.toString("HH:mm:ss")); self.clock_source.setText("PC 시간 · Windows 설정 기준")
        weekdays = ("월요일","화요일","수요일","목요일","금요일","토요일","일요일")
        self.greeting.setText(f"{current.toString('yyyy년 M월 d일')} {weekdays[current.date().dayOfWeek()-1]} · {(self.store.actor or {}).get('name','')}님")
        phrases = ("오늘은 작은 정리가 큰 여유를 만듭니다. 마감 전에 장부를 한 번 살펴보세요.","차근차근 확인한 한 건의 거래가 든든한 하루를 만듭니다.","오늘의 행운은 반가운 인사에서 시작됩니다. 손님에게 미소를 건네보세요.","서두르지 않아도 괜찮습니다. 중요한 일부터 하나씩 마무리해 보세요.","새로운 아이디어가 떠오르면 메모해 두세요. 내일의 도움이 될 수 있습니다.","잠깐의 휴식이 집중력을 더합니다. 바쁜 하루에도 물 한 잔 잊지 마세요.")
        day = current.date().toString("yyyy-MM-dd")
        self.fortune.setText(phrases[int(sha256(day.encode()).hexdigest()[:8],16)%len(phrases)])

    def enable_online(self):
        self.online_enabled=True; self.online_timer.start(); QTimer.singleShot(100,self.refresh_online)

    def refresh_online(self):
        config=self.store.online_preferences()
        if not config["enabled"]:
            self.weather.setText("날씨 · 지역을 선택하고 표시를 켜세요"); self.clock_anchor=None; self.update_clock(); return
        if not self.online_enabled or self.online_pending: return
        if self.last_online_fetch and self.last_online_fetch[0]==config and time.monotonic()-self.last_online_fetch[1]<(600 if self.last_online_fetch[2] else 30):return
        self.online_pending=True
        self.weather.setText(f"{config['city']} · 날씨 확인 중…")
        self.worker=OnlineWorker(config); self.worker.signals.finished.connect(self.online_finished)
        QThreadPool.globalInstance().start(self.worker)

    def online_finished(self,result):
        self.online_pending=False
        try: current=self.store.online_preferences()
        except (ValueError,PermissionError): return
        if result["config"]!=current: return
        self.last_online_fetch=(current,time.monotonic(),bool(result.get("weather")))
        if result.get("weather"):
            self.weather.setText(f"{result['city']} · {result['weather']}")
            self.weather_source.setText(f"{result['weather_at']} KST 시간대 예보\nMET Norway · CC BY 4.0 / 자동 위치 조회 없음")
        else:
            self.weather.setText(f"{current['city']} · 날씨 조회 불가")
            self.weather_source.setText("인터넷 연결 또는 예보 제공 상태를 확인하세요.\n장부·일정 기능은 계속 사용할 수 있습니다.")
        if result.get("clock"):
            self.clock_anchor=(result["clock"],result["clock_anchor"])
        self.update_clock()

    def configure_online(self):
        try: config=self.store.online_preferences()
        except (ValueError,PermissionError) as exc:self.fail(exc); return
        dialog=FormDialog("날씨 지역 · 인터넷 시간",self)
        enabled=QCheckBox("인터넷에서 날씨·한국 시각 조회"); enabled.setChecked(config["enabled"]); dialog.form.addRow(enabled)
        city=QComboBox()
        for name in CITIES:city.addItem(name)
        city.addItem("직접 입력")
        city.setCurrentText(config["city"] if config["city"] in CITIES else "직접 입력")
        dialog.form.addRow("지역 선택",city)
        name=dialog.field("city","지역명",config["city"])
        lat=dialog.field("latitude","위도",config["latitude"]); lon=dialog.field("longitude","경도",config["longitude"])
        def select_city(value):
            if value in CITIES:
                name.setText(value); lat.setText(str(CITIES[value][0])); lon.setText(str(CITIES[value][1]))
        city.currentTextChanged.connect(select_city)
        info=QLabel("GPS·IP 위치 조회는 하지 않습니다. 예보 서비스(MET Norway)에 선택한 지역 좌표만 전송합니다. 시각은 TimeAPI에서 확인하며 PC 시간은 변경하지 않습니다. 인터넷 표시를 끄면 외부 조회를 하지 않습니다."); info.setWordWrap(True); dialog.body.addWidget(info)
        def save():
            try:self.store.save_settings({"online_info":{"enabled":enabled.isChecked(),"city":name.text(),"latitude":lat.text(),"longitude":lon.text()}}); dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.finish(save)
        if dialog.exec():self.clock_anchor=None; self.refresh_online()

    def refresh(self):
        self.draw_calendar()
        while self.links_layout.count():
            widget = self.links_layout.takeAt(0).widget()
            if widget: widget.deleteLater()
        for index,key in enumerate(k for k in ("products","purchases","payments","sales","members","reports","settings") if k in self.window.items and has_menu(self.store.actor,k)):
            button = action(self.window.items[key].text(0),lambda checked=False,target=key:self.window.open_page(target))
            attach_help(button,MENU_HELP[key]); self.links_layout.addWidget(button,index//4,index%4)
        self.update_clock()

    def move_month(self,step):
        month = self.month.year*12+self.month.month-1+step
        self.month = date(month//12,month%12+1,1); self.draw_calendar()

    def today(self):
        self.month = date.today().replace(day=1); self.selected_date = date.today().isoformat(); self.draw_calendar()

    def draw_calendar(self):
        first = self.month-timedelta(days=(self.month.weekday()+1)%7)
        weeks=((self.month.weekday()+1)%7+calendar.monthrange(self.month.year,self.month.month)[1]+6)//7
        last = first+timedelta(days=weeks*7-1)
        self.calendar.setRowCount(weeks)
        self.calendar.setMinimumHeight(360 if weeks<6 else 420)
        self.calendar_data = self.store.home_calendar(first.isoformat(),last.isoformat())
        events = self.store.desk_events(first.isoformat(),last.isoformat())
        counts = {}
        for event in events:
            if not event["done"]: counts[event["date"]] = counts.get(event["date"],0)+1
        self.month_title.setText(f"{self.month.year}년 {self.month.month}월")
        for offset in range(weeks*7):
            current = first+timedelta(days=offset); key = current.isoformat()
            data = self.calendar_data["days"].get(key,{})
            details = [str(current.day)]
            if data:
                if self.calendar_data["purchase_visible"]: details.append(f"입 {won(data['purchase_total'])}")
                if self.calendar_data["sale_visible"]: details.append(f"판 {won(data['sale_total'])}")
            if counts.get(key): details.append(f"● 일정 {counts[key]}")
            item = QTableWidgetItem("\n".join(details)); item.setData(Qt.ItemDataRole.UserRole,key)
            item.setTextAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft)
            item.setForeground(QColor("#9CAAB0" if current.month!=self.month.month else "#BA5C58" if offset%7==0 else "#5277B7" if offset%7==6 else "#36515E"))
            item.setBackground(QColor("#E4F2EB" if key==date.today().isoformat() else "#F4F6F7" if current.month!=self.month.month else "#FFFFFF"))
            self.calendar.setItem(offset//7,offset%7,item)
            if key==self.selected_date: self.calendar.setCurrentItem(item)
        self.refresh_events()

    def select_day(self,row,column):
        self.selected_date = self.calendar.item(row,column).data(Qt.ItemDataRole.UserRole); self.refresh_events()

    def refresh_events(self,*_):
        if not hasattr(self,"events"): return
        start = self.month.isoformat() if self.event_scope.currentData() else self.selected_date
        end = self.month.replace(day=calendar.monthrange(self.month.year,self.month.month)[1]).isoformat() if self.event_scope.currentData() else self.selected_date
        records = self.store.desk_events(start,end)
        self.events.fill([[f"{r['date']} {r['time']}",r["title"],"완료" if r["done"] else "알림 예약" if r["alarm"] and not r["notified_at"] else "알림 확인" if r["alarm"] else "메모"] for r in records],records)
        data = getattr(self,"calendar_data",{}).get("days",{}).get(self.selected_date,{})
        self.day_summary.setText(f"{self.selected_date} · " + " · ".join(f"{label} {won(data.get(key,0))}원" for key,label,visible in (("purchase_total","순매입",self.calendar_data["purchase_visible"]),("sale_total","순판매",self.calendar_data["sale_visible"])) if visible))
        self.preview_event()

    def preview_event(self):
        row = self.events.selected()
        self.event_detail.setText((row["notes"]+'\n'+row.get('counter','')) if row else "일정과 메모를 선택하면 상세 내용이 표시됩니다.")

    def add_event(self):
        if ScheduleDialog(self.store,self.selected_date,parent=self).exec(): self.draw_calendar()

    def edit_event(self):
        row = self.events.selected()
        if row and ScheduleDialog(self.store,self.selected_date,row,self).exec(): self.draw_calendar()

    def toggle_done(self):
        row = self.events.selected()
        if row:
            try: self.store.save_desk_event({"done":not row["done"]},row["id"]); self.draw_calendar()
            except (ValueError,PermissionError) as exc:self.fail(exc)

    def delete_event(self):
        row = self.events.selected()
        if row and QMessageBox.question(self,"일정 삭제","선택한 일정·메모를 삭제할까요?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_desk_event(row["id"]); self.draw_calendar()
            except (ValueError,PermissionError) as exc:self.fail(exc)
