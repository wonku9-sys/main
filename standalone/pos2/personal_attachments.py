"""Encrypted, backup-contained attachments; no automatic file execution."""
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4
from cryptography.exceptions import InvalidTag
from .common import now,text
from .diary import _seal,_open

ATTACHMENT_LIMIT=10*1024*1024
ATTACHMENT_SCHEMA='''
CREATE TABLE IF NOT EXISTS personal_attachments (
 id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('diary','household')),record_type TEXT NOT NULL,record_id TEXT NOT NULL,
 metadata BLOB NOT NULL CHECK(length(metadata)>=28),ciphertext BLOB NOT NULL CHECK(length(ciphertext)>=28),created_at TEXT NOT NULL
);
'''
EXTENSIONS={'.pdf','.jpg','.jpeg','.png','.webp','.gif','.bmp','.txt','.md','.csv','.xlsx','.xls','.docx','.doc','.hwp','.hwpx','.pptx'}


class AttachmentMixin:
    def _attachment_record(self,key,kind,record_type,identifier,operation=None):
        if kind not in {'diary','household'}:raise ValueError('개인 기록 종류를 확인하세요.')
        (self._diary_require_key if kind=='diary' else self._require_household_key)(key)
        table=f'{kind}_entries' if record_type=='entry' else 'household_vehicle_logs' if kind=='household' and record_type=='vehicle_log' else 'personal_health_entries' if record_type=='health' else None
        if not table:raise ValueError('첨부할 기록 종류를 확인하세요.')
        if operation and operation!='export' and kind=='household':self._require_capability(kind,operation)
        extra=' AND kind=?' if record_type=='health' else ''
        args=(identifier,self.actor['id'],kind) if record_type=='health' else (identifier,self.actor['id'])
        if not self.db.execute(f'SELECT 1 FROM {table} WHERE id=? AND user_id=?'+extra,args).fetchone():raise ValueError('기록을 먼저 저장한 뒤 파일을 첨부하세요.')

    def _attachment_aad(self,kind,record_type,record_id,identifier,meta=False):
        return f'SeoyoungPOS/attachment/v1/{self.actor["id"]}/{kind}/{record_type}/{record_id}/{identifier}/{"meta" if meta else "file"}'.encode()

    def personal_attachments(self,key,kind,record_type,record_id):
        self._attachment_record(key,kind,record_type,record_id)
        records=[]
        try:
            for row in self.db.execute('SELECT id,metadata,created_at FROM personal_attachments WHERE user_id=? AND kind=? AND record_type=? AND record_id=? ORDER BY created_at,id',(self.actor['id'],kind,record_type,record_id)):
                meta=json.loads(_open(key,row['metadata'],self._attachment_aad(kind,record_type,record_id,row['id'],True)))
                records.append(dict(meta,id=row['id'],created_at=row['created_at']))
        except (InvalidTag,ValueError,KeyError,TypeError):raise ValueError('첨부파일 정보를 열 수 없습니다. 백업 상태를 확인하세요.') from None
        return records

    def add_personal_attachment(self,key,kind,record_type,record_id,filename,payload):
        with self._tx():
            self._attachment_record(key,kind,record_type,record_id,'edit')
            filename=text(str(filename).replace('\\','/').split('/')[-1],'파일 이름',True,200)
            if Path(filename).suffix.lower() not in EXTENSIONS:raise ValueError('사진·PDF·문서 파일만 첨부할 수 있습니다. 실행 파일·스크립트·바로가기는 허용하지 않습니다.')
            if not isinstance(payload,bytes) or not 0<len(payload)<=ATTACHMENT_LIMIT:raise ValueError('첨부파일은 0바이트 초과, 파일당 10MB 이하로 선택하세요.')
            if len(self.personal_attachments(key,kind,record_type,record_id))>=20:raise ValueError('기록 하나당 첨부파일은 20개까지 저장할 수 있습니다.')
            used=self.db.execute('SELECT COALESCE(SUM(length(ciphertext)),0) FROM personal_attachments WHERE user_id=?',(self.actor['id'],)).fetchone()[0]
            if used+len(payload)+28>200*1024*1024:raise ValueError('개인 첨부파일은 사용자당 200MB까지 저장할 수 있습니다. 불필요한 파일을 정리하세요.')
            identifier=uuid4().hex;meta=dict(name=filename,size=len(payload),sha256=sha256(payload).hexdigest())
            self.db.execute('INSERT INTO personal_attachments VALUES(?,?,?,?,?,?,?,?)',(identifier,self.actor['id'],kind,record_type,record_id,
                _seal(key,json.dumps(meta,ensure_ascii=False).encode(),self._attachment_aad(kind,record_type,record_id,identifier,True)),
                _seal(key,payload,self._attachment_aad(kind,record_type,record_id,identifier)),now()))
            self._audit('attach',kind,None,{})
            return identifier

    def personal_attachment_data(self,key,kind,record_type,record_id,identifier):
        self._attachment_record(key,kind,record_type,record_id,'export')
        row=self.db.execute('SELECT * FROM personal_attachments WHERE id=? AND user_id=? AND kind=? AND record_type=? AND record_id=?',(identifier,self.actor['id'],kind,record_type,record_id)).fetchone()
        if not row:raise ValueError('첨부파일을 찾을 수 없습니다.')
        try:
            meta=json.loads(_open(key,row['metadata'],self._attachment_aad(kind,record_type,record_id,identifier,True)))
            payload=_open(key,row['ciphertext'],self._attachment_aad(kind,record_type,record_id,identifier))
            if len(payload)!=meta['size'] or sha256(payload).hexdigest()!=meta['sha256']:raise ValueError()
        except (InvalidTag,ValueError,TypeError,KeyError):raise ValueError('첨부파일을 열 수 없거나 파일이 손상되었습니다.') from None
        return payload

    def delete_personal_attachment(self,key,kind,record_type,record_id,identifier):
        with self._tx():
            self._attachment_record(key,kind,record_type,record_id,'delete')
            if not self.db.execute('DELETE FROM personal_attachments WHERE id=? AND user_id=? AND kind=? AND record_type=? AND record_id=?',(identifier,self.actor['id'],kind,record_type,record_id)).rowcount:raise ValueError('첨부파일을 찾을 수 없습니다.')
            self._audit('detach',kind,None,{})
