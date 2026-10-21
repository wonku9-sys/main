"""Opt-in standalone/host/client setup and non-destructive live view refresh."""
from hashlib import sha256
import json
from pathlib import Path
import secrets
from PySide6.QtCore import QTimer,QObject,QRunnable,Signal
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import QApplication,QCheckBox,QComboBox,QDialog,QDialogButtonBox,QFileDialog,QHBoxLayout,QLabel,QLineEdit,QMessageBox
from .widgets import FormDialog,action
from .navigation import mark_saved
from .shared_config import load_config,save_config,read_bundle,public_bundle
from .shared_protocol import private_address


class NetworkSettingsDialog(FormDialog):
    def __init__(self,path,store=None,parent=None):
        super().__init__('PC 연결 · 단독/기준/연결 PC 선택',parent);self.store,self.path=store,Path(path);self.resize(780,760)
        try:self.config=load_config(path)
        except ValueError:self.config={'mode':'standalone'}
        self.mode=self.combo('mode','이 PC의 사용 방식',[('단독 사용','standalone'),('기준 PC · 장부 공유','host'),('연결 PC · 기준 PC에 접속','client')],self.config['mode'])
        self.address=self.field('address','기준 PC의 내부 IPv4',self.config.get('address',''));self.port=self.field('port','공유 포트',self.config.get('port',8795))
        self.code=self.field('client_key','연결 코드',self.config.get('client_key',''),password=True)
        visible=QCheckBox('연결 코드 표시');visible.toggled.connect(lambda checked:self.code.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password));self.form.addRow(visible)
        row=QHBoxLayout()
        for title,callback in [('이 PC 주소 선택',self.choose_address),('기준 PC 인증키 생성',self.generate),('연결 파일 불러오기',self.import_bundle),('연결 파일 내보내기',self.export_bundle)]:row.addWidget(action(title,callback))
        self.body.addLayout(row)
        self.certificate=self.config.get('certificate','');self.private_key=self.config.get('private_key','')
        self.fingerprint=QLabel();self.fingerprint.setWordWrap(True);self.body.addWidget(self.fingerprint);self.update_fingerprint()
        self.body.addWidget(action('연결 코드 새로 발급 · 기존 연결 해제',self.rotate))
        notice=QLabel('기준 PC를 한 대만 지정하세요. 같은 장부를 두 기준 PC로 나누지 마세요.\n\n기준 PC에서 연결 파일을 내보내 다른 PC로 복사하고, 연결 PC에서는 파일을 불러온 후 연결 코드를 입력합니다. 기준 PC에 표시된 인증서 지문이 같은지 확인하세요. 연결 파일에는 비밀번호·개인키·업무 자료가 없습니다. 연결 코드는 별도로 안전하게 전달하세요.\n\n기준 PC가 켜져 있어야 공유 입력이 가능합니다. 기준 PC는 고정 내부 IP 사용을 권장하며 Windows 방화벽이 물으면 신뢰하는 개인 네트워크에서만 허용하세요. 인터넷 공유기 포트 개방은 하지 마세요.\n\n서로 다른 버전은 연결하지 않습니다. 업무 자료만 공유하며 가계부·일기장·건강 기록·개인 일정은 각 PC에 남습니다. 백업·복원·직원 권한과 환경설정은 기준 PC에서 관리합니다. 설정은 프로그램을 종료하고 다시 실행하면 적용합니다.');notice.setWordWrap(True);self.body.addWidget(notice)
        self.finish(self.save)
        if getattr(store,'is_shared_client',False):self.body.addWidget(action('미확인 저장 결과 확인',self.resolve_pending))
        if getattr(store,'is_shared_client',False) and (store.actor or {}).get('host_admin'):
            self.body.addWidget(action('이 연결 PC의 개인 자료 백업·복원',self.private_backup))
    def private_backup(self):
        dialog=PersonalBackupDialog(self.store.private,self)
        try:
            if dialog.exec()==2:
                window=self.parentWidget()
                self.accept();window._backup_runtime_enabled=False;window.navigation.suspended=True;window.close()
        finally:dialog.deleteLater()
    def admin(self):
        if not self.store or not self.store.actor or getattr(self.store,'is_shared_client',False):raise PermissionError('기준 PC 설정은 이 PC에 단독으로 관리자 로그인한 뒤 변경하세요.')
        self.store._require('admin')
    def update_fingerprint(self):
        self.fingerprint.setText('인증서 지문 SHA256\n'+sha256(self.certificate.encode()).hexdigest() if self.certificate else '기준 PC 인증키를 만들거나 연결 파일을 불러오세요.')
    def choose_address(self):
        dialog=FormDialog('이 PC의 내부 주소',self);choices=[]
        for address in QNetworkInterface.allAddresses():
            try:value=private_address(address.toString())
            except ValueError:continue
            if value not in [v for _,v in choices]:choices.append((value,value))
        if not choices:self.error('사용 가능한 내부 IPv4 주소가 없습니다. 유선 또는 Wi-Fi 네트워크를 확인하세요.');return
        selected=dialog.combo('address','기준 PC 주소',choices);dialog.finish(dialog.accept)
        if dialog.exec():self.address.setText(selected.currentData())
    def generate(self):
        try:
            self.admin()
            if self.certificate and QMessageBox.question(self,'인증키 교체','인증키를 교체하면 연결 PC에서 연결 파일을 다시 불러와야 합니다. 기존 개인 기록은 이전 연결 프로필에 남습니다. 계속할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            from .shared_server import identity
            config=identity(self.address.text().strip(),int(self.port.text()));self.certificate=config['certificate'];self.private_key=config['private_key'];self.code.setText(config['client_key']);self.update_fingerprint()
        except (ValueError,PermissionError) as exc:self.error(exc)
    def rotate(self):
        try:
            self.admin()
            if QMessageBox.question(self,'연결 코드 변경','기존 PC의 연결이 해제됩니다. 새 코드를 각 PC에 다시 입력해야 합니다. 변경할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:self.code.setText(secrets.token_urlsafe(32))
        except PermissionError as exc:self.error(exc)
    def import_bundle(self):
        path,_=QFileDialog.getOpenFileName(self,'기준 PC 연결 파일','','PC 연결 파일 (*.poslan)')
        if not path:return
        try:
            data=read_bundle(path);self.certificate=data['certificate'];self.private_key='';self.address.setText(data['address']);self.port.setText(str(data['port']));self.mode.setCurrentIndex(self.mode.findData('client'));self.code.clear();self.update_fingerprint()
        except (ValueError,OSError) as exc:self.error(exc)
    def values(self):return {'mode':self.mode.currentData(),'address':self.address.text().strip(),'port':self.port.text(),'certificate':self.certificate,'private_key':self.private_key,'client_key':self.code.text().strip()}
    def export_bundle(self):
        try:
            self.admin()
            if self.mode.currentData()!='host':raise ValueError('기준 PC를 선택하고 인증키를 생성하세요.')
            from .shared_config import validate_config
            config=validate_config(self.values())
            path,_=QFileDialog.getSaveFileName(self,'연결 파일 내보내기','기준PC연결.poslan','PC 연결 파일 (*.poslan)')
            if path:Path(path).write_text(json.dumps(public_bundle(config),ensure_ascii=False,indent=2),encoding='utf-8')
        except (ValueError,PermissionError,OSError) as exc:self.error(exc)
    def save(self):
        try:
            if self.mode.currentData()=='host':self.admin()
            save_config(self.path,self.values());mark_saved(self);self.accept()
            QMessageBox.information(self,'PC 연결 설정 저장','설정을 저장했습니다. 프로그램을 종료하고 다시 실행하면 적용됩니다.')
        except (ValueError,PermissionError,OSError) as exc:self.error(exc)
    def resolve_pending(self):
        try:
            result=self.store.pending_status()
            if result is None:self.error('미확인 저장 요청이 없습니다.');return
            if result['found']:
                if QMessageBox.question(self,'저장 결과 확인',f"기준 PC에 처리 결과가 있습니다: {result['result']}\n해당 전표를 최신 목록에서 확인하고 중복 등록하지 마세요. 미확인 표시를 해제할까요?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:self.store.acknowledge_pending()
            elif QMessageBox.question(self,'복원 이전 요청' if result.get('stale_epoch') else '아직 저장되지 않은 요청',('기준 PC가 복원되었습니다. 이전 입력을 자동으로 다시 등록하지 않습니다. ' if result.get('stale_epoch') else '')+'기준 PC에서 미확인 요청을 취소 처리할까요? 전송이 늦게 도착하더라도 중복 저장되지 않도록 취소 번호를 남깁니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:self.store.cancel_pending()
        except (ValueError,PermissionError,OSError) as exc:self.error(exc)
    def reject(self):
        super().reject()
        if not self.isVisible():
            self.code.clear();guard=getattr(self,'_navigation_guard',None)
            if guard:guard.snapshots.pop(self,None)


class RefreshSignals(QObject):finished=Signal(object,object)
class RefreshWorker(QRunnable):
    def __init__(self,store):super().__init__();self.store=store;self.signals=RefreshSignals()
    def run(self):
        try:self.signals.finished.emit(self.store.poll_status(),None)
        except (ValueError,PermissionError,OSError) as exc:self.signals.finished.emit(None,exc)


class SharedRefresh(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.revision=None;self.changed=False;self.busy=False;self.stopping=False
        self.timer=QTimer(self);self.timer.setInterval(3000);self.timer.timeout.connect(self.tick);self.timer.start()
    def tick(self):
        if self.stopping or self.busy or not self.window.isVisible():return
        store=self.window.store
        if getattr(store,'is_shared_client',False):
            from PySide6.QtCore import QThreadPool
            self.busy=True;self.worker=RefreshWorker(store);self.worker.signals.finished.connect(self.finished);QThreadPool.globalInstance().start(self.worker)
        else:
            try:self.finished({'revision':store.audit_revision()},None)
            except (ValueError,PermissionError):pass
    def finished(self,result,error):
        self.busy=False
        if self.stopping:return
        window=self.window
        if error:
            window.notify(str(error));window.shared_notice.setText('⚠ 공유 연결 확인 · '+str(error));window.shared_notice.show()
            if isinstance(error,PermissionError):
                self.stopping=True;self.timer.stop();window.navigation.suspended=True;window._backup_runtime_enabled=False
                from .household_ui import HouseholdDialog
                from .diary_ui import DiaryDialog
                for dialog in window.findChildren(QDialog):
                    if isinstance(dialog,(HouseholdDialog,DiaryDialog)):
                        try:dialog.save()
                        except (ValueError,PermissionError):pass
                    if hasattr(dialog,'wipe'):dialog.wipe()
                    QDialog.reject(dialog)
                window.hide();QMessageBox.warning(window,'공유 로그인 종료','권한·비밀번호 또는 공유 장부가 변경되었습니다. 프로그램을 다시 실행해 로그인하세요.');window.close()
            return
        if getattr(window.store,'is_shared_client',False):
            try:window.store.apply_status(result)
            except (ValueError,PermissionError,OSError) as exc:self.finished(None,exc);return
        window.shared_notice.hide()
        revision=tuple(result['revision'])
        if self.revision is not None and revision!=self.revision:self.changed=True
        self.revision=revision
        if not self.changed:return
        if QApplication.activeModalWidget() is not None or window.navigation.changed(window.current_page):
            notice='새 공유 자료가 있습니다. 작성 중인 입력은 유지하며 작업을 마치면 자동 갱신합니다.'
            window.notify(notice);window.shared_notice.setText(notice);window.shared_notice.show();return
        try:
            window.current_page.refresh();self.changed=False;window.notify('최신 공유 자료로 자동 갱신했습니다.')
        except (ValueError,PermissionError,OSError) as exc:window.notify(str(exc))
    def stop(self):self.stopping=True;self.timer.stop()


class PersonalBackupDialog(QDialog):
    """Host admins can manage a client's private profile without business RPC."""
    def __init__(self,store,parent=None):
        from .widgets import DataGrid
        from PySide6.QtWidgets import QVBoxLayout
        super().__init__(parent);self.store=store;store._require('admin');self.setWindowTitle('이 연결 PC의 개인 자료 백업·복원');self.resize(820,510)
        body=QVBoxLayout(self);note=QLabel('이 PC의 일기장·가계부·건강·첨부 자료만 백업합니다. 기준 PC의 업무 장부는 변경하지 않습니다.\n선택 복원은 이 개인 저장소 전체를 교체하고 프로그램을 종료합니다. 다른 사용자의 로컬 개인 자료도 백업 시점으로 돌아갑니다.');note.setWordWrap(True);body.addWidget(note)
        self.grid=DataGrid(['백업 생성일','파일 이름','종류','크기(KB)']);body.addWidget(self.grid,1);buttons=QHBoxLayout()
        for label,fn in [('지금 백업',self.backup),('선택 파일 복원',self.restore_selected),('외부 백업 선택',self.restore_external),('닫기',self.reject)]:buttons.addWidget(action(label,fn))
        body.addLayout(buttons);body.addWidget(QLabel('종료 자동 백업이 기본 적용됩니다. 매주 오래된 관리 백업을 정리하되 최근 15개는 보존합니다.'));self.refresh()
    def refresh(self):
        rows=self.store.backup_files();self.grid.fill([[r['created'],r['name'],r['kind'],f"{r['size']/1024:.1f}"] for r in rows],rows)
    def backup(self):
        try:self.store.create_backup();self.refresh();QMessageBox.information(self,'개인 자료 백업','이 PC의 개인 자료를 백업했습니다.')
        except (ValueError,PermissionError,OSError) as exc:QMessageBox.warning(self,'백업 실패',str(exc))
    def restore_selected(self):
        record=self.grid.selected()
        if record:self.restore(record['path'])
    def restore_external(self):
        path,_=QFileDialog.getOpenFileName(self,'개인 자료 백업 선택','','독립판 백업 (*.db)')
        if path:self.restore(path)
    def restore(self,path):
        from PySide6.QtWidgets import QInputDialog
        try:
            info=self.store.inspect_backup(path)
            if any(info['counts'][name] for name in ('products','partners','documents','members','point_entries')):raise ValueError('업무 자료가 들어 있는 백업입니다. 연결 PC의 개인 저장소 백업을 선택하세요.')
            if QMessageBox.warning(self,'개인 자료 복원 주의','이 PC의 개인 자료 전체가 선택한 백업으로 바뀝니다. 현재 자료는 보호 백업 후 교체됩니다. 계속할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            password,accepted=QInputDialog.getText(self,'본인 확인','현재 로그인 비밀번호',QLineEdit.EchoMode.Password)
            if not accepted:return
            try:self.store.restore_backup(path,password,info['digest'])
            finally:password=''
            QMessageBox.information(self,'복원 완료','이 PC의 개인 자료를 복원했습니다. 프로그램을 다시 실행해 로그인하세요.');self.done(2)
        except (ValueError,PermissionError,OSError) as exc:QMessageBox.warning(self,'복원 실패',str(exc))
