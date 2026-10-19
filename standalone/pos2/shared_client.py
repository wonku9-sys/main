"""Verified-TLS LAN client with durable, exactly-once write retry identities."""
from hashlib import sha256
import http.client
import json
from pathlib import Path
import secrets
import socket
import ssl
import tempfile
from uuid import uuid4

from . import __version__
from . import windows_secrets
from .common import PERMISSIONS
from .shared_protocol import PRIVATE,READS,WRITES,decode,encode,fingerprint,private_address
from .store import Store,password_hash

EMAIL_LOCAL=frozenset('mail_settings save_mail_settings recovery_email_status verify_recovery_email verify_private_email_recovery complete_email_delivery'.split())


class LanTransport:
    def __init__(self,config,allow_loopback=False):
        self.config=config;private_address(config['address'],allow_loopback)
        self.context=ssl.create_default_context(cadata=config['certificate']);self.context.minimum_version=ssl.TLSVersion.TLSv1_2
        self.session=''
    def request(self,message):
        message=dict(message,version=__version__)
        connection=http.client.HTTPSConnection(self.config['address'],self.config['port'],context=self.context,timeout=6)
        try:
            body=encode(message).encode();headers={'Content-Type':'application/json','X-Client-Key':self.config['client_key']}
            if self.session:headers['Authorization']='Bearer '+self.session
            connection.request('POST','/api',body,headers);response=connection.getresponse();raw=response.read(64_000_001)
            if len(raw)>64_000_000:raise ValueError('조회 자료가 너무 많습니다. 기간이나 검색 조건을 줄이세요.')
            data=decode(raw)
            if not isinstance(data,dict) or 'ok' not in data:raise OSError('올바르지 않은 공유 응답입니다.')
            if not data['ok']:
                if data.get('kind')=='permission':raise PermissionError(data['error'])
                raise ValueError(data['error'])
            return data['result']
        except PermissionError:raise
        except (OSError,ssl.SSLError,http.client.HTTPException,json.JSONDecodeError) as exc:
            raise ConnectionError('기준 PC 연결을 확인하세요. 저장 중 끊겼다면 같은 내용으로 다시 저장하면 중복 없이 결과를 확인합니다.') from exc
        finally:connection.close()


