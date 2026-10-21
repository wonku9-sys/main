"""Private Excel preview, explicit tax confirmation, atomic create-only import."""
from PySide6.QtCore import QThread,Signal,Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QFileDialog,QMessageBox,QAbstractItemView,QProgressBar
from .widgets import action,DataGrid
from .tax_display import tax_style,tax_icon


class CatalogWorker(QThread):
    result=Signal(object);failed=Signal(str)
    def __init__(self,parent,source=None,context=None,rows=None):
        super().__init__(parent);self.source=source;self.context=context;self.rows=rows
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance()
        if not hasattr(app,'_sy_catalog_workers'):app._sy_catalog_workers=[]
        app._sy_catalog_workers.append(self)
        self.finished.connect(lambda:app._sy_catalog_workers.remove(self) if self in app._sy_catalog_workers else None)
    def run(self):
        try:
            if self.source:
                from .catalog_import import plan_excel
                result=plan_excel(self.source)
            else:
                from .store import Store
                path,actor,password_hash,restore_token=self.context;store=Store(path)
                try:
                    store.actor=actor;store._session_password_hash=password_hash;store._restore_token=restore_token
                    result=store.import_catalog(self.rows)
                finally:store.close()
            self.result.emit(result)
        except Exception as exc:self.failed.emit(str(exc))


