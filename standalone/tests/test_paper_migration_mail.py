"""A real v211 schema upgrade and encrypted SMTP image attachments."""
from datetime import date
from decimal import Decimal
import re
import sqlite3
import secrets
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PySide6.QtWidgets import QApplication
from pos2.store import Store


def test_actual_v211_constraints_upgrade_is_backed_up_and_preserves_all_links(tmp_path,monkeypatch):
    import pos2.schema as schema
    import pos2.operations as operations
    import pos2.offline_features as offline
    path=tmp_path/'legacy.db'
    with monkeypatch.context() as patch:
        old=schema.SCHEMA
        for name in ('stock_qty','stock_cost','balance_qty','balance_cost'):
            old=old.replace(f'CHECK(ABS({name})<=9000000000000)',f'CHECK({name} BETWEEN 0 AND 9000000000000)')
        old_ops=operations.OPERATIONS_SCHEMA
        for name in ('expected_qty','expected_cost','stock_qty','stock_cost'):
            old_ops=old_ops.replace(f'CHECK(ABS({name})<=9000000000000)',f'CHECK({name}>=0)')
        old_forms=offline.OFFLINE_SCHEMA.replace("'tax_reference','order'","'tax_reference'")
        old_forms=re.sub(r'CREATE TABLE IF NOT EXISTS sales_order_details \([\s\S]*?\n\);\n','',old_forms)
        patch.setattr(schema,'SCHEMA',old);patch.setattr(schema,'OFFLINE_SCHEMA',old_forms)
        patch.setattr(schema,'OPERATIONS_SCHEMA',old_ops,raising=False);patch.setattr(operations,'OPERATIONS_SCHEMA',old_ops)
        original=Store(path);original.setup_admin('owner','관리자','Owner-Password-2026!')
        supplier=original.save_partner(dict(kind='supplier',name='원공급사'));customer=original.save_partner(dict(kind='customer',name='원고객'))
        product=original.save_product(dict(name='원상품',base_unit='개',purchase_price='100.12',sale_price='200.34'))
        doc=original.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,lines=[dict(product_id=product,qty='3',unit_price='100.12')]))
        paper=original.save_sales_form('quotation',dict(date=date.today().isoformat(),partner_id=customer,lines=[dict(product_id=product,qty='1',unit_price='200.34')]))
        original.db.execute('PRAGMA user_version=211');original.close()
    before=path.read_bytes();upgraded=Store(path)
    try:
        upgraded.login('owner','Owner-Password-2026!')
        assert upgraded.migration_backup_path and upgraded.db.execute('PRAGMA user_version').fetchone()[0]==212
        assert upgraded.document(doc)['total']==Decimal('300.36')
        assert upgraded.sales_form(paper)['customer']['name']=='원고객'
        assert upgraded.db.execute('PRAGMA foreign_key_check').fetchone() is None
        assert len(list(upgraded.db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'product_cross%'")))==2
        assert upgraded.inspect_backup(upgraded.migration_backup_path)['schema_version']==211
        upgraded.post_document(dict(kind='sale',date=date.today().isoformat(),partner_id=customer,lines=[dict(product_id=product,qty='5',unit_price='200.34')]))
        assert upgraded.products()[0]['stock_qty']=='-2.000'
        current_backup=upgraded.create_backup()
        assert upgraded.inspect_backup(current_backup)['schema_version']==212
        backup=sqlite3.connect(upgraded.migration_backup_path)
        try:
            assert backup.execute('PRAGMA user_version').fetchone()[0]==211
            assert backup.execute('SELECT stock_qty FROM products WHERE id=?',(product,)).fetchone()[0]==3000
        finally:backup.close()
    finally:upgraded.close()


def test_document_email_is_explicitly_addressed_png_and_clears_job_secrets(tmp_path,monkeypatch):
    from pos2 import windows_secrets,email_recovery
    from pos2.document_mail import prepare_document_mail
    app=QApplication.instance() or QApplication([])
    key=secrets.token_bytes(32)
    def protect(payload):
        nonce=secrets.token_bytes(12);return nonce+AESGCM(key).encrypt(nonce,payload,b'windows-user')
    monkeypatch.setattr(windows_secrets,'protect',protect)
    monkeypatch.setattr(windows_secrets,'unprotect',lambda payload:AESGCM(key).decrypt(payload[:12],payload[12:],b'windows-user'))
    s=Store(tmp_path/'mail.db');s.setup_admin('owner','관리자','Owner-Password-2026!')
    try:
        customer=s.save_partner(dict(kind='customer',name='받는 상점'));product=s.save_product(dict(name='품목',sale_price='10.01'))
        identifier=s.save_sales_form('quotation',dict(date=date.today().isoformat(),partner_id=customer,lines=[dict(product_id=product,qty='1',unit_price='10.01')]))
        record=s.sales_form(identifier)
        with pytest.raises(ValueError,match='SMTP'):prepare_document_mail(s,record,'견적서','recipient@example.com')
        s.save_mail_settings(dict(host='smtp.example.com',port=465,mode='ssl',username='sender@example.com',password='FAKE-APP-PASSWORD',sender='sender@example.com'))
        with pytest.raises(ValueError):prepare_document_mail(s,record,'견적서','bad\r\nBcc:secret@example.com')
        sent=[]
        class FakeSMTP:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def ehlo(self):pass
            def login(self,*args):assert args==('sender@example.com','FAKE-APP-PASSWORD')
            def send_message(self,message):sent.append(message);return {}
        monkeypatch.setattr(email_recovery.smtplib,'SMTP_SSL',FakeSMTP)
        job=prepare_document_mail(s,record,'견적서','recipient@example.com')
        assert 'FAKE-APP-PASSWORD' not in repr(job)
        job.send();assert len(sent)==1 and sent[0]['To']=='recipient@example.com'
        attachments=list(sent[0].iter_attachments());assert attachments and attachments[0].get_content_type()=='image/png'
        assert attachments[0].get_payload(decode=True).startswith(b'\x89PNG')
        assert job._body=='' and job._attachments==()
    finally:s.close()
