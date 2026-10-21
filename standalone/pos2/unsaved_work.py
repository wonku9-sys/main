"""Encrypted, local crash journal. Restoring never calls a business save/post."""
import base64
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sys
import weakref
from PySide6.QtCore import QObject,QTimer,QEvent,QIODevice,QSaveFile,QDate,QTime,Qt
from PySide6.QtWidgets import (QApplication,QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTextEdit,QLineEdit,QComboBox,QCheckBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QTableWidget,QMessageBox)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from . import windows_secrets
from .widgets import action,DataGrid

CONTROLS=(QTimeEdit,QDateEdit,QComboBox,QCheckBox,QDoubleSpinBox,QSpinBox,QTextEdit,QLineEdit)
EXCLUDE=('암호','비밀번호','인증','이메일 발송','로그인','복구 이메일','메일 전송','문서 이미지 이메일')


def controls(owner):
    counts={}
    for widget in owner.findChildren(QWidget):
        if not isinstance(widget,CONTROLS):continue
        ancestor=widget.parentWidget();inside_table=False
        while ancestor is not None and ancestor is not owner:
            if isinstance(ancestor,QTableWidget):inside_table=True;break
            ancestor=ancestor.parentWidget()
        if inside_table:continue
        # Skip editors internal to another typed Qt control, plus passwords.
        if isinstance(widget,QLineEdit) and (widget.echoMode()!=QLineEdit.EchoMode.Normal or isinstance(widget.parentWidget(),(QComboBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox))):continue
        kind=type(widget).__name__;index=counts.get(kind,0);counts[kind]=index+1
        yield f'{kind}:{index}',widget


def capture_values(owner):
    values={}
    for path,widget in controls(owner):
        if isinstance(widget,QTimeEdit):value={'time':widget.time().toString('HH:mm')}
        elif isinstance(widget,QDateEdit):value={'date':widget.date().toString('yyyy-MM-dd')}
        elif isinstance(widget,QComboBox):
            data=widget.currentData();value={'combo':data if isinstance(data,(str,int,type(None))) else None,'text':widget.currentText()}
        elif isinstance(widget,QCheckBox):value={'check':widget.isChecked()}
        elif isinstance(widget,(QSpinBox,QDoubleSpinBox)):value={'number':widget.value()}
        elif isinstance(widget,QTextEdit):value={'text':widget.toPlainText()}
        else:value={'text':widget.text()}
        values[path]=value
    tables=[]
    for table in owner.findChildren(QTableWidget):
        if table.editTriggers()==table.EditTrigger.NoEditTriggers:continue
        if any(table.cellWidget(r,c) is not None for r in range(table.rowCount()) for c in range(table.columnCount())):continue
        if table.rowCount()*table.columnCount()>20000:continue
        tables.append([[table.item(r,c).text() if table.item(r,c) else '' for c in range(table.columnCount())] for r in range(table.rowCount())])
    payload={'values':values,'tables':tables}
    if type(owner).__name__=='TradeDialog':
        try:payload['trade']=owner.payload()
        except ValueError:
            payload['trade']=dict(lines=[dict(product_id=row['product'].currentData(),unit_id=row['unit'].currentData(),qty=row['qty'].text(),unit_price=row['price'].text(),source_line_id=(row.get('source') or {}).get('id')) for row in owner.line_rows if row['product'].currentData()])
    if type(owner).__name__=='SalesFormDialog':payload['lines']=[dict(product_id=row['product'].currentData(),unit_id=row['unit'].currentData(),qty=row['qty'].text(),unit_price=row['price'].text()) for row in owner.rows]
    if type(owner).__name__=='DiaryDialog':payload['diary']=owner.snapshot()
    if type(owner).__name__=='HouseholdDialog':payload['household']=owner.snapshot()
    if type(owner).__name__=='CountEditor':payload['count_snapshot']=owner.snapshot;payload['counts']={str(key):field.text() for key,field in owner.inputs.items()}
    return payload


