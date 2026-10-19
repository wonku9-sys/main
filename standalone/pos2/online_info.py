"""Optional public weather/time; the business database never goes online."""
from datetime import datetime, timezone, timedelta
import json
import math
import time
from urllib.request import Request, urlopen

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


def _json(url):
    request = Request(url,headers={"User-Agent":"SeoyoungPOS-Standalone/2.3.0 (https://github.com/wonku9-sys/main)","Accept":"application/json"})
    with urlopen(request,timeout=3) as response:
        raw = response.read(262145)
        if len(raw)>262144: raise ValueError("응답 크기 초과")
        return json.loads(raw)


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


def fetch_online(config):
    config = validate_online(config)
    if not config["enabled"]: return {"disabled":True}
    result = {"city":config["city"],"received":time.monotonic()}
    try:
        data = _json(f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={config['latitude']:.4f}&lon={config['longitude']:.4f}")
        forecast = min(data["properties"]["timeseries"],key=lambda r:abs(datetime.fromisoformat(r["time"].replace('Z','+00:00')).timestamp()-time.time()))
        current = forecast["data"]
        temperature = float(current["instant"]["details"]["air_temperature"])
        if not math.isfinite(temperature) or not -100<=temperature<=70: raise ValueError()
        observed = datetime.fromisoformat(forecast["time"].replace("Z","+00:00")).astimezone(timezone(timedelta(hours=9)))
        symbol = current.get("next_1_hours",current.get("next_6_hours",{})).get("summary",{}).get("symbol_code","")
        description = "뇌우" if "thunder" in symbol else "눈" if "snow" in symbol else "진눈깨비" if "sleet" in symbol else "비" if "rain" in symbol else "맑음" if "clearsky" in symbol or "fair" in symbol else "구름 조금" if "partlycloudy" in symbol else "흐림" if "cloudy" in symbol else "안개" if "fog" in symbol else "기상정보"
        result["weather"] = f"{description} · {temperature:.1f}°C"
        result["weather_at"] = observed.strftime("%m/%d %H:%M")
    except (OSError,ValueError,TypeError,KeyError,IndexError): result["weather_error"] = True
    try:
        before = time.monotonic()
        data = _json("https://timeapi.io/api/time/current/zone?timeZone=Asia%2FSeoul")
        value = datetime.fromisoformat(data["dateTime"])
        result["clock"] = value.replace(tzinfo=timezone(timedelta(hours=9))).timestamp()
        result["clock_anchor"] = (before+time.monotonic())/2
    except (OSError,ValueError,TypeError,KeyError): result["clock_error"] = True
    return result
