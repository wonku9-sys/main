"""Private cashbook: independent amounts, optional password, encrypted entries."""
import hmac
from hashlib import sha256
import json
import secrets
import time
from uuid import uuid4

from cryptography.exceptions import InvalidTag

from .common import day, money, now, text
from .diary import _password_key, _seal, _open
from .household_finance import HouseholdFinanceMixin

HOUSEHOLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS personal_popup_preferences (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
 sound_enabled INTEGER NOT NULL DEFAULT 1 CHECK(sound_enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS personal_themes (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('diary','household')),
 theme TEXT NOT NULL CHECK(theme IN ('cream','rose','forest','lavender','night')),
 PRIMARY KEY(user_id,kind)
);
CREATE TABLE IF NOT EXISTS household_memos (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES household_vaults(user_id) ON DELETE RESTRICT,
 ciphertext BLOB NOT NULL CHECK(length(ciphertext)>=28), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS household_vaults (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
 locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1)),
 salt BLOB NOT NULL, wrapped_key BLOB NOT NULL, plain_key BLOB,
 failures INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0,
 CHECK((locked=1 AND length(salt)=16 AND length(wrapped_key)=60 AND plain_key IS NULL)
 OR (locked=0 AND length(salt)=0 AND length(wrapped_key)=0 AND length(plain_key)=32))
);
CREATE TABLE IF NOT EXISTS household_entries (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES household_vaults(user_id) ON DELETE RESTRICT,
 ciphertext BLOB NOT NULL CHECK(length(ciphertext)>=28),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS personal_preferences (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
 music_enabled INTEGER NOT NULL DEFAULT 1 CHECK(music_enabled IN (0,1)),
 music_volume INTEGER NOT NULL DEFAULT 6 CHECK(music_volume BETWEEN 0 AND 30)
);
"""


class HouseholdMixin(HouseholdFinanceMixin):
    def popup_sound_enabled(self):
        self._require()
        row=self.db.execute('SELECT sound_enabled FROM personal_popup_preferences WHERE user_id=?',(self.actor['id'],)).fetchone()
        return bool(row[0]) if row else True

    def save_popup_sound_enabled(self,enabled):
        if type(enabled) is not bool:raise ValueError('효과음 설정을 확인하세요.')
        with self._tx():
            self._require()
            self.db.execute('INSERT INTO personal_popup_preferences VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET sound_enabled=excluded.sound_enabled',(self.actor['id'],int(enabled)))

    def personal_theme(self,kind):
        if kind not in {'diary','household'}:raise ValueError('개인 화면 종류를 확인하세요.')
        self.require_menu(kind)
        row=self.db.execute('SELECT theme FROM personal_themes WHERE user_id=? AND kind=?',(self.actor['id'],kind)).fetchone()
        return row[0] if row else ('lavender' if kind=='diary' else 'cream')

    def save_personal_theme(self,kind,theme):
        if kind not in {'diary','household'} or theme not in {'cream','rose','forest','lavender','night'}:raise ValueError('선택 가능한 테마를 확인하세요.')
        with self._tx():
            self.require_menu(kind)
            self.db.execute('INSERT INTO personal_themes VALUES(?,?,?) ON CONFLICT(user_id,kind) DO UPDATE SET theme=excluded.theme',(self.actor['id'],kind,theme))

    def _household_stamp(self):
        row=self.db.execute("SELECT salt,wrapped_key,plain_key FROM household_vaults WHERE user_id=?",(self.actor["id"],)).fetchone()
        return sha256(b"".join(bytes(value or b"") for value in row)).digest() if row else None
    @staticmethod
    def _household_aad(user,entry="key"):
        return f"SeoyoungPOS/private-household/v1/{user}/{entry}".encode()

    def household_status(self):
        self.require_menu("household")
        row=self.db.execute("SELECT locked FROM household_vaults WHERE user_id=?",(self.actor["id"],)).fetchone()
        return {"exists":bool(row),"password_enabled":bool(row and row[0])}

    def setup_household(self,password="",confirm=""):
        with self._tx():
            self.require_menu("household")
            if password!=confirm:raise ValueError("가계부 암호가 서로 다릅니다.")
            if self.db.execute("SELECT 1 FROM household_vaults WHERE user_id=?",(self.actor["id"],)).fetchone():raise ValueError("가계부가 이미 설정되어 있습니다.")
            key=secrets.token_bytes(32)
            locked=bool(password)
            salt=secrets.token_bytes(16) if locked else b""
            wrapped=_seal(_password_key(password,salt),key,self._household_aad(self.actor["id"])) if locked else b""
            self.db.execute("INSERT INTO household_vaults(user_id,locked,salt,wrapped_key,plain_key) VALUES(?,?,?,?,?)",(self.actor["id"],int(locked),salt,wrapped,None if locked else key))
            self._audit("setup","household",None,{"password_enabled":locked})

    def unlock_household(self,password=""):
        failed=False
        with self._tx():
            self.require_menu("household")
            row=self.db.execute("SELECT * FROM household_vaults WHERE user_id=?",(self.actor["id"],)).fetchone()
            if not row:raise ValueError("가계부를 먼저 설정하세요.")
            if row["locked"]:
                if row["locked_until"]>time.time():raise ValueError("암호를 여러 번 틀려 5분 동안 잠겼습니다.")
                try:key=_open(_password_key(password,row["salt"]),row["wrapped_key"],self._household_aad(self.actor["id"]))
                except (InvalidTag,ValueError):
                    failures=row["failures"]+1;failed=True
                    self.db.execute("UPDATE household_vaults SET failures=?,locked_until=? WHERE user_id=?",(0 if failures>=5 else failures,int(time.time())+300 if failures>=5 else 0,self.actor["id"]))
                else:self.db.execute("UPDATE household_vaults SET failures=0,locked_until=0 WHERE user_id=?",(self.actor["id"],))
            else:key=row["plain_key"]
        if failed:raise ValueError("가계부 암호가 올바르지 않습니다.")
        self._household_unlock_token=(self.actor["id"],sha256(key).digest(),self._current_restore_token(),self._household_stamp())
        return bytearray(key)

    def lock_household(self):
        self._household_unlock_token=None
        from .private_session import forget_key
        forget_key(self,"household")

    def _require_household_key(self,key):
        self.require_menu("household")
        expected=getattr(self,"_household_unlock_token",None)
        try:valid=expected and expected[0]==self.actor["id"] and expected[2]==self._current_restore_token() and hmac.compare_digest(expected[1],sha256(bytes(key)).digest())
        except (TypeError,ValueError):valid=False
        if not valid:raise ValueError("가계부 잠금을 다시 해제하세요.")
        if len(expected)<4 or expected[3]!=self._household_stamp():
            self.lock_household();raise ValueError("가계부 암호 설정이 변경되었습니다. 다시 잠금을 해제하세요.")

    def set_household_password(self,key,password,confirm):
        if password!=confirm:raise ValueError("새 가계부 암호가 서로 다릅니다.")
        with self._tx():
            self._require_household_key(key)
            salt=secrets.token_bytes(16) if password else b""
            wrapped=_seal(_password_key(password,salt),key,self._household_aad(self.actor["id"])) if password else b""
            self.db.execute("UPDATE household_vaults SET locked=?,salt=?,wrapped_key=?,plain_key=?,failures=0,locked_until=0 WHERE user_id=?",(int(bool(password)),salt,wrapped,None if password else bytes(key),self.actor["id"]))
            self.db.execute("UPDATE email_challenges SET consumed=1 WHERE user_id=? AND purpose LIKE 'household_%'",(self.actor["id"],))
            self._audit("password_mode","household",None,{"password_enabled":bool(password)})
        self._household_unlock_token=(self.actor["id"],sha256(bytes(key)).digest(),self._current_restore_token(),self._household_stamp())

    def _household_records(self,key):
        self._require_household_key(key)
        records=[]
        try:
            for row in self.db.execute("SELECT * FROM household_entries WHERE user_id=?",(self.actor["id"],)):
                item=json.loads(_open(key,row["ciphertext"],self._household_aad(self.actor["id"],row["id"])))
                item["id"]=row["id"];records.append(item)
        except (InvalidTag,ValueError,TypeError,KeyError):raise ValueError("가계부를 열 수 없습니다. 암호나 파일 손상 여부를 확인하세요.") from None
        return sorted(records,key=lambda r:(r["date"],r["created_at"],r["id"]))

    def household_report(self,key,start,end,category="",search="",account_id=None):
        self._require_household_key(key)
        start,end=day(start),day(end)
        if start>end:raise ValueError("조회 기간을 확인하세요.")
        records=self._household_ledger(key)
        selected=[r for r in records if (account_id is None or r['account_id']==account_id) and (not category or r["category"]==category) and (not search or str(search).casefold().removeprefix('#') in (r["title"]+r["memo"]+r["category"]+r.get('payee','')+' '.join(r.get('tags',[]))).casefold())]
        delta=lambda r:r['amount']*(-1 if r['kind'] in {'expense','transfer_out'} else 1)
        opening=sum(delta(r) for r in selected if r["date"]<start or r['kind']=='opening' and r['date']==start)
        balance=opening;income=expense=0;rows=[]
        for r in selected:
            if not start<=r["date"]<=end or r['kind']=='opening' and r['date']==start:continue
            balance+=delta(r)
            income+=r["amount"] if r["kind"]=="income" else 0
            expense+=r["amount"] if r["kind"]=="expense" else 0
            rows.append(dict(r,balance=balance))
        return {"rows":rows,"opening_balance":opening,"income_total":income,"expense_total":expense,"closing_balance":balance,"categories":sorted({r["category"] for r in records})}

    def save_household_entry(self,key,data,identifier=None):
        with self._tx():
            self._require_household_key(key)
            self._require_capability("household","edit" if identifier else "create")
            old=next((r for r in self._household_records(key) if r['id']==identifier),None) if identifier else None
            if identifier and not old:raise ValueError("가계부 항목을 찾을 수 없습니다.")
            if old and old.get('vehicle_obligation_id'):raise ValueError('차량 납부관리에서 납부를 취소한 뒤 다시 기록하세요.')
            kind=data.get("kind")
            if kind not in {"income","expense"}:raise ValueError("수입 또는 지출을 선택하세요.")
            from .household_parse import normalize_tags
            data=dict(data)
            if data.get('auto_category') and str(data.get('category','')).strip() in {'','기타'}:
                suggestion=self.suggest_household_category(key,str(data.get('title',''))+' '+str(data.get('memo','')),kind)
                if suggestion['category']:data['category']=suggestion['category']
            content={"date":day(data.get("date")),"kind":kind,"title":text(data.get("title"),"내용",True,200),"category":text(data.get("category","기타"),"분류",True,100),"amount":money(data.get("amount"),positive=True),"memo":text(data.get("memo",""),"메모",maximum=10000),'tags':normalize_tags(data.get('tags',[]))}
            content.update(self._finance_entry_metadata(key,data,old))
            if old and old.get('fixed_rule_id'):content['fixed_rule_id']=old['fixed_rule_id']
            return self._household_put_entry(key,content,identifier,old)

    def delete_household_entry(self,key,identifier):
        with self._tx():
            self._require_household_key(key);self._require_capability("household","delete")
            if any(r['id']==identifier and r.get('vehicle_obligation_id') for r in self._household_records(key)):raise ValueError('차량 납부관리에서 납부를 취소하면 연결된 가계부 기록도 삭제됩니다.')
            if not self.db.execute("DELETE FROM household_entries WHERE id=? AND user_id=?",(identifier,self.actor["id"])).rowcount:raise ValueError("가계부 항목을 찾을 수 없습니다.")
            self.db.execute("DELETE FROM personal_attachments WHERE user_id=? AND kind='household' AND record_type='entry' AND record_id=?",(self.actor['id'],identifier))
            self._audit("delete","household_entry",None,{})

    def household_memos(self,key,value=""):
        self._require_household_key(key)
        if value:value=day(value)
        records=[]
        try:
            for row in self.db.execute("SELECT * FROM household_memos WHERE user_id=?",(self.actor["id"],)):
                item=json.loads(_open(key,row["ciphertext"],self._household_aad(self.actor["id"],"memo/"+row["id"])))
                if not value or item["date"]==value:records.append(dict(item,id=row["id"]))
        except (InvalidTag,ValueError,TypeError,KeyError):raise ValueError("가계부 메모를 열 수 없습니다. 파일 손상 여부를 확인하세요.") from None
        return sorted(records,key=lambda r:r["date"])

    def save_household_memo(self,key,value,body):
        with self._tx():
            self._require_household_key(key)
            value=day(value);body=text(body,"날짜 메모",maximum=20000)
            previous=next((r for r in self.household_memos(key,value)),None)
            self._require_capability("household","edit" if previous else "create")
            identifier=previous["id"] if previous else uuid4().hex
            cipher=_seal(key,json.dumps({"date":value,"body":body},ensure_ascii=False).encode(),self._household_aad(self.actor["id"],"memo/"+identifier))
            stamp=now()
            self.db.execute("INSERT INTO household_memos(id,user_id,ciphertext,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext,updated_at=excluded.updated_at",(identifier,self.actor["id"],cipher,stamp,stamp))
            self._audit("save_memo","household",None,{})
            return identifier

    def diary_music_preferences(self):
        self.require_menu("diary")
        row=self.db.execute("SELECT music_enabled,music_volume FROM personal_preferences WHERE user_id=?",(self.actor["id"],)).fetchone()
        return {"enabled":bool(row[0]) if row else True,"volume":row[1] if row else 6}

    def save_diary_music_preferences(self,enabled,volume):
        if type(enabled) is not bool or type(volume) is not int or not 0<=volume<=30:raise ValueError("음악 음량 설정을 확인하세요.")
        with self._tx():
            self.require_menu("diary")
            self.db.execute("INSERT INTO personal_preferences(user_id,music_enabled,music_volume) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET music_enabled=excluded.music_enabled,music_volume=excluded.music_volume",(self.actor["id"],int(enabled),volume))
