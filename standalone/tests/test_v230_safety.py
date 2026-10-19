"""Migration, offline-network fallback and new UI permissions are regression gates."""
from decimal import Decimal
from datetime import datetime,timezone
import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from pos2.store import Store
from pos2.currency import MONEY_COLUMNS
from pos2.online_info import DEFAULT_ONLINE,validate_online,fetch_online


@pytest.fixture
def store(tmp_path):
    result=Store(tmp_path/"safety.db");result.setup_admin("owner","관리자","Owner-Strong-2026!")
    yield result
    result.close()


def test_real_old_whole_won_schema_upgrades_once_without_quantity_conversion(tmp_path):
    path=tmp_path/"old-v220.db"
    old=Store(path);old.setup_admin("owner","관리자","Owner-Strong-2026!")
    supplier=old.save_partner({"name":"옛 공급사","kind":"supplier","opening_balance":1000})
    product=old.save_product({"name":"기존 kg","base_unit":"kg","purchase_price":1650,"sale_price":3800})
    document=old.post_document({"kind":"purchase","date":"2026-09-15","partner_id":supplier,"lines":[{"product_id":product,"qty":"10.1","unit_price":1650}],"paid":100})
    old.inventory_close("2026-09")
    protected=[tuple(r) for r in old.db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('inventory_closes','inventory_close_lines','cash_closes')")]
    for name,_ in protected:old.db.execute(f'DROP TRIGGER "{name}"')
    for table,columns in MONEY_COLUMNS.items():
        old.db.execute(f'UPDATE "{table}" SET '+','.join(f'"{c}"="{c}"/100' for c in columns))
    for _,sql in protected:old.db.execute(sql)
    for table,column in (("products","price_basis"),("document_lines","price_basis"),("documents","rounding_mode")):
        old.db.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
    for table in ("personal_health_entries","desk_event_receipts","desk_event_rules","email_private_recovery","email_challenges","recovery_emails","email_smtp","household_memos","household_entries","household_vaults","personal_preferences","personal_themes","personal_popup_preferences","diary_entries","diary_vaults","work_logs","desk_events","sales_forms","member_profiles","supplier_group_members","supplier_groups","supplier_profiles"):
        old.db.execute(f'DROP TABLE "{table}"')
    old.db.execute("PRAGMA user_version=202");old.close()
    upgraded=Store(path)
    try:
        upgraded.login("owner","Owner-Strong-2026!")
        assert upgraded.document(document)["total"]==Decimal("16665.00")
        assert upgraded.document(document)["cash_paid"]==Decimal("100.00")
        assert upgraded.document(document)["lines"][0]["base_qty"]=="10.100"
        assert upgraded.products()[0]["purchase_price"]==Decimal("1650.00")
        assert upgraded.products()[0]["price_basis"]==1
        assert upgraded.inventory_closes()[0]["stock_cost"]==Decimal("16665.00")
        assert upgraded.migration_backup_path
        upgraded.inspect_backup(upgraded.migration_backup_path)
        source=sqlite3.connect(upgraded.migration_backup_path)
        try:assert source.execute("SELECT total FROM documents").fetchone()[0]==16665
        finally:source.close()
        with pytest.raises(sqlite3.IntegrityError):upgraded.db.execute("UPDATE inventory_closes SET stock_cost=0")
    finally:upgraded.close()
    again=Store(path)
    try:
        again.login("owner","Owner-Strong-2026!")
        assert again.document(document)["total"]==Decimal("16665.00")
        assert again.migration_backup_path is None
    finally:again.close()


def test_network_features_are_opt_in_and_never_use_ip_location(monkeypatch):
    assert DEFAULT_ONLINE["enabled"] is False
    calls=[]
    def mock(url):
        calls.append(url)
        if "weather.go.kr" in url:
            from pos2.online_info import kma_grid
            from datetime import datetime,timezone,timedelta
            stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d%H%M')
            x,y=kma_grid(36.8151,127.1139)
            return f'<wid><header><tm>{stamp}</tm><x>{x}</x><y>{y}</y></header><body><data><day>1</day><hour>24</hour><temp>17.5</temp><sky>1</sky><pty>0</pty></data></body></wid>'.encode()
        assert "timeapi.io" in url
        return b'{"dateTime":"2026-10-19T09:00:00","timeZone":"Asia/Seoul"}'
    monkeypatch.setattr("pos2.online_info._read",mock)
    assert fetch_online(DEFAULT_ONLINE)=={"disabled":True} and calls==[]
    result=fetch_online(dict(DEFAULT_ONLINE,enabled=True,city="천안",latitude=36.8151,longitude=127.1139))
    assert result["city"]=="천안" and "17.5" in result["weather"]
    assert len(calls)==2 and "gridx=" in calls[0] and 'gridy=' in calls[0]
    assert all("ipapi" not in url and "ipwho" not in url for url in calls)


def test_online_failure_falls_back_without_throwing(monkeypatch):
    def unavailable(url):raise OSError("offline")
    monkeypatch.setattr("pos2.online_info._read",unavailable)
    result=fetch_online(dict(DEFAULT_ONLINE,enabled=True))
    assert result["weather_error"] and result["clock_error"]


@pytest.mark.parametrize("bad",[{},{"enabled":"yes"},dict(DEFAULT_ONLINE,latitude="NaN"),dict(DEFAULT_ONLINE,longitude=181),dict(DEFAULT_ONLINE,city="")])
def test_network_preferences_validate_coordinates_without_connecting(bad):
    with pytest.raises(ValueError):validate_online(bad)


def test_supplier_failed_profile_rolls_back_main_info_and_membership(store):
    supplier=store.save_partner({"kind":"supplier","name":"원래 공급사","fax":"123"})
    with pytest.raises(ValueError):store.save_partner({"name":"잘못 바뀐 이름","settlement_day":32},supplier)
    record=store.partners("supplier")[0]
    assert record["name"]=="원래 공급사" and record["fax"]=="123"


def test_supplier_group_stale_guard_and_foreign_member_are_atomic(store):
    supplier=store.save_partner({"kind":"supplier","name":"공급사"})
    customer=store.save_partner({"kind":"customer","name":"판매처"})
    group=store.save_supplier_group({"kind":"general","name":"지역","code":"1"})
    store.set_supplier_group_members(group,[supplier])
    with pytest.raises(ValueError,match="변경"):store.set_supplier_group_members(group,[],expected=[])
    with pytest.raises(ValueError):store.set_supplier_group_members(group,[customer])
    assert store.supplier_group_members(group)==[supplier]


def test_separate_diary_password_is_required_even_for_empty_vault(store):
    store.setup_diary("Private-Diary-2026!","Private-Diary-2026!")
    with pytest.raises(ValueError):store.save_diary_entry(bytearray(32),{"date":"2026-10-19","title":"우회"})
    key=store.unlock_diary("Private-Diary-2026!")
    store.lock_diary()
    with pytest.raises(ValueError):store.diary_entries(key)


def test_admin_login_password_reset_does_not_unlock_private_diary(store):
    store.setup_diary("Private-Diary-2026!","Private-Diary-2026!")
    key=store.unlock_diary("Private-Diary-2026!")
    store.save_diary_entry(key,{"date":"2026-10-19","title":"개인","body":"비밀"})
    store.change_password("Owner-Strong-2026!","Changed-Login-2026!")
    store.logout();store.login("owner","Changed-Login-2026!")
    with pytest.raises(ValueError):store.unlock_diary("Changed-Login-2026!")
    key=store.unlock_diary("Private-Diary-2026!")
    assert store.diary_entries(key)[0]["body"]=="비밀"


def test_work_logs_are_private_and_edits_deletes_require_permission(store):
    identifier=store.save_work_log({"date":"2026-10-19","title":"업무","body":"정산"})
    user=store.save_user({"code":"staff","name":"직원","password":"Staff-Strong-2026!","role":"staff","permissions":[]})
    store.login("staff","Staff-Strong-2026!")
    assert store.work_logs("2026-10-01","2026-10-31")==[]
    with pytest.raises(ValueError):store.delete_work_log(identifier)
    store.login("owner","Owner-Strong-2026!")
    store.save_user({"permissions":["deny:worklog.create"]},user)
    store.login("staff","Staff-Strong-2026!")
    with pytest.raises(PermissionError):store.save_work_log({"date":"2026-10-19","title":"금지"})
