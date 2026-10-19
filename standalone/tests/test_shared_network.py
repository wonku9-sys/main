"""Real loopback TLS, independent clients, atomic writes and local-only privacy."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
import secrets
from uuid import uuid4
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pos2 import __version__
from pos2.store import Store
from pos2.shared_server import SharedService,identity
from pos2.shared_client import ClientStore,LanTransport
from pos2.shared_protocol import encode,fingerprint,private_address

PASSWORD='Owner-Strong-2026!'

def test_frozen_network_smoke_contract_on_real_tls(tmp_path,crypto):
    from pos2.shared_smoke import run
    assert run(tmp_path/'frozen-network-contract')

@pytest.fixture
def crypto(monkeypatch):
    # Explicit non-production double. Native Windows DPAPI has its own test.
    key=secrets.token_bytes(32)
    def seal(payload):
        nonce=secrets.token_bytes(12);return nonce+AESGCM(key).encrypt(nonce,payload,b'network-test')
    monkeypatch.setattr('pos2.windows_secrets.protect',seal)
    monkeypatch.setattr('pos2.windows_secrets.unprotect',lambda payload:AESGCM(key).decrypt(payload[:12],payload[12:],b'network-test'))

@pytest.fixture
def network(tmp_path,crypto):
    owner=Store(tmp_path/'host.db');owner.setup_admin('owner','관리자',PASSWORD)
    supplier=owner.save_partner({'kind':'supplier','name':'공유 공급사'})
    customer=owner.save_partner({'kind':'customer','name':'공유 판매처'})
    product=owner.save_product({'name':'공유 상품','barcode':'00001234','base_unit':'g','price_basis':100,'purchase_price':'1880.25','sale_price':'3800.75'})
    owner.post_document({'kind':'purchase','date':'2026-10-19','partner_id':supplier,'lines':[{'product_id':product,'qty':'1000','unit_price':'1880.25'}]})
    config=identity('127.0.0.1',allow_loopback=True);config['port']=0
    service=SharedService(owner.path,config,True);service.start();config['port']=service.server.server_address[1]
    clients=[]
    try:
        for name in ('pc2','pc3'):
            client=ClientStore(config,tmp_path/name/'personal.db',True);client.login('owner',PASSWORD);clients.append(client)
        yield owner,service,clients,config,supplier,customer,product
    finally:
        for client in clients:client.close()
        service.stop();owner.close()

def purchase(network,quantity='1',price='1234.56'):
    _,_,_,_,supplier,_,product=network
    return {'kind':'purchase','date':'2026-10-19','partner_id':supplier,'lines':[{'product_id':product,'qty':quantity,'unit_price':price}]}

def test_two_clients_see_host_and_each_others_committed_records(network):
    owner,_,(second,third),_,_,_,_=network
    before=third.audit_revision();identifier=second.post_document(purchase(network))
    assert third.document(identifier)['total']==Decimal('12.35')
    assert owner.document(identifier)['total']==Decimal('12.35')
    assert before!=third.audit_revision()
    other=third.post_document(purchase(network,'2'))
    assert second.document(other)['total']==Decimal('24.69')
    assert second.private.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==0

def test_dropped_response_retry_is_exactly_once_and_durable(network,monkeypatch):
    owner,_,(second,_),_,_,_,_=network;data=purchase(network)
    actual=second.transport.request;lost=[False]
    def drop(message):
        result=actual(message)
        if message.get('method')=='post_document' and not lost[0]:lost[0]=True;raise ConnectionError('simulated lost response after commit')
        return result
    monkeypatch.setattr(second.transport,'request',drop)
    with pytest.raises(ConnectionError):second.post_document(data)
    assert second.pending and second.pending_path.exists()
    assert b'1234.56' not in second.pending_path.read_bytes()
    before=len(owner.documents());identifier=second.post_document(data)
    assert len(owner.documents())==before and not second.pending and owner.document(identifier)['total']==Decimal('12.35')

def test_pending_survives_client_reopen_without_copying_business_database(network,monkeypatch):
    owner,_,clients,config,_,_,_=network;second=clients[0];data=purchase(network)
    actual=second.transport.request
    def drop(message):
        result=actual(message)
        if message.get('method')=='post_document':raise ConnectionError('lost result')
        return result
    monkeypatch.setattr(second.transport,'request',drop)
    with pytest.raises(ConnectionError):second.post_document(data)
    path=second.path;second.close();clients.pop(0)
    reopened=ClientStore(config,path,True);reopened.login('owner',PASSWORD);clients.append(reopened)
    before=len(owner.documents());reopened.post_document(data)
    assert len(owner.documents())==before and reopened.private.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==0

def test_unconfirmed_write_blocks_different_write_until_safe_cancel(network,monkeypatch):
    owner,_,(second,_),_,_,_,_=network;actual=second.transport.request
    def offline(message):
        if message.get('method')=='post_document':raise ConnectionError('not delivered')
        return actual(message)
    monkeypatch.setattr(second.transport,'request',offline)
    with pytest.raises(ConnectionError):second.post_document(purchase(network))
    delayed=dict(second.pending)
    with pytest.raises(ValueError,match='미확인|결과'):second.post_document(purchase(network,'2'))
    monkeypatch.setattr(second.transport,'request',actual)
    assert second.cancel_pending()['cancelled']
    with pytest.raises(ValueError,match='취소'):actual(delayed)
    assert len(owner.documents())==1
    second.post_document(purchase(network,'2'));assert len(owner.documents())==2

def test_atomic_concurrent_sales_cannot_oversell(network):
    owner,_,clients,_,_,customer,product=network
    data={'kind':'sale','date':'2026-10-19','partner_id':customer,'lines':[{'product_id':product,'qty':'800','unit_price':'3800.75'}]}
    def sell(client):
        try:return client.post_document(data)
        except ValueError:return None
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(sell,clients))
    assert sum(value is not None for value in results)==1
    assert owner.products()[0]['stock_qty']=='200.000'

def test_stale_product_and_draft_edits_are_rejected_for_host_and_client(network):
    owner,_,(second,third),_,_,_,product=network
    old=second.products()[0]
    owner.save_product({'name':'다른 PC 수정'},product)
    with pytest.raises(ValueError,match='다른 PC'):second.save_product({'name':'덮어쓰기','_expected_token':old['_edit_token']},product)
    draft=second.save_draft(purchase(network));before=second.document(draft)
    current=third.document(draft);third.save_draft(dict(purchase(network,'2'),_expected_token=current['_edit_token']),draft)
    with pytest.raises(ValueError,match='다른 PC'):second.save_draft(dict(purchase(network),_expected_token=before['_edit_token']),draft)
    with pytest.raises(ValueError,match='다른 PC'):owner.post_document(dict(purchase(network),_expected_token=before['_edit_token']),draft)

def test_diary_cashbook_health_and_schedule_never_cross_the_lan(network):
    owner,_,(second,third),_,_,_,_=network
    second.setup_household('Private-Key-2026!','Private-Key-2026!');key=second.unlock_household('Private-Key-2026!')
    second.save_household_memo(key,'2026-10-19','로컬에만 남는 비밀 메모')
    second.save_health_entry('household',key,{'date':'2026-10-19','title':'개인 건강 비밀','category':'growth'})
    account=second.save_household_account(key,{'name':'비밀 금융 통장','opening_date':'2026-01-01','opening_balance':'123.45'})
    car=second.save_household_vehicle(key,{'name':'개인 자동차'})
    entry=second.save_household_entry(key,{'date':'2026-10-19','kind':'expense','title':'개인 차량 보험','amount':'1.25','account_id':account,'vehicle_id':car,'vehicle_type':'insurance'})
    second.add_personal_attachment(key,'household','entry',entry,'개인보험.pdf',b'Private insurance document')
    second.inspiration(True)
    assert owner.db.execute('SELECT COUNT(*) FROM household_accounts').fetchone()[0]==0
    assert owner.db.execute('SELECT COUNT(*) FROM personal_attachments').fetchone()[0]==0
    assert not third.household_status()['exists'] and not owner.household_status()['exists']
    assert owner.db.execute('SELECT COUNT(*) FROM personal_health_entries').fetchone()[0]==0
    with pytest.raises(PermissionError):second.transport.request({'command':'call','method':'household_memos','args':[],'kwargs':{}})
    backup=second.backup_on_exit();assert Path(backup).is_file()

def test_pair_code_and_certificate_are_both_required(network):
    _,_,_,config,_,_,_=network
    wrong=dict(config,client_key='x'*43)
    with pytest.raises(PermissionError):LanTransport(wrong,True).request({'command':'hello'})
    wrong=dict(config,certificate=identity('127.0.0.1',allow_loopback=True)['certificate'])
    with pytest.raises(ConnectionError):LanTransport(wrong,True).request({'command':'hello'})

def test_incompatible_version_and_private_admin_rpc_are_rejected(network):
    _,service,(second,_),_,_,_,_=network
    with pytest.raises(ValueError):service.handle({'version':'old','command':'hello'},'','127.0.0.1')
    with pytest.raises(PermissionError):second.transport.request({'command':'call','method':'restore_backup','args':[],'kwargs':{}})
    assert second.actor['role']=='staff' and second.actor['host_admin']

def test_live_permission_recheck_and_password_change_invalidate_other_client(network):
    owner,_,(second,third),_,_,_,_=network
    second.change_password(PASSWORD,'New-Strong-2026!')
    with pytest.raises(PermissionError):third.poll_status()

def test_old_pending_cannot_replay_after_host_restore(network,monkeypatch):
    owner,_,(second,_),_,_,_,_=network;backup=owner.create_backup();actual=second.transport.request
    def not_delivered(message):
        if message.get('method')=='post_document':raise ConnectionError('offline')
        return actual(message)
    monkeypatch.setattr(second.transport,'request',not_delivered)
    with pytest.raises(ConnectionError):second.post_document(purchase(network))
    delayed=dict(second.pending);owner.restore_backup(backup,PASSWORD);owner.login('owner',PASSWORD)
    monkeypatch.setattr(second.transport,'request',actual);second.login('owner',PASSWORD)
    with pytest.raises(ValueError,match='복원'):second.post_document(purchase(network))
    with pytest.raises(ValueError,match='복원'):actual(delayed)
    assert second.pending and second.pending_status()['stale_epoch']
    assert second.cancel_pending()['cancelled']
    second.post_document(purchase(network));assert len(owner.documents())==2

def test_pending_is_bound_to_original_user(network,monkeypatch):
    owner,_,(second,_),_,_,_,_=network
    owner.save_user({'code':'staff','name':'직원','password':'Staff-Strong-2026!','role':'staff','permissions':['trade']})
    actual=second.transport.request
    def not_delivered(message):
        if message.get('method')=='post_document':raise ConnectionError('offline')
        return actual(message)
    monkeypatch.setattr(second.transport,'request',not_delivered)
    with pytest.raises(ConnectionError):second.post_document(purchase(network))
    monkeypatch.setattr(second.transport,'request',actual);second.logout();second.login('staff','Staff-Strong-2026!')
    with pytest.raises(PermissionError,match='다른 계정'):second.pending_status()
    with pytest.raises(PermissionError,match='다른 계정'):second.post_document(purchase(network))
    assert second.pending
    second.logout();second.login('owner',PASSWORD);assert second.cancel_pending()['cancelled']

def test_local_ack_write_failure_keeps_retry_identity(network,monkeypatch):
    owner,_,(second,_),_,_,_,_=network;persist=second._persist_pending
    def disk_failure():
        if second.pending is None:raise OSError('disk full')
        persist()
    monkeypatch.setattr(second,'_persist_pending',disk_failure)
    with pytest.raises(ConnectionError):second.post_document(purchase(network))
    assert second.pending and len(owner.documents())==2
    monkeypatch.setattr(second,'_persist_pending',persist);second.post_document(purchase(network))
    assert second.pending is None and len(owner.documents())==2

def test_authentication_failure_never_discards_a_previously_unknown_write(network,monkeypatch):
    owner,_,(second,third),_,_,_,_=network;actual=second.transport.request
    def lost(message):
        result=actual(message)
        if message.get('method')=='post_document':raise ConnectionError('lost after commit')
        return result
    monkeypatch.setattr(second.transport,'request',lost)
    with pytest.raises(ConnectionError):second.post_document(purchase(network))
    monkeypatch.setattr(second.transport,'request',actual);third.change_password(PASSWORD,'Changed-Strong-2026!')
    with pytest.raises(PermissionError):second.post_document(purchase(network))
    assert second.pending
    second.login('owner','Changed-Strong-2026!');second.post_document(purchase(network))
    owner.login('owner','Changed-Strong-2026!')
    assert len(owner.documents())==2 and second.pending is None
    second.post_document(purchase(network))

@pytest.mark.parametrize('address',['8.8.8.8','0.0.0.0','169.254.2.1','127.0.0.1','0.0.0.1','host.example.com'])
def test_only_internal_numeric_addresses_are_accepted(address):
    with pytest.raises(ValueError):private_address(address)

def test_connection_file_contains_no_secret_and_local_config_is_dpapi_protected(tmp_path,crypto):
    from pos2.shared_config import save_config,load_config,public_bundle
    config=dict(identity('192.168.0.5'),mode='host');path=tmp_path/'connection.json'
    save_config(path,config);raw=path.read_text()
    assert config['client_key'] not in raw and config['private_key'] not in raw
    assert load_config(path)==config
    bundle=encode(public_bundle(config));assert config['client_key'] not in bundle and 'PRIVATE KEY' not in bundle
