"""Email-only reset, password-authorized verified recipients, one-time codes.

Diary/household recovery keys are delivered to the owner by email. Only a
key-wrapped data key is stored locally; administrators are not given escrow keys.
SMTP credentials use Windows-user DPAPI; no service account is shipped.
"""
from dataclasses import dataclass, field
from email.message import EmailMessage
from hashlib import sha256, pbkdf2_hmac
import hmac
import json
import re
import secrets
import smtplib
import ssl
import time

from cryptography.exceptions import InvalidTag

from .common import text, now
from .diary import _seal, _open, _password_key, _aad
from . import windows_secrets

EMAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS email_smtp (
 id INTEGER PRIMARY KEY CHECK(id=1), config BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS recovery_emails (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
 email TEXT NOT NULL, verified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_challenges (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 purpose TEXT NOT NULL CHECK(purpose IN ('bind','login_reset','diary_reset','household_reset','diary_enable','household_enable')),
 email TEXT NOT NULL, salt BLOB NOT NULL CHECK(length(salt)=16),
 digest BLOB NOT NULL CHECK(length(digest)=32), receipt BLOB NOT NULL CHECK(length(receipt)=32),
 epoch TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1)),
 delivered INTEGER NOT NULL DEFAULT 0 CHECK(delivered IN (0,1)),
 recovery_salt BLOB, recovery_wrapped BLOB
);
CREATE TABLE IF NOT EXISTS email_private_recovery (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('diary','household')),
 salt BLOB NOT NULL CHECK(length(salt)=16), wrapped_key BLOB NOT NULL CHECK(length(wrapped_key)=60),
 PRIMARY KEY(user_id,kind)
);
"""

CODE_TTL = 600
RESEND_INTERVAL = 60
MAX_HOURLY = 5


def email_address(value):
    value = str(value or "").strip()
    if len(value)>254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",value):
        raise ValueError("올바른 이메일 주소를 입력하세요.")
    return value


def masked_address(address):
    local,domain=address.rsplit("@",1)
    return local[:2]+"***@"+domain


def validate_smtp(values):
    if not isinstance(values,dict):raise ValueError("메일 발송 설정을 확인하세요.")
    host=str(values.get("host","")).strip()
    if len(host)>253 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?",host):
        raise ValueError("SMTP 서버 주소를 입력하세요. https:// 등은 넣지 않습니다.")
    mode=values.get("mode","ssl")
    try:port=int(values.get("port",465))
    except (TypeError,ValueError):raise ValueError("SMTP 포트를 확인하세요.") from None
    if mode not in {"ssl","starttls"} or not 1<=port<=65535:raise ValueError("암호화된 SMTP 연결과 올바른 포트를 선택하세요.")
    username=text(values.get("username"),"발송 계정",True,254)
    password=values.get("password")
    if any(c in username for c in "\r\n") or not isinstance(password,str) or not 1<=len(password)<=1024:
        raise ValueError("발송 계정과 앱 비밀번호를 확인하세요.")
    return dict(host=host,port=port,mode=mode,username=username,password=password,sender=email_address(values.get("sender",username)))


@dataclass(repr=False)
class EmailDelivery:
    identifier: str
    recipient_mask: str
    _receipt: str = field(repr=False)
    _config: bytes = field(repr=False)
    _recipient: str = field(repr=False)
    _body: str = field(repr=False)

    def send(self):
        """Run in a UI worker; it must never access a SQLite connection."""
        try:
            try: config=validate_smtp(json.loads(windows_secrets.unprotect(self._config)))
            except (ValueError,TypeError,KeyError):
                raise ValueError("발송 설정을 이 Windows 사용자 계정에서 열 수 없습니다. ‘이메일 발송 설정’에서 앱 비밀번호를 다시 저장하세요.") from None
            message=EmailMessage()
            message["From"],message["To"]=config["sender"],self._recipient
            message["Subject"]="[SY POS] 이메일 인증 · 암호 재설정 안내"
            message.set_content(self._body)
            context=ssl.create_default_context()
            if config["mode"]=="ssl":
                connection=smtplib.SMTP_SSL(config["host"],config["port"],timeout=10,context=context)
            else:
                connection=smtplib.SMTP(config["host"],config["port"],timeout=10)
            with connection as smtp:
                smtp.ehlo()
                if config["mode"]=="starttls":smtp.starttls(context=context);smtp.ehlo()
                smtp.login(config["username"],config["password"])
                refused=smtp.send_message(message)
                if refused:raise smtplib.SMTPRecipientsRefused(refused)
        except smtplib.SMTPAuthenticationError:
            raise ValueError("발송 계정 인증에 실패했습니다. ‘이메일 발송 설정’에서 계정·앱 비밀번호와 메일 서비스의 SMTP 사용 설정을 확인하세요. 기존 암호는 변경되지 않았습니다.") from None
        except smtplib.SMTPRecipientsRefused:
            raise ValueError("메일 서비스가 받는 이메일을 거부했습니다. 받는 주소와 발송 계정의 이용 제한을 확인하세요. 기존 암호는 변경되지 않았습니다.") from None
        except ssl.SSLCertVerificationError:
            raise ValueError("메일 서버의 보안 인증서를 확인하지 못했습니다. Windows 날짜·시각과 인증서 업데이트를 확인하세요. 보안 연결을 끄지 마세요.") from None
        except ValueError:
            raise
        except (OSError,smtplib.SMTPException,TypeError,KeyError):
            raise ValueError("메일을 발송하지 못했습니다. 인터넷·SMTP 설정·앱 비밀번호를 확인하세요. 기존 암호는 변경되지 않았습니다.") from None
        finally:
            self._body=""


class EmailRecoveryMixin:
    def mail_settings(self):
        self._require("admin")
        row=self.db.execute("SELECT config FROM email_smtp WHERE id=1").fetchone()
        if not row:return {"configured":False}
        try:config=validate_smtp(json.loads(windows_secrets.unprotect(row[0])))
        except (ValueError,TypeError,json.JSONDecodeError):return {"configured":True,"needs_reconfigure":True}
        return {key:value for key,value in dict(config,configured=True).items() if key!="password"}

    def save_mail_settings(self,values):
        self._require("admin")
        values=dict(values)
        if not values.get("password"):
            old=self.db.execute("SELECT config FROM email_smtp WHERE id=1").fetchone()
            if old:values["password"]=json.loads(windows_secrets.unprotect(old[0]))["password"]
        config=validate_smtp(values)
        cipher=windows_secrets.protect(json.dumps(config).encode())
        with self._tx():
            self._require("admin")
            self.db.execute("INSERT INTO email_smtp(id,config) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config",(cipher,))
            self._audit("smtp_settings","settings",None,{"credentials":"Windows-user encrypted"})

    def recovery_email_status(self):
        self._require()
        row=self.db.execute("SELECT email FROM recovery_emails WHERE user_id=?",(self.actor["id"],)).fetchone()
        kinds={r[0] for r in self.db.execute("SELECT kind FROM email_private_recovery WHERE user_id=?",(self.actor["id"],))}
        return {"email":row[0] if row else "","verified":bool(row),"diary": "diary" in kinds,"household":"household" in kinds,"smtp_configured":bool(self.db.execute("SELECT 1 FROM email_smtp").fetchone())}

    def _email_epoch(self,user,purpose):
        parts=[user["password_hash"],str(user["active"]),self._current_restore_token(),user["code"]]
        profile=self.db.execute("SELECT email,verified_at FROM recovery_emails WHERE user_id=?",(user["id"],)).fetchone()
        parts.extend(list(profile) if profile else ["no-recovery-email"])
        if purpose.startswith("diary_"):
            row=self.db.execute("SELECT salt,wrapped_key FROM diary_vaults WHERE user_id=?",(user["id"],)).fetchone()
            parts.extend([bytes(v).hex() for v in row] if row else ["no-vault"])
        if purpose.startswith("household_"):
            row=self.db.execute("SELECT salt,wrapped_key FROM household_vaults WHERE user_id=?",(user["id"],)).fetchone()
            parts.extend([bytes(v).hex() for v in row] if row else ["no-vault"])
        return sha256("\0".join(parts).encode()).hexdigest()

    def prepare_email_code(self,purpose,user_code="",email="",current_password=""):
        """Reserve a bounded challenge; only EmailDelivery contains the mail body."""
        if purpose not in {"bind","login_reset","diary_reset","household_reset","diary_enable","household_enable"}:
            raise ValueError("이메일 인증 용도를 확인하세요.")
        from .store import password_matches
        key=None
        if purpose!="login_reset":
            self._require()
            user_code=self.actor["code"]
        if purpose.endswith("_enable"):
            kind=purpose.removesuffix("_enable")
            key=self.unlock_diary(current_password) if kind=="diary" else self.unlock_household(current_password)
        try:
            with self._tx():
                if purpose!="login_reset":self._require()
                user=self.db.execute("SELECT * FROM users WHERE code=? AND active=1",(text(user_code),)).fetchone()
                if not user:raise ValueError("계정의 이메일 복구 설정을 확인하세요.")
                profile=self.db.execute("SELECT email FROM recovery_emails WHERE user_id=?",(user["id"],)).fetchone()
                if purpose=="bind":
                    if not password_matches(current_password,user["password_hash"]):raise ValueError("현재 로그인 비밀번호를 확인하세요.")
                    recipient=email_address(email)
                    if profile and recipient.casefold()==profile[0].casefold():raise ValueError("이미 인증한 복구 이메일입니다. 변경할 새 주소를 입력하세요.")
                else:
                    if not profile:raise ValueError("계정의 복구 이메일을 먼저 등록·인증하세요.")
                    recipient=profile[0]
                    if email and not hmac.compare_digest(email_address(email).casefold().encode(),recipient.casefold().encode()):
                        raise ValueError("아이디와 현재 등록된 복구 이메일 주소를 확인하세요. 다른 주소로는 인증번호를 보낼 수 없습니다.")
                if purpose.endswith("_reset") and purpose!="login_reset":
                    kind=purpose.removesuffix("_reset")
                    self.require_menu("diary" if kind=="diary" else "household")
                    if not self.db.execute("SELECT 1 FROM email_private_recovery WHERE user_id=? AND kind=?",(user["id"],kind)).fetchone():
                        raise ValueError("해당 개인 자료의 이메일 복구를 사전에 설정하지 않았습니다. 기존 암호가 필요합니다.")
                config=self.db.execute("SELECT config FROM email_smtp WHERE id=1").fetchone()
                if not config:raise ValueError("관리자 설정에서 발송용 메일을 먼저 설정하세요.")
                instant=int(time.time())
                recent=self.db.execute("SELECT created FROM email_challenges WHERE user_id=? ORDER BY created DESC LIMIT 1",(user["id"],)).fetchone()
                if recent and instant-recent[0]<RESEND_INTERVAL:raise ValueError("인증 메일은 1분 후 다시 요청하세요.")
                if self.db.execute("SELECT COUNT(*) FROM email_challenges WHERE user_id=? AND created>?",(user["id"],instant-3600)).fetchone()[0]>=MAX_HOURLY:
                    raise ValueError("한 시간에 인증 메일 5회까지 요청할 수 있습니다. 잠시 후 다시 시도하세요.")
                code=f"{secrets.randbelow(100_000_000):08d}"
                identifier,receipt=secrets.token_hex(16),secrets.token_hex(32)
                salt=secrets.token_bytes(16)
                recovery_salt=recovery_wrapped=None
                extra=""
                if key is not None:
                    kind=purpose.removesuffix("_enable")
                    secret=secrets.token_urlsafe(32)
                    recovery_salt=secrets.token_bytes(16)
                    derived=pbkdf2_hmac("sha256",secret.encode(),recovery_salt,600_000,32)
                    recovery_wrapped=_seal(derived,key,f"SeoyoungPOS/email-recovery/{user['id']}/{kind}/{recipient}".encode())
                    extra=f"\n개인 자료 복구키 (이 최초 메일을 삭제하지 말고 안전하게 보관하세요):\n{secret}\n\n이 키는 프로그램·관리자에게 평문으로 보관되지 않습니다. 개인 암호 재설정에는 새 인증번호와 이 복구키가 모두 필요합니다. 기존 암호와 이 메일의 복구키를 모두 잃으면 내용 복구가 불가능합니다.\n"
                self.db.execute("UPDATE email_challenges SET consumed=1 WHERE user_id=? AND purpose=?",(user["id"],purpose))
                self.db.execute("INSERT INTO email_challenges(id,user_id,purpose,email,salt,digest,receipt,epoch,created,expires,recovery_salt,recovery_wrapped) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(identifier,user["id"],purpose,recipient,salt,sha256(salt+code.encode()).digest(),sha256(receipt.encode()).digest(),self._email_epoch(user,purpose),instant,instant+CODE_TTL,recovery_salt,recovery_wrapped))
                label={"bind":"복구 이메일 등록","login_reset":"로그인 암호 재설정","diary_reset":"일기장 암호 재설정","household_reset":"가계부 암호 재설정","diary_enable":"일기장 이메일 복구 등록","household_enable":"가계부 이메일 복구 등록"}[purpose]
                body=f"SY POS · {label}\n아이디: {user['code']}\n\n일회용 인증번호: {code}\n유효시간: 10분 / 5회 틀리면 무효\n\n프로그램의 이메일 인증 화면에 입력하세요. 인증번호를 확인하기 전에는 기존 암호가 바뀌지 않습니다. 재요청하면 이전 인증번호는 사용할 수 없습니다.\n{extra}\n본인이 요청하지 않았다면 무시하세요. 인증번호나 복구키를 다른 사람에게 전달하지 마세요.\n"
                self._audit("email_requested","user",user["id"],{"purpose":purpose})
                return EmailDelivery(identifier,masked_address(recipient),receipt,config[0],recipient,body)
        finally:
            # Wipe this temporary password-verified key, not an already-open
            # independent editor's session. Its unsaved work must remain usable.
            if key is not None:key[:]=bytes(len(key))

    def complete_email_delivery(self,identifier,receipt,success):
        with self._tx():
            row=self.db.execute("SELECT * FROM email_challenges WHERE id=?",(identifier,)).fetchone()
            if not row or not hmac.compare_digest(sha256(str(receipt).encode()).digest(),row["receipt"]):raise ValueError("메일 발송 확인 정보가 올바르지 않습니다.")
            if row["consumed"] or row["expires"]<=time.time():raise ValueError("인증 요청이 만료되었거나 새 요청으로 바뀌었습니다.")
            self.db.execute("UPDATE email_challenges SET delivered=?,consumed=? WHERE id=?",(int(bool(success)),0 if success else 1,identifier))

    def _check_email_code(self,identifier,code,purpose):
        row=self.db.execute("SELECT * FROM email_challenges WHERE id=? AND purpose=?",(identifier,purpose)).fetchone()
        if not row or row["consumed"] or not row["delivered"] or row["expires"]<=time.time():return None,"인증번호가 만료되었거나 사용할 수 없습니다. 새 메일을 요청하세요."
        user=self.db.execute("SELECT * FROM users WHERE id=? AND active=1",(row["user_id"],)).fetchone()
        if not user or row["epoch"]!=self._email_epoch(user,purpose):return None,"계정이나 자료가 변경되었습니다. 새 인증 메일을 요청하세요."
        if purpose!="login_reset":
            self._require()
            if self.actor["id"]!=row["user_id"]:raise PermissionError("다른 계정의 인증번호를 사용할 수 없습니다.")
        valid=isinstance(code,str) and len(code)==8 and hmac.compare_digest(sha256(row["salt"]+code.encode()).digest(),row["digest"])
        if not valid:
            self._fail_email_attempt(row)
            return None,"인증번호가 올바르지 않습니다. 5회 틀리면 무효가 됩니다."
        return row,None

    def _fail_email_attempt(self,row):
        attempts=min(5,row["attempts"]+1)
        self.db.execute("UPDATE email_challenges SET attempts=?,consumed=? WHERE id=?",(attempts,int(attempts>=5),row["id"]))

    def verify_recovery_email(self,identifier,code):
        with self._tx():
            row,error=self._check_email_code(identifier,code,"bind")
            if row:
                changing=bool(self.db.execute("SELECT 1 FROM recovery_emails WHERE user_id=?",(row["user_id"],)).fetchone())
                self.db.execute("INSERT INTO recovery_emails(user_id,email,verified_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,verified_at=excluded.verified_at",(row["user_id"],row["email"],now()))
                # Private recovery wrappers authenticate the old recipient in AAD.
                # They cannot be safely moved without the owner's private key.
                # Keep all vaults/content intact; require an explicit re-enrolment.
                if changing:self.db.execute("DELETE FROM email_private_recovery WHERE user_id=?",(row["user_id"],))
                self.db.execute("UPDATE email_challenges SET consumed=1 WHERE user_id=?",(row["user_id"],))
                self._audit("email_changed" if changing else "email_verified","user",row["user_id"],{"private_reenrolment_required":changing})
        if error:raise ValueError(error)

    def verify_private_email_recovery(self,kind,identifier,code):
        if kind not in {"diary","household"}:raise ValueError("개인 자료 구분을 확인하세요.")
        with self._tx():
            row,error=self._check_email_code(identifier,code,kind+"_enable")
            if row:
                self.require_menu(kind)
                self.db.execute("INSERT INTO email_private_recovery(user_id,kind,salt,wrapped_key) VALUES(?,?,?,?) ON CONFLICT(user_id,kind) DO UPDATE SET salt=excluded.salt,wrapped_key=excluded.wrapped_key",(row["user_id"],kind,row["recovery_salt"],row["recovery_wrapped"]))
                self.db.execute("UPDATE email_challenges SET consumed=1 WHERE id=?",(identifier,))
                self._audit("private_email_enabled","user",row["user_id"],{"kind":kind})
        if error:raise ValueError(error)

    def reset_password_by_email(self,identifier,code,new_password,confirm,kind="login",recovery_key=""):
        if kind not in {"login","diary","household"}:raise ValueError("암호 종류를 확인하세요.")
        if new_password!=confirm:raise ValueError("새 암호가 서로 다릅니다.")
        from .store import password_hash
        encoded=password_hash(new_password) if kind=="login" else None
        # Validate policy before consuming a code; a typo must not reset a password.
        if kind!="login":_password_key(new_password,secrets.token_bytes(16))
        key=None
        with self._tx():
            row,error=self._check_email_code(identifier,code,kind+"_reset")
            if row:
                if kind=="login":self.db.execute("UPDATE users SET password_hash=? WHERE id=?",(encoded,row["user_id"]))
                else:
                    self.require_menu(kind)
                    rescue=self.db.execute("SELECT * FROM email_private_recovery WHERE user_id=? AND kind=?",(row["user_id"],kind)).fetchone()
                    try:
                        if not rescue or not isinstance(recovery_key,str) or len(recovery_key.strip())!=43:raise ValueError()
                        derived=pbkdf2_hmac("sha256",recovery_key.strip().encode(),rescue["salt"],600_000,32)
                        aad=f"SeoyoungPOS/email-recovery/{row['user_id']}/{kind}/{row['email']}".encode()
                        key=bytearray(_open(derived,rescue["wrapped_key"],aad))
                    except (InvalidTag,ValueError,TypeError):
                        self._fail_email_attempt(row);error="최초 복구 메일의 개인 자료 복구키를 확인하세요. 기존 내용은 변경하지 않았습니다."
                    else:
                        salt=secrets.token_bytes(16)
                        aad=_aad(row["user_id"]) if kind=="diary" else self._household_aad(row["user_id"])
                        wrapped=_seal(_password_key(new_password,salt),key,aad)
                        if kind=="diary":self.db.execute("UPDATE diary_vaults SET salt=?,wrapped_key=?,failures=0,locked_until=0 WHERE user_id=?",(salt,wrapped,row["user_id"]))
                        else:self.db.execute("UPDATE household_vaults SET salt=?,wrapped_key=?,plain_key=NULL,locked=1,failures=0,locked_until=0 WHERE user_id=?",(salt,wrapped,row["user_id"]))
                if not error:
                    self.db.execute("UPDATE email_challenges SET consumed=1 WHERE user_id=?",(row["user_id"],))
                    self._audit("email_password_reset","user",row["user_id"],{"kind":kind})
        if key is not None:key[:]=bytes(len(key))
        if error:raise ValueError(error)
        if kind=="login":self.actor=None
        self.lock_diary()
        if hasattr(self,"lock_household"):self.lock_household()
