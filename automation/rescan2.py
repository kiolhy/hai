#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增量+限速(≈3 req/s)补扫 + 批量偷菜。断点续扫: results/rescan_progress.jsonl"""
import argparse, base64, glob, json, os, sys, time, threading, uuid
import urllib.request, urllib.error

LOCK = threading.Lock()
ROOT = ''; COOKIE_FILE = ''
STATE = {'token': '', 'exp': 0}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'
MIN_GAP = 0.34
_rl = threading.Lock(); _last = [0.0]

def rate_wait():
    with _rl:
        now = time.time(); gap = now - _last[0]
        if gap < MIN_GAP: time.sleep(MIN_GAP - gap)
        _last[0] = time.time()

def jwt_exp(t):
    try:
        p = t.split('.')[1]; p += '=' * (-len(p) % 4)
        return int(json.loads(base64.urlsafe_b64decode(p)).get('exp', 0))
    except Exception: return 0

def rc():
    return open(COOKIE_FILE, encoding='utf-8').read().strip()
def wc(v):
    open(COOKIE_FILE, 'w', encoding='utf-8').write(v)

def http(method, url, token=None, body=None, cookie=None, timeout=20):
    h = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': ROOT, 'User-Agent': UA}
    if token: h['Authorization'] = 'Bearer ' + token
    if cookie: h['Cookie'] = 'new_api_refresh=' + cookie
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
            return r.status, (json.loads(raw) if raw.strip().startswith(('{', '[')) else raw), (r.headers.get_all('Set-Cookie') or [])
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try: d = json.loads(raw)
        except Exception: d = raw
        return e.code, d, (e.headers.get_all('Set-Cookie') or [])
    except Exception as e:
        return 0, {'error': str(e)}, []

def do_refresh():
    st, d, sc = http('POST', ROOT + '/api/user/auth/refresh', cookie=rc(), body={})
    if st == 200 and isinstance(d, dict) and d.get('success') and d.get('data', {}).get('access_token'):
        for c in sc:
            if c.startswith('new_api_refresh='):
                wc(c.split(';', 1)[0].split('=', 1)[1].strip()); break
        STATE['token'] = d['data']['access_token']; STATE['exp'] = jwt_exp(STATE['token']); return True
    return False

def get_token(force=False):
    with LOCK:
        if force or not STATE['token'] or STATE['exp'] - time.time() < 120:
            if not do_refresh(): raise RuntimeError('refresh failed')
        return STATE['token']

