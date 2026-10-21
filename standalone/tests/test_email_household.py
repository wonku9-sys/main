"""Email challenges use mocked delivery; no test contacts a real mailbox."""
from decimal import Decimal
import json
import re
import secrets
import sys

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pos2.store import Store
from pos2.email_recovery import EmailDelivery,validate_smtp,email_address

PASSWORD="Owner-Strong-2026!"


@pytest.fixture
def shop(tmp_path,monkeypatch):
    # Explicit test double only. Production never substitutes for Windows DPAPI.
    key=secrets.token_bytes(32)
    def seal(data):
        nonce=secrets.token_bytes(12);return nonce+AESGCM(key).encrypt(nonce,data,b"test")
    def unseal(data):return AESGCM(key).decrypt(data[:12],data[12:],b"test")
    monkeypatch.setattr("pos2.windows_secrets.protect",seal)
    monkeypatch.setattr("pos2.windows_secrets.unprotect",unseal)
    instant=[1_792_400_000]
    monkeypatch.setattr("pos2.email_recovery.time.time",lambda:instant[0])
    store=Store(tmp_path/"email.db");store.setup_admin("owner","관리자",PASSWORD)
    store.save_mail_settings({"host":"smtp.example.com","port":465,"mode":"ssl","username":"sender@example.com","sender":"sender@example.com","password":"Private-SMTP-Test!"})
    yield store,instant
    store.close()


def code(job):return re.search(r"일회용 인증번호: (\d{8})",job._body)[1]
def secret(job):return re.search(r"\n([A-Za-z0-9_-]{43})\n",job._body)[1]
def delivered(store,job):store.complete_email_delivery(job.identifier,job._receipt,True)


def bind(shop):
    store,clock=shop
    job=store.prepare_email_code("bind",email="owner@example.com",current_password=PASSWORD)
    otp=code(job);delivered(store,job);store.verify_recovery_email(job.identifier,otp);clock[0]+=61


def test_email_is_verified_before_binding_and_change_requires_current_password(shop):
    store,_=shop
    job=store.prepare_email_code("bind",email="owner@example.com",current_password=PASSWORD)
    otp=code(job)
    with pytest.raises(ValueError):store.verify_recovery_email(job.identifier,otp)
    assert not store.recovery_email_status()["verified"]
    delivered(store,job);store.verify_recovery_email(job.identifier,otp)
    assert store.recovery_email_status()["email"]=="owner@example.com"
    with pytest.raises(ValueError):store.verify_recovery_email(job.identifier,otp)
    with pytest.raises(ValueError):store.prepare_email_code("bind",email="attacker@example.com",current_password="Wrong-Password!")


def test_login_reset_preserves_old_password_until_valid_code_and_invalidates_other_sessions(shop):
    store,_=shop;bind(shop)
    twin=Store(store.path);twin.login("owner",PASSWORD)
    try:
        store.logout();job=store.prepare_email_code("login_reset","owner")
        otp=code(job);delivered(store,job)
        with pytest.raises(ValueError):store.reset_password_by_email(job.identifier,"XXXXXXXX","New-Password-2026!","New-Password-2026!")
        twin._require()
        store.reset_password_by_email(job.identifier,otp,"New-Password-2026!","New-Password-2026!")
        with pytest.raises(PermissionError):twin._require()
        with pytest.raises(ValueError):store.login("owner",PASSWORD)
        store.login("owner","New-Password-2026!")
        with pytest.raises(ValueError):store.reset_password_by_email(job.identifier,otp,"Another-Strong-2026!","Another-Strong-2026!")
    finally:twin.close()


