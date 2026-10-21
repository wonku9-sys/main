"""Explicit email setup/verification; no SMTP calls occur on the GUI thread."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtWidgets import QCheckBox,QComboBox,QDialogButtonBox,QHBoxLayout,QLabel,QLineEdit,QMessageBox

from .widgets import FormDialog,action


class MailSignals(QObject):
    finished=Signal(bool,str)


class MailWorker(QRunnable):
    def __init__(self,job):
        super().__init__();self.job=job;self.signals=MailSignals()
    def run(self):
        try:self.job.send()
        except (ValueError,OSError) as exc:self.signals.finished.emit(False,str(exc))
        except Exception:self.signals.finished.emit(False,"메일 발송 중 오류가 발생했습니다. 발송 설정을 확인하고 다시 요청하세요. 기존 암호는 변경되지 않았습니다.")
        else:self.signals.finished.emit(True,"")


class MailSettingsDialog(FormDialog):
    def __init__(self,store,parent=None):
        super().__init__("이메일 발송 설정 · 관리자",parent)
        self.store=store
        config=store.mail_settings()
        self.resize(760,700)
        preset=QComboBox();preset.addItems(["직접 설정","Gmail","Daum"]);self.form.addRow("발송 서비스",preset)
        self.host=self.field("host","SMTP 서버",config.get("host",""))
        self.port=self.field("port","포트",config.get("port",465))
        self.mode=QComboBox();self.mode.addItem("SSL/TLS","ssl");self.mode.addItem("STARTTLS","starttls");self.mode.setCurrentIndex(max(0,self.mode.findData(config.get("mode","ssl"))));self.form.addRow("보안 연결",self.mode)
        self.username=self.field("username","발송 계정",config.get("username",""))
        self.sender=self.field("sender","발신 이메일",config.get("sender",""))
        self.username.setPlaceholderText("예: myaccount@gmail.com")
        self.sender.setPlaceholderText("보통 발송 계정과 같은 이메일 주소")
        self.username.editingFinished.connect(lambda:self.sender.setText(self.username.text()) if not self.sender.text().strip() else None)
        self.password=self.field("password","앱 비밀번호 (빈칸이면 기존 값 유지)",password=True)
        def choose(value):
            if value in {"Gmail","Daum"}:
                self.host.setText("smtp.gmail.com" if value=="Gmail" else "smtp.daum.net");self.port.setText("465");self.mode.setCurrentIndex(0)
        preset.currentTextChanged.connect(choose)
        note=QLabel("① Gmail/Daum 또는 직접 설정을 선택 → ② 발송 이메일 계정과 앱 비밀번호 입력 → ③ 저장 후 ‘인증 메일 요청’을 누르세요.\n\nGmail은 계정의 2단계 인증·앱 비밀번호, Daum은 SMTP 사용 설정을 확인하세요. 서비스 정책에 따라 앱 비밀번호가 필요합니다.\n\n메일 비밀번호는 현재 Windows 사용자 계정으로 암호화해 저장합니다. 다른 PC·Windows 계정에서는 다시 설정해야 합니다. 프로그램에 공용 발송 계정은 들어 있지 않습니다. 받는 주소는 ‘복구 이메일’에서 따로 등록합니다.")
        note.setWordWrap(True);self.body.addWidget(note)
        self.finish(self.save)
        self.scroll_form()
    def save(self):
        try:
            self.store.save_mail_settings({"host":self.host.text(),"port":self.port.text(),"mode":self.mode.currentData(),"username":self.username.text(),"sender":self.sender.text(),"password":self.password.text()})
            self.password.clear();self.accept()
        except (ValueError,PermissionError) as exc:self.error(exc)
    def reject(self):
        self.password.clear();super().reject()


class EmailCodeDialog(FormDialog):
    """Bind, enable recovery, or reset; only the registered recipient is used."""
    def __init__(self,store,purpose,parent=None,user_code="",email=""):
        title={"bind":"복구 이메일 최초 등록·인증","login_reset":"로그인 암호 이메일 재설정","diary_enable":"일기장 이메일 복구 등록","diary_reset":"일기장 암호 이메일 재설정","household_enable":"가계부 이메일 복구 등록","household_reset":"가계부 암호 이메일 재설정"}[purpose]
        super().__init__(title,parent)
        self.store,self.purpose=store,purpose
        self.job=None;self.sending=False;self.delivery_ok=False;self.resize(720,710)
        self.user=self.field("user","아이디",user_code if purpose=="login_reset" else store.actor["code"])
        self.user.setReadOnly(purpose!="login_reset")
        state=store.recovery_email_status() if store.actor else None
        self.changing_email=bool(purpose=="bind" and state and state["verified"])
        self.email=self.field("email","받을 복구 이메일 주소 *" if purpose=="bind" else "현재 등록된 복구 이메일 주소 *",email or (state["email"] if state else ""))
        self.email.setPlaceholderText("예: myname@gmail.com / myname@daum.net")
        self.email.setReadOnly(bool(state and state["verified"] and purpose not in {"bind","login_reset"}))
        if self.changing_email:
            self.email.clear();self.email.setPlaceholderText("변경할 새 복구 이메일 주소")
        self.current=self.secret=self.new=self.confirm=None
        if purpose=="bind":
            self.current=self.field("current","현재 로그인 비밀번호",password=True)
        elif purpose.endswith("_enable"):
            self.current=self.field("current","현재 일기장 암호" if purpose.startswith("diary") else "현재 가계부 암호",password=True)
        if purpose.endswith("_reset"):
            if purpose!="login_reset":self.secret=self.field("recovery","최초 복구 메일의 개인 자료 복구키",password=True)
            self.new=self.field("new","새 암호 (8~128자)",password=True)
            self.confirm=self.field("confirm","새 암호 확인",password=True)
        self.code=self.field("code","이메일 인증번호 (8자리)")
        self.code.setMaxLength(8)
        self.email.textEdited.connect(self.invalidate_recipient)
        self.user.textEdited.connect(self.invalidate_recipient)
        self.status=QLabel("주소를 입력하고 ‘인증 메일 요청’을 누르세요. 발송 계정(SMTP) 설정이 필요합니다.");self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.status)
        self.send_button=action("인증 메일 요청",self.send,primary=True);self.body.addWidget(self.send_button)
        self.settings_button=action("이메일 발송 설정 (SMTP)",self.local_mail_settings)
        can_admin=bool(store.actor and (store.actor.get("role")=="admin" or store.actor.get("host_admin")))
        self.settings_button.setEnabled(can_admin)
        self.settings_button.setToolTip("관리자 로그인 후 발송 계정·앱 비밀번호를 설정합니다. 받는 주소 입력만으로는 메일이 발송되지 않습니다.")
        self.body.addWidget(self.settings_button)
        if state and not state["verified"] and purpose!="bind":
            self.body.addWidget(action("복구 이메일 주소 먼저 등록·인증",self.register_email))
        information="인증번호는 10분 동안 1회 사용하며 5회 틀리면 무효입니다. 재요청 시 이전 번호는 무효가 됩니다.\n복구 메일은 등록·인증한 주소로만 보냅니다. 주소 변경은 본인의 현재 로그인 비밀번호와 새 주소 인증이 필요합니다."
        if self.changing_email:
            information+="\n\n주소 변경 시 일기장·가계부 내용과 암호는 유지됩니다. 다만 기존 이메일 복구 설정/복구키는 해제됩니다. 변경 후 각 개인 암호로 이메일 복구를 다시 등록하고 새 복구키 메일을 보관하세요."
        if purpose.startswith(("diary_","household_")):
            information+="\n\n개인 자료 복구를 등록하면 인증 메일에 복구키가 들어 있습니다. 이 최초 메일을 안전하게 보관하세요. 이후 암호 재설정에는 새 인증번호와 최초 메일의 복구키가 모두 필요합니다. 관리자에게 복구키를 자동 보관하지 않습니다. 복구키만으로 또는 새 인증번호만으로는 복구할 수 없습니다."
        info=QLabel(information);info.setWordWrap(True);self.body.addWidget(info)
        self.finish(self.verify)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("인증 후 적용")
        self.scroll_form()
    def local_mail_settings(self):
        dialog=MailSettingsDialog(self.store.private if getattr(self.store,'is_shared_client',False) else self.store,self)
        try:dialog.exec()
        finally:dialog.password.clear();dialog.deleteLater()
    def invalidate_recipient(self,*_):
        self.delivery_ok=False;self.code.clear()
        self.status.setText("주소 또는 아이디가 바뀌었습니다. 입력 내용을 확인하고 인증 메일을 다시 요청하세요.")
    def register_email(self):
        if EmailCodeDialog(self.store,"bind",self,email=self.email.text()).exec():
            self.email.setText(self.store.recovery_email_status()["email"])
            self.status.setText("복구 이메일이 등록되었습니다. 1분 후 이 화면의 인증 메일을 요청하세요.")
    def send(self):
        if self.sending:return
        try:
            from .email_recovery import email_address
            email_address(self.email.text())
            self.job=self.store.prepare_email_code(self.purpose,self.user.text(),self.email.text() if self.email else "",self.current.text() if self.current else "")
        except (ValueError,PermissionError) as exc:
            self.status.setText(str(exc));self.error(exc);return
        if self.current:self.current.clear()
        self.delivery_ok=False;self.code.clear()
        self.sending=True;self.send_button.setEnabled(False);self.send_button.setText("메일 발송 중…")
        self.settings_button.setEnabled(False)
        self.email.setEnabled(False);self.user.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.status.setText("암호화된 연결로 메일을 보내는 중입니다…")
        self.worker=MailWorker(self.job);self.worker.signals.finished.connect(self.sent)
        QThreadPool.globalInstance().start(self.worker)
    def sent(self,success,message):
        self.sending=False;self.send_button.setEnabled(True);self.send_button.setText("인증 메일 다시 요청")
        self.settings_button.setEnabled(bool(self.store.actor and (self.store.actor.get("role")=="admin" or self.store.actor.get("host_admin"))))
        self.email.setEnabled(True);self.user.setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        try:self.store.complete_email_delivery(self.job.identifier,self.job._receipt,success)
        except (ValueError,PermissionError) as exc:self.status.setText(str(exc));return
        self.delivery_ok=success
        self.status.setText(f"{self.job.recipient_mask}로 인증 메일을 보냈습니다. 스팸함도 확인하세요." if success else message)
        if success:self.code.setFocus()
    def verify(self):
        if self.sending or self.job is None or not self.delivery_ok:
            self.error("먼저 인증 메일을 요청하고 수신한 번호를 입력하세요.");return
        if self.changing_email and QMessageBox.question(self,"복구 이메일 변경","새 주소로 변경할까요?\n일기장·가계부 내용은 유지되며 이메일 복구는 각 개인 암호로 다시 등록해야 합니다.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:
            if self.purpose=="bind":self.store.verify_recovery_email(self.job.identifier,self.code.text())
            elif self.purpose.endswith("_enable"):self.store.verify_private_email_recovery(self.purpose.removesuffix("_enable"),self.job.identifier,self.code.text())
            else:
                self.store.reset_password_by_email(self.job.identifier,self.code.text(),self.new.text(),self.confirm.text(),"login" if self.purpose=="login_reset" else self.purpose.removesuffix("_reset"),self.secret.text() if self.secret else "")
            self.clear_secrets();self.accept()
        except (ValueError,PermissionError) as exc:self.error(exc)
    def clear_secrets(self):
        for control in (self.current,self.secret,self.new,self.confirm,self.code):
            if control:control.clear()
        if self.job:self.job._body=""
    def reject(self):
        if self.sending:
            QMessageBox.information(self,"메일 발송 중","발송 결과를 확인한 뒤 닫아 주세요.");return
        self.clear_secrets();super().reject()


class RecoveryEmailDialog(FormDialog):
    def __init__(self,store,parent=None):
        super().__init__("나의 복구 이메일",parent);self.store=store;self.resize(720,620)
        self.email=self.field("email","내 복구 이메일 주소")
        self.email.setPlaceholderText("인증번호를 받을 이메일 주소를 입력하세요")
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);self.body.addWidget(self.status)
        self.register_button=action("이 주소로 인증 메일 요청 · 최초 등록",self.register,primary=True)
        self.body.addWidget(self.register_button)
        self.settings_button=action("이메일 발송 설정 (SMTP)",self.mail_settings)
        self.settings_button.setEnabled(bool(store.actor and (store.actor.get("role")=="admin" or store.actor.get("host_admin"))))
        self.body.addWidget(self.settings_button)
        self.body.addWidget(action("일기장 이메일 복구 등록·재발급",lambda:self.enable("diary")))
        self.body.addWidget(action("가계부 이메일 복구 등록·재발급",lambda:self.enable("household")))
        self.body.addWidget(QLabel("일기장·가계부의 복구키는 등록 메일에만 표시됩니다.\n재발급하려면 현재 개인 암호가 필요하며, 새 메일 인증 완료 후 이전 키가 무효가 됩니다."))
        self.body.addWidget(action("닫기",self.reject));self.refresh()
    def refresh(self):
        state=self.store.recovery_email_status()
        if state['verified']:self.email.setText(state['email'])
        self.email.setReadOnly(state['verified'])
        self.register_button.setText("복구 이메일 변경 · 비밀번호 확인 및 새 주소 인증" if state['verified'] else "이 주소로 인증 메일 요청 · 최초 등록")
        self.status.setText(f"복구 이메일: {state['email'] if state['verified'] else '미등록'}\n일기장 복구: {'등록됨' if state['diary'] else '미등록'} · 가계부 복구: {'등록됨' if state['household'] else '미등록'}\n발송 설정: {'저장됨' if state['smtp_configured'] else '관리자가 먼저 설정해야 합니다'}")
    def register(self):
        if EmailCodeDialog(self.store,"bind",self,email=self.email.text()).exec():self.refresh()
    def mail_settings(self):
        dialog=MailSettingsDialog(self.store.private if getattr(self.store,'is_shared_client',False) else self.store,self)
        try:dialog.exec();self.refresh()
        finally:dialog.password.clear();dialog.deleteLater()
    def enable(self,kind):
        if EmailCodeDialog(self.store,kind+"_enable",self).exec():self.refresh()
