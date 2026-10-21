"""Customer registration, every reference condition, credit and safe address bridge."""
from datetime import date
from decimal import Decimal
import http.client,json,sqlite3
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QCoreApplication,QDate,QEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from pos2.store import Store
from pos2.loyalty_ui import MemberDialog,MembersPage
from pos2.member_registration import credit_balances

PASSWORD='Customer-Test-Only-2026!'


@pytest.fixture
def shop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    from pos2.popup_policy import install_popup_policy
    install_popup_policy(app)
    store=Store(tmp_path/'customer.db');store.setup_admin('owner','시험 관리자',PASSWORD)
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:pytest.fail(str(args[2])))
    yield app,store
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def save_customer(s,index=1,**changes):
    values=dict(code=f'M{index}',name=f'가상 회원 {index}',phone=f'010-{index:08d}',birthday='1980-12-25',anniversary='2000-01-03',
                member_type='도매회원',address='가상시 시험동',group_name='시험그룹',
                registration=dict(abc='A',grade='우수',wholesale_grade='도매1',staff_name='담당 예시',postcode='12345',
                                  address_detail='가상 101호',email='test@example.invalid',credit_allowed=True,credit_limit='100.25'))
    values.update(changes);return s.save_member(values)


def sale(s,member,amount,paid='0'):
    product=s.save_product(dict(name='가상 판매품',base_unit='개',tracked=False))
    return s.post_document(dict(kind='sale',partner_id=1,member_id=member,date=date.today().isoformat(),
        paid=paid,lines=[dict(product_id=product,qty='1',unit_price=amount)]))


def test_registration_roundtrip_cancel_and_partial_update_preserve_details(shop):
    app,s=shop;dialog=MemberDialog(s);dialog.fields['name'].setText('가상 고객')
    dialog.detail_fields['postcode'].setText('12345');dialog.fields['address'].setText('가상주소');dialog.detail_fields['address_detail'].setText('상세 1층')
    dialog.credit_allowed.setChecked(True);dialog.detail_fields['credit_limit'].setText('100.25')
    dialog.save();record=s.members()[0]
    assert record['registration']['postcode']=='12345' and record['registration']['credit_limit']==Decimal('100.25')
    s.save_member({'memo':'연락 완료'},record['id']);assert s.members()[0]['registration']==record['registration']
    again=MemberDialog(s,s.members()[0]);again.fields['name'].setText('저장하지 않음');again.reject()
    assert s.members()[0]['name']=='가상 고객'


@pytest.mark.parametrize('bad',[{'credit_limit':'-1'},{'credit_limit':'0.001'},{'credit_allowed':'yes'},{'postcode':'123'},{'email':'bad'},{'abc':'Z'},{'family_count':-1}])
def test_invalid_registration_rolls_back_member_and_audit(shop,bad):
    _,s=shop;before=s.audit_revision()
    with pytest.raises(ValueError):s.save_member(dict(code='BAD',name='잘못된 입력',registration=bad))
    assert not s.members() and s.audit_revision()==before


def test_credit_limit_is_exact_collect_return_refund_and_denied_void(shop):
    _,s=shop;member=save_customer(s);first=sale(s,member,'100.25','20.00')
    assert s.member_credit_summary(member)['credit_balance']==Decimal('80.25')
    before=len(s.documents())
    with pytest.raises(ValueError,match='한도'):sale(s,member,'20.01')
    assert len(s.documents())==before
    payment=s.add_payment(first,'30.25',date.today().isoformat(),'transfer')
    assert s.member_credit_summary(member)['credit_available']==Decimal('50.25')
    second=sale(s,member,'50.25')
    assert s.member_credit_summary(member)['credit_balance']==Decimal('100.25')
    with pytest.raises(ValueError,match='한도'):s.void_payment(payment,'한도 초과 취소')
    record=s.document(second);line=record['lines'][0]
    returned=s.post_document(dict(kind='sale_return',partner_id=1,source_id=second,date=date.today().isoformat(),
        lines=[dict(product_id=line['product_id'],source_line_id=line['id'],qty='1')],paid='0'))
    assert s.member_credit_summary(member)['credit_balance']==Decimal('50.00')
    s.void_payment(payment,'반품 후 취소')
    assert s.member_credit_summary(member)['credit_balance']==Decimal('80.25')
    s.save_member({'registration':{'credit_allowed':False}},member)
    with pytest.raises(ValueError,match='전액'):sale(s,member,'1')
    s.add_payment(first,'80.25',date.today().isoformat(),'transfer')
    assert s.member_credit_summary(member)['credit_balance']==0
    assert s.member_credit_summary(member)['credit_limit']==Decimal('100.25')


