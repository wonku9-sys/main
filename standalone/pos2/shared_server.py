"""Opt-in certificate-verified LAN service embedded in the selected host PC."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import inspect
import ipaddress
import json
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import tempfile
import threading
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID

from . import __version__
from .common import now
from .store import Store
from .shared_protocol import READS,WRITES,client_actor,decode,encode,fingerprint,private_address


def identity(address,port=8795,allow_loopback=False):
    address=private_address(address,allow_loopback)
    if type(port) is not int or not 1024<=port<=65535:raise ValueError('포트는 1024~65535 사이로 지정하세요.')
    key=ec.generate_private_key(ec.SECP256R1());moment=datetime.now(timezone.utc)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Seoyoung POS LAN host')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(moment-timedelta(days=1)).not_valid_after(moment+timedelta(days=3650))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(address))]),critical=False)
          .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).sign(key,hashes.SHA256()))
    return {'address':address,'port':port,'certificate':cert.public_bytes(serialization.Encoding.PEM).decode(),'private_key':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),'client_key':secrets.token_urlsafe(32)}


class SharedService:
    def __init__(self,path,config,allow_loopback=False):
        self.path=Path(path);self.config=config
        private_address(config['address'],allow_loopback)
        self.lock=threading.RLock();self.sessions={};self.failures={};self.server=self.thread=None;self.closing=False

    def start(self):
        if self.server:raise ValueError('공유가 이미 실행 중입니다.')
        self.closing=False
        service=self
        class Server(ThreadingHTTPServer):
            daemon_threads=False
            allow_reuse_address=True
            def get_request(self):
                sock,address=self.socket.accept();sock.settimeout(8)
                try:return context.wrap_socket(sock,server_side=True),address
                except BaseException:sock.close();raise
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.0'
            def setup(self):
                self.request.settimeout(8);super().setup()
            def log_message(self,*_):pass # Do not log credentials, commands or business data.
            def do_POST(self):
                try:
                    if self.path!='/api':raise PermissionError('허용하지 않는 공유 주소입니다.')
                    supplied=self.headers.get('X-Client-Key','')
                    if not hmac.compare_digest(supplied,service.config['client_key']):raise PermissionError('PC 연결 코드가 올바르지 않습니다.')
                    if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON 형식만 허용됩니다.')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2_000_000:raise ValueError('공유 요청 크기를 확인하세요.')
                    message=decode(self.rfile.read(length));result=service.handle(message,self.headers.get('Authorization',''),self.client_address[0])
                    status,payload=200,{'ok':True,'result':result}
                except PermissionError as exc:status,payload=403,{'ok':False,'error':str(exc),'kind':'permission'}
                except (ValueError,TypeError,KeyError,OverflowError,sqlite3.Error) as exc:status,payload=400,{'ok':False,'error':str(exc),'kind':'value'}
                except Exception:status,payload=500,{'ok':False,'error':'기준 PC에서 요청을 처리하지 못했습니다. 기준 PC의 상태를 확인하세요.','kind':'value'}
                try:
                    body=encode(payload).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                except (OSError,ssl.SSLError):pass
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
        # Keep the trusted root stable when the host's LAN address changes.
        # Its DPAPI-protected signing key issues a short-lived address-bound
        # server certificate; no trust check is disabled or external CA used.
        root=x509.load_pem_x509_certificate(self.config['certificate'].encode())
        root_key=serialization.load_pem_private_key(self.config['private_key'].encode(),None)
        leaf_key=ec.generate_private_key(ec.SECP256R1());moment=datetime.now(timezone.utc)
        leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'POS LAN session')]))
              .issuer_name(root.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(moment-timedelta(days=1)).not_valid_after(min(moment+timedelta(days=30),root.not_valid_after_utc))
              .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
              .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(self.config['address']))]),critical=False)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
              .sign(root_key,hashes.SHA256()))
        with tempfile.TemporaryDirectory(prefix='pos-lan-tls-') as temporary:
            cert=Path(temporary)/'host.crt';key=Path(temporary)/'host.key'
            cert.write_text(leaf.public_bytes(serialization.Encoding.PEM).decode()+self.config['certificate'],encoding='ascii');key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
            context.load_cert_chain(cert,key)
        self.server=Server((self.config['address'],self.config['port']),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,name='POS-LAN-host',daemon=True);self.thread.start()

    def stop(self):
        self.begin_close()
        if self.server:
            self.server.shutdown();self.server.server_close();self.thread.join(timeout=10);self.server=None
        self.sessions.clear()

    def begin_close(self):
        self.closing=True
        with self.lock:pass # Wait for an in-flight commit before exit backup.

    def cancel_close(self):self.closing=False

    def handle(self,message,authorization,client_ip):
        if not isinstance(message,dict):raise ValueError('공유 요청을 확인하세요.')
        if message.get('version')!=__version__:raise ValueError('기준 PC와 연결 PC를 같은 프로그램 버전으로 맞추세요.')
        command=message.get('command')
        with self.lock:
            if self.closing:raise ValueError('기준 PC가 종료 중입니다. 잠시 후 다시 연결하세요.')
            store=Store(self.path)
            try:
                if command=='hello':return {'version':__version__,'users':store.users_count(),'certificate_hash':sha256(self.config['certificate'].encode()).hexdigest()}
                if command=='login':
                    code=str(message.get('code',''));failure_key=(client_ip,code);count,blocked=self.failures.get(failure_key,(0,0))
                    if blocked>time.monotonic():raise ValueError('로그인을 여러 번 틀려 5분 동안 잠겼습니다.')
                    try:actor=store.login(code,message.get('password',''))
                    except ValueError:
                        count+=1;self.failures[failure_key]=(0 if count>=5 else count,time.monotonic()+300 if count>=5 else 0)
                        if len(self.failures)>1000:self.failures={failure_key:self.failures[failure_key]}
                        raise
                    self.failures.pop(failure_key,None)
                    self.sessions={k:v for k,v in self.sessions.items() if time.monotonic()-v['last']<1800}
                    if len(self.sessions)>=64:raise ValueError('공유 연결이 너무 많습니다. 사용하지 않는 PC를 로그아웃하세요.')
                    token=secrets.token_urlsafe(32);self.sessions[token]={'actor':actor,'hash':store._session_password_hash,'restore':store._restore_token,'last':time.monotonic()}
                    return {'session':token,'actor':client_actor(actor),'restore_epoch':store._current_restore_token()}
                session=self.sessions.get(authorization.removeprefix('Bearer '))
                if not session or time.monotonic()-session['last']>=1800:raise PermissionError('공유 연결 로그인이 만료되었습니다. 다시 로그인하세요.')
                store.actor=session['actor'];store._session_password_hash=session['hash'];store._restore_token=session['restore'];actor=store._require();session['last']=time.monotonic()
                if command=='logout':self.sessions.pop(authorization.removeprefix('Bearer '),None);return True
                if command=='status':return {'revision':store.audit_revision(),'actor':client_actor(actor)}
                if command=='change_password':
                    store.change_password(message.get('old',''),message.get('new',''));session['hash']=store._session_password_hash;return True
                if command in {'pending_result','cancel_pending'}:
                    request=message.get('request_id','')
                    if not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('요청 번호를 확인하세요.')
                    previous=store.db.execute('SELECT * FROM shared_requests WHERE request_id=?',(request,)).fetchone()
                    if previous and previous['user_id']!=actor['id']:raise PermissionError('다른 계정의 요청입니다.')
                    if command=='pending_result':return {'found':bool(previous),'result':decode(previous['result']) if previous else None}
                    if previous:
                        result=decode(previous['result']);return {'cancelled':result=={'$cancelled':True},'result':result}
                    with store._tx():store.db.execute('INSERT INTO shared_requests VALUES(?,?,?,?,?)',(request,actor['id'],str(message.get('payload_hash','')),encode({'$cancelled':True}),now()))
                    return {'cancelled':True,'result':None}
                if command=='authorize':
                    if message.get('menu'):store.require_menu(message['menu'])
                    elif message.get('permissions'):store._require(*message['permissions'])
                    if message.get('operation'):store._require_capability(message['menu'],message['operation'])
                    return client_actor(store.actor)
                if command!='call':raise ValueError('허용하지 않는 공유 명령입니다.')
                method=message.get('method')
                if method not in READS|WRITES:raise PermissionError('이 기능은 기준 PC에서 실행하세요. 개인 자료는 PC 사이에 전송하지 않습니다.')
                args,kwargs=message.get('args',[]),message.get('kwargs',{})
                if not isinstance(args,list) or not isinstance(kwargs,dict):raise ValueError('요청 인수를 확인하세요.')
                function=getattr(store,method);inspect.signature(function).bind(*args,**kwargs)
                request=message.get('request_id','');payload_hash=fingerprint({'method':method,'args':args,'kwargs':kwargs})
                store.db.execute('BEGIN IMMEDIATE');store._shared_outer_transaction=True
                try:
                    if method in WRITES:
                        if message.get('owner_id')!=actor['id']:raise PermissionError('저장 요청의 사용자와 로그인 계정이 다릅니다.')
                        if message.get('restore_epoch')!=store._current_restore_token():raise ValueError('기준 PC가 백업으로 복원되었습니다. 이전 미확인 요청은 다시 저장하지 말고 연결 메뉴에서 취소 처리한 뒤 최신 장부를 확인하세요.')
                        if not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('저장 요청 번호를 확인하세요.')
                        previous=store.db.execute('SELECT * FROM shared_requests WHERE request_id=?',(request,)).fetchone()
                        if previous:
                            if previous['user_id']!=actor['id'] or previous['payload_hash']!=payload_hash:raise ValueError('중복 저장 요청의 내용이 다릅니다.')
                            result=decode(previous['result'])
                            if result=={'$cancelled':True}:raise ValueError('취소한 미확인 저장 요청입니다. 최신 자료를 조회한 뒤 새로 입력하세요.')
                            store.db.commit();return result
                    store._shared_enforce_snapshots=True
                    result=function(*args,**kwargs)
                    if method in WRITES:store.db.execute('INSERT INTO shared_requests VALUES(?,?,?,?,?)',(request,actor['id'],payload_hash,encode(result),now()))
                    store.db.commit();return result
                except BaseException:store.db.rollback();raise
                finally:store._shared_outer_transaction=False
            finally:store.close()
