#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高频连采: 快速轮询 /farm/neighbors(含关闭邻居, 带round) -> 立即 qqStealAll;
每10轮叠加 11 个开放花园的 canSteal 熟地块。滚动池来一个偷一个, 尽量覆盖所有可偷用户。"""
import argparse, base64, json, os, time, uuid, threading, urllib.request, urllib.error

CK = 'new_api_refresh'; UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'
ROOT = ''; COOKIE_FILE = ''; STATE_FILE = ''
TOK = {'v': '', 'exp': 0}; LK = threading.Lock()
_rl = threading.Lock(); _last = [0.0]; MIN_GAP = 0.4
OPEN_IDS = [1345, 1350, 1369, 1380, 1524, 1632, 1692, 1694, 1816, 1991, 2405]

def rate_wait():
    with _rl:
        g = time.time() - _last[0]
        if g < MIN_GAP: time.sleep(MIN_GAP - g)
        _last[0] = time.time()
def jwt_exp(t):
    p = t.split('.')[1]; p += '=' * (-len(p) % 4)
    return int(json.loads(base64.urlsafe_b64decode(p)).get('exp', 0))
def http(method, url, token=None, body=None, cookie=None, timeout=20):
    h = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': ROOT, 'User-Agent': UA}
    if token: h['Authorization'] = 'Bearer ' + token
    if cookie: h['Cookie'] = CK + '=' + cookie
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
    with LK:
        last = ''
        for attempt in range(5):
            try:
                ck = open(COOKIE_FILE, encoding='utf-8').read().strip()
                st, dd, sc = http('POST', ROOT + '/api/user/auth/refresh', cookie=ck, body={})
                if st == 200 and isinstance(dd, dict) and dd.get('success') and dd.get('data', {}).get('access_token'):
                    for c in sc:
                        if c.startswith(CK + '='):
                            open(COOKIE_FILE, 'w', encoding='utf-8').write(c.split(';', 1)[0].split('=', 1)[1].strip()); break
                    TOK['v'] = dd['data']['access_token']; TOK['exp'] = jwt_exp(TOK['v']); return True
                last = f'{st} {str(dd)[:100]}'
            except Exception as e:
                last = str(e)
            time.sleep(2 + attempt * 2)
        print('[auth] refresh failed after retries:', last, flush=True); return False
def token(force=False):
    if force or not TOK['v'] or TOK['exp'] - time.time() < 120:
        if not refresh(): raise RuntimeError('auth')
    return TOK['v']
def get_state():
    for _ in range(3):
        rate_wait()
        st, d, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
        if st == 401: token(True); continue
        if st == 200 and isinstance(d, dict) and d.get('success'): return d['data']['state']['stars'], d['data']['version']
        time.sleep(0.5)
    return None, None
def neighbors_targets():
    rate_wait()
    st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    if st == 401: token(True); rate_wait(); st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    ts = []
    if st == 200 and isinstance(d, dict) and d.get('success'):
        for n in d['data']['neighbors']:
            for p in n.get('plots', []):
                if p.get('qq'): ts.append({'victim': n['user_id'], 'plot': p['i'], 'round': p['round']})
    return ts
def garden_targets():
    ts = []
    for oid in OPEN_IDS:
        rate_wait()
        st, g, _ = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={oid}', token=token())
        if st == 401: token(True); continue
        if st == 200 and isinstance(g, dict) and g.get('success'):
            for i, p in enumerate(g['data'].get('plots', [])):
                if p.get('canSteal') is True and p.get('round'): ts.append({'victim': oid, 'plot': i, 'round': int(p['round'])})
    return ts
def steal(targets, version, chunk=80):
    stars = None
    for i in range(0, len(targets), chunk):
        batch = targets[i:i + chunk]
        body = {'action': 'qqStealAll', 'params': {'targets': batch}, 'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
        rate_wait()
        st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
        if st == 401: token(True); st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
        if st == 200 and isinstance(d, dict) and d.get('success'):
            res = d['data']['result']; version = d['data'].get('version', version); stars = d['data']['state']['stars']
            yield ('ok', len(res.get('steals', [])), len(res.get('blockedPlots', [])), stars)
        elif st == 409:
            ns, nv = get_state()
            if nv: version = nv
            yield ('stale', 0, 0, ns)
        else:
            yield (f'http{st}', 0, 0, stars)
        time.sleep(0.2)
    return

def wstate(stars, version, note=''):
    try:
        json.dump({'ts': int(time.time()*1000), 'time': time.strftime('%H:%M:%S'), 'stars': stars, 'version': version, 'note': note}, open(STATE_FILE, 'w', encoding='utf-8'))
    except Exception: pass

def main():
    global ROOT, COOKIE_FILE, STATE_FILE, MIN_GAP
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True); ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--target', type=int, default=500); ap.add_argument('--duration', type=int, default=3600)
    ap.add_argument('--gap', type=float, default=0.4); ap.add_argument('--idle', type=float, default=2.0)
    ap.add_argument('--state-file', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', 'steal_state.json'))
    args = ap.parse_args()
    ROOT = args.root.rstrip('/'); COOKIE_FILE = args.cookie_file; STATE_FILE = args.state_file; MIN_GAP = args.gap
    if not refresh(): raise SystemExit(2)
    stars, version = get_state()
    if stars is None: print('[state] fail', flush=True); raise SystemExit(3)
    start = stars; print(f'[start] stars={stars} version={version} target={args.target}', flush=True)
    t0 = time.time(); cyc = 0; got = 0
    while time.time() - t0 < args.duration:
        cyc += 1
        ts = neighbors_targets()
        if cyc % 10 == 0: ts += garden_targets()
        seen = set(); ded = []
        for t in ts:
            k = (t['victim'], t['plot'])
            if k not in seen: seen.add(k); ded.append(t)
        if ded:
            for kind, nS, nB, ns in steal(ded, version):
                if ns is not None: stars = ns; version = version
                print(f'[steal] c{cyc} sent={len(ded)} {kind} stolen={nS} blocked={nB} stars={stars}', flush=True)
            wstate(stars, version)
            if stars is not None and stars >= args.target:
                print(f'[DONE] stars={stars} >= {args.target}', flush=True); wstate(stars, version, 'DONE'); return
        else:
            if cyc % 5 == 1:
                ns, nv = get_state()
                if ns is not None: stars = ns; version = nv
                wstate(stars, version)
                print(f'[wait] c{cyc} stars={stars} 无邻居可偷, idle {args.idle}s', flush=True)
            time.sleep(args.idle)
        if cyc % 30 == 0:
            wstate(stars, version)
    ns, nv = get_state()
    print(f'[end] stars={ns} (+{(ns-start) if ns is not None else "?"})', flush=True); wstate(ns, nv, 'END')

if __name__ == '__main__':
    main()
