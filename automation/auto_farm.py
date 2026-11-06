import json, base64, os, time, uuid, urllib.request, urllib.error
d=r'D:\project\偷菜\_recon'; ROOT='https://www.0809.one'; UA='Mozilla/5.0'; CK='new_api_refresh'; TOK={'v':'','exp':0}
CKF=os.path.join(d,'mycookie_lllliii.txt')
STATE=os.path.join(d,'..','results','farm_state.txt')
QQ=json.load(open(os.path.join(d,'qqcat.json'),encoding='utf-8'))
CROPS=QQ['crops']
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
def act(kind,name,params):
    dd0=getstate();
    if not dd0: return None,{'error':'no state'}
    version=dd0['version']
    if kind=='direct':
        body={'action':name,'params':params,'request_id':f'farm:{name}:{uuid.uuid4()}','version':version}
    else:
        cmd={'action':name}; cmd.update(params or {}); body={'action':'qq','params':{'command':cmd},'request_id':f'farm:qq:{uuid.uuid4()}','version':version}
    st,dd,_=http('POST',ROOT+'/api/farm2d/farm/action',token=token(),body=body)
    ok=dd.get('success') if isinstance(dd,dict) else None
    msg=(dd.get('message') or dd.get('code')) if isinstance(dd,dict) else dd
    return ok,msg
def total_grow(c):
    try:
        parts=[int(x) for x in str(c.get('cropGrow','')).split(',')[:5]]
        return sum(parts), parts
    except Exception:
        return 10**9,[]
def pick_crop(level):
    best=None
    for c in CROPS:
        if (c.get('lv') or 99)>level: continue
        if not (c.get('shopVisible') and c.get('shopCurrency')=='coins' and c.get('localArtComplete')): continue
        if (c.get('landRequirement') or 0)>0: continue
        g,parts=total_grow(c)
        if g<=0: continue
        if best is None or g<best[1]:
            best=(c['id'],g,c.get('name'),c.get('shopPrice'),parts)
    return best
def steal_neighbors():
    st,nb,_=http('GET',ROOT+'/api/farm2d/farm/neighbors',token=token())
    tg=[]
    if st==200 and isinstance(nb,dict) and nb.get('success'):
        for n in nb['data']['neighbors']:
            for p in n.get('plots',[]):
                if p.get('qq'): tg.append({'victim':n['user_id'],'plot':p['i'],'round':p['round']})
    if tg:
        ok,msg=act('direct','qqStealAll',{'targets':tg})
        return f'steal {len(tg)} -> {ok} {str(msg)[:40]}'
    return 'steal: no neighbor'
def main(duration=60, target=10):
    if not refresh(): print('refresh fail'); return
    dd=getstate(); qv=dd['state']['qqView']
    start_lp=qv['levelProgress']
    print(f"START level={qv['level']} lp={qv['levelProgress']}/{qv['levelRequired']} coins={dd['state']['coins']} stars={dd['state']['stars']}")
    t0=time.time(); cyc=0
    while time.time()-t0<duration:
        cyc+=1
        dd=getstate()
        if not dd: print('c no state'); time.sleep(3); continue
        qv=dd['state']['qqView']; level=qv['level']; lp=qv.get('levelProgress'); req=qv.get('levelRequired')
        print(f"[c{cyc}] level={level} lp={lp}/{req} coins={dd['state']['coins']} stars={dd['state']['stars']} plots={[(i,p.get('cropId'),p.get('mature'),p.get('remaining')) for i,p in enumerate(qv['plots'])]}")
        if level>=target:
            print('DONE level>=target'); break
        crop=pick_crop(level)
        fast_g = crop[1] if crop else 10**9
        # shovel 过慢作物(剩余 > 2x最快熟) 释放地块
        for i,p in enumerate(qv['plots']):
            if p.get('cropId') and (p.get('remaining') or 0) > max(fast_g*2,180):
                ok,msg=act('wrap','shovel',{'plot':i}); print(f'    shovel plot{i} rem={p.get("remaining")} -> {ok} {str(msg)[:30]}')
        if crop:
            ok,msg=act('wrap','plantAll',{'cropId':crop[0],'buyMissing':True,'confirm':True}); print(f'    plantAll id={crop[0]} ({crop[2]}) grow={crop[1]}s price={crop[3]} -> {ok} {str(msg)[:40]}')
        ok,msg=act('wrap','careAll',{}); print(f'    careAll -> {ok} {str(msg)[:30]}')
        ok,msg=act('wrap','harvestAll',{}); print(f'    harvestAll -> {ok} {str(msg)[:40]}')
        ok,msg=act('wrap','sellAll',{}); print(f'    sellAll -> {ok} {str(msg)[:30]}')
        if cyc%5==0:
            print('    ',steal_neighbors())
        if cyc%10==0:
            act('direct','claimAll',{}); act('direct','claimAllAchv',{})
        time.sleep(20)
    dd=getstate(); qv=dd['state']['qqView']
    print(f"END level={qv['level']} lp={qv['levelProgress']}/{qv['levelRequired']} (start lp {start_lp})")
if __name__=='__main__':
    import sys
    dur=int(sys.argv[1]) if len(sys.argv)>1 else 60
    main(duration=dur)
