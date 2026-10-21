"""Explainable local keyword classification, with encrypted user overrides."""
from .common import text

BUILTINS=(
 ('salary','급여',['급여','월급','상여'],'income'),
 ('interest','이자수입',['이자입금','예금이자'],'income'),
 ('fuel','차량',['주유','휘발유','경유','자동차보험','자동차세'],'expense'),
 ('medical','의료·건강',['병원','의원','약국','진료','치과'],'expense'),
 ('housing','주거·공과금',['월세','관리비','도시가스','전기요금','수도요금'],'expense'),
 ('phone','통신',['통신비','휴대폰요금','인터넷요금'],'expense'),
 ('food','식비',['식당','김밥','식비','장보기','마트'],'expense'),
 ('cafe','카페·간식',['카페','커피','베이커리','빵집'],'expense'),
 ('traffic','교통',['버스','지하철','택시','철도','주차','통행료'],'expense'),
 ('education','교육',['학원','수강료','교육비','도서구입'],'expense'),
)


class HouseholdCategoryMixin:
    def household_category_rules(self,key):
        custom=self._finance_records(key,'category_rules');overrides={r.get('builtin'):r for r in custom if r.get('builtin')}
        rules=[dict(id='builtin/'+identifier,builtin=identifier,category=category,keywords=keywords,kind=kind,priority=100+index,active=True)
               for index,(identifier,category,keywords,kind) in enumerate(BUILTINS) if identifier not in overrides]
        return sorted(custom+rules,key=lambda r:(r['priority'],r['category'],r['id']))

    def save_household_category_rule(self,key,data,identifier=None):
        with self._tx():
            existing=self._finance_records(key,'category_rules');builtin=''
            if identifier and str(identifier).startswith('builtin/'):
                builtin=str(identifier).split('/',1)[1]
                if builtin not in {r[0] for r in BUILTINS}:raise ValueError('기본 분류 규칙을 확인하세요.')
                identifier=next((r['id'] for r in existing if r.get('builtin')==builtin),None)
            elif identifier:
                old=next((r for r in existing if r['id']==identifier),None)
                if not old:raise ValueError('분류 규칙을 찾을 수 없습니다.')
                builtin=old.get('builtin','')
            if not identifier and len(existing)>=100:raise ValueError('개인 자동분류 규칙은 100개까지 저장할 수 있습니다.')
            keywords=data.get('keywords',[])
            if isinstance(keywords,str):keywords=keywords.replace('\n',',').split(',')
            if not isinstance(keywords,list):raise ValueError('키워드는 쉼표로 나누어 입력하세요.')
            keywords=list(dict.fromkeys(text(value,'키워드',True,100) for value in keywords if str(value).strip()))
            if not keywords or len(keywords)>20:raise ValueError('키워드는 1~20개를 지정하세요.')
            kind=data.get('kind','expense')
            if kind not in {'income','expense','both'}:raise ValueError('수입·지출 적용 구분을 확인하세요.')
            try:priority=int(data.get('priority',50))
            except (ValueError,TypeError):raise ValueError('우선순위는 0~999 정수입니다.') from None
            if not 0<=priority<=999:raise ValueError('우선순위는 0~999 정수입니다.')
            return self._finance_put(key,'category_rules',dict(category=text(data.get('category'),'추천 분류',True,100),keywords=keywords,
                kind=kind,priority=priority,active=bool(data.get('active',True)),builtin=builtin),identifier)

    def suggest_household_category(self,key,source,kind='expense'):
        source=text(source,'자동분류 내용',maximum=20000).casefold()
        if kind not in {'income','expense',''}:raise ValueError('수입·지출 구분을 확인하세요.')
        for rule in self.household_category_rules(key):
            if not rule['active'] or rule['kind']!='both' and kind and rule['kind']!=kind:continue
            matched=next((word for word in rule['keywords'] if word.casefold() in source),None)
            if matched:return dict(category=rule['category'],keyword=matched,rule_id=rule['id'])
        return dict(category='',keyword='',rule_id=None)