def apply_values(owner,payload):
    if 'household' in payload:
        owner.memo_date=payload['household'][0];owner.calendar.blockSignals(True);owner.calendar.setSelectedDate(QDate.fromString(owner.memo_date,'yyyy-MM-dd'));owner.calendar.blockSignals(False)
    if 'trade' in payload:
        data=payload['trade']
        while owner.line_rows:owner.remove_line(owner.line_rows[-1])
        for line in data['lines']:
            source=next((r for r in (owner.source or owner.record or {}).get('lines',[]) if r.get('id')==line.get('source_line_id')),None)
            owner.add_line(line['product_id'],line['unit_id'],line['qty'],line['unit_price'],source)
    elif 'lines' in payload and hasattr(owner,'rows'):
        for row in list(owner.rows):owner.remove(row)
        for line in payload['lines']:owner.add_line(line['product_id'],line)
    widgets=dict(controls(owner))
    # Product/unit changes recalculate prices: restore all text only afterwards.
    for path,value in payload.get('values',{}).items():
        widget=widgets.get(path)
        if widget is None:continue
        if 'combo' in value and isinstance(widget,QComboBox):
            index=widget.findData(value['combo']) if value['combo'] is not None else widget.findText(value['text'])
            if index<0 and value['text']:raise ValueError('상품·거래처·선택 항목이 변경되었습니다. 임시본 내용을 확인해 새로 선택하세요.')
            widget.setCurrentIndex(index)
        elif 'check' in value and isinstance(widget,QCheckBox):widget.setChecked(value['check'])
        elif 'date' in value and isinstance(widget,QDateEdit):widget.setDate(QDate.fromString(value['date'],'yyyy-MM-dd'))
        elif 'time' in value and isinstance(widget,QTimeEdit):widget.setTime(QTime.fromString(value['time'],'HH:mm'))
        elif 'number' in value and isinstance(widget,(QSpinBox,QDoubleSpinBox)):widget.setValue(value['number'])
    for path,value in payload.get('values',{}).items():
        widget=widgets.get(path)
        if 'text' in value and 'combo' not in value:
            if isinstance(widget,QTextEdit):widget.setPlainText(value['text'])
            elif isinstance(widget,QLineEdit):widget.setText(value['text'])
    from PySide6.QtWidgets import QTableWidgetItem
    tables=[table for table in owner.findChildren(QTableWidget) if table.editTriggers()!=table.EditTrigger.NoEditTriggers and not any(table.cellWidget(r,c) is not None for r in range(table.rowCount()) for c in range(table.columnCount()))]
    for table,rows in zip(tables,payload.get('tables',[])):
        table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[:table.columnCount()]):table.setItem(r,c,QTableWidgetItem(value))
    if 'diary' in payload:owner.identifier=payload['diary'][0]
    if 'household' in payload:owner.memo_date=payload['household'][0]
    if 'count_snapshot' in payload:
        owner.snapshot={int(key):value for key,value in payload['count_snapshot'].items()}
        for key,value in payload['counts'].items():
            if int(key) in owner.inputs:owner.inputs[int(key)].setText(value)


