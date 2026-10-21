"""Local logistics work records, distinct from posted POS stock and invoices."""
from collections import defaultdict
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import json
from uuid import uuid4
from .common import day,decimal,money,now,text
from .currency import round_amount

WORKLOG_SCHEMA='''
CREATE TABLE IF NOT EXISTS work_log_details (
 work_log_id INTEGER PRIMARY KEY REFERENCES work_logs(id) ON DELETE CASCADE,
 content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_log_files (
 id TEXT PRIMARY KEY,work_log_id INTEGER NOT NULL REFERENCES work_logs(id) ON DELETE CASCADE,
 name TEXT NOT NULL,payload BLOB NOT NULL CHECK(length(payload) BETWEEN 1 AND 10485760),created_at TEXT NOT NULL
);
'''
ACTIVITIES=('하역','적치','이동','피킹','포장','출고','리버스','재고','사무','기타')
STATUSES={'planned':'예정','active':'진행 중','done':'완료','hold':'보류'}


def quantity(value,label):
    result=decimal(value)
    if result<0 or result>Decimal('100000000') or result!=result.quantize(Decimal('0.001')):raise ValueError(label+'는 0 이상 소수점 세 자리까지 입력하세요.')
    return str(result)


def validate_details(data):
    status=data.get('status','done')
    if status not in STATUSES:raise ValueError('처리 상태를 확인하세요.')
    result=dict(status=status,category=text(data.get('category','일반업무'),'업무 구분',True,100),
                customer=text(data.get('customer',''),'고객사',maximum=100),working_day=bool(data.get('working_day',True)),
                handover=text(data.get('handover',''),'인수인계',maximum=10000),issue=text(data.get('issue',''),'특이사항·안전',maximum=10000))
    for name in ('handling_revenue','storage_revenue','extra_revenue','rent_cost','management_cost','other_cost'):
        result[name]=money(data.get(name,0))
    result['capacity']=quantity(data.get('capacity',0),'최대 보관량');result['occupied']=quantity(data.get('occupied',0),'현재 보관량')
    optimal=decimal(data.get('optimal_percent',85))
    if not 0<=optimal<=100:raise ValueError('적정 보관율은 0~100%입니다.')
    result['optimal_percent']=str(optimal)
    workers=data.get('workers',[]);moves=data.get('movements',[])
    if not isinstance(workers,list) or len(workers)>100 or not isinstance(moves,list) or len(moves)>200:raise ValueError('인력은 100명, 작업은 200행까지 입력하세요.')
    result['workers']=[];result['movements']=[]
    for r in workers:
        kind=r.get('kind','regular')
        if kind not in {'regular','temporary','support'}:raise ValueError('인력 구분을 확인하세요.')
        regular=quantity(r.get('regular_hours',0),'정규 시간');overtime=quantity(r.get('overtime_hours',0),'잔업 시간')
        factor=decimal(r.get('overtime_factor','1.5'))
        if not 1<=factor<=5:raise ValueError('잔업 계산 배율은 1~5로 입력하세요.')
        result['workers'].append(dict(name=text(r.get('name'),'작업자',True,100),kind=kind,regular_hours=regular,overtime_hours=overtime,
                                      hourly_rate=money(r.get('hourly_rate',0)),overtime_factor=str(factor)))
    for r in moves:
        if r.get('activity') not in ACTIVITIES or r.get('unit') not in {'EA','BOX','PLT'}:raise ValueError('작업 구분과 단위(EA·BOX·PLT)를 확인하세요.')
        result['movements'].append(dict(activity=r['activity'],unit=r['unit'],qty=quantity(r.get('qty',0),'작업 수량'),hours=quantity(r.get('hours',0),'작업 소요 시간')))
    return result


