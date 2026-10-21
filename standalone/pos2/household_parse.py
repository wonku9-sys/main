"""Conservative offline preview of explicitly pasted bank/card notifications."""
from datetime import date
from decimal import Decimal
import re


def normalize_tags(value):
    if isinstance(value,str): value=re.split(r'[\s,#]+',value)
    if not isinstance(value,(list,tuple)): raise ValueError('태그는 #여행 #식비처럼 입력하세요.')
    result=[]
    for tag in value:
        tag=str(tag).strip().lstrip('#')
        if not tag: continue
        if len(tag)>30 or not re.fullmatch(r'[\w가-힣-]+',tag): raise ValueError('태그는 30자 이내의 글자·숫자·밑줄·하이픈을 사용하세요.')
        if tag not in result: result.append(tag)
    if len(result)>20: raise ValueError('태그는 한 거래에 20개까지 지정하세요.')
    return result


def parse_notification(source,today=None):
    """No clipboard polling, remote calls, storage or automatic posting."""
    source=str(source).strip(); today=today or date.today()
    if not source or len(source)>20000: raise ValueError('문자·알림을 20,000자 이내로 붙여넣으세요.')
    warnings=[]; amounts=[]
    # Ignore balances, credit limits and cumulative summaries, not just the last
    # number in the message. Multiple transaction amounts require manual choice.
    for match in re.finditer(r'(?<![\d.,])(?:[₩￦]\s*)?([\d][\d,]*(?:\.\d{1,2})?)\s*원',source):
        prefix=source[max(0,match.start()-15):match.start()]
        if re.search(r'(?:잔액|누적|한도|누계|총액)[\s:：]*$',prefix): continue
        number=Decimal(match[1].replace(',',''))
        if number>0: amounts.append(number)
    unique=list(dict.fromkeys(amounts))
    amount=str(unique[0]) if len(amounts)==1 else ''
    if not amount: warnings.append('거래 금액을 하나로 확정할 수 없습니다. 금액을 직접 확인하세요.')
    income=bool(re.search(r'입금|급여',source)); expense=bool(re.search(r'출금|승인|결제|이체완료',source))
    kind='income' if income and not expense else 'expense' if expense and not income else ''
    if not kind: warnings.append('수입·지출 구분을 직접 선택하세요.')
    if re.search(r'취소|거절|예정|청구|환불',source): warnings.append('취소·예정·청구·환불 안내일 수 있습니다. 실제 거래인지 확인하세요.'); kind=''
    value=today; match=re.search(r'(?<!\d)(?:(20\d{2})[./-])?(\d{1,2})[./-](\d{1,2})(?!\d)',source)
    if match:
        try: value=date(int(match[1] or today.year),int(match[2]),int(match[3]))
        except ValueError: warnings.append('날짜를 읽지 못했습니다. 거래일을 확인하세요.')
        if not match[1]: warnings.append('연도는 PC의 올해로 입력했습니다. 거래일을 확인하세요.')
    else: warnings.append('거래일을 읽지 못해 오늘 날짜로 입력했습니다.')
    if value>today: warnings.append('미래 날짜입니다. 실제 거래일을 확인하세요.')
    return {'date':value.isoformat(),'kind':kind,'amount':amount,'title':'문자·알림에서 입력','category':'기타',
            'memo':source,'tags':normalize_tags(re.findall(r'#([\w가-힣-]+)',source)), 'warnings':warnings}