class CatalogImportDialog(QDialog):
    imported=Signal()
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.records=[];self.filtered=[];self.page=0;self.worker=None
        self.setWindowTitle('상품 엑셀 등록 · 과면세·분류 검토');self.resize(1180,760);layout=QVBoxLayout(self)
        note=QLabel('기존 상품·가격·재고·거래는 덮어쓰지 않습니다. 파일에 없는 과면세·분류는 추천 초안이며, 확인 필요 품목은 지정 전 등록하지 않습니다.\n원물·1차 가공과 조리·조미 여부에 따른 추천은 예외가 있으므로 등록 전 검토하세요. 원본 파일과 가격표는 공개 배포에 넣지 않습니다.');note.setWordWrap(True);layout.addWidget(note)
        tools=QHBoxLayout();self.open_button=action('XLS / XLSX 선택',self.choose,primary=True);tools.addWidget(self.open_button)
        self.search=QLineEdit();self.search.setPlaceholderText('상품명·바코드·공급사·분류 검색');self.search.textChanged.connect(self.filter);tools.addWidget(self.search,1)
        self.status_filter=QComboBox();self.status_filter.addItems(['전체','과면세 확인 필요','등록 가능','오류']);self.status_filter.currentIndexChanged.connect(self.filter);tools.addWidget(self.status_filter);layout.addLayout(tools)
        changes=QHBoxLayout();self.tax=QComboBox();self.tax.addItem('적용할 과면세 선택',None);self.tax.addItem('과 · 과세','taxable');self.tax.addItem('면 · 면세','exempt');changes.addWidget(self.tax)
        changes.addWidget(action('선택행에 적용',lambda:self.apply_tax(False)));changes.addWidget(action('검색 결과 전체에 적용',lambda:self.apply_tax(True)));changes.addStretch();layout.addLayout(changes)
        self.grid=DataGrid(['원본 행','과면세','상품명','규격','바코드','공급사','대 / 중 / 소분류','매입단가','판매단가','검토']);self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);layout.addWidget(self.grid,1)
        self.grid.setColumnWidth(2,230);self.grid.setColumnWidth(6,250)
        pages=QHBoxLayout();pages.addWidget(action('이전 500개',lambda:self.move(-1)));pages.addWidget(action('다음 500개',lambda:self.move(1)));self.summary=QLabel();self.summary.setWordWrap(True);pages.addWidget(self.summary,1);layout.addLayout(pages)
        self.progress=QProgressBar();self.progress.hide();layout.addWidget(self.progress);self.message=QLabel('원본 엑셀을 선택하세요.');self.message.setWordWrap(True);layout.addWidget(self.message)
        footer=QHBoxLayout();self.commit_button=action('확인된 상품 등록',self.commit,primary=True);self.commit_button.setEnabled(False);footer.addWidget(self.commit_button);footer.addWidget(action('이 창 닫기',self.close));layout.addLayout(footer)
    def busy(self,value):
        self.open_button.setEnabled(not value);self.commit_button.setEnabled(not value and bool(self.records));self.progress.setVisible(value);self.progress.setRange(0,0)
        for control in (self.search,self.status_filter,self.tax,self.grid):control.setEnabled(not value)
    def choose(self):
        name,_=QFileDialog.getOpenFileName(self,'상품 목록 선택','','Excel (*.xls *.xlsx)')
        if name:self.load_file(name)
    def load_file(self,name):
        if self.worker and self.worker.isRunning():return
        self.busy(True);self.message.setText('원본 목록을 분석하고 있습니다…');self.worker=CatalogWorker(self,source=name)
        self.worker.result.connect(self.loaded);self.worker.failed.connect(self.failed);self.worker.finished.connect(lambda:self.busy(False));self.worker.start()
    def loaded(self,plan):
        self.records=plan['rows'];self.record_map={row['source_row']:row for row in self.records};self.page=0;self.message.setText(f"{len(self.records):,}개 상품 분석 · 빈 행/통계 {plan['skipped']:,}개 제외 · 과면세/분류의 ‘추천’은 수정 가능합니다.");self.filter();self.commit_button.setEnabled(True)
    def failed(self,message):self.message.setText('등록하지 못했습니다. 적용 중 실패했다면 전체 취소됩니다. '+message)
    def filter(self,*_):
        term=self.search.text().strip().casefold();kind=self.status_filter.currentIndex()
        self.filtered=[row for row in self.records if (not term or term in ' '.join(str(row.get(k,'')) for k in ('name','barcode','supplier_name','category','category_mid','category_small')).casefold()) and (kind==0 or kind==1 and not row['tax_mode'] or kind==2 and row['tax_mode'] and not row['error'] or kind==3 and row['error'])]
        self.page=0;self.render()
    def render(self):
        count=len(self.filtered);self.page=max(0,min(self.page,max(0,(count-1)//500)));rows=self.filtered[self.page*500:(self.page+1)*500]
        self.grid.fill([[r['source_row'],(tax_style(r['tax_mode'])[0]+' · '+tax_style(r['tax_mode'])[1]) if r['tax_mode'] else '확인 필요',r['name'],r['specification'],r['barcode'],r['supplier_name'],' / '.join(r[k] for k in ('category','category_mid','category_small')),r['purchase_price'],r['sale_price'],r['error'] or r['tax_source']+' 과면세 · '+r['category_source']+' 분류'] for r in rows],rows)
        for index in range(self.grid.rowCount()):
            record=self.grid.item(index,0).data(Qt.ItemDataRole.UserRole)
            if record['tax_mode']:
                _,_,fg,bg=tax_style(record['tax_mode']);item=self.grid.item(index,1);item.setForeground(QColor(fg));item.setBackground(QColor(bg));self.grid.item(index,2).setIcon(tax_icon(record['tax_mode']))
        valid=sum(bool(r['tax_mode']) and not r['error'] for r in self.records)
        self.summary.setText(f'검색 {count:,} / 전체 {len(self.records):,}개 · {self.page+1} / {max(1,(count+499)//500)}쪽 · 등록 가능 {valid:,}개')
    def move(self,direction):self.page+=direction;self.render()
    def apply_tax(self,all_filtered):
        mode=self.tax.currentData()
        if not mode:return
        rows=self.filtered if all_filtered else [self.record_map[self.grid.item(i.row(),0).data(Qt.ItemDataRole.UserRole)['source_row']] for i in self.grid.selectionModel().selectedRows()]
        if not rows:return
        if all_filtered and QMessageBox.question(self,'검색 결과 과면세 지정',f'{len(rows):,}개에 {self.tax.currentText()}를 지정할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        for row in rows:row['tax_mode']=mode;row['tax_source']='직접 확인'
        self.filter()
    def commit(self):
        from .store import Store
        if not isinstance(self.store,Store):self.message.setText('대량 엑셀 등록은 기준 PC에서 실행하세요. 완료된 상품은 다른 PC에도 공유됩니다.');return
        if self.worker and self.worker.isRunning():return
        rows=[r.copy() for r in self.records if r['tax_mode'] and not r['error']]
        if not rows:self.message.setText('과면세와 입력 오류를 먼저 확인하세요.');return
        if QMessageBox.question(self,'추천값 검토·상품 등록',f"과면세·추천분류를 검토하셨나요?\n{len(rows):,}개 등록 시도 / 확인 필요·오류 {len(self.records)-len(rows):,}개 제외\n중복 상품은 건너뛰며 기존 가격·재고를 변경하지 않습니다.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        context=(self.store.path,dict(self.store.actor),self.store._session_password_hash,self.store._restore_token)
        self.busy(True);self.message.setText('보호 백업 후 일괄 등록 중입니다. 완료 전 프로그램을 종료하지 마세요.');self.worker=CatalogWorker(self,context=context,rows=rows);self.worker.result.connect(self.applied);self.worker.failed.connect(self.failed);self.worker.finished.connect(lambda:self.busy(False));self.worker.start()
    def applied(self,result):
        self.message.setText(f"새 상품 {result['created']:,}개 등록 · 중복 {result['skipped']:,}개 건너뜀\n보호 백업: {result['backup']}");self.imported.emit()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.message.setText('분석·등록이 완료된 후 닫을 수 있습니다.');event.ignore();return
        # QDialog's default closeEvent calls virtual reject(). Our reject routes
        # Escape through close() to protect running workers; calling the default
        # closeEvent here re-enters close/reject and leaves an idle dialog stuck.
        QDialog.reject(self)
        event.accept()
    def reject(self):self.close()
