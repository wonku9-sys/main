"""Manual health tracking and arithmetic summaries, not nutrition lookup/advice."""
from datetime import date,datetime
from decimal import Decimal
from .common import day,decimal,text

# name: (caption, maximum, record categories)
TRACKING_FIELDS={
 'target_weight':('목표 체중 kg',1000,{'goal'}),
 'target_water_ml':('하루 목표 수분 ml',100000,{'goal'}),
 'target_calories':('하루 참고 칼로리 kcal',100000,{'goal'}),
 'calories':('섭취·계획 칼로리 kcal',100000,{'meal','diet_plan'}),
 'protein_g':('단백질 g',10000,{'meal','diet_plan'}),
 'carbs_g':('탄수화물 g',10000,{'meal','diet_plan'}),
 'fat_g':('지방 g',10000,{'meal','diet_plan'}),
 'sugar_g':('당류 g',10000,{'meal','diet_plan'}),
 'sodium_mg':('나트륨 mg',100000,{'meal','diet_plan'}),
 'water_ml':('마신 수분 ml',100000,{'water'}),
 'duration_minutes':('운동·명상·루틴 시간 분',1440,{'exercise','routine','meditation'}),
 'burned_calories':('소모 칼로리 kcal · 수동 기록',100000,{'exercise'}),
 'exercise_distance':('운동 거리 km',10000,{'exercise'}),
 'sets':('세트 수',10000,{'exercise','routine'}),
 'reps':('세트당 횟수',10000,{'exercise','routine'}),
 'systolic':('수축기 혈압 mmHg',400,{'metric'}),
 'diastolic':('이완기 혈압 mmHg',300,{'metric'}),
 'pulse':('맥박 회/분',400,{'metric'}),
 'glucose':('혈당 mg/dL',2000,{'metric'}),
 'sleep_hours':('수면 시간',24,{'metric','sleep'}),
 'sleep_quality':('수면 만족도 1~5',5,{'sleep'}),
 'stress_level':('체감 스트레스 0~10',10,{'meditation','metric'}),
 'waist_cm':('허리둘레 cm',500,{'metric','body'}),
 'chest_cm':('가슴둘레 cm',500,{'body'}),
 'hip_cm':('엉덩이둘레 cm',500,{'body'}),
 'arm_cm':('팔둘레 cm',200,{'body'}),
 'thigh_cm':('허벅지둘레 cm',300,{'body'}),
}
NUTRIENTS=('calories','protein_g','carbs_g','fat_g','sugar_g','sodium_mg')
MEAL_SLOTS={'breakfast':'아침','lunch':'점심','dinner':'저녁','snack':'간식'}


def tracking_data(data,category):
    result={}
    for name,(label,maximum,categories) in TRACKING_FIELDS.items():
        value=data.get(name,'') if category in categories else ''
        if value not in ('',None):
            number=decimal(value)
            if not 0<=number<=maximum or number!=number.quantize(Decimal('0.001')):raise ValueError(label+' 값을 확인하세요. 소수점 세 자리까지 입력할 수 있습니다.')
            if name in {'target_weight','water_ml','systolic','diastolic','pulse','glucose'} and number==0:raise ValueError(label+'는 0보다 커야 합니다.')
            result[name]=str(number)
        else:result[name]=''
    if bool(result['systolic'])!=bool(result['diastolic']):raise ValueError('혈압은 수축기·이완기를 함께 입력하세요.')
    if result['systolic'] and decimal(result['systolic'])<decimal(result['diastolic']):raise ValueError('수축기 혈압은 이완기 혈압보다 작을 수 없습니다.')
    result['meal_slot']=data.get('meal_slot','breakfast') if category in {'meal','diet_plan'} else ''
    if result['meal_slot'] and result['meal_slot'] not in MEAL_SLOTS:raise ValueError('식사 구분을 확인하세요.')
    result['food_items']=text(data.get('food_items',''),'식단 내용',maximum=2000) if category in {'meal','diet_plan'} else ''
    result['exercise_type']=text(data.get('exercise_type',''),'운동·요가 종류',maximum=100) if category in {'exercise','routine'} else ''
    result['goal_date']=day(data['goal_date']) if category=='goal' and data.get('goal_date') else ''
    result['sleep_start']=text(data.get('sleep_start',''),'잠든 시각',maximum=5) if category=='sleep' else ''
    result['sleep_end']=text(data.get('sleep_end',''),'깬 시각',maximum=5) if category=='sleep' else ''
    if result['sleep_start'] or result['sleep_end']:
        try:
            start=datetime.strptime(result['sleep_start'],'%H:%M');end=datetime.strptime(result['sleep_end'],'%H:%M')
            if start.strftime('%H:%M')!=result['sleep_start'] or end.strftime('%H:%M')!=result['sleep_end'] or start==end:raise ValueError()
        except ValueError:raise ValueError('수면 시작·종료를 HH:MM으로 모두 입력하세요. 같은 시각은 사용할 수 없습니다.') from None
        minutes=((end.hour*60+end.minute)-(start.hour*60+start.minute))%1440
        result['sleep_hours']=str((Decimal(minutes)/60).quantize(Decimal('0.01')))
    result['supplement_dose']=text(data.get('supplement_dose',''),'직접 정한 복용 메모',maximum=200) if category in {'supplement','supplement_taken'} else ''
    result['supplement_times']=[];result['supplement_days']=[];result['supplement_end']=''
    if category=='supplement':
        times=data.get('supplement_times','09:00')
        if isinstance(times,str):times=[v.strip() for v in times.split(',') if v.strip()]
        if not isinstance(times,list) or not 1<=len(times)<=6:raise ValueError('영양제 알림은 하루 1~6개 시각을 쉼표로 나누어 입력하세요.')
        try:
            for value in times:
                if datetime.strptime(value,'%H:%M').strftime('%H:%M')!=value:raise ValueError()
        except (ValueError,TypeError):raise ValueError('알림 시각은 09:00,18:30처럼 입력하세요.') from None
        result['supplement_times']=sorted(set(times))
        days=data.get('supplement_days',list(range(1,8)))
        if isinstance(days,str):days=[v.strip() for v in days.split(',') if v.strip()]
        try:days=sorted(set(int(v) for v in days))
        except (ValueError,TypeError):raise ValueError('복용 알림 요일은 월요일 1~일요일 7로 입력하세요.') from None
        if not days or set(days)-set(range(1,8)):raise ValueError('복용 알림 요일은 1~7 중에서 선택하세요.')
        result['supplement_days']=days
        result['supplement_end']=day(data['supplement_end']) if data.get('supplement_end') else ''
        if result['supplement_end'] and result['supplement_end']<day(data.get('date')):raise ValueError('영양제 알림 종료일을 확인하세요.')
    weekdays=data.get('routine_days','') if category=='routine' else ''
    if isinstance(weekdays,list):values=weekdays
    else:
        mapping={'월':1,'화':2,'수':3,'목':4,'금':5,'토':6,'일':7}
        values=[mapping.get(v.strip(),v.strip()) for v in str(weekdays).split(',') if v.strip()]
    try:result['routine_days']=sorted({int(v) for v in values})
    except (ValueError,TypeError):raise ValueError('루틴 요일은 월,수,금 또는 1,3,5처럼 입력하세요.') from None
    if set(result['routine_days'])-set(range(1,8)):raise ValueError('루틴 요일은 월요일(1)~일요일(7)입니다.')
    return result


