"""Explicit owner setup and background business reset; no automatic reset path."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QCheckBox,QDialog,QFormLayout,QLabel,QLineEdit,QMessageBox,QProgressBar,QVBoxLayout
from .widgets import FormDialog,action
from .factory_reset import RESET_ID


class BusinessResetDialog(QDialog):
    def __init__(self,window,parent=None):
        super().__init__(parent or window);self.window=window;self.store=window.store;self.worker=None;self.result_data=None;self.failure=''
        self._sy_no_home_button=True;self.setWindowTitle('업무자료 초기화 · 개인 기록 보존');self.resize(650,470)
        layout=QVBoxLayout(self);warning=QLabel('주의: 상품·공급사·매입·판매·결제·재고·회원·문서·사업자 정보를 초기화합니다.\n일기장·가계부·업무일지·일정·개인 첨부와 기존 로그인 계정·개인 암호는 유지합니다.\n보호 백업이 검증되지 않으면 초기화하지 않습니다. 완료 후 종료하며 다시 로그인해야 합니다.')
        warning.setWordWrap(True);warning.setObjectName('notice');layout.addWidget(warning)
        counts=self.store.business_reset_plan()
        summary=QLabel('현재 업무자료: 상품 {products:,} · 거래처 {partners:,} · 전표 {documents:,} · 회원 {members:,} · 문서 {sales_forms:,}'.format(**counts));summary.setWordWrap(True);layout.addWidget(summary)
        layout.addWidget(action('초기화 전용 인증 등록 / 변경',self.configure))
        self.config_state=QLabel();layout.addWidget(self.config_state);self.update_config_state()
        form=QFormLayout();self.admin_password=QLineEdit();self.admin_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.identifier=QLineEdit();self.identifier.setPlaceholderText(RESET_ID);self.identifier.setMaxLength(64)
        self.owner_password=QLineEdit();self.owner_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.phrase=QLineEdit();self.phrase.setPlaceholderText('업무자료 초기화')
        for name,field in (('현재 관리자 비밀번호',self.admin_password),('초기화 전용 아이디',self.identifier),('초기화 전용 비밀번호',self.owner_password),('최종 확인 문구',self.phrase)):
            field.setAccessibleName(name);form.addRow(name,field)
        layout.addLayout(form)
        self.consent=QCheckBox('업무자료 삭제·개인 기록 및 계정 보존·보호 백업 생성에 동의합니다.');layout.addWidget(self.consent)
        self.error=QLabel();self.error.setWordWrap(True);layout.addWidget(self.error)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        self.begin_button=action('경고 확인 후 업무자료 초기화',self.begin,danger=True);layout.addWidget(self.begin_button)
        layout.addWidget(action('취소',self.reject))

    def update_config_state(self):
        ready=self.store.reset_authority_configured()
        self.config_state.setText('전용 인증 등록됨 · 비밀번호는 화면·공개 코드에 표시하지 않습니다.' if ready else '최초 1회, 이 PC에서 전용 비밀번호를 직접 등록하세요. 기본/공용 초기화 비밀번호는 배포하지 않습니다.')
        self.config_state.setWordWrap(True)

    def configure(self):
        dialog=FormDialog('초기화 전용 인증 등록 / 변경',self)
        admin=dialog.field('admin_password','현재 관리자 비밀번호',password=True)
        identifier=dialog.field('reset_id','초기화 전용 아이디',RESET_ID)
        previous=dialog.field('previous_password','기존 초기화 비밀번호 (변경 시)',password=True)
        password=dialog.field('reset_password','새 초기화 비밀번호',password=True)
        confirmation=dialog.field('confirmation_password','새 비밀번호 확인',password=True)
        def save():
            try:self.store.configure_reset_authority(admin.text(),identifier.text(),password.text(),confirmation.text(),previous.text());dialog.accept()
            except (ValueError,PermissionError,OSError) as exc:dialog.error(exc)
        dialog.finish(save);dialog.exec()
        for field in (admin,previous,password,confirmation):field.clear()
        self.update_config_state()

    def begin(self):
        if not self.consent.isChecked() or self.phrase.text()!='업무자료 초기화':self.error.setText('동의 체크와 최종 확인 문구를 확인하세요.');return
        if any(w.isRunning() for w in getattr(QApplication.instance(),'_sy_catalog_workers',[])):
            self.error.setText('진행 중인 분석·저장 작업을 마친 뒤 다시 시도하세요.');return
        journal=getattr(self.window,'crash_journal',None)
        if journal and journal.rows():self.error.setText('미저장 작업 복구에서 임시본을 저장하거나 정리한 뒤 초기화하세요. 다른 계정의 미저장 개인 기록도 먼저 저장해야 합니다.');return
        if QMessageBox.warning(self,'최종 초기화 확인','업무자료를 초기화할까요?\n개인 기록과 기존 계정은 유지합니다. 보호 백업 후 초기화하고 프로그램을 종료합니다.\n취소하려면 아니요를 누르세요.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        from .background_store import StoreTask
        self.failure='';self.result_data=None
        args=(self.admin_password.text(),self.identifier.text(),self.owner_password.text(),self.phrase.text())
        self.worker=StoreTask(self,self.store,'reset_business_data',args)
        self.admin_password.clear();self.owner_password.clear();self.progress.show();self.begin_button.setEnabled(False)
        self.worker.succeeded.connect(self.succeeded);self.worker.failed.connect(self.failed);self.worker.finished.connect(self.finished_work)
        self._journal_was_active=bool(journal and journal.timer.isActive())
        if journal:journal.timer.stop()
        self.worker.start()
    def succeeded(self,result):self.result_data=result
    def failed(self,message):self.failure=message
    def finished_work(self):
        self.progress.hide()
        if self.result_data:self.accept()
        else:
            self.error.setText(self.failure or '초기화하지 않았습니다.');self.begin_button.setEnabled(True)
            journal=getattr(self.window,'crash_journal',None)
            if journal and self._journal_was_active:journal.timer.start()
    def reject(self):
        if not self.worker or not self.worker.isRunning():super().reject()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore()
        else:super().closeEvent(event)
