"""Small, welcoming encrypted planning panels; all tables print/export normally."""
from datetime import date
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox,QFrame,QHBoxLayout,QLabel,QMessageBox,QProgressBar,QSpinBox,QTabWidget,QVBoxLayout,QWidget

from .household_planning import ASSET_TYPES,EXPENSE_GROUPS,REPORTS
from .widgets import DataGrid,FormDialog,action,date_field,won
from .household_finance_ui import MoneyChart,account_choices
from .menu_icons import menu_icon


class HouseholdPlanningTabs(QTabWidget):
    def __init__(self, finances):
        super().__init__(finances);self.finances=finances;self.book=finances.book;self.store=self.book.store;self.key=self.book.key
        self.setDocumentMode(True);self.setStyleSheet('QTabBar::tab{padding:10px 15px;margin:2px;border-radius:8px;}QTabBar::tab:selected{background:#E2EEE8;color:#315F4A;}')
        overview,layout=self.panel('재무상태표','wallet')
        self.cards=[];cards=QHBoxLayout()
        for title,color in [('자산','#E4F0E6'),('부채','#F7E5E5'),('순자산','#E9E5F5')]:
            frame=QFrame();frame.setObjectName('cashCard');stack=QVBoxLayout(frame);label=QLabel(title);label.setPixmap(menu_icon('wallet' if title!='부채' else 'money').pixmap(24,24));stack.addWidget(label)
            value=QLabel();value.setWordWrap(True);value.setStyleSheet('font-size:18px;font-weight:700;padding:8px;');stack.addWidget(QLabel(title));stack.addWidget(value);cards.addWidget(frame);self.cards.append(value)
        layout.addLayout(cards);self.liquidity=QLabel();self.liquidity.setWordWrap(True);layout.addWidget(self.liquidity)
        self.assets=DataGrid(['종류','이름','분류','평가일','금액','메모']);layout.addWidget(self.assets,1)
        row=QHBoxLayout()
        for name,fn in [('자산 등록',lambda:self.editor('asset')),('부채 등록',lambda:self.editor('debt')),('수정',lambda:self.edit(self.assets)),('삭제',lambda:self.remove(self.assets))]:row.addWidget(action(name,fn))
        layout.addLayout(row)
        self.asset_chart=MoneyChart('pie',title='현금성·묶인 자산 구성');layout.addWidget(self.asset_chart)
        self.note(layout,'통장 잔액은 자동 합산합니다. 이미 통장에 등록한 예금·대출을 다시 자산·부채에 등록하지 마세요. 수동 평가액은 최신 입력값이며 과거 시세·이전 평가액을 재현하지 않습니다. 마이너스 통장 잔액은 부채로 분리합니다.')
        goals,layout=self.panel('목돈 목표','goal')
        self.goals=DataGrid(['목표','목표일','목표액','모은 금액','남은 금액','달성률','월 필요 저축','상태']);layout.addWidget(self.goals,1)
        self.goal_progress=QProgressBar();self.goal_progress.setRange(0,10000);layout.addWidget(self.goal_progress)
        self.goals.itemSelectionChanged.connect(self.goal_changed)
        row=QHBoxLayout()
        for name,fn in [('목표 추가',lambda:self.editor('goal')),('목표 수정',lambda:self.edit(self.goals)),('목표 삭제',lambda:self.remove(self.goals))]:row.addWidget(action(name,fn))
        layout.addLayout(row);self.note(layout,'통장과 연결하면 잔액으로 달성률을 계산합니다. 연결하지 않으면 직접 모은 금액을 입력합니다. 목표 금액은 자산에 중복 합산하지 않으며 이자·투자수익은 가정하지 않습니다.')
        budgets,layout=self.panel('항목별 예산','category')
        self.budgets=DataGrid(['월','분류','예산','실제 지출','남은 예산','사용률']);layout.addWidget(self.budgets,1)
        row=QHBoxLayout()
        for name,fn in [('분류 예산 추가',lambda:self.editor('category_budget')),('예산 수정',lambda:self.edit(self.budgets)),('예산 삭제',lambda:self.remove(self.budgets)),('월 전체 예산',self.month_budget)]:row.addWidget(action(name,fn))
        layout.addLayout(row);self.note(layout,'분류 예산은 해당 월 1일부터 조회 종료일까지의 같은 분류 지출과 비교합니다. 월 전체 예산과 별개이며 자동으로 합산하거나 덮어쓰지 않습니다. 조회 기간에 포함된 월을 표시합니다.')
        annual,layout=self.panel('월·연간 결산','report')
        row=QHBoxLayout();self.year=QSpinBox();self.year.setRange(1900,9998);self.year.setValue(date.today().year);self.year.valueChanged.connect(lambda *_:self.refresh());row.addWidget(QLabel('연도'));row.addWidget(self.year);row.addWidget(action('결산 조회',self.refresh));row.addStretch();layout.addLayout(row)
        self.annual=DataGrid(['월','수입','지출','수지 차액','고정비','변동비','전체 예산','예산 잔액']);layout.addWidget(self.annual,1)
        self.annual_chart=MoneyChart('bar',title='월별 수지 차액 · 수입 − 지출',keep_order=True);layout.addWidget(self.annual_chart)
        self.annual_chart.setMinimumHeight(325)
        self.annual_total=QLabel();self.annual_total.setWordWrap(True);layout.addWidget(self.annual_total)
        self.note(layout,'이체·시작 잔액·수동 자산 평가는 수입과 지출에서 제외합니다. 1~12월의 직접 입력된 기록을 집계합니다. 고정비는 자동 고정비 규칙에서 생성된 지출입니다.')
        cashflow,layout=self.panel('생활비·현금흐름','money')
        self.cashflow=DataGrid(['생활비 구분','지출액']);layout.addWidget(self.cashflow,1)
        self.living=QLabel();self.living.setWordWrap(True);layout.addWidget(self.living)
        self.groups=DataGrid(['분류','생활비 구분','메모']);layout.addWidget(self.groups,1)
        row=QHBoxLayout()
        for name,fn in [('분류 구분 설정',lambda:self.editor('category_group')),('구분 수정',lambda:self.edit(self.groups)),('구분 삭제',lambda:self.remove(self.groups))]:row.addWidget(action(name,fn))
        layout.addLayout(row);self.note(layout,'FP114 설명서의 생활비 정의를 참고했습니다. 필요생활비=총지출−세금·사회보험−저축·투자·보장보험 / 순생활비=필요생활비−교육비. 분류별 구분을 직접 설정할 수 있습니다. 자산 이체는 지출이 아닙니다.')
        forecast,layout=self.panel('미래 잔액 예상','report')
        self.forecast=DataGrid(['미래 월','예상 정기 수입','예정 고정 지출','예상 통장 합계']);layout.addWidget(self.forecast,1)
        self.forecast_chart=MoneyChart('bar',title='앞으로의 통장 잔액 예상',keep_order=True);layout.addWidget(self.forecast_chart)
        self.forecast_chart.setMinimumHeight(325)
        layout.addWidget(action('예상 월 수입 설정',lambda:self.editor('forecast',next(iter(self.store.household_plans(self.key,'forecast')),None))))
        self.note(layout,'오늘의 통장 합계에 다음 달부터 12개월의 예상 수입과 활성 고정비만 적용한 단순 시나리오입니다. 현재 월의 남은 기간·변동비·미등록 카드대금·금리·투자수익은 제외되므로 실제 잔액과 다릅니다. 실제 거래를 생성하거나 송금하지 않습니다.')
        reports,layout=self.panel('맞춤 보고서','report')
        row=QHBoxLayout();self.report_type=QComboBox()
        for key,title in REPORTS.items():self.report_type.addItem(title,key)
        row.addWidget(self.report_type,1);self.preset=QComboBox();row.addWidget(self.preset,1)
        row.addWidget(action('설정 적용',self.apply_preset));row.addWidget(action('설정 저장·수정',self.save_preset));row.addWidget(action('설정 삭제',self.delete_preset));row.addWidget(action('조회',self.refresh));layout.addLayout(row)
        self.report_grid=DataGrid(['수입·지출','묶음','금액','거래 횟수']);layout.addWidget(self.report_grid,1)
        self.report_chart=MoneyChart('pie',title='조회 결과의 지출 구성');layout.addWidget(self.report_chart)
        self.report_summary=QLabel();self.report_summary.setWordWrap(True);layout.addWidget(self.report_summary)
        layout.addWidget(action('선택 묶음 세부 거래',self.report_details));self.report_grid.cellDoubleClicked.connect(lambda *_:self.report_details())
        self.note(layout,'상단 기간·통장·분류·검색 조건을 적용합니다. 시작 잔액과 통장 간 이체는 수입·지출 순위에서 제외합니다. 태그는 거래 하나에 여러 개일 수 있어 태그별 금액을 합산하면 중복될 수 있습니다. 합계는 실제 거래를 한 번씩 집계합니다.')
        templates,layout=self.panel('자주 쓰는 거래틀','worklog')
        self.templates=DataGrid(['이름','구분','분류','내용','금액','거래처','메모']);layout.addWidget(self.templates,1)
        row=QHBoxLayout()
        for name,fn in [('거래틀 추가',lambda:self.editor('template')),('거래틀 수정',lambda:self.edit(self.templates)),('거래틀 삭제',lambda:self.remove(self.templates)),('선택 틀로 입력',self.apply_template)]:row.addWidget(action(name,fn))
        layout.addLayout(row);self.note(layout,'거래틀을 선택하면 입력 창에 내용을 채워 줍니다. 날짜·금액·통장을 확인하고 저장해야 실제 거래가 생깁니다. 금액이 매번 다르면 틀의 금액을 0원으로 두고 입력할 때 바꾸세요.')
        self.report_type.currentIndexChanged.connect(lambda *_:self.refresh())

    def panel(self,title,icon):
        widget=QWidget();layout=QVBoxLayout(widget);self.addTab(widget,menu_icon(icon),title);return widget,layout

    def note(self,layout,text):
        label=QLabel(text);label.setWordWrap(True);label.setStyleSheet('font-size:11px;color:#788578;padding:8px;');layout.addWidget(label)

    def refresh(self):
        start=self.book.start.date().toString('yyyy-MM-dd');end=self.book.end.date().toString('yyyy-MM-dd')
        data=self.store.household_financial_overview(self.key,start,end)
        for control,key in zip(self.cards,('asset_total','debt_total','net_assets')):control.setText(won(data[key])+'원')
        self.liquidity.setText('현금성 '+won(data['cash_assets'])+'원  ·  예·적금·부동산 등 '+won(data['locked_assets'])+'원  ·  통장 잔액은 조회 종료일 기준')
        rows=data['valuations'];self.assets.fill([['자산' if r['kind']=='asset' else '부채',r['name'],ASSET_TYPES[r['asset_type']] if r['kind']=='asset' else '대출·미납 등',r['date'],r['amount'],r['memo']] for r in rows],rows)
        self.asset_chart.set_values([('현금성',data['cash_assets']),('묶인 자산',data['locked_assets'])])
        rows=data['goals'];self.goals.fill([[r['name'],r['target_date'],r['amount'],r['saved_amount'],r['gap'],str(r['percent'])+'%',r['monthly_saving'],'기한 지남' if r['overdue'] else '달성' if not r['gap'] else '진행 중'] for r in rows],rows);self.goal_changed()
        rows=data['category_budgets'];self.budgets.fill([[r['month'],r['name'],r['amount'],r['expense_total'],r['available_total'],str(r['percent'])+'%' if r['percent'] is not None else '예산 0원'] for r in rows],rows)
        rows=self.store.household_annual_report(self.key,self.year.value());self.annual.fill([[r[k] for k in ('month','income_total','expense_total','balance','fixed_total','variable_total','budget_total','available_total')] for r in rows],rows)
        self.annual_chart.set_values([(r['month'][5:]+'월',r['balance']) for r in rows])
        self.annual_total.setText(f"{self.year.value()}년 수입 {won(sum(r['income_total'] for r in rows))}원 · 지출 {won(sum(r['expense_total'] for r in rows))}원 · 수지 차액 {won(sum(r['balance'] for r in rows))}원")
        self.cashflow.fill([[r['name'],r['amount']] for r in data['expense_groups']],data['expense_groups'])
        self.living.setText('필요생활비 '+won(data['necessary_total'])+'원  ·  순생활비 '+won(data['living_total'])+'원')
        rows=self.store.household_plans(self.key,'category_group');self.groups.fill([[r['name'],EXPENSE_GROUPS[r['group']],r['memo']] for r in rows],rows)
        rows=self.store.household_cash_forecast(self.key,date.today().isoformat());self.forecast.fill([[r['month'],r['income_total'],r['expense_total'],r['projected_balance']] for r in rows],rows)
        self.forecast_chart.set_values([(r['month'][2:],r['projected_balance']) for r in rows])
        old=self.preset.currentData();self.preset.clear();self.preset.addItem('저장한 보고서 설정',None)
        for r in self.store.household_plans(self.key,'report_preset'):self.preset.addItem(r['name'],r['id'])
        self.preset.setCurrentIndex(max(0,self.preset.findData(old)))
        rows=self.store.household_plans(self.key,'template');self.templates.fill([[r['name'],'수입' if r['entry_kind']=='income' else '지출',r['category'],r['title'],r['amount'],r['payee'],r['memo']] for r in rows],rows)
        report=self.store.household_custom_report(self.key,start,end,self.report_type.currentData(),self.book.account.currentData(),self.book.category.currentData() or '',self.book.search.text())
        self.report_grid.fill([['수입' if r['kind']=='income' else '지출',r['name'],r['amount'],r['count']] for r in report['rows']],report['rows'])
        self.report_chart.set_values([(r['name'],r['amount']) for r in report['rows'] if r['kind']=='expense'])
        self.report_summary.setText('수입 '+won(report['income_total'])+'원 · 지출 '+won(report['expense_total'])+'원 · 수지 차액 '+won(report['balance'])+'원')
        self._report_entries=report['entries']

    def goal_changed(self):
        row=self.goals.selected();percent=row['percent'] if row else Decimal(0);self.goal_progress.setValue(min(10000,int(percent*100)));self.goal_progress.setFormat(f'{percent:.2f}% 달성' if row else '목표를 선택해 보세요')

    def active_grid(self):return [self.assets,self.goals,self.budgets,self.annual,self.cashflow,self.forecast,self.report_grid,self.templates][self.currentIndex()]

    def report_details(self):
        row=self.report_grid.selected()
        if not row:return
        from PySide6.QtWidgets import QDialog
        d=QDialog(self);d.setWindowTitle('선택 묶음 세부 거래');d.resize(900,560);layout=QVBoxLayout(d)
        grid=DataGrid(['날짜','통장','분류','내용','금액','거래처','메모']);layout.addWidget(grid)
        rows=[r for r in self._report_entries if r['id'] in row['entry_ids']]
        grid.fill([[r['date'],r['account_name'],r['category'],r['title'],r['amount'],r.get('payee',''),r['memo']] for r in rows])
        tools=QHBoxLayout();tools.addWidget(action('엑셀 저장',lambda:grid.export(d,'가계부 세부 거래')));tools.addWidget(action('인쇄·PDF',lambda:grid.print_pages(d,'가계부 세부 거래')));tools.addWidget(action('닫기',d.reject));layout.addLayout(tools)
        try:d.exec()
        finally:grid.fill([]);rows.clear();d.deleteLater()

    def apply_preset(self):
        r=next((r for r in self.store.household_plans(self.key,'report_preset') if r['id']==self.preset.currentData()),None)
        if not r:return
        self.book.search.setText(r['search']);self.book.account.setCurrentIndex(max(0,self.book.account.findData(r['account_id'])));self.book.category.setCurrentIndex(max(0,self.book.category.findData(r['category'] or None)))
        self.report_type.blockSignals(True);self.report_type.setCurrentIndex(self.report_type.findData(r['view']));self.report_type.blockSignals(False);self.book.refresh()

    def save_preset(self):
        existing=next((r for r in self.store.household_plans(self.key,'report_preset') if r['id']==self.preset.currentData()),None)
        d=FormDialog('현재 보고서 조건 저장',self);name=d.field('name','설정 이름',(existing or {}).get('name',''))
        def save():
            try:self.store.save_household_plan(self.key,dict(kind='report_preset',name=name.text(),view=self.report_type.currentData(),search=self.book.search.text(),category=self.book.category.currentData() or '',account_id=self.book.account.currentData()),(existing or {}).get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.finances.private_exec(d):self.refresh()

    def delete_preset(self):
        identifier=self.preset.currentData()
        if identifier and QMessageBox.question(self,'보고서 설정 삭제','선택한 보고서 설정만 삭제할까요? 거래 내역은 남습니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_household_plan(self.key,identifier);self.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'설정 삭제',str(exc))

    def apply_template(self):
        row=self.templates.selected()
        if row:self.book.editor(initial=dict(kind=row['entry_kind'],title=row['title'],category=row['category'],amount=row['amount'] if row['amount'] else '',memo=row['memo'],payee=row['payee']))

    def month_budget(self):
        month=self.book.end.date().toString('yyyy-MM');d=FormDialog('월 전체 예산',self);d.resize(520,340)
        value=d.field('month','월 (YYYY-MM)',month);amount=d.field('amount','전체 예산 (원)','')
        def save():
            try:self.store.save_household_budget(self.key,value.text(),amount.text());d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.finances.private_exec(d):self.book.refresh()

    def edit(self,grid):
        row=grid.selected()
        if row:self.editor(row['kind'],row)

    def remove(self,grid):
        row=grid.selected()
        if row and QMessageBox.question(self,'계획 삭제','선택한 계획·평가 기록을 삭제할까요? 실제 수입·지출 기록은 삭제되지 않습니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            try:self.store.delete_household_plan(self.key,row['id']);self.book.refresh()
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'계획 삭제',str(exc))

    def editor(self,kind,record=None):
        r=record or {};d=FormDialog({'asset':'자산 평가','debt':'부채 잔액','goal':'목돈 목표','category_budget':'분류별 예산','category_group':'생활비 구분','forecast':'예상 월 수입','template':'자주 쓰는 거래틀'}[kind],self);d.resize(640,580)
        name=d.field('name','분류명' if kind.startswith('category') else '이름',r.get('name','예상 월 수입' if kind=='forecast' else ''))
        amount=d.field('amount','목표액 (원)' if kind=='goal' else '월 예상 수입 (원)' if kind=='forecast' else '금액 (원)',r.get('amount','0.00'))
        controls={}
        if kind in {'asset','debt'}:
            controls['date']=date_field(r.get('date'));d.form.addRow('평가일',controls['date'])
            controls['asset_type']=d.combo('type','자산 종류',[(v,k) for k,v in ASSET_TYPES.items()],r.get('asset_type','other'));controls['asset_type'].setVisible(kind=='asset')
            self.note(d.body,'통장 잔액에 포함된 금액은 중복 등록하지 마세요. 부채 금액은 남은 원금·미납액을 양수로 입력합니다. 상환 기록만으로 이 잔액이 자동 변경되지 않습니다.')
        elif kind=='goal':
            controls['target_date']=date_field(r.get('target_date'));d.form.addRow('목표일',controls['target_date'])
            controls['saved_amount']=d.field('saved','직접 모은 금액 (통장 연결 시 무시)',r.get('saved_amount','0.00'))
            controls['account_id']=d.combo('account','연결 통장',[('직접 금액 입력','')]+[(a['name'],a['id']) for a in self.store.household_accounts(self.key)],r.get('account_id',''))
        elif kind=='category_budget':controls['month']=d.field('month','예산 월 (YYYY-MM)',r.get('month',self.book.end.date().toString('yyyy-MM')))
        elif kind=='category_group':
            amount.setVisible(False);controls['group']=d.combo('group','구분',[(v,k) for k,v in EXPENSE_GROUPS.items()],r.get('group','living'))
        elif kind=='template':
            controls['entry_kind']=d.combo('entry_kind','구분',[('지출','expense'),('수입','income')],r.get('entry_kind','expense'))
            for key,label,default in [('category','분류','기타'),('title','거래 내용',''),('payee','거래처','')]:controls[key]=d.field(key,label,r.get(key,default))
        memo=d.field('memo','메모',r.get('memo',''))
        def save():
            data=dict(kind=kind,name=name.text(),amount='0' if kind=='category_group' else amount.text(),memo=memo.text())
            for key,widget in controls.items():
                data[key]=widget.currentData() if isinstance(widget,QComboBox) else widget.date().toString('yyyy-MM-dd') if hasattr(widget,'date') else widget.text()
            try:self.store.save_household_plan(self.key,data,r.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if self.finances.private_exec(d):self.book.refresh()

    def wipe(self):
        for grid in self.findChildren(DataGrid):grid.fill([])
        for chart in (self.asset_chart,self.annual_chart,self.forecast_chart,self.report_chart):chart.set_values([])
        for label in self.cards+[self.liquidity,self.living,self.annual_total,self.report_summary]:label.clear()
        self._report_entries=[];self.preset.clear()
        self.goal_progress.setValue(0);self.goal_progress.setFormat('')
