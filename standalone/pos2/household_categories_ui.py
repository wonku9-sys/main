from PySide6.QtWidgets import QCheckBox,QDialog,QHBoxLayout,QLabel,QMessageBox,QVBoxLayout
from .widgets import DataGrid,FormDialog,action


class CategoryRulesDialog(QDialog):
    def __init__(self,store,key,parent=None):
        super().__init__(parent);self.store,self.key=store,key;self.setWindowTitle('가계부 자동 분류 · 로컬 키워드 규칙');self.resize(820,540)
        body=QVBoxLayout(self);self.grid=DataGrid(['우선순위','추천 분류','키워드','적용','상태']);body.addWidget(self.grid,1)
        controls=QHBoxLayout()
        for title,fn in [('규칙 추가',self.add),('규칙 수정·중지',self.edit),('닫기',self.reject)]:controls.addWidget(action(title,fn))
        body.addLayout(controls);note=QLabel('작은 우선순위 숫자의 규칙부터 확인합니다. 키워드는 내용·문자 알림에서 부분 일치로 찾습니다.\n외부 AI·은행·서버에 보내지 않습니다. 추천은 틀릴 수 있으니 저장 전 확인하세요. 수동으로 바꾼 분류는 자동 덮어쓰지 않습니다.\n기본 규칙도 수정하거나 ‘사용’ 체크를 꺼서 중지할 수 있습니다.');note.setWordWrap(True);body.addWidget(note)
        self.grid.cellDoubleClicked.connect(lambda *_:self.edit());self.refresh()
    def refresh(self):
        rows=self.store.household_category_rules(self.key);self.grid.fill([[r['priority'],r['category'],', '.join(r['keywords']),{'income':'수입','expense':'지출','both':'모두'}[r['kind']],'사용' if r['active'] else '중지'] for r in rows],rows)
    def add(self):self.editor()
    def edit(self):
        record=self.grid.selected()
        if record:self.editor(record)
    def editor(self,record=None):
        record=record or {};d=FormDialog('자동분류 규칙',self)
        category=d.field('category','추천할 분류 *',record.get('category',''))
        keywords=d.field('keywords','키워드 (쉼표로 구분)',', '.join(record.get('keywords',[])))
        kind=d.combo('kind','적용 구분',[('지출','expense'),('수입','income'),('모두','both')],record.get('kind','expense'))
        priority=d.field('priority','우선순위 (0~999, 작을수록 우선)',record.get('priority',50))
        active=QCheckBox('사용');active.setChecked(record.get('active',True));d.form.addRow(active)
        def save():
            try:self.store.save_household_category_rule(self.key,dict(category=category.text(),keywords=keywords.text(),kind=kind.currentData(),priority=priority.text(),active=active.isChecked()),record.get('id'));d.accept()
            except (ValueError,PermissionError) as exc:d.error(exc)
        d.finish(save)
        if d.exec():self.refresh()
        for field in (category,keywords,priority):field.clear()
        d.deleteLater()
    def wipe(self):self.grid.fill([])
    def reject(self):self.wipe();super().reject()
