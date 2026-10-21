"""Native frozen-EXE LAN self-test, loopback only and no live business data."""
from decimal import Decimal
from pathlib import Path
from .store import Store
from .shared_server import SharedService,identity
from .shared_client import ClientStore


def run(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    owner=Store(root/'host.db');service=None;clients=[]
    try:
        owner.setup_admin('network-smoke','가상 검사 계정','Network-Smoke-2026!')
        supplier=owner.save_partner({'kind':'supplier','name':'공유 검사용 가상 공급사'})
        product=owner.save_product({'name':'공유 검사용 가상 상품','base_unit':'g','price_basis':100})
        config=identity('127.0.0.1',allow_loopback=True);config['port']=0
        service=SharedService(owner.path,config,True);service.start();config['port']=service.server.server_address[1]
        for label in ('pc2','pc3'):
            client=ClientStore(config,root/label/'personal.db',True);clients.append(client);client.login('network-smoke','Network-Smoke-2026!')
        second,third=clients
        payload={'kind':'purchase','date':'2026-01-01','partner_id':supplier,'lines':[{'product_id':product,'qty':'100','unit_price':'123.45'}]}
        actual=second.transport.request
        def lost_response(message):
            result=actual(message)
            if message.get('method')=='post_document':raise ConnectionError('intentional lost response')
            return result
        second.transport.request=lost_response
        try:second.post_document(payload)
        except ConnectionError:pass
        else:raise AssertionError('Loss recovery path was not exercised')
        assert second.pending and second.pending_path.is_file()
        second.transport.request=actual;identifier=second.post_document(payload)
        assert len(owner.documents())==1 and third.document(identifier)['total']==Decimal('123.45')
        second.setup_household('Private-Smoke-2026!','Private-Smoke-2026!');key=second.unlock_household('Private-Smoke-2026!')
        second.save_household_account(key,{'name':'공유하지 않는 가상 통장','opening_date':'2026-01-01','opening_balance':'12.34'})
        assert not third.household_status()['exists'] and owner.db.execute('SELECT COUNT(*) FROM household_accounts').fetchone()[0]==0
        return True
    finally:
        for client in clients:client.close()
        if service:service.stop()
        owner.close()
