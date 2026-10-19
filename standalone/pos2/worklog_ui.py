"""PDF-inspired work diary and logistics dashboard, with manual-only metrics."""
from datetime import date
from collections import defaultdict
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox,QComboBox,QDialog,QHBoxLayout,QLabel,QLineEdit,QMenu,QMessageBox,QTabWidget,QTableWidget,QTableWidgetItem,QTextEdit,QVBoxLayout,QWidget
from .widgets import Page,DataGrid,FormDialog,action,date_field,won
from .worklog import ACTIVITIES,STATUSES
from .menu_icons import menu_icon
from .household_finance_ui import MoneyChart


class WorkLogPage(Page):
    def __init__(self,window):
        super().__init__(window,'업무일지 · 물류 업무 현황','일반 업무와 물류 통계를 함께 기록합니다. 현재 계정의 기록만 표시하며, 매입·판매 전표나 재고를 자동 변경하지 않습니다.')
        self.menu_key='worklog';row=QHBoxLayout();self.start,self.end=date_field(date.today().replace(day=1)),date_field();self.search=QLineEdit();self.search.setPlaceholderText('제목 · 업무 내용 검색')
        for c in (self.start,QLabel('~'),self.end,self.search):row.addWidget(c)
        self.status=QComboBox();self.status.addItem('전체 처리 상태','')
        for k,v in STATUSES.items():self.status.addItem(v,k)
        row.addWidget(self.status)
        for title,fn in [('조회',self.refresh),('새 업무일지',self.add),('수정',self.edit),('사진·문서 첨부',self.attach)]:row.addWidget(action(title,fn))
        self.body.addLayout(row);self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setStyleSheet('background:#E8F1EB;border-radius:12px;padding:16px;font-size:16px;');self.body.addWidget(self.summary)
        self.tabs=QTabWidget();self.body.addWidget(self.tabs,1)
        first=QWidget();layout=QVBoxLayout(first);self.tabs.addTab(first,menu_icon('worklog'),'업무·인수인계')
        self.grid=DataGrid(['날짜·요일','상태','구분','고객사','제목','인수인계','특이사항','수정 시각']);layout.addWidget(self.grid,1);self.grid.cellDoubleClicked.connect(lambda *_:self.edit());self.grid.itemSelectionChanged.connect(self.selection_changed)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);self.grid.customContextMenuRequested.connect(self.context_menu)
        second=QWidget();layout=QVBoxLayout(second);self.tabs.addTab(second,menu_icon('report'),'일·주·요일 통계')
        self.mode=QComboBox();self.mode.addItems(['일별','주간','요일별']);self.mode.currentIndexChanged.connect(lambda *_:self.refresh());layout.addWidget(self.mode)
        self.statistics=DataGrid(['기간','기록 수','매출 입력액','비용 입력액','관리 손익','작업시간(h)']);layout.addWidget(self.statistics,1)
        self.chart=MoneyChart('bar',title='기간별 관리 손익 · 입력 자료 기준',keep_order=True);layout.addWidget(self.chart)
        third=QWidget();layout=QVBoxLayout(third);self.tabs.addTab(third,menu_icon('inventory'),'물동량·생산성')
        self.metrics=QLabel();self.metrics.setWordWrap(True);layout.addWidget(self.metrics)
        self.productivity=DataGrid(['작업','단위','작업량','소요시간(h)','시간당 작업량','작업 1단위당 분']);layout.addWidget(self.productivity,1)
        help_label=QLabel('업무·인수인계 탭에서 일지를 선택하면 보관율·생산성을 표시합니다. EA·BOX·PLT를 서로 더하거나 같은 단위로 간주하지 않습니다.\n시급과 잔업 배율은 직접 입력하며 급여·청구를 확정하는 기능이 아닙니다. 보관 통계는 해당 일지의 스냅샷으로 기간 합산하지 않습니다.');help_label.setWordWrap(True);layout.addWidget(help_label)
        controls=QHBoxLayout()
        for title,fn in [('삭제',self.delete),('엑셀 저장',lambda:self.active_grid().export(self,'업무일지')),('인쇄·PDF',lambda:self.active_grid().print_pages(self,'업무일지',self.summary.text()))]:controls.addWidget(action(title,fn))
        self.body.addLayout(controls);note=QLabel('업무일지와 첨부파일은 별도 암호화되지 않습니다. 민감한 개인 기록은 보안 일기장을 이용하세요. 통계는 완료·예정·보류 상태를 포함한 관리용 입력값입니다.');note.setWordWrap(True);self.body.addWidget(note)
        self.status.setToolTip('기록은 유지하면서 예정·진행·완료·보류만 골라 봅니다.');self.mode.setToolTip('같은 기록을 날짜·주간·요일로 묶습니다. 빈 날짜를 근무일로 가정하지 않습니다.')

    def active_grid(self):return (self.grid,self.statistics,self.productivity)[self.tabs.currentIndex()]

    def refresh(self):
        try:
            report=self.store.work_log_report(self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'))
            rows=[r for r in report['records'] if (not self.status.currentData() or r['details']['status']==self.status.currentData()) and (not self.search.text() or self.search.text().casefold() in (r['title']+r['body']).casefold())]
            self.grid.fill([[r['date']+' '+('월화수목금토일'[date.fromisoformat(r['date']).weekday()])+'요일',STATUSES[r['details']['status']],r['details']['category'],r['details']['customer'],r['title'],r['details']['handover'],r['details']['issue'],r['updated_at']] for r in rows],rows)
            revenue=sum(r['metrics']['revenue_total'] for r in rows);cost=sum(r['metrics']['total_cost'] for r in rows);days={r['date'] for r in rows if r['details']['working_day']}
            self.summary.setText(f"기록 {len(rows)}건 · 근무 {len(days)}일 · 완료 {sum(r['details']['status']=='done' for r in rows)}건\n매출 입력 {won(revenue)}원 · 비용 {won(cost)}원 · 관리 손익 {won(revenue-cost)}원")
            grouped={}
            for r in rows:
                when=date.fromisoformat(r['date']);iso=when.isocalendar();label=r['date'] if self.mode.currentIndex()==0 else f'{iso.year}-W{iso.week:02}' if self.mode.currentIndex()==1 else str(when.weekday()+1)+' · '+'월화수목금토일'[when.weekday()]+'요일'
                bucket=grouped.setdefault(label,[0,Decimal(0),Decimal(0),Decimal(0),Decimal(0)]);bucket[0]+=1
                for i,k in enumerate(('revenue_total','total_cost','profit','total_hours'),1):bucket[i]+=r['metrics'][k]
            values=sorted(grouped.items());self.statistics.fill([[k,*v] for k,v in values]);self.chart.set_values([(k,v[3]) for k,v in values]);self.selection_changed()
        except (ValueError,PermissionError) as exc:self.fail(exc)

    def selection_changed(self):
        row=self.grid.selected()
        if not row:self.productivity.fill([]);self.metrics.clear();return
        r=row['metrics'];self.metrics.setText(f"{row['date']} · {row['title']}\n작업자 {r['workers']}명 · {r['total_hours']}시간 · 인건비 {won(r['labor_cost'])}원 · 보관율 "+(str(r['occupancy'])+'%' if r['occupancy'] is not None else '보관 CAPA 미입력')+f" · 추가 보관 가능 {r['remaining_capacity']} PLT")
        self.productivity.fill([[v['activity'],v['unit'],v['qty'],v['hours'],v['per_hour'] if v['per_hour'] is not None else '시간 미입력',v['minutes_per_touch'] if v['minutes_per_touch'] is not None else '수량 0'] for v in r['productivity']])

    def context_menu(self,position):
        index=self.grid.indexAt(position)
        if index.isValid():self.grid.selectRow(index.row())
        menu=QMenu(self);menu.addAction('새 업무일지',self.add)
        if self.grid.selected():
            for title,fn in [('선택 일지 수정',self.edit),('사진·문서 첨부',self.attach),('생산성 보기',lambda:self.tabs.setCurrentIndex(2)),('일지 삭제',self.delete)]:menu.addAction(title,fn)
        self._context=menu;menu.popup(self.grid.viewport().mapToGlobal(position))

    def editor(self,record=None):
        r=record or {};details=self.store.work_log_detail(r['id']) if r else {};d=FormDialog('업무일지 등록정보',self);d.resize(1050,800)
        title=d.field('title','제목 *',r.get('title',''));when=date_field(r.get('date'));d.form.addRow('업무일',when)
        status=d.combo('status','상태',[(v,k) for k,v in STATUSES.items()],details.get('status','active'));category=d.field('category','업무 구분',details.get('category','일반업무'));customer=d.field('customer','고객사·거래처',details.get('customer',''))
        working=QCheckBox('근무일로 집계');working.setChecked(details.get('working_day',True));d.form.addRow(working)
        tabs=QTabWidget();d.body.addWidget(tabs,1)
        def panel(title):
            widget=QWidget();layout=QVBoxLayout(widget);tabs.addTab(widget,menu_icon(title),title);return layout
        layout=panel('업무·인수인계');body=QTextEdit();body.setPlainText(r.get('body',''));body.setPlaceholderText('오늘 처리한 일과 확인할 일을 기록하세요.');layout.addWidget(body)
        handover=QTextEdit();handover.setPlainText(details.get('handover',''));handover.setPlaceholderText('인수인계 · 다음 근무자가 확인할 내용');layout.addWidget(handover)
        issue=QLineEdit(details.get('issue',''));issue.setPlaceholderText('사고·안전·특이사항');layout.addWidget(issue)
        layout=panel('작업량·생산성');moves=QTableWidget(max(10,len(details.get('movements',[]))+3),4);moves.setHorizontalHeaderLabels(['작업 구분','EA / BOX / PLT','작업 수량','해당 작업 소요시간(h)']);layout.addWidget(moves)
        for i,row in enumerate(details.get('movements',[])):
            for c,k in enumerate(('activity','unit','qty','hours')):moves.setItem(i,c,QTableWidgetItem(str(row[k])))
        note=QLabel('작업 구분: '+', '.join(ACTIVITIES)+'\n75분=1.25시간. 단위별·작업별 수량과 시간을 별도 입력하며 섞어서 합산하지 않습니다.');note.setWordWrap(True);layout.addWidget(note)
        layout=panel('작업인원');workers=QTableWidget(max(8,len(details.get('workers',[]))+3),7);workers.setHorizontalHeaderLabels(['작업자','정규/임시/지원','정규시간(h)','잔업시간(h)','시급(원)','잔업 배율','비고(저장 제외)']);layout.addWidget(workers)
        names={'regular':'정규','temporary':'임시','support':'지원'}
        for i,row in enumerate(details.get('workers',[])):
            for c,k in enumerate(('name','kind','regular_hours','overtime_hours','hourly_rate','overtime_factor')):workers.setItem(i,c,QTableWidgetItem(names[row[k]] if k=='kind' else str(row[k])))
        note=QLabel('급여 지급 기준의 정규·잔업 시간을 따로 기록합니다. 휴식 포함 여부는 실제 기준에 맞게 입력하세요.\n인건비=정규시간×시급+잔업시간×시급×입력 배율. 계약·법정 수당을 자동 판단하지 않습니다.');note.setWordWrap(True);layout.addWidget(note)
        layout=panel('매출·비용·보관');fields={}
        for key,label in [('handling_revenue','하역·입출고 매출'),('storage_revenue','보관 매출'),('extra_revenue','추가작업 매출'),('rent_cost','해당일 임대비'),('management_cost','해당일 관리비'),('other_cost','기타 비용'),('capacity','최대 보관량(PLT)'),('occupied','현재 보관량(PLT)'),('optimal_percent','적정 보관율(%)')]:
            row=QHBoxLayout();row.addWidget(QLabel(label));field=QLineEdit(str(details.get(key,85 if key=='optimal_percent' else 0)));fields[key]=field;row.addWidget(field);layout.addLayout(row)
        note=QLabel('매출은 실제 작업량과 별개인 계약·청구 기준으로 계산한 금액을 입력하세요. 입력한 비용·매출은 POS 전표·재고·가계부에 자동 전기하지 않습니다.');note.setWordWrap(True);layout.addWidget(note)
        def table_rows(table,keys):
            return [dict(zip(keys,[(table.item(i,c).text().strip() if table.item(i,c) else '') for c in range(len(keys))])) for i in range(table.rowCount()) if any(table.item(i,c) and table.item(i,c).text().strip() for c in range(len(keys)))]
        def save():
            values={k:v.text() for k,v in fields.items()};values.update(status=status.currentData(),category=category.text(),customer=customer.text(),working_day=working.isChecked(),handover=handover.toPlainText(),issue=issue.text())
            values['movements']=table_rows(moves,('activity','unit','qty','hours'));values['workers']=table_rows(workers,('name','kind','regular_hours','overtime_hours','hourly_rate','overtime_factor'))
            for worker in values['workers']:
                worker['kind']={'정규':'regular','임시':'temporary','지원':'support'}.get(worker['kind'],worker['kind']) or 'regular'
                for key in ('regular_hours','overtime_hours','hourly_rate'):worker[key]=worker[key] or '0'
                worker['overtime_factor']=worker['overtime_factor'] or '1.5'
            for movement in values['movements']:
                movement['hours']=movement['hours'] or '0';movement['qty']=movement['qty'] or '0'
            try:self.store.save_work_log(dict(date=when.date().toString('yyyy-MM-dd'),title=title.text(),body=body.toPlainText(),details=values),r.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if d.exec():self.refresh()
        d.deleteLater()

    def add(self):self.editor()
    def edit(self):
        row=self.grid.selected()
        if row:self.editor(row)
    def delete(self):
        row=self.grid.selected()
        if row and QMessageBox.question(self,'업무일지 삭제','선택한 업무일지와 첨부 복사본을 삭제할까요? 원본 파일은 삭제하지 않습니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_work_log(row['id']);self.refresh()
            except (ValueError,PermissionError) as exc:self.fail(exc)
    def attach(self):
        row=self.grid.selected()
        if not row:return
        from .attachment_ui import AttachmentDialog
        class Adapter:
            def personal_attachments(_,key,kind,rt,identifier):return self.store.work_log_files(identifier)
            def add_personal_attachment(_,key,kind,rt,identifier,name,payload):return self.store.add_work_log_file(identifier,name,payload)
            def personal_attachment_data(_,key,kind,rt,identifier,file_id):return self.store.work_log_file_data(identifier,file_id)
            def delete_personal_attachment(_,key,kind,rt,identifier,file_id):return self.store.delete_work_log_file(identifier,file_id)
        d=AttachmentDialog(Adapter(),None,'worklog','entry',row['id'],self)
        for label in d.findChildren(QLabel):
            if '암호화하여' in label.text():label.setText('사진·문서 복사본을 업무 장부에 보관하고 백업에도 포함합니다. 업무일지와 첨부는 별도 암호화되지 않습니다. 파일당 10MB·일지당 20개·사용자당 200MB입니다. 실행 파일은 허용하지 않으며 자동으로 열지 않습니다.')
        d.exec();d.wipe();d.deleteLater()
