"""Compact customer registration, grouped like the supplied reference."""
from PySide6.QtCore import QDate,Qt
from PySide6.QtGui import QKeySequence,QShortcut
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDateEdit,QDialogButtonBox,QGridLayout,QGroupBox,
    QHBoxLayout,QLabel,QLineEdit,QMessageBox,QSpinBox,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)
from .widgets import FormDialog,action,won
from .member_registration import DEFAULTS,MEMBER_TYPES


class MemberDialog(FormDialog):
    def __init__(self,store,record=None,parent=None):
        super().__init__('고객 등록정보' if record else '새 고객등록',parent)
        self.store,self.record=store,record or {};self.detail_fields={};self._lookup=None
        self._sy_no_home_button=True;self.resize(820,890)
        self.body.itemAt(0).widget().hide()
        self.body.removeItem(self.form);self.form.deleteLater()
        self.body.setContentsMargins(12,10,12,10);self.body.setSpacing(6)
        self.detail=dict(DEFAULTS,**self.record.get('registration',{}))
        self.setStyleSheet('QGroupBox{background:#E6E9E0;border:1px solid #A8B1A3;border-radius:0;margin-top:13px;padding-top:11px;} QLineEdit,QComboBox,QSpinBox,QDateEdit{background:#FFFFE9;min-height:18px;padding:3px;} QLabel{background:transparent;}')
        def group(title):
            box=QGroupBox(title);grid=QGridLayout(box);grid.setContentsMargins(8,10,8,7);grid.setSpacing(5);return box,grid
        def field(key,value=None,detail=False):
            entry=QLineEdit(str((self.detail if detail else self.record).get(key,'') if value is None else value))
            entry.setAccessibleName(key);(self.detail_fields if detail else self.fields)[key]=entry;return entry
        def pair(grid,row,col,title,control,span=1):
            grid.addWidget(QLabel(title),row,col);grid.addWidget(control,row,col+1,1,span)
        self._field=field
        header,grid=group('회원정보')
        code=field('code',self.record.get('code') or store.next_member_code())
        grid.addWidget(action('바코드',lambda:code.setText(store.next_member_code())),0,0);grid.addWidget(code,0,1)
        self.active=QCheckBox('유효');self.active.setChecked(self.record.get('active',True));grid.addWidget(self.active,0,2)
        self.abc=QComboBox();self.abc.addItems(['','A','B','C','D']);self.abc.setCurrentText(self.detail['abc']);pair(grid,0,3,'ABC',self.abc)
        pair(grid,0,5,'담당자',field('staff_name',detail=True))
        self.member_type=QComboBox();self.member_type.setEditable(True);self.member_type.addItems(MEMBER_TYPES)
        self.member_type.setCurrentText(self.record.get('member_type','일반고객'));pair(grid,1,0,'유형',self.member_type)
        self.wholesale=QComboBox();self.wholesale.setEditable(True);self.wholesale.addItems(['정상가','도매1','도매2','도매3']);self.wholesale.setCurrentText(self.detail['wholesale_grade'])
        self.wholesale.setToolTip('고객 조회용 분류입니다. 실제 판매가격은 상품 가격·회원 지정가 정책을 따릅니다.')
        pair(grid,1,2,'도매등급',self.wholesale);pair(grid,1,4,'등급',field('grade',detail=True));self.body.addWidget(header)
        personal,grid=group('기본 고객정보')
        pair(grid,0,0,'이름 *',field('name'));self.gender=QComboBox();self.gender.addItems(['미지정','여','남']);self.gender.setCurrentText(self.detail['gender'] or '미지정')
        pair(grid,0,2,'성별',self.gender);self.family_count=QSpinBox();self.family_count.setRange(0,100);self.family_count.setValue(self.detail['family_count']);pair(grid,0,4,'가족수',self.family_count)
        pair(grid,1,0,'전화1',field('phone'));pair(grid,2,0,'전화2',field('phone2',detail=True));pair(grid,3,0,'휴대폰',field('mobile'))
        self.birthday_enabled=QCheckBox('생일');self.birthday_enabled.setChecked(bool(self.record.get('birthday')))
        self.birthday=QDateEdit();self.birthday.setCalendarPopup(True);self.birthday.setDisplayFormat('yyyy-MM-dd');self.birthday.setKeyboardTracking(False)
        self.birthday.setDateRange(QDate(1900,1,1),QDate.currentDate());self.birthday.setDate(QDate.fromString(self.record.get('birthday') or '1977-03-10','yyyy-MM-dd'))
        self.birthday.setEnabled(self.birthday_enabled.isChecked());self.birthday_enabled.toggled.connect(self.birthday.setEnabled)
        grid.addWidget(self.birthday_enabled,1,2);grid.addWidget(self.birthday,1,3)
        self.solar=QCheckBox('양력');self.solar.setChecked(self.detail['birthday_calendar']=='solar');grid.addWidget(self.solar,1,4)
        pair(grid,2,2,'기념일',field('anniversary'));self.fields['anniversary'].setPlaceholderText('YYYY-MM-DD / 미등록은 빈칸')
        pair(grid,3,2,'E-mail',field('email',detail=True),3)
        self.phone_type=QComboBox();self.phone_type.setEditable(True);self.phone_type.addItems(['휴대폰','일반전화','집','직장','기타']);self.phone_type.setCurrentText(self.record.get('phone_type','일반전화'))
        pair(grid,4,0,'전화1 구분',self.phone_type);pair(grid,4,2,'회원그룹',field('group_name'),3);self.body.addWidget(personal)
        middle=QHBoxLayout();business,grid=group('사업자 정보')
        for row,(key,title,detail) in enumerate((('company','상호',False),('business_no','사업자번호',False),('representative','대표자',False),('business_type','업태',True),('business_category','업종',True))):
            pair(grid,row,0,title,field(key,detail=detail))
        middle.addWidget(business,1);credit,grid=group('거래 정보')
        self.credit_allowed=QCheckBox('외상거래 허용');self.credit_allowed.setChecked(self.detail['credit_allowed']);grid.addWidget(self.credit_allowed,0,0,1,2)
        pair(grid,1,0,'외상한도 (원)',field('credit_limit',detail=True))
        self.credit_balance=QLineEdit(won(self.record.get('credit_balance',0)));self.credit_balance.setReadOnly(True);pair(grid,2,0,'현재 외상잔액',self.credit_balance)
        self.closing_day=QSpinBox();self.closing_day.setRange(1,31);self.closing_day.setValue(self.detail['closing_day']);pair(grid,3,0,'결제마감 매월',self.closing_day)
        note=QLabel('허용 체크와 한도 이내에서만 외상판매됩니다.\n수금·반품 시 실제 잔액을 다시 계산합니다.\n마감일은 관리용이며 자동 청구·승인은 하지 않습니다.');note.setWordWrap(True);grid.addWidget(note,4,0,1,2);middle.addWidget(credit,1);self.body.addLayout(middle)
        address,grid=group('주소 · 메모')
        grid.addWidget(action('우편번호 찾기',self.find_address),0,0);grid.addWidget(field('postcode',detail=True),0,1);grid.addWidget(QLabel('무료 온라인 검색 / 직접 입력 가능'),0,2,1,2)
        for row,key,title,detail in ((1,'address','기본주소',False),(2,'address_detail','상세주소',True),(3,'delivery_memo','배달 메모',True),(4,'memo','기타 메모',False)):
            pair(grid,row,0,title,field(key,detail=detail),3)
        self.body.addWidget(address)
        bottom=QHBoxLayout();self.identifiers=self.editable_rows('추가 인식 정보',['인식정보','설명'],self.detail['identifiers'],('code','description'));bottom.addWidget(self.identifiers[0])
        self.vehicles=self.editable_rows('차량정보',['차량번호','최종할인일 (YYYY-MM-DD)'],self.detail['vehicles'],('plate','last_discount'));bottom.addWidget(self.vehicles[0]);self.body.addLayout(bottom)
        self.finish(self.save);self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('저장 (Ctrl+S)')
        shortcut=QShortcut(QKeySequence('Ctrl+S'),self);shortcut.activated.connect(self.save)
        self.finished.connect(self.stop_lookup)
    def editable_rows(self,title,headers,rows,keys):
        from .trade_sheet import EntrySheet
        group=QGroupBox(title);layout=QVBoxLayout(group);table=EntrySheet(0,2);table.setHorizontalHeaderLabels(headers);table.setMaximumHeight(115);table.horizontalHeader().setStretchLastSection(True)
        for row in rows:
            index=table.rowCount();table.insertRow(index)
            for col,key in enumerate(keys):table.setItem(index,col,QTableWidgetItem(row[key]))
        layout.addWidget(table);tools=QHBoxLayout()
        def add():
            if table.rowCount()<50:table.insertRow(table.rowCount())
        tools.addWidget(action('추가',add));tools.addWidget(action('삭제',lambda:table.removeRow(table.currentRow()) if table.currentRow()>=0 else None));layout.addLayout(tools)
        return group,table,keys
    def rows(self,bundle):
        _,table,keys=bundle
        return [{key:table.item(r,c).text().strip() if table.item(r,c) else '' for c,key in enumerate(keys)} for r in range(table.rowCount())]
    def values(self):
        values={key:field.text().strip() for key,field in self.fields.items()}
        detail={key:field.text().strip() for key,field in self.detail_fields.items()}
        detail.update(abc=self.abc.currentText(),wholesale_grade=self.wholesale.currentText(),gender='' if self.gender.currentIndex()==0 else self.gender.currentText(),
                      family_count=self.family_count.value(),birthday_calendar='solar' if self.solar.isChecked() else 'lunar',
                      credit_allowed=self.credit_allowed.isChecked(),closing_day=self.closing_day.value(),
                      identifiers=self.rows(self.identifiers),vehicles=self.rows(self.vehicles))
        values.update(active=self.active.isChecked(),birthday=self.birthday.date().toString('yyyy-MM-dd') if self.birthday_enabled.isChecked() else '',
                      phone_type=self.phone_type.currentText(),member_type=self.member_type.currentText(),registration=detail)
        return values
    def save(self):
        try:self.saved_id=self.store.save_member(self.values(),self.record.get('id'));self.accept()
        except (ValueError,PermissionError,OSError) as exc:self.error(exc)
    def stop_lookup(self,*_):
        if self._lookup:self._lookup.stop()
    def find_address(self):
        answer=QMessageBox.question(self,'무료 온라인 주소찾기','기본 브라우저에서 카카오 우편번호 검색을 열까요?\n검색어·선택 주소만 조회하며 고객 이름·전화번호·회원번호는 보내지 않습니다.\n인터넷이나 검색 서비스가 안 되면 우편번호·주소를 직접 입력하세요.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        self.stop_lookup()
        from .address_lookup import AddressLookup
        lookup=AddressLookup(self);self._lookup=lookup;before=self.fields['address'].text()
        def selected(result):
            if not self.isVisible():return
            if self.fields['address'].text()!=before and QMessageBox.question(self,'주소 적용','직접 입력한 기본주소가 바뀌었습니다. 검색 주소로 바꿀까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            self.detail_fields['postcode'].setText(result['postcode']);self.fields['address'].setText(result['address']);self.detail_fields['address_detail'].setFocus()
        lookup.selected.connect(selected)
        try:lookup.start(before)
        except (OSError,ValueError) as exc:self.error(exc)
