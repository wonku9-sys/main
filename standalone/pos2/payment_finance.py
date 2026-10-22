"""Manual financial records: exact amounts, atomic allocation, no bank/VAN API.

Issuing a bill transfers supplier debt to a separately visible bill liability.
Paying that bill must never reduce supplier debt for a second time. Discounts
are non-cash settlements, not payments or changes to inventory cost/VAT.
"""
from datetime import date
import json
from calendar import monthrange
from .common import day,money,text,now
from .currency import amount as public_amount
from .shared_protocol import fingerprint

METHODS={'cash':'현금','transfer':'계좌이체','card':'카드 수기','bill':'어음',
         'dc':'D/C','rebate':'장려금','coupon':'쿠폰/스폰','other_discount':'기타 할인'}
DISCOUNTS={'dc','rebate','coupon','other_discount'}


def validate_instruments(db):
    if db.execute("SELECT 1 FROM payments p JOIN documents d ON d.id=p.document_id WHERE p.method NOT IN ('cash','transfer','card') AND (d.kind<>'purchase' OR p.amount<=0) LIMIT 1").fetchone():
        raise ValueError('할인·어음의 매입전표 연결이 올바르지 않습니다.')
    for kind,table,key in (('settlement','supplier_settlements','settlement_id'),('payment','payments','payment_id')):
        if db.execute(f"SELECT 1 FROM {table} p LEFT JOIN payable_bills b ON b.{key}=p.id WHERE p.method='bill' AND "+("p.supplier_settlement_id IS NULL AND " if kind=='payment' else '')+"b.id IS NULL LIMIT 1").fetchone():
            raise ValueError('어음 발행 정보가 누락되었습니다.')
    cursor=db.execute("SELECT b.*,COALESCE(s.date,p.date) issue_date,COALESCE(s.method,p.method) method,COALESCE(s.voided,p.voided) voided FROM payable_bills b LEFT JOIN supplier_settlements s ON s.id=b.settlement_id LEFT JOIN payments p ON p.id=b.payment_id")
    for raw in cursor:
        r=dict(zip((c[0] for c in cursor.description),raw))
        if r['method']!='bill' or day(r['due_date'])<r['issue_date'] or (r['paid_date'] and (r['voided'] or day(r['paid_date'])<r['due_date'])):
            raise ValueError('어음 만기·지급 상태가 올바르지 않습니다.')


