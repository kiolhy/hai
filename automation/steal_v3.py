#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3: 每轮先取权威 state(版本/星级) -> 邻居+开放花园取熟地块 -> 偷; 处理 409 STALE_STATE 自动刷新。
写进度到 results/steal_state.json，便于外部核验(不与会话争抢)。"""
import argparse, base64, json, os, time, uuid, urllib.request, urllib.error

CK = 'new_api_refresh'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'
ROOT = ''; COOKIE_FILE = ''; STATE_FILE = ''
TOK = {'v': '', 'exp': 0}
OPEN_IDS = [1345, 1350, 1369, 1380, 1524, 1632, 1692, 1694, 1816, 1991, 2405]

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
    print('[auth] refresh failed', st, str(dd)[:160], flush=True); return False
def token(force=False):
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
def neighbors_targets():
    st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    if st == 401: token(True); st, d, _ = http('GET', ROOT + '/api/farm2d/farm/neighbors', token=token())
    ts = []
    if st == 200 and isinstance(d, dict) and d.get('success'):
        for n in d['data']['neighbors']:
            for p in n.get('plots', []):
                if p.get('qq'): ts.append({'victim': n['user_id'], 'plot': p['i'], 'round': p['round']})
    return ts
def garden_targets():
    ts = []
    for oid in OPEN_IDS:
        st, g, _ = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={oid}', token=token())
        if st == 401: token(True); st, g, _ = http('GET', ROOT + f'/api/farm2d/farm/qq/garden?owner={oid}', token=token())
        if st == 200 and isinstance(g, dict) and g.get('success'):
            for i, p in enumerate(g['data'].get('plots', [])):
                if p.get('canSteal') is True and p.get('round'):
                    ts.append({'victim': oid, 'plot': i, 'round': int(p['round'])})
    return ts
def steal(targets, version):
    body = {'action': 'qqStealAll',
            'params': {'targets': [{'victim': t['victim'], 'plot': t['plot'], 'round': t['round']} for t in targets]},
            'request_id': f'farm:qqStealAll:{uuid.uuid4()}', 'version': version}
    return http('POST', ROOT + '/api/farm2d/farm/action', token=token(), body=body)
def write_state(stars, version, extra=''):
    try:
        json.dump({'ts': int(time.time()*1000), 'time': time.strftime('%H:%M:%S'), 'stars': stars, 'version': version, 'note': extra},
                  open(STATE_FILE, 'w', encoding='utf-8'))
    except Exception: pass

def main():
    global ROOT, COOKIE_FILE, STATE_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True); ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--target', type=int, default=200)
    ap.add_argument('--duration', type=int, default=3600)
    ap.add_argument('--poll', type=int, default=20)
    ap.add_argument('--chunk', type=int, default=100)
    ap.add_argument('--state-file', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', 'steal_state.json'))
    args = ap.parse_args()
    ROOT = args.root.rstrip('/'); COOKIE_FILE = args.cookie_file; STATE_FILE = args.state_file
    if not refresh(): raise SystemExit(2)
    t0 = time.time(); plots = 0; cyc = 0; start = None
    while time.time() - t0 < args.duration:
        cyc += 1
        stars, version = get_state()
        if stars is None:
            print(f'[c{cyc}] state 读取失败, 退避', flush=True); time.sleep(5); continue
        if start is None: start = stars; print(f'[start] stars={stars} version={version} target={args.target}', flush=True)
        write_state(stars, version)
        if stars >= args.target:
            print(f'[DONE] stars={stars} >= {args.target} plots={plots} elapsed={int(time.time()-t0)}s', flush=True)
            write_state(stars, version, 'DONE'); return
        tgt = neighbors_targets() + garden_targets()
        seen = set(); ded = []
        for t in tgt:
            k = (t['victim'], t['plot'])
            if k not in seen: seen.add(k); ded.append(t)
        if ded:
            done_all = True
            for i in range(0, len(ded), args.chunk):
                batch = ded[i:i + args.chunk]
                st, d, _ = steal(batch, version)
                if st == 200 and isinstance(d, dict) and d.get('success'):
                    res = d['data']['result']; nS = len(res.get('steals', []))
                    version = d['data'].get('version', version); ns = d['data']['state']['stars']
                    gain = ns - stars; stars = ns; plots += nS
                    print(f'[steal] c{cyc} sent={len(batch)} stolen={nS} stars={stars} (+{gain})', flush=True)
                    write_state(stars, version)
                elif st == 409:
                    # 版本过期: 取返回快照或重取状态, 下轮重来
                    dd = d.get('data') if isinstance(d, dict) else None
                    if isinstance(dd, dict) and 'version' in dd:
                        version = dd['version']
                    print(f'[steal] c{cyc} 409 STALE_STATE, 刷新版本重试', flush=True)
                    done_all = False; break
                elif st == 401:
                    token(True); done_all = False; break
                elif st in (429, 503):
                    print(f'[steal] c{cyc} HTTP{st} backoff', flush=True); time.sleep(4); done_all = False; break
                else:
                    print(f'[steal] c{cyc} HTTP{st} {str(d)[:100]}', flush=True); time.sleep(2)
                if stars >= args.target: break
            time.sleep(0.4)
        else:
            if cyc % 15 == 1:
                print(f'[wait] stars={stars} 无熟地块/邻居 (elapsed {int(time.time()-t0)}s)', flush=True)
            time.sleep(args.poll)
    stars, version = get_state()
    print(f'[end] stars={stars} (start {start}, +{(stars-start) if (stars is not None and start is not None) else "?"}) plots={plots} elapsed={int(time.time()-t0)}s reached={(stars>=args.target) if stars is not None else False}', flush=True)
    write_state(stars, version, 'END')

if __name__ == '__main__':
    main()
