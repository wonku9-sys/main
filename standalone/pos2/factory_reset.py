"""Owner-authorized business reset, preserving private records and login keys.

No universal reset password is shipped. The dedicated owner credential is
registered locally by an authenticated administrator and stored as salted scrypt.
"""
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import tempfile

RESET_ID='wonku9'
PRESERVED_TABLES=frozenset('users desk_events desk_event_rules desk_event_receipts diary_vaults diary_entries work_logs work_log_details work_log_files household_vaults household_entries household_memos household_accounts household_transfers household_fixed_costs household_fixed_runs household_fixed_alerts household_vehicles household_vehicle_logs household_vehicle_obligations household_vehicle_alerts household_budgets household_category_rules household_plans personal_preferences personal_themes personal_popup_preferences personal_health_entries personal_health_receipts personal_attachments inspiration_history recovery_emails email_private_recovery email_smtp'.split())
BUSINESS_TABLES=frozenset('audit cash_closes code_sequences document_lines documents email_challenges gift_redemptions gifts inventory_close_lines inventory_closes inventory_count_lines inventory_counts loyalty_return_actions loyalty_sale_actions member_contact_types member_prices member_profiles members partners payments point_entries price_schedules product_categories product_units products promotion_items promotions purchase_imports restore_state sales_forms sales_order_details settings shared_requests stock_adjustments stock_events supplier_group_members supplier_groups supplier_profiles supplier_settlements'.split())
BUSINESS_TABLES=BUSINESS_TABLES|{'member_registration','payable_bills','business_entries'}


def private_digest(db):
    result=sha256()
    for table in sorted(PRESERVED_TABLES):
        result.update(table.encode())
        for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
            result.update(repr(tuple(row)).encode('utf-8'));result.update(b'\n')
    return result.hexdigest()


