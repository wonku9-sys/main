"""Private AES-256-GCM diary, separate from account authentication."""
from datetime import datetime
from hashlib import pbkdf2_hmac
import json
import secrets
import time
import hmac
from hashlib import sha256
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .common import day, now, text
from .worklog import WorkLogMixin,WORKLOG_SCHEMA

DIARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS diary_vaults (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
 salt BLOB NOT NULL CHECK(length(salt)=16),
 wrapped_key BLOB NOT NULL CHECK(length(wrapped_key)=60),
 failures INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS diary_entries (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES diary_vaults(user_id) ON DELETE RESTRICT,
 ciphertext BLOB NOT NULL CHECK(length(ciphertext)>=28),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_logs (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 date TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def _aad(user_id,entry="key"):
    return f"SeoyoungPOS/private-diary/v1/{user_id}/{entry}".encode()


def _password_key(password,salt):
    if not isinstance(password,str) or not 8<=len(password)<=128:
        raise ValueError("일기장 암호는 8~128자로 입력하세요.")
    return pbkdf2_hmac("sha256",password.encode(),salt,600_000,dklen=32)


def _seal(key,payload,aad):
    nonce = secrets.token_bytes(12)
    return nonce+AESGCM(bytes(key)).encrypt(nonce,payload,aad)


def _open(key,cipher,aad):
    return AESGCM(bytes(key)).decrypt(cipher[:12],cipher[12:],aad)


DIARY_SCHEMA+=WORKLOG_SCHEMA

class DiaryMixin(WorkLogMixin):
    def _diary_require_key(self,key):
        self.require_menu("diary")
        try: token = (self.actor["id"],sha256(bytes(key)).digest(),self._current_restore_token())
        except (TypeError,ValueError):raise ValueError("일기장 잠금을 다시 해제하세요.") from None
        expected = getattr(self,"_diary_unlock_token",None)
        if expected is None or token[0]!=expected[0] or token[2]!=expected[2] or not hmac.compare_digest(token[1],expected[1]):
            raise ValueError("일기장 잠금을 다시 해제하세요.")
        row=self.db.execute("SELECT salt,wrapped_key FROM diary_vaults WHERE user_id=?",(self.actor["id"],)).fetchone()
        if not row or len(expected)<4 or expected[3]!=sha256(bytes(row[0])+bytes(row[1])).digest():
            self.lock_diary();raise ValueError("일기장 암호가 변경되었습니다. 다시 잠금을 해제하세요.")

    def lock_diary(self):
        self._diary_unlock_token = None
        from .private_session import forget_key
        forget_key(self,"diary")

    def diary_exists(self):
        self.require_menu("diary")
        return bool(self.db.execute("SELECT 1 FROM diary_vaults WHERE user_id=?",(self.actor["id"],)).fetchone())

    def setup_diary(self,password,confirm):
        with self._tx():
            self.require_menu("diary")
            if password!=confirm: raise ValueError("일기장 암호가 서로 다릅니다.")
            if self.db.execute("SELECT 1 FROM diary_vaults WHERE user_id=?",(self.actor["id"],)).fetchone():
                raise ValueError("이미 일기장 암호가 설정되어 있습니다.")
            salt,key = secrets.token_bytes(16),secrets.token_bytes(32)
            wrapped = _seal(_password_key(password,salt),key,_aad(self.actor["id"]))
            self.db.execute("INSERT INTO diary_vaults(user_id,salt,wrapped_key) VALUES(?,?,?)",(self.actor["id"],salt,wrapped))
            self._audit("setup","private_diary",None,{})

    def unlock_diary(self,password):
        failed = False
        with self._tx():
            self.require_menu("diary")
            row = self.db.execute("SELECT * FROM diary_vaults WHERE user_id=?",(self.actor["id"],)).fetchone()
            if not row: raise ValueError("일기장 암호를 먼저 설정하세요.")
            if row["locked_until"]>time.time(): raise ValueError("암호를 여러 번 틀려 5분 동안 잠겼습니다. 잠시 후 다시 시도하세요.")
            try:
                key = _open(_password_key(password,row["salt"]),row["wrapped_key"],_aad(self.actor["id"]))
            except (InvalidTag,ValueError):
                failed = True
                failures = row["failures"]+1
                self.db.execute("UPDATE diary_vaults SET failures=?,locked_until=? WHERE user_id=?",(0 if failures>=5 else failures,int(time.time())+300 if failures>=5 else 0,self.actor["id"]))
            else:
                self.db.execute("UPDATE diary_vaults SET failures=0,locked_until=0 WHERE user_id=?",(self.actor["id"],))
        if failed: raise ValueError("일기장 암호가 올바르지 않습니다.")
        self._diary_unlock_token = (self.actor["id"],sha256(key).digest(),self._current_restore_token(),sha256(bytes(row["salt"])+bytes(row["wrapped_key"])).digest())
        return bytearray(key)

    def diary_entries(self,key):
        self._diary_require_key(key)
        result = []
        try:
            # Authenticate the key even when the diary has no entries.
            records = self.db.execute("SELECT * FROM diary_entries WHERE user_id=? ORDER BY updated_at DESC,id",(self.actor["id"],))
            for row in records:
                content = json.loads(_open(key,row["ciphertext"],_aad(self.actor["id"],row["id"])))
                content.update(id=row["id"])
                result.append(content)
        except (InvalidTag,ValueError,TypeError,KeyError):
            raise ValueError("일기장을 열 수 없습니다. 암호 또는 파일 손상 여부를 확인하세요.") from None
        return result

    def save_diary_entry(self,key,data,identifier=None):
        with self._tx():
            self._diary_require_key(key)
            user = self.actor["id"]
            old = self.db.execute("SELECT * FROM diary_entries WHERE id=? AND user_id=?",(identifier,user)).fetchone() if identifier else None
            if identifier and not old: raise ValueError("일기를 찾을 수 없습니다.")
            # A matching vault key is proved by decrypting an existing entry.
            check = old or self.db.execute("SELECT * FROM diary_entries WHERE user_id=? LIMIT 1",(user,)).fetchone()
            if not self.db.execute("SELECT 1 FROM diary_vaults WHERE user_id=?",(user,)).fetchone(): raise ValueError("일기장이 잠겨 있습니다.")
            try:
                if check: _open(key,check["ciphertext"],_aad(user,check["id"]))
                if len(key)!=32: raise ValueError()
            except (InvalidTag,ValueError,TypeError): raise ValueError("일기장 잠금을 다시 해제하세요.") from None
            content = {"date":day(data.get("date")),"title":text(data.get("title","제목 없음"),"제목",True,200),"body":text(data.get("body",""),"일기",maximum=100000),"mood":text(data.get("mood","평온"),"기분",maximum=40)}
            from .household_parse import normalize_tags
            content.update(tags=normalize_tags(data.get('tags',[])),bookmark=bool(data.get('bookmark',False)))
            identifier = identifier or uuid4().hex
            cipher = _seal(key,json.dumps(content,ensure_ascii=False).encode(),_aad(user,identifier))
            stamp = now()
            if old:self.db.execute("UPDATE diary_entries SET ciphertext=?,updated_at=? WHERE id=?",(cipher,stamp,identifier))
            else:self.db.execute("INSERT INTO diary_entries(id,user_id,ciphertext,created_at,updated_at) VALUES(?,?,?,?,?)",(identifier,user,cipher,stamp,stamp))
            return identifier

    def delete_diary_entry(self,key,identifier):
        with self._tx():
            self._diary_require_key(key)
            row = self.db.execute("SELECT * FROM diary_entries WHERE id=? AND user_id=?",(identifier,self.actor["id"])).fetchone()
            if not row:raise ValueError("일기를 찾을 수 없습니다.")
            try:_open(key,row["ciphertext"],_aad(self.actor["id"],identifier))
            except (InvalidTag,ValueError,TypeError):raise ValueError("일기장 잠금을 다시 해제하세요.") from None
            self.db.execute("DELETE FROM diary_entries WHERE id=?",(identifier,))
            self.db.execute("DELETE FROM personal_attachments WHERE user_id=? AND kind='diary' AND record_type='entry' AND record_id=?",(self.actor['id'],identifier))

    def change_diary_password(self,old_password,new_password,confirm):
        key = self.unlock_diary(old_password)
        try:
            if new_password!=confirm:raise ValueError("새 일기장 암호가 서로 다릅니다.")
            with self._tx():
                self.require_menu("diary")
                salt = secrets.token_bytes(16)
                wrapped = _seal(_password_key(new_password,salt),key,_aad(self.actor["id"]))
                self.db.execute("UPDATE diary_vaults SET salt=?,wrapped_key=? WHERE user_id=?",(salt,wrapped,self.actor["id"]))
        finally:key[:] = bytes(len(key))

    def work_logs(self,start,end,search=""):
        self.require_menu("worklog")
        start,end = day(start),day(end)
        if start>end:raise ValueError("조회 기간을 확인하세요.")
        return [dict(r) for r in self.db.execute("SELECT * FROM work_logs WHERE user_id=? AND date BETWEEN ? AND ? AND (title LIKE ? OR body LIKE ?) ORDER BY date DESC,id DESC",(self.actor["id"],start,end,*[f"%{text(search)}%"]*2))]

    def save_work_log(self,data,identifier=None):
        with self._tx():
            self._require_capability("worklog","edit" if identifier else "create")
            values = (day(data.get("date")),text(data.get("title"),"제목",True,200),text(data.get("body",""),"업무 내용",maximum=100000))
            stamp = now()
            if identifier:
                if not self.db.execute("UPDATE work_logs SET date=?,title=?,body=?,updated_at=? WHERE id=? AND user_id=?",(*values,stamp,identifier,self.actor["id"])).rowcount:raise ValueError("업무일지를 찾을 수 없습니다.")
            else:identifier = self.db.execute("INSERT INTO work_logs(date,title,body,user_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",(*values,self.actor["id"],stamp,stamp)).lastrowid
            if 'details' in data:
                from .worklog import validate_details
                self.db.execute('INSERT INTO work_log_details VALUES(?,?) ON CONFLICT(work_log_id) DO UPDATE SET content=excluded.content',(identifier,json.dumps(validate_details(data['details']),ensure_ascii=False)))
            self._audit("update" if data.get("id") else "save","work_log",identifier,{})
            return identifier

    def delete_work_log(self,identifier):
        with self._tx():
            self._require_capability("worklog","delete")
            if not self.db.execute("DELETE FROM work_logs WHERE id=? AND user_id=?",(identifier,self.actor["id"])).rowcount:raise ValueError("업무일지를 찾을 수 없습니다.")
            self._audit("delete","work_log",identifier,{})
