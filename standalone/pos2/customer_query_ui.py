"""Reference customer filters with recent-first cap and bounded rendering."""
from datetime import date
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QKeySequence,QShortcut
from PySide6.QtWidgets import QCheckBox,QComboBox,QGridLayout,QHBoxLayout,QLabel,QLineEdit,QSpinBox,QVBoxLayout,QWidget
from .widgets import DataGrid,FormDialog,ScanField,action,date_field,won
from .member_registration import MEMBER_TYPES

HEADERS=['회원명','유형','ABC','바코드','사업자번호','전화번호','휴대폰','우편번호','기본주소','상세주소','도매등급','등급','그룹','등록일','최종거래','외상잔액','외상한도','포인트','상태']


class MemberGrid(DataGrid):
    all_export_rows=None
    def export_rows(self):
        return self.all_export_rows if self.all_export_rows is not None else super().export_rows()


class CustomerQuery(QWidget):
    def __init__(self,page):
        super().__init__(page);self.page=page;self.store=page.store;self.cache=None;self.revision=None;self.matches=[];self.offset=0
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        self.setStyleSheet('QLineEdit,QComboBox,QSpinBox,QDateEdit{min-height:18px;padding:3px;}')
        first=QHBoxLayout();first.addWidget(QLabel('검색어'));self.search=ScanField();self.search.setPlaceholderText('이름 · 회원번호 · 전화 · 사업자번호');first.addWidget(self.search,2)
        self.top=QCheckBox('상위');self.top.setChecked(True);self.top.setToolTip('최근 등록순입니다. 체크 해제하면 조건에 맞는 전체 회원을 조회합니다.')
        self.limit=QSpinBox();self.limit.setRange(1,100000);self.limit.setValue(100);self.limit.setMaximumWidth(85);first.addWidget(self.top);first.addWidget(self.limit)
        self.staff=QCheckBox('담당자');self.staff_name=QLineEdit();self.staff_name.setMaximumWidth(130);first.addWidget(self.staff);first.addWidget(self.staff_name);first.addStretch()
        first.addWidget(action('새 회원등록',page.add,primary=True));layout.addLayout(first)
        options=QHBoxLayout();self.status=QComboBox()
        for title,value in (('유효',1),('상태 전체',None),('무효',0)):self.status.addItem(title,value)
        self.kind=QComboBox();self.kind.addItem('회원유형 전체','')
        for name in MEMBER_TYPES:self.kind.addItem(name,name)
        self.wholesale=QComboBox();self.wholesale.addItem('도매등급 전체','')
        self.abc=QComboBox();self.abc.addItem('ABC 전체','')
        for value in ('A','B','C','D'):self.abc.addItem(value,value)
        self.grade=QComboBox();self.grade.addItem('등급 전체','')
        self.credit=QComboBox()
        for label,key in (('외상 전체',''),('외상 허용','allowed'),('외상 불가','denied'),('미수 회원','outstanding')):self.credit.addItem(label,key)
        self.group=QComboBox();self.group.addItem('그룹 전체','')
        for control in (self.status,self.kind,self.wholesale,self.abc,self.grade,self.credit,self.group):options.addWidget(control,1)
        layout.addLayout(options)
        dates=QGridLayout();self.ranges={}
        for index,(key,title) in enumerate((('created','등록'),('last','최종거래'),('birthday','생일'),('anniversary','기념일'))):
            row,col=divmod(index,2);col*=5
            enabled=QCheckBox(title);start=date_field(date.today().replace(day=1).isoformat());end=date_field()
            if key in {'birthday','anniversary'}:
                start.setDisplayFormat('MM-dd');end.setDisplayFormat('MM-dd');enabled.setToolTip('저장된 월·일 기준입니다. 연말~연초 범위를 지원하며 음력 날짜를 자동 환산하지 않습니다.')
            dates.addWidget(enabled,row,col);dates.addWidget(start,row,col+1);dates.addWidget(QLabel('~'),row,col+2);dates.addWidget(end,row,col+3)
            self.ranges[key]=(enabled,start,end);start.setEnabled(False);end.setEnabled(False)
            enabled.toggled.connect(start.setEnabled);enabled.toggled.connect(end.setEnabled);enabled.toggled.connect(self.options_changed)
        self.postcode=QLineEdit();self.postcode.setPlaceholderText('우편번호');self.postcode.setMaximumWidth(90)
        self.address=QLineEdit();self.address.setPlaceholderText('주소 검색')
        dates.addWidget(QLabel('우편'),0,9);dates.addWidget(self.postcode,0,10);dates.addWidget(QLabel('주소'),1,9);dates.addWidget(self.address,1,10);layout.addLayout(dates)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(250);self.timer.timeout.connect(page.refresh)
        for field in (self.search,self.staff_name,self.postcode,self.address):field.textChanged.connect(self.schedule)
        self.search.scanned.connect(lambda *_:page.refresh())
        for box in (self.status,self.kind,self.wholesale,self.abc,self.grade,self.credit,self.group):box.currentIndexChanged.connect(self.options_changed)
        self.top.toggled.connect(self.options_changed);self.staff.toggled.connect(self.options_changed);self.limit.valueChanged.connect(self.options_changed)
        self.pager=QWidget();pager=QHBoxLayout(self.pager);pager.setContentsMargins(0,0,0,0)
        self.previous=action('이전 500명',lambda:self.move(-1));self.next=action('다음 500명',lambda:self.move(1));self.summary=QLabel()
        pager.addWidget(self.previous);pager.addWidget(self.next);pager.addWidget(self.summary,1)
        self._shortcut=QShortcut(QKeySequence('F4'),page);self._shortcut.activated.connect(page.focus_scan)
    def schedule(self,*_):self.offset=0;self.timer.start()
    def options_changed(self,*_):
        self.offset=0
        if hasattr(self.page,'grid'):self.page.refresh()
    def choices(self,combo,values):
        values=sorted(set(v for v in values if v));current=combo.currentData()
        if values==[combo.itemData(i) for i in range(1,combo.count())]:return
        combo.blockSignals(True)
        while combo.count()>1:combo.removeItem(1)
        for value in values:combo.addItem(value,value)
        combo.setCurrentIndex(max(0,combo.findData(current)));combo.blockSignals(False)
    def filtered(self):
        revision=self.store.audit_revision()
        if self.cache is None or self.revision!=revision:
            self.cache=self.store.members();self.revision=revision
            for combo,key in ((self.wholesale,'wholesale_grade'),(self.grade,'grade')):self.choices(combo,[r['registration'][key] for r in self.cache])
            self.choices(self.group,[r.get('group_name','') for r in self.cache])
        term=self.search.text().strip().casefold();address=self.address.text().strip().casefold();postal=self.postcode.text().strip();rows=[]
        for record in self.cache:
            detail=record['registration']
            if self.status.currentData() is not None and record['active']!=self.status.currentData():continue
            if term and not any(term in str(record.get(k,'')).casefold() for k in ('name','code','mobile','phone','business_no','company','address','group_name')) and not any(term in str(detail.get(k,'')).casefold() for k in ('phone2','email')):continue
            if self.kind.currentData() and record['member_type']!=self.kind.currentData():continue
            if any(combo.currentData() and detail[key]!=combo.currentData() for combo,key in ((self.wholesale,'wholesale_grade'),(self.abc,'abc'),(self.grade,'grade'))):continue
            if self.group.currentData() and record['group_name']!=self.group.currentData():continue
            if self.staff.isChecked() and self.staff_name.text().strip().casefold() not in detail['staff_name'].casefold():continue
            if postal and not detail['postcode'].startswith(postal):continue
            if address and address not in (record['address']+' '+detail['address_detail']).casefold():continue
            selected=self.credit.currentData()
            if selected=='allowed' and not detail['credit_allowed'] or selected=='denied' and detail['credit_allowed'] or selected=='outstanding' and record['credit_balance']<=0:continue
            matched=True
            for key,(enabled,start,end) in self.ranges.items():
                if not enabled.isChecked():continue
                value=record.get({'created':'created_at','last':'last_trade','birthday':'birthday','anniversary':'anniversary'}[key],'')[:10]
                first,last=start.date().toString('yyyy-MM-dd'),end.date().toString('yyyy-MM-dd')
                if key in {'birthday','anniversary'}:
                    value,first,last=value[5:],first[5:],last[5:];valid=bool(value) and (first<=value<=last if first<=last else value>=first or value<=last)
                else:
                    if first>last:raise ValueError(f'{enabled.text()} 조회 시작일과 종료일을 확인하세요.')
                    valid=bool(value) and first<=value<=last
                if not valid:matched=False;break
            if matched:rows.append(record)
        rows.sort(key=lambda r:r['id'],reverse=True);self.total_matching=len(rows)
        return rows[:self.limit.value()] if self.top.isChecked() else rows
    def values(self,r):
        d=r['registration']
        return [r['name'],r['member_type'],d['abc'],r['code'],r['business_no'],r['phone'],r['mobile'],d['postcode'],r['address'],d['address_detail'],d['wholesale_grade'],d['grade'],r['group_name'],r['created_at'][:10],r['last_trade'],r['credit_balance'],d['credit_limit'],r['points'],'유효' if r['active'] else '무효']
    def refresh(self):
        self.timer.stop();previous=self.page.grid.selected();self.matches=self.filtered()
        self.offset=min(self.offset,max(0,(len(self.matches)-1)//500*500));records=self.matches[self.offset:self.offset+500]
        grid=self.page.grid;grid.blockSignals(True);grid.all_export_rows=[self.values(r) for r in self.matches];grid.fill([self.values(r) for r in records],records);grid.blockSignals(False)
        if records:grid.selectRow(next((i for i,r in enumerate(records) if previous and previous['id']==r['id']),0))
        self.previous.setEnabled(self.offset>0);self.next.setEnabled(self.offset+500<len(self.matches))
        self.summary.setText(f'조건 일치 {self.total_matching:,}명 / 조회 {len(self.matches):,}명 · 최근 등록순 · 표시 {self.offset+1 if records else 0:,}~{self.offset+len(records):,} · 엑셀/인쇄는 조회 전체');self.page.details()
    def move(self,direction):self.offset=max(0,self.offset+direction*500);self.page.refresh()


class MemberPaymentDialog(FormDialog):
    def __init__(self,store,member,parent=None):
        super().__init__(member['name']+' · 회원 외상 수금',parent);self.store=store
        records=[r for r in store.documents('sale',member_id=member['id'],status='posted') if r['balance']>0]
        if not records:raise ValueError('수금할 외상 잔액이 없습니다.')
        self.document=self.combo('document','수금할 판매전표',[(f"{r['date']} · {r['number']} · 미수 {won(r['balance'])}",r['id']) for r in records])
        self.value=self.field('amount','수금액 (원)',str(records[0]['balance']));self.date=date_field();self.form.addRow('수금일',self.date)
        self.method=self.combo('method','수금 수단',[('현금','cash'),('계좌이체','transfer')],'cash');self.memo=self.field('memo','메모')
        self.document.currentIndexChanged.connect(lambda:self.value.setText(str(next(r['balance'] for r in records if r['id']==self.document.currentData()))));self.finish(self.save)
    def save(self):
        try:self.store.add_payment(self.document.currentData(),self.value.text(),self.date.date().toString('yyyy-MM-dd'),self.method.currentData(),self.memo.text());self.accept()
        except (ValueError,PermissionError,OSError) as exc:self.error(exc)
