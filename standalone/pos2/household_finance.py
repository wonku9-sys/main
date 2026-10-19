"""Encrypted personal accounts, transfers, recurring costs and vehicle expenses.

Only cashbook entries represent spending. A vehicle record is metadata on that
same entry, never a second financial posting. Recurrence receipts survive entry
deletion so opening the book cannot silently recreate a deleted expense.
"""
import calendar
from datetime import date
from decimal import Decimal
import json
from uuid import uuid4

from cryptography.exceptions import InvalidTag

from .common import day, money, now, text, decimal
from .diary import _seal, _open
from .currency import money_input
from .household_categories import HouseholdCategoryMixin
from .vehicle_management import VehicleManagementMixin,CHECKS

FINANCE_TABLES = {'accounts', 'transfers', 'fixed_costs', 'vehicles', 'vehicle_logs', 'budgets', 'category_rules','vehicle_obligations'}
FINANCE_SCHEMA = ''.join(f'''
CREATE TABLE IF NOT EXISTS household_{name} (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES household_vaults(user_id) ON DELETE RESTRICT,
 ciphertext BLOB NOT NULL CHECK(length(ciphertext)>=28), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
''' for name in sorted(FINANCE_TABLES)) + '''
CREATE TABLE IF NOT EXISTS household_fixed_runs (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES household_vaults(user_id) ON DELETE RESTRICT,
 entry_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS household_fixed_alerts (
 id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES household_vaults(user_id) ON DELETE RESTRICT,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS household_vehicle_alerts (
 id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES household_vaults(user_id) ON DELETE RESTRICT,created_at TEXT NOT NULL
);
'''

VEHICLE_TYPES = {'fuel': '주유비', 'insurance': '보험료', 'repair': '정비·소모품',
                 'tax': '자동차세', 'parking': '주차비', 'toll': '통행료', 'other': '기타 유지비'}


