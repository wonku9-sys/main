"""Local supplier contact details and grouping; no online ordering credentials."""
from .common import text


PROFILE_TEXT = ("representative", "business_type", "business_item", "representative_mobile", "fax", "mobile", "email", "postal_code", "address", "homepage")
PROFILE_DEFAULTS = {**dict.fromkeys(PROFILE_TEXT, ""), "settlement_method": "cash", "settlement_day": 0}
GROUP_KINDS = {"settlement": "결제유형", "general": "일반그룹"}

SUPPLIER_SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_profiles (
 partner_id INTEGER PRIMARY KEY REFERENCES partners(id) ON DELETE CASCADE,
 representative TEXT NOT NULL DEFAULT '', business_type TEXT NOT NULL DEFAULT '',
 business_item TEXT NOT NULL DEFAULT '', representative_mobile TEXT NOT NULL DEFAULT '',
 fax TEXT NOT NULL DEFAULT '', mobile TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
 postal_code TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', homepage TEXT NOT NULL DEFAULT '',
 settlement_method TEXT NOT NULL DEFAULT 'cash' CHECK(settlement_method IN ('cash','transfer')),
 settlement_day INTEGER NOT NULL DEFAULT 0 CHECK(settlement_day BETWEEN 0 AND 31)
);
CREATE TABLE IF NOT EXISTS supplier_groups (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('settlement','general')),
 code TEXT NOT NULL, name TEXT NOT NULL,
 sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order BETWEEN 0 AND 1000000),
 UNIQUE(kind,code), UNIQUE(kind,name)
);
CREATE TABLE IF NOT EXISTS supplier_group_members (
 group_id INTEGER NOT NULL REFERENCES supplier_groups(id) ON DELETE CASCADE,
 partner_id INTEGER NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
 PRIMARY KEY(group_id,partner_id)
);
"""


class SupplierMixin:
    def set_supplier_payment_method(self, identifiers, method):
        if method not in ('cash', 'transfer') or not isinstance(identifiers, (list, tuple)) or not 1 <= len(identifiers) <= 10000:
            raise ValueError('공급사와 결제방법을 선택하세요.')
        if any(type(i) is not int or i <= 0 for i in identifiers):
            raise ValueError('공급사 선택을 확인하세요.')
        with self._tx():
            self._require_capability('suppliers', 'edit')
            rows = []
            for identifier in dict.fromkeys(identifiers):
                row = self.db.execute("SELECT id,name FROM partners WHERE id=? AND kind='supplier'", (identifier,)).fetchone()
                if not row:
                    raise ValueError('삭제되었거나 공급사가 아닌 항목이 있습니다.')
                rows.append(row)
            changed = 0
            for row in rows:
                before = self._supplier_profile(row['id'])['settlement_method']
                if before == method:
                    continue
                self._save_supplier_profile(row['id'], {'settlement_method': method})
                self._audit('update', 'partner', row['id'], {'name': row['name'], 'settlement_method_before': before, 'settlement_method_after': method})
                changed += 1
        return changed

    def set_suppliers_active(self, identifiers, active):
        """Change only supplier availability, atomically and without touching ledgers."""
        if type(active) is not bool or not isinstance(identifiers, (list, tuple)) or not identifiers:
            raise ValueError('공급사와 유효/무효 상태를 선택하세요.')
        if len(identifiers) > 10000 or any(type(i) is not int or i <= 0 for i in identifiers):
            raise ValueError('공급사 선택을 확인하세요.')
        identifiers = list(dict.fromkeys(identifiers))
        with self._tx():
            self._require_capability('suppliers', 'edit')
            rows = []
            for identifier in identifiers:
                row = self.db.execute("SELECT id,name,active FROM partners WHERE id=? AND kind='supplier'", (identifier,)).fetchone()
                if not row:
                    raise ValueError('삭제되었거나 공급사가 아닌 항목이 있습니다. 다시 조회하세요.')
                rows.append(row)
            changed = 0
            for row in rows:
                if bool(row['active']) == active:
                    continue
                self.db.execute('UPDATE partners SET active=? WHERE id=?', (int(active), row['id']))
                self._audit('update', 'partner', row['id'], {'name': row['name'], 'active_before': bool(row['active']), 'active_after': active})
                changed += 1
        return changed

    def _init_supplier_management(self):
        if not self.db.execute("SELECT 1 FROM supplier_groups LIMIT 1").fetchone():
            for code, name in (("10", "장부"), ("20", "회전결제"), ("30", "마감일지정결제")):
                self.db.execute("INSERT OR IGNORE INTO supplier_groups(kind,code,name,sort_order) VALUES('settlement',?,?,?)", (code, name, int(code)))

    def _supplier_profile(self, identifier):
        row = self.db.execute("SELECT * FROM supplier_profiles WHERE partner_id=?", (identifier,)).fetchone()
        result = {**PROFILE_DEFAULTS, **(dict(row) if row else {})}
        result.pop("partner_id", None)
        groups = [dict(row) for row in self.db.execute("SELECT g.* FROM supplier_groups g JOIN supplier_group_members m ON m.group_id=g.id WHERE m.partner_id=? ORDER BY g.kind,g.sort_order,g.code", (identifier,))]
        result["groups"] = groups
        result["group_ids"] = [row["id"] for row in groups]
        result["settlement_group_id"] = next((row["id"] for row in groups if row["kind"] == "settlement"), None)
        result["settlement_type"] = " · ".join(row["name"] for row in groups if row["kind"] == "settlement")
        result["group_names"] = " · ".join(row["name"] for row in groups if row["kind"] == "general")
        return result

    def _save_supplier_profile(self, identifier, data):
        current = self._supplier_profile(identifier)
        values = {key: text(data.get(key, current[key]), key, False, 1000 if key == "address" else 300) for key in PROFILE_TEXT}
        values["settlement_method"] = data.get("settlement_method", current["settlement_method"])
        if not isinstance(values["settlement_method"], str) or values["settlement_method"] not in {"cash", "transfer"}:
            raise ValueError("결제방법은 현금 또는 계좌이체를 선택하세요.")
        raw = data.get("settlement_day", current["settlement_day"])
        try:
            day = int(raw)
        except (ValueError, TypeError, OverflowError):
            raise ValueError("약정 결제일은 0~31로 입력하세요. 0은 미지정입니다.") from None
        if isinstance(raw, bool) or str(raw).strip() != str(day) or not 0 <= day <= 31:
            raise ValueError("약정 결제일은 0~31로 입력하세요. 0은 미지정입니다.")
        values["settlement_day"] = day
        columns = tuple(values)
        self.db.execute("INSERT INTO supplier_profiles(partner_id," + ",".join(columns) + ") VALUES(?" + ",?" * len(columns) + ") ON CONFLICT(partner_id) DO UPDATE SET " + ",".join(f"{key}=excluded.{key}" for key in columns), (identifier, *values.values()))
        if "settlement_group_id" in data:
            group = data["settlement_group_id"] or None
            if group and not self.db.execute("SELECT 1 FROM supplier_groups WHERE id=? AND kind='settlement'", (group,)).fetchone():
                raise ValueError("결제유형 그룹을 다시 선택하세요.")
            self.db.execute("DELETE FROM supplier_group_members WHERE partner_id=? AND group_id IN (SELECT id FROM supplier_groups WHERE kind='settlement')", (identifier,))
            if group:
                self.db.execute("INSERT INTO supplier_group_members(group_id,partner_id) VALUES(?,?)", (group, identifier))

    def supplier_groups(self, kind=None):
        self.require_menu("suppliers")
        if kind is not None and kind not in GROUP_KINDS:
            raise ValueError("그룹 종류를 선택하세요.")
        return [dict(row) for row in self.db.execute("SELECT g.*, (SELECT COUNT(*) FROM supplier_group_members m WHERE m.group_id=g.id) AS member_count FROM supplier_groups g" + (" WHERE kind=?" if kind else "") + " ORDER BY kind,sort_order,code,id", (kind,) if kind else ())]

    def save_supplier_group(self, data, identifier=None):
        with self._tx():
            self._require_capability("suppliers", "edit")
            old = self.db.execute("SELECT * FROM supplier_groups WHERE id=?", (identifier,)).fetchone() if identifier else None
            if identifier and not old:
                raise ValueError("그룹을 찾을 수 없습니다.")
            kind = data.get("kind", old["kind"] if old else "general")
            if not isinstance(kind, str) or kind not in GROUP_KINDS or old and kind != old["kind"]:
                raise ValueError("기존 그룹의 종류는 변경할 수 없습니다.")
            code = text(data.get("code", old["code"] if old else ""), "그룹코드", True, 30)
            name = text(data.get("name", old["name"] if old else ""), "그룹명", True, 100)
            raw = data.get("sort_order", old["sort_order"] if old else 0)
            try:
                order = int(raw)
            except (ValueError, TypeError, OverflowError):
                raise ValueError("순번은 0~1000000의 정수로 입력하세요.") from None
            if isinstance(raw, bool) or str(raw).strip() != str(order) or not 0 <= order <= 1000000:
                raise ValueError("순번은 0~1000000의 정수로 입력하세요.")
            if old:
                self.db.execute("UPDATE supplier_groups SET code=?,name=?,sort_order=? WHERE id=?", (code, name, order, identifier))
            else:
                identifier = self.db.execute("INSERT INTO supplier_groups(kind,code,name,sort_order) VALUES(?,?,?,?)", (kind, code, name, order)).lastrowid
            self._audit("save_supplier_group", "supplier_group", identifier, {"kind": kind, "code": code, "name": name})
        return identifier

    def delete_supplier_group(self, identifier):
        with self._tx():
            self._require_capability("suppliers", "edit")
            if self.db.execute("SELECT 1 FROM supplier_group_members WHERE group_id=?", (identifier,)).fetchone():
                raise ValueError("소속 공급사를 먼저 해제한 뒤 그룹을 삭제하세요.")
            if not self.db.execute("DELETE FROM supplier_groups WHERE id=?", (identifier,)).rowcount:
                raise ValueError("그룹을 찾을 수 없습니다.")
            self._audit("delete_supplier_group", "supplier_group", identifier, {})

    def supplier_group_members(self, identifier):
        self.require_menu("suppliers")
        if not self.db.execute("SELECT 1 FROM supplier_groups WHERE id=?", (identifier,)).fetchone():
            raise ValueError("그룹을 선택하세요.")
        return [row[0] for row in self.db.execute("SELECT partner_id FROM supplier_group_members WHERE group_id=? ORDER BY partner_id", (identifier,))]

    def set_supplier_group_members(self, identifier, members, expected=None):
        with self._tx():
            self._require_capability("suppliers", "edit")
            current = self.supplier_group_members(identifier)
            if expected is not None and sorted(expected) != current:
                raise ValueError("그룹 소속이 변경되었습니다. 다시 조회한 후 저장하세요.")
            if not isinstance(members, (list, tuple)) or any(type(value) is not int for value in members):
                raise ValueError("공급사를 목록에서 선택하세요.")
            selected = sorted(set(members))
            for partner in selected:
                if not self.db.execute("SELECT 1 FROM partners WHERE id=? AND kind='supplier'", (partner,)).fetchone():
                    raise ValueError("공급사만 그룹에 등록할 수 있습니다.")
            group = self.db.execute("SELECT kind FROM supplier_groups WHERE id=?", (identifier,)).fetchone()
            self.db.execute("DELETE FROM supplier_group_members WHERE group_id=?", (identifier,))
            for partner in selected:
                if group["kind"] == "settlement":
                    self.db.execute("DELETE FROM supplier_group_members WHERE partner_id=? AND group_id IN (SELECT id FROM supplier_groups WHERE kind='settlement')", (partner,))
                self.db.execute("INSERT INTO supplier_group_members(group_id,partner_id) VALUES(?,?)", (identifier, partner))
            self._audit("supplier_group_members", "supplier_group", identifier, {"members": selected})
