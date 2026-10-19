"""Owner-only encrypted health records; never medical advice or shop postings."""
import json
from uuid import uuid4
from datetime import datetime
from cryptography.exceptions import InvalidTag
from .diary import _seal,_open
from .common import day,text,money,now,decimal

HEALTH_TYPES={'growth':'아이 성장 기록','weight':'체중·다이어트','meal':'식사 기록','exercise':'운동 기록','health':'건강 메모','treatment':'병원 진료·치료','appointment':'병원 예약','pharmacy':'약국 구매'}

HEALTH_SCHEMA="""
CREATE TABLE IF NOT EXISTS personal_health_entries (
 id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('diary','household')),ciphertext BLOB NOT NULL CHECK(length(ciphertext)>=28),
 alarm_event_id INTEGER REFERENCES desk_events(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
"""


class HealthMixin:
    def _health_key(self,kind,key):
        if kind=='diary':self._diary_require_key(key)
        elif kind=='household':self._require_household_key(key)
        else:raise ValueError('개인 기록 종류를 확인하세요.')

    def _health_aad(self,kind,identifier):return f'SeoyoungPOS/private-health/v1/{self.actor["id"]}/{kind}/{identifier}'.encode()

    def health_entries(self,kind,key,start,end,category=''):
        self._health_key(kind,key);start,end=day(start),day(end)
        if start>end:raise ValueError('조회 기간을 확인하세요.')
        records=[]
        try:
            for row in self.db.execute('SELECT * FROM personal_health_entries WHERE user_id=? AND kind=?',(self.actor['id'],kind)):
                item=json.loads(_open(key,row['ciphertext'],self._health_aad(kind,row['id'])))
                if start<=item['date']<=end and (not category or item['category']==category):records.append(dict(item,id=row['id'],alarm=bool(row['alarm_event_id'])))
        except (InvalidTag,ValueError,TypeError,KeyError):raise ValueError('건강 기록을 열 수 없습니다. 암호나 파일 손상 여부를 확인하세요.') from None
        return sorted(records,key=lambda r:(r['date'],r['time'],r['id']))

    def save_health_entry(self,kind,key,data,identifier=None):
        with self._tx():
            self._health_key(kind,key)
            if kind=='household':self._require_capability(kind,'edit' if identifier else 'create')
            old=self.db.execute('SELECT * FROM personal_health_entries WHERE id=? AND user_id=? AND kind=?',(identifier,self.actor['id'],kind)).fetchone() if identifier else None
            if identifier and not old:raise ValueError('건강 기록을 찾을 수 없습니다.')
            category=data.get('category','health')
            if category not in HEALTH_TYPES:raise ValueError('기록 종류를 확인하세요.')
            when=day(data.get('date'));clock=text(data.get('time','09:00'),'시각',True)
            try:
                if datetime.strptime(clock,'%H:%M').strftime('%H:%M')!=clock:raise ValueError()
            except ValueError:raise ValueError('시각은 HH:MM으로 입력하세요.') from None
            weight=text(data.get('weight',''),'체중',maximum=20)
            if weight and not 0<decimal(weight)<=1000:raise ValueError('체중은 0보다 크고 1,000kg 이하로 입력하세요.')
            height=text(data.get('height',''),'키',maximum=20)
            if height and not 0<decimal(height)<=300:raise ValueError('키는 0보다 크고 300cm 이하로 입력하세요.')
            born=day(data['birth_date']) if data.get('birth_date') else ''
            if born and born>when:raise ValueError('생년월일은 기록일보다 이후일 수 없습니다.')
            content={'date':when,'time':clock,'category':category,'title':text(data.get('title'),'내용',True,200),
                'place':text(data.get('place',''),'병원·약국',maximum=200),'weight':weight,'height':height,
                'subject':text(data.get('subject','나'),'기록 대상',True,100),'birth_date':born,
                'amount':money(data.get('amount',0)),'notes':text(data.get('notes',''),'설명',maximum=20000)}
            alarm=bool(data.get('alarm',False))
            if alarm and category!='appointment':raise ValueError('알림은 병원 예약에서 설정하세요.')
            previous=old['alarm_event_id'] if old else None
            if previous:self.db.execute('DELETE FROM desk_events WHERE id=? AND user_id=?',(previous,self.actor['id']))
            stamp=now();event_id=None
            if alarm:
                self.require_menu('home')
                event_id=self.db.execute("INSERT INTO desk_events(user_id,date,time,title,notes,alarm,created_at,updated_at) VALUES(?,?,?,'개인 일정 알림','개인 창의 건강·병원 기록에서 예약 내용을 확인하세요.',1,?,?)",(self.actor['id'],when,clock,stamp,stamp)).lastrowid
            identifier=identifier or uuid4().hex
            cipher=_seal(key,json.dumps(content,ensure_ascii=False).encode(),self._health_aad(kind,identifier))
            if old:self.db.execute('UPDATE personal_health_entries SET ciphertext=?,alarm_event_id=?,updated_at=? WHERE id=?',(cipher,event_id,stamp,identifier))
            else:self.db.execute('INSERT INTO personal_health_entries VALUES(?,?,?,?,?,?,?)',(identifier,self.actor['id'],kind,cipher,event_id,stamp,stamp))
            self._audit('save','personal_health',None,{})
            return identifier

    def delete_health_entry(self,kind,key,identifier):
        with self._tx():
            self._health_key(kind,key)
            if kind=='household':self._require_capability(kind,'delete')
            row=self.db.execute('SELECT alarm_event_id FROM personal_health_entries WHERE id=? AND user_id=? AND kind=?',(identifier,self.actor['id'],kind)).fetchone()
            if not row:raise ValueError('건강 기록을 찾을 수 없습니다.')
            self.db.execute('DELETE FROM personal_health_entries WHERE id=?',(identifier,))
            if row[0]:self.db.execute('DELETE FROM desk_events WHERE id=? AND user_id=?',(row[0],self.actor['id']))
            self._audit('delete','personal_health',None,{})