class HouseholdFinanceMixin(HouseholdCategoryMixin,VehicleManagementMixin):
    def save_household_budget(self,key,month,total):
        import re
        if not re.fullmatch(r'\d{4}-\d{2}',str(month)):raise ValueError('예산 월은 YYYY-MM 형식입니다.')
        day(str(month)+'-01')
        with self._tx():
            previous=next((r for r in self._finance_records(key,'budgets') if r['month']==month),None)
            return self._finance_put(key,'budgets',dict(month=month,amount=money(total)),previous['id'] if previous else None)

    def household_budget(self,key,as_of=None):
        value=day(as_of or date.today())
        if value>date.today().isoformat():raise ValueError('예산 현황은 오늘까지의 기록을 기준으로 확인하세요.')
        month=value[:7];budget=next((r['amount'] for r in self._finance_records(key,'budgets') if r['month']==month),0)
        used=sum(r['amount'] for r in self._household_records(key) if r['kind']=='expense' and month+'-01'<=r['date']<=value)
        return {'month':month,'date':value,'amount':budget,'expense_total':used,'balance':budget-used,
                'percent':(Decimal(used)*100/Decimal(budget)).quantize(Decimal('0.01')) if budget else Decimal(0)}

    def household_spending_comparison(self,key,as_of=None):
        today=date.fromisoformat(day(as_of or date.today()))
        if today>date.today():raise ValueError('지출 비교는 오늘까지의 기록을 기준으로 확인하세요.')
        year,month=(today.year,today.month-1) if today.month>1 else (today.year-1,12)
        last=date(year,month,calendar.monthrange(year,month)[1]);first=last.replace(day=1)
        comparable=last.replace(day=min(today.day,last.day))
        expenses=[r for r in self._household_records(key) if r['kind']=='expense']
        current=[r for r in expenses if today.replace(day=1).isoformat()<=r['date']<=today.isoformat()]
        used=sum(r['amount'] for r in current)
        previous=sum(r['amount'] for r in expenses if first.isoformat()<=r['date']<=last.isoformat())
        matched=sum(r['amount'] for r in expenses if first.isoformat()<=r['date']<=comparable.isoformat())
        groups={}
        for r in current:groups[r['category']]=groups.get(r['category'],0)+r['amount']
        top=[dict(name=name,amount=value,percent=(Decimal(value)*100/Decimal(used)).quantize(Decimal('0.01')) if used else Decimal(0)) for name,value in sorted(groups.items(),key=lambda item:(-item[1],item[0]))]
        return dict(month=today.strftime('%Y-%m'),date=today.isoformat(),previous_month=first.strftime('%Y-%m'),comparable_end=comparable.isoformat(),
            expense_total=used,previous_total=previous,comparable_total=matched,difference=used-matched,
            percent_change=(Decimal(used-matched)*100/Decimal(matched)).quantize(Decimal('0.01')) if matched else None,top_categories=top)

    def due_household_fixed_alerts(self,key,as_of=None):
        import hmac
        today=day(as_of or date.today())
        if today>date.today().isoformat():raise ValueError('미래 고정 지출 알림은 미리 처리하지 않습니다.')
        with self._tx():
            self._require_household_key(key);rows=[];uid=self.actor['id']
            for rule in self.household_fixed_costs(key):
                if not rule['active'] or rule['start_date']>today:continue
                end=date.fromisoformat(min(today,rule['end_date'] or today));year,month=end.year,end.month
                due=date(year,month,min(rule['monthly_day'],calendar.monthrange(year,month)[1]))
                if due>end:
                    year,month=(year,month-1) if month>1 else (year-1,12)
                    due=date(year,month,min(rule['monthly_day'],calendar.monthrange(year,month)[1]))
                if due.isoformat()<rule['start_date']:continue
                receipt=hmac.digest(bytes(key),f'fixed-alert/{uid}/{rule["id"]}/{due:%Y-%m}'.encode(),'sha256').hex()
                if self.db.execute('SELECT 1 FROM household_fixed_alerts WHERE id=? AND user_id=?',(receipt,uid)).fetchone():continue
                rows.append(dict(id=rule['id'],date=due.isoformat(),title=rule['title'],amount=rule['amount']))
                self.db.execute('INSERT INTO household_fixed_alerts VALUES(?,?,?)',(receipt,uid,now()))
                if len(rows)>=10:break
            return rows

    def _finance_records(self, key, kind):
        self._require_household_key(key)
        if kind not in FINANCE_TABLES: raise ValueError('개인 자료 종류를 확인하세요.')
        records = []
        try:
            for row in self.db.execute(f'SELECT * FROM household_{kind} WHERE user_id=?', (self.actor['id'],)):
                item = json.loads(_open(key, row['ciphertext'], self._household_aad(self.actor['id'], kind+'/'+row['id'])))
                records.append(dict(item, id=row['id']))
        except (InvalidTag, ValueError, TypeError, KeyError):
            raise ValueError('개인 금융 자료를 열 수 없습니다. 파일 손상 여부를 확인하세요.') from None
        return sorted(records, key=lambda r: (r.get('created_at', ''), r['id']))

    def _finance_put(self, key, kind, content, identifier=None):
        if kind not in FINANCE_TABLES: raise ValueError('개인 자료 종류를 확인하세요.')
        old = next((r for r in self._finance_records(key, kind) if r['id'] == identifier), None)
        if identifier and not old: raise ValueError('선택한 개인 자료를 찾을 수 없습니다.')
        self._require_capability('household', 'edit' if old else 'create')
        identifier = identifier or uuid4().hex
        stamp = now(); content = dict(content, created_at=old['created_at'] if old else stamp)
        cipher = _seal(key, json.dumps(content, ensure_ascii=False).encode(), self._household_aad(self.actor['id'], kind+'/'+identifier))
        self.db.execute(f'INSERT INTO household_{kind} VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext,updated_at=excluded.updated_at',
                        (identifier, self.actor['id'], cipher, content['created_at'], stamp))
        self._audit('save', 'household_'+kind, None, {})
        return identifier

    def _finance_account(self, key, identifier, value, existing=False):
        identifier = str(identifier or '')
        if not identifier: return ''  # Backward-compatible unassigned cash.
        account = next((r for r in self._finance_records(key, 'accounts') if r['id'] == identifier), None)
        if not account: raise ValueError('통장을 찾을 수 없습니다.')
        if not account['active'] and not existing: raise ValueError('보관된 통장에는 새 거래를 입력할 수 없습니다.')
        if value < account['opening_date']: raise ValueError('거래일은 통장의 시작일보다 빠를 수 없습니다.')
        return identifier

    def household_accounts(self, key): return self._finance_records(key, 'accounts')

    def save_household_account(self, key, data, identifier=None):
        with self._tx():
            content = {'name': text(data.get('name'), '통장 이름', True, 100),
                       'bank': text(data.get('bank', ''), '은행·별칭', maximum=100),
                       'opening_date': day(data.get('opening_date')),
                       'opening_balance': money_input(data.get('opening_balance', 0), signed=True),
                       'active': bool(data.get('active', True)), 'memo': text(data.get('memo', ''), '메모', maximum=2000)}
            if identifier:
                old = next((r for r in self.household_accounts(key) if r['id'] == identifier), None)
                references = [r['date'] for r in self._household_records(key) if r.get('account_id', '') == identifier]
                references += [r['date'] for r in self._finance_records(key, 'transfers') if identifier in {r['from_account'], r['to_account']}]
                rules = [r for r in self._finance_records(key, 'fixed_costs') if r['account_id'] == identifier and r['active']]
                if references and (not old or (old['opening_date'], old['opening_balance']) != (content['opening_date'], content['opening_balance'])):
                    raise ValueError('거래가 있는 통장의 시작 잔액·시작일은 변경할 수 없습니다. 차액은 수입·지출로 기록하세요.')
                if rules and not content['active']: raise ValueError('통장을 보관하려면 연결된 월 고정비를 먼저 중지하세요.')
            return self._finance_put(key, 'accounts', content, identifier)

    def household_transfers(self, key): return self._finance_records(key, 'transfers')

    def save_household_transfer(self, key, data, identifier=None):
        with self._tx():
            value = day(data.get('date'))
            source = self._finance_account(key, data.get('from_account'), value, existing=bool(identifier))
            target = self._finance_account(key, data.get('to_account'), value, existing=bool(identifier))
            if source == target: raise ValueError('서로 다른 출금·입금 통장을 선택하세요.')
            return self._finance_put(key, 'transfers', {'date': value, 'from_account': source, 'to_account': target,
                'amount': money(data.get('amount'), positive=True), 'memo': text(data.get('memo', ''), '이체 메모', maximum=2000)}, identifier)

    def delete_household_transfer(self, key, identifier):
        with self._tx():
            self._require_household_key(key); self._require_capability('household', 'delete')
            if not self.db.execute('DELETE FROM household_transfers WHERE id=? AND user_id=?', (identifier, self.actor['id'])).rowcount:
                raise ValueError('이체 내역을 찾을 수 없습니다.')
            self._audit('delete', 'household_transfer', None, {})

    def household_vehicles(self, key): return self._finance_records(key, 'vehicles')

    def save_household_vehicle(self, key, data, identifier=None):
        with self._tx():
            content = {'name': text(data.get('name'), '차량 이름', True, 100),
                       'plate': text(data.get('plate', ''), '차량번호', maximum=30),
                       'model': text(data.get('model', ''), '차종·연식', maximum=100),
                       'memo': text(data.get('memo', ''), '차량 메모', maximum=2000), 'active': bool(data.get('active', True))}
            content['next_service_date']=day(data['next_service_date']) if data.get('next_service_date') else ''
            content['next_service_km']=self._vehicle_number(data.get('next_service_km'),'다음 정비 주행거리')
            if identifier and not content['active'] and any(r['active'] and r.get('vehicle_id') == identifier for r in self._finance_records(key, 'fixed_costs')):
                raise ValueError('차량을 보관하려면 연결된 월 고정비를 먼저 중지하세요.')
            return self._finance_put(key, 'vehicles', content, identifier)

    def _finance_entry_metadata(self, key, data, old=None):
        value = day(data.get('date'))
        account = self._finance_account(key, data.get('account_id'), value,
                    existing=bool(old and old.get('account_id', '') == data.get('account_id', '')))
        vehicle = str(data.get('vehicle_id') or '')
        result = {'account_id': account, 'vehicle_id': vehicle, 'vehicle_type': '', 'liters': '', 'odometer': ''}
        for name,label,limit in [('vehicle_vendor','주유소·정비업체·보험사',100),('vehicle_detail','정비·교환 부품·보험 내용',2000),('fuel_kind','연료 종류',30)]:
            result[name]=text(data.get(name,''),label,maximum=limit) if vehicle else ''
        result['full_tank']=bool(data.get('full_tank',False)) if vehicle else False
        for name in ('insurance_start','insurance_end'):result[name]=day(data[name]) if vehicle and data.get(name) else ''
        if result['insurance_start'] and result['insurance_end'] and result['insurance_start']>result['insurance_end']:raise ValueError('보험 보장 기간을 확인하세요.')
        if vehicle:
            car = next((r for r in self.household_vehicles(key) if r['id'] == vehicle), None)
            if not car or not car['active'] and (not old or old.get('vehicle_id') != vehicle): raise ValueError('사용 가능한 차량을 선택하세요.')
            if data.get('kind') != 'expense': raise ValueError('차량 유지비는 지출로 기록하세요.')
            category = data.get('vehicle_type', 'other')
            if category not in VEHICLE_TYPES: raise ValueError('차량 비용 종류를 선택하세요.')
            result['vehicle_type'] = category
            for name, label in (('liters', '주유량(L)'), ('odometer', '누적 주행거리(km)')):
                if data.get(name) not in (None, ''):
                    number = decimal(data[name])
                    if number < 0 or number > Decimal('100000000') or name == 'liters' and number == 0:
                        raise ValueError(label+' 값을 확인하세요.')
                    if number != number.quantize(Decimal('0.001')): raise ValueError(label+'는 소수점 세 자리까지 입력하세요.')
                    result[name] = str(number)
            if category != 'fuel' and result['liters']: raise ValueError('주유량은 주유비를 선택했을 때만 입력하세요.')
        elif data.get('vehicle_type') or data.get('liters') or data.get('odometer'):
            raise ValueError('차량을 먼저 선택하세요.')
        return result

    @staticmethod
    def _vehicle_number(value,label):
        if value in (None,''):return ''
        result=decimal(value)
        if result<0 or result>Decimal('100000000') or result!=result.quantize(Decimal('0.001')):raise ValueError(label+'는 0 이상, 소수점 세 자리까지 입력하세요.')
        return str(result)

    def household_vehicle_logs(self,key,identifier,start,end):
        start,end=day(start),day(end)
        if start>end:raise ValueError('조회 기간을 확인하세요.')
        return sorted([r for r in self._finance_records(key,'vehicle_logs') if r['vehicle_id']==identifier and start<=r['date']<=end],key=lambda r:(r['date'],r['created_at']))

    def save_household_vehicle_log(self,key,data,identifier=None):
        with self._tx():
            if not any(r['id']==data.get('vehicle_id') for r in self.household_vehicles(key)):raise ValueError('차량을 선택하세요.')
            kind=data.get('log_kind','note')
            if kind not in {'drive','inspection','accident','service','note'}:raise ValueError('차량 기록 종류를 확인하세요.')
            if identifier and any(r.get('completed_log_id')==identifier for r in self.household_vehicle_obligations(key)):raise ValueError('납부·정비 예정에서 완료를 취소한 뒤 수정하세요.')
            checks=data.get('checks',{})
            if not isinstance(checks,dict) or set(checks)-CHECKS.keys() or any(value not in {'unchecked','ok','needs'} for value in checks.values()):raise ValueError('차량 점검 항목을 확인하세요.')
            return self._finance_put(key,'vehicle_logs',dict(vehicle_id=data['vehicle_id'],date=day(data.get('date')),log_kind=kind,
                title=text(data.get('title'),'기록 내용',True,200),place=text(data.get('place',''),'장소·업체',maximum=100),
                odometer=self._vehicle_number(data.get('odometer'),'누적 주행거리'),distance=self._vehicle_number(data.get('distance'),'운행 거리'),
                memo=text(data.get('memo',''),'상세 메모',maximum=10000),checks=checks,
                departure=text(data.get('departure',''),'출발지',maximum=200),destination=text(data.get('destination',''),'도착지',maximum=200),route=text(data.get('route',''),'이동 경로',maximum=1000)),identifier)

    def delete_household_vehicle_log(self,key,identifier):
        with self._tx():
            self._require_household_key(key);self._require_capability('household','delete')
            if any(r.get('completed_log_id')==identifier for r in self.household_vehicle_obligations(key)):raise ValueError('납부·정비 예정에서 완료를 취소한 뒤 삭제하세요.')
            if not self.db.execute('DELETE FROM household_vehicle_logs WHERE id=? AND user_id=?',(identifier,self.actor['id'])).rowcount:raise ValueError('차량 기록을 찾을 수 없습니다.')
            self.db.execute("DELETE FROM personal_attachments WHERE user_id=? AND kind='household' AND record_type='vehicle_log' AND record_id=?",(self.actor['id'],identifier))
            self._audit('delete','household_vehicle_log',None,{})

    def _household_put_entry(self, key, content, identifier=None, old=None):
        stamp = now(); identifier = identifier or uuid4().hex
        content = dict(content, created_at=old['created_at'] if old else stamp)
        cipher = _seal(key, json.dumps(content, ensure_ascii=False).encode(), self._household_aad(self.actor['id'], identifier))
        self.db.execute('INSERT INTO household_entries VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext,updated_at=excluded.updated_at',
                        (identifier, self.actor['id'], cipher, content['created_at'], stamp))
        self._audit('save', 'household_entry', None, {})
        return identifier

    def household_fixed_costs(self, key): return self._finance_records(key, 'fixed_costs')

    def save_household_fixed_cost(self, key, data, identifier=None):
        with self._tx():
            start = day(data.get('start_date')); end = day(data['end_date']) if data.get('end_date') else ''
            if end and end < start: raise ValueError('고정비 종료일을 확인하세요.')
            try: monthly_day = int(data.get('monthly_day', 1))
            except (ValueError, TypeError): raise ValueError('매월 기록일은 1~31일입니다.') from None
            if str(monthly_day) != str(data.get('monthly_day', 1)) or not 1 <= monthly_day <= 31: raise ValueError('매월 기록일은 1~31일입니다.')
            metadata = self._finance_entry_metadata(key, dict(data, date=start, kind='expense'))
            return self._finance_put(key, 'fixed_costs', dict(metadata, title=text(data.get('title'), '고정비 내용', True, 200),
                category=text(data.get('category', '고정비'), '분류', True, 100), amount=money(data.get('amount'), positive=True),
                monthly_day=monthly_day, start_date=start, end_date=end, active=bool(data.get('active', True)),
                memo=text(data.get('memo', ''), '고정비 메모', maximum=2000)), identifier)

    def apply_household_fixed_costs(self, key, as_of=None):
        """Record due months only while unlocked. Never execute a bank payment."""
        import hmac
        today = day(as_of or date.today())
        if today > date.today().isoformat(): raise ValueError('미래 고정비는 미리 지출로 기록하지 않습니다.')
        with self._tx():
            self._require_household_key(key); self._require_capability('household', 'create')
            count = 0; uid = self.actor['id']
            for rule in self.household_fixed_costs(key):
                if not rule['active'] or rule['start_date'] > today: continue
                start = date.fromisoformat(rule['start_date']); end = date.fromisoformat(min(today, rule['end_date'] or today))
                span = (end.year-start.year)*12+end.month-start.month
                if span > 119: raise ValueError('고정비 자동 기록은 최대 10년입니다. 시작일을 최근 날짜로 조정하세요.')
                for offset in range(span+1):
                    year, month0 = divmod(start.year*12+start.month-1+offset, 12); month = month0+1
                    due = date(year, month, min(rule['monthly_day'], calendar.monthrange(year, month)[1])).isoformat()
                    if not rule['start_date'] <= due <= end.isoformat(): continue
                    receipt = hmac.digest(bytes(key), f'fixed/{uid}/{rule["id"]}/{year:04}-{month:02}'.encode(), 'sha256').hex()
                    if self.db.execute('SELECT 1 FROM household_fixed_runs WHERE id=? AND user_id=?', (receipt, uid)).fetchone(): continue
                    entry = {k: rule[k] for k in ('title', 'category', 'amount', 'memo', 'account_id', 'vehicle_id', 'vehicle_type', 'liters', 'odometer')}
                    self._finance_entry_metadata(key, dict(entry, date=due, kind='expense'))
                    entry.update(date=due, kind='expense', fixed_rule_id=rule['id'])
                    entry_id = self._household_put_entry(key, entry)
                    self.db.execute('INSERT INTO household_fixed_runs VALUES(?,?,?,?)', (receipt, uid, entry_id, now())); count += 1
            return count

    def _household_ledger(self, key):
        accounts = self.household_accounts(key); names = {r['id']: r['name'] for r in accounts}; names[''] = '미지정·현금'
        rows = [dict(r, account_id=r.get('account_id', ''), account_name=names.get(r.get('account_id', ''), '보관 통장')) for r in self._household_records(key)]
        for r in accounts:
            rows.append(dict(id='opening/'+r['id'], date=r['opening_date'], kind='opening', amount=r['opening_balance'],
                account_id=r['id'], account_name=r['name'], title='시작 잔액', category='시작 잔액', memo='', created_at=''))
        for r in self.household_transfers(key):
            for account, other, kind in ((r['from_account'], r['to_account'], 'transfer_out'), (r['to_account'], r['from_account'], 'transfer_in')):
                rows.append(dict(r, id=r['id']+'/'+kind, transfer_id=r['id'], kind=kind, account_id=account, account_name=names.get(account, '보관 통장'),
                    title=('→ ' if kind == 'transfer_out' else '← ')+names.get(other, '보관 통장'), category='통장 간 이체'))
        return sorted(rows, key=lambda r:(r['date'], r['created_at'], r['id']))

    def household_dashboard(self, key, start, end):
        start, end = day(start), day(end)
        if start > end: raise ValueError('조회 기간을 확인하세요.')
        ledger = self._household_ledger(key); accounts = self.household_accounts(key)
        account_rows = [dict(id='', name='미지정·현금', bank='', active=True)] + accounts
        delta = lambda r: r['amount']*(-1 if r['kind'] in {'expense', 'transfer_out'} else 1)
        for account in account_rows:
            own = [r for r in ledger if r['account_id'] == account['id'] and r['date'] <= end]
            period = [r for r in own if r['date'] >= start]
            account.update(balance=sum(delta(r) for r in own), income_total=sum(r['amount'] for r in period if r['kind']=='income'),
                           expense_total=sum(r['amount'] for r in period if r['kind']=='expense'))
        expenses = [r for r in ledger if start <= r['date'] <= end and r['kind']=='expense']
        groups = {}
        for r in expenses: groups[r['category']] = groups.get(r['category'], 0)+r['amount']
        cars = self.household_vehicles(key)
        for car in cars:
            own = [r for r in expenses if r.get('vehicle_id') == car['id']]
            car['expense_total'] = sum(r['amount'] for r in own)
        return {'accounts': account_rows, 'balance': sum(r['balance'] for r in account_rows),
            'income_total': sum(r['income_total'] for r in account_rows), 'expense_total': sum(r['expense_total'] for r in account_rows),
            'categories': [{'name': k, 'amount': v} for k,v in sorted(groups.items(), key=lambda p:-p[1])], 'vehicles': cars}

    def household_vehicle_history(self, key, identifier, start, end):
        if not any(r['id'] == identifier for r in self.household_vehicles(key)): raise ValueError('차량을 선택하세요.')
        start, end = day(start), day(end)
        if start > end: raise ValueError('조회 기간을 확인하세요.')
        return [r for r in self._household_records(key) if r.get('vehicle_id') == identifier and start <= r['date'] <= end]
