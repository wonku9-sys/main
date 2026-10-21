"""User-owned local ROM registration. Never extracts archives or invokes a shell."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path,PurePosixPath
import re
from zipfile import ZipFile,BadZipFile
from PySide6.QtCore import QStandardPaths,QSaveFile,QIODevice,QProcess

# Titles/checksums identify the user's approved files; no ROM bytes are shipped.
APPROVED=(
 ('슈퍼 마리오브라더스 1','슈퍼마리오1.nes','07453885f32c765125edc3f2350a4409dcd15936e36d733035dc4959ddfc1e23','nes'),
 ('슈퍼 마리오브라더스 2','슈퍼마리오2.nes','89b3ce11c3cc67ab231ec3f15393f3d460a58cc4e7d554190fcb27887ea54f80','nes'),
 ('슈퍼 마리오브라더스 3','슈퍼마리오3.nes','4377a7f5e6eb50bdd2ac6f249bf1a7085500aca8eb41f38545c3a2731c51a579','nes'),
 ('버블보블 · 보글보글','bublbobl.zip','c23a70a5f12e695fec513fee682441accba5ea44a811ff43289ed894ec8ce505','arcade'),
 ('버블보블 2','bublbob2.zip','8222e5d5b99af5688c686e72eb752eb91185183a813c9afe3b4cd2bfe55bad1d','arcade'),
 ('슈퍼 마리오 올스타 + 월드','Super Mario All Stars & World (US).smc','4a4519fda1eabf7e21b1c2337d5e5e9254cc0f05783d33c050b6cbb2d072f8fb','snes'),
)
PLATFORM_SUFFIXES={'nes':{'.nes'},'snes':{'.smc','.sfc'},'arcade':{'.zip'}}


def validate_snes(source):
    """Check common LoROM/HiROM/ExHiROM headers, preserving copier headers."""
    size=source.stat().st_size
    copier=512 if size%1024==512 else 0
    payload_size=size-copier
    if payload_size<32768 or payload_size>8*1024*1024 or payload_size%1024:
        raise ValueError('SNES ROM 크기 또는 512바이트 복사기 헤더를 확인하세요.')
    with source.open('rb') as stream:
        for offset,modes in ((0x7fc0,{0,2,3}),(0xffc0,{1}),(0x40ffc0,{5})):
            if offset+64>payload_size:continue
            stream.seek(copier+offset);header=stream.read(64)
            complement=int.from_bytes(header[28:30],'little');checksum=int.from_bytes(header[30:32],'little')
            reset=int.from_bytes(header[60:62],'little')
            if (header[21]&15 in modes and header[21]&0xe0==0x20 and
                complement^checksum==0xffff and checksum not in {0,0xffff} and
                reset>=0x8000 and all(32<=c<127 for c in header[:21])):
                return
    raise ValueError('올바른 SNES 내부 헤더·체크섬 쌍·시작 주소를 찾지 못했습니다.')


def validate_rom(source):
    source=Path(source)
    if not source.is_file() or source.is_symlink() or not 16<=source.stat().st_size<=128*1024*1024:raise ValueError('16바이트~128MB의 실제 게임 파일을 선택하세요.')
    suffix=source.suffix.lower()
    if suffix=='.nes':
        with source.open('rb') as stream:header=stream.read(16)
        minimum=16+header[4]*16384+header[5]*8192+(512 if header[6]&4 else 0)
        if header[:4]!=b'NES\x1a' or not header[4] or source.stat().st_size<minimum:raise ValueError('올바른 NES ROM 헤더·파일 크기가 아닙니다.')
        platform='nes'
    elif suffix in PLATFORM_SUFFIXES['snes']:
        validate_snes(source);platform='snes'
    elif suffix=='.zip':
        if not re.fullmatch(r'[A-Za-z0-9_]{1,48}',source.stem):raise ValueError('오락실 ZIP 이름은 실행기 기종명과 같은 영문·숫자·밑줄이어야 합니다. 예: bublbobl.zip')
        try:
            with ZipFile(source) as archive:
                infos=archive.infolist()
                if not infos or len(infos)>200 or sum(item.file_size for item in infos)>128*1024*1024:raise ValueError('오락실 ROM 묶음의 크기·파일 수를 확인하세요.')
                for item in infos:
                    name=PurePosixPath(item.filename)
                    if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename or item.flag_bits&1:raise ValueError('안전하지 않은 경로 또는 암호화된 ZIP은 등록할 수 없습니다.')
                if archive.testzip() is not None:raise ValueError('게임 ZIP의 무결성 검사가 실패했습니다.')
        except BadZipFile:raise ValueError('올바른 게임 ZIP 파일이 아닙니다.') from None
        platform='arcade'
    else:raise ValueError('NES(.nes), SNES(.smc/.sfc) 또는 오락실 ROM(.zip) 파일을 선택하세요.')
    digest=sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return platform,digest.hexdigest()


class RomLibrary:
    def __init__(self,root=None):self.root=Path(root) if root else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'approved-games';self.manifest=self.root/'library.json'
    def load(self):
        if self.root.is_symlink() or self.manifest.is_symlink():raise ValueError('게임 보관 경로에 링크를 사용할 수 없습니다.')
        if not self.manifest.exists():return dict(games={},emulators={})
        if self.manifest.stat().st_size>5_000_000:raise ValueError('게임 목록 파일이 너무 큽니다.')
        try:
            data=json.loads(self.manifest.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or not isinstance(data.get('games'),dict) or not isinstance(data.get('emulators'),dict):raise ValueError()
            for key,row in data['games'].items():
                if not re.fullmatch('[0-9a-f]{64}',key) or not isinstance(row,dict) or row.get('platform') not in PLATFORM_SUFFIXES or Path(row.get('filename','')).name!=row.get('filename') or any(c in row.get('filename','') for c in '/\\:'):raise ValueError()
                if not isinstance(row.get('title'),str) or Path(row['filename']).suffix.lower() not in PLATFORM_SUFFIXES[row['platform']] or type(row.get('plays',0)) is not int or not isinstance(row.get('scores',[]),list):raise ValueError()
                if any(not isinstance(score,dict) or type(score.get('score')) is not int or not isinstance(score.get('name'),str) or not isinstance(score.get('date'),str) for score in row.get('scores',[])):raise ValueError()
            if any(kind not in PLATFORM_SUFFIXES or not isinstance(program,str) for kind,program in data['emulators'].items()):raise ValueError()
            return data
        except (ValueError,UnicodeError,TypeError):raise ValueError('게임 목록 파일을 읽지 못했습니다. 기존 파일은 덮어쓰지 않습니다.') from None
    def save(self,data):
        self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink() or self.manifest.is_symlink():raise ValueError('게임 보관 경로에 링크를 사용할 수 없습니다.')
        output=QSaveFile(str(self.manifest));payload=json.dumps(data,ensure_ascii=False).encode('utf-8')
        if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(payload)!=len(payload) or not output.commit():raise OSError('게임 목록을 저장하지 못했습니다.')
    def rows(self):
        data=self.load();rows=[]
        for title,filename,digest,platform in APPROVED:
            registered=data['games'].get(digest)
            rows.append(dict(registered or {},title=title,filename=filename,digest=digest,platform=platform,registered=registered is not None))
        known={row['digest'] for row in rows}
        rows.extend(dict(row,digest=digest,registered=True) for digest,row in data['games'].items() if digest not in known)
        return rows
    def register(self,source):
        source=Path(source);platform,digest=validate_rom(source);data=self.load()
        previous=data['games'].get(digest,{})
        if not previous and len(data['games'])>=100:raise ValueError('게임은 최대 100개까지 등록할 수 있습니다.')
        directory=self.root/'roms'/digest[:16]
        if (self.root/'roms').is_symlink() or directory.is_symlink():raise ValueError('게임 보관 경로에 링크를 사용할 수 없습니다.')
        directory.mkdir(parents=True,exist_ok=True);target=directory/previous.get('filename',source.name)
        if target.exists():
            if validate_rom(target)!=(platform,digest):raise ValueError('보관 위치의 기존 파일이 원본과 다릅니다. 기존 파일을 먼저 확인하세요.')
        else:
            output=QSaveFile(str(target))
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):raise OSError('게임 파일을 보관할 수 없습니다.')
            with source.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):
                    if output.write(chunk)!=len(chunk):raise OSError('게임 파일 복사에 실패했습니다.')
            if not output.commit():raise OSError('게임 파일 복사에 실패했습니다.')
        if validate_rom(target)!=(platform,digest):raise ValueError('복사된 게임 파일이 원본과 다릅니다.')
        title=next((name for name,_,key,_ in APPROVED if key==digest),source.stem)
        data['games'][digest]=previous or dict(title=title,filename=source.name,platform=platform,plays=0,scores=[],registered_at=datetime.now().astimezone().isoformat(timespec='seconds'))
        self.save(data);return digest
    def set_emulator(self,platform,program):
        program=Path(program)
        if platform not in PLATFORM_SUFFIXES or not program.is_file() or program.is_symlink() or program.suffix.lower()!='.exe':raise ValueError('신뢰할 수 있는 Windows 에뮬레이터 EXE를 선택하세요.')
        data=self.load();data['emulators'][platform]=str(program.resolve());self.save(data)
    def command(self,digest):
        data=self.load();row=data['games'].get(digest)
        if row is None:raise ValueError('먼저 이 PC에서 해당 ROM 파일을 등록하세요.')
        program=Path(data['emulators'].get(row['platform'],''))
        if not program.is_file() or program.is_symlink() or program.suffix.lower()!='.exe':raise ValueError('호환 실행기(에뮬레이터) EXE를 먼저 선택하세요. 프로그램에는 실행기가 포함되지 않습니다.')
        target=self.root/'roms'/digest[:16]/row['filename']
        if self.root.is_symlink() or target.parent.is_symlink() or not target.resolve().is_relative_to(self.root.resolve()):raise ValueError('게임 보관 경로를 확인하세요.')
        if validate_rom(target)!=(row['platform'],digest):raise ValueError('등록 후 게임 파일이 변경되었습니다. 원본을 확인하세요.')
        if row['platform'] in {'nes','snes'}:args=[str(target.resolve())]
        else:
            if not re.fullmatch(r'[A-Za-z0-9_]{1,48}',target.stem):raise ValueError('오락실 기종명을 확인하세요.')
            directories=[str((self.root/'roms'/key[:16]).resolve()) for key,value in data['games'].items() if value['platform']=='arcade']+[str(program.parent/'roms')]
            args=[target.stem,'-rompath',';'.join(directories),'-window']
        return str(program),args
    def launch(self,digest):
        program,args=self.command(digest);success,pid=QProcess.startDetached(program,args,str(Path(program).parent))
        if not success:raise OSError('외부 실행기를 시작하지 못했습니다. EXE 호환성과 Windows 보안 메시지를 확인하세요.')
        data=self.load();row=data['games'][digest];row['plays']=int(row.get('plays',0))+1;row['last_played']=datetime.now().astimezone().isoformat(timespec='seconds');self.save(data);return pid
    def record_score(self,digest,name,score):
        if type(score) is not int or not 0<=score<=1_000_000_000:raise ValueError('점수는 0~1,000,000,000 정수로 입력하세요.')
        data=self.load()
        if digest not in data['games']:raise ValueError('등록된 게임을 선택하세요.')
        row=data['games'][digest];scores=row.get('scores',[]);scores.insert(0,dict(name=str(name).strip()[:24] or '플레이어',score=score,date=datetime.now().astimezone().isoformat(timespec='seconds')))
        row['scores']=scores[:200];row['best']=max(int(row.get('best',0)),score);self.save(data)