class HealthTrackingMixin:
    def health_report(self,kind,key,start,end,subject=''):
        start,end=day(start),day(end)
        rows=self.health_entries(kind,key,start,end)
        if subject:rows=[r for r in rows if r['subject']==subject]
        daily={};sum_value=lambda records,name:sum((decimal(r.get(name) or 0) for r in records),Decimal(0))
        for row in rows:
            if row['category'] in {'goal','routine','diet_plan','supplement'}:continue
            record=daily.setdefault(row['date'],dict(date=row['date'],calories=Decimal(0),protein_g=Decimal(0),carbs_g=Decimal(0),fat_g=Decimal(0),sugar_g=Decimal(0),sodium_mg=Decimal(0),water_ml=Decimal(0),duration_minutes=Decimal(0),burned_calories=Decimal(0),sleep_hours=Decimal(0),meditation_minutes=Decimal(0)))
            fields=NUTRIENTS if row['category']=='meal' else ('water_ml',) if row['category']=='water' else ('duration_minutes','burned_calories') if row['category']=='exercise' else ()
            for name in fields:record[name]+=decimal(row.get(name) or 0)
            if row['category']=='sleep':record['sleep_hours']+=decimal(row.get('sleep_hours') or 0)
            if row['category']=='meditation':record['meditation_minutes']+=decimal(row.get('duration_minutes') or 0)
        totals={name:sum_value(list(daily.values()),name) for name in (*NUTRIENTS,'water_ml','duration_minutes','burned_calories','sleep_hours','meditation_minutes')}
        history=self.health_entries(kind,key,'1900-01-01',end)
        if subject:history=[r for r in history if r['subject']==subject]
        people=[]
        for person in sorted({r['subject'] for r in history}):
            own=[r for r in history if r['subject']==person]
            measures=[r for r in own if r.get('weight') and r['category'] in {'weight','growth'}]
            goals=[r for r in own if r['category']=='goal'];goal=goals[-1] if goals else {}
            latest=measures[-1] if measures else {}
            people.append(dict(subject=person,date=latest.get('date',''),weight=latest.get('weight',''),target_weight=goal.get('target_weight',''),goal_date=goal.get('goal_date',''),target_water_ml=goal.get('target_water_ml',''),target_calories=goal.get('target_calories','')))
        weights=[r for r in rows if r.get('weight') and r['category'] in {'weight','growth'}]
        return dict(daily=sorted(daily.values(),key=lambda r:r['date']),totals=totals,people=people,weights=weights,
            plans=[r for r in rows if r['category']=='diet_plan'],routines=[r for r in history if r['category']=='routine'],
            metrics=[r for r in rows if r['category'] in {'metric','sleep','meditation','body','supplement_taken'}],expense_total=sum(r['amount'] for r in rows),
            day_count=(date.fromisoformat(end)-date.fromisoformat(start)).days+1)
