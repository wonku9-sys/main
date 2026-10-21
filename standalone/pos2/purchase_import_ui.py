"""Responsive multi-file preview and explicit purchase-draft import."""
from decimal import Decimal
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QFileDialog, QMessageBox, QApplication, QCheckBox
from .widgets import DataGrid, action, date_field
from .purchase_import import plan_files


class PurchaseReadWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent, paths, catalog, supplier, date, current_prices=False):
        super().__init__(parent)
        self.args = paths, catalog, supplier, date, current_prices
        app = QApplication.instance()
        if not hasattr(app, '_sy_catalog_workers'):
            app._sy_catalog_workers = []
        app._sy_catalog_workers.append(self)
        self.finished.connect(lambda: app._sy_catalog_workers.remove(self) if self in app._sy_catalog_workers else None)

    def run(self):
        try:
            self.succeeded.emit(plan_files(*self.args))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.args = ()


class PurchaseImportDialog(QDialog):
    imported = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.worker, self.files = store, None, []
        store.require_menu('purchases')
        self.setWindowTitle('매입 엑셀 불러오기 · 여러 파일 / 초안 검토')
        self.resize(1080, 740)
        layout = QVBoxLayout(self)
        notice = QLabel('XLS/XLSX를 한 개 또는 여러 개 선택하세요. 파일별로 매입 초안을 만듭니다.\n재고·결제는 반영하지 않습니다. 초안을 열어 확인한 뒤 최종 저장(확정)하세요. 같은 파일은 중복 등록하지 않습니다.\nSY POS 매입전표 양식 또는 상품명·수량·단가 제목이 있는 목록을 지원합니다. 반품·취소·불명확한 상품은 자동 등록하지 않습니다.')
        notice.setWordWrap(True); layout.addWidget(notice)
        controls = QHBoxLayout()
        self.supplier = QComboBox(); self.supplier.addItem('파일에 공급사 없을 때 기본 공급사 선택', None)
        for row in store.trade_partners('supplier'):
            self.supplier.addItem(f"{row['code']} · {row['name']}", row['id'])
        self.date = date_field()
        controls.addWidget(self.supplier, 1); controls.addWidget(QLabel('날짜 없는 파일의 매입일')); controls.addWidget(self.date)
        self.open_button = action('엑셀 파일 선택 · 다중 선택', self.choose, True)
        controls.addWidget(self.open_button); layout.addLayout(controls)
        self.current_prices = QCheckBox('단가 없는 바코드·수량 파일은 현재 상품 등록 매입가 사용 (과거 단가 아님)')
        layout.addWidget(self.current_prices)
        self.file_grid = DataGrid(['선택', '파일명', '공급사', '매입일', '품목 수', '합계', '검토 결과'])
        self.file_grid.setWordWrap(False)
        for column, width in enumerate((65, 270, 165, 110, 75, 120, 300)):
            self.file_grid.setColumnWidth(column, width)
        layout.addWidget(self.file_grid, 1)
        self.file_grid.itemSelectionChanged.connect(self.detail)
        self.line_grid = DataGrid(['파일 행', '상품명', '수량', '단가', '금액'])
        layout.addWidget(self.line_grid, 2)
        self.message = QLabel('파일을 선택하면 분석 결과를 보여드립니다.'); self.message.setWordWrap(True); layout.addWidget(self.message)
        footer = QHBoxLayout()
        self.commit_button = action('체크한 파일을 매입 초안으로 등록', self.commit, True)
        self.commit_button.setEnabled(False)
        footer.addWidget(self.commit_button); footer.addWidget(action('이 창 닫기', self.close)); layout.addLayout(footer)

    def busy(self, value):
        for widget in (self.open_button, self.supplier, self.date, self.file_grid, self.current_prices):
            widget.setEnabled(not value)
        self.commit_button.setEnabled(not value and any(not f['error'] for f in self.files))

    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '매입 엑셀 선택 (Ctrl/Shift로 여러 파일)', '', 'Excel (*.xls *.xlsx)')
        if paths:
            self.load_files(paths)

    def load_files(self, paths):
        if self.worker and self.worker.isRunning():
            return
        if not 1 <= len(paths) <= 50:
            return self.failed('한 번에 최대 50개 파일을 선택하세요.')
        try:
            self.store._require_capability('purchases', 'create')
            catalog = self.store.purchase_import_catalog()
            self.busy(True); self.message.setText('엑셀 파일을 분석하고 있습니다…')
            self.worker = PurchaseReadWorker(self, paths, catalog, self.supplier.currentData(), self.date.date().toString('yyyy-MM-dd'), self.current_prices.isChecked())
            self.worker.succeeded.connect(self.loaded)
            self.worker.failed.connect(self.failed)
            self.worker.finished.connect(lambda: self.busy(False))
            self.worker.start()
        except (ValueError, PermissionError) as exc:
            self.failed(str(exc))

    def loaded(self, files):
        self.files = files
        self.file_grid.fill([['', f['file'], f.get('supplier_name', ''), f.get('date', ''), len(f['lines']), Decimal(f.get('total', '0')), f['error'] or '초안 등록 가능 · '+f.get('price_source','')+' · '+f.get('metadata_source','')] for f in files], files)
        for row in range(self.file_grid.rowCount()):
            item = self.file_grid.item(row, 0)
            record = item.data(Qt.ItemDataRole.UserRole)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if record['error'] else Qt.CheckState.Checked)
        self.message.setText(f"{len(files)}개 파일 분석 · 오류 파일은 체크 해제하고 원본을 수정해 다시 불러오세요. 등록 전 품목·금액을 확인하세요.")
        if files:
            self.file_grid.selectRow(0)

    def detail(self):
        file = self.file_grid.selected()
        if not file:
            return
        lines = file['lines'][:500]
        self.line_grid.fill([[l['source_row'], l['name'], l['qty'], l['unit_price'], l['total']] for l in lines])
        self.line_grid.setToolTip(f"품목 {len(file['lines'])}개 · 미리보기는 처음 500개 표시 · 등록은 전체 품목")

    def commit(self):
        if self.worker and self.worker.isRunning():
            return
        files = [self.file_grid.item(i, 0).data(Qt.ItemDataRole.UserRole) for i in range(self.file_grid.rowCount())
                 if self.file_grid.item(i, 0).checkState() == Qt.CheckState.Checked]
        if not files or any(f['error'] for f in files):
            return self.failed('오류 없는 파일을 체크하세요.')
        if QMessageBox.question(self, '매입 초안 등록', f'{len(files)}개 파일을 초안으로 등록할까요? 재고·결제는 반영하지 않습니다.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            from .store import Store
            if type(self.store) is Store and self.store.path:
                from .background_store import StoreTask
                self.busy(True)
                self.worker = StoreTask(self, self.store, 'import_purchase_drafts', (files,))
                self.worker.succeeded.connect(self.committed); self.worker.failed.connect(self.failed)
                self.worker.finished.connect(lambda: self.busy(False)); self.worker.start()
            else:
                self.committed(self.store.import_purchase_drafts(files))
        except (ValueError, PermissionError) as exc:
            self.failed(str(exc))

    def committed(self, result):
        self.message.setText(f"매입 초안 {len(result['created'])}건 등록 · 같은 파일 {len(result['existing'])}건 중복 제외. 매입전표에서 해당 날짜로 조회해 확인·확정하세요.")
        self.imported.emit()

    def failed(self, message):
        self.message.setText('처리하지 못했습니다: '+message)

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.message.setText('분석·등록 작업 완료 후 닫을 수 있습니다.'); event.ignore(); return
        QDialog.reject(self); event.accept()