class FactoryResetMixin:
    def _require_reset_context(self):
        self._require('admin');self.require_menu('settings')
        if not self.path or getattr(self,'_shared_host_running',False) or getattr(self,'_shared_outer_transaction',False):
            raise ValueError('단독 사용 중인 기준 PC의 파일 장부에서만 초기화할 수 있습니다. 공유를 해제하고 재실행하세요.')
        if self.db.in_transaction:raise ValueError('진행 중인 저장 작업을 마친 뒤 다시 시도하세요.')

    def _reset_authority_path(self):
        self._require_reset_context()
        path=self.path.parent/'reset-authority.json'
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)():raise ValueError('초기화 인증 파일에 링크를 사용할 수 없습니다.')
        return path

    def _reset_authority(self):
        path=self._reset_authority_path()
        if not path.exists():return None
        try:
            if not path.is_file() or path.stat().st_size>4096:raise ValueError()
            data=json.loads(path.read_text(encoding='utf-8'))
            if set(data)!={'version','id','password_hash'} or data['version']!=1 or data['id']!=RESET_ID or not isinstance(data['password_hash'],str) or not re.fullmatch(r'scrypt\$16384\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{64}',data['password_hash']):raise ValueError()
            return data
        except (ValueError,TypeError,UnicodeError):raise ValueError('초기화 인증 파일이 올바르지 않습니다. 업무자료를 변경하지 않았습니다.') from None

    def reset_authority_configured(self):return self._reset_authority() is not None

    def _verify_reset_admin(self,password):
        from .store import password_matches
        actor=self._require('admin')
        current=self.db.execute('SELECT password_hash FROM users WHERE id=?',(actor['id'],)).fetchone()
        if not current or not password_matches(password,current[0]):raise ValueError('현재 관리자 인증에 실패했습니다.')

    def configure_reset_authority(self,admin_password,identifier,password,confirmation,previous=''):
        from PySide6.QtCore import QSaveFile,QIODevice
        from .store import password_hash,password_matches
        self._require_reset_context();self._verify_reset_admin(admin_password)
        if not hmac.compare_digest(str(identifier).strip().encode('utf-8'),RESET_ID.encode()):raise ValueError('초기화 전용 아이디가 올바르지 않습니다.')
        if password!=confirmation:raise ValueError('초기화 비밀번호 확인이 일치하지 않습니다.')
        existing=self._reset_authority()
        if existing and not password_matches(previous,existing['password_hash']):raise ValueError('기존 초기화 비밀번호 인증에 실패했습니다.')
        digest=password_hash(password);path=self._reset_authority_path()
        self._verify_reset_admin(admin_password)
        output=QSaveFile(str(path));payload=json.dumps(dict(version=1,id=RESET_ID,password_hash=digest)).encode('utf-8')
        if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(payload)!=len(payload) or not output.commit():raise OSError('초기화 인증 정보를 보관하지 못했습니다.')
        if os.name!='nt':path.chmod(0o600)
        with self._tx():self._require('admin');self._audit('reset_authority','settings',None,{'id':RESET_ID})
        return True

    def _verify_reset_owner(self,identifier,password):
        from .store import password_matches
        data=self._reset_authority()
        if not data:raise ValueError('먼저 이 PC에서 초기화 전용 인증을 등록하세요.')
        if not hmac.compare_digest(str(identifier).strip().encode('utf-8'),RESET_ID.encode()) or not password_matches(password,data['password_hash']):
            raise ValueError('초기화 전용 아이디 또는 비밀번호가 올바르지 않습니다. 초기화하지 않았습니다.')

    def business_reset_plan(self):
        self._require_reset_context()
        return {table:self.db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in ('products','partners','documents','members','sales_forms')}

    def reset_business_data(self,admin_password,identifier,password,phrase):
        from .store import Store
        from .recovery import _validate_database
        self._require_reset_context();self._verify_reset_admin(admin_password);self._verify_reset_owner(identifier,password)
        if phrase!='업무자료 초기화':raise ValueError('최종 확인 문구가 일치하지 않습니다. 초기화하지 않았습니다.')
        tables={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables!=PRESERVED_TABLES|BUSINESS_TABLES:raise ValueError('분류되지 않은 자료 구조가 있습니다. 안전을 위해 초기화하지 않습니다.')
        _validate_database(self.db)
        # A real retained protection backup is made before preparing any reset.
        snapshot=self.create_backup(before_restore=True);revision=self.audit_revision()
        with self._prepared_backup(snapshot) as (source,_):
            expected_private=private_digest(source)
            with tempfile.TemporaryDirectory(prefix='sy-business-reset-') as folder:
                fresh=Store(Path(folder)/'new-business.db')
                try:
                    fresh.db.execute('BEGIN IMMEDIATE');fresh.db.execute('PRAGMA defer_foreign_keys=ON')
                    for table in sorted(PRESERVED_TABLES):
                        cursor=source.execute(f'SELECT * FROM "{table}"')
                        width=len(cursor.description);sql=f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in range(width))})'
                        while rows:=cursor.fetchmany(128):fresh.db.executemany(sql,[tuple(r) for r in rows])
                    # Weather/calendar preferences are not business records.
                    for row in source.execute("SELECT key,value FROM settings WHERE key='online_info'"):
                        fresh.db.execute('INSERT INTO settings(key,value) VALUES(?,?)',tuple(row))
                    fresh.db.commit();_validate_database(fresh.db)
                    if private_digest(fresh.db)!=expected_private:raise ValueError('개인 기록 보존 검사가 실패했습니다. 초기화하지 않았습니다.')
                finally:fresh.close()
                def guard():
                    self._require_reset_context();self._verify_reset_admin(admin_password);self._verify_reset_owner(identifier,password)
                    changed=self.db.execute("SELECT 1 FROM audit WHERE id>? AND NOT(entity='settings' AND action IN ('backup','managed_backup')) LIMIT 1",(revision[1],)).fetchone()
                    if self._current_restore_token()!=revision[0] or changed or private_digest(self.db)!=expected_private:
                        raise ValueError('준비 중 자료가 변경됐습니다. 초기화하지 않았습니다. 다시 확인하세요.')
                guard()
                result=self.restore_backup(fresh.path,admin_password,_pre_copy_check=guard)
                result.update(business_reset=True,source_snapshot=snapshot,private_preserved=True)
                return result