def test_old_members_default_to_full_payment_and_backup_preserves_customer_data(shop):
    _,s=shop;member=s.save_member(dict(code='OLD',name='기존 회원'))
    with pytest.raises(ValueError,match='전액'):sale(s,member,'10.25')
    first=sale(s,member,'10.25','10.25')
    with pytest.raises(ValueError):s.void_payment(s.document(first)['payments'][0]['id'],'기존 전액 유지')
    save_customer(s,2);before=s.members();backup=s.create_backup();s.restore_backup(backup,PASSWORD);s.login('owner',PASSWORD)
    assert s.members()==before


def test_every_reference_filter_uses_stored_values_and_recent_cap(shop):
    app,s=shop;save_customer(s,1);save_customer(s,2,active=False);save_customer(s,3,member_type='일반고객',registration={'abc':'D','postcode':'54321'})
    page=MembersPage(SimpleNamespace(store=s));page.refresh();q=page.customer_query
    assert [r['id'] for r in q.matches]==[3,1]
    q.limit.setValue(1);page.refresh();assert q.matches[0]['code']=='M3'
    q.top.setChecked(False);q.kind.setCurrentIndex(q.kind.findData('도매회원'));page.refresh();assert [r['code'] for r in q.matches]==['M1']
    for combo,value in ((q.wholesale,'도매1'),(q.abc,'A'),(q.grade,'우수'),(q.group,'시험그룹')):
        combo.setCurrentIndex(combo.findData(value));page.refresh();assert len(q.matches)==1
    q.staff_name.setText('담당');q.staff.setChecked(True);q.postcode.setText('123');q.address.setText('101호');page.refresh();assert len(q.matches)==1
    for key in ('created','birthday','anniversary'):
        enabled,start,end=q.ranges[key]
        if key=='created':start.setDate(QDate.currentDate());end.setDate(QDate.currentDate())
        else:start.setDate(QDate(2000,12,20));end.setDate(QDate(2001,1,5))
        enabled.setChecked(True);page.refresh();assert len(q.matches)==1
    sale(s,1,'1');enabled,start,end=q.ranges['last'];start.setDate(QDate.currentDate());end.setDate(QDate.currentDate());enabled.setChecked(True)
    q.credit.setCurrentIndex(q.credit.findData('outstanding'));page.refresh();assert len(q.matches)==1
    q.search.setText('등록되지 않은 이름');page.refresh();assert not q.matches
    q.timer.stop();page.deleteLater()


def test_members_listing_has_no_per_member_sql_and_recent_top500_pages(shop):
    _,s=shop
    with s._tx():
        s.db.executemany("INSERT INTO members(code,name,created_at,updated_at) VALUES(?,?,'2026-10-21','2026-10-21')",[(f'M{i}',f'가상 회원 {i}') for i in range(1100)])
    statements=[];s.db.set_trace_callback(statements.append);assert len(s.members())==1100;s.db.set_trace_callback(None)
    assert sum(x.lstrip().upper().startswith('SELECT') for x in statements)<10
    page=MembersPage(SimpleNamespace(store=s));page.refresh();assert page.grid.rowCount()==100
    page.customer_query.top.setChecked(False);page.refresh();assert page.grid.rowCount()==500 and len(page.grid.export_rows())==1100
    page.customer_query.move(1);assert page.grid.rowCount()==500
    page.customer_query.move(1);assert page.grid.rowCount()==100
    page.customer_query.timer.stop();page.deleteLater()


def test_address_bridge_opt_in_nonce_origin_single_use_and_no_identity(shop,monkeypatch):
    from pos2.address_lookup import AddressLookup
    _,_=shop;opened=[];monkeypatch.setattr('pos2.address_lookup.QDesktopServices.openUrl',lambda url:opened.append(url.toString()) or True)
    bridge=AddressLookup();received=[];bridge.selected.connect(received.append)
    url=bridge.start('가상 주소');connection=http.client.HTTPConnection('127.0.0.1',bridge.server.server_port,timeout=3)
    try:
        connection.request('GET','/wrong');assert connection.getresponse().status==404
        connection.close();connection=http.client.HTTPConnection('127.0.0.1',bridge.server.server_port,timeout=3)
        connection.request('GET','/'+bridge.token);response=connection.getresponse();html=response.read().decode()
        assert response.status==200 and 't1.daumcdn.net' in html and '회원번호' not in html
        connection.request('POST','/'+bridge.token,json.dumps({'postcode':'12345','address':'가상시 시험동'}),{'Content-Type':'application/json','Origin':'https://outside.invalid'})
        response=connection.getresponse();assert response.status==403;response.read()
        connection.request('POST','/'+bridge.token,json.dumps({'postcode':'12345','address':'가상시 시험동'}),{'Content-Type':'application/json','Origin':bridge.origin})
        response=connection.getresponse();assert response.status==200;response.read()
        QApplication.instance().processEvents();assert received==[{'postcode':'12345','address':'가상시 시험동'}] and bridge.used
    finally:connection.close();bridge.stop()
