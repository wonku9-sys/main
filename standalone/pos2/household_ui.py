"""Private household cashbook, separate from the shop's financial ledger."""
from datetime import date
from decimal import Decimal
import time

from PySide6.QtCore import QEvent,QTimer,QDate,Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication,QCheckBox,QComboBox,QDialog,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QVBoxLayout,QWidget,QCalendarWidget,QTextEdit,QFrame

from .widgets import Page,FormDialog,DataGrid,action,date_field,won
from .navigation import mark_saved,confirm_dialog_exit,ask_unsaved


class CashCalendar(QCalendarWidget):
    def __init__(self,parent=None):super().__init__(parent);self.marks={}
    def paintCell(self,painter,rect,day):
        super().paintCell(painter,rect,day)
        kinds=self.marks.get(day.toString('yyyy-MM-dd'),set())
        x=rect.center().x()-len(kinds)*3
        for kind in sorted(kinds):
            painter.save();painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor({'income':'#5C9B76','expense':'#CE8D9C','memo':'#D1A65A'}[kind]));painter.drawEllipse(x,rect.bottom()-6,4,4);painter.restore();x+=7


class HouseholdPage(Page):
    def __init__(self,window):
        super().__init__(window,"나의 가계부","개인 수입·지출·잔액 · 매장 매입/판매·결제·회원 포인트에 영향을 주지 않습니다.")
        self.menu_key="household"
        panel=QWidget();panel.setStyleSheet("background:#FFF7EC;border-radius:12px;")
        body=QVBoxLayout(panel);body.setContentsMargins(32,32,32,32)
        title=QLabel("한눈에 정리하는 나의 생활");title.setStyleSheet("font-size:25px;color:#9B7049;font-weight:700;")
        body.addWidget(title)
        note=QLabel("수입과 지출을 분류별로 기록하고 기간별 합계를 확인합니다.\n\n원하면 로그인 암호와 별도로 가계부 암호를 설정할 수 있습니다.\n암호를 설정한 자료는 암호화 저장되며, 이메일 복구는 암호를 잊기 전에 미리 등록해야 합니다.\n\n‘암호 없이 사용’은 별도 암호 보호를 제공하지 않습니다. 개인 금융정보에는 암호 사용을 권장합니다.");note.setWordWrap(True);body.addWidget(note)
        body.addWidget(action("가계부 열기",self.open_book,primary=True))
        body.addWidget(action("가계부 암호 찾기 · 이메일 인증",self.email_reset))
        self.body.addWidget(panel);self.body.addStretch()
    def refresh(self):self.store.require_menu("household")
    def email_reset(self):
        from .email_ui import EmailCodeDialog
        EmailCodeDialog(self.store,"household_reset",self).exec()
    def open_book(self):
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
            password=dialog.field("password","가계부 암호",password=True)
            holder={}
            def unlock():
                try:holder["key"]=self.store.unlock_household(password.text());password.clear();dialog.accept()
                except (ValueError,PermissionError) as exc:password.clear();dialog.error(exc)
            dialog.finish(unlock)
            if dialog.exec():key=holder.get("key")
            password.clear()
        else:key=self.store.unlock_household()
        if key is not None:
            book=HouseholdDialog(self.store,key,self)
            try:book.exec()
            finally:book.wipe();book.deleteLater()