class CrashJournal(QObject):
    def __init__(self,desktop,testing=False):
        super().__init__(desktop);self.desktop=desktop;self.store=desktop.store;self.local=getattr(self.store,'private',self.store)
        self.enabled=bool(self.local.path and (sys.platform=='win32' or testing));self.pending=None;self.restoring=False;self.owners=weakref.WeakKeyDictionary();self.hashes=weakref.WeakKeyDictionary();self.reported=False
        identity=str(self.store.actor['id'])+'|'+str(getattr(self.local,'_restore_token',''))+'|'+str(getattr(self.store,'restore_epoch',''))
        self.identity=sha256(identity.encode()).hexdigest();self.root=self.local.path.parent/'unsaved-work'/self.identity
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.capture_all)
        if self.enabled:QApplication.instance().installEventFilter(self);self.timer.start()
    def owner_private(self,owner):
        current=owner
        while current is not None:
            name=type(current).__name__
            if name in {'DiaryDialog','HouseholdDialog'}:return ('diary' if name=='DiaryDialog' else 'household'),current
            current=current.parentWidget()
        return '',None
    def bind(self,owner):
        # Never queue/replay a payment editor as an ordinary recoverable form.
        # Its live optimistic balance token must be obtained again after login.
        if type(owner).__name__=='PurchasePaymentDialog':return
        if not self.enabled or owner in self.owners:return
        if any(word in owner.windowTitle() for word in EXCLUDE):return
        if not self.desktop.navigation.editable(owner):return
        self.owners[owner]=secrets.token_hex(16)
        if isinstance(owner,QDialog):owner.finished.connect(lambda result,reference=weakref.ref(owner):self.forget(reference()) if result==QDialog.DialogCode.Accepted and reference() is not None else None)
    def forget(self,owner):
        identifier=self.owners.get(owner)
        if identifier:
            target=self.root/(identifier+'.draft')
            if target.is_file() and not target.is_symlink():target.unlink()
    def write(self,identifier,meta,payload,key=None):
        content=json.dumps(payload,ensure_ascii=False,default=str).encode('utf-8')
        if len(content)>2_000_000:raise ValueError('임시 작업이 너무 큽니다. 직접 저장하세요.')
        if key is not None:
            nonce=secrets.token_bytes(12);content=nonce+AESGCM(bytes(key)).encrypt(nonce,content,(self.identity+'|'+identifier).encode());meta=dict(meta,sealed=True)
        envelope=dict(identity=self.identity,meta=meta,payload=base64.b64encode(content).decode('ascii'))
        cipher=windows_secrets.protect(json.dumps(envelope,ensure_ascii=False).encode('utf-8'))
        if self.root.is_symlink() or self.root.parent.is_symlink():raise ValueError('임시 작업 경로에 링크를 사용할 수 없습니다.')
        self.root.mkdir(parents=True,exist_ok=True);target=self.root/(identifier+'.draft')
        if not target.exists() and sum(1 for _ in self.root.glob('*.draft'))>=100:raise ValueError('임시본이 100개 있습니다. 미저장 작업 복구에서 필요 없는 임시본을 확인·삭제하세요.')
        if target.is_symlink():raise ValueError('임시 작업 파일에 링크를 사용할 수 없습니다.')
        output=QSaveFile(str(target))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(cipher)!=len(cipher) or not output.commit():raise OSError('임시 작업 보관에 실패했습니다. 디스크 공간을 확인하고 직접 저장하세요.')
    def rows(self):
        if not self.enabled or not self.root.exists():return []
        if self.root.is_symlink() or self.root.parent.is_symlink():raise ValueError('임시 작업 경로를 확인하세요.')
        rows=[]
        for path in sorted(self.root.glob('*.draft'))[:100]:
            if path.is_symlink() or path.stat().st_size>3_000_000:continue
            try:
                envelope=json.loads(windows_secrets.unprotect(path.read_bytes()))
                if envelope['identity']==self.identity:rows.append(dict(envelope['meta'],identifier=path.stem))
            except (ValueError,KeyError,UnicodeError):continue
        return sorted(rows,key=lambda row:row['date'],reverse=True)
    def read(self,identifier,key=None):
        if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('임시 작업 번호를 확인하세요.')
        path=self.root/(identifier+'.draft')
        if path.is_symlink() or path.stat().st_size>3_000_000:raise ValueError('임시 작업 파일을 확인하세요.')
        envelope=json.loads(windows_secrets.unprotect(path.read_bytes()))
        if envelope['identity']!=self.identity:raise PermissionError('다른 계정·복원 이전의 임시 작업은 열 수 없습니다.')
        payload=base64.b64decode(envelope['payload'],validate=True)
        if envelope['meta'].get('sealed'):
            if key is None:raise PermissionError('개인 기록 암호를 먼저 입력해 잠금을 해제하세요.')
            from cryptography.exceptions import InvalidTag
            try:payload=AESGCM(bytes(key)).decrypt(payload[:12],payload[12:],(self.identity+'|'+identifier).encode())
            except InvalidTag:raise PermissionError('개인 기록 암호가 바뀌었거나 임시본이 손상되었습니다.') from None
        return json.loads(payload)
    def capture(self,owner):
        if not self.enabled or self.restoring or not self.desktop.navigation.changed(owner):return
        self.bind(owner)
        if owner not in self.owners:return
        kind,private=self.owner_private(owner)
        if private is not None and getattr(private,'closed_securely',False):return
        record=getattr(owner,'record',None) or {};record=record if isinstance(record,dict) else {}
        from .permissions import menu_key_for
        current=owner;route=None
        while current is not None and route is None:route=menu_key_for(current);current=current.parentWidget()
        meta=dict(title='개인 기록 임시본' if kind else owner.windowTitle() or getattr(owner,'title','작업'),private=kind,route=kind or route or self.desktop.current_key,owner=type(owner).__name__,record_id=record.get('id') or getattr(owner,'_recovery_record_id',None),token=record.get('_edit_token'),kind=getattr(owner,'kind',''),source_id=(getattr(owner,'source',None) or {}).get('id') or record.get('source_id'),date=datetime.now().astimezone().isoformat(timespec='seconds'))
        if type(owner).__name__=='SalesFormDialog':meta['source_ids']=owner.source_ids or (record or {}).get('source_ids',[])
        meta['form_tag']=sha256(owner.windowTitle().encode()).hexdigest();meta['form_role']=getattr(owner,'_recovery_role','')
        payload=capture_values(owner);digest=sha256(json.dumps(payload,ensure_ascii=False,default=str).encode()).hexdigest()
        if self.hashes.get(owner)==digest and (self.root/(self.owners[owner]+'.draft')).exists():return
        self.write(self.owners[owner],meta,payload,private.key if private else None);self.hashes[owner]=digest
    def capture_all(self):
        try:
            for owner in list(self.desktop.navigation.snapshots):
                if owner.isVisible():self.capture(owner)
        except (ValueError,PermissionError,OSError,RuntimeError) as exc:
            if not self.reported:self.desktop.notify('임시 작업 보관 확인: '+str(exc));self.reported=True
    def eventFilter(self,owner,event):
        kind=event.type()
        if kind not in (QEvent.Type.Show,QEvent.Type.Close):return False
        if not isinstance(owner,QDialog) or not self.desktop.navigation.belongs(owner):return False
        if kind==QEvent.Type.Show:
            QTimer.singleShot(0,self,lambda:self.shown(owner))
        elif kind==QEvent.Type.Close:
            try:self.capture(owner)
            except (ValueError,PermissionError,OSError,RuntimeError):pass
        return False
    def shown(self,owner):
        from shiboken6 import isValid
        if not isValid(owner) or not owner.isVisible():return
        self.bind(owner)
        if owner in self.owners and self.pending and self.pending['owner']==type(owner).__name__:
            if self.pending.get('form_tag')!=sha256(owner.windowTitle().encode()).hexdigest():return
            if type(owner).__name__=='FormDialog' and self.pending.get('private'):
                kind,_=self.owner_private(owner)
                if kind!=self.pending['private']:return
            self.restore_to(owner,self.pending)
    def restore_to(self,owner,meta):
        try:
            _,private=self.owner_private(owner)
            payload=self.read(meta['identifier'],private.key if private else None)
            record=getattr(owner,'record',None) or {}
            if meta.get('token') and record.get('_edit_token')!=meta['token']:raise ValueError('다른 PC 또는 이후 작업에서 원본이 변경되었습니다. 임시 내용을 확인하고 새 기록으로 옮기세요.')
            self.restoring=True;apply_values(owner,payload);self.owners[owner]=meta['identifier'];self.pending=None
            self.desktop.notify('미저장 작업을 입력창으로 복구했습니다. 내용을 확인한 뒤 직접 저장하세요. 재고·결제는 아직 변경되지 않았습니다.')
        except (ValueError,PermissionError,OSError) as exc:QMessageBox.warning(owner,'임시 작업 복구',str(exc))
        finally:self.restoring=False
    def show_center(self):
        if not self.enabled:QMessageBox.information(self.desktop,'미저장 작업 복구','암호화 임시 보관은 Windows 실행판에서 사용할 수 있습니다.');return
        RecoveryCenter(self).exec()
    def offer(self):
        if not self.desktop.isVisible():return
        if QApplication.activeModalWidget() is not None:QTimer.singleShot(500,self,self.offer);return
        if self.rows():self.show_center()
    def stop(self):
        self.timer.stop()
        if self.enabled:QApplication.instance().removeEventFilter(self)