class ClientStore:
    is_shared_client=True
    migration_backup_path=None
    def __init__(self,config,private_path,allow_loopback=False):
        self.transport=LanTransport(config,allow_loopback);self.path=Path(private_path)
        self.transport.request({'command':'hello'})
        self.private=Store(self.path);self.actor=None
        self.pending_path=self.path.with_suffix('.pending');self.pending=None
        try:
            if self.pending_path.exists():self.pending=decode(windows_secrets.unprotect(self.pending_path.read_bytes()))
        except BaseException:self.private.close();raise

    def _persist_pending(self):
        payload=windows_secrets.protect(encode(self.pending).encode())
        if self.pending_path.is_symlink():raise ValueError('미확인 요청 파일에 링크 경로를 사용할 수 없습니다.')
        with tempfile.NamedTemporaryFile(dir=self.pending_path.parent,prefix='request-',suffix='.part',delete=False) as stream:
            temporary=Path(stream.name);stream.write(payload)
        try:temporary.replace(self.pending_path)
        finally:
            if temporary.exists():temporary.unlink()

    def users_count(self):return max(1,self.transport.request({'command':'hello'})['users'])
    def default_login_available(self):return False
    def default_settings(self):raise ValueError('공유 환경설정은 기준 PC에서 변경하세요.')
    def login(self,code,password):
        result=self.transport.request({'command':'login','code':code,'password':password});self.transport.session=result['session'];self.actor=result['actor'];self.restore_epoch=result['restore_epoch']
        # Mirror only this authenticated identity. Never copy business rows or a
        # server password hash into the client's personal database.
        with self.private._tx():
            if not self.private.db.execute('SELECT 1 FROM users WHERE id=-1').fetchone():
                self.private.db.execute("INSERT INTO users(id,code,name,password_hash,role,permissions) VALUES(-1,?,'개인 저장소 시스템',?,'admin',?)",('__private_'+secrets.token_hex(8),password_hash(secrets.token_urlsafe(32)),json.dumps(sorted(PERMISSIONS))))
            digest=password_hash(password)
            # A renamed account must not collide with an older shadow's former
            # login code. Stable numeric IDs own private records, not usernames.
            self.private.db.execute('UPDATE users SET code=? WHERE code=? AND id<>?',('__shadow_'+secrets.token_hex(16),self.actor['code'],self.actor['id']))
            self.private.db.execute("INSERT INTO users(id,code,name,password_hash,role,permissions,active) VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET code=excluded.code,name=excluded.name,password_hash=excluded.password_hash,role=excluded.role,permissions=excluded.permissions,active=1",(self.actor['id'],self.actor['code'],self.actor['name'],digest,'admin' if self.actor.get('host_admin') else self.actor['role'],json.dumps(self.actor['permissions'])))
        self.private.actor=dict(self.actor);self.private._session_password_hash=digest;self.private._restore_token=self.private._current_restore_token()
        self.private._require()
        return self.actor

    def logout(self):
        try:
            if self.transport.session:self.transport.request({'command':'logout'})
        except (ValueError,PermissionError,ConnectionError):pass
        self.transport.session='';self.actor=None;self.private.logout()
    def close(self):self.logout();self.private.close()
    def _require(self,*permissions):
        self.actor=self.transport.request({'command':'authorize','permissions':list(permissions)});return self.actor
    def _require_capability(self,menu,operation):
        self.actor=self.transport.request({'command':'authorize','menu':menu,'operation':operation});return self.actor
    def _require_household_key(self,key):return self.private._require_household_key(key)
    def require_menu(self,menu):
        self.actor=self.transport.request({'command':'authorize','menu':menu});return self.actor
    def audit_revision(self):return tuple(self.transport.request({'command':'status'})['revision'])
    def poll_status(self):return self.transport.request({'command':'status'})
    def apply_status(self,result):
        self.actor=result['actor']
        with self.private._tx():self.private.db.execute('UPDATE users SET role=?,permissions=? WHERE id=?',('admin' if self.actor.get('host_admin') else self.actor['role'],json.dumps(self.actor['permissions']),self.actor['id']))
        self.private._require()
    def run_scheduled_backup(self,*args,**kwargs):return self.private.run_scheduled_backup(*args,**kwargs)
    def backup_on_exit(self,*args,**kwargs):return self.private.backup_on_exit(*args,**kwargs)
    def run_backup_retention(self,*args,**kwargs):return self.private.run_backup_retention(*args,**kwargs)
    def change_password(self,old,new):
        self.transport.request({'command':'change_password','old':old,'new':new})
        self.private.change_password(old,new)
    def prepare_email_code(self,purpose,*args,**kwargs):
        if purpose=='login_reset':raise ValueError('공유 계정의 로그인 암호 복구는 기준 PC에서 실행하세요.')
        return self.private.prepare_email_code(purpose,*args,**kwargs)
    def reset_password_by_email(self,*args,**kwargs):
        kind=kwargs.get('kind',args[4] if len(args)>4 else 'login')
        if kind=='login':raise ValueError('공유 계정의 로그인 암호 복구는 기준 PC에서 실행하세요.')
        return self.private.reset_password_by_email(*args,**kwargs)
    def pending_status(self):
        if not self.pending:return None
        self._pending_owner()
        result=self.transport.request({'command':'pending_result','request_id':self.pending['request_id']})
        result['stale_epoch']=self.pending.get('restore_epoch')!=self.restore_epoch
        return result
    def _pending_owner(self):
        if not self.actor or self.pending.get('owner_id')!=self.actor['id']:raise PermissionError('이 PC에 다른 계정의 미확인 저장 요청이 있습니다. 원래 계정으로 로그인해 결과를 확인하세요.')
    def acknowledge_pending(self):
        result=self.pending_status()
        if not result or not result['found']:raise ValueError('기준 PC에 저장 결과가 없습니다. 같은 요청을 재시도하거나 취소 처리하세요.')
        self._clear_pending();return result
    def _clear_pending(self):
        previous=self.pending;self.pending=None
        try:self._persist_pending()
        except (ValueError,OSError) as exc:
            self.pending=previous
            raise ConnectionError('저장 결과를 이 PC에 기록하지 못했습니다. 미확인 요청은 유지했습니다. 디스크 상태를 확인한 뒤 같은 요청의 결과를 다시 확인하세요.') from exc
    def cancel_pending(self):
        if not self.pending:return True
        self._pending_owner()
        result=self.transport.request({'command':'cancel_pending','request_id':self.pending['request_id'],'payload_hash':fingerprint({k:self.pending[k] for k in ('method','args','kwargs')})})
        if result['cancelled']:self._clear_pending()
        return result
    def __getattr__(self,name):
        if name.startswith('_'):raise AttributeError(name)
        if name in PRIVATE|EMAIL_LOCAL:return getattr(self.private,name)
        if name not in READS|WRITES:
            def unsupported(*args,**kwargs):raise ValueError('이 기능은 기준 PC에서 실행하세요. 연결·백업·직원 권한 설정은 기준 PC에서 관리합니다.')
            return unsupported
        def call(*args,**kwargs):
            message={'command':'call','method':name,'args':list(args),'kwargs':kwargs}
            had_pending=bool(self.pending)
            if name in WRITES:
                signature=fingerprint({k:message[k] for k in ('method','args','kwargs')})
                if self.pending:
                    self._pending_owner()
                    if self.pending.get('restore_epoch')!=self.restore_epoch:raise ValueError('기준 PC가 복원되어 이전 요청을 재시도할 수 없습니다. 공유 연결 메뉴에서 미확인 요청을 취소 처리하고 최신 장부를 확인하세요.')
                    previous=fingerprint({k:self.pending[k] for k in ('method','args','kwargs')})
                    if previous!=signature:raise ValueError('결과를 확인하지 못한 저장 요청이 있습니다. 같은 입력으로 다시 저장하거나 공유 연결 메뉴에서 결과를 확인하세요.')
                    message=self.pending
                else:
                    message.update(request_id=uuid4().hex,owner_id=self.actor['id'],restore_epoch=self.restore_epoch);self.pending=message
                self._persist_pending()
            try:result=self.transport.request(message)
            except ConnectionError:raise
            except (ValueError,PermissionError):
                if name in WRITES and not had_pending:self._clear_pending()
                raise
            else:
                if name in WRITES:self._clear_pending()
                return result
        return call
