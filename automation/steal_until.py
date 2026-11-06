#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持续偷菜直到 stars 达到目标值。轮询 /farm/neighbors，偷 qq 地块，动态滚动。"""
import argparse, base64, json, os, time, uuid, urllib.request, urllib.error

CK = 'new_api_refresh'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'
ROOT = ''; COOKIE_FILE = ''
TOK = {'v': '', 'exp': 0}
LOCK_ERR = {'n': 0}

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
    print('[auth] refresh failed', st, str(dd)[:200], flush=True); return False

def token(force=False):
    if force or not TOK['v'] or TOK['exp'] - time.time() < 120:
        if not refresh(): raise RuntimeError('auth')
    return TOK['v']

def get_state():
    st, d, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
    if st == 401:
        token(True); st, d, _ = http('GET', ROOT + '/api/farm2d/farm/state', token=token())
    if st == 200 and d.get('success'):
        return d['data']['state']['stars'], d['data']['version']
    return None, None

def get_neighbors():
    st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    if st == 401:
        token(True); st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    if st == 200 and d.get('success'):
        return d['data']['neighbors']
    return []

def steal(targets, version):
    body = {'action': 'qqStealAll',
            'params': {'targets': [{'victim': t['victim'], 'plot': t['plot'], 'round': t['round']} for t in targets]},
            'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
    st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
    if st == 401:
        token(True); st, d, _ = http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
    return st, d

def main():
    global ROOT, COOKIE_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.environ.get('FARM_ROOT', 'https://www.0809.one'))
    ap.add_argument('--cookie-file', default=os.environ.get('FARM_COOKIE_FILE', r'D:\project\偷菜\_recon\mycookie_lllliii.txt'))
    ap.add_argument('--target', type=int, default=200)
    ap.add_argument('--duration', type=int, default=1200, help='本轮运行秒数')
    ap.add_argument('--poll', type=int, default=40, help='无邻居时轮询间隔秒')
    ap.add_argument('--chunk', type=int, default=100)
    ap.add_argument('--logdir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results'))
    args = ap.parse_args()
    ROOT = args.root.rstrip('/'); COOKIE_FILE = args.cookie_file
    os.makedirs(args.logdir, exist_ok=True)
    if not refresh(): raise SystemExit(2)

    stars, version = get_state()
    if stars is None:
        print('[state] 读取失败', flush=True); raise SystemExit(3)
    print(f'[start] stars={stars} version={version} target={args.target}', flush=True)
    t0 = time.time()
    total_plots = 0
    total_stars_gain = 0
    start_stars = stars
    rounds = 0
    while stars < args.target and time.time() - t0 < args.duration:
        rounds += 1
        neigh = get_neighbors()
        targets = []
        for n in neigh:
            for p in n.get('plots', []):
                if p.get('qq'):
                    targets.append({'victim': n['user_id'], 'plot': p['i'], 'round': p['round']})
        if targets:
            for i in range(0, len(targets), args.chunk):
                batch = targets[i:i + args.chunk]
                st, d = steal(batch, version)
                if st == 200 and isinstance(d, dict) and d.get('success'):
                    res = d['data']['result']
                    nS = len(res.get('steals', [])); nB = len(res.get('blockedPlots', []))
                    version = d['data'].get('version', version)
                    ns = d['data']['state']['stars']
                    gain = ns - stars
                    stars = ns
                    total_plots += nS; total_stars_gain += gain
                    print(f'[steal] r{rounds} sent={len(batch)} stolen={nS} blocked={nB} stars={stars} (+{gain})', flush=True)
                elif st == 429 or st == 503:
                    print(f'[steal] HTTP{st} 限频/处理中, 退避...', flush=True); time.sleep(5)
                else:
                    print(f'[steal] HTTP{st} {str(d)[:120]}', flush=True); time.sleep(2)
                if stars >= args.target: break
            time.sleep(0.5)
        else:
            # 无邻居: 轮询等待熟地块 / 新邻居
            if rounds % 5 == 1:
                print(f'[wait] stars={stars} 无可用邻居, {args.poll}s后重试 (elapsed {int(time.time()-t0)}s)', flush=True)
            time.sleep(args.poll)
    print(f'[end] stars={stars} (start {start_stars}, +{stars-start_stars}) plots_stolen={total_plots} elapsed={int(time.time()-t0)}s target_reached={stars>=args.target}', flush=True)
    if stars >= args.target:
        print('[DONE] 目标达成', flush=True)

if __name__ == '__main__':
    main()