def garden(uid):
    for attempt in range(6):
        rate_wait()
        try: tok = get_token()
        except Exception as e: return {'id': uid, 'status': 'AUTHFAIL'}
        st, d, _ = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={uid}', token=tok)
        if st == 401:
            try: get_token(force=True)
            except Exception: return {'id': uid, 'status': 'AUTHFAIL'}
            continue
        if st in (429, 0) or st >= 500:
            time.sleep(0.5 + attempt * 0.8); continue
        if st == 200 and isinstance(d, dict) and d.get('success'):
            plots = d.get('data', {}).get('plots', [])
            tg = [{'victim': uid, 'plot': i, 'round': int(p['round'])} for i, p in enumerate(plots) if p.get('canSteal') is True and p.get('round')]
            return {'id': uid, 'status': 'OPEN', 'plots': len(plots), 'targets': tg}
        if st == 403: return {'id': uid, 'status': 'CLOSED'}
        if st == 404: return {'id': uid, 'status': 'GONE'}
        return {'id': uid, 'status': f'HTTP{st}'}
    return {'id': uid, 'status': 'GAVEUP'}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True); ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--prev'); ap.add_argument('--gap', type=float, default=0.34)
    ap.add_argument('--chunk', type=int, default=80)
    ap.add_argument('--outdir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results'))
    args = ap.parse_args()
    global ROOT, COOKIE_FILE, MIN_GAP
    ROOT = args.root.rstrip('/'); COOKIE_FILE = args.cookie_file; MIN_GAP = args.gap
    os.makedirs(args.outdir, exist_ok=True)
    prog = os.path.join(args.outdir, 'rescan_progress.jsonl')

    prev = args.prev or sorted(glob.glob(os.path.join(args.outdir, 'scan_*.json')))[-1]
    pj = json.load(open(prev, encoding='utf-8'))
    results = {r['id']: r for r in pj['results']}
    retry_ids = [i for i, r in results.items() if r['status'] not in ('GONE', 'NOTFOUND', 'CLOSED', 'OPEN')]

    done = {}
    if os.path.exists(prog):
        for line in open(prog, encoding='utf-8'):
            line = line.strip()
            if not line: continue
            try:
                r = json.loads(line); done[r['id']] = r
            except Exception: pass
    todo = [i for i in retry_ids if i not in done]
    print(f'[scan] prev total={len(results)} unknown={len(retry_ids)} 已完成={len(done)} 待扫={len(todo)} gap={MIN_GAP}', flush=True)
    if not do_refresh(): print('[fatal] refresh failed', flush=True); sys.exit(2)
    print(f'[auth] exp in {int(STATE["exp"]-time.time())}s', flush=True)

    if todo:
        t0 = time.time(); n = 0
        f = open(prog, 'a', encoding='utf-8')
        for uid in todo:
            r = garden(uid); done[uid] = r
            f.write(json.dumps(r, ensure_ascii=False) + '\n'); f.flush()
            n += 1
            if n % 100 == 0:
                el = int(time.time() - t0)
                c = {}
                for x in done.values(): c[x['status']] = c.get(x['status'], 0) + 1
                print(f'  ...{n}/{len(todo)} {el}s {c}', flush=True)
        f.close()
        print(f'[scan] done {int(time.time()-t0)}s', flush=True)

    # 合并: prev 已知 + 本次 done
    allr = dict(results); allr.update(done)
    counts = {}
    for r in allr.values(): counts[r['status']] = counts.get(r['status'], 0) + 1
    open_users = sorted([i for i, r in allr.items() if r['status'] == 'OPEN'])
    targets = [t for r in allr.values() if r['status'] == 'OPEN' for t in r.get('targets', [])]
    print(f'[result] counts={counts}', flush=True)
    print(f'[result] OPEN用户={len(open_users)} -> {open_users}', flush=True)
    print(f'[result] 可偷地块={len(targets)}', flush=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    json.dump({'counts': counts, 'open_users': open_users, 'targets': targets, 'results': list(allr.values())},
              open(os.path.join(args.outdir, f'scan2_{ts}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if not targets:
        print('[steal] 无可偷地块', flush=True); return

    def sv():
        st, d, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=get_token())
        return d['data']['version'], d['data']['state']['stars']
    version, stars0 = sv()
    print(f'[steal] version={version} stars={stars0} targets={len(targets)}', flush=True)
    steals, skipped = [], []
    for i in range(0, len(targets), args.chunk):
        batch = targets[i:i + args.chunk]
        body = {'action': 'qqStealAll', 'params': {'targets': [{'victim': t['victim'], 'plot': t['plot'], 'round': t['round']} for t in batch]},
                'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
        st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=get_token(), body=body)
        ok = st == 200 and isinstance(d, dict) and d.get('success')
        nS = nK = 0
        if ok:
            res = d['data']['result']; steals += res.get('steals', []); skipped += res.get('skipped', [])
            nS, nK = len(res.get('steals', [])), len(res.get('skipped', [])); version = d['data'].get('version', version)
        print(f'[steal] batch {i//args.chunk+1}: HTTP{st} sent={len(batch)} steals={nS} skipped={nK}', flush=True)
        time.sleep(0.4)
    _, stars1 = sv()
    out = {'time': ts, 'open_users': open_users, 'targets': len(targets), 'stolen': len(steals), 'skipped': len(skipped),
           'stars_start': stars0, 'stars_end': stars1, 'steals': steals, 'skipped_detail': skipped}
    fn = os.path.join(args.outdir, f'scansteal2_{ts}.json')
    json.dump(out, open(fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'[done] stolen={len(steals)} skipped={len(skipped)} stars {stars0}->{stars1} -> {fn}', flush=True)

if __name__ == '__main__':
    main()
