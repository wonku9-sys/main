"""Fresh local SQLite unit of work and authentication boundary."""

from contextlib import contextmanager
from copy import deepcopy
from hashlib import scrypt
import hmac
import json
from pathlib import Path
import secrets
import sqlite3

from .catalog import CatalogMixin
from .inventory_reporting import InventoryReportingMixin
from .backup_policy import BackupPolicyMixin
from .commerce import CommerceMixin
from .common import PERMISSIONS, ALLOWED_PERMISSIONS, now, text
from .permissions import MENU_POLICIES, ACTIONS, has_menu, can_action
from .loyalty import LoyaltyMixin
from .operations import OperationsMixin
from .recovery import RecoveryMixin, SCHEMA_VERSION
from .schema import initialize
from .settlement import SettlementMixin
from .backup_schedule import BackupScheduleMixin, DEFAULT_BACKUP_SCHEDULE, validate_schedule
from .suppliers import SupplierMixin
from .currency import currency_boundary, convert_result, upgrade_currency
from .purchase_reports import PurchaseReportingMixin
from .offline_features import OfflineFeaturesMixin
from .online_info import DEFAULT_ONLINE, validate_online
from .diary import DiaryMixin
from .household import HouseholdMixin
from .email_recovery import EmailRecoveryMixin
from .health import HealthMixin
from .personal_attachments import AttachmentMixin
from .inspiration import InspirationMixin

APPLICATION_ID = 1398362162
DEFAULT_SETTINGS = {
    "online_info": DEFAULT_ONLINE,
    "rounding_mode": "decimal",
    "backup_schedule": DEFAULT_BACKUP_SCHEDULE,
    "store_name": "SY POS", "business_no": "", "phone": "", "address": "",
    "representative":"", "business_type":"", "business_category":"", "fax":"", "store_email":"",
    "bank":"", "account":"", "account_holder":"", "allow_negative_stock":True,
    "earn_bps": 100, "point_min": 1000, "point_step": 100, "point_enabled": True,
}


def password_hash(password):
    password = str(password)
    if len(password) < 8 or len(password) > 128:
        raise ValueError("비밀번호는 8~128자로 입력하세요.")
    return _scrypt_hash(password)


