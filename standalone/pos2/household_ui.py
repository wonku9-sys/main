"""Private household cashbook, separate from the shop's financial ledger."""
from datetime import date
from decimal import Decimal
import time

from PySide6.QtCore import QEvent,QTimer,QDate,Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication,QCheckBox,QComboBox,QDialog,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QVBoxLayout,QWidget,QCalendarWidget,QTextEdit,QFrame,QProgressBar,QScrollArea

from .widgets import Page,FormDialog,DataGrid,action,date_field,won
from .navigation import mark_saved,confirm_dialog_exit,ask_unsaved


class CashCalendar(QCalendarWidget):
    def __init__(self,parent=None):super().__init__(parent);self.marks={};self.spending={}
    def paintCell(self,painter,rect,day):
        painter.save()
        current=day.month()==self.monthShown() and day.year()==self.yearShown()
        selected=day==self.selectedDate()
        painter.fillRect(rect,QColor('#F0DFC0' if selected else '#FFFCF7' if current else '#F3F0EB'))
        painter.setPen(QColor('#A7A098' if not current else '#C3757A' if day.dayOfWeek()==7 else '#648BB4' if day.dayOfWeek()==6 else '#514B43'))
        font=painter.font();font.setPixelSize(11);font.setBold(day==QDate.currentDate());painter.setFont(font)
        painter.drawText(rect.adjusted(1,1,-1,-rect.height()//2),Qt.AlignmentFlag.AlignCenter,str(day.day()))
        kinds=self.marks.get(day.toString('yyyy-MM-dd'),set()) & {'income','expense','memo'}
        if current and day<=QDate.currentDate():
            value=self.spending.get(day.toString('yyyy-MM-dd'),Decimal(0))
            painter.setPen(QColor('#AA6575' if value else '#6B967B'))
            font=painter.font();font.setPixelSize(9);painter.setFont(font)
            label=(f'{value/Decimal(10000):.1f}만' if value>=10000 else won(value).replace('.00','')) if value else '무지출'
            painter.drawText(rect.adjusted(0,rect.height()//2,0,-1),Qt.AlignmentFlag.AlignCenter,label)
        x=rect.right()-len(kinds)*3-1
        for kind in sorted(kinds):
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor({'income':'#5C9B76','expense':'#CE8D9C','memo':'#D1A65A'}[kind]));painter.drawEllipse(x,rect.top()+2,2,2);x+=3
        painter.restore()


class HouseholdPage(Page):
    def __init__(self,window):
        super().__init__(window,"나의 가계부","통장과 생활비를 한눈에 · 첫 잠금 해제 후 같은 로그인 동안 다시 열기")
        self.menu_key="household"
        panel=QWidget();panel.setStyleSheet("background:#FFF7EC;border-radius:12px;")
        body=QVBoxLayout(panel);body.setContentsMargins(32,32,32,32)
        title=QLabel("한눈에 정리하는 나의 생활");title.setStyleSheet("font-size:25px;color:#9B7049;font-weight:700;")
        body.addWidget(title)
        body.addWidget(QLabel("나의 가계부 · 열기 / 개인 암호 설정 / 이메일 복구"))
        note=QLabel("수입과 지출을 분류별로 기록하고 기간별 합계를 확인합니다.\n\n원하면 로그인 암호와 별도로 가계부 암호를 설정할 수 있습니다.\n암호를 설정한 자료는 암호화 저장되며, 이메일 복구는 암호를 잊기 전에 미리 등록해야 합니다.\n\n‘암호 없이 사용’은 별도 암호 보호를 제공하지 않습니다. 개인 금융정보에는 암호 사용을 권장합니다.");note.setWordWrap(True);body.addWidget(note)
        body.addWidget(action("가계부 열기",self.open_book,primary=True))
        body.addWidget(action("가계부 암호 찾기 · 이메일 인증",self.email_reset))
        self.body.addWidget(panel);self.body.addStretch()
    def refresh(self):self.store.require_menu("household")
    def email_reset(self):
        from .email_ui import EmailCodeDialog
        EmailCodeDialog(self.store,"household_reset",self).exec()
    def open_book(self):
        from .independent_windows import active_personal
        if active_personal(self,'household'):return
        from .private_session import cached_key
        cached=cached_key(self.store,"household")
        if cached is not None:
            self.show_book(cached);return
        try:state=self.store.household_status()
        except (ValueError,PermissionError) as exc:self.fail(exc);return
        if not state["exists"]:
            dialog=FormDialog("처음 사용하는 가계부",self)
            protect=QCheckBox("별도 가계부 암호로 보호 (권장)");protect.setChecked(True);dialog.form.addRow(protect)
            password=dialog.field("password","가계부 암호 (8~128자)",password=True)
            confirm=dialog.field("confirm","암호 확인",password=True)
            protect.toggled.connect(password.setEnabled);protect.toggled.connect(confirm.setEnabled)
            def setup():
                try:
                    self.store.setup_household(password.text() if protect.isChecked() else "",confirm.text() if protect.isChecked() else "")
                    password.clear();confirm.clear();dialog.accept()
                except (ValueError,PermissionError) as exc:dialog.error(exc)
            dialog.finish(setup)
            if not dialog.exec():password.clear();confirm.clear();return
            state=self.store.household_status()
        key=None
        if state["password_enabled"]:
            dialog=FormDialog("가계부 잠금 해제",self)
            guide=QLabel("나의 가계부\n개인 가계부 암호를 한 번 입력하면 같은 로그인 중에는 다시 묻지 않습니다.");guide.setWordWrap(True);dialog.body.insertWidget(1,guide)
            password=dialog.field("password","가계부 암호",password=True)
            dialog.body.addWidget(action('가계부 암호 찾기 · 이메일 인증',self.email_reset))
            holder={}
            def unlock():
                try:holder["key"]=self.store.unlock_household(password.text());password.clear();dialog.accept()
                except (ValueError,PermissionError) as exc:password.clear();dialog.error(exc)
            dialog.finish(unlock)
            if dialog.exec():key=holder.get("key")
            password.clear()
        else:key=self.store.unlock_household()
        if key is not None:
            self.show_book(key)

    def show_book(self,key):
        from .independent_windows import show_personal
        book=HouseholdDialog(self.store,key,self)
        show_personal(self,'household',book)


class HouseholdDialog(QDialog):
    def __init__(self,store,key,parent=None):
        if getattr(store,'is_shared_client',False):store=store.private
        super().__init__(parent);self.store,self.key=store,key;self.menu_key="household";self.read_permissions=()
        from .private_session import remember_key
        remember_key(store,"household",key)
        self.closed_securely=False;self.setWindowTitle("나의 가계부 · 수입과 지출");self.resize(1150,760)
        self.setStyleSheet("QDialog {background:#FFF9F6;} QTableWidget {alternate-background-color:#FFF8FA;selection-background-color:#F2DDEB;} #cashCard {background:#F2F8EE;border:1px solid #DDEAD7;border-radius:12px;} #memoCard {background:#FFF0E9;border:1px solid #F1DACE;border-radius:12px;} QCalendarWidget {background:#FFFFFF;border:1px solid #E9DEEB;border-radius:12px;} QCalendarWidget QToolButton {color:#876A88;background:#F7EFF7;} QTextEdit {background:#FFFCF2;border:1px solid #EBDCD1;border-radius:8px;padding:10px;}")
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);scroll=QScrollArea(self);scroll.setWidgetResizable(True);container=QWidget();container.setObjectName('personalSurface');self.body=QVBoxLayout(container);scroll.setWidget(container);outer.addWidget(scroll)
        heading=QHBoxLayout();title=QLabel("나의 가계부");title.setObjectName('personalHeading');title.setStyleSheet("font-size:23px;color:#947044;font-weight:700;")
        from .personal_themes import theme_picker
        self.theme=theme_picker(store,'household',self)
        heading.addWidget(title,1);heading.addWidget(self.theme);heading.addWidget(action("암호 설정·변경",self.password_settings));heading.addWidget(action("이메일 복구 등록",self.email_enable));heading.addWidget(action("잠그고 닫기",self.lock_close));heading.addWidget(action("닫기",self.reject));self.body.addLayout(heading)
        row=QHBoxLayout();self.start,self.end=date_field(date.today().replace(day=1)),date_field()
        self.category=QComboBox();self.account=QComboBox();self.search=QLineEdit();self.search.setPlaceholderText("내용 · 분류 · 메모 · #태그 검색")
        for control in (self.start,QLabel("~"),self.end,self.account,self.category,self.search):row.addWidget(control)
        row.addWidget(action("조회",self.refresh));self.body.addLayout(row)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setStyleSheet("background:#EDF6EB;border:1px solid #DCEBD8;border-radius:12px;padding:15px;font-size:16px;color:#5B785A;");self.body.addWidget(self.summary)
        budget=QHBoxLayout();self.budget_label=QLabel();self.budget_label.setWordWrap(True);budget.addWidget(self.budget_label,2)
        self.budget_bar=QProgressBar();self.budget_bar.setRange(0,10000);self.budget_bar.setTextVisible(False);self.budget_bar.setMaximumHeight(16);self.budget_bar.setMinimumWidth(150);budget.addWidget(self.budget_bar,1)
        budget.addWidget(action('이번 달 예산 설정',self.budget_settings));self.body.addLayout(budget)
        budget.addWidget(action('자동분류 규칙',self.category_rules))
        self.comparison=QLabel();self.comparison.setTextFormat(Qt.TextFormat.RichText);self.comparison.setWordWrap(True);self.body.addWidget(self.comparison)
        content=QHBoxLayout();left=QVBoxLayout()
        self.calendar=CashCalendar();self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader);self.calendar.setMinimumWidth(290);self.calendar.setMinimumHeight(295);self.calendar.setMaximumHeight(320)
        left.addWidget(self.calendar)
        from .calendar_actions import attach_calendar_menu
        attach_calendar_menu(self.calendar,self.calendar_menu)
        legend=QLabel('● 초록 수입  ·  분홍 지출  ·  금색 메모');legend.setStyleSheet('font-size:10px;');left.addWidget(legend)
        card=QFrame();card.setObjectName("memoCard");memo_layout=QVBoxLayout(card)
        self.memo_date=date.today().isoformat();self.memo_heading=QLabel();self.memo_heading.setStyleSheet("font-size:15px;color:#A17B6C;font-weight:600;")
        memo_layout.addWidget(self.memo_heading)
        self.memo=QTextEdit();self.memo.setPlaceholderText("오늘의 작은 메모를 남겨보세요.\n사고 싶은 것, 아낀 일, 기억할 일정…\n금액 없이 메모만 저장할 수 있어요.");self.memo.setMinimumHeight(130);memo_layout.addWidget(self.memo,1)
        memo_layout.addWidget(action("오늘의 메모 저장",self.save));left.addWidget(card,1)
        sidebar=QWidget();sidebar.setLayout(left);sidebar.setMaximumWidth(330);content.addWidget(sidebar)
        self.grid=DataGrid(["날짜","통장","구분","분류","내용","금액","누적 잔액","태그","메모"])
        from .household_finance_ui import CashFinanceTabs
        self.finances=CashFinanceTabs(self,self.grid);content.addWidget(self.finances,1);self.body.addLayout(content,1)
        controls=QHBoxLayout()
        for label,callback in (("수입·지출 추가",self.add),("수정",self.edit),("삭제",self.delete),("문자 붙여넣기",self.finances.paste_notification),("엑셀 저장",self.export),("인쇄·PDF",self.print_book)):controls.addWidget(action(label,callback))
        controls.addStretch();self.body.addLayout(controls)
        self.fixed_notice=QLabel();self.fixed_notice.setWordWrap(True);self.body.addWidget(self.fixed_notice)
        foot=QLabel("달력은 기록된 일별 지출·무지출을 표시합니다. 실제 은행 잔액과 자동 동기화하지 않습니다.\n통장·분류·검색을 지정하면 거래내역 잔액은 그 조건 기준입니다. 통장 한눈에·차량·고정비는 기간만 적용합니다.");foot.setWordWrap(True);self.body.addWidget(foot)
        self.grid.cellDoubleClicked.connect(lambda *_:self.edit());self.search.returnPressed.connect(self.refresh)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);self.grid.customContextMenuRequested.connect(self.transaction_menu)
        from .popup_sound import sound_checkbox
        personal=QHBoxLayout();self.body.addLayout(personal)
        self.popup_sound=sound_checkbox(store);personal.addWidget(self.popup_sound);personal.addStretch()
        personal.addWidget(action('건강·병원 기록',self.health))
        personal.addWidget(action('📅 기념일·알림',self.schedules))
        personal.addWidget(action('사진·문서 첨부',self.attach))
        from .personal_themes import apply_theme
        apply_theme(self,self.theme.currentData())
        self.last_activity=time.monotonic();self.last_fixed_check=0;self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.check_idle);self.timer.start()
        QApplication.instance().installEventFilter(self);self.refresh();self.load_memo()
        self.calendar.clicked.connect(self.select_day);self.calendar.currentPageChanged.connect(self.select_month)
        QTimer.singleShot(400,self.fixed_alerts)
    def showEvent(self,event):
        super().showEvent(event)
        from .popup_sound import play_popup
        play_popup(self.store,True)
    def refresh(self):
        from .permissions import can_action
        from .household_finance_ui import account_choices,KINDS
        if can_action(self.store.actor,'household','create'):
            try:
                count=self.store.apply_household_fixed_costs(self.key)
                if count:self.fixed_notice.setText(f'월 고정비 {count}건을 가계부에 기록했습니다. 실제 은행 결제는 실행하지 않았습니다.')
            except (ValueError,PermissionError) as exc:self.fixed_notice.setText('고정비 자동 기록 확인: '+str(exc))
        self.last_fixed_check=time.monotonic()
        selected_account=self.account.currentData()
        self.account.clear()
        for label,value in account_choices(self.store,self.key,True):self.account.addItem(label,value)
        self.account.setCurrentIndex(max(0,self.account.findData(selected_account)))
        selected=self.category.currentData()
        report=self.store.household_report(self.key,self.start.date().toString("yyyy-MM-dd"),self.end.date().toString("yyyy-MM-dd"),selected or "",self.search.text().lstrip('#'),self.account.currentData())
        self.category.clear();self.category.addItem("전체 분류","")
        for value in report["categories"]:self.category.addItem(value,value)
        self.category.setCurrentIndex(max(0,self.category.findData(selected)))
        rows=report["rows"]
        self.grid.fill([[r["date"],r['account_name'],KINDS[r['kind']],r["category"],r["title"],r["amount"],r["balance"],' '.join('#'+t for t in r.get('tags',[])),r["memo"]] for r in rows],rows)
        self.summary.setText(f"이월 {won(report['opening_balance'])}원   ·   수입 +{won(report['income_total'])}원   ·   지출 −{won(report['expense_total'])}원   ·   잔액 {won(report['closing_balance'])}원")
        first=QDate(self.calendar.yearShown(),self.calendar.monthShown(),1)
        month=self.store.household_report(self.key,first.toString('yyyy-MM-dd'),QDate(first.year(),first.month(),first.daysInMonth()).toString('yyyy-MM-dd'))
        marks={}
        for record in month['rows']:marks.setdefault(record['date'],set()).add(record['kind'])
        for memo in self.store.household_memos(self.key):
            if memo['body']:marks.setdefault(memo['date'],set()).add('memo')
        spending={}
        for record in month['rows']:
            if record['kind']=='expense':spending[record['date']]=spending.get(record['date'],Decimal(0))+record['amount']
        from PySide6.QtGui import QTextCharFormat
        for number in range(1,first.daysInMonth()+1):
            value=QDate(first.year(),first.month(),number);style=QTextCharFormat();style.setToolTip(value.toString('yyyy-MM-dd')+' · 기록된 지출 '+won(spending.get(value.toString('yyyy-MM-dd'),0))+'원');self.calendar.setDateTextFormat(value,style)
        self.calendar.marks=marks;self.calendar.spending=spending;self.calendar.updateCells();self.finances.refresh()
        budget=self.store.household_budget(self.key);percent=budget['percent'];self.budget_bar.setValue(min(10000,max(0,int(percent*100))))
        if budget['amount']:
            remainder=('남은 '+won(budget['balance'])+'원') if budget['balance']>=0 else ('초과 '+won(-budget['balance'])+'원')
            self.budget_label.setText(f"{budget['month']} 예산 {won(budget['amount'])}원 · 오늘까지 {won(budget['expense_total'])}원 사용 ({percent:.2f}%) · {remainder}")
        else:self.budget_label.setText(f"이번 달 예산을 설정해 보세요. · 오늘까지 전체 지출 {won(budget['expense_total'])}원 · 이체 제외")
        self.budget_bar.setToolTip('이번 달 전체 예산 대비 오늘까지 지출. 조회 필터와 무관합니다. 100% 초과는 숫자로 표시합니다.')
        color='#C56E78' if percent>=100 else '#C89F53' if percent>=80 else '#6C9C84'
        self.budget_bar.setStyleSheet(f'QProgressBar{{border:1px solid #D9D3C6;border-radius:7px;background:#EEE9DF;}}QProgressBar::chunk{{border-radius:7px;background:{color};}}')
        from html import escape
        comparison=self.store.household_spending_comparison(self.key);difference=comparison['difference'];percent=comparison['percent_change']
        change=(won(abs(difference))+'원 '+('증가' if difference>0 else '감소' if difference<0 else '동일'))
        rate=f' ({abs(percent):.2f}%)' if percent is not None else ' · 지난달 동기간 0원이라 비율 비교 없음'
        top=comparison['top_categories'];highlight=(f"<b style='color:#A56851'>가장 큰 지출: {escape(top[0]['name'])} {won(top[0]['amount'])}원 ({top[0]['percent']:.2f}%)</b>" if top else '이번 달 기록된 지출이 아직 없습니다.')
        self.comparison.setText(f"지난달({comparison['previous_month']}) 전체 {won(comparison['previous_total'])}원 · 같은 날짜까지 대비 {change}{rate}<br>{highlight}")
    def snapshot(self):return self.memo_date,self.memo.toPlainText()
    def category_rules(self):
        from .household_categories_ui import CategoryRulesDialog
        dialog=CategoryRulesDialog(self.store,self.key,self)
        try:dialog.exec()
        finally:dialog.wipe();dialog.deleteLater()
    def budget_settings(self):
        budget=self.store.household_budget(self.key);dialog=FormDialog('이번 달 전체 예산',self)
        total=dialog.field('total',budget['month']+' 예산 (원, 0이면 미설정)',budget['amount'])
        note=QLabel('오늘까지의 전체 통장 지출과 비교합니다. 이체·시작 잔액은 제외합니다. 미래 날짜 지출도 아직 합산하지 않습니다.');note.setWordWrap(True);dialog.body.addWidget(note)
        def save():
            try:self.store.save_household_budget(self.key,budget['month'],total.text());dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.finish(save)
        if dialog.exec():self.refresh()
        total.clear();dialog.deleteLater()
    def fixed_alerts(self):
        if self.closed_securely or not self.isVisible() or QApplication.activeModalWidget() not in {None,self}:return
        try:rows=self.store.due_household_fixed_alerts(self.key)
        except (ValueError,PermissionError):return
        if rows:
            content='\n'.join(r['date']+' · '+r['title']+' · '+won(r['amount'])+'원' for r in rows)
            QMessageBox.information(self,'📌 이번 달 고정 지출을 확인하세요',content+'\n\n가계부 기록과 실제 납부 여부를 확인해 주세요. 은행 송금·문자 발송은 실행하지 않습니다.')
    def health(self):
        from .health_ui import HealthDialog
        dialog=HealthDialog(self.store,'household',self.key,self)
        try:dialog.exec()
        finally:dialog.reject();dialog.deleteLater()
    def schedules(self):
        from .personal_schedule_ui import PersonalScheduleDialog
        dialog=PersonalScheduleDialog(self.store,self)
        try:dialog.exec()
        finally:dialog.reject();dialog.deleteLater()
    def attach(self):
        row=self.grid.selected() if self.finances.currentIndex()==0 else self.finances.history.selected() if self.finances.currentIndex()==4 else None
        if not row or row.get('kind') not in {'income','expense'} and not row.get('_record_type'):
            QMessageBox.information(self,'첨부할 기록 선택','거래내역 또는 차량 기록을 먼저 저장하고 선택하세요.');return
        from .attachment_ui import attachments
        attachments(self.store,self.key,'household',row.get('_record_type','entry'),row['id'],self)
    def load_memo(self):
        records=self.store.household_memos(self.key,self.memo_date)
        self.memo.setPlainText(records[0]["body"] if records else "");self.memo_heading.setText(self.memo_date+" · 작은 메모")
        self.memo_saved=self.snapshot();mark_saved(self)
    def confirm_memo(self):
        if self.snapshot()==self.memo_saved:return True
        if getattr(self,"_navigation_guard",None):return confirm_dialog_exit(self)
        choice=ask_unsaved(self)
        if choice==QMessageBox.StandardButton.Cancel:return False
        if choice==QMessageBox.StandardButton.Save:return self.save()
        return choice==QMessageBox.StandardButton.Discard
    def select_day(self,value):
        if not self.confirm_memo():self.calendar.setSelectedDate(QDate.fromString(self.memo_date,"yyyy-MM-dd"));return
        self.memo_date=value.toString("yyyy-MM-dd");self.start.setDate(value);self.end.setDate(value);self.load_memo();self.refresh()
    def calendar_menu(self,selected,position):
        self.select_day(selected)
        if self.memo_date!=selected.toString('yyyy-MM-dd'):return
        self.calendar.setSelectedDate(selected)
        from .calendar_actions import schedule_menu
        def add(kind):self.editor(initial={'date':self.memo_date,'kind':kind})
        schedule_menu(self.store,selected,position,self,self.refresh,extra=[('이 날짜 지출 기록',lambda:add('expense')),('이 날짜 수입 기록',lambda:add('income')),('비공개 메모 작성·수정',lambda:self.memo.setFocus())])
    def select_month(self,year,month):
        if not self.confirm_memo():return
        first=QDate(year,month,1);self.start.setDate(first);self.end.setDate(QDate(year,month,first.daysInMonth()))
        self.memo_date=first.toString("yyyy-MM-dd");self.load_memo();self.refresh()
    def save(self):
        try:
            self.store.save_household_memo(self.key,self.memo_date,self.memo.toPlainText());self.memo_saved=self.snapshot();mark_saved(self);self.refresh();return True
        except (ValueError,PermissionError) as exc:QMessageBox.warning(self,"메모 저장",str(exc));return False
    def editor(self,record=None,initial=None):
        record=record or {};values=dict(initial or {},**record);dialog=FormDialog("가계부 수입·지출",self);dialog.resize(650,780);dialog._recovery_record_id=record.get('id');dialog._recovery_role='household_entry'
        from .household_finance_ui import account_choices
        from .household_finance import VEHICLE_TYPES
        account=dialog.combo('account','통장',account_choices(self.store,self.key),values.get('account_id',''))
        record_values=record;record=values
        kind=dialog.combo("kind","구분",([('구분을 직접 선택하세요','')] if record.get('kind')=='' else [])+[("지출","expense"),("수입","income")],record.get("kind","expense"))
        entry_date=date_field(record.get("date"));dialog.form.addRow("날짜",entry_date)
        category=dialog.field("category","분류 (식비·교통·급여 등)",record.get("category","기타"))
        title=dialog.field("title","내용 *",record.get("title",""))
        amount=dialog.field("amount","금액 (원, 소수점 두 자리)",record.get("amount",""))
        memo=dialog.field("memo","메모",record.get("memo",""))
        payee=dialog.field('payee','거래처·사용자 (가게·가족 이름 등)',record.get('payee',''))
        tags=dialog.field('tags','태그 (#여행 #가족 등)',' '.join('#'+t for t in record.get('tags',[])))
        car=dialog.combo('car','차량 연동',[('차량 아님','')]+[(r['name'],r['id']) for r in self.store.household_vehicles(self.key)],record.get('vehicle_id',''))
        car_kind=dialog.combo('type','차량 비용 종류',[(v,k) for k,v in VEHICLE_TYPES.items()],record.get('vehicle_type') or 'fuel')
        liters=dialog.field('liters','주유량(L) · 선택',record.get('liters',''))
        odometer=dialog.field('odometer','누적 주행거리(km) · 선택',record.get('odometer',''))
        vendor=dialog.field('vendor','주유소·정비업체·보험사',record.get('vehicle_vendor',''))
        detail=dialog.field('detail','정비·교환 부품·보험 내용',record.get('vehicle_detail',''))
        fuel=dialog.field('fuel','연료 종류 (휘발유·경유 등)',record.get('fuel_kind',''))
        full=QCheckBox('가득 주유');full.setChecked(record.get('full_tank',False));dialog.form.addRow(full)
        insurance_start=dialog.field('insurance_start','보험 시작일 (YYYY-MM-DD, 선택)',record.get('insurance_start',''))
        insurance_end=dialog.field('insurance_end','보험 만기일 (YYYY-MM-DD, 선택)',record.get('insurance_end',''))
        automatic=QCheckBox('내용·문자로 분류 자동 추천');automatic.setChecked(not bool(record_values));dialog.form.addRow(automatic)
        recommendation=QLabel();recommendation.setWordWrap(True);dialog.form.addRow(recommendation)
        def classify():
            if not automatic.isChecked():return
            try:
                result=self.store.suggest_household_category(self.key,title.text()+' '+memo.text(),kind.currentData())
                if result['category']:category.setText(result['category']);recommendation.setText('추천 근거: '+result['keyword'])
                else:recommendation.setText('일치하는 분류 규칙이 없습니다. 직접 선택하세요.')
            except (ValueError,PermissionError) as exc:recommendation.setText(str(exc))
        title.editingFinished.connect(classify);memo.editingFinished.connect(classify);automatic.toggled.connect(lambda *_:classify());kind.currentIndexChanged.connect(lambda *_:classify());category.textEdited.connect(lambda *_:automatic.setChecked(False));classify()
        def car_fields():
            enabled=bool(car.currentData());car_kind.setEnabled(enabled);odometer.setEnabled(enabled);liters.setEnabled(enabled and car_kind.currentData()=='fuel')
            for widget in (vendor,detail,fuel,full,insurance_start,insurance_end):widget.setEnabled(enabled)
        car.currentIndexChanged.connect(car_fields);car_kind.currentIndexChanged.connect(car_fields);car_fields()
        def save():
            try:
                self.store.save_household_entry(self.key,{"date":entry_date.date().toString("yyyy-MM-dd"),"kind":kind.currentData(),"category":category.text(),"title":title.text(),"amount":amount.text(),"memo":memo.text(),'payee':payee.text(),'tags':tags.text(),'account_id':account.currentData(),'vehicle_id':car.currentData(),'vehicle_type':car_kind.currentData() if car.currentData() else '', 'liters':liters.text() if liters.isEnabled() else '', 'odometer':odometer.text() if car.currentData() else '', 'vehicle_vendor':vendor.text(),'vehicle_detail':detail.text(),'fuel_kind':fuel.text(),'full_tank':full.isChecked(),'insurance_start':insurance_start.text(),'insurance_end':insurance_end.text()},record_values.get("id"));dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.scroll_form();dialog.finish(save)
        accepted=dialog.exec()
        for field in dialog.fields.values():
            if isinstance(field,QLineEdit):field.clear()
            elif isinstance(field,QComboBox):field.clear()
        values.clear();dialog.deleteLater()
        if accepted:self.refresh()
    def add(self):self.editor()
    def transaction_menu(self,position):
        from PySide6.QtWidgets import QMenu
        item=self.grid.indexAt(position)
        if item.isValid():self.grid.selectRow(item.row())
        menu=QMenu(self);menu.addAction('수입·지출 추가',self.add);row=self.grid.selected()
        if row and row['kind'] in {'income','expense'}:
            menu.addAction('선택 거래 수정',lambda:self.editor(row));menu.addAction('사진·문서 첨부',self.attach);menu.addAction('거래 나누기',self.split_entry)
        menu.addSeparator();menu.addAction('재무·예산·목표·보고서 열기',lambda:self.finances.setCurrentIndex(5))
        self._transaction_context=menu;menu.popup(self.grid.viewport().mapToGlobal(position))
    def split_entry(self):
        from PySide6.QtWidgets import QTableWidget,QTableWidgetItem
        row=self.grid.selected()
        if not row or row['kind'] not in {'income','expense'}:return
        d=FormDialog('거래 나누기 · 합계 보존',self);d.resize(760,520)
        note=QLabel('원래 금액 '+won(row['amount'])+'원 · 같은 날짜·통장·수입/지출로 분리합니다.\n첫 번째 세부 거래에 원래 첨부파일을 유지합니다. 차량·고정비 거래는 분할하지 않습니다.');note.setWordWrap(True);d.body.addWidget(note)
        grid=QTableWidget(10,3);grid.setHorizontalHeaderLabels(['분류','내용','금액']);d.body.addWidget(grid,1)
        for c,value in enumerate((row['category'],row['title'],str(row['amount']))):grid.setItem(0,c,QTableWidgetItem(value))
        total=QLabel();d.body.addWidget(total)
        def parts():return [dict(zip(('category','title','amount'),[(grid.item(r,c).text().strip() if grid.item(r,c) else '') for c in range(3)])) for r in range(grid.rowCount()) if any(grid.item(r,c) and grid.item(r,c).text().strip() for c in range(3))]
        def calculate():
            try:total.setText('합계 '+won(sum(Decimal(p['amount'].replace(',','')) for p in parts()))+'원 · 원금과 같아야 저장됩니다.')
            except Exception:total.setText('금액을 숫자로 입력하세요.')
        grid.itemChanged.connect(lambda *_:calculate());calculate()
        def save():
            try:self.store.split_household_entry(self.key,row['id'],parts());d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        try:
            if d.exec():self.refresh()
        finally:grid.clearContents();d.deleteLater()
    def edit(self):
        if self.finances.currentIndex()!=0:return
        row=self.grid.selected()
        if row and row['kind'] in {'income','expense'}:self.editor(row)
        elif row:QMessageBox.information(self,'이체·시작 잔액','이체는 ‘이체 관리’, 시작 잔액은 ‘통장 한눈에’에서 수정하세요.')
    def delete(self):
        if self.finances.currentIndex()!=0:return
        row=self.grid.selected()
        if row and row['kind'] not in {'income','expense'}:QMessageBox.information(self,'이체·시작 잔액','이체는 ‘이체 관리’에서 삭제하세요. 시작 잔액은 통장 정보에서 관리합니다.');return
        if row and QMessageBox.question(self,"가계부 항목 삭제","선택한 수입·지출 항목을 삭제할까요?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_household_entry(self.key,row["id"]);self.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,"삭제 실패",str(exc))
    def password_settings(self):
        dialog=FormDialog("가계부 암호 설정·변경",self)
        guide=QLabel("나의 가계부\n별도 암호 사용 여부와 새 암호를 설정합니다. 같은 로그인 중에는 닫았다 다시 열어도 잠금 해제를 유지합니다.");guide.setWordWrap(True);dialog.body.insertWidget(1,guide)
        enabled=QCheckBox("별도 암호 사용");enabled.setChecked(self.store.household_status()["password_enabled"]);dialog.form.addRow(enabled)
        password=dialog.field("password","새 가계부 암호 (8~128자)",password=True);confirm=dialog.field("confirm","새 암호 확인",password=True)
        note=QLabel("암호 사용을 끄면 별도 암호 보호가 없어집니다. 현재 열려 있는 가계부에만 적용합니다.");note.setWordWrap(True);dialog.body.addWidget(note)
        def save():
            try:self.store.set_household_password(self.key,password.text() if enabled.isChecked() else "",confirm.text() if enabled.isChecked() else "");password.clear();confirm.clear();dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.finish(save);dialog.exec();password.clear();confirm.clear()
    def email_enable(self):
        from .email_ui import EmailCodeDialog
        EmailCodeDialog(self.store,"household_enable",self).exec()
        # Recovery verifies a separate key copy; normal close still honours memo saving.
        self.reject()
    def export(self):
        self.store._require_household_key(self.key);self.finances.active_grid().export(self,"개인 가계부 · "+self.finances.tabText(self.finances.currentIndex()))
    def print_book(self):
        self.store._require_household_key(self.key);self.finances.active_grid().print_pages(self,"개인 가계부 · "+self.finances.tabText(self.finances.currentIndex()),self.summary.text())
    def eventFilter(self,watched,event):
        if event.type() in {QEvent.Type.KeyPress,QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,QEvent.Type.Wheel} and isinstance(watched,QWidget) and (watched is self or self.isAncestorOf(watched)):self.last_activity=time.monotonic()
        return False
    def check_idle(self):
        if self.closed_securely:return
        try:self.store._require_household_key(self.key)
        except (ValueError,PermissionError):
            self._lock_on_close=True;self.wipe();QDialog.reject(self);return
        self.fixed_alerts()
        if not self.closed_securely:
            from .health_report_ui import show_health_alerts
            show_health_alerts(self.store,'household',self.key,self)
            if self.isVisible() and QApplication.activeModalWidget() in {None,self} and time.monotonic()-getattr(self,'_last_vehicle_alert',0)>=60:
                self._last_vehicle_alert=time.monotonic()
                try:alerts=self.store.due_household_vehicle_alerts(self.key)
                except (ValueError,PermissionError):alerts=[]
                if alerts:QMessageBox.information(self,'차량 납부·정비 예정 확인','\n'.join(r['vehicle']+' · '+r['title']+' · '+r['due_date']+(' / '+r['due_km']+'km' if r['due_km'] else '') for r in alerts)+'\n\n실제 차량 상태와 납부 여부를 확인하세요. 자동 송금하거나 차량 상태를 판정하지 않습니다.')
        if not self.closed_securely and time.monotonic()-self.last_fixed_check>=60 and QApplication.activeModalWidget() in {None,self}:self.refresh()
        if not self.closed_securely and self.isVisible() and QApplication.activeModalWidget() in {None,self}:
            try:records=self.store.due_desk_alerts()
            except (ValueError,PermissionError):records=[]
            if records:
                from .alert_ui import ScheduleAlertDialog
                ScheduleAlertDialog(records,self).exec()
    def lock_close(self):
        self._lock_on_close=True
        try:self.reject()
        finally:self._lock_on_close=False
    def wipe(self):
        if self.closed_securely:return
        from .popup_sound import play_popup
        play_popup(self.store,False)
        self.closed_securely=True;self.timer.stop();QApplication.instance().removeEventFilter(self)
        from .health_ui import scrub_health
        scrub_health(self)
        from .attachment_ui import scrub_attachments
        scrub_attachments(self)
        self.finances.wipe();self.account.clear();self.category.clear();self.fixed_notice.clear();self.budget_label.clear();self.comparison.clear();self.budget_bar.setValue(0);self.calendar.spending={};self.calendar.marks={};self.calendar.updateCells()
        self.key[:]=bytes(len(self.key))
        if getattr(self,"_lock_on_close",False):self.store.lock_household()
        self.grid.fill([]);self.summary.clear();self.search.clear();self.memo.clear()
        guard=getattr(self,"_navigation_guard",None)
        if guard:guard.snapshots.pop(self,None)
    def reject(self):
        if not self.closed_securely and not self.confirm_memo():return
        self.wipe();super().reject()
