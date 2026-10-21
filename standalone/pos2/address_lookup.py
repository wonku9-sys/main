"""Opt-in free Kakao postcode search in the system browser, no WebEngine."""
import json
from http.server import BaseHTTPRequestHandler,HTTPServer
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
from PySide6.QtCore import QObject,Signal,QUrl
from PySide6.QtGui import QDesktopServices


def selection(data):
    if not isinstance(data,dict) or set(data)!={'postcode','address'}:raise ValueError('주소검색 응답을 확인하세요.')
    postcode,address=data['postcode'],data['address']
    if not isinstance(postcode,str) or not re.fullmatch(r'[0-9]{5}',postcode):raise ValueError('우편번호를 확인하세요.')
    if not isinstance(address,str) or not 1<=len(address.strip())<=300 or any(ord(c)<32 for c in address):raise ValueError('주소를 확인하세요.')
    return dict(postcode=postcode,address=address.strip())


class AddressLookup(QObject):
    selected=Signal(dict)
    def __init__(self,parent=None):
        super().__init__(parent);self.server=None;self.thread=None;self.token=secrets.token_urlsafe(32)
        self.deadline=0;self.used=False;self.stopped=threading.Event()
    def start(self,query=''):
        if self.server is not None:raise ValueError('주소검색이 이미 열려 있습니다.')
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass  # Never log addresses.
            def answer(self,status,payload=b'',kind='text/plain; charset=utf-8'):
                self.send_response(status);self.send_header('Content-Type',kind)
                self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store')
                self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                self.wfile.write(payload)
            def valid(self):
                return self.headers.get('Host')==owner.host and urlsplit(self.path).path=='/'+owner.token and time.monotonic()<owner.deadline and not owner.used
            def do_GET(self):
                if not self.valid():self.answer(404);return
                self.answer(200,owner.html(query).encode('utf-8'),'text/html; charset=utf-8')
            def do_POST(self):
                if not self.valid() or self.headers.get('Origin')!=owner.origin or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    self.answer(403);return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=4096:raise ValueError()
                    result=selection(json.loads(self.rfile.read(size)))
                except (ValueError,TypeError,UnicodeError):self.answer(400);return
                owner.used=True;self.answer(200,b'OK');owner.selected.emit(result);owner.stopped.set()
        self.server=HTTPServer(('127.0.0.1',0),Handler);self.server.timeout=.2
        self.host=f'127.0.0.1:{self.server.server_port}';self.origin='http://'+self.host;self.deadline=time.monotonic()+600
        def run():
            try:
                while not self.stopped.is_set() and time.monotonic()<self.deadline:self.server.handle_request()
            finally:self.server.server_close()
        self.thread=threading.Thread(target=run,name='sy-postcode',daemon=True);self.thread.start()
        self.url=self.origin+'/'+self.token
        if not QDesktopServices.openUrl(QUrl(self.url)):
            self.stop();raise OSError('기본 브라우저를 열지 못했습니다. 주소를 직접 입력하세요.')
        return self.url
    def stop(self):
        self.stopped.set()
        if self.thread is not None and self.thread is not threading.current_thread():self.thread.join(.4)
    def html(self,query):
        # Only the address query reaches the official service, not customer
        # name/phone/member ID. Keep the official logo and script unmodified.
        query_json=json.dumps(str(query)[:300],ensure_ascii=True).replace('<','\\u003c')
        return """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="referrer" content="no-referrer"><title>SY POS 무료 주소찾기</title>
<style>body{font-family:sans-serif;background:#e5e8e1;margin:18px}#postcode{width:100%;height:620px;background:white}p{line-height:1.6}</style>
<h2>우편번호 · 기본주소 선택</h2><p id="status">카카오 우편번호 검색입니다. 주소를 고르면 SY POS 입력창에 전달됩니다.
상세주소는 프로그램에서 직접 입력하세요. 검색이 열리지 않으면 프로그램에서 수기로 입력할 수 있습니다.</p>
<div id="postcode"></div>
<script src="https://t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"
onerror="document.getElementById('status').textContent='인터넷 연결 또는 서비스 상태를 확인하고, 프로그램에서 주소를 직접 입력하세요.'"></script>
<script>if(window.daum&&daum.Postcode){new daum.Postcode({oncomplete:async function(data){
try{let response=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({postcode:data.zonecode,address:data.userSelectedType==='R'?data.roadAddress:data.jibunAddress})});
document.getElementById('status').textContent=response.ok?'선택 주소를 전달했습니다. SY POS에서 확인하고 저장하세요. 이 브라우저 탭은 닫아도 됩니다.':'전달하지 못했습니다. 프로그램에서 주소를 직접 입력하세요.';
}catch(error){document.getElementById('status').textContent='프로그램의 검색 시간이 끝났거나 창이 닫혔습니다. 주소를 직접 입력하세요.';}
}}).embed(document.getElementById('postcode'),{q:"""+query_json+"""});}</script></html>"""
