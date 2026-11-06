#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动全站狩猎：扫 owner=START..END 的开放花园 canSteal 熟地块 + 邻居 qq 地块 -> 批量偷。
跳过已知 GONE(无农场) 的 ID 以提速。带全局限速、409 版本刷新、幂等 request_id。"""
import argparse, base64, glob, json, os, time, uuid, threading
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

CK = 'new_api_refresh'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'
ROOT = ''; COOKIE_FILE = ''
TOK = {'v': '', 'exp': 0}
LK = threading.Lock()
_rl = threading.Lock(); _last = [0.0]; MIN_GAP = 0.33
STAT = {'open': 0, 'closed': 0, 'gone': 0, 'else': 0}

def rate_wait():
    with _rl:
        now = time.time(); g = now - _last[0]
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
    ck = open(COOKIE_FILE, encoding='utf-8').read().strip()
    st, dd, sc = http('POST', ROOT + '/api/user/auth/refresh', cookie=ck, body={})
    if st == 200 and isinstance(dd, dict) and dd.get('success') and dd.get('data', {}).get('access_token'):
        for c in sc:
            if c.startswith(CK + '='):
                open(COOKIE_FILE, 'w', encoding='utf-8').write(c.split(';', 1)[0].split('=', 1)[1].strip()); break
        TOK['v'] = dd['data']['access_token']; TOK['exp'] = jwt_exp(TOK['v']); return True
    print('[auth] refresh failed', st, str(dd)[:140], flush=True); return False
def token(force=False):
    with LK:
        if force or not TOK['v'] or TOK['exp'] - time.time() < 120:
            if not refresh(): raise RuntimeError('auth')
        return TOK['v']
def get_state():
    for _ in range(3):
        st, d, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
        if st == 401: token(True); continue
        if st == 200 and isinstance(d, dict) and d.get('success'):
            return d['data']['state']['stars'], d['data']['version']
        time.sleep(1)
    return None, None
def scan_garden(uid, own):
    for _ in range(3):
        rate_wait()
        try: tok = token()
        except Exception: return (uid, 'AUTH', [])
        st, d, _ = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={uid}', token=tok)
        if st == 401: token(True); continue
        if st in (429, 0) or st >= 500: time.sleep(0.8); continue
        if st == 200 and isinstance(d, dict) and d.get('success'):
            if uid == own: return (uid, 'SELF', [])
            tg = [{'victim': uid, 'plot': i, 'round': int(p['round'])} for i, p in enumerate(d['data'].get('plots', [])) if p.get('canSteal') is True and p.get('round')]
            return (uid, 'OPEN', tg)
        if st == 403: return (uid, 'CLOSED', [])
        if st == 404: return (uid, 'GONE', [])
        return (uid, f'HTTP{st}', [])
    return (uid, 'GAVEUP', [])
def neighbors_targets():
    st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    if st == 401: token(True); st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    ts = []
    if st == 200 and isinstance(d, dict) and d.get('success'):
        for n in d['data']['neighbors']:
            for p in n.get('plots', []):
                if p.get('qq'): ts.append({'victim': n['user_id'], 'plot': p['i'], 'round': p['round']})
    return ts
def steal_all(targets, chunk):
    seen = set(); ded = []
    for t in targets:
        k = (t['victim'], t['plot'])
        if k not in seen: seen.add(k); ded.append(t)
    stars, version = get_state()
    print(f'[steal] 去重后目标 {len(ded)} 个, 起始 stars={stars} version={version}', flush=True)
    steals = 0
    for i in range(0, len(ded), chunk):
        batch = ded[i:i + chunk]
        body = {'action': 'qqStealAll', 'params': {'targets': [{'victim': t['victim'], 'plot': t['plot'], 'round': t['round']} for t in batch]},
                'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
        st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
        if st == 401: token(True); st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
        if st == 200 and isinstance(d, dict) and d.get('success'):
            res = d['data']['result']; nS = len(res.get('steals', [])); nB = len(res.get('blockedPlots', []))
            stars = d['data']['state']['stars']; version = d['data'].get('version', version); steals += nS
            print(f'[steal] batch{i//chunk+1} sent={len(batch)} stolen={nS} blocked={nB} stars={stars}', flush=True)
        elif st == 409:
            ns, version = get_state(); stars = ns if ns is not None else stars
            print(f'[steal] batch{i//chunk+1} 409 STALE, 刷新 version={version} stars={stars}', flush=True)
            time.sleep(0.5)
            # 重试本批一次
            body['version'] = version
            st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
            if st == 200 and isinstance(d, dict) and d.get('success'):
                res = d['data']['result']; nS = len(res.get('steals', [])); stars = d['data']['state']['stars']; version = d['data'].get('version', version); steals += nS
                print(f'[steal] retry ok stolen={nS} stars={stars}', flush=True)
        else:
            print(f'[steal] batch{i//chunk+1} HTTP{st} {str(d)[:100]}', flush=True)
        time.sleep(0.4)
    ns, _ = get_state()
    if ns is not None: stars = ns
    print(f'[steal] 完成 本批偷取={steals} 当前 stars={stars}', flush=True)
    return stars, ded

def main():
    global ROOT, COOKIE_FILE, MIN_GAP
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True); ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--start', type=int, default=1); ap.add_argument('--end', type=int, default=2900)
    ap.add_argument('--threads', type=int, default=5); ap.add_argument('--gap', type=float, default=0.33)
    ap.add_argument('--chunk', type=int, default=80)
    ap.add_argument('--outdir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results'))
    args = ap.parse_args()
    ROOT = args.root.rstrip('/'); COOKIE_FILE = args.cookie_file; MIN_GAP = args.gap
    if not refresh(): raise SystemExit(2)
    me = None
    st, b, _ = http('GET', ROOT + '/api/farm2d/balance', token=token())
    if st == 200 and b.get('success'): me = b['data'].get('user_id')
    print(f'[init] me={me}', flush=True)

    # 已知 GONE 跳过
    gone = set(); removed_other = set()
    for f in glob.glob(os.path.join(args.outdir, 'scan*.json')):
        try:
            j = json.load(open(f, encoding='utf-8'))
            for r in j.get('results', []):
                if r.get('status') in ('GONE', 'NOTFOUND'): gone.add(r['id'])
        except Exception: pass
    ids = [i for i in range(args.start, args.end + 1) if i not in gone and i != me]
    print(f'[scan] 全站 {args.start}-{args.end}, 跳过已知无农场 {len(gone)}, 待扫 {len(ids)}', flush=True)

    targets = neighbors_targets()
    print(f'[scan] 邻居可偷 {len(targets)} 个', flush=True)
    t0 = time.time(); n = 0
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = [ex.submit(scan_garden, uid, me) for uid in ids]
        for fut in as_completed(futs):
            uid, status, tg = fut.result(); n += 1
            if status == 'OPEN':
                STAT['open'] += 1; targets.extend(tg)
                if tg: print(f'  OPEN owner={uid} canSteal={len(tg)}', flush=True)
            elif status == 'CLOSED': STAT['closed'] += 1
            elif status == 'GONE': STAT['gone'] += 1
            else: STAT['else'] += 1
            if n % 200 == 0: print(f'  ...{n}/{len(ids)} {int(time.time()-t0)}s {STAT} targets={len(targets)}', flush=True)
    print(f'[scan] done {int(time.time()-t0)}s {STAT} 合计可偷 {len(targets)}', flush=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    json.dump({'stats': STAT, 'targets': targets}, open(os.path.join(args.outdir, f'hunt_{ts}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if targets:
        steal_all(targets, args.chunk)

if __name__ == '__main__':
    main()