class HouseholdDialog(QDialog):
    def __init__(self,store,key,parent=None):
        super().__init__(parent);self.store,self.key=store,key;self.menu_key="household";self.read_permissions=()
        self.closed_securely=False;self.setWindowTitle("나의 가계부 · 수입과 지출");self.resize(1150,760)
        self.setStyleSheet("QDialog {background:#FFF9F6;} QTableWidget {alternate-background-color:#FFF8FA;selection-background-color:#F2DDEB;} #cashCard {background:#F2F8EE;border:1px solid #DDEAD7;border-radius:12px;} #memoCard {background:#FFF0E9;border:1px solid #F1DACE;border-radius:12px;} QCalendarWidget {background:#FFFFFF;border:1px solid #E9DEEB;border-radius:12px;} QCalendarWidget QToolButton {color:#876A88;background:#F7EFF7;} QTextEdit {background:#FFFCF2;border:1px solid #EBDCD1;border-radius:8px;padding:10px;}")
        self.body=QVBoxLayout(self)
        heading=QHBoxLayout();title=QLabel("나의 수입과 지출");title.setStyleSheet("font-size:23px;color:#947044;font-weight:700;")
        from .personal_themes import theme_picker
        self.theme=theme_picker(store,'household',self)
        heading.addWidget(title,1);heading.addWidget(self.theme);heading.addWidget(action("암호 설정·변경",self.password_settings));heading.addWidget(action("이메일 복구 등록",self.email_enable));heading.addWidget(action("잠그고 닫기",self.reject));self.body.addLayout(heading)
        row=QHBoxLayout();self.start,self.end=date_field(date.today().replace(day=1)),date_field()
        self.category=QComboBox();self.search=QLineEdit();self.search.setPlaceholderText("내용 · 분류 · 메모 검색")
        for control in (self.start,QLabel("~"),self.end,self.category,self.search):row.addWidget(control)
        row.addWidget(action("조회",self.refresh));self.body.addLayout(row)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setStyleSheet("background:#EDF6EB;border:1px solid #DCEBD8;border-radius:12px;padding:15px;font-size:16px;color:#5B785A;");self.body.addWidget(self.summary)
        content=QHBoxLayout();left=QVBoxLayout()
        self.calendar=CashCalendar();self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader);self.calendar.setMinimumWidth(290);self.calendar.setMaximumHeight(245)
        left.addWidget(self.calendar)
        legend=QLabel('● 초록 수입  ·  분홍 지출  ·  금색 메모');legend.setStyleSheet('font-size:10px;');left.addWidget(legend)
        card=QFrame();card.setObjectName("memoCard");memo_layout=QVBoxLayout(card)
        self.memo_date=date.today().isoformat();self.memo_heading=QLabel();self.memo_heading.setStyleSheet("font-size:15px;color:#A17B6C;font-weight:600;")
        memo_layout.addWidget(self.memo_heading)
        self.memo=QTextEdit();self.memo.setPlaceholderText("오늘의 작은 메모를 남겨보세요.\n사고 싶은 것, 아낀 일, 기억할 일정…\n금액 없이 메모만 저장할 수 있어요.");self.memo.setMinimumHeight(130);memo_layout.addWidget(self.memo,1)
        memo_layout.addWidget(action("오늘의 메모 저장",self.save));left.addWidget(card,1)
        sidebar=QWidget();sidebar.setLayout(left);sidebar.setMaximumWidth(330);content.addWidget(sidebar)
        self.grid=DataGrid(["날짜","구분","분류","내용","금액","누적 잔액","메모"]);content.addWidget(self.grid,1);self.body.addLayout(content,1)
        controls=QHBoxLayout()
        for label,callback in (("수입·지출 추가",self.add),("수정",self.edit),("삭제",self.delete),("엑셀 저장",self.export),("인쇄·PDF",self.print_book)):controls.addWidget(action(label,callback))
        controls.addStretch();self.body.addLayout(controls)
        foot=QLabel("달력 날짜를 누르면 그날의 기록과 메모를 봅니다. 월을 바꾸면 한 달 합계로 돌아갑니다.\n분류·검색을 지정하면 이월과 잔액도 그 조건 기준입니다. · 암호가 있으면 메모도 같은 키로 보호합니다.");foot.setWordWrap(True);self.body.addWidget(foot)
        self.grid.cellDoubleClicked.connect(lambda *_:self.edit());self.search.returnPressed.connect(self.refresh)
        from .popup_sound import sound_checkbox
        self.popup_sound=sound_checkbox(store);controls.addWidget(self.popup_sound)
        controls.addWidget(action('건강·병원 기록',self.health))
        from .personal_themes import apply_theme
        apply_theme(self,self.theme.currentData())
        self.last_activity=time.monotonic();self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.check_idle);self.timer.start()
        QApplication.instance().installEventFilter(self);self.refresh();self.load_memo()
        self.calendar.clicked.connect(self.select_day);self.calendar.currentPageChanged.connect(self.select_month)
    def showEvent(self,event):
        super().showEvent(event)
        from .popup_sound import play_popup
        play_popup(self.store,True)
    def refresh(self):
        selected=self.category.currentData()
        report=self.store.household_report(self.key,self.start.date().toString("yyyy-MM-dd"),self.end.date().toString("yyyy-MM-dd"),selected or "",self.search.text())
        self.category.clear();self.category.addItem("전체 분류","")
        for value in report["categories"]:self.category.addItem(value,value)
        self.category.setCurrentIndex(max(0,self.category.findData(selected)))
        rows=report["rows"]
        self.grid.fill([[r["date"],"수입" if r["kind"]=="income" else "지출",r["category"],r["title"],r["amount"],r["balance"],r["memo"]] for r in rows],rows)
        self.summary.setText(f"이월 {won(report['opening_balance'])}원   ·   수입 +{won(report['income_total'])}원   ·   지출 −{won(report['expense_total'])}원   ·   잔액 {won(report['closing_balance'])}원")
        first=QDate(self.calendar.yearShown(),self.calendar.monthShown(),1)
        month=self.store.household_report(self.key,first.toString('yyyy-MM-dd'),QDate(first.year(),first.month(),first.daysInMonth()).toString('yyyy-MM-dd'))
        marks={}
        for record in month['rows']:marks.setdefault(record['date'],set()).add(record['kind'])
        for memo in self.store.household_memos(self.key):
            if memo['body']:marks.setdefault(memo['date'],set()).add('memo')
        self.calendar.marks=marks;self.calendar.updateCells()
    def snapshot(self):return self.memo_date,self.memo.toPlainText()
    def health(self):
        from .health_ui import HealthDialog
        dialog=HealthDialog(self.store,'household',self.key,self)
        try:dialog.exec()
        finally:dialog.reject();dialog.deleteLater()
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
    def select_month(self,year,month):
        if not self.confirm_memo():return
        first=QDate(year,month,1);self.start.setDate(first);self.end.setDate(QDate(year,month,first.daysInMonth()))
        self.memo_date=first.toString("yyyy-MM-dd");self.load_memo();self.refresh()
    def save(self):
        try:
            self.store.save_household_memo(self.key,self.memo_date,self.memo.toPlainText());self.memo_saved=self.snapshot();mark_saved(self);self.refresh();return True
        except (ValueError,PermissionError) as exc:QMessageBox.warning(self,"메모 저장",str(exc));return False
    def editor(self,record=None):
        record=record or {};dialog=FormDialog("가계부 수입·지출",self);dialog.resize(620,600)
        kind=dialog.combo("kind","구분",[("지출","expense"),("수입","income")],record.get("kind","expense"))
        entry_date=date_field(record.get("date"));dialog.form.addRow("날짜",entry_date)
        category=dialog.field("category","분류 (식비·교통·급여 등)",record.get("category","기타"))
        title=dialog.field("title","내용 *",record.get("title",""))
        amount=dialog.field("amount","금액 (원, 소수점 두 자리)",record.get("amount",""))
        memo=dialog.field("memo","메모",record.get("memo",""))
        def save():
            try:
                self.store.save_household_entry(self.key,{"date":entry_date.date().toString("yyyy-MM-dd"),"kind":kind.currentData(),"category":category.text(),"title":title.text(),"amount":amount.text(),"memo":memo.text()},record.get("id"));dialog.accept()
            except (ValueError,PermissionError) as exc:dialog.error(exc)
        dialog.finish(save)
        if dialog.exec():self.refresh()
    def add(self):self.editor()
    def edit(self):
        row=self.grid.selected()
        if row:self.editor(row)
    def delete(self):
        row=self.grid.selected()
        if row and QMessageBox.question(self,"가계부 항목 삭제","선택한 수입·지출 항목을 삭제할까요?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_household_entry(self.key,row["id"]);self.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,"삭제 실패",str(exc))
    def password_settings(self):
        dialog=FormDialog("가계부 암호 설정·변경",self)
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
        # Recovery setup verifies the password separately and relocks the key.
        self.reject()
    def export(self):
        self.store._require_household_key(self.key);self.grid.export(self,"개인 가계부")
    def print_book(self):
        self.store._require_household_key(self.key);self.grid.print_pages(self,"개인 가계부",self.summary.text())
    def eventFilter(self,watched,event):
        if event.type() in {QEvent.Type.KeyPress,QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,QEvent.Type.Wheel} and isinstance(watched,QWidget) and (watched is self or self.isAncestorOf(watched)):self.last_activity=time.monotonic()
        return False
    def check_idle(self):
        # Do not discard an editor's unsaved entries. Its own home/close guard
        # remains active; lock when it closes after an idle timeout.
        if time.monotonic()-self.last_activity>=300 and QApplication.activeModalWidget() in {None,self}:
            self.hide()
            if self.snapshot()!=self.memo_saved:self.save()
            self.wipe();QDialog.reject(self)
    def wipe(self):
        if self.closed_securely:return
        from .popup_sound import play_popup
        play_popup(self.store,False)
        self.closed_securely=True;self.timer.stop();QApplication.instance().removeEventFilter(self)
        from .health_ui import scrub_health
        scrub_health(self)
        self.key[:]=bytes(len(self.key));self.store.lock_household();self.grid.fill([]);self.summary.clear();self.search.clear();self.memo.clear()
        guard=getattr(self,"_navigation_guard",None)
        if guard:guard.snapshots.pop(self,None)
    def reject(self):
        if not self.closed_securely and not self.confirm_memo():return
        self.wipe();super().reject()
