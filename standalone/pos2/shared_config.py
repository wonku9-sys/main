"""Public pairing certificates plus Windows-user encrypted connection secrets."""
import base64
import json
from pathlib import Path
import re
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from . import windows_secrets
from .shared_protocol import private_address


def validate_config(config,allow_loopback=False):
    mode=config.get('mode','standalone')
    if mode not in {'standalone','host','client'}:raise ValueError('사용 방식을 선택하세요.')
    if mode=='standalone':return {'mode':mode}
    result={'mode':mode,'address':private_address(config.get('address'),allow_loopback)}
    try:result['port']=int(config.get('port',8795))
    except (ValueError,TypeError):raise ValueError('공유 포트를 확인하세요.') from None
    if not 1024<=result['port']<=65535:raise ValueError('포트는 1024~65535로 입력하세요.')
    try:
        certificate=str(config['certificate']);cert=x509.load_pem_x509_certificate(certificate.encode('ascii'))
        if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:raise ValueError()
    except (ValueError,KeyError,UnicodeError,x509.ExtensionNotFound):raise ValueError('기준 PC에서 내보낸 올바른 연결 파일을 선택하세요.') from None
    result['certificate']=certificate;result['client_key']=str(config.get('client_key',''))
    if not re.fullmatch('[A-Za-z0-9_-]{32,128}',result['client_key']):raise ValueError('기준 PC의 연결 코드를 입력하세요.')
    if mode=='host':
        result['private_key']=str(config.get('private_key',''))
        if not result['private_key']:raise ValueError('기준 PC의 공유 인증키를 생성하세요.')
        try:
            private=serialization.load_pem_private_key(result['private_key'].encode(),password=None)
            if private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)!=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo):raise ValueError()
        except (ValueError,TypeError,UnicodeError):raise ValueError('기준 PC 인증서와 개인키가 일치하지 않습니다. 인증키를 다시 생성하세요.') from None
    return result


def save_config(path,config):
    result=validate_config(config);public={key:value for key,value in result.items() if key not in {'private_key','client_key'}}
    if result['mode']!='standalone':
        secret={k:result[k] for k in ('private_key','client_key') if k in result}
        public['protected']=base64.b64encode(windows_secrets.protect(json.dumps(secret).encode())).decode('ascii')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('연결 설정 파일의 링크 경로는 사용할 수 없습니다.')
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix='connection-',suffix='.part',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name);stream.write(json.dumps(public,ensure_ascii=False))
    try:temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()


def load_config(path):
    path=Path(path)
    if not path.exists():return {'mode':'standalone'}
    try:
        if path.is_symlink() or path.stat().st_size>128000:raise ValueError()
        config=json.loads(path.read_text(encoding='utf-8'))
        if config.get('mode')!='standalone':config.update(json.loads(windows_secrets.unprotect(base64.b64decode(config.pop('protected')))))
        return validate_config(config)
    except (ValueError,TypeError,KeyError,OSError) as exc:raise ValueError('이 Windows 계정에서 공유 설정을 열 수 없습니다. 연결 설정에서 인증 파일과 연결 코드를 다시 등록하세요.') from exc


def public_bundle(config):return {'format':'SeoyoungPOS-LAN-v1',**{k:config[k] for k in ('address','port','certificate')}}


def read_bundle(path):
    path=Path(path)
    if path.stat().st_size>64000:raise ValueError('연결 파일이 너무 큽니다.')
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('format')!='SeoyoungPOS-LAN-v1':raise ValueError()
        return {k:data[k] for k in ('address','port','certificate')}
    except (ValueError,KeyError,TypeError,UnicodeError):raise ValueError('기준 PC에서 내보낸 .poslan 연결 파일을 선택하세요.') from None
