import json, base64, os, time, uuid, urllib.request, urllib.error
d=r'D:\project\偷菜\_recon'; ROOT='https://www.0809.one'; UA='Mozilla/5.0'; CK='new_api_refresh'; TOK={'v':'','exp':0}
CKF=os.path.join(d,'mycookie_lllliii.txt')
LEGACY={'cai':71,'wheat':61,'berry':1,'carrot':3,'corn':4,'potato':5,'tomato':7,'pumpkin':10,'grape':13,'sun':145}
def jwt_exp(t):
    p=t.split('.')[1];p+='='*(-len(p)%4);return int(json.loads(base64.urlsafe_b64decode(p)).get('exp',0))
def http(m,u,token=None,body=None,cookie=None,tries=3):
    h={'Accept':'application/json','Content-Type':'application/json','Origin':ROOT,'User-Agent':UA}
    if token:h['Authorization']='Bearer '+token
    if cookie:h['Cookie']=CK+'='+cookie
    data=json.dumps(body).encode() if body is not None else None
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
        except Exception: time.sleep(1)
    return 0,{'error':'timeout'},[]
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
def act(name,params,kind='wrap',tag=''):
    for r in range(5):
        dd0=getstate()
        if not dd0: print(f'  [{tag}{name}] no state'); return False
        ver=dd0['version']
        if kind=='direct': body={'action':name,'params':params,'request_id':f'farm:{name}:{uuid.uuid4()}','version':ver}
        else:
            cmd={'action':name}; cmd.update(params or {}); body={'action':'qq','params':{'command':cmd},'request_id':f'farm:qq:{uuid.uuid4()}','version':ver}
        st,dd,_=http('POST',ROOT+'/api/farm2d/farm/action',token=token(),body=body)
        ok=dd.get('success') if isinstance(dd,dict) else None
        msg=(dd.get('message') or dd.get('code')) if isinstance(dd,dict) else dd
        if isinstance(dd,dict) and dd.get('data') and isinstance(dd['data'].get('result'),dict): msg=msg or dd['data']['result'].get('qqMessage')
        if ok: print(f'  [OK] [{tag}{name}] {json.dumps(params,ensure_ascii=False)[:50]} -> {str(msg)[:70]}'); return True
        if isinstance(dd,dict) and 'STALE' in str(dd.get('code','')): time.sleep(0.4); continue
        print(f'  [X] [{tag}{name}] {json.dumps(params,ensure_ascii=False)[:50]} -> {str(msg)[:70]}'); return False
    return False
if not refresh(): raise SystemExit
dd=getstate(); S=dd['state']; qv=S['qqView']
print('START level',qv['level'],'lp',qv['levelProgress'],'/',qv['levelRequired'],'stars',S['stars'],'coins',S['coins'])
print('== 每日/领取 玩法 ==')
act('checkIn',{},'direct','签到 ')
act('wish',{'kind':'coins'},'wrap','祈愿 ')
act('wish',{},'wrap','祈愿2 ')
act('claimAll',{},'direct','一键领取 ')
act('claimAllAchv',{},'direct','成就 ')
act('claimFieldTasks',{},'direct','丰收 ')
act('claimHoney',{},'wrap','蜂房 ')
act('claimVoyage',{},'wrap','远航 ')
act('welcome',{},'direct','新手金 ')
print('== 农田照料/清理 ==')
act('careAll',{},'wrap','照料 ')
act('waterAll',{},'wrap','浇水 ')
act('shovelAll',{},'wrap','清枯枝 ')
act('plantAll',{'cropId':59,'buyMissing':True,'confirm':True},'wrap','播种 ')
act('harvestAll',{},'wrap','收获 ')
act('sellAll',{},'wrap','卖菜 ')
print('== 村市(市场) ==')
village=(qv.get('village') or {}).get('offers') or []
wh=qv.get('warehouse') or {}
for off in village[:6]:
    oid=off.get('id'); kind=off.get('kind'); item=off.get('item'); have=int(wh.get(str(item),0) or 0)
    if kind=='crop' and have>0:
        act('marketSell',{'offer':oid,'amount':have},'wrap',f'卖市{oid} ')
    else:
        print(f'  · 村市 {oid} {off.get("name")} 价{off.get("price")} 余量{off.get("remaining")} 持有{have}(无货,暂不卖)')
print('== 订单委托 ==')
for i,o in enumerate(S.get('orders',[])):
    ok=True; need={}
    for dm in o.get('demands',[]):
        cr=dm.get('crop'); key=str(LEGACY.get(cr,cr)); have=int(wh.get(key,0) or 0)
        need[key]=need.get(key,0)+dm.get('qty',0)
        if have<dm.get('qty',0): ok=False
    if ok:
        act('completeOrder',{'slot':i,'order':o.get('id'),'allowReserved':False},'wrap',f'交单{o.get("id")} ')
    else:
        print(f'  · 订单{o.get("id")} 需{need} 仓库不足,跳过')
print('== 商会合同 ==')
act('acceptContract',{},'wrap','接合同 ')
act('completeContract',{},'wrap','交合同 ')
print('== 工坊/加工 ==')
act('buildWorkshop',{'workshop':'bakery'},'wrap','建面包坊 ')
act('claimProduction',{'workshop':'bakery'},'wrap','领成品 ')
print('== 资源/蜂房加工 ==')
act('compost',{'quantity':5},'wrap','花粉制肥 ')
dd=getstate(); S=dd['state']; qv=S['qqView']
print('END level',qv['level'],'lp',qv['levelProgress'],'/',qv['levelRequired'],'stars',S['stars'],'coins',S['coins'],'fert',json.dumps(qv.get('fertilizers'),ensure_ascii=False))
