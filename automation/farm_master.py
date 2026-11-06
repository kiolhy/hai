import json, base64, os, glob, time, uuid, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
d=r'D:\project\偷菜\_recon'; ROOT='https://www.0809.one'; UA='Mozilla/5.0'; CK='new_api_refresh'
CKF=os.path.join(d,'mycookie_lllliii.txt'); OUT=os.path.join(d,'..','results'); LOG=os.path.join(OUT,'farm_master.log')
ME=1692
TOK={'v':'','exp':0}; TLOCK=threading.Lock()
RL=threading.Lock(); _last=[0.0]; GAP=0.3
def log(s):
    line=time.strftime('%H:%M:%S ')+str(s); print(line,flush=True)
    try: open(LOG,'a',encoding='utf-8').write(line+'\n')
    except: pass
def jwt_exp(t):
    p=t.split('.')[1];p+='='*(-len(p)%4);return int(json.loads(base64.urlsafe_b64decode(p)).get('exp',0))
def rate():
    with RL:
        g=time.time()-_last[0]
        if g<GAP: time.sleep(GAP-g)
        _last[0]=time.time()
def http(m,u,token=None,body=None,cookie=None,tries=3):
    h={'Accept':'application/json','Content-Type':'application/json','Origin':ROOT,'User-Agent':UA}
    if token:h['Authorization']='Bearer '+token
    if cookie:h['Cookie']=CK+'='+cookie
    data=json.dumps(body).encode() if body is not None else None
    last=''
    for a in range(tries):
        rate()
        r=urllib.request.Request(u,data=data,headers=h,method=m)
        try:
            with urllib.request.urlopen(r,timeout=15) as x:
                raw=x.read().decode('utf-8','replace');return x.status,(json.loads(raw) if raw.strip().startswith(('{','[')) else raw),(x.headers.get_all('Set-Cookie') or [])
        except urllib.error.HTTPError as e:
            raw=e.read().decode('utf-8','replace')
            try:dd=json.loads(raw)
            except:dd=raw
            return e.code,dd,(e.headers.get_all('Set-Cookie') or [])
        except Exception as e: last=str(e); time.sleep(1)
    return 0,{'error':last},[]
def refresh():
    with TLOCK:
        ck=open(CKF,encoding='utf-8').read().strip()
        for a in range(3):
            st,dd,sc=http('POST',ROOT+'/api/user/auth/refresh',cookie=ck,body={})
            if st==200 and dd.get('success') and dd.get('data',{}).get('access_token'):
                for c in sc:
                    if c.startswith(CK+'='):open(CKF,'w',encoding='utf-8').write(c.split(';',1)[0].split('=',1)[1].strip());break
                TOK['v']=dd['data']['access_token'];TOK['exp']=jwt_exp(TOK['v']);return True
            time.sleep(2)
        return False
def token(force=False):
    with TLOCK:
        v=TOK['v']; e=TOK['exp']
    if force or not v or e-time.time()<120:
        if not refresh(): raise RuntimeError('auth')
    return TOK['v']
_THEFTS=[]; _STEAL_LOG=[]
def fetch_history(tok):
    global _THEFTS,_STEAL_LOG
    try:
        st,lg,_=http('GET',ROOT+'/api/farm2d/farm/log?limit=30',token=tok)
        if st==200 and isinstance(lg,dict) and lg.get('success'):
            sl=[]
            for row in lg['data'].get('log',[]):
                if 'Steal' in str(row.get('action')):
                    det=row.get('detail',{}) or {}
                    sl.append({'ts':row.get('ts'),'action':row.get('action'),'stolen':len(det.get('steals',[]) or []),'blocked':len(det.get('blockedPlots',[]) or []),'skipped':len(det.get('skippedPlots',[]) or []),'stars':det.get('stars',0)})
            _STEAL_LOG=sl[:12]
        st2,tf,_=http('GET',ROOT+'/api/farm2d/farm/thefts?limit=30',token=tok)
        if st2==200 and isinstance(tf,dict) and tf.get('success'):
            _THEFTS=(tf.get('data',{}).get('thefts',[]) or [])[:20]
    except Exception: pass