def work_metrics(details):
    labor=0;hours=Decimal(0)
    for r in details.get('workers',[]):
        normal=decimal(r['regular_hours']);extra=decimal(r['overtime_hours']);hours+=normal+extra
        labor+=int((Decimal(r['hourly_rate'])*(normal+extra*decimal(r['overtime_factor']))).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    revenue=sum(details.get(k,0) for k in ('handling_revenue','storage_revenue','extra_revenue'))
    costs=labor+sum(details.get(k,0) for k in ('rent_cost','management_cost','other_cost'))
    capacity=decimal(details.get('capacity',0));occupied=decimal(details.get('occupied',0))
    productivity=[]
    for r in details.get('movements',[]):
        qty=decimal(r['qty']);h=decimal(r['hours'])
        productivity.append(dict(r,per_hour=(qty/h).quantize(Decimal('.01')) if h else None,minutes_per_touch=(h*60/qty).quantize(Decimal('.01')) if qty else None))
    return dict(revenue_total=revenue,labor_cost=labor,total_cost=costs,profit=revenue-costs,
                profit_rate=(Decimal(revenue-costs)*100/revenue).quantize(Decimal('.01')) if revenue else None,
                total_hours=hours,workers=len(details.get('workers',[])),
                occupancy=(occupied*100/capacity).quantize(Decimal('.01')) if capacity else None,
                remaining_capacity=capacity-occupied,optimal_capacity=(capacity*decimal(details.get('optimal_percent',85))/100-occupied).quantize(Decimal('.001')),
                productivity=productivity)


class WorkLogMixin:
    def work_log_detail(self,identifier):
        self.require_menu('worklog')
        if not self.db.execute('SELECT 1 FROM work_logs WHERE id=? AND user_id=?',(identifier,self.actor['id'])).fetchone():raise ValueError('업무일지를 찾을 수 없습니다.')
        row=self.db.execute('SELECT content FROM work_log_details WHERE work_log_id=?',(identifier,)).fetchone()
        return json.loads(row[0]) if row else validate_details({})

    def work_log_report(self,start,end):
        rows=self.work_logs(start,end);days=set();groups=defaultdict(lambda:dict(revenue_total=0,total_cost=0,profit=0,total_hours=Decimal(0),records=0))
        units=defaultdict(Decimal);status={k:0 for k in STATUSES};records=[]
        for r in rows:
            details=self.work_log_detail(r['id']);metrics=work_metrics(details);records.append(dict(r,details=details,metrics=metrics));status[details['status']]+=1
            if details['working_day']:days.add(r['date'])
            group=groups[r['date']];group['records']+=1
            for key in ('revenue_total','total_cost','profit','total_hours'):group[key]+=metrics[key]
            for movement in details['movements']:units[movement['unit']]+=decimal(movement['qty'])
        totals={key:sum(r[key] for r in groups.values()) for key in ('revenue_total','total_cost','profit','total_hours')}
        return dict(records=records,days=[dict(date=k,**v) for k,v in sorted(groups.items())],working_days=len(days),status=status,units=dict(units),totals=totals)

    def _work_file_owner(self,identifier,operation='read'):
        self.require_menu('worklog')
        if operation not in {'read','export'}:self._require_capability('worklog',operation)
        if not self.db.execute('SELECT 1 FROM work_logs WHERE id=? AND user_id=?',(identifier,self.actor['id'])).fetchone():raise ValueError('업무일지를 찾을 수 없습니다.')

    def work_log_files(self,identifier):
        self._work_file_owner(identifier)
        return [dict(r) for r in self.db.execute('SELECT id,name,length(payload) size,created_at FROM work_log_files WHERE work_log_id=? ORDER BY created_at,id',(identifier,))]

    def add_work_log_file(self,identifier,name,payload):
        from .personal_attachments import EXTENSIONS,ATTACHMENT_LIMIT
        with self._tx():
            self._work_file_owner(identifier,'edit');name=text(str(name).replace('\\','/').split('/')[-1],'파일 이름',True,200)
            if Path(name).suffix.lower() not in EXTENSIONS:raise ValueError('사진·PDF·문서만 첨부할 수 있습니다.')
            if not isinstance(payload,bytes) or not 0<len(payload)<=ATTACHMENT_LIMIT:raise ValueError('파일은 10MB 이하로 선택하세요.')
            if len(self.work_log_files(identifier))>=20:raise ValueError('업무일지당 첨부파일은 20개까지입니다.')
            used=self.db.execute('SELECT COALESCE(SUM(length(f.payload)),0) FROM work_log_files f JOIN work_logs w ON w.id=f.work_log_id WHERE w.user_id=?',(self.actor['id'],)).fetchone()[0]
            if used+len(payload)>200*1024*1024:raise ValueError('업무 첨부파일은 사용자당 200MB까지입니다.')
            value=uuid4().hex;self.db.execute('INSERT INTO work_log_files VALUES(?,?,?,?,?)',(value,identifier,name,payload,now()));self._audit('attach','work_log',identifier,{})
            return value

    def work_log_file_data(self,identifier,file_id):
        self._work_file_owner(identifier,'export');row=self.db.execute('SELECT payload FROM work_log_files WHERE id=? AND work_log_id=?',(file_id,identifier)).fetchone()
        if not row:raise ValueError('첨부파일을 찾을 수 없습니다.')
        return bytes(row[0])

    def delete_work_log_file(self,identifier,file_id):
        with self._tx():
            self._work_file_owner(identifier,'delete')
            if not self.db.execute('DELETE FROM work_log_files WHERE id=? AND work_log_id=?',(file_id,identifier)).rowcount:raise ValueError('첨부파일을 찾을 수 없습니다.')
            self._audit('detach','work_log',identifier,{})
