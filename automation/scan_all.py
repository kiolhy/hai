#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百川农场 全站用户ID扫描 + 批量偷菜
------------------------------------
Phase 1: 遍历 owner=START..END 调 GET /api/farm2d/farm/qq/garden
         200 -> 开放花园, 解析 plots 中 canSteal==True 且带 round 的地块
         403 -> GARDEN_CLOSED(关闭, 读不到 round, 跳过)
         404 -> PLOT_GONE / 无农场
Phase 2: 对收集到的目标 POST /api/farm2d/farm/action  action=qqStealAll 分批偷

token 由 new_api_refresh cookie 走 /api/user/auth/refresh 自动续期(15min)。
自己会话独立, 不与浏览器争抢。
"""
import argparse, base64, json, os, sys, time, threading, uuid
import urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

LOCK = threading.Lock()
ROOT = ''
COOKIE_FILE = ''
STATE = {'token': '', 'exp': 0}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'

def jwt_exp(tok):
    try:
        p = tok.split('.')[1]; p += '=' * (-len(p) % 4)
        d = json.loads(base64.urlsafe_b64decode(p))
        return int(d.get('exp', 0))
    except Exception:
        return 0

def read_cookie():
    with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()

def write_cookie(v):
    with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
        f.write(v)

def http(method, url, token=None, body=None, cookie=None, timeout=20):
    h = {'Accept': 'application/json', 'Content-Type': 'application/json',
         'Origin': ROOT, 'User-Agent': UA}
    if token:
        h['Authorization'] = 'Bearer ' + token
    if cookie:
        h['Cookie'] = 'new_api_refresh=' + cookie
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
            sc = r.headers.get_all('Set-Cookie') or []
            return r.status, (json.loads(raw) if raw.strip().startswith(('{', '[')) else raw), sc
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        sc = e.headers.get_all('Set-Cookie') or []
        try:
            return e.code, json.loads(raw), sc
        except Exception:
            return e.code, raw, sc
    except Exception as e:
        return 0, {'error': str(e)}, []

def do_refresh():
    cookie = read_cookie()
    st, d, sc = http('POST', ROOT + '/api/user/auth/refresh', cookie=cookie, body={})
    if st == 200 and isinstance(d, dict) and d.get('success') and d.get('data', {}).get('access_token'):
        for c in sc:
            if c.startswith('new_api_refresh='):
                nv = c.split(';', 1)[0].split('=', 1)[1]
                write_cookie(nv.strip())
                break
        STATE['token'] = d['data']['access_token']
        STATE['exp'] = jwt_exp(STATE['token'])
        return True
    return False

def get_token(force=False):
    with LOCK:
        if force or not STATE['token'] or STATE['exp'] - time.time() < 120:
            ok = do_refresh()
            if not ok:
                raise RuntimeError('refresh failed (session expired/revoked)')
        return STATE['token']

def scan_one(uid, timeout=20):
    for attempt in range(2):
        try:
            tok = get_token()
        except Exception as e:
            return {'id': uid, 'status': 'AUTHFAIL', 'error': str(e)}
        st, d, _ = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={uid}', token=tok, timeout=timeout)
        if st == 401:
            try:
                get_token(force=True)
            except Exception as e:
                return {'id': uid, 'status': 'AUTHFAIL', 'error': str(e)}
            continue
        if st == 200 and isinstance(d, dict) and d.get('success'):
            plots = d.get('data', {}).get('plots', [])
            tgt = []
            for i, p in enumerate(plots):
                if p.get('canSteal') is True and p.get('round'):
                    tgt.append({'victim': uid, 'plot': i, 'round': int(p['round']),
                                'cropId': p.get('cropId'), 'yieldTotal': p.get('yieldTotal')})
            return {'id': uid, 'status': 'OPEN', 'plots': len(plots), 'targets': tgt}
        if st == 403:
            return {'id': uid, 'status': 'CLOSED'}
        if st == 404:
            code = d.get('code') if isinstance(d, dict) else ''
            return {'id': uid, 'status': 'GONE' if code == 'PLOT_GONE' else 'NOTFOUND', 'code': code}
        return {'id': uid, 'status': f'HTTP{st}', 'body': str(d)[:120]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, help='站点根, 如 https://www.example.com')
    ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--end', type=int, default=2800)
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--delay', type=float, default=0.03, help='每请求后 sleep 秒')
    ap.add_argument('--chunk', type=int, default=80)
    ap.add_argument('--outdir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results'))
    args = ap.parse_args()

    global ROOT, COOKIE_FILE
    ROOT = args.root.rstrip('/')
    COOKIE_FILE = args.cookie_file
    os.makedirs(args.outdir, exist_ok=True)
    ts = time.strftime('%Y%m%d_%H%M%S')

    if not do_refresh():
        print('[fatal] 初始 refresh 失败, cookie 可能已失效'); sys.exit(2)
    print(f'[auth] token ok uid? exp in {int(STATE["exp"]-time.time())}s')

    # Phase 1 scan
    results = []
    counts = {}
    print(f'[scan] {args.start}..{args.end} threads={args.threads}')
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = {ex.submit(scan_one, uid): uid for uid in range(args.start, args.end + 1)}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            counts[r['status']] = counts.get(r['status'], 0) + 1
            done += 1
            if done % 200 == 0:
                print(f'  ...{done}/{args.end-args.start+1}  {counts}  {int(time.time()-t0)}s')
            if args.delay:
                time.sleep(args.delay)

    targets = []
    open_users = []
    for r in results:
        if r['status'] == 'OPEN':
            open_users.append(r['id'])
            targets.extend(r['targets'])
    print(f'[scan] done {int(time.time()-t0)}s  status={counts}')
    print(f'[scan] 开放花园用户 {len(open_users)} 个, 可偷地块 {len(targets)} 个')

    scan_fn = os.path.join(args.outdir, f'scan_{ts}.json')
    with open(scan_fn, 'w', encoding='utf-8') as f:
        json.dump({'range': [args.start, args.end], 'counts': counts, 'open_users': open_users,
                   'targets': targets, 'results': results}, f, ensure_ascii=False, indent=1)
    print(f'[scan] 明细已存 {scan_fn}')

    if not targets:
        print('[steal] 无可偷地块, 结束'); return

    # Phase 2 steal
    def state_version():
        tok = get_token()
        st, d, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=tok)
        return d['data']['version'], d['data']['state']['stars']

    version, stars0 = state_version()
    print(f'[steal] version={version} stars={stars0} targets={len(targets)}')
    steals, skipped = [], []
    for i in range(0, len(targets), args.chunk):
        batch = targets[i:i + args.chunk]
        tok = get_token()
        body = {'action': 'qqStealAll',
                'params': {'targets': [{'victim': t['victim'], 'plot': t['plot'], 'round': t['round']} for t in batch]},
                'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
        st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=tok, body=body)
        if st == 401:
            get_token(force=True); st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=get_token(), body=body)
        ok = st == 200 and isinstance(d, dict) and d.get('success')
        nS = nK = 0
        if ok:
            res = d['data']['result']
            steals += res.get('steals', [])
            skipped += res.get('skipped', [])
            nS, nK = len(res.get('steals', [])), len(res.get('skipped', []))
            version = d['data'].get('version', version)
        print(f'[steal] batch {i//args.chunk+1}: HTTP{st} sent={len(batch)} steals={nS} skipped={nK}')
        time.sleep(0.4)

    _, stars1 = state_version()
    summary = {'time': ts, 'range': [args.start, args.end], 'open_users': open_users,
               'targets': len(targets), 'stolen': len(steals), 'skipped': len(skipped),
               'stars_start': stars0, 'stars_end': stars1, 'steals': steals, 'skipped_detail': skipped}
    fn = os.path.join(args.outdir, f'scansteal_{ts}.json')
    with open(fn, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f'[done] 偷取 {len(steals)} 个地块, 跳过 {len(skipped)}, stars {stars0}->{stars1}')
    print(f'[done] 结果 {fn}')

if __name__ == '__main__':
    main()
