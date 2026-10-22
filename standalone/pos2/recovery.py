"""Validated, atomic SQLite restore with a retained before-restore backup."""
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import secrets
import re
import sqlite3
import tempfile
import time

from .common import ALLOWED_PERMISSIONS, now
from .backup_schedule import validate_schedule
from .loyalty import LOYALTY_SCHEMA
from .operations import OPERATIONS_SCHEMA
from .schema import SCHEMA, initialize
from .suppliers import SUPPLIER_SCHEMA
from .currency import upgrade_currency


RESTORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS restore_state (
 id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL
);
INSERT OR IGNORE INTO restore_state(id,token) VALUES(1,'');
PRAGMA user_version=218;
"""
SUPPORTED_VERSIONS = {200, 201, 202, 203, 204, 205, 206, 207, 208,209,210,211,212,213,214,215,216,217,218}
SCHEMA_VERSION = 218
APPLICATION_ID = 1398362162


def _objects(db):
    return {(row[0], row[1]): "".join(re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[^\s]", row[2])) for row in db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
    )}


@lru_cache(maxsize=1)
def _expected_objects():
    db = sqlite3.connect(":memory:")
    try:
        initialize(db)
        from .member_registration import REGISTRATION_SCHEMA
        db.executescript(LOYALTY_SCHEMA + REGISTRATION_SCHEMA + OPERATIONS_SCHEMA + RESTORE_SCHEMA)
        return _objects(db)
    finally:
        db.close()


def _validate_database(db):
    if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("SY POS 독립판의 백업 파일이 아닙니다. 기존 별도 프로그램이나 다른 앱의 파일은 복원할 수 없습니다.")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in SUPPORTED_VERSIONS:
        raise ValueError("지원하지 않는 백업 버전입니다. 같은 독립판 버전의 백업을 선택하세요.")
    expected = dict(_expected_objects())
    actual = _objects(db)
    if version<218 and ('table','payment_month_closes') not in actual:
        expected={key:value for key,value in expected.items() if not key[1].startswith('payment_month_close')}
    if version<216 and ('table','document_entry') not in actual:
        expected.pop(('table','document_entry'),None)
    if version<215:
        for table in ('payable_bills','business_entries'):
            if ('table',table) not in actual:expected.pop(('table',table),None)
        for table in ('payments','supplier_settlements'):
            key=('table',table)
            if "'bill'" not in actual.get(key,''):
                expected[key]=expected[key].replace("'cash','transfer','card','bill','dc','rebate','coupon','other_discount'","'cash','transfer','card'")
    if version<214 and ('table','member_registration') not in actual:expected.pop(('table','member_registration'),None)
    if version<214:
        for table in ('payments','supplier_settlements'):
            key=('table',table)
            if "'cash','transfer','card'" not in actual.get(key,''):
                expected[key]=expected[key].replace("'cash','transfer','card'","'cash','transfer'")
    if version < 213 and ('table', 'purchase_imports') not in actual:
        expected.pop(('table', 'purchase_imports'), None)
    if version<212:
        if ('table','sales_order_details') not in actual:expected.pop(('table','sales_order_details'),None)
        changes={
            'products': [('CHECK(ABS(stock_qty)<=9000000000000)','CHECK(stock_qtyBETWEEN0AND9000000000000)'),('CHECK(ABS(stock_cost)<=9000000000000)','CHECK(stock_costBETWEEN0AND9000000000000)')],
            'stock_events': [('CHECK(ABS(balance_qty)<=9000000000000)','CHECK(balance_qtyBETWEEN0AND9000000000000)'),('CHECK(ABS(balance_cost)<=9000000000000)','CHECK(balance_costBETWEEN0AND9000000000000)')],
            'inventory_count_lines': [('CHECK(ABS(expected_qty)<=9000000000000)','CHECK(expected_qty>=0)'),('CHECK(ABS(expected_cost)<=9000000000000)','CHECK(expected_cost>=0)')],
            'inventory_closes':[('CHECK(ABS(stock_cost)<=9000000000000)','CHECK(stock_cost>=0)')],
            'inventory_close_lines':[('CHECK(ABS(stock_qty)<=9000000000000)','CHECK(stock_qty>=0)'),('CHECK(ABS(stock_cost)<=9000000000000)','CHECK(stock_cost>=0)')],
            'sales_forms':[("'tax_reference','order'","'tax_reference'")],
        }
        for table,pairs in changes.items():
            key=('table',table)
            if key in expected and actual.get(key)!=expected[key]:
                for before,after in pairs:
                    if before not in actual.get(key,'') and after in actual.get(key,''):expected[key]=expected[key].replace(before,after)
    if version<211 and ('table','household_plans') not in actual:expected.pop(('table','household_plans'),None)
    for table in ('work_log_details','work_log_files'):
        if version<211 and ('table',table) not in actual:expected.pop(('table',table),None)
    if version<210 and ('table','stock_adjustments') not in actual:
        expected={key:value for key,value in expected.items() if not key[1].startswith('stock_adjustments')}
    if version<210 and ('table','member_contact_types') not in actual:expected.pop(('table','member_contact_types'),None)
    if version<209 and ('table','shared_requests') not in actual:expected.pop(('table','shared_requests'),None)
    if version<209 and ('table','personal_health_receipts') not in actual:expected.pop(('table','personal_health_receipts'),None)
    finance_objects={('table','household_'+name) for name in ('accounts','transfers','fixed_costs','fixed_runs','fixed_alerts','vehicles','vehicle_logs','vehicle_obligations','vehicle_alerts','budgets','category_rules')}|{('table','personal_attachments'),('table','inspiration_history')}
    if version<209 and not finance_objects & actual.keys():
        expected={key:value for key,value in expected.items() if key not in finance_objects}
    email_objects={("table",name) for name in ("email_smtp","recovery_emails","email_challenges","email_private_recovery","household_vaults","household_entries","household_memos","personal_preferences","personal_themes","personal_popup_preferences","desk_event_rules","desk_event_receipts","personal_health_entries")}
    if version<208 and not email_objects & actual.keys():
        expected={key:value for key,value in expected.items() if key not in email_objects}
    private_objects = {("table",name) for name in ("diary_vaults","diary_entries","work_logs")}
    if version<207 and not private_objects & actual.keys():
        expected = {key:value for key,value in expected.items() if key not in private_objects}
    if version<206 and ("table","desk_events") not in actual:
        expected.pop(("table","desk_events"),None)
    offline_objects = {("table", name) for name in ("sales_forms", "member_profiles")}
    if version < 205 and not offline_objects & actual.keys():
        expected = {key: value for key, value in expected.items() if key not in offline_objects}
    if version < 204:
        for table, addition in (("products", ",price_basisINTEGERNOTNULLDEFAULT1CHECK(price_basisIN(1,100))"), ("document_lines", ",price_basisINTEGERNOTNULLDEFAULT1CHECK(price_basisIN(1,100))"), ("documents", ",rounding_modeTEXTNOTNULLDEFAULT'won'CHECK(rounding_modeIN('decimal','won'))")):
            key = ("table", table)
            if addition not in actual.get(key, ""):
                expected[key] = expected[key].replace(addition, "")
    supplier_objects = {("table", name) for name in ("supplier_profiles", "supplier_groups", "supplier_group_members")}
    if version < 203 and not supplier_objects & actual.keys():
        expected = {key: value for key, value in expected.items() if key not in supplier_objects}
    if version == 200:
        expected = {key: value for key, value in expected.items() if key not in {
            (kind, name) for kind, name in (("table", "restore_state"), ("table", "code_sequences"), ("table", "product_categories"), ("index", "category_root_name"), ("table", "supplier_settlements")) if (kind, name) not in actual}}
        # v2.0.0/v2.0.1 did not yet have the retirement marker. Accept only that
        # exact historical column omission, not arbitrary schema changes.
        retirement = ",retirement_targetINTEGERNOTNULLDEFAULT0CHECK(retirement_targetIN(0,1))"
        if actual.get(("table", "products")) == expected[("table", "products")].replace(retirement, ""):
            expected[("table", "products")] = actual[("table", "products")]
        settlement = ",supplier_settlement_idINTEGERREFERENCESsupplier_settlements(id)ONDELETERESTRICT"
        if actual.get(("table", "payments")) == expected[("table", "payments")].replace(settlement, ""):
            expected[("table", "payments")] = actual[("table", "payments")]
    if actual != expected:
        raise ValueError("백업의 데이터 구조가 현재 독립판과 다르거나 변경되었습니다. 안전을 위해 복원하지 않습니다.")
    if ('table','payment_month_closes') in actual:
        from .payment_closing import validate_payment_closes
        validate_payment_closes(db)
        if version<218 and db.execute('SELECT 1 FROM payment_month_closes').fetchone():
            raise ValueError('MIS 결제 월마감 장부는 형식 218 이상으로 복원해야 합니다.')
    if [row[0] for row in db.execute("PRAGMA integrity_check")] != ["ok"]:
        raise ValueError("백업 파일이 손상되어 복원할 수 없습니다.")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("백업의 거래·상품 연결 이력이 손상되어 복원할 수 없습니다.")
    if ('table','document_entry') in actual:
        from .common import day,money,text
        from datetime import datetime
        for entry in db.execute('SELECT e.payload,d.date,(SELECT COUNT(*) FROM document_lines l WHERE l.document_id=d.id) count,d.kind,d.partner_id,d.total FROM document_entry e JOIN documents d ON d.id=e.document_id'):
            try:
                payload=json.loads(entry[0])
                if set(payload)-{'datetime','staff','lines','payment_plan'} or not {'datetime','staff','lines'}<=set(payload):raise ValueError()
                if 'payment_plan' in payload:
                    from .purchase_payment_plan import normalize_plan
                    if version<217:raise ValueError()
                    plan=normalize_plan(payload['payment_plan'])
                    if entry[3]!='purchase' or plan['partner_id']!=entry[4] or money(plan['target'])>entry[5] or plan['datetime'][:10]<entry[1]:raise ValueError()
                stamp=datetime.strptime(payload['datetime'],'%Y-%m-%d %H:%M:%S')
                if stamp.date().isoformat()!=day(entry[1]):raise ValueError()
                text(payload['staff'],'담당자',True,100)
                if not isinstance(payload['lines'],list) or len(payload['lines'])!=entry[2]:raise ValueError()
                for line in payload['lines']:
                    if set(line)!={'sale_price','memo'}:raise ValueError()
                    money(line['sale_price']);text(line['memo'],'품목 메모',maximum=500)
            except (ValueError,TypeError,KeyError,OverflowError):
                raise ValueError('백업의 매입일시·담당자·품목 입력정보가 올바르지 않습니다.') from None
    if ('table','member_registration') in actual:
        from .member_registration import decode
        for row in db.execute('SELECT data FROM member_registration'):decode(row[0])
    if db.execute("SELECT 1 FROM payments p JOIN documents d ON d.id=p.document_id WHERE p.method='card' AND d.kind NOT IN ('purchase','purchase_return') LIMIT 1").fetchone():
        raise ValueError('백업의 카드 수기결제가 매입 이외의 전표에 연결되어 있습니다.')
    if version>=215:
        from .payment_finance import validate_instruments
        validate_instruments(db)
    if ('table', 'purchase_imports') in actual and db.execute("SELECT 1 FROM purchase_imports i JOIN documents d ON d.id=i.document_id WHERE d.kind<>'purchase' LIMIT 1").fetchone():
        raise ValueError('백업의 매입 Excel 가져오기 연결 이력이 올바르지 않습니다.')
    if ("table", "supplier_profiles") in actual:
        if db.execute("SELECT 1 FROM supplier_profiles p JOIN partners s ON s.id=p.partner_id WHERE s.kind<>'supplier' LIMIT 1").fetchone() or db.execute("SELECT 1 FROM supplier_group_members m JOIN partners s ON s.id=m.partner_id WHERE s.kind<>'supplier' LIMIT 1").fetchone():
            raise ValueError("백업의 공급사 정보에 판매처가 연결되어 있습니다.")
        if db.execute("SELECT m.partner_id FROM supplier_group_members m JOIN supplier_groups g ON g.id=m.group_id WHERE g.kind='settlement' GROUP BY m.partner_id HAVING COUNT(*)>1 LIMIT 1").fetchone():
            raise ValueError("백업의 공급사 결제유형이 중복되어 있습니다.")
    if ("table", "product_categories") in actual and db.execute("SELECT c.id FROM product_categories c LEFT JOIN product_categories p ON p.id=c.parent_id WHERE (c.parent_id IS NULL AND c.level<>1) OR (c.parent_id IS NOT NULL AND (p.id IS NULL OR c.level<>p.level+1)) LIMIT 1").fetchone():
        raise ValueError("백업의 상품 분류 연결이 올바르지 않습니다.")
    if ("table", "supplier_settlements") in actual:
        if "supplier_settlement_id" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
            raise ValueError("백업의 결제 배분 구조가 올바르지 않습니다.")
        inconsistent = db.execute("SELECT g.id FROM supplier_settlements g JOIN partners s ON s.id=g.partner_id WHERE s.kind<>'supplier' OR g.amount<>g.opening_amount+(SELECT COALESCE(SUM(p.amount),0) FROM payments p WHERE p.supplier_settlement_id=g.id) LIMIT 1").fetchone()
        mismatched = db.execute("SELECT p.id FROM payments p JOIN supplier_settlements g ON g.id=p.supplier_settlement_id JOIN documents d ON d.id=p.document_id WHERE p.partner_id<>g.partner_id OR p.method<>g.method OR p.date<>g.date OR p.user_id<>g.user_id OR p.voided<>g.voided OR p.amount<=0 OR d.kind<>'purchase' LIMIT 1").fetchone()
        if inconsistent or mismatched:
            raise ValueError("백업의 공급사 결제금액과 전표 배분 내역이 맞지 않습니다.")
    if not db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1 LIMIT 1").fetchone():
        raise ValueError("백업에 활성 관리자 계정이 없습니다. 복원 후 로그인할 수 없어 중단합니다.")
    for row in db.execute("SELECT password_hash,permissions,role FROM users"):
        try:
            algorithm, n, r, p, salt, digest = row[0].split("$")
            if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1") or len(bytes.fromhex(salt)) != 16 or len(bytes.fromhex(digest)) != 32:
                raise ValueError("invalid password hash")
            permissions = json.loads(row[1])
            if not isinstance(permissions, list) or not set(permissions) <= ALLOWED_PERMISSIONS or row[2] != "admin" and "admin" in permissions:
                raise ValueError("invalid permissions")
        except (ValueError, TypeError):
            raise ValueError("백업의 사용자 인증 정보가 올바르지 않습니다.") from None
    settings = {}
    try:
        settings = {row[0]: json.loads(row[1]) for row in db.execute("SELECT key,value FROM settings")}
        for key in ("earn_bps", "point_min", "point_step"):
            value = settings.get(key, {"earn_bps": 100, "point_min": 1000, "point_step": 100}[key])
            if type(value) is not int or not (1 if key == "point_step" else 0) <= value <= (10000 if key == "earn_bps" else 9_000_000_000_000):
                raise ValueError("invalid points policy")
        if type(settings.get("point_enabled", True)) is not bool or not all(isinstance(settings.get(key, ""), str) for key in ("store_name", "business_no", "phone", "address")):
            raise ValueError("invalid settings")
        if type(settings.get('allow_negative_stock',True)) is not bool or not all(isinstance(settings.get(key,''),str) for key in ('representative','business_type','business_category','fax','store_email','bank','account','account_holder','store_memo')):raise ValueError('invalid store profile')
        if len(settings.get('store_memo',''))>500:raise ValueError('invalid store memo')
        if "backup_schedule" in settings:
            validate_schedule(settings["backup_schedule"])
        if "online_info" in settings:
            from .online_info import validate_online
            validate_online(settings["online_info"])
        if 'appearance_theme' in settings:
            from .appearance import valid_theme
            valid_theme(settings['appearance_theme'])
        if any(type(settings.get(key,False)) is not bool for key in ('holiday_skin_enabled','snow_effect_enabled','weather_effect_enabled')):raise ValueError('invalid appearance preferences')
        if settings.get("rounding_mode", "decimal") not in {"decimal", "won"}:
            raise ValueError("invalid rounding policy")
        if ("table", "restore_state") in actual:
            states = db.execute("SELECT token FROM restore_state").fetchall()
            if len(states) != 1:
                raise ValueError("invalid state")
            token = states[0][0]
            if token != "" and (len(token) != 64 or len(bytes.fromhex(token)) != 32):
                raise ValueError("invalid state")
    except (ValueError, TypeError):
        raise ValueError("백업의 매장·포인트 설정이 올바르지 않습니다.") from None
    counts = {table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
              for table in ("users", "products", "partners", "documents", "members", "point_entries")}
    return {"schema_version": version, "store_name": settings.get("store_name", "SY POS"), "counts": counts}


def _copy_database(source, destination, timeout=10):
    """SQLite owns the destination transaction; interruption rolls it back."""
    deadline = time.monotonic() + timeout
    def progress(status, remaining, total):
        # SQLITE_DONE has already committed. Never report a timeout afterwards.
        if status != sqlite3.SQLITE_DONE and time.monotonic() > deadline:
            raise ValueError("데이터베이스가 사용 중이거나 응답이 없습니다. 다른 프로그램을 종료한 뒤 다시 시도하세요.")
    source.backup(destination, pages=128, progress=progress, sleep=.025)


class RecoveryMixin:
    def _init_recovery(self):
        self.db.executescript(RESTORE_SCHEMA)
        self._restore_token = self._current_restore_token()

    def _current_restore_token(self):
        row = self.db.execute("SELECT token FROM restore_state WHERE id=1").fetchone()
        return row[0] if row else None

    @contextmanager
    def _prepared_backup(self, filename):
        source = Path(filename).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("복원할 백업 파일을 선택하세요.")
        if self.path and source.samefile(self.path):
            raise ValueError("현재 사용 중인 장부는 복원 파일로 선택할 수 없습니다.")
        for ending in ("-wal", "-journal"):
            sidecar = Path(str(source) + ending)
            if sidecar.exists() and sidecar.stat().st_size:
                raise ValueError("선택한 파일이 다른 프로그램에서 사용 중입니다. 프로그램을 종료하거나 '백업 파일 저장'으로 만든 파일을 선택하세요.")
        with tempfile.TemporaryDirectory(prefix="seoyoung-restore-") as folder:
            staged = Path(folder) / "verified-backup.db"
            before = source.stat()
            fingerprint = sha256()
            with source.open("rb") as incoming, staged.open("xb") as outgoing:
                first = incoming.read(16)
                if first != b"SQLite format 3\x00":
                    raise ValueError("올바른 SQLite 백업 파일이 아닙니다. ZIP·엑셀 파일은 복원할 수 없습니다.")
                outgoing.write(first)
                fingerprint.update(first)
                while block := incoming.read(1024 * 1024):
                    outgoing.write(block)
                    fingerprint.update(block)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError("확인 중 백업 파일이 변경되었습니다. 다시 선택하세요.")
            db = sqlite3.connect(staged, isolation_level=None, timeout=1)
            try:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                info = _validate_database(db)
                info.update(source=str(source), digest=fingerprint.hexdigest(), size=after.st_size)
                yield db, info
            except sqlite3.Error as exc:
                raise ValueError("백업 파일을 읽거나 복원할 수 없습니다. 손상 여부와 파일 형식을 확인하세요.") from exc
            finally:
                db.close()

    def inspect_backup(self, filename):
        self._require("admin")
        with self._prepared_backup(filename) as (_, info):
            self._require("admin")
            return info

    def restore_backup(self, filename, password, expected_digest=None, _pre_copy_check=None):
        from .store import password_matches
        self._require("admin")
        if getattr(self,'_shared_host_running',False):
            raise ValueError('기준 PC가 공유 중입니다. PC 연결 설정을 단독 사용으로 바꾸고 종료·재실행한 뒤 복원하세요. 다른 PC도 장부 작업을 멈춰야 합니다.')
        if not self.path:
            raise ValueError("파일로 저장되는 장부에서만 복원할 수 있습니다.")
        if self.db.in_transaction:
            raise ValueError("진행 중인 작업이 있습니다. 저장을 마친 뒤 복원하세요.")
        actor = dict(self.actor)
        def reauthenticate():
            self._require("admin")
            row = self.db.execute("SELECT password_hash FROM users WHERE id=?", (actor["id"],)).fetchone()
            if not row or not password_matches(password, row[0]):
                raise ValueError("현재 관리자의 비밀번호가 올바르지 않습니다.")
        reauthenticate()
        with self._prepared_backup(filename) as (staged, info):
            if expected_digest is not None and info["digest"] != expected_digest:
                raise ValueError("미리 확인한 백업 파일이 변경되었습니다. 파일을 다시 선택하세요.")
            reauthenticate()
            # A failed/cancelled validation has not touched the current business DB.
            safety = Path(self.create_backup(before_restore=True))
            reauthenticate()
            from types import SimpleNamespace
            from .schema_upgrade import upgrade_business_schema
            upgrade_business_schema(SimpleNamespace(db=staged,path=None,_opening_version=info['schema_version']))
            initialize(staged)
            staged.executescript(LOYALTY_SCHEMA)
            from .member_registration import REGISTRATION_SCHEMA
            staged.executescript(REGISTRATION_SCHEMA)
            staged.executescript(OPERATIONS_SCHEMA)
            upgrade_currency(SimpleNamespace(db=staged, path=None), info["schema_version"])
            staged.executescript(RESTORE_SCHEMA)
            # Keep code high-water marks even when restoring an older snapshot.
            staged.execute("CREATE TABLE IF NOT EXISTS code_sequences (name TEXT PRIMARY KEY, last_value INTEGER NOT NULL CHECK(last_value>=0))")
            live_sequence = self.db.execute("SELECT last_value FROM code_sequences WHERE name='product'").fetchone()
            if live_sequence:
                staged.execute("INSERT INTO code_sequences(name,last_value) VALUES('product',?) ON CONFLICT(name) DO UPDATE SET last_value=MAX(last_value,excluded.last_value)", (live_sequence[0],))
            staged.execute("INSERT INTO code_sequences(name,last_value) VALUES('user',?) ON CONFLICT(name) DO UPDATE SET last_value=MAX(last_value,excluded.last_value)",(self._user_high_water(),))
            token = secrets.token_hex(32)
            staged.execute("UPDATE restore_state SET token=? WHERE id=1", (token,))
            staged.execute("INSERT INTO audit(at,user_id,action,entity,entity_id,detail) VALUES(?,NULL,'restore','settings',NULL,?)", (
                now(), json.dumps({"source": Path(info["source"]).name, "digest": info["digest"],
                                   "safety_backup": safety.name, "operator_code": actor["code"]}, ensure_ascii=False),
            ))
            _validate_database(staged)
            if _pre_copy_check is not None:_pre_copy_check()
            try:
                _copy_database(staged, self.db)
                _validate_database(self.db)
            except Exception as exc:
                # A retained automatic backup is also used for rollback if a
                # post-copy check fails. Never delete the user's selected file.
                try:
                    saved = sqlite3.connect(safety, isolation_level=None)
                    try:
                        _copy_database(saved, self.db)
                    finally:
                        saved.close()
                    self._restore_token = self._current_restore_token()
                    self.actor = actor
                except Exception as recovery_error:
                    self.actor = None
                    raise RuntimeError(f"복원을 완료하지 못했습니다. 프로그램을 종료하세요. 현재 자료의 보호 백업: {safety}") from recovery_error
                raise ValueError(f"복원을 완료하지 못해 이전 자료로 되돌렸습니다. 보호 백업: {safety}\n{exc}") from exc
            self._restore_token = token
            self.actor = None
            return {**info, "safety_backup": str(safety), "restart_required": True}
