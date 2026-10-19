"""Optional public weather/time; the business database never goes online."""
from datetime import datetime, timezone, timedelta
import json
import math
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from . import __version__

KST = timezone(timedelta(hours=9))
NETWORK_ERRORS = (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ElementTree.ParseError)
WEATHER_SITES = {"기상청":"https://www.weather.go.kr/w/index.do", "웨더아이":"https://www.weatheri.co.kr/"}

DEFAULT_ONLINE = {"enabled":False,"city":"서울","latitude":37.5665,"longitude":126.9780}
CITIES = {"서울":(37.5665,126.9780),"아산":(36.7898,127.0018),"천안":(36.8151,127.1139),"부산":(35.1796,129.0756),"대구":(35.8714,128.6014),"인천":(37.4563,126.7052),"광주":(35.1595,126.8526),"대전":(36.3504,127.3845),"울산":(35.5384,129.3114),"세종":(36.4800,127.2890),"수원":(37.2636,127.0286),"청주":(36.6424,127.4890),"전주":(35.8242,127.1480),"제주":(33.4996,126.5312),"강릉":(37.7519,128.8761)}


def validate_online(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_ONLINE) or type(value["enabled"]) is not bool:
        raise ValueError("날씨·시간 설정을 확인하세요.")
    if not isinstance(value["city"],str) or not value["city"].strip() or len(value["city"])>50:
        raise ValueError("날씨 지역명을 입력하세요.")
    try:
        lat,lon = float(value["latitude"]),float(value["longitude"])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180: raise ValueError()
    except (TypeError,ValueError): raise ValueError("위도·경도 범위를 확인하세요.") from None
    return dict(enabled=value["enabled"],city=value["city"].strip(),latitude=lat,longitude=lon)


def _read(url):
    request = Request(url,headers={"User-Agent":f"SY-POS/{__version__} (https://github.com/wonku9-sys/main)","Accept":"application/xml,application/json;q=0.9,*/*;q=0.5"})
    with urlopen(request,timeout=8) as response:
        raw = response.read(1_048_577)
        if len(raw)>1_048_576: raise ValueError("응답 크기 초과")
        return raw


def _json(url):
    return json.loads(_read(url))


def network_error(exc):
    """Actionable, sanitized errors; never expose a proxy URL or credentials."""
    if isinstance(exc, HTTPError): return f"서비스 응답 오류 (HTTP {exc.code})"
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError): return "보안 인증서 확인 실패 · Windows 날짜·시각을 확인하세요"
    if isinstance(reason, (TimeoutError, socket.timeout)): return "응답 시간 초과"
    if isinstance(exc, OSError): return "인터넷 연결 또는 서비스 접속 실패"
    return "날씨 응답 형식 오류"


def weather_text(code):
    if code==0:return "맑음"
    if code in {1,2}:return "구름 조금"
    if code==3:return "흐림"
    if code in {45,48}:return "안개"
    if code in {51,53,55,56,57}:return "이슬비"
    if code in {61,63,65,66,67,80,81,82}:return "비"
    if code in {71,73,75,77,85,86}:return "눈"
    if code in {95,96,99}:return "뇌우"
    return "기상정보"


def kma_grid(latitude, longitude):
    """KMA DFS Lambert conformal 5 km grid, not GPS/IP geolocation."""
    if not 31<=latitude<=44 or not 124<=longitude<=132:
        raise ValueError("기상청 동네예보는 국내 지역 좌표를 선택하세요.")
    rad=math.pi/180;re=6371.00877/5
    slat1,slat2=30*rad,60*rad
    sn=math.log(math.cos(slat1)/math.cos(slat2))/math.log(math.tan(math.pi/4+slat2/2)/math.tan(math.pi/4+slat1/2))
    sf=math.tan(math.pi/4+slat1/2)**sn*math.cos(slat1)/sn
    ro=re*sf/math.tan(math.pi/4+38*rad/2)**sn
    ra=re*sf/math.tan(math.pi/4+latitude*rad/2)**sn
    theta=(longitude-126)*rad*sn
    return math.floor(ra*math.sin(theta)+43+.5), math.floor(ro-ra*math.cos(theta)+136+.5)


def _kma_weather(config, host):
    x,y=kma_grid(config['latitude'],config['longitude'])
    raw=_read(f"https://{host}/wid/queryDFS.jsp?gridx={x}&gridy={y}")
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise ValueError("외부 XML 선언 거부")
    root=ElementTree.fromstring(raw)
    if int(root.findtext('.//header/x'))!=x or int(root.findtext('.//header/y'))!=y: raise ValueError("예보 지역 불일치")
    issued=datetime.strptime(root.findtext('.//header/tm'),'%Y%m%d%H%M').replace(tzinfo=KST)
    instant=time.time()
    if abs(issued.timestamp()-instant)>24*3600: raise ValueError("예보 발표 시각을 확인하세요")
    forecasts=[]
    for row in root.findall('.//body/data'):
        day,hour=int(row.findtext('day')),int(row.findtext('hour'))
        if day not in {0,1,2} or not 1<=hour<=24: raise ValueError("예보 시각 오류")
        stamp=issued.replace(hour=0,minute=0,second=0)+timedelta(days=day,hours=hour)
        if stamp.timestamp()>=instant:forecasts.append((stamp,row))
    if not forecasts:raise ValueError("최신 예보 없음")
    observed,row=min(forecasts,key=lambda pair:pair[0])
    pty,sky=int(row.findtext('pty')),int(row.findtext('sky'))
    description=({1:'비',2:'비/눈',3:'눈',4:'소나기',5:'빗방울',6:'빗방울/눈날림',7:'눈날림'}.get(pty) if pty else {1:'맑음',3:'구름 많음',4:'흐림'}.get(sky))
    if description is None:raise ValueError("날씨 코드 오류")
    result=_weather_result(row.findtext('temp'),description,observed,'기상청 동네예보')
    result['weather_issued']=issued.strftime('%m/%d %H:%M')
    result['weather_grid']=[x,y]
    return result


def _weather_result(value, description, observed, source):
    if isinstance(value, bool): raise ValueError("기온 오류")
    temperature = float(value)
    if not math.isfinite(temperature) or not -100<=temperature<=70: raise ValueError("기온 오류")
    return {"weather":f"{description} · {temperature:.1f}°C", "weather_at":observed.astimezone(KST).strftime("%m/%d %H:%M"), "weather_source":source}


def fetch_online(config):
    config = validate_online(config)
    if not config["enabled"]: return {"disabled":True}
    result = {"city":config["city"],"received":time.monotonic()}
    failures=[]
    for host in ("www.weather.go.kr", "www.kma.go.kr"):
        try:
            result.update(_kma_weather(config,host))
            break
        except NETWORK_ERRORS as exc:
            failures.append(f"{host}: {network_error(exc)}")
    else:
        result.update(weather_error=True, weather_details="\n".join(failures))
    try:
        before = time.monotonic()
        data = _json("https://timeapi.io/api/time/current/zone?timeZone=Asia%2FSeoul")
        value = datetime.fromisoformat(data["dateTime"])
        if value.tzinfo is None: value = value.replace(tzinfo=KST)
        result["clock"] = value.timestamp()
        result["clock_anchor"] = (before+time.monotonic())/2
    except NETWORK_ERRORS: result["clock_error"] = True
    return result