class PaymentFinanceMixin:
    def purchase_payment_batch(self,payment_id,source_type='payment'):
        """Immutable batch membership comes from the original posting audit."""
        self._require('trade');self.require_menu('payments')
        if source_type=='payment':self.require_menu('purchases')
        if source_type not in {'payment','settlement'}:raise ValueError('매입 결제 유형을 확인하세요.')
        table='payments' if source_type=='payment' else 'supplier_settlements'
        row=self.db.execute("SELECT p.* FROM payments p JOIN documents d ON d.id=p.document_id WHERE p.id=? AND d.kind='purchase' AND d.status='posted'",(payment_id,)).fetchone() if source_type=='payment' else self.db.execute('SELECT * FROM supplier_settlements WHERE id=?',(payment_id,)).fetchone()
        if not row or row['voided'] or source_type=='payment' and row['supplier_settlement_id']:
            raise ValueError('유효한 매입 결제 이력을 선택하세요. 묶음 배분행은 공급사 결제에서 선택하세요.')
        document_id=row['document_id'] if source_type=='payment' else None
        audit=self.db.execute("SELECT a.detail FROM audit a,json_each(a.detail,'$.records') r WHERE a.action='financial_payment_batch' AND a.entity='partner' AND a.entity_id=? AND json_extract(r.value,'$.type')=? AND json_extract(r.value,'$.id')=? ORDER BY a.id DESC LIMIT 1",(row['partner_id'],source_type,payment_id)).fetchone()
        detail=json.loads(audit[0]) if audit else {}
        ids=[r['id'] for r in detail.get('records',[]) if r['type']==source_type] or [payment_id]
        rows=[dict(self.db.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone()) for identifier in ids]
        if any(r['voided'] or r['partner_id']!=row['partner_id'] or r['date']!=row['date'] or source_type=='payment' and (r['document_id']!=document_id or r['supplier_settlement_id']) for r in rows):
            raise ValueError('일부 결제가 취소·변경된 묶음입니다. 최신 결제 이력을 확인하세요.')
        values={k:sum(r['amount'] for r in rows if r['method']==k) for k in METHODS}
        bill=self.db.execute(f"SELECT number,due_date,bank,paid_date FROM payable_bills WHERE {'payment_id' if source_type=='payment' else 'settlement_id'} IN ("+','.join('?' for _ in ids)+')',ids).fetchone()
        plan=detail.get('details') or dict(partner_id=row['partner_id'],target=str(public_amount(sum(values.values()))),components={k:str(public_amount(v)) for k,v in values.items()},datetime=row['date']+' 00:00:00',account='',memo=row['memo'],bill=dict(bill) if bill else None)
        if plan['bill']:plan['bill']={k:plan['bill'][k] for k in ('number','due_date','bank')}
        snapshot=self.payment_context(row['partner_id'],row['date'],document_id)
        allocations=[dict(r) for r in self.db.execute('SELECT * FROM payments WHERE supplier_settlement_id IN ('+','.join('?' for _ in ids)+') ORDER BY id',ids)] if source_type=='settlement' else []
        reason=self._payment_edit_reason(rows+allocations,dict(bill) if bill else None)
        state=fingerprint(dict(rows=rows,supplier=snapshot['state'],bill=dict(bill) if bill else None,allocations=allocations,closing=self._payment_close_state()))
        return dict(plan=plan,payment_ids=ids,source_type=source_type,document_id=document_id,cap=snapshot['cap']+sum(values.values()),state=state,
                    editable=not reason,edit_reason=reason)

    def replace_purchase_payment_batch(self,payment_id,plan,expected_state,reason,source_type='payment'):
        with self._tx():
            self._require_capability('payments','create')
            current=self._void_purchase_payment_batch_in_tx(payment_id,expected_state,reason,source_type)
            from .purchase_payment_plan import normalize_plan
            plan=normalize_plan(plan)
            if plan['partner_id']!=current['plan']['partner_id']:
                raise ValueError('결제 수정에서는 공급사를 변경할 수 없습니다.')
            snapshot=self.payment_context(plan['partner_id'],plan['datetime'][:10],current['document_id'])
            result=self._register_supplier_payment_in_tx(plan['partner_id'],plan['components'],plan['datetime'][:10],plan['memo'],snapshot['state'],current['document_id'],plan['bill'],plan)
            self._audit('replace_purchase_payment_batch','payment',payment_id,dict(reason=reason,replacements=result['records']))
            return result

    def void_purchase_payment_batch(self,payment_id,expected_state,reason,source_type='payment'):
        with self._tx():
            self._void_purchase_payment_batch_in_tx(payment_id,expected_state,reason,source_type)

    def _void_purchase_payment_batch_in_tx(self,payment_id,expected_state,reason,source_type='payment'):
        self._require_capability('payments','delete')
        current=self.purchase_payment_batch(payment_id,source_type)
        if current['state']!=expected_state:raise ValueError('결제·잔액이 바뀌었습니다. 최신 이력을 다시 조회하세요.')
        if not current['editable']:raise ValueError(current['edit_reason'])
        reason=text(reason,'결제 정정 사유',True,500)
        for identifier in current['payment_ids']:
            if source_type=='payment':self._void_trade_payment(identifier,reason)
            else:self._void_supplier_settlement_in_tx(identifier,reason)
        return current

    def payment_context(self,partner_id,payment_date=None,document_id=None):
        self._require('trade');self.require_menu('payments')
        when=day(payment_date or date.today())
        if when>date.today().isoformat():raise ValueError('미래 날짜에는 결제를 등록할 수 없습니다.')
        outstanding=self.supplier_outstanding(partner_id,when)
        cap=outstanding['cap'];document=None
        if document_id is not None:
            data=self.purchase_payment_context(document_id,when)
            if data['partner']['id']!=partner_id:raise ValueError('매입전표와 공급사가 일치하지 않습니다.')
            cap=data['cap'];document=data['document']
        closing=self._payment_close_state()
        closed=bool(closing and when<=closing['through_date'])
        state=fingerprint(dict(supplier=outstanding['state'],document=document,date=when,cap=cap,closing=closing))
        return dict(partner=outstanding['partner'],document=document,cap=cap,
                    balance=outstanding['balance'],as_of=outstanding['as_of'],date=when,user_name=self.actor['name'],state=state,
                    opening=outstanding['opening'],documents=outstanding['documents'],payment_closed=closed,
                    closed_through=closing['through_date'] if closing else '')

    def register_supplier_payment(self,partner_id,components,payment_date,memo='',expected_state=None,document_id=None,bill=None,details=None):
        with self._tx():
            return self._register_supplier_payment_in_tx(partner_id,components,payment_date,memo,expected_state,document_id,bill,details)

    def _register_supplier_payment_in_tx(self,partner_id,components,payment_date,memo='',expected_state=None,document_id=None,bill=None,details=None):
        self._require('trade');self._require_capability('payments','create')
        if not isinstance(components,dict) or set(components)-set(METHODS):raise ValueError('결제 항목을 확인하세요.')
        values={key:money(components.get(key,0)) for key in METHODS}
        total=sum(values.values())
        if not total:raise ValueError('결제금액을 입력해주시기 바랍니다.')
        memo=text(memo,'결제 메모',maximum=300)
        snapshot=self.payment_context(partner_id,payment_date,document_id)
        self._assert_payment_open(snapshot['date'])
        if not expected_state or expected_state!=snapshot['state']:raise ValueError('잔액이 바뀌었습니다. 다시 조회한 뒤 결제하세요.')
        if total>snapshot['cap']:raise ValueError('현재 또는 선택일의 결제 가능 잔액을 초과합니다.')
        if details is not None:
            from .purchase_payment_plan import normalize_plan
            details=normalize_plan(details)
            if details['partner_id']!=partner_id or details['datetime'][:10]!=snapshot['date'] or money(details['target'])!=total or any(money(details['components'][k])!=v for k,v in values.items()) or details['bill']!=bill or details['memo']!=memo:
                raise ValueError('상세 결제와 지급 입력값이 일치하지 않습니다.')
        if values['bill']:
            if not isinstance(bill,dict) or set(bill)!={'number','due_date','bank'}:raise ValueError('어음번호·만기일·은행을 확인하세요.')
            bill=dict(number=text(bill['number'],'어음번호',True,80),due_date=day(bill['due_date']),bank=text(bill['bank'],'은행',maximum=100))
            if bill['due_date']<snapshot['date']:raise ValueError('어음 만기일은 발행일보다 빠를 수 없습니다.')
            if self.db.execute('SELECT 1 FROM payable_bills WHERE number=?',(bill['number'],)).fetchone():raise ValueError('이미 등록된 어음번호입니다. 취소 이력도 같은 번호를 재사용하지 않습니다.')
        elif bill:raise ValueError('어음금액이 없는 발행 정보입니다.')
        ids=[]
        self._finance_batch_active=True
        try:
            for method,value in values.items():
                if not value:continue
                if document_id is None:
                    identifier=self._settle_supplier_in_tx(partner_id,public_amount(value),snapshot['date'],method,memo)
                else:identifier=self._insert_trade_payment(document_id,value,snapshot['date'],method,memo)
                ids.append(dict(id=identifier,type='settlement' if document_id is None else 'payment',method=method))
                if method=='bill':
                    key='settlement_id' if document_id is None else 'payment_id'
                    self.db.execute(f'INSERT INTO payable_bills({key},number,due_date,bank) VALUES(?,?,?,?)',(identifier,bill['number'],bill['due_date'],bill['bank']))
        finally:self._finance_batch_active=False
        self._audit('financial_payment_batch','partner',partner_id,dict(records=ids,document_id=document_id,amount=total,details=details))
        return dict(records=ids,amount=total,paid_total=sum(v for k,v in values.items() if k not in DISCOUNTS),discount_total=sum(values[k] for k in DISCOUNTS))

    def payment_summary(self,start,end,search='',only_purchases=False,partner_id=None):
        self._require('trade');self.require_menu('payments')
        rows=self.supplier_summary(start,end,search,only_purchases,partner_id)
        extra={}
        # Current catalogue attribution, explicitly labelled by the UI. This is
        # not a historical stock valuation or a supplier's consignment asset.
        stock={r[0]:r[1] for r in self.db.execute('SELECT supplier_id,SUM(stock_cost) FROM products WHERE tracked=1 GROUP BY supplier_id')}
        sql="""SELECT partner_id,method,SUM(amount) amount FROM (
          SELECT partner_id,date,method,amount FROM supplier_settlements WHERE voided=0
          UNION ALL SELECT p.partner_id,p.date,p.method,p.amount FROM payments p JOIN documents d ON d.id=p.document_id WHERE p.voided=0 AND p.supplier_settlement_id IS NULL AND d.status='posted'
        ) WHERE date BETWEEN ? AND ? GROUP BY partner_id,method"""
        for r in self.db.execute(sql,(day(start),day(end))):extra.setdefault(r['partner_id'],{})[r['method']]=r['amount']
        for r in rows:
            values=extra.get(r['id'],{})
            r.update(discount_payment=sum(values.get(k,0) for k in DISCOUNTS),bill_payment=values.get('bill',0),
                     paid_total=sum(values.get(k,0) for k in ('cash','transfer','card','bill')),stock_value=stock.get(r['id'],0))
        return rows

    def payable_bills(self,start,end,include_voided=False):
        self._require('trade');self.require_menu('payments')
        first,last=day(start),day(end)
        if first>last:raise ValueError('조회 시작일과 종료일을 확인하세요.')
        rows=self.db.execute("""SELECT b.*,COALESCE(s.partner_id,p.partner_id) partner_id,
           COALESCE(s.date,p.date) date,COALESCE(s.amount,p.amount) amount,COALESCE(s.voided,p.voided) voided,
           party.name partner_name FROM payable_bills b LEFT JOIN supplier_settlements s ON s.id=b.settlement_id
           LEFT JOIN payments p ON p.id=b.payment_id JOIN partners party ON party.id=COALESCE(s.partner_id,p.partner_id)
           WHERE b.due_date BETWEEN ? AND ? ORDER BY b.due_date,b.id""",(first,last))
        return [dict(r,status='취소' if r['voided'] else '지급완료' if r['paid_date'] else '만기경과' if r['due_date']<date.today().isoformat() else '미지급') for r in rows if include_voided or not r['voided']]

    def pay_bill(self,identifier,payment_date,method,memo=''):
        with self._tx():
            self._require('trade');self._require_capability('payments','create')
            row=self.db.execute("SELECT b.*,COALESCE(s.voided,p.voided) voided FROM payable_bills b LEFT JOIN supplier_settlements s ON s.id=b.settlement_id LEFT JOIN payments p ON p.id=b.payment_id WHERE b.id=?",(identifier,)).fetchone()
            when=day(payment_date)
            if not row or row['voided'] or row['paid_date']:raise ValueError('이미 지급했거나 취소한 어음입니다.')
            if when<row['due_date'] or when>date.today().isoformat():raise ValueError('만기일 이후이며 오늘을 넘지 않는 지급일을 선택하세요.')
            if method not in {'cash','transfer'}:raise ValueError('어음 지급은 현금·계좌이체로 기록하세요.')
            self._assert_open(when)
            self._assert_payment_open(when)
            if method=='cash':self._assert_cash_open(when,self.actor['id'])
            memo=text(memo,'어음 지급 메모',maximum=300)
            self.db.execute('UPDATE payable_bills SET paid_date=?,paid_method=?,paid_memo=?,paid_user_id=? WHERE id=?',(when,method,memo,self.actor['id'],identifier))
            self._audit('pay_bill','payable_bill',identifier,dict(date=when,method=method,memo=memo))
            return identifier

    def business_entries(self,start,end):
        self._require('reports');self.require_menu('payments');self.require_menu('reports')
        first,last=day(start),day(end)
        if first>last:raise ValueError('조회 시작일과 종료일을 확인하세요.')
        return [dict(r) for r in self.db.execute('SELECT e.*,u.name user_name FROM business_entries e JOIN users u ON u.id=e.user_id WHERE e.date BETWEEN ? AND ? ORDER BY e.date,e.id',(first,last))]

    def add_business_entry(self,date,kind,account,amount,method,memo=''):
        with self._tx():
            self._require('reports');self.require_menu('reports');self._require_capability('payments','create')
            when=day(date)
            from datetime import date as calendar_date
            if when>calendar_date.today().isoformat():raise ValueError('미래 업무 수입·비용은 확정할 수 없습니다.')
            if kind not in {'income','expense'} or method not in {'cash','transfer','card'}:raise ValueError('업무 수입·비용 구분과 수단을 확인하세요.')
            self._assert_open(when)
            self._assert_payment_open(when)
            if method=='cash':self._assert_cash_open(when,self.actor['id'])
            identifier=self.db.execute('INSERT INTO business_entries(date,kind,account,amount,method,memo,user_id,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (when,kind,text(account,'계정과목',True,80),money(amount,positive=True),method,text(memo,'메모',maximum=300),self.actor['id'],now())).lastrowid
            self._audit('business_entry','business_entry',identifier,dict(kind=kind))
            return identifier

    def void_business_entry(self,identifier,reason):
        with self._tx():
            self._require('reports');self.require_menu('reports');self._require_capability('payments','delete')
            row=self.db.execute('SELECT * FROM business_entries WHERE id=?',(identifier,)).fetchone()
            if not row or row['voided']:raise ValueError('유효한 업무기록만 취소할 수 있습니다.')
            self._assert_open(row['date'])
            self._assert_payment_open(row['date'])
            if row['method']=='cash':self._assert_cash_open(row['date'],row['user_id'])
            reason=text(reason,'취소 사유',True)
            self.db.execute('UPDATE business_entries SET voided=1 WHERE id=?',(identifier,))
            self._audit('void_business_entry','business_entry',identifier,dict(reason=reason))

    def finance_profit(self,start,end):
        self._require('reports');self.require_menu('payments');self.require_menu('reports')
        first,last=day(start),day(end)
        if first>last:raise ValueError('조회 시작일과 종료일을 확인하세요.')
        if int(last[:4])*12+int(last[5:7])-(int(first[:4])*12+int(first[5:7]))>120:raise ValueError('손익 조회는 10년 이내로 나누어 조회하세요.')
        year=int(first[:4]);prev_start=date(year-1,int(first[5:7]),min(int(first[8:]),monthrange(year-1,int(first[5:7]))[1])).isoformat() if year>1 else first
        year=int(last[:4]);prev_end=date(year-1,int(last[5:7]),min(int(last[8:]),monthrange(year-1,int(last[5:7]))[1])).isoformat() if year>1 else last
        # Three grouped scans for the entire comparison window, not a full
        # document scan once per month/supplier. The read boundary is one DB
        # snapshot, so the visible totals and monthly details cannot disagree.
        daily={}
        def bucket(when):return daily.setdefault(when,dict(sale_total=0,cost=0,other_income=0,expenses=0))
        for r in self.db.execute("SELECT d.date,SUM(CASE WHEN d.kind='sale' THEN l.total ELSE -l.total END) sale_total,SUM(CASE WHEN d.kind='sale' THEN l.cost ELSE -l.cost END) cost FROM document_lines l JOIN documents d ON d.id=l.document_id WHERE d.status='posted' AND d.kind IN ('sale','sale_return') AND d.date BETWEEN ? AND ? GROUP BY d.date",(prev_start,last)):
            bucket(r['date']).update(sale_total=r['sale_total'],cost=r['cost'])
        for r in self.db.execute("SELECT date,SUM(CASE WHEN kind='income' THEN amount ELSE 0 END) other_income,SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END) expenses FROM business_entries WHERE voided=0 AND date BETWEEN ? AND ? GROUP BY date",(prev_start,last)):
            bucket(r['date']).update(other_income=r['other_income'],expenses=r['expenses'])
        for r in self.db.execute("SELECT date,SUM(amount) amount FROM (SELECT date,amount,method FROM supplier_settlements WHERE voided=0 UNION ALL SELECT p.date,p.amount,p.method FROM payments p JOIN documents d ON d.id=p.document_id WHERE p.voided=0 AND p.supplier_settlement_id IS NULL AND d.status='posted') WHERE date BETWEEN ? AND ? AND method IN ('dc','rebate','coupon','other_discount') GROUP BY date",(prev_start,last)):
            bucket(r['date'])['other_income']+=r['amount']
        def totals(a,b):
            result={key:sum(row[key] for when,row in daily.items() if a<=when<=b) for key in ('sale_total','cost','other_income','expenses')}
            result['profit']=result['sale_total']-result['cost'];result['net_profit']=result['profit']+result['other_income']-result['expenses']
            return result
        current=totals(first,last);previous=totals(prev_start,prev_end)
        monthly=[];year,month=int(first[:4]),int(first[5:7])
        while f'{year:04}-{month:02}-01'<=last:
            a=max(first,f'{year:04}-{month:02}-01');b=min(last,f'{year:04}-{month:02}-{monthrange(year,month)[1]}')
            monthly.append(dict(period=f'{year:04}-{month:02}',**totals(a,b)))
            month+=1
            if month==13:month=1;year+=1
        return dict(current=current,previous=previous,monthly=monthly,
            basis='부가세 포함 확정전표의 저장된 판매원가 + 공급사 할인·업무 수입 − 등록된 업무비용 기준. 할인은 재고원가·부가세를 수정하지 않습니다. 미등록 비용·세금·감가상각은 제외하며 세무 손익계산서가 아닙니다.')

    def finance_member_ledger(self,member_id,start,end):
        self._require('trade');self.require_menu('payments');self.require_menu('members')
        self._member_row(member_id)
        first,last=day(start),day(end)
        if first>last:raise ValueError('조회 시작일과 종료일을 확인하세요.')
        entries=[]
        for row in self.db.execute("SELECT * FROM documents WHERE member_id=? AND status='posted' ORDER BY date,id",(member_id,)):
            entries.append(dict(date=row['date'],number=row['number'],kind=row['kind'],document_id=row['id'],charge=(row['total']-row['points_used'])*(-1 if row['source_id'] else 1),payment=0,memo=row['memo'],order=row['id']*2))
        for row in self.db.execute("SELECT p.*,d.number FROM payments p JOIN documents d ON d.id=p.document_id WHERE d.member_id=? AND d.status='posted' AND p.voided=0",(member_id,)):
            entries.append(dict(date=row['date'],number=row['number'],kind='payment',document_id=row['document_id'],charge=0,payment=row['amount'],memo=row['memo'],method=row['method'],order=row['document_id']*2+1))
        entries.sort(key=lambda r:(r['date'],r['order']))
        opening=sum(r['charge']-r['payment'] for r in entries if r['date']<first);balance=opening;result=[]
        for row in entries:
            if first<=row['date']<=last:
                balance+=row['charge']-row['payment'];result.append({**row,'balance':balance})
        return dict(opening=opening,closing=balance,entries=result)
