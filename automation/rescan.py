#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""限速补扫: 读取上一轮 scan_*.json, 对未知(429/0/超时)的 ID 用限速+退避重扫, 再批量偷。"""
import argparse, base64, glob, json, os, sys, time, threading, uuid
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

LOCK = threading.Lock()
ROOT = ''; COOKIE_FILE = ''
STATE = {'token': '', 'exp': 0}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'
MIN_GAP = 0.22   # 全局最小请求间隔(秒) ~4.5 req/s
_rl_lock = threading.Lock(); _rl_last = [0.0]

def rate_wait():
    with _rl_lock:
        now = time.time(); gap = now - _rl_last[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _rl_last[0] = time.time()

def jwt_exp(tok):
    try:
        p = tok.split('.')[1]; p += '=' * (-len(p) % 4)
        return int(json.loads(base64.urlsafe_b64decode(p)).get('exp', 0))
    except Exception:
        return 0

def read_cookie():
    with open(COOKIE_FILE, encoding='utf-8') as f: return f.read().strip()
def write_cookie(v):
    with open(COOKIE_FILE, 'w', encoding='utf-8') as f: f.write(v)

def http(method, url, token=None, body=None, cookie=None, timeout=20):
    h = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': ROOT, 'User-Agent': UA}
    if token: h['Authorization'] = 'Bearer ' + token
    if cookie: h['Cookie'] = 'new_api_refresh=' + cookie
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
            return r.status, (json.loads(raw) if raw.strip().startswith(('{', '[')) else raw), (r.headers.get_all('Set-Cookie') or []), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try: d = json.loads(raw)
        except Exception: d = raw
        return e.code, d, (e.headers.get_all('Set-Cookie') or []), dict(e.headers)
    except Exception as e:
        return 0, {'error': str(e)}, [], {}

def do_refresh():
    st, d, sc, _ = http('POST', ROOT + '/api/user/auth/refresh', cookie=read_cookie(), body={})
    if st == 200 and isinstance(d, dict) and d.get('success') and d.get('data', {}).get('access_token'):
        for c in sc:
            if c.startswith('new_api_refresh='):
                write_cookie(c.split(';', 1)[0].split('=', 1)[1].strip()); break
        STATE['token'] = d['data']['access_token']; STATE['exp'] = jwt_exp(STATE['token']); return True
    return False

def get_token(force=False):
    with LOCK:
        if force or not STATE['token'] or STATE['exp'] - time.time() < 120:
            if not do_refresh(): raise RuntimeError('refresh failed')
        return STATE['token']

def garden(uid):
    """带 429/超时退避重试"""
    backoff = 1.0
    for attempt in range(7):
        rate_wait()
        try: tok = get_token()
        except Exception as e: return {'id': uid, 'status': 'AUTHFAIL', 'error': str(e)}
        st, d, _, hdr = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={uid}', token=tok)
        if st == 401:
            try: get_token(force=True)
            except Exception as e: return {'id': uid, 'status': 'AUTHFAIL', 'error': str(e)}
            continue
        if st in (429, 0) or st >= 500:
            time.sleep(backoff); backoff = min(backoff * 1.8, 10); continue
        if st == 200 and isinstance(d, dict) and d.get('success'):
            plots = d.get('data', {}).get('plots', [])
            tg = []
            for i, p in enumerate(plots):
                if p.get('canSteal') is True and p.get('round'):
                    tg.append({'victim': uid, 'plot': i, 'round': int(p['round'])})
            return {'id': uid, 'status': 'OPEN', 'plots': len(plots), 'targets': tg}
        if st == 403: return {'id': uid, 'status': 'CLOSED'}
        if st == 404: return {'id': uid, 'status': 'GONE'}
        return {'id': uid, 'status': f'HTTP{st}', 'body': str(d)[:120]}
    return {'id': uid, 'status': 'GAVEUP'}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--prev', help='上一轮 scan_*.json 路径, 默认取 results 最新')
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--chunk', type=int, default=80)
    ap.add_argument('--outdir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results'))
    args = ap.parse_args()
    global ROOT, COOKIE_FILE
    ROOT = args.root.rstrip('/'); COOKIE_FILE = args.cookie_file

    prev = args.prev or sorted(glob.glob(os.path.join(args.outdir, 'scan_*.json')))[-1]
    pj = json.load(open(prev, encoding='utf-8'))
    results = {r['id']: r for r in pj['results']}
    # 需要重扫的: 非 GONE/NOTFOUND/CLOSED/OPEN
    retry_ids = [i for i, r in results.items() if r['status'] not in ('GONE', 'NOTFOUND', 'CLOSED', 'OPEN')]
    print(f'[rescan] prev={os.path.basename(prev)} total={len(results)} 需重扫={len(retry_ids)}')
    if not do_refresh(): print('[fatal] refresh failed'); sys.exit(2)
    print(f'[auth] exp in {int(STATE["exp"]-time.time())}s')

    t0 = time.time(); done = 0
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = {ex.submit(garden, uid): uid for uid in retry_ids}
        for fut in as_completed(futs):
            r = fut.result(); results[r['id']] = r; done += 1
            if done % 150 == 0: print(f'  ...{done}/{len(retry_ids)} {int(time.time()-t0)}s')
    print(f'[rescan] done {int(time.time()-t0)}s')

    counts = {}
    for r in results.values(): counts[r['status']] = counts.get(r['status'], 0) + 1
    open_users = [i for i, r in results.items() if r['status'] == 'OPEN']
    targets = [t for r in results.values() if r['status'] == 'OPEN' for t in r.get('targets', [])]
    print(f'[rescan] counts={counts}')
    print(f'[rescan] 开放花园 {len(open_users)} 个 -> {sorted(open_users)}')
    print(f'[rescan] 可偷地块 {len(targets)} 个')
    ts = time.strftime('%Y%m%d_%H%M%S')
    json.dump({'counts': counts, 'open_users': open_users, 'targets': targets,
               'results': list(results.values())}, open(os.path.join(args.outdir, f'scan2_{ts}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    if not targets:
        print('[steal] 无可偷地块'); return
    # steal
    def sv():
        st, d, _, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=get_token())
        return d['data']['version'], d['data']['state']['stars']
    version, stars0 = sv()
    print(f'[steal] version={version} stars={stars0} targets={len(targets)}')
    steals, skipped = [], []
    for i in range(0, len(targets), args.chunk):
        batch = targets[i:i + args.chunk]
        body = {'action': 'qqStealAll', 'params': {'targets': [{'victim': t['victim'], 'plot': t['plot'], 'round': t['round']} for t in batch]},
                'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
        st, d, _, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=get_token(), body=body)
        ok = st == 200 and isinstance(d, dict) and d.get('success')
        nS = nK = 0
        if ok:
            res = d['data']['result']; steals += res.get('steals', []); skipped += res.get('skipped', [])
            nS, nK = len(res.get('steals', [])), len(res.get('skipped', [])); version = d['data'].get('version', version)
        print(f'[steal] batch {i//args.chunk+1}: HTTP{st} sent={len(batch)} steals={nS} skipped={nK}')
        time.sleep(0.4)
    _, stars1 = sv()
    out = {'time': ts, 'open_users': open_users, 'targets': len(targets), 'stolen': len(steals),
           'skipped': len(skipped), 'stars_start': stars0, 'stars_end': stars1, 'steals': steals, 'skipped_detail': skipped}
    fn = os.path.join(args.outdir, f'scansteal2_{ts}.json')
    json.dump(out, open(fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'[done] stolen={len(steals)} skipped={len(skipped)} stars {stars0}->{stars1}')
    print(f'[done] {fn}')

if __name__ == '__main__':
    main()