def _live_dump(d):
    try:
        stt=d['state']; qv=stt.get('qqView',{}); s1=stt.get('stats',{}) or {}; sl=stt.get('steal',{}) or {}; pl=qv.get('plots',[])
        plots=[{'i':i,'cropId':p.get('cropId'),'mature':p.get('mature'),'remaining':p.get('remaining'),'stage':p.get('stageName'),'weed':p.get('weed'),'pest':p.get('pest'),'humidity':p.get('humidity')} for i,p in enumerate(pl)]
        live={'ts':int(time.time()),'level':qv.get('level'),'levelProgress':qv.get('levelProgress'),'levelRequired':qv.get('levelRequired'),'stars':stt.get('stars'),'coins':stt.get('coins'),'steals_total':s1.get('steals'),'steal_today':sl.get('count'),'harvests':s1.get('harvests'),'planted':s1.get('planted'),'orders_done':s1.get('ordersDone'),'plots_count':len(pl),'mature_count':sum(1 for p in pl if p.get('mature')),'plots':plots,'orders':stt.get('orders',[]),'tasks':stt.get('fieldTasks'),'thefts':_THEFTS,'steal_log':_STEAL_LOG}
        open(os.path.join(OUT,'farm_live.json'),'w',encoding='utf-8').write(json.dumps(live,ensure_ascii=False))
    except Exception: pass
def getstate():
    st,s,_=http('GET',ROOT+'/api/farm2d/farm/state',token=token())
    if st==401: token(True); st,s,_=http('GET',ROOT+'/api/farm2d/farm/state',token=token())
    if st==200 and s.get('success'):
        _live_dump(s['data']); return s['data']
    return None
def act(name,params,kind='wrap'):
    for r in range(5):
        dd0=getstate()
        if not dd0: return False,'nostate'
        ver=dd0['version']
        if kind=='direct': body={'action':name,'params':params,'request_id':f'farm:{name}:{uuid.uuid4()}','version':ver}
        else:
            cmd={'action':name}; cmd.update(params or {}); body={'action':'qq','params':{'command':cmd},'request_id':f'farm:qq:{uuid.uuid4()}','version':ver}
        st,dd,_=http('POST',ROOT+'/api/farm2d/farm/action',token=token(),body=body)
        if st==401: token(True); continue
        ok=dd.get('success') if isinstance(dd,dict) else None
        msg=(dd.get('message') or dd.get('code')) if isinstance(dd,dict) else dd
        if isinstance(dd,dict) and dd.get('data') and isinstance(dd['data'].get('result'),dict): msg=msg or dd['data']['result'].get('qqMessage')
        if ok: return True,msg
        if isinstance(dd,dict) and 'STALE' in str(dd.get('code','')): time.sleep(0.3); continue
        return False,msg
    return False,'gaveup'
# ---- known GONE ids (skip in scan) ----
GONE=set()
for f in glob.glob(os.path.join(OUT,'scan*.json')):
    try:
        j=json.load(open(f,encoding='utf-8'))
        for r in j.get('results',[]):
            if r.get('status') in ('GONE','NOTFOUND'): GONE.add(r['id'])
    except Exception: pass
SCAN_IDS=[i for i in range(1,2901) if i not in GONE and i!=ME]
CUR=[0]
def spend():
    # 每日金币化肥(限6)。注意: village 补给包(小麦650→10麦≈96币)是亏本，勿买。
    bought=0
    for i in range(6):
        ok,msg=act('marketBuy',{'offer':'fertilizer'},'wrap')
        if ok: bought+=1
        else: break
    log(f'[spend] 金币化肥x{bought} (不买补给包:亏本)')
def use_fert(dd):
    qv=dd['state']['qqView']
    for i,p in enumerate(qv['plots']):
        if p.get('cropId') and not p.get('mature') and 0 < (p.get('remaining') or 0) <= 9000:
            act('fertilize',{'plot':i,'fertilizerId':2},'wrap')
def farm_pass():
    dd=getstate()
    if not dd: log('farm nostate'); return
    qv=dd['state']['qqView']
    act('careAll',{})
    use_fert(dd)
    ok,msg=act('harvestAll',{}); 
    act('sellAll',{})
    act('plantAll',{'cropId':59,'buyMissing':True,'confirm':True},'wrap')
    act('claimAll',{},'direct'); act('claimAllAchv',{},'direct'); act('claimFieldTasks',{},'direct')
    try: fetch_history(token())
    except Exception: pass
    dd=getstate()
    if dd:
        qv=dd['state']['qqView']; log(f'[farm] lvl={qv["level"]} lp={qv["levelProgress"]}/{qv["levelRequired"]} stars={dd["state"]["stars"]} coins={dd["state"]["coins"]} plots={[(i,p.get("cropId"),p.get("mature"),p.get("remaining")) for i,p in enumerate(qv["plots"])]}')