def _scrypt_hash(password):
    salt = secrets.token_bytes(16)
    digest = scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def password_matches(password, encoded):
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (16384, 8, 1):
            return False
        if len(str(password)) > 128:
            return False
        digest = scrypt(str(password).encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


@currency_boundary
class Store(InventoryReportingMixin, CatalogMixin, CommerceMixin, OperationsMixin, LoyaltyMixin, RecoveryMixin, BackupPolicyMixin, SettlementMixin, BackupScheduleMixin, SupplierMixin, PurchaseReportingMixin, OfflineFeaturesMixin, DiaryMixin,HouseholdMixin,EmailRecoveryMixin,HealthMixin,AttachmentMixin,InspirationMixin):
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve() if str(path) != ":memory:" else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path) if self.path else ":memory:", isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.actor = None
        self._session_password_hash=None
        self.migration_backup_path = None
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA busy_timeout=15000")
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            marker = self.db.execute("PRAGMA application_id").fetchone()[0]
            self._opening_version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if tables and marker != APPLICATION_ID:
                raise ValueError("이 파일은 새 독립판 업무 DB가 아닙니다. 기존 프로그램 데이터는 열거나 변경하지 않습니다.")
            if tables and self.db.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
                raise ValueError("더 최신 버전의 장부입니다. 같은 버전 이상의 프로그램으로 실행하세요.")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            from .schema_upgrade import upgrade_business_schema
            upgrade_business_schema(self)
            initialize(self.db)
            self.db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            self._init_loyalty()
            self._init_operations()
            upgrade_currency(self, self._opening_version)
            self._init_recovery()
            self._init_catalog()
            self._init_supplier_management()
            self._dummy_password = password_hash(secrets.token_urlsafe(24))
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.lock_diary();self.lock_household()
        self.actor = None
        self.db.close()

    @contextmanager
    def _tx(self):
        if self.db.in_transaction:
            if getattr(self,'_shared_outer_transaction',False):
                yield self.db
                return
            raise RuntimeError("중첩 업무 트랜잭션은 허용되지 않습니다.")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self._pending_ui_sound=None
            yield self.db
            self.db.commit()
        except sqlite3.IntegrityError as exc:
            self.db.rollback()
            raise ValueError(f"중복 코드·바코드 또는 연결된 이력 때문에 저장할 수 없습니다: {exc}") from exc
        except sqlite3.Error as exc:
            self.db.rollback()
            raise ValueError(f"업무 자료 처리 중 데이터베이스 오류가 발생했습니다: {exc}") from exc
        except BaseException:
            self.db.rollback()
            raise
        else:
            kind=getattr(self,'_pending_ui_sound',None)
            callback=getattr(self,'_ui_sound_callback',None)
            if kind and callback:
                try:callback(kind)
                except (RuntimeError,OSError,ValueError):pass

    def _public_user(self, row):
        result = {key: row[key] for key in ("id", "code", "name", "role", "active")}
        result["active"] = bool(result["active"])
        result["permissions"] = sorted(PERMISSIONS) if row["role"] == "admin" else json.loads(row["permissions"])
        return result

    def audit_revision(self):
        self._require()
        return self._current_restore_token(),self.db.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0]

    def _edit_snapshot(self,table,identifier):
        if table not in {'products','documents','sales_forms'}:raise ValueError('편집 대상이 잘못되었습니다.')
        from .shared_protocol import fingerprint
        row=self.db.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone()
        value={'record':dict(row) if row else None}
        if table=='documents':value['lines']=[dict(r) for r in self.db.execute('SELECT * FROM document_lines WHERE document_id=? ORDER BY id',(identifier,))]
        if table=='sales_forms':value['order']=[dict(r) for r in self.db.execute('SELECT * FROM sales_order_details WHERE form_id=?',(identifier,))]
        return fingerprint(value)

    def _check_edit_snapshot(self,table,identifier,data):
        token=data.get('_expected_token')
        if identifier and (token or getattr(self,'_shared_enforce_snapshots',False)):
            if not token or not hmac.compare_digest(str(token),self._edit_snapshot(table,identifier)):
                raise ValueError('다른 PC에서 이 자료가 변경되었습니다. 입력 내용을 따로 메모하고 최신 자료를 다시 열어 수정하세요.')

    def _require(self, *permissions):
        if set(permissions) - PERMISSIONS:
            raise ValueError("알 수 없는 업무 권한입니다.")
        if self._restore_token != self._current_restore_token():
            self.actor = None
            raise PermissionError("자료가 복원되었습니다. 프로그램을 다시 실행해 로그인하세요.")
        row = self.db.execute("SELECT * FROM users WHERE id=?", (self.actor["id"],)).fetchone() if self.actor else None
        if not row or not row["active"]:
            self.actor = None
            raise PermissionError("로그인이 필요합니다.")
        if self._session_password_hash is not None and self._session_password_hash!=row["password_hash"]:
            self.actor=None
            self.lock_diary();self.lock_household()
            raise PermissionError("비밀번호가 변경되었습니다. 다시 로그인하세요.")
        self.actor = self._public_user(row)
        if permissions and row["role"] != "admin" and not (set(permissions) - {"admin"}) & set(self.actor["permissions"]):
            raise PermissionError("이 업무를 사용할 권한이 없습니다.")
        return self.actor

    def _require_any(self, *permissions):
        last_error = None
        for permission in permissions:
            try:
                return self._require(permission)
            except PermissionError as exc:
                last_error = exc
        raise last_error or PermissionError("로그인이 필요합니다.")

    def require_menu(self, key):
        actor = self._require()
        if not has_menu(actor, key):
            raise PermissionError(f"{MENU_POLICIES.get(key, (key,))[0]} 메뉴 접근권한이 없습니다.")
        return actor

    def _require_capability(self, key, operation):
        actor = self.require_menu(key)
        if not can_action(actor, key, operation):
            raise PermissionError(f"{MENU_POLICIES[key][0]}의 {ACTIONS[operation]} 권한이 없습니다.")
        return actor

    def _audit(self, action, entity, entity_id=None, detail=None):
        self.db.execute("INSERT INTO audit(at,user_id,action,entity,entity_id,detail) VALUES(?,?,?,?,?,?)", (
            now(), self.actor["id"] if self.actor else None, action, entity, entity_id,
            json.dumps(convert_result(detail or {}), ensure_ascii=False, sort_keys=True, default=str),
        ))
        if self.db.in_transaction:
            if 'delete' in action or 'cancel' in action:self._pending_ui_sound='delete'
            elif 'update' in action or 'edit' in action or 'change' in action:self._pending_ui_sound='edit'
            elif action not in {'login','logout','read'}:self._pending_ui_sound='save'

    def users_count(self):
        return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def setup_admin(self, code, name, password):
        code, name = text(code, "사용자 코드", True, 80), text(name, "사용자 이름", True, 100)
        encoded = password_hash(password)
        with self._tx():
            if self.users_count():
                raise ValueError("최초 관리자 설정은 한 번만 가능합니다.")
            identifier = self.db.execute("INSERT INTO users(code,name,password_hash,role,permissions) VALUES(?,?,?,'admin',?)", (code, name, encoded, json.dumps(sorted(PERMISSIONS)))).lastrowid
            self.actor = self._public_user(self.db.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone())
            self._session_password_hash=encoded
            self._audit("create", "user", identifier, {"code": code, "name": name, "role": "admin"})
            self.db.execute("INSERT INTO partners(kind,code,name,opening_date) VALUES('customer','WALKIN','일반고객',date('now','localtime'))")
        return identifier

    def login(self, code, password):
        self.actor = None
        self.lock_diary();self.lock_household()
        row = self.db.execute("SELECT * FROM users WHERE code=?", (text(code),)).fetchone()
        valid = password_matches(password, row["password_hash"] if row else self._dummy_password)
        if not row or not valid or not row["active"]:
            raise ValueError("사용자 코드 또는 비밀번호를 확인하세요.")
        self._restore_token = self._current_restore_token()
        self.actor = self._public_user(row)
        self._session_password_hash=row["password_hash"]
        with self._tx():
            self._audit("login", "user", row["id"], {})
        return self.actor

    def bootstrap_default_admin(self):
        """The explicitly requested, publicly documented first-run credential.

        Never reset an existing account; all later password changes retain the
        normal eight-character minimum. The database stores only a salted hash.
        """
        with self._tx():
            if self.users_count():
                return False
            identifier = self.db.execute("INSERT INTO users(code,name,password_hash,role,permissions) VALUES('admin','관리자',?,'admin',?)", (_scrypt_hash("1234"), json.dumps(sorted(PERMISSIONS)))).lastrowid
            self.db.execute("INSERT OR IGNORE INTO partners(kind,code,name,opening_date) VALUES('customer','WALKIN','일반고객',date('now','localtime'))")
            self._audit("bootstrap_admin", "user", identifier, {"code": "admin", "password_change_recommended": True})
        return True

    def default_login_available(self):
        row = self.db.execute("SELECT password_hash FROM users WHERE code='admin' AND role='admin' AND active=1").fetchone()
        return bool(row and password_matches("1234", row[0]))

    def logout(self):
        self.lock_diary()
        self.lock_household()
        if self.actor:
            with self._tx():
                self._audit("logout", "user", self.actor["id"], {})
        self.actor = None

    def list_users(self):
        self._require("admin")
        return [self._public_user(row) for row in self.db.execute("SELECT * FROM users ORDER BY code")]

    def save_user(self, data, id=None):
        with self._tx():
            self._require("admin")
            existing = self.db.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone() if id else None
            if id and not existing:
                raise ValueError("사용자를 찾을 수 없습니다.")
            code = text(data.get("code", existing["code"] if existing else ""), "사용자 코드", True, 80)
            name = text(data.get("name", existing["name"] if existing else ""), "이름", True, 100)
            role = data.get("role", existing["role"] if existing else "staff")
            if role not in {"admin", "staff"}:
                raise ValueError("계정 역할은 관리자 또는 일반 사용자여야 합니다.")
            active = int(bool(data.get("active", existing["active"] if existing else True)))
            permissions = data.get("permissions", json.loads(existing["permissions"]) if existing else [])
            if not isinstance(permissions, (list, tuple, set)) or not set(permissions) <= ALLOWED_PERMISSIONS:
                raise ValueError("올바른 사용자 권한을 선택하세요.")
            if role != "admin" and "admin" in permissions:
                raise ValueError("관리자 권한은 관리자 역할에만 부여할 수 있습니다.")
            if existing and existing["id"] == self.actor["id"] and not active:
                raise ValueError("현재 로그인한 계정은 비활성화할 수 없습니다.")
            if existing and existing["role"] == "admin" and existing["active"] and (role != "admin" or not active):
                if self.db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (id,)).fetchone()[0] == 0:
                    raise ValueError("마지막 활성 관리자 계정은 변경할 수 없습니다.")
            encoded = password_hash(data["password"]) if data.get("password") else existing["password_hash"] if existing else password_hash("")
            values = (code, name, encoded, role, json.dumps(sorted(PERMISSIONS if role == "admin" else set(permissions))), active)
            if existing:
                self.db.execute("UPDATE users SET code=?,name=?,password_hash=?,role=?,permissions=?,active=? WHERE id=?", values + (id,))
            else:
                # Client-only personal vaults may outlive a host-side staff
                # account. Never assign a former numeric owner ID to a new
                # person, including after an older backup is restored.
                id=self._user_high_water()+1
                self.db.execute("INSERT INTO code_sequences VALUES('user',?) ON CONFLICT(name) DO UPDATE SET last_value=excluded.last_value",(id,))
                self.db.execute("INSERT INTO users(id,code,name,password_hash,role,permissions,active) VALUES(?,?,?,?,?,?,?)",(id,)+values)
            self._audit("update" if existing else "create", "user", id, {"code": code, "name": name, "role": role, "permissions": json.loads(values[4]), "active": bool(active)})
            if self.actor and id==self.actor["id"]:self._session_password_hash=encoded
        return id

    def _user_high_water(self):
        current=self.db.execute('SELECT COALESCE(MAX(id),0) FROM users').fetchone()[0]
        historical=self.db.execute("SELECT COALESCE(MAX(entity_id),0) FROM audit WHERE entity='user'").fetchone()[0]
        sequence=self.db.execute("SELECT last_value FROM code_sequences WHERE name='user'").fetchone()
        return max(0,current,historical,sequence[0] if sequence else 0)

    def delete_user(self, id):
        with self._tx():
            self._require("admin")
            row = self.db.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
            if not row:
                raise ValueError("사용자를 찾을 수 없습니다.")
            if row["id"] == self.actor["id"]:
                raise ValueError("현재 로그인한 계정은 삭제할 수 없습니다.")
            if row["role"] == "admin" and row["active"] and self.db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (id,)).fetchone()[0] == 0:
                raise ValueError("마지막 관리자 계정은 삭제할 수 없습니다.")
            self.db.execute("DELETE FROM users WHERE id=?", (id,))
            self._audit("delete", "user", id, {"code": row["code"], "name": row["name"]})

    def change_password(self, old, new):
        with self._tx():
            self._require()
            row = self.db.execute("SELECT * FROM users WHERE id=?", (self.actor["id"],)).fetchone()
            if not password_matches(old, row["password_hash"]):
                raise ValueError("현재 비밀번호가 일치하지 않습니다.")
            encoded=password_hash(new)
            self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, row["id"]))
            self._audit("password", "user", row["id"], {})
        self._session_password_hash=encoded

    def _settings_values(self):
        result = deepcopy(DEFAULT_SETTINGS)
        result.update({row["key"]: json.loads(row["value"]) for row in self.db.execute("SELECT * FROM settings")})
        return result

    def settings(self):
        self._require("admin")
        return self._settings_values()

    def store_profile(self):
        self._require()
        keys=('store_name','business_no','representative','business_type','business_category','phone','fax','address','store_email','bank','account','account_holder')
        values=self._settings_values()
        return {key:values[key] for key in keys}

    def calculation_policy(self):
        self._require()
        return {"rounding_mode": self._settings_values()["rounding_mode"]}

    def online_preferences(self):
        self._require()
        return validate_online(self._settings_values()["online_info"])

    def save_settings(self, values):
        if not isinstance(values, dict) or set(values) - set(DEFAULT_SETTINGS):
            raise ValueError("지원하지 않는 설정 항목입니다.")
        parsed = {}
        for key, value in values.items():
            if key in {"earn_bps", "point_min", "point_step"}:
                try:
                    parsed_integer = int(value)
                except (TypeError, ValueError, OverflowError):
                    raise ValueError("포인트 정책은 정수로 입력하세요.") from None
                if isinstance(value, bool) or str(value).strip() != str(parsed_integer):
                    raise ValueError("포인트 정책은 정수로 입력하세요.")
                value = parsed_integer
                limit = 10000 if key == "earn_bps" else 9_000_000_000_000
                if value < (1 if key == "point_step" else 0) or value > limit:
                    raise ValueError("포인트 정책 허용 범위를 확인하세요.")
            elif key == "rounding_mode":
                if value not in {"decimal", "won"}:
                    raise ValueError("반올림 설정을 선택하세요.")
            elif key == "backup_schedule":
                value = validate_schedule(value)
            elif key == "online_info":
                value = validate_online(value)
            elif key in {"point_enabled","allow_negative_stock"}:
                if not isinstance(value, bool):
                    raise ValueError("포인트 사용 여부는 체크 값이어야 합니다.")
            else:
                value = text(value, key, key == "store_name", 500)
            parsed[key] = value
        with self._tx():
            self._require("admin")
            for key, value in parsed.items():
                self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))
            self._audit("update", "settings", None, parsed)

    def audit_log(self):
        self._require("admin")
        return [dict(row) for row in self.db.execute("SELECT a.*,u.name AS user_name FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 5000")]

    def backup(self, path):
        self._require("admin")
        result = self._backup_file(path)
        with self._tx():
            self._require("admin")
            self._audit("backup", "settings", None, {"file": Path(result).name})
        return result

    def _backup_file(self, path):
        target = Path(path).expanduser().resolve()
        if self.path and target == self.path:
            raise ValueError("사용 중인 업무 DB에 덮어쓸 수 없습니다.")
        if target.exists():
            raise ValueError("이미 존재하는 파일입니다. 새 백업 파일명을 선택하세요.")
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(str(target))
        try:
            self.db.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("백업 파일 무결성 검사에 실패했습니다.")
            if destination.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("백업 파일 연결 이력 검사에 실패했습니다.")
        except sqlite3.Error as exc:
            raise ValueError(f"백업 파일을 저장하지 못했습니다: {exc}") from exc
        finally:
            destination.close()
        return str(target)
