import json, base64, os, time, uuid, urllib.request, urllib.error
d=r'D:\project\偷菜\_recon'; ROOT='https://www.0809.one'; UA='Mozilla/5.0'; CK='new_api_refresh'; TOK={'v':'','exp':0}
CKF=os.path.join(d,'mycookie_lllliii.txt')
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
        except Exception as e: last=str(e); time.sleep(1)
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
        if not dd0: return None,'nostate'
        ver=dd0['version']
        if kind=='direct': body={'action':name,'params':params,'request_id':f'farm:{name}:{uuid.uuid4()}','version':ver}
        else:
            cmd={'action':name}; cmd.update(params or {}); body={'action':'qq','params':{'command':cmd},'request_id':f'farm:qq:{uuid.uuid4()}','version':ver}
        st,dd,_=http('POST',ROOT+'/api/farm2d/farm/action',token=token(),body=body)
        ok=dd.get('success') if isinstance(dd,dict) else None
        msg=(dd.get('message') or dd.get('code')) if isinstance(dd,dict) else dd
        if ok: return True,msg
        if isinstance(dd,dict) and 'STALE' in str(dd.get('code','')): time.sleep(0.4); continue
        return False,msg
    return False,'gaveup'
import math
if not refresh(): print('authfail'); raise SystemExit
dd=getstate(); qv=dd['state']['qqView']
print('BEFORE level=',qv['level'],'lp=',qv['levelProgress'],'/',qv['levelRequired'],'stars=',dd['state']['stars'])
budget=110; spent=0
for i,p in enumerate(qv['plots']):
    if not p.get('cropId') or p.get('mature'): continue
    for _ in range(40):
        dd=getstate(); qv=dd['state']['qqView']; p=qv['plots'][i]
        if p.get('mature') or not p.get('cropId'): break
        rem=p.get('remaining') or 0
        if rem<=0: break
        need=math.ceil(rem/9000)
        if spent+3>budget: print('budget hit'); break
        ok1,_=act('buyFertilizer',{'fertilizerId':2,'stars':3,'confirm':True})
        if not ok1: print('buy fail plot',i); break
        ok2,_=act('fertilize',{'plot':i,'fertilizerId':2})
        spent+=3
        if not ok2: print('fert fail plot',i); break
    print(f' plot{i} after: mature={ (getstate()["state"]["qqView"]["plots"][i]).get("mature") } rem={(getstate()["state"]["qqView"]["plots"][i]).get("remaining")} spentStars={spent}')
    if spent+3>budget: break
ok,msg=act('harvestAll',{}); print('harvestAll ->',ok,str(msg)[:80])
dd=getstate(); qv=dd['state']['qqView']
print('AFTER level=',qv['level'],'lp=',qv['levelProgress'],'/',qv['levelRequired'],'stars=',dd['state']['stars'],'coins=',dd['state']['coins'],'spentStars=',spent)
ok,msg=act('sellAll',{}); print('sellAll ->',ok,str(msg)[:50])
dd=getstate(); print('final coins=',dd['state']['coins'],'stars=',dd['state']['stars'])
