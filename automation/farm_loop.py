import json, base64, os, time, uuid, urllib.request, urllib.error
d=r'D:\project\偷菜\_recon'; ROOT='https://www.0809.one'; UA='Mozilla/5.0'; CK='new_api_refresh'; TOK={'v':'','exp':0}
CKF=os.path.join(d,'mycookie_lllliii.txt')
LOG=os.path.join(d,'..','results','farm_loop.log')
def log(s):
    print(s,flush=True)
    try:
        open(LOG,'a',encoding='utf-8').write(str(s)+'\n')
    except: pass
def jwt_exp(t):
    p=t.split('.')[1];p+='='*(-len(p)%4);return int(json.loads(base64.urlsafe_b64decode(p)).get('exp',0))
def http(m,u,token=None,body=None,cookie=None,tries=4):
    h={'Accept':'application/json','Content-Type':'application/json','Origin':ROOT,'User-Agent':UA}
    if token:h['Authorization']='Bearer '+token
    if cookie:h['Cookie']=CK+'='+cookie
    data=json.dumps(body).encode() if body is not None else None
    last=''
    for a in range(tries):
        r=urllib.request.Request(u,data=data,headers=h,method=m)
        try:
            with urllib.request.urlopen(r,timeout=15) as x:
                raw=x.read().decode('utf-8','replace');return x.status,(json.loads(raw) if raw.strip().startswith(('{','[')) else raw),(x.headers.get_all('Set-Cookie') or [])
        except urllib.error.HTTPError as e:
            raw=e.read().decode('utf-8','replace')
            try:dd=json.loads(raw)
            except:dd=raw
            return e.code,dd,(e.headers.get_all('Set-Cookie') or [])
        except Exception as e: last=str(e); time.sleep(1.2)
    return 0,{'error':last},[]
def refresh():
    ck=open(CKF,encoding='utf-8').read().strip()
    for a in range(4):
        st,dd,sc=http('POST',ROOT+'/api/user/auth/refresh',cookie=ck,body={})
        if st==200 and dd.get('success') and dd.get('data',{}).get('access_token'):
            for c in sc:
                if c.startswith(CK+'='):open(CKF,'w',encoding='utf-8').write(c.split(';',1)[0].split('=',1)[1].strip());break
            TOK['v']=dd['data']['access_token'];TOK['exp']=jwt_exp(TOK['v']);return True
        time.sleep(2)
    return False
def token():
    if not TOK['v'] or TOK['exp']-time.time()<120:
        if not refresh():raise RuntimeError('auth')
    return TOK['v']
def getstate():
    st,s,_=http('GET',ROOT+'/api/farm2d/farm/state',token=token())
    return s['data'] if st==200 and s.get('success') else None
def act(name,params,kind='wrap'):
    for r in range(6):
        dd0=getstate()
        if not dd0: return None,'no state'
        ver=dd0['version']
        if kind=='direct': body={'action':name,'params':params,'request_id':f'farm:{name}:{uuid.uuid4()}','version':ver}
        else:
            cmd={'action':name}; cmd.update(params or {}); body={'action':'qq','params':{'command':cmd},'request_id':f'farm:qq:{uuid.uuid4()}','version':ver}
        st,dd,_=http('POST',ROOT+'/api/farm2d/farm/action',token=token(),body=body)
        ok=dd.get('success') if isinstance(dd,dict) else None
        msg=(dd.get('message') or dd.get('code')) if isinstance(dd,dict) else dd
        if isinstance(dd,dict) and dd.get('data') and isinstance(dd['data'].get('result'),dict): msg=msg or dd['data']['result'].get('qqMessage')
        if ok: return True,msg
        if isinstance(dd,dict) and 'STALE' in str(dd.get('code','')): time.sleep(0.4); continue
        return False,msg
    return False,'gaveup'
def steal():
    st,nb,_=http('GET',ROOT+'/api/farm2d/farm/neighbors',token=token())
    tg=[]
    if st==200 and isinstance(nb,dict) and nb.get('success'):
        for n in nb['data']['neighbors']:
            for p in n.get('plots',[]):
                if p.get('qq'): tg.append({'victim':n['user_id'],'plot':p['i'],'round':p['round']})
    if not tg: return 'no neighbor'
    ok,msg=act('qqStealAll',{'targets':tg},'direct'); return f'stole {len(tg)} -> {ok}'
def main(duration=7200,target=10):
    open(LOG,'w',encoding='utf-8').close()
    if not refresh(): log('refresh fail'); return
    dd=getstate(); qv=dd['state']['qqView']; log(f"START level={qv['level']} lp={qv['levelProgress']}/{qv['levelRequired']} stars={dd['state']['stars']} coins={dd['state']['coins']}")
    t0=time.time(); cyc=0
    while time.time()-t0<duration:
        cyc+=1
        dd=getstate()
        if not dd: log('no state'); time.sleep(4); continue
        qv=dd['state']['qqView']; level=qv['level']; lp=qv.get('levelProgress'); req=qv.get('levelRequired'); stars=dd['state']['stars']
        if cyc%3==1: log(f"[c{cyc}] lvl={level} lp={lp}/{req} stars={stars} coins={dd['state']['coins']} plots={[(i,p.get('cropId'),p.get('mature'),p.get('remaining')) for i,p in enumerate(qv['plots'])]}")
        if level>=target: log(f'DONE level={level}'); return
        # harvest
        ok,msg=act('harvestAll',{}); 
        if ok: log(f'  harvest: {str(msg)[:70]}')
        act('sellAll',{})
        if cyc%8==0:
            act('claimAll',{},'direct'); act('claimAllAchv',{},'direct'); act('claimFieldTasks',{},'direct')
            act('wish',{},'wrap'); act('compost',{'quantity':5},'wrap')
            # 交可完成的订单
            for i,o in enumerate((getstate() or {}).get('state',{}).get('orders',[])):
                pass
        # 只对快熟(<=9000s=2.5h)地块用便宜化肥收尾(正收益), 且保底星
        for i,p in enumerate(qv['plots']):
            if p.get('cropId') and not p.get('mature') and 0 < (p.get('remaining') or 0) <= 9000 and stars>80:
                o1,_=act('buyFertilizer',{'fertilizerId':2,'stars':3,'confirm':True})
                o2,_=act('fertilize',{'plot':i,'fertilizerId':2})
                if o1 and o2: log(f'  finish plot{i} rem={p.get("remaining")} (fert)'); stars-=3
        # 清理 + 播种(空/枯枝地块)
        act('careAll',{}); act('shovelAll',{})
        dd2=getstate()
        if dd2:
            qv2=dd2['state']['qqView']; empt=[i for i,p in enumerate(qv2['plots']) if not p.get('cropId')]
            if empt:
                ok,msg=act('plantAll',{'cropId':59,'buyMissing':True,'confirm':True}); log(f'  plant {len(empt)} empties -> {ok} {str(msg)[:30]}')
        if cyc%4==0: log('  '+steal())
        time.sleep(30)
    dd=getstate(); qv=dd['state']['qqView']; log(f"END level={qv['level']} lp={qv['levelProgress']}/{qv['levelRequired']} stars={dd['state']['stars']}")
if __name__=='__main__':
    import sys; main(duration=int(sys.argv[1]) if len(sys.argv)>1 else 7200)
