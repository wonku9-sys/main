"""Compact cashbook tabs. Charts use Qt painting, without a chart dependency."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout,
    QLabel, QMessageBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from .household_finance import VEHICLE_TYPES
from .household_parse import parse_notification
from .widgets import DataGrid, FormDialog, action, date_field, won

KINDS={'income':'수입','expense':'지출','transfer_in':'이체 입금','transfer_out':'이체 출금','opening':'시작 잔액'}


class MoneyChart(QWidget):
    def __init__(self, mode, parent=None,title=None,keep_order=False):
        super().__init__(parent); self.mode=mode; self.values=[]; self.chart_title=title;self.keep_order=keep_order;self.setMinimumHeight(230)
    def set_values(self, values): self.values=list(values); self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#FFFCF7')); p.setPen(QColor('#514C46'))
        p.drawText(12,22,self.chart_title or ('지출 분류 비율' if self.mode=='pie' else '통장별 잔액 · 보관 통장 포함'))
        values=self.values
        if not values or not any(v for _,v in values): p.drawText(16,65,'표시할 기록이 아직 없습니다.'); return
        colors=['#709D8A','#C995A3','#CFAB63','#8B9DC3','#AD91B9','#B8C794']
        if self.mode=='pie':
            values=sorted(values,key=lambda x:-x[1]); values=values[:5]+([('그 외',sum(v for _,v in values[5:]))] if len(values)>5 else [])
            total=sum(v for _,v in values); size=min(150,self.width()//2-15,self.height()-48); angle=0
            for i,(label,value) in enumerate(values):
                span=round(float(value/total)*5760); p.setBrush(QColor(colors[i%len(colors)])); p.setPen(Qt.PenStyle.NoPen)
                p.drawPie(QRectF(10,40,size,size),angle,span); angle+=span
                p.setPen(QColor('#514C46')); p.drawText(size+22,52+i*29,f'{label[:12]} · {float(value/total)*100:.1f}%')
                p.drawText(size+22,65+i*29,won(value)+'원')
        else:
            # The table always lists every account. The compact chart shows the
            # eight largest absolute balances, including negative overdrafts.
            values=(values[:24] if self.keep_order else sorted(values,key=lambda x:-abs(x[1]))[:8]); peak=max(abs(v) for _,v in values) or Decimal(1)
            origin=self.width()*.50; width=max(20,self.width()*.23); step=max(21,min(30,(self.height()-38)/len(values)))
            p.setPen(QColor('#CEC8BE')); p.drawLine(int(origin),35,int(origin),self.height()-8)
            for i,(label,value) in enumerate(values):
                y=40+i*step; length=float(abs(value)/peak)*width
                p.setPen(QColor('#514C46')); p.drawText(10,int(y+12),label[:12]); p.drawText(int(origin+width+5),int(y+12),won(value))
                p.fillRect(QRectF(origin-length if value<0 else origin,y,length,13),QColor('#C17D82' if value<0 else colors[0]))


def account_choices(store,key,include_all=False):
    values=([('전체 통장',None)] if include_all else [])+[('미지정·현금','')]
    return values+[(r['name']+(' · 보관' if not r['active'] else ''),r['id']) for r in store.household_accounts(key)]


class CashFinanceTabs(QTabWidget):
    def __init__(self,book,entries):
        super().__init__(book); self.book=book; self.store=book.store; self.key=book.key
        self.addTab(entries,'거래내역')
        accounts,layout=self.panel('통장 한눈에')
        row=QHBoxLayout()
        for label,fn in [('통장 추가',self.add_account),('통장 수정·보관',self.edit_account),('통장 간 이체',self.transfer)]:row.addWidget(action(label,fn))
        layout.addLayout(row)
        self.accounts=DataGrid(['통장·별칭','은행','잔액','기간 수입','기간 지출','상태']);layout.addWidget(self.accounts,1)
        charts=QHBoxLayout();self.pie=MoneyChart('pie');self.bar=MoneyChart('bar');charts.addWidget(self.pie);charts.addWidget(self.bar);layout.addLayout(charts)
        note=QLabel('표의 잔액은 조회 종료일까지의 전체 거래 기준입니다. 이체·시작 잔액은 수입·지출 합계에 넣지 않습니다.\n막대 그래프는 잔액 절댓값 상위 8개, 표에는 모든 통장을 표시합니다.');note.setWordWrap(True);layout.addWidget(note)
        transfers,layout=self.panel('이체 관리')
        self.transfers=DataGrid(['날짜','출금 통장','입금 통장','금액','메모']);layout.addWidget(self.transfers,1)
        row=QHBoxLayout()
        for label,fn in [('이체 추가',self.transfer),('이체 수정',self.edit_transfer),('이체 삭제',self.delete_transfer)]:row.addWidget(action(label,fn))
        layout.addLayout(row)
        fixed,layout=self.panel('월 고정비')
        self.analysis=QLabel();self.analysis.setWordWrap(True);layout.addWidget(self.analysis)
        self.fixed=DataGrid(['내용','금액','매월 기록일','시작일','종료일','통장','상태']);layout.addWidget(self.fixed,1)
        row=QHBoxLayout()
        for label,fn in [('고정비 추가',self.fixed_editor),('수정·자동 기록 중지',self.edit_fixed),('미반영 고정비 기록',self.apply_fixed)]:row.addWidget(action(label,fn))
        layout.addLayout(row)
        note=QLabel('가계부를 열거나 조회할 때 지난 지정일의 고정비를 월 1회 기록합니다. 잠긴 동안에는 기록하지 않습니다.\n31일이 없는 달은 말일에 기록합니다. 실제 은행 이체·결제는 실행하지 않습니다. 삭제한 자동 기록은 다시 만들지 않습니다.');note.setWordWrap(True);layout.addWidget(note)
        cars,layout=self.panel('🚙 차량 관리')
        row=QHBoxLayout()
        for label,fn in [('차량 추가',self.add_vehicle),('차량 수정·보관',self.edit_vehicle),('유지비 기록',self.add_vehicle_expense),('비용 없는 기록',self.vehicle_log_editor),('기록 삭제',self.delete_vehicle_record)]:row.addWidget(action(label,fn))
        layout.addLayout(row)
        self.vehicles=DataGrid(['차량','차량번호','차종·연식','기간 유지비','상태']);layout.addWidget(self.vehicles,1)
        more=QHBoxLayout()
        for label,fn in [('납부·정비 예정',self.obligations),('유지비·연비 리포트',self.vehicle_report),('리콜 공식 조회',lambda:self.official('recall')),('검사 공식 안내',lambda:self.official('inspection'))]:more.addWidget(action(label,fn))
        layout.addLayout(more)
        self.vehicle_summary=QLabel();layout.addWidget(self.vehicle_summary)
        self.vehicle_summary.setWordWrap(True);self.vehicle_summary.setStyleSheet('background:#E9F0EA;border:1px solid #D7E5DA;padding:14px;border-radius:10px;font-weight:600;')
        self.history=DataGrid(['날짜','기록 종류','내용','금액','업체·장소','주유량(L)','주행거리(km)','상세·보험 기간','메모']);layout.addWidget(self.history,1)
        self.vehicles.itemSelectionChanged.connect(self.vehicle_history)
        self.history.cellDoubleClicked.connect(self.edit_vehicle_expense)
        note=QLabel('차량 비용은 가계부 지출 1건과 연결됩니다. 아래 기록을 더블클릭해 수정하면 가계부도 함께 바뀝니다.\n주유량·주행거리는 선택 입력입니다. 보험료·정비비를 중복으로 가계부에 입력하지 마세요.');note.setWordWrap(True);layout.addWidget(note)
        from .household_planning_ui import HouseholdPlanningTabs
        self.planning=HouseholdPlanningTabs(self);self.addTab(self.planning,'재무·계획')
        from .menu_icons import menu_icon
        for i,key in enumerate(('report','wallet','money','calendar','truck','goal')):self.setTabIcon(i,menu_icon(key))
    def panel(self,title):
        widget=QWidget();layout=QVBoxLayout(widget);self.addTab(widget,title);return widget,layout
    def private_exec(self,dialog):
        dialog.scroll_form()
        try:return dialog.exec()
        finally:
            from PySide6.QtWidgets import QLineEdit
            for control in dialog.findChildren(QLineEdit)+dialog.findChildren(QTextEdit)+dialog.findChildren(QComboBox):control.clear()
            guard=getattr(dialog,'_navigation_guard',None)
            if guard:guard.snapshots.pop(dialog,None)
            dialog.deleteLater()
    def refresh(self):
        b=self.book;start=b.start.date().toString('yyyy-MM-dd');end=b.end.date().toString('yyyy-MM-dd')
        data=self.store.household_dashboard(self.key,start,end);names={r['id']:r['name'] for r in data['accounts']}
        self.accounts.fill([[r['name'],r['bank'],r['balance'],r['income_total'],r['expense_total'],'사용' if r['active'] else '보관'] for r in data['accounts']],data['accounts'])
        self.pie.set_values([(r['name'],r['amount']) for r in data['categories']]);self.bar.set_values([(r['name'],r['balance']) for r in data['accounts']])
        rows=[r for r in self.store.household_transfers(self.key) if start<=r['date']<=end]
        self.transfers.fill([[r['date'],names.get(r['from_account'],''),names.get(r['to_account'],''),r['amount'],r['memo']] for r in rows],rows)
        rows=self.store.household_fixed_costs(self.key)
        self.fixed.fill([[r['title'],r['amount'],str(r['monthly_day'])+'일',r['start_date'],r['end_date'],names.get(r['account_id'],''),'자동 기록' if r['active'] else '중지'] for r in rows],rows)
        expenses=[r for r in self.store.household_report(self.key,start,end)['rows'] if r['kind']=='expense']
        fixed=sum((r['amount'] for r in expenses if r.get('fixed_rule_id')),Decimal(0));variable=sum((r['amount'] for r in expenses if not r.get('fixed_rule_id')),Decimal(0));total=fixed+variable
        self.analysis.setText(f"기간 고정비 {won(fixed)}원 · 변동비 {won(variable)}원 · 고정비 비율 {float(fixed/total)*100 if total else 0:.1f}%\n자동 고정비로 생성된 거래만 고정비로 집계합니다. 금액이 큰 항목부터 계약·구독 유지 여부를 점검해 보세요.")
        selected=self.vehicles.selected();self.vehicles.blockSignals(True)
        self.vehicles.fill([[r['name'],r['plate'],r['model'],r['expense_total'],'사용' if r['active'] else '보관'] for r in data['vehicles']],data['vehicles'])
        self.vehicles.blockSignals(False)
        index=next((i for i in range(self.vehicles.rowCount()) if self.vehicles.item(i,0).data(Qt.ItemDataRole.UserRole)['id']==(selected or {}).get('id')),0)
        if self.vehicles.rowCount():self.vehicles.selectRow(index)
        self.vehicle_history()
        self.planning.refresh()
    def active_grid(self):return self.planning.active_grid() if self.currentIndex()==5 else {0:self.book.grid,1:self.accounts,2:self.transfers,3:self.fixed,4:self.history}[self.currentIndex()]
    def add_account(self):self.account_editor()
    def edit_account(self):
        row=self.accounts.selected()
        if row and row['id']:
            record=next(r for r in self.store.household_accounts(self.key) if r['id']==row['id']);self.account_editor(record)
    def account_editor(self,record=None):
        record=record or {};d=FormDialog('통장 등록 · 시작 잔액',self)
        name=d.field('name','통장 이름 *',record.get('name',''));bank=d.field('bank','은행·별칭',record.get('bank',''))
        owner=d.field('owner','소유자 별칭 (본인·배우자·아이 등)',record.get('owner','본인'))
        account_type=d.combo('account_type','계정 종류',[('입출금 통장','bank'),('현금','cash'),('예·적금','deposit'),('투자','investment'),('카드 미납 관리','card'),('대출 관리','loan'),('기타','other')],record.get('account_type','bank'))
        opened=date_field(record.get('opening_date'));d.form.addRow('시작일',opened)
        amount=d.field('opening','시작 잔액 · 마이너스 가능',record.get('opening_balance','0'))
        active=QCheckBox('사용 중');active.setChecked(record.get('active',True));d.form.addRow(active)
        memo=d.field('memo','메모',record.get('memo',''))
        def save():
            try:self.store.save_household_account(self.key,dict(name=name.text(),bank=bank.text(),owner=owner.text(),account_type=account_type.currentData(),opening_date=opened.date().toString('yyyy-MM-dd'),opening_balance=amount.text(),active=active.isChecked(),memo=memo.text()),record.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.private_exec(d):self.book.refresh()
    def transfer(self,record=None):
        record=record or {};d=FormDialog('통장 간 이체 · 지출 합계에서 제외',self)
        value=date_field(record.get('date'));d.form.addRow('이체일',value)
        choices=account_choices(self.store,self.key)
        source=d.combo('from','출금 통장',choices,record.get('from_account'));target=d.combo('to','입금 통장',choices,record.get('to_account'))
        amount=d.field('amount','이체 금액',record.get('amount',''));memo=d.field('memo','메모',record.get('memo',''))
        def save():
            try:self.store.save_household_transfer(self.key,dict(date=value.date().toString('yyyy-MM-dd'),from_account=source.currentData(),to_account=target.currentData(),amount=amount.text(),memo=memo.text()),record.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.private_exec(d):self.book.refresh()
    def edit_transfer(self):
        row=self.transfers.selected()
        if row:self.transfer(row)
    def delete_transfer(self):
        row=self.transfers.selected()
        if row and QMessageBox.question(self,'이체 삭제','이체 내역을 삭제하면 양쪽 통장 잔액이 함께 바뀝니다. 삭제할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_household_transfer(self.key,row['id']);self.book.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'이체 삭제',str(exc))
    def fixed_editor(self,record=None):
        record=record or {};d=FormDialog('매월 고정비 · 자동 지출 기록',self)
        title=d.field('title','내용 *',record.get('title',''));amount=d.field('amount','매월 금액',record.get('amount',''))
        monthly=d.field('day','매월 기록일 (1~31)',record.get('monthly_day',date.today().day))
        start=date_field(record.get('start_date'));d.form.addRow('시작일',start)
        end=d.field('end','종료일 (없으면 빈칸)',record.get('end_date',''))
        account=d.combo('account','출금 통장',account_choices(self.store,self.key),record.get('account_id',''))
        category=d.field('category','분류',record.get('category','고정비'))
        car=d.combo('car','차량 연동',[('차량 아님','')]+[(r['name'],r['id']) for r in self.store.household_vehicles(self.key)],record.get('vehicle_id',''))
        kind=d.combo('type','차량 비용 종류',[(v,k) for k,v in VEHICLE_TYPES.items()],record.get('vehicle_type') or 'insurance')
        active=QCheckBox('가계부를 열 때 미반영분 자동 기록');active.setChecked(record.get('active',True));d.form.addRow(active)
        memo=d.field('memo','메모',record.get('memo',''))
        def save():
            try:
                self.store.save_household_fixed_cost(self.key,dict(title=title.text(),amount=amount.text(),monthly_day=monthly.text(),start_date=start.date().toString('yyyy-MM-dd'),end_date=end.text(),account_id=account.currentData(),category=category.text(),vehicle_id=car.currentData(),vehicle_type=kind.currentData() if car.currentData() else '',active=active.isChecked(),memo=memo.text()),record.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.private_exec(d):self.book.refresh()
    def edit_fixed(self):
        row=self.fixed.selected()
        if row:self.fixed_editor(row)
    def apply_fixed(self):
        try:
            count=self.store.apply_household_fixed_costs(self.key);QMessageBox.information(self,'월 고정비',f'미반영 고정비 {count}건을 기록했습니다. 실제 결제는 실행하지 않았습니다.');self.book.refresh()
        except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'월 고정비',str(exc))
    def add_vehicle(self):self.vehicle_editor()
    def edit_vehicle(self):
        row=self.vehicles.selected()
        if row:self.vehicle_editor(row)
    def vehicle_editor(self,record=None):
        record=record or {};d=FormDialog('차량 등록 · 관리',self)
        fields={k:d.field(k,label,record.get(k,'')) for k,label in [('name','차량 이름 *'),('plate','차량번호'),('model','차종·연식'),('next_service_date','다음 정비일 (YYYY-MM-DD, 선택)'),('next_service_km','다음 정비 주행거리(km, 선택)'),('memo','차량 메모')]}
        active=QCheckBox('사용 중');active.setChecked(record.get('active',True));d.form.addRow(active)
        def save():
            try:self.store.save_household_vehicle(self.key,dict({k:v.text() for k,v in fields.items()},active=active.isChecked()),record.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.private_exec(d):self.book.refresh()
    def add_vehicle_expense(self):
        row=self.vehicles.selected()
        if not row:QMessageBox.information(self,'차량 선택','먼저 차량을 등록하고 선택하세요.');return
        self.book.editor(initial=dict(kind='expense',category='차량',vehicle_id=row['id'],vehicle_type='fuel'))
    def edit_vehicle_expense(self,*_):
        row=self.history.selected()
        if row:
            if row.get('_record_type')=='vehicle_log':self.vehicle_log_editor(row)
            else:self.book.editor(row)
    def vehicle_log_editor(self,record=None):
        record=record or {};car=self.vehicles.selected()
        if not car:QMessageBox.information(self,'차량 선택','먼저 차량을 등록하고 선택하세요.');return
        d=FormDialog('운행·점검·사고 메모 · 비용 없는 기록',self)
        when=date_field(record.get('date'));d.form.addRow('기록일',when)
        kind=d.combo('kind','기록 종류',[('운행','drive'),('점검','inspection'),('정비 메모','service'),('사고 기록','accident'),('기타 메모','note')],record.get('log_kind','note'))
        fields={k:d.field(k,label,record.get(k,'')) for k,label in [('title','기록 내용 *'),('place','장소·업체'),('odometer','누적 주행거리(km)'),('distance','이번 운행 거리(km)'),('departure','출발지'),('destination','도착지'),('route','이동 경로 메모 · GPS 사용 안 함'),('memo','상세 메모')]}
        from .vehicle_management import CHECKS
        checks={name:d.combo(name,label,[('미확인','unchecked'),('확인·양호','ok'),('추가 점검 필요','needs')],record.get('checks',{}).get(name,'unchecked')) for name,label in CHECKS.items()}
        note=QLabel('금액이 발생했다면 유지비 기록에서 입력하세요. 이 메모는 가계부 잔액을 바꾸지 않습니다.');note.setWordWrap(True);d.body.addWidget(note)
        def save():
            try:self.store.save_household_vehicle_log(self.key,dict({k:v.text() for k,v in fields.items()},vehicle_id=car['id'],date=when.date().toString('yyyy-MM-dd'),log_kind=kind.currentData(),checks={k:v.currentData() for k,v in checks.items()}),record.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.private_exec(d):self.book.refresh()
    def delete_vehicle_record(self):
        row=self.history.selected()
        if not row:return
        message='선택한 비용 없는 차량 기록과 첨부파일을 삭제할까요?' if row.get('_record_type')=='vehicle_log' else '차량 유지비와 첨부파일을 삭제할까요? 연결된 가계부 지출도 함께 삭제됩니다.'
        if QMessageBox.question(self,'차량 기록 삭제',message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:
            if row.get('_record_type')=='vehicle_log':self.store.delete_household_vehicle_log(self.key,row['id'])
            else:self.store.delete_household_entry(self.key,row['id'])
            self.book.refresh()
        except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'차량 기록 삭제',str(exc))
    def vehicle_history(self):
        row=self.vehicles.selected()
        if not row:self.history.fill([]);self.vehicle_summary.clear();return
        b=self.book;rows=self.store.household_vehicle_history(self.key,row['id'],b.start.date().toString('yyyy-MM-dd'),b.end.date().toString('yyyy-MM-dd'))
        logs=self.store.household_vehicle_logs(self.key,row['id'],b.start.date().toString('yyyy-MM-dd'),b.end.date().toString('yyyy-MM-dd'))
        all_rows=rows+[dict(r,_record_type='vehicle_log') for r in logs];all_rows.sort(key=lambda r:(r['date'],r['created_at']))
        log_names={'drive':'운행','inspection':'점검','service':'정비 메모','accident':'사고','note':'메모'}
        self.history.fill([[r['date'],log_names[r['log_kind']] if r.get('_record_type') else VEHICLE_TYPES[r['vehicle_type']],r['title'],r.get('amount','—'),r.get('vehicle_vendor',r.get('place','')),r.get('liters',''),r.get('odometer',''),r.get('vehicle_detail','')+' '+r.get('fuel_kind','')+(' · 가득 주유' if r.get('full_tank') else '')+' '+r.get('insurance_start','')+('~'+r['insurance_end'] if r.get('insurance_end') else ''),r['memo']] for r in all_rows],all_rows)
        total=sum((r['amount'] for r in rows),Decimal(0));fuel=sum((r['amount'] for r in rows if r['vehicle_type']=='fuel'),Decimal(0))
        status=''
        # Due kilometre readings use all recorded history through today, not a
        # period-filtered subset, and never invent a future odometer reading.
        car=next(r for r in self.store.household_vehicles(self.key) if r['id']==row['id'])
        all_history=self.store.household_vehicle_history(self.key,row['id'],'1900-01-01',date.today().isoformat())+self.store.household_vehicle_logs(self.key,row['id'],'1900-01-01',date.today().isoformat())
        odometer=max((Decimal(r['odometer']) for r in all_history if r.get('odometer')),default=Decimal(0))
        if car.get('next_service_date') and car['next_service_date']<=date.today().isoformat() or car.get('next_service_km') and odometer>=Decimal(car['next_service_km']):status='\n⚠ 다음 정비 기준에 도달했습니다. 정비 후 차량 정보의 예정일·주행거리를 갱신하세요.'
        pending=[r for r in self.store.household_vehicle_obligations(self.key,row['id']) if r['active'] and not r['completed']]
        reminders=[]
        for task in sorted(pending,key=lambda r:(r['due_date'] or '9999',r['title']))[:3]:
            due=[]
            if task['due_date']:
                left=(date.fromisoformat(task['due_date'])-date.today()).days;due.append(('D-'+str(left)) if left>0 else '오늘' if left==0 else str(-left)+'일 지남')
            if task['due_km']:due.append(f"{Decimal(task['due_km'])-odometer:,.0f}km 남음")
            reminders.append(task['title']+' ('+', '.join(due)+')')
        self.vehicle_summary.setText(f"{row['name']} · 기간 유지비 {won(total)}원 · 주유비 {won(fuel)}원\n비용 {len(rows)}건 / 운행·점검 {len(logs)}건 · 기록된 누적 {odometer:,}km · 미처리 예정 {len(pending)}건"+status+('\n'+' · '.join(reminders) if reminders else ''))
    def obligations(self):
        self.vehicle_window('obligations')
    def vehicle_report(self):self.vehicle_window('report')
    def vehicle_window(self,kind):
        car=self.vehicles.selected()
        if not car:QMessageBox.information(self,'차량 선택','차량을 먼저 선택하세요.');return
        from .vehicle_management_ui import VehicleObligationsDialog,VehicleReportDialog
        dialog=(VehicleObligationsDialog if kind=='obligations' else VehicleReportDialog)(self.store,self.key,car['id'],self)
        try:dialog.exec()
        finally:dialog.wipe();dialog.deleteLater();self.book.refresh()
    def official(self,kind):
        from .vehicle_management_ui import official_site
        official_site(self,kind)
    def paste_notification(self):
        d=FormDialog('문자·알림 붙여넣기 · 저장 전 확인',self);d.resize(650,480)
        source=QTextEdit();source.setPlaceholderText('은행·카드 문자나 알림을 복사한 뒤 여기에 Ctrl+V로 붙여넣으세요.');d.body.addWidget(source)
        note=QLabel('클립보드를 자동 감시하지 않습니다. 외부 전송 없이 이 PC에서만 읽습니다.\n여러 거래·취소 알림은 금액과 구분을 꼭 확인하세요.');note.setWordWrap(True);d.body.addWidget(note)
        holder={}
        def preview():
            try:holder.update(parse_notification(source.toPlainText()));d.accept()
            except ValueError as exc:d.error(exc)
        d.finish(preview);d.buttons.button(d.buttons.StandardButton.Save).setText('읽고 확인하기')
        accepted=d.exec();source.clear()
        if accepted:
            warnings=holder.pop('warnings')
            if warnings:QMessageBox.information(self,'붙여넣기 확인','\n'.join(warnings))
            self.book.editor(initial=holder)
        holder.clear();d.deleteLater()
    def wipe(self):
        from PySide6.QtWidgets import QLineEdit
        for dialog in self.findChildren(QDialog):
            if hasattr(dialog,'wipe'):dialog.wipe()
            for control in dialog.findChildren(QLineEdit)+dialog.findChildren(QTextEdit)+dialog.findChildren(QComboBox):control.clear()
            guard=getattr(dialog,'_navigation_guard',None)
            if guard:guard.snapshots.pop(dialog,None)
            QDialog.reject(dialog)
        for grid in self.findChildren(DataGrid):grid.fill([])
        self.pie.set_values([]);self.bar.set_values([]);self.analysis.clear();self.vehicle_summary.clear()
        self.planning.wipe()
