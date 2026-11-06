import json, base64, os, time, uuid, urllib.request, urllib.error
d = r'D:\project\偷菜\_recon'
ROOT = 'https://www.0809.one'
UA = 'Mozilla/5.0'
CK = 'new_api_refresh'
TOK = {'v': '', 'exp': 0}
def jwt_exp(t):
    p = t.split('.')[1]; p += '=' * (-len(p) % 4)
    return int(json.loads(base64.urlsafe_b64decode(p)).get('exp', 0))
def http(method, url, token=None, body=None, cookie=None):
    h = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': ROOT, 'User-Agent': UA}
    if token: h['Authorization'] = 'Bearer ' + token
    if cookie: h['Cookie'] = CK + '=' + cookie
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode('utf-8', 'replace')
            return r.status, (json.loads(raw) if raw.strip().startswith(('{', '[')) else raw), (r.headers.get_all('Set-Cookie') or [])
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try: dd = json.loads(raw)
        except Exception: dd = raw
        return e.code, dd, (e.headers.get_all('Set-Cookie') or [])
    except Exception as e:
        return 0, {'error': str(e)}, []
def refresh():
    ck = open(os.path.join(d, 'mycookie.txt'), encoding='utf-8').read().strip()
    st, dd, sc = http('POST', ROOT + '/api/user/auth/refresh', cookie=ck, body={})
    if st == 200 and dd.get('success') and dd.get('data', {}).get('access_token'):
        for c in sc:
            if c.startswith(CK + '='):
                open(os.path.join(d, 'mycookie.txt'), 'w', encoding='utf-8').write(c.split(';', 1)[0].split('=', 1)[1].strip()); break
        TOK['v'] = dd['data']['access_token']; TOK['exp'] = jwt_exp(TOK['v']); return True
    return False
def token():
    if not TOK['v'] or TOK['exp'] - time.time() < 120:
        if not refresh(): raise RuntimeError('refresh fail')
    return TOK['v']
if not refresh(): print('auth fail'); raise SystemExit
start, end = 2801, 2900
counts = {}; targets = []
t0 = time.time()
for uid in range(start, end + 1):
    for attempt in range(5):
        try: tok = token()
        except Exception: tok = None
        st, g, _ = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={uid}', token=tok)
        if st == 401: refresh(); continue
        if st in (429, 0) or st >= 500: time.sleep(0.6 + attempt * 0.7); continue
        break
    if st == 200 and isinstance(g, dict) and g.get('success'):
        ps = g['data']['plots']
        tg = [{'victim': uid, 'plot': i, 'round': int(p['round'])} for i, p in enumerate(ps) if p.get('canSteal') is True and p.get('round')]
        counts['OPEN'] = counts.get('OPEN', 0) + 1; targets += tg
        print(f'  OPEN owner={uid} plots={len(ps)} canSteal={len(tg)}', flush=True)
    elif st == 403: counts['CLOSED'] = counts.get('CLOSED', 0) + 1
    elif st == 404: counts['GONE'] = counts.get('GONE', 0) + 1
    else: counts[f'HTTP{st}'] = counts.get(f'HTTP{st}', 0) + 1
    time.sleep(0.33)
print(f'[tail] {start}-{end} counts={counts} targets={len(targets)} {int(time.time()-t0)}s', flush=True)
if targets:
    st, s, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
    version = s['data']['version']; stars0 = s['data']['state']['stars']
    body = {'action': 'qqStealAll', 'params': {'targets': targets}, 'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
    st, r, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
    st2, s2, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
    print('[tail-steal]', st, json.dumps(r, ensure_ascii=False)[:300], 'stars', stars0, '->', s2['data']['state']['stars'], flush=True)