@pytest.mark.parametrize("case",["expired","five_wrong","send_failed","password_changed","new_code"])
def test_invalid_or_superseded_codes_never_reset_login(shop,case):
    store,clock=shop;bind(shop)
    job=store.prepare_email_code("login_reset","owner");otp=code(job)
    if case=="send_failed":store.complete_email_delivery(job.identifier,job._receipt,False)
    else:delivered(store,job)
    if case=="expired":clock[0]+=601
    if case=="password_changed":store.change_password(PASSWORD,"Different-Login-2026!")
    if case=="five_wrong":
        for _ in range(5):
            with pytest.raises(ValueError):store.reset_password_by_email(job.identifier,"WRONGOTP","New-Strong-2026!","New-Strong-2026!")
    if case=="new_code":
        clock[0]+=61;store.prepare_email_code("login_reset","owner")
    with pytest.raises(ValueError):store.reset_password_by_email(job.identifier,otp,"New-Strong-2026!","New-Strong-2026!")
    store.login("owner","Different-Login-2026!" if case=="password_changed" else PASSWORD)


def test_resends_are_rate_limited_and_code_is_never_stored_in_database(shop):
    store,clock=shop;bind(shop)
    job=store.prepare_email_code("login_reset","owner");otp=code(job)
    row=store.db.execute("SELECT * FROM email_challenges WHERE id=?",(job.identifier,)).fetchone()
    assert otp not in repr(dict(row))
    assert len(row["digest"])==32
    with pytest.raises(ValueError,match="1분"):store.prepare_email_code("login_reset","owner")
    for _ in range(3):clock[0]+=61;store.prepare_email_code("login_reset","owner")
    clock[0]+=61
    with pytest.raises(ValueError,match="5회"):store.prepare_email_code("login_reset","owner")


def test_smtp_password_is_encrypted_masked_and_not_in_audit(shop):
    store,_=shop
    config=store.mail_settings()
    assert config["configured"] and "password" not in config
    raw=store.db.execute("SELECT config FROM email_smtp").fetchone()[0]
    assert b"Private-SMTP-Test!" not in raw
    assert "Private-SMTP-Test!" not in repr(store.audit_log())


@pytest.mark.parametrize("kind",["diary","household"])
def test_personal_email_recovery_preserves_ciphertext_and_requires_first_mail_key(shop,kind):
    store,clock=shop;bind(shop)
    if kind=="diary":
        store.setup_diary("Private-Diary-2026!","Private-Diary-2026!");key=store.unlock_diary("Private-Diary-2026!")
        store.save_diary_entry(key,{"date":"2026-10-19","title":"개인 제목","body":"암호화 개인 내용"})
    else:
        store.setup_household("Private-Diary-2026!","Private-Diary-2026!");key=store.unlock_household("Private-Diary-2026!")
        store.save_household_entry(key,{"date":"2026-10-19","kind":"expense","title":"개인 지출","category":"생활","amount":"12.34"})
    job=store.prepare_email_code(kind+"_enable",current_password="Private-Diary-2026!")
    rescue,otp=secret(job),code(job);delivered(store,job)
    store.verify_private_email_recovery(kind,job.identifier,otp)
    assert rescue not in repr(store.audit_log())
    assert rescue.encode() not in store.db.execute("SELECT wrapped_key FROM email_private_recovery WHERE kind=?",(kind,)).fetchone()[0]
    clock[0]+=61
    reset=store.prepare_email_code(kind+"_reset");otp=code(reset);delivered(store,reset)
    before=[tuple(r) for r in store.db.execute(f"SELECT id,ciphertext FROM {kind}_entries")]
    with pytest.raises(ValueError):store.reset_password_by_email(reset.identifier,otp,"New-Private-2026!","New-Private-2026!",kind,"wrong")
    store.reset_password_by_email(reset.identifier,otp,"New-Private-2026!","New-Private-2026!",kind,rescue)
    assert before==[tuple(r) for r in store.db.execute(f"SELECT id,ciphertext FROM {kind}_entries")]
    if kind=="diary":
        key=store.unlock_diary("New-Private-2026!");assert store.diary_entries(key)[0]["body"]=="암호화 개인 내용"
    else:
        key=store.unlock_household("New-Private-2026!");assert store.household_report(key,"2026-10-01","2026-10-31")["expense_total"]==Decimal("12.34")


