"""Validated customer registration metadata and exact, source-linked credit."""
import json
import re
from .common import LIMIT,day,money,text

MEMBER_TYPES=('일반고객','요식업소','상점','회사/오피스','단체/관공서','직원','도매회원','직영점','가맹점')
REGISTRATION_SCHEMA="""
CREATE TABLE IF NOT EXISTS member_registration (
 member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
 data TEXT NOT NULL DEFAULT '{}'
);
"""
DEFAULTS=dict(abc='D',grade='',wholesale_grade='정상가',staff_name='',gender='',family_count=0,
              phone2='',email='',business_type='',business_category='',postcode='',address_detail='',
              delivery_memo='',birthday_calendar='solar',credit_allowed=False,credit_limit=0,
              closing_day=1,identifiers=[],vehicles=[])


def registration(db,member_id):
    row=db.execute('SELECT data FROM member_registration WHERE member_id=?',(member_id,)).fetchone()
    return decode(row[0] if row else '{}')


def decode(value):
    try:
        record=json.loads(value)
        if not isinstance(record,dict) or set(record)-set(DEFAULTS):raise ValueError()
        if 'credit_limit' in record:
            if type(record['credit_limit']) is not int or not 0<=record['credit_limit']<=LIMIT:raise ValueError()
            from .currency import amount
            record['credit_limit']=amount(record['credit_limit'])
        return validate(record)
    except (ValueError,TypeError):raise ValueError('고객 상세정보 형식이 올바르지 않습니다.') from None


def validate(values,previous=None):
    if not isinstance(values,dict) or set(values)-set(DEFAULTS):raise ValueError('지원하지 않는 고객 등록 항목입니다.')
    result=dict(DEFAULTS,**(previous or {}))
    for key in ('abc','grade','wholesale_grade','staff_name','gender','phone2','email','business_type','business_category',
                'postcode','address_detail','delivery_memo','birthday_calendar'):
        if key in values:result[key]=text(values[key],key,False,500 if key in {'address_detail','delivery_memo'} else 100)
    if result['abc'] not in {'','A','B','C','D'} or result['gender'] not in {'','여','남'} or result['birthday_calendar'] not in {'solar','lunar'}:raise ValueError('ABC·성별·생일 기준을 확인하세요.')
    if result['postcode'] and not re.fullmatch(r'\d{5}',result['postcode']):raise ValueError('우편번호는 5자리 숫자로 입력하세요.')
    if result['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',result['email']):raise ValueError('이메일 형식을 확인하세요.')
    for key,low,high in (('family_count',0,100),('closing_day',1,31)):
        if key in values:
            try:
                number=int(str(values[key]))
                if str(number)!=str(values[key]).strip() or not low<=number<=high:raise ValueError()
            except (ValueError,TypeError):raise ValueError(f'{key} 입력 범위를 확인하세요.') from None
            result[key]=number
    if 'credit_allowed' in values:
        if type(values['credit_allowed']) is not bool:raise ValueError('외상거래 허용은 체크 값이어야 합니다.')
        result['credit_allowed']=values['credit_allowed']
    if 'credit_limit' in values:result['credit_limit']=money(values['credit_limit'])
    for key in ('identifiers','vehicles'):
        if key not in values:continue
        if not isinstance(values[key],list) or len(values[key])>50:raise ValueError('추가 인식정보·차량은 각각 50개까지 등록할 수 있습니다.')
        result[key]=[]
        for row in values[key]:
            expected={'code','description'} if key=='identifiers' else {'plate','last_discount'}
            if not isinstance(row,dict) or set(row)!=expected:raise ValueError('인식정보·차량정보 항목을 확인하세요.')
            clean={k:text(v,k,False,100) for k,v in row.items()}
            if clean.get('last_discount'):clean['last_discount']=day(clean['last_discount'])
            primary='code' if key=='identifiers' else 'plate'
            if not clean[primary]:raise ValueError('인식번호·차량번호는 비워 둘 수 없습니다.')
            if any(r[primary]==clean[primary] for r in result[key]):raise ValueError('인식번호·차량번호가 중복됩니다.')
            result[key].append(clean)
    return result


def credit_balances(db,member_id=None):
    # cash_paid is maintained from non-void payments in the same transaction.
    # Refunds reduce the return's unpaid credit, never double-release a limit.
    query="""SELECT d.member_id,SUM(MAX(0,d.total-d.points_used-d.cash_paid-COALESCE(r.credit,0))) credit_balance
        FROM documents d LEFT JOIN (
          SELECT source_id,SUM(total-points_used-cash_paid) credit FROM documents
          WHERE kind='sale_return' AND status='posted' GROUP BY source_id
        ) r ON r.source_id=d.id WHERE d.kind='sale' AND d.status='posted' AND d.member_id IS NOT NULL"""
    args=()
    if member_id is not None:query+=' AND d.member_id=?';args=(member_id,)
    query+=' GROUP BY d.member_id'
    return {r[0]:r[1] for r in db.execute(query,args)}


def assert_credit(store,member_id,additional=0):
    policy=registration(store.db,member_id)
    balance=credit_balances(store.db,member_id).get(member_id,0)+additional
    if additional>0 and not policy['credit_allowed']:raise ValueError('회원 매출은 전액 정산해야 합니다. 고객정보에서 외상거래 허용을 먼저 확인하세요.')
    if balance>policy['credit_limit']:raise ValueError('회원 외상한도를 초과합니다. 미수금을 수금하거나 한도를 확인하세요.')
    return balance


class MemberRegistrationMixin:
    def member_credit_summary(self,member_id):
        self._loyalty_require_any('loyalty','trade','reports');self._member_row(member_id)
        policy=registration(self.db,member_id)
        balance=credit_balances(self.db,member_id).get(member_id,0)
        return dict(member_id=member_id,credit_allowed=policy['credit_allowed'],credit_limit=policy['credit_limit'],
                    credit_balance=balance,credit_available=max(0,policy['credit_limit']-balance))
