import json, base64, os, time, uuid, sys, asyncio, urllib.request, urllib.error
import websockets
d=r'D:\project\偷菜\_recon'; ROOT='https://www.0809.one'; HOST='www.0809.one'; CK='new_api_refresh'; TOK={'v':''}
CKF=os.path.join(d,'mycookie_lllliii.txt'); LOG=os.path.join(d,'..','results','ws_play.log')
def log(s):
    print(s,flush=True)
    try: open(LOG,'a',encoding='utf-8').write(str(s)+'\n')
    except: pass
def http(m,u,token=None,body=None,cookie=None):
    h={'Accept':'application/json','Content-Type':'application/json','Origin':ROOT,'User-Agent':'Mozilla/5.0'}
    if token:h['Authorization']='Bearer '+token
    if cookie:h['Cookie']=CK+'='+cookie
    data=json.dumps(body).encode() if body is not None else None
    r=urllib.request.Request(u,data=data,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=15) as x:
            raw=x.read().decode('utf-8','replace');return x.status,(json.loads(raw) if raw.strip().startswith(('{','[')) else raw),(x.headers.get_all('Set-Cookie') or [])
    except urllib.error.HTTPError as e:
        raw=e.read().decode('utf-8','replace')
        try:dd=json.loads(raw)
        except:dd=raw
        return e.code,dd,(e.headers.get_all('Set-Cookie') or [])
def refresh():
    ck=open(CKF,encoding='utf-8').read().strip()
    for a in range(4):
        st,dd,sc=http('POST',ROOT+'/api/user/auth/refresh',cookie=ck,body={})
        if st==200 and dd.get('success') and dd.get('data',{}).get('access_token'):
            for c in sc:
                if c.startswith(CK+'='):open(CKF,'w',encoding='utf-8').write(c.split(';',1)[0].split('=',1)[1].strip());break
            TOK['v']=dd['data']['access_token'];return True
        time.sleep(2)
    return False
def cookie_header():
    try:
        parts=[]
        for ln in open(os.path.join(d,'jar_lllliii.txt'),encoding='utf-8').read().splitlines():
            if not ln or ln.startswith('#'):continue
            f=ln.split('\t')
            if len(f)>=7:parts.append(f[5]+'='+f[6])
        return '; '.join(parts)
    except Exception:return ''
def rest_state():
    st,dd,_=http('GET',ROOT+'/api/farm2d/farm/state',token=TOK['v'])
    return dd['data'] if st==200 and dd.get('success') else None
def rest_neigh():
    st,dd,_=http('GET',ROOT+'/api/farm2d/farm/neighbors',token=TOK['v'])
    return dd['data'] if st==200 and dd.get('success') else None
class C:
    def __init__(self,ws): self.ws=ws; self.version=0
    async def recv(self):
        m=json.loads(await asyncio.wait_for(self.ws.recv(),timeout=20)); t=m.get('type')
        if t in ('snapshot','patch'):
            dd=m.get('data') or {}
            if isinstance(dd,dict) and 'version' in dd: self.version=dd['version']
            return None
        if t=='pong': return None
        return m
    async def auth(self):
        await self.ws.send(json.dumps({'type':'auth','token':TOK['v'],'expectExisting':True}))
        while True:
            m=await self.recv()
            if m is None: continue
            if m.get('type')=='ready': return True
            if m.get('type') in ('auth_error','blocked','unavailable'): log('auth err '+json.dumps(m)[:120]); return False
    async def req(self,method,body):
        rid='live:'+str(uuid.uuid4())
        await self.ws.send(json.dumps({'type':'request','id':rid,'method':method,'body':body}))
        while True:
            m=await self.recv()
            if m is None: continue
            if m.get('type')=='reply' and m.get('id')==rid:
                b=m.get('body') or {}
                if isinstance(b,dict) and isinstance(b.get('data'),dict) and 'version' in b['data']: self.version=b['data']['version']
                return m.get('status'),b
    async def action(self,direct=None,command=None,params=None,tag=''):
        for _ in range(4):
            if command is not None:
                body={'action':'qq','params':{'command':command},'request_id':'farm:qq:'+str(uuid.uuid4()),'version':self.version}
                nm=command.get('action')
            else:
                body={'action':direct,'params':params or {},'request_id':f'farm:{direct}:{uuid.uuid4()}','version':self.version}
                nm=direct
            st,b=await self.req('action',body)
            code=b.get('code') if isinstance(b,dict) else ''
            if st==409 or (isinstance(b,dict) and 'STALE' in str(code)):
                s=rest_state()
                if s: self.version=s['version']
                continue
            return st,b
        return st,b
