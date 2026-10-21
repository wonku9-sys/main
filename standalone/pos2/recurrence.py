"""Korean solar/lunar anniversaries, using packaged offline conversion data."""
import calendar
from datetime import date,timedelta
from korean_lunar_calendar import KoreanLunarCalendar

KINDS={'birthday':'생일','wedding':'결혼기념일','memorial':'제사','anniversary':'기념일','event':'행사','memo':'일정·메모'}


def lunar_date(year,month,day,leap=False,clamp=False):
    converter=KoreanLunarCalendar()
    if converter.setLunarDate(year,month,day,leap) and converter.isIntercalation==leap:
        return date.fromisoformat(converter.SolarIsoFormat())
    if clamp and day==30:return lunar_date(year,month,29,leap)
    return None


def validate_rule(data):
    try:
        result={'calendar':data.get('calendar','solar'),'repeat':data.get('repeat','once'),'event_kind':data.get('event_kind','memo'),
                'base_year':int(data['base_year']),'month':int(data['month']),'day':int(data['day']),
                'leap':int(bool(data.get('leap',False))),'lead_days':int(data.get('lead_days',0)),
                'leap_fallback':int(bool(data.get('leap_fallback',True)))}
    except (TypeError,ValueError,KeyError):raise ValueError('일정의 기준 연도·월·일을 확인하세요.') from None
    if result['calendar'] not in {'solar','lunar'} or result['repeat'] not in {'once','yearly'} or result['event_kind'] not in KINDS or not 0<=result['lead_days']<=365:
        raise ValueError('일정 종류·반복·알림 설정을 확인하세요.')
    try:
        if result['calendar']=='solar':origin=date(result['base_year'],result['month'],result['day']);result['leap']=0
        else:
            if not 1900<=result['base_year']<=2050:raise ValueError()
            origin=lunar_date(result['base_year'],result['month'],result['day'],bool(result['leap']))
            if origin is None:raise ValueError()
    except (ValueError,OverflowError):raise ValueError('유효하지 않은 날짜입니다. 음력은 1900~2050년, 윤달 여부도 확인하세요.') from None
    return result,origin


def occurrences(rule,start,end):
    _,origin=validate_rule(rule)
    if rule['repeat']=='once':return [origin] if start<=origin<=end else []
    result=[]
    for year in range(max(rule['base_year'],start.year-1),end.year+1):
        if rule['calendar']=='solar':
            value=date(year,rule['month'],min(rule['day'],calendar.monthrange(year,rule['month'])[1]))
        else:
            if not 1900<=year<=2050:continue
            value=lunar_date(year,rule['month'],rule['day'],bool(rule['leap']),True)
            if value is None and rule['leap'] and rule['leap_fallback']:value=lunar_date(year,rule['month'],rule['day'],False,True)
        if value and start<=value<=end and value>=origin:result.append(value)
    return sorted(set(result))


def counter(rule,on=None):
    on=on or date.today();_,origin=validate_rule(rule)
    elapsed=(on-origin).days
    if elapsed<0:return f'시작까지 {-elapsed}일'
    years=on.year-origin.year-((on.month,on.day)<(origin.month,origin.day))
    label='만 '+str(years)+'세' if rule['event_kind']=='birthday' else '결혼 '+str(years)+'주년' if rule['event_kind']=='wedding' else str(years)+'년 경과'
    return f'{label} · {elapsed+1:,}일째 (실제 경과 {elapsed:,}일)'


def event_rows(store,start,end):
    records=[]
    for raw in store.db.execute('SELECT * FROM desk_events WHERE user_id=?',(store.actor['id'],)):
        base=dict(raw);rule=store.db.execute('SELECT * FROM desk_event_rules WHERE event_id=?',(base['id'],)).fetchone()
        if rule:
            rule=dict(rule);dates=occurrences(rule,start,end)
        else:dates=[date.fromisoformat(base['date'])] if start.isoformat()<=base['date']<=end.isoformat() else []
        for value in dates:
            item=dict(base,date=value.isoformat())
            if rule:
                item.update(rule);item['source_date']=base['date'];item['counter']=counter(rule)
                if rule['repeat']=='yearly':
                    receipt=store.db.execute('SELECT notified_at FROM desk_event_receipts WHERE event_id=? AND occurrence=?',(base['id'],value.isoformat())).fetchone()
                    item['notified_at']=receipt[0] if receipt else ''
            records.append(item)
    return sorted(records,key=lambda r:(r['date'],r['time'],r['id']))
