import json, base64, os, time, uuid, urllib.request, urllib.error
d = r'D:\project\偷菜\_recon'
ROOT = 'https://www.0809.one'
UA = 'Mozilla/5.0'; CK = 'new_api_refresh'; TOK = {'v': '', 'exp': 0}
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
st, s, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
print('BEFORE stars=', s['data']['state']['stars'], 'version=', s['data']['version'])
st, nb, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
neigh = nb['data']['neighbors']
print('neighbors=', len(neigh))
targets = []
for n in neigh:
    for p in n.get('plots', []):
        if p.get('qq'):
            targets.append({'victim': n['user_id'], 'plot': p['i'], 'round': p['round']})
    print('  neighbor', n['user_id'], 'gardenOpen=', n.get('gardenOpen'), 'qq_plots=', sum(1 for p in n.get('plots', []) if p.get('qq')))
if targets:
    version = s['data']['version']
    body = {'action': 'qqStealAll', 'params': {'targets': targets}, 'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
    st, r, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
    print('steal HTTP', st, 'resp', json.dumps(r, ensure_ascii=False)[:400])
st, s2, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
print('AFTER stars=', s2['data']['state']['stars'], 'version=', s2['data']['version'])