def brief(b):
    if not isinstance(b,dict): return str(b)[:60]
    ok=b.get('success'); msg=b.get('message') or b.get('code') or ''
    r=b.get('data',{}).get('result') if isinstance(b.get('data'),dict) else None
    if isinstance(r,dict) and r.get('qqMessage'): msg=r['qqMessage']
    return f'ok={ok} {str(msg)[:60]}'
async def play_pass(c, do_guild_ws=True):
    stt=rest_state()
    if not stt: log('no state'); return
    c.version=stt['version']; qv=stt['state']['qqView']
    # 一排：水/草/虫（careAll）+逐块补
    st,b=await c.action(command={'action':'careAll'}); log('[careAll] '+brief(b))
    for i,p in enumerate(qv['plots']):
        if p.get('weed',0)/1>0: st,b=await c.action(command={'action':'weed','plot':i}); log(f'[weed {i}] '+brief(b))
        if p.get('pest',0)/1>0: st,b=await c.action(command={'action':'pest','plot':i}); log(f'[pest {i}] '+brief(b))
        if not p.get('humidity'): st,b=await c.action(command={'action':'water','plot':i}); log(f'[water {i}] '+brief(b))
    # 收获/卖/种
    for cmd in [{'action':'harvestAll'},{'action':'sellAll'},{'action':'plantAll','cropId':59,'buyMissing':True,'confirm':True}]:
        st,b=await c.action(command=cmd); log(f"[{cmd['action']}] "+brief(b))
    # 领取
    for a in ['claimAll','claimAllAchv','claimFieldTasks']:
        st,b=await c.action(direct=a); log(f'[{a}] '+brief(b))
    # 商会
    if do_guild_ws:
        st,b=await c.action(command={'action':'acceptContract'}); log('[acceptContract] '+brief(b))
        st,b=await c.action(command={'action':'completeContract'}); log('[completeContract] '+brief(b))
        # 工坊/加工
        st,b=await c.action(command={'action':'buildWorkshop','workshop':'bakery'}); log('[buildWorkshop] '+brief(b))
        st,b=await c.action(command={'action':'claimProduction','workshop':'bakery'}); log('[claimProduction] '+brief(b))
        st,b=await c.action(command={'action':'produce','recipe':'bread','quantity':1}); log('[produce bread] '+brief(b))
    # 偷菜
    nb=rest_neigh(); tg=[]
    if isinstance(nb,dict):
        for n in nb.get('neighbors',[]):
            for p in n.get('plots',[]):
                if p.get('qq'):tg.append({'victim':n['user_id'],'plot':p['i'],'round':p['round']})
    if tg:
        st,b=await c.action(direct='qqStealAll',params={'targets':tg}); log(f'[qqStealAll {len(tg)}] '+brief(b))
async def connect():
    if not refresh(): raise RuntimeError('auth')
    url=f'wss://{HOST}/api/farm2d/farm/live'
    hdr={'Origin':ROOT,'User-Agent':'Mozilla/5.0','Cookie':cookie_header()}
    ws=await websockets.connect(url,max_size=2**22,open_timeout=15,additional_headers=hdr)
    c=C(ws)
    if not await c.auth(): raise RuntimeError('wsauth')
    return c
async def main(duration=7200, once=False):
    open(LOG,'w',encoding='utf-8').close()
    c=await connect(); log('WS connected. version='+str(c.version))
    if once:
        await play_pass(c); 
        stt=rest_state(); qv=stt['state']['qqView']; log(f"END level={qv['level']} lp={qv['levelProgress']}/{qv['levelRequired']} stars={stt['state']['stars']} coins={stt['state']['coins']}")
        await c.ws.close(); return
    t0=time.time(); cyc=0
    while time.time()-t0<duration:
        cyc+=1
        try:
            await play_pass(c)
        except Exception as e:
            log('pass error '+str(e)[:100])
            try: await c.ws.close()
            except: pass
            await asyncio.sleep(3)
            try: c=await connect(); log('reconnected v='+str(c.version))
            except Exception as e2: log('reconnect fail '+str(e2)[:80]); await asyncio.sleep(10); continue
        stt=rest_state()
        if stt:
            qv=stt['state']['qqView']; log(f"== c{cyc} level={qv['level']} lp={qv['levelProgress']}/{qv['levelRequired']} stars={stt['state']['stars']} coins={stt['state']['coins']}")
        await asyncio.sleep(35)
if __name__=='__main__':
    once = ('once' in sys.argv)
    dur = 7200
    for a in sys.argv:
        if a.isdigit(): dur=int(a)
    asyncio.run(main(duration=dur, once=once))