def test_unregistered_private_recovery_does_not_offer_false_recovery(shop):
    store,_=shop;bind(shop);store.setup_diary("Private-Diary-2026!","Private-Diary-2026!")
    with pytest.raises(ValueError,match="사전에"):store.prepare_email_code("diary_reset")


def test_household_exact_amounts_filters_password_toggle_and_no_shop_effect(shop):
    store,_=shop
    store.setup_household();key=store.unlock_household()
    before={table:store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("documents","payments","stock_events","point_entries")}
    store.save_household_entry(key,{"date":"2026-09-30","kind":"income","title":"이월","category":"기타","amount":"1000.25"})
    store.save_household_entry(key,{"date":"2026-10-01","kind":"income","title":"급여","category":"급여","amount":"2000.50"})
    expense=store.save_household_entry(key,{"date":"2026-10-02","kind":"expense","title":"식비","category":"식비","amount":"700.33"})
    report=store.household_report(key,"2026-10-01","2026-10-31")
    assert report["opening_balance"]==Decimal("1000.25") and report["closing_balance"]==Decimal("2300.42")
    assert report["income_total"]==Decimal("2000.50") and report["expense_total"]==Decimal("700.33")
    assert store.household_report(key,"2026-10-01","2026-10-31","식비")["closing_balance"]==Decimal("-700.33")
    store.set_household_password(key,"Cashbook-Strong-2026!","Cashbook-Strong-2026!");store.lock_household()
    with pytest.raises(ValueError):store.unlock_household()
    key=store.unlock_household("Cashbook-Strong-2026!")
    store.delete_household_entry(key,expense)
    assert len(store.household_report(key,"2026-10-01","2026-10-31")["rows"])==1
    assert before=={table:store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}


def test_personal_data_backup_restores_with_password_and_code_expires_after_restore(shop):
    store,_=shop;bind(shop)
    store.setup_household("Cashbook-Strong-2026!","Cashbook-Strong-2026!");key=store.unlock_household("Cashbook-Strong-2026!")
    store.save_household_entry(key,{"date":"2026-10-19","kind":"income","title":"저축","category":"생활","amount":"10.25"})
    job=store.prepare_email_code("login_reset","owner");otp=code(job);delivered(store,job)
    backup=store.create_backup();store.restore_backup(backup,PASSWORD);store.login("owner",PASSWORD)
    with pytest.raises(ValueError):store.reset_password_by_email(job.identifier,otp,"New-Strong-2026!","New-Strong-2026!")
    key=store.unlock_household("Cashbook-Strong-2026!")
    assert store.household_report(key,"2026-10-01","2026-10-31")["closing_balance"]==Decimal("10.25")


@pytest.mark.parametrize("address",["bad","x\n@example.com","x@example.com\r\nBcc:other@example.com","",None])
def test_address_header_injection_is_rejected(address):
    with pytest.raises(ValueError):email_address(address)


def test_smtp_forces_encryption_and_explicit_send(shop,monkeypatch):
    store,_=shop
    calls=[]
    class SMTP:
        def __init__(self,*args,**kwargs):calls.append((args,kwargs))
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def ehlo(self):calls.append("ehlo")
        def starttls(self,**kwargs):calls.append("tls")
        def login(self,*args):calls.append("login")
        def send_message(self,message):calls.append((message["To"],message.get_content()));return {}
    monkeypatch.setattr("pos2.email_recovery.smtplib.SMTP_SSL",SMTP)
    job=store.prepare_email_code("bind",email="owner@example.com",current_password=PASSWORD)
    assert calls==[]
    job.send()
    assert "login" in calls and job._body==""
    assert any(isinstance(item,tuple) and item[0]=="owner@example.com" for item in calls)


@pytest.mark.skipif(sys.platform!="win32",reason="Native Windows user DPAPI is exercised by Windows release CI")
def test_native_windows_dpapi_round_trip():
    # Import fresh primitives rather than the explicit fixture double.
    from pos2.windows_secrets import protect,unprotect
    secret=b"Native-Windows-Only-Test"
    cipher=protect(secret)
    assert secret not in cipher and unprotect(cipher)==secret
