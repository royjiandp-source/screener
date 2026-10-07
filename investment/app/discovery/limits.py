"""Bound request bodies and local mutation rates before JSON parsing."""
import time
import threading
from collections import deque
from urllib.parse import urlparse
from starlette.responses import JSONResponse

class DiscoveryLimits:
    def __init__(self,app,max_bytes=10_000_000):
        self.app=app;self.max_bytes=max_bytes;self.lock=threading.Lock();self.calls={}

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or not scope['path'].startswith('/api/discovery/') or scope['method']!='POST':
            return await self.app(scope,receive,send)
        headers={k.decode().lower():v.decode() for k,v in scope['headers']}
        origin=headers.get('origin')
        if origin and urlparse(origin).netloc.lower()!=headers.get('host','').lower():
            return await JSONResponse({'detail':'다른 사이트에서 시작한 변경 요청은 허용되지 않습니다.'},403)(scope,receive,send)
        try:length=int(headers.get('content-length','0'))
        except ValueError:length=self.max_bytes+1
        if length<0 or length>self.max_bytes:
            return await JSONResponse({'detail':'요청 자료는 10MB 이하로 나누어 주세요.'},413)(scope,receive,send)
        peer=(scope.get('client') or ['unknown'])[0];now=time.monotonic()
        with self.lock:
            for old in [k for k,v in self.calls.items() if not v or v[-1]<now-60]:self.calls.pop(old,None)
            calls=self.calls.setdefault(peer,deque())
            while calls and calls[0]<now-60:calls.popleft()
            limited=len(calls)>=30
            if not limited:calls.append(now)
        if limited:return await JSONResponse({'detail':'잠시 후 다시 요청하세요.'},429)(scope,receive,send)
        body=[];size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            chunk=message.get('body',b'');size+=len(chunk)
            if size>self.max_bytes:return await JSONResponse({'detail':'요청 자료가 10MB를 초과했습니다.'},413)(scope,receive,send)
            body.append(chunk)
            if not message.get('more_body'):break
        delivered=False
        async def buffered():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {'type':'http.request','body':b''.join(body),'more_body':False}
            return await receive()
        return await self.app(scope,buffered,send)