class RecoveryCenter(QDialog):
    def __init__(self,journal):
        super().__init__(journal.desktop);self.journal=journal;self.setWindowTitle('미저장 작업 복구');self.resize(940,650)
        layout=QVBoxLayout(self);note=QLabel('비정상 종료 전에 약 2초 간격으로 암호화 보관한 임시본입니다.\n복구해도 전표·재고·결제가 확정되지 않습니다. 개인 기록은 다시 암호를 입력해 열어야 합니다.');note.setWordWrap(True);layout.addWidget(note)
        self.grid=DataGrid(['임시 보관 시각','화면','개인 잠금','작업']);layout.addWidget(self.grid,1)
        self.preview=QTextEdit();self.preview.setReadOnly(True);self.preview.setMaximumHeight(160);layout.addWidget(self.preview)
        tools=QHBoxLayout();tools.addWidget(action('선택 임시본 복구',self.restore,primary=True));tools.addWidget(action('입력 내용 확인',self.inspect));tools.addWidget(action('선택 임시본 삭제',self.remove,danger=True));tools.addWidget(action('나중에 · 닫기',self.reject));layout.addLayout(tools);self.refresh()
    def refresh(self):
        rows=self.journal.rows();self.grid.fill([[row['date'][:19].replace('T',' '),row['title'],'잠김' if row.get('private') else 'Windows 암호화',row['owner']] for row in rows],rows)
    def inspect(self):
        row=self.grid.selected()
        if not row:return
        key=None
        if row.get('private'):
            from .private_session import cached_key
            key=cached_key(self.journal.local,row['private'])
            if key is None:self.preview.setPlainText('일기장·가계부에서 개인 암호로 먼저 잠금을 해제한 뒤 내용을 확인하세요.');return
        try:self.preview.setPlainText(json.dumps(self.journal.read(row['identifier'],key),ensure_ascii=False,indent=2))
        except (ValueError,PermissionError,OSError) as exc:self.preview.setPlainText(str(exc))
    def remove(self):
        row=self.grid.selected()
        if row and QMessageBox.question(self,'임시본 삭제','이 미저장 임시본을 삭제할까요? 저장된 원본 자료는 바뀌지 않습니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            path=self.journal.root/(row['identifier']+'.draft')
            if not path.is_symlink():path.unlink(missing_ok=True)
            self.preview.clear();self.refresh()
    def restore(self):
        row=self.grid.selected()
        if not row:return
        journal=self.journal;window=journal.desktop;store=window.store
        try:
            window.store.require_menu(row['route']);journal.pending=row
            self.accept()
            if row.get('private'):
                window.open_page(row['private']);owner=window.personal_windows.get(row['private'])
                if owner and type(owner).__name__==row['owner']:journal.restore_to(owner,row)
                elif owner:
                    # Nested household entry: opening its normal editor retains
                    # the original store validation and attachment workflow.
                    if row['owner']=='FormDialog' and row.get('form_role')=='household_entry':
                        record=None
                        if row.get('record_id'):
                            record=next((r for r in owner.store.household_report(owner.key,'1900-01-01','9999-12-31')['rows'] if r['id']==row['record_id']),None)
                            if record is None:raise ValueError('원래 개인 기록이 삭제되었습니다. 임시본은 보존합니다.')
                        owner.editor(record)
                    else:
                        journal.pending=None;QMessageBox.information(window,'개인 임시본 확인','개인 잠금을 해제했습니다. 미저장 작업 복구의 입력 내용 확인에서 임시본을 확인하고 원래 입력 화면에 옮겨 저장하세요.')
                return
            name=row['owner'];record=None
            if name=='ProductDialog':
                from .catalog_ui import ProductDialog
                try:
                    record=store.catalog_product(row['record_id']) if row['record_id'] else None
                except ValueError:
                    record=None
                if row['record_id'] and not record:raise ValueError('원상품이 삭제되었습니다. 임시 내용을 확인해 새 상품으로 등록하세요.')
                dialog=ProductDialog(store,record,window)
            elif name=='TradeDialog':
                from .workflow_ui import TradeDialog
                dialog=TradeDialog(window,row['kind'],row['record_id'],row.get('source_id'))
                if dialog.readonly:raise ValueError('이미 확정된 전표입니다. 임시본으로 덮어쓸 수 없습니다.')
            elif name=='CountEditor':
                from .workflow_ui import CountEditor
                dialog=CountEditor(window)
            elif name=='SupplierDialog':
                from .supplier_ui import SupplierDialog
                record=next((p for p in store.partners('supplier') if p['id']==row['record_id']),None) if row['record_id'] else None
                if row['record_id'] and not record:raise ValueError('원공급사가 삭제되었습니다.')
                dialog=SupplierDialog(window,record)
            elif name=='SalesFormDialog':
                from .offline_ui import SalesFormDialog
                record=store.sales_form(row['record_id']) if row['record_id'] else None
                dialog=SalesFormDialog(window,row['route'],record,source_ids=row.get('source_ids'),parent=window)
            elif name in {'SettingsPage','StoreProfilePage'}:
                window.open_page(row['route']);journal.restore_to(window.current_page,row);return
            else:
                window.open_page(row['route']);page=window.current_page
                if hasattr(page,'editor') and row.get('form_role')=='worklog':
                    record=None
                    if row.get('record_id') and row['route']=='worklog':record=next((r for r in store.work_logs('1900-01-01','9999-12-31') if r['id']==row['record_id']),None)
                    if row.get('record_id') and record is None:raise ValueError('원래 기록이 삭제되었습니다. 임시본은 보존합니다.')
                    page.editor(record)
                else:raise ValueError('이 보조 입력창은 입력 내용 확인에서 임시본을 확인해 원래 화면에 직접 다시 입력하세요. 임시본은 삭제하지 않았습니다.')
                return
            # Modeless edit window: keep its reference until closed.
            if not hasattr(window,'_recovered_editors'):window._recovered_editors=[]
            window._recovered_editors.append(dialog);dialog.setWindowModality(Qt.WindowModality.NonModal);dialog._desktop_owner=window
            dialog.show();journal.restore_to(dialog,row)
        except (ValueError,PermissionError,OSError) as exc:
            journal.pending=None;QMessageBox.warning(window,'임시 작업 복구',str(exc))
