"""Private vehicle reports and pending insurance/tax/maintenance management."""
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QHBoxLayout,QLabel,QMessageBox,QVBoxLayout,QCheckBox
from .widgets import DataGrid,FormDialog,action,date_field,won
from .household_finance import VEHICLE_TYPES


def official_site(parent,kind):
    title,url=('자동차 리콜센터','https://www.car.go.kr/') if kind=='recall' else ('한국교통안전공단 사이버검사소','https://www.cyberts.kr/')
    if QMessageBox.question(parent,'공식 사이트 열기',title+'를 외부 브라우저로 엽니다. 인터넷이 필요합니다. 차량번호·위치·개인 자료를 프로그램에서 자동 전송하지 않습니다. 계속할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
        if not QDesktopServices.openUrl(QUrl(url)):QMessageBox.information(parent,'공식 사이트',url+' 주소를 브라우저에 직접 입력하세요.')


class VehicleReportDialog(QDialog):
    def __init__(self,store,key,identifier,parent=None):
        super().__init__(parent);self.store,self.key,self.identifier=store,key,identifier;self.setWindowTitle('차량 월별·기간별 유지비 · 연비 참고 리포트');self.resize(920,690)
        body=QVBoxLayout(self);row=QHBoxLayout();self.start,self.end=date_field(),date_field();self.start.setDate(self.start.date().addMonths(-6))
        for widget in (self.start,QLabel('~'),self.end):row.addWidget(widget)
        row.addWidget(action('조회',self.refresh));body.addLayout(row)
        self.summary=QLabel();self.summary.setWordWrap(True);body.addWidget(self.summary)
        self.months=DataGrid(['월','유지비 합계']);body.addWidget(self.months,1)
        self.categories=DataGrid(['비용 종류','금액']);body.addWidget(self.categories,1)
        self.fuel=DataGrid(['시작일','종료일','주행 km','연료 L','참고 km/L']);body.addWidget(self.fuel,1)
        tools=QHBoxLayout()
        for label,fn in [('월별 엑셀',lambda:self.months.export(self,'차량 월별 유지비')),('월별 인쇄·PDF',lambda:self.months.print_pages(self,'차량 월별 유지비',self.summary.text())),('연비 엑셀',lambda:self.fuel.export(self,'만땅법 참고 연비')),('닫기',self.reject)]:tools.addWidget(action(label,fn))
        body.addLayout(tools);note=QLabel('연비는 두 번의 만땅 주유 사이 주행거리 ÷ 그 사이 주유량입니다. 첫 만땅 주유량은 제외합니다.\n주유 기록 누락·주행거리 오류·중간에 연료를 뺀 경우는 정확하지 않습니다. 같은 날 여러 주유의 순서를 알 수 없거나 양이 빠지면 해당 구간을 계산하지 않습니다. 참고값이며 차량 성능 판정이 아닙니다.');note.setWordWrap(True);body.addWidget(note);self.refresh()
    def refresh(self):
        try:
            r=self.store.household_vehicle_report(self.key,self.identifier,self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'))
            self.summary.setText('기간 유지비 '+won(r['expense_total'])+'원 · 만땅법 참고 연비 '+(str(r['km_per_liter'])+' km/L' if r['km_per_liter'] is not None else '계산 가능한 기록 부족')+(' · 불완전한 구간 제외' if r['uncertain'] else ''))
            self.months.fill([[v['month'],v['expense_total']] for v in r['months']]);self.categories.fill([[VEHICLE_TYPES[v['name']],v['amount']] for v in r['categories']])
            self.fuel.fill([[v[k] for k in ('start','end','distance','liters','km_per_liter')] for v in r['segments']])
        except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'차량 리포트',str(exc))
    def wipe(self):
        for grid in (self.months,self.categories,self.fuel):grid.fill([])
        self.summary.clear()
    def reject(self):self.wipe();super().reject()


class VehicleObligationsDialog(QDialog):
    def __init__(self,store,key,identifier,parent=None):
        super().__init__(parent);self.store,self.key,self.identifier=store,key,identifier;self.setWindowTitle('보험·세금 납부관리 · 정비·검사 예정');self.resize(930,560)
        body=QVBoxLayout(self);self.grid=DataGrid(['예정 내용','종류','예정일','예정 주행 km','예정 금액','상태','업체']);body.addWidget(self.grid,1)
        controls=QHBoxLayout()
        for title,fn in [('예정 추가',self.add),('수정·중지',self.edit),('납부·처리 완료',self.complete),('완료 취소',self.void),('닫기',self.reject)]:controls.addWidget(action(title,fn))
        body.addLayout(controls);note=QLabel('예정 등록은 지출이 아닙니다. ‘납부·처리 완료’에서 실제 날짜·통장을 확인하면 가계부 지출 1건으로 연결합니다.\n0원 점검은 비용 없는 차량 기록으로 남습니다. 같은 항목을 두 번 완료해도 지출을 중복 생성하지 않습니다. 실제 송금·보험사/국가기관 연동은 하지 않습니다.\n예정일·주행거리 도달은 가계부가 열려 있을 때 알립니다. 정비 후 다음 예정은 직접 새로 등록하세요.');note.setWordWrap(True);body.addWidget(note);self.refresh()
    def refresh(self):
        rows=self.store.household_vehicle_obligations(self.key,self.identifier);labels={'insurance':'보험','tax':'세금','maintenance':'정비·소모품','inspection':'검사'}
        self.grid.fill([[r['title'],labels[r['obligation_kind']],r['due_date'],r['due_km'],r['amount'],'완료' if r['completed'] else '예정' if r['active'] else '중지',r['vendor']] for r in rows],rows)
    def add(self):self.editor()
    def edit(self):
        record=self.grid.selected()
        if record:self.editor(record)
    def editor(self,record=None):
        record=record or {};d=FormDialog('납부·정비 예정',self)
        title=d.field('title','내용 *',record.get('title',''));kind=d.combo('kind','종류',[('보험','insurance'),('세금','tax'),('정비·소모품','maintenance'),('검사','inspection')],record.get('obligation_kind','maintenance'))
        fields={k:d.field(k,label,record.get(k,default)) for k,label,default in [('due_date','예정일 (YYYY-MM-DD, 선택)',''),('due_km','예정 주행거리(km, 선택)',''),('amount','예정 금액 · 비용 없으면 0','0.00'),('vendor','보험사·업체',''),('memo','상세 메모','')]}
        active=QCheckBox('예정 알림 사용');active.setChecked(record.get('active',True));d.form.addRow(active)
        def save():
            try:self.store.save_household_vehicle_obligation(self.key,dict({k:v.text() for k,v in fields.items()},vehicle_id=self.identifier,title=title.text(),obligation_kind=kind.currentData(),active=active.isChecked()),record.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.scroll_form();d.finish(save)
        if d.exec():self.refresh()
        for value in fields.values():value.clear()
        title.clear();d.deleteLater()
    def complete(self):
        record=self.grid.selected()
        if not record:return
        from .household_finance_ui import account_choices
        d=FormDialog('실제 납부·처리 확인',self);when=date_field();d.form.addRow('실제 납부·처리일',when)
        account=d.combo('account','지출 통장',account_choices(self.store,self.key))
        note=QLabel(record['title']+' · '+won(record['amount'])+'원\n금액이 다르면 취소하고 예정 항목을 먼저 수정하세요. 실제 은행 송금은 하지 않습니다.');note.setWordWrap(True);d.body.addWidget(note)
        def save():
            try:self.store.complete_household_vehicle_obligation(self.key,record['id'],when.date().toString('yyyy-MM-dd'),account.currentData());d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if d.exec():self.refresh()
        account.clear();d.deleteLater()
    def void(self):
        record=self.grid.selected()
        if record and QMessageBox.warning(self,'납부·완료 취소','연결된 가계부 지출 또는 비용 없는 차량 기록과 첨부파일도 삭제됩니다. 예정 상태로 되돌릴까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.void_household_vehicle_obligation(self.key,record['id']);self.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'취소 실패',str(exc))
    def wipe(self):self.grid.fill([])
    def reject(self):self.wipe();super().reject()
