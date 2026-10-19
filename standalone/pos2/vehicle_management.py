"""Full-to-full fuel estimates and exactly-once private vehicle payments."""
from datetime import date
from decimal import Decimal
from collections import Counter
import hmac
from .common import day,money,text,now,decimal

CHECKS={'tires':'타이어','oil':'엔진오일','coolant':'냉각수','brakes':'브레이크','lights':'등화 장치','wipers':'와이퍼','battery':'배터리'}


class VehicleManagementMixin:
    def household_vehicle_report(self,key,identifier,start,end):
        start,end=day(start),day(end)
        if start>end:raise ValueError('조회 기간을 확인하세요.')
        history=self.household_vehicle_history(key,identifier,'1900-01-01',end)
        period=[r for r in history if r['date']>=start];months={};groups={}
        for row in period:
            month=row['date'][:7];months[month]=months.get(month,0)+row['amount'];name=row['vehicle_type'];groups[name]=groups.get(name,0)+row['amount']
        fuels=[r for r in history if r['vehicle_type']=='fuel'];counts=Counter(r['date'] for r in fuels);ambiguous={r['date'] for r in fuels if not r.get('odometer') and counts[r['date']]>1}
        fuels.sort(key=lambda r:(r['date'],decimal(r.get('odometer') or 0),r['created_at'],r['id']))
        anchor=None;liters=Decimal(0);segments=[];uncertain=False
        for row in fuels:
            if row['date'] in ambiguous or not row.get('liters'):
                anchor=None;liters=Decimal(0);uncertain=True;continue
            amount=decimal(row['liters']);odo=decimal(row['odometer']) if row.get('odometer') else None
            if anchor:
                if odo is not None and odo<=decimal(anchor['odometer']):anchor=None;liters=Decimal(0);uncertain=True
                else:liters+=amount
            if row.get('full_tank'):
                if anchor and odo is not None and liters>0:
                    distance=odo-decimal(anchor['odometer'])
                    if row['date']>=start:segments.append(dict(start=anchor['date'],end=row['date'],distance=distance,liters=liters,km_per_liter=(distance/liters).quantize(Decimal('0.01'))))
                anchor=row if odo is not None else None;liters=Decimal(0)
        distance=sum((r['distance'] for r in segments),Decimal(0));consumed=sum((r['liters'] for r in segments),Decimal(0))
        return dict(expense_total=sum(r['amount'] for r in period),months=[dict(month=k,expense_total=v) for k,v in sorted(months.items())],
            categories=[dict(name=k,amount=v) for k,v in sorted(groups.items(),key=lambda item:-item[1])],segments=segments,
            distance=distance,liters=consumed,km_per_liter=(distance/consumed).quantize(Decimal('0.01')) if consumed else None,uncertain=uncertain)

    def household_vehicle_obligations(self,key,identifier=''):
        return [r for r in self._finance_records(key,'vehicle_obligations') if not identifier or r['vehicle_id']==identifier]

    def save_household_vehicle_obligation(self,key,data,identifier=None):
        with self._tx():
            if not any(r['id']==data.get('vehicle_id') for r in self.household_vehicles(key)):raise ValueError('차량을 선택하세요.')
            old=next((r for r in self.household_vehicle_obligations(key) if r['id']==identifier),None)
            if old and old['completed']:raise ValueError('이미 처리한 항목입니다. 납부·완료를 취소한 뒤 수정하세요.')
            kind=data.get('obligation_kind','maintenance')
            if kind not in {'insurance','tax','maintenance','inspection'}:raise ValueError('납부·정비 종류를 확인하세요.')
            value=day(data['due_date']) if data.get('due_date') else ''
            due_km=self._vehicle_number(data.get('due_km'),'예정 주행거리')
            if not value and not due_km:raise ValueError('예정일 또는 예정 주행거리를 입력하세요.')
            return self._finance_put(key,'vehicle_obligations',dict(vehicle_id=data['vehicle_id'],title=text(data.get('title'),'납부·정비 내용',True,200),
                obligation_kind=kind,due_date=value,due_km=due_km,amount=money(data.get('amount',0)),vendor=text(data.get('vendor',''),'업체·보험사',maximum=100),
                memo=text(data.get('memo',''),'상세 메모',maximum=5000),active=bool(data.get('active',True)),completed=False,paid_entry_id='',completed_log_id=''),identifier)

    def complete_household_vehicle_obligation(self,key,identifier,value,account_id=''):
        with self._tx():
            self._require_household_key(key);self._require_capability('household','edit')
            record=next((r for r in self.household_vehicle_obligations(key) if r['id']==identifier),None)
            if not record:raise ValueError('납부·정비 항목을 찾을 수 없습니다.')
            if record['completed']:return record.get('paid_entry_id') or record.get('completed_log_id')
            if not record['active']:raise ValueError('중지한 예정 항목입니다.')
            self._require_capability('household','create');value=day(value)
            if value>date.today().isoformat():raise ValueError('미래 날짜는 아직 납부·완료로 기록할 수 없습니다.')
            if record['amount']:
                entry=dict(date=value,kind='expense',title=record['title'],category='차량',amount=record['amount'],memo=record['memo'],account_id=account_id,
                    vehicle_id=record['vehicle_id'],vehicle_type=record['obligation_kind'] if record['obligation_kind'] in {'insurance','tax'} else 'repair',vehicle_vendor=record['vendor'])
                entry.update(self._finance_entry_metadata(key,entry));entry['vehicle_obligation_id']=identifier
                linked=self._household_put_entry(key,entry);record['paid_entry_id']=linked
            else:
                linked=self._finance_put(key,'vehicle_logs',dict(vehicle_id=record['vehicle_id'],date=value,log_kind='inspection',title=record['title'],place=record['vendor'],
                    odometer='',distance='',memo=record['memo'],vehicle_obligation_id=identifier))
                record['completed_log_id']=linked
            record['completed']=True;self._finance_put(key,'vehicle_obligations',{k:v for k,v in record.items() if k!='id'},identifier)
            return linked

    def void_household_vehicle_obligation(self,key,identifier):
        with self._tx():
            self._require_household_key(key);self._require_capability('household','delete');self._require_capability('household','edit')
            record=next((r for r in self.household_vehicle_obligations(key) if r['id']==identifier),None)
            if not record or not record['completed']:raise ValueError('완료 처리한 항목을 선택하세요.')
            for field,table,record_type in [('paid_entry_id','household_entries','entry'),('completed_log_id','household_vehicle_logs','vehicle_log')]:
                if record.get(field):
                    self.db.execute(f'DELETE FROM {table} WHERE id=? AND user_id=?',(record[field],self.actor['id']))
                    self.db.execute("DELETE FROM personal_attachments WHERE user_id=? AND kind='household' AND record_type=? AND record_id=?",(self.actor['id'],record_type,record[field]))
            record.update(completed=False,paid_entry_id='',completed_log_id='');self._finance_put(key,'vehicle_obligations',{k:v for k,v in record.items() if k!='id'},identifier)

    def due_household_vehicle_alerts(self,key):
        with self._tx():
            self._require_household_key(key);today=date.today().isoformat();rows=[];uid=self.actor['id']
            for car in self.household_vehicles(key):
                if not car['active']:continue
                entries=self.household_vehicle_history(key,car['id'],'1900-01-01',today)+self.household_vehicle_logs(key,car['id'],'1900-01-01',today)
                odometer=max((decimal(r['odometer']) for r in entries if r.get('odometer')),default=Decimal(0))
                tasks=[r for r in self.household_vehicle_obligations(key,car['id']) if r['active'] and not r['completed']]
                if car.get('next_service_date') or car.get('next_service_km'):tasks.append(dict(id='master/'+car['id'],title='다음 정비',due_date=car.get('next_service_date',''),due_km=car.get('next_service_km','')))
                for task in tasks:
                    if not (task['due_date'] and task['due_date']<=today or task['due_km'] and odometer>=decimal(task['due_km'])):continue
                    receipt=hmac.digest(bytes(key),f'vehicle-alert/{uid}/{task["id"]}/{task["due_date"]}/{task["due_km"]}'.encode(),'sha256').hex()
                    if self.db.execute('SELECT 1 FROM household_vehicle_alerts WHERE id=?',(receipt,)).fetchone():continue
                    rows.append(dict(vehicle=car['name'],title=task['title'],due_date=task['due_date'],due_km=task['due_km']))
                    self.db.execute('INSERT INTO household_vehicle_alerts VALUES(?,?,?)',(receipt,uid,now()))
                    if len(rows)>=10:return rows
            return rows