def steal_neighbors():
    st,nb,_=http('GET',ROOT+'/api/farm2d/farm/neighbors',token=token())
    tg=[]
    if st==200 and isinstance(nb,dict) and nb.get('success'):
        for n in nb['data']['neighbors']:
            for p in n.get('plots',[]):
                if p.get('qq'): tg.append({'victim':n['user_id'],'plot':p['i'],'round':p['round']})
    if tg:
        ok,msg=act('qqStealAll',{'targets':tg},'direct'); log(f'[steal-neigh] {len(tg)} -> {ok} {str(msg)[:30]}')
def scan_batch(n=40):
    global CUR
    start=CUR[0]; ids=[]
    i=start
    while len(ids)<n and i<len(SCAN_IDS):
        ids.append(SCAN_IDS[i]); i+=1
    CUR[0]=i
    if CUR[0]>=len(SCAN_IDS): CUR[0]=0
    def rd(uid):
        st,g,_=http('GET',ROOT+f'/api/farm2d/farm/qq/garden?owner={uid}',token=token())
        if st==200 and isinstance(g,dict) and g.get('success'):
            return [{'victim':uid,'plot':k,'round':int(p['round'])} for k,p in enumerate(g['data'].get('plots',[])) if p.get('canSteal') is True and p.get('round')]
        return []
    tg=[]
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r in ex.map(rd, ids):
            tg.extend(r)
    if tg:
        ok,msg=act('qqStealAll',{'targets':tg},'direct'); log(f'[steal-scan {start}..] found {len(tg)} -> {ok}')
def steal_loop(stop, duration):
    t0=time.time()
    while not stop.is_set() and time.time()-t0<duration:
        try:
            steal_neighbors(); scan_batch(40)
        except Exception as e:
            log('steal err '+str(e)[:80])
        time.sleep(6)
# ---- WebSocket 实时动态监听（接入唯一会话，捕获 /farm/live 所有推送）----
WS={'connected':False,'since':int(time.time()),'last_ts':0,'counts':{},'recent':[],'latest':{}}
WSLOCK=threading.Lock()
def _extract(d):
    try:
        st=d['state'];qv=st.get('qqView',{});s1=st.get('stats',{}) or {};sl=st.get('steal',{}) or {}
        return {'level':qv.get('level'),'levelProgress':qv.get('levelProgress'),'stars':st.get('stars'),'coins':st.get('coins'),'steals_total':s1.get('steals'),'steal_today':sl.get('count')}
    except Exception: return {}
def _summ(t,m):
    d=m.get('data')
    try:
        if t=='reply':
            b=m.get('body') or {};return ('ok' if b.get('success') else ('fail '+(str(b.get('code')) if isinstance(b,dict) else '')))
        if t in ('snapshot','patch') and isinstance(d,dict): return 'v=%s'%d.get('version')
        if t=='neighbors' and isinstance(d,dict): return 'neighbors=%d'%len(d.get('neighbors',[]) or [])
        if t=='balance': return 'balance'
    except Exception: pass
    return ''
def _ws_on_frame(m):
    t=m.get('type');d=m.get('data')
    with WSLOCK:
        WS['connected']=True;WS['last_ts']=int(time.time())
        WS['counts'][t]=WS['counts'].get(t,0)+1
        if isinstance(d,dict) and isinstance(d.get('state'),dict):
            try:WS['latest']=_extract(d)
            except Exception:pass
        ev={'ts':int(time.time()),'type':t,'sum':_summ(t,m)}
        WS['recent'].append(ev);WS['recent']=WS['recent'][-60:]
        try:open(os.path.join(OUT,'ws_status.json'),'w',encoding='utf-8').write(json.dumps(WS,ensure_ascii=False))
        except Exception:pass
        try:open(os.path.join(OUT,'ws_events.jsonl'),'a',encoding='utf-8').write(json.dumps(ev,ensure_ascii=False)+'\n')
        except Exception:pass
def ws_listener():
    import asyncio,websockets
    async def one():
        tok=token();ck=open(CKF,encoding='utf-8').read().strip()
        hdr={'Origin':ROOT,'User-Agent':UA,'Cookie':CK+'='+ck}
        async with websockets.connect('wss://www.0809.one/api/farm2d/farm/live',max_size=2**22,open_timeout=15,additional_headers=hdr) as ws:
            await ws.send(json.dumps({'type':'auth','token':tok,'expectExisting':True}))
            log('[ws] connected')
            while True:
                m=json.loads(await asyncio.wait_for(ws.recv(),timeout=90));_ws_on_frame(m)
    def run():
        attempt=0
        while True:
            try:
                asyncio.run(one()); attempt=0
            except Exception as e:
                with WSLOCK:WS['connected']=False
                attempt=min(attempt+1,6); d=min(60,5*(2**attempt))
                log('[ws] err '+str(e)[:70]+(' | retry %ds'%d));time.sleep(d)
    threading.Thread(target=run,daemon=True).start()
PROBE_CUR=[0]; PROBE={'ts':0,'attempts':0,'confirmed':False,'last':None}
def _write_probe():
    try: open(os.path.join(OUT,'round_probe.json'),'w',encoding='utf-8').write(json.dumps(PROBE,ensure_ascii=False))
    except Exception: pass
    try:
        if PROBE.get('last'): open(os.path.join(OUT,'round_probe.jsonl'),'a',encoding='utf-8').write(json.dumps(PROBE['last'],ensure_ascii=False)+'\n')
    except Exception: pass
def round_probe_once():
    ids=[]; i=PROBE_CUR[0]
    for _ in range(60):
        if i>=len(SCAN_IDS): i=0
        ids.append(SCAN_IDS[i]); i+=1
    PROBE_CUR[0]=i
    tok=token(); found=[]
    for uid in ids:
        st,g,_=http('GET',ROOT+f'/api/farm2d/farm/qq/garden?owner={uid}',token=tok)
        if st==200 and isinstance(g,dict) and g.get('success'):
            data=g.get('data') or {}
            for p in (data.get('plots') or []):
                if p.get('canSteal'):
                    found.append({'victim':uid,'plot':p.get('i'),'round':p.get('round'),'open':data.get('gardenOpen')}); break
        if found: break
    PROBE['ts']=int(time.time())
    if not found:
        PROBE['last']={'ts':int(time.time()),'result':'no_ripe_target'}; _write_probe(); log('[probe] no ripe target in batch'); return
    t=found[0]
    ok,msg=act('qqStealAll',{'targets':[{'victim':t['victim'],'plot':t['plot'],'round':1}]},'direct')
    bypass=False
    try:
        det=json.loads(msg) if isinstance(msg,str) and msg.strip().startswith('{') else {}
        bypass=bool(det.get('steals'))
    except Exception: pass
    PROBE['attempts']=PROBE.get('attempts',0)+1
    PROBE['last']={'ts':int(time.time()),'target':t,'forged_round':1,'ok':ok,'msg':str(msg)[:200],'bypass':bypass}
    if bypass:
        PROBE['confirmed']=True; log('[probe] BYPASS CONFIRMED victim=%s plot=%s'%(t['victim'],t['plot']))
    else:
        log('[probe] forged round failed: '+str(msg)[:100])
        try: act('qqStealAll',{'targets':[{'victim':t['victim'],'plot':t['plot'],'round':t.get('round')}]},'direct')
        except Exception: pass
    _write_probe()
def probe_loop():
    time.sleep(20)
    while True:
        try: round_probe_once()
        except Exception as e: log('[probe] err '+str(e)[:80])
        time.sleep(40)
def main(duration=7200):
    open(LOG,'w',encoding='utf-8').close()
    if not refresh(): log('auth fail'); return
    log(f'START scan_pool={len(SCAN_IDS)}')
    threading.Thread(target=ws_listener,daemon=True).start()
    threading.Thread(target=probe_loop,daemon=True).start()
    spend()
    stop=threading.Event()
    th=threading.Thread(target=steal_loop,args=(stop,duration),daemon=True); th.start()
    t0=time.time(); cyc=0
    while time.time()-t0<duration:
        cyc+=1
        try: farm_pass()
        except Exception as e: log('farm err '+str(e)[:80])
        time.sleep(25)
    stop.set()
if __name__=='__main__':
    import sys
    dur=int(sys.argv[1]) if len(sys.argv)>1 and sys.argv[1].isdigit() else 7200
    main(duration=dur)
