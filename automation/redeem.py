#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百川农场 钻石 -> NewAPI 额度 兑换客户端（正确的接口用法）
------------------------------------------------------------
接口:
  GET  /api/farm2d/balance   (Authorization: Bearer <access_token>)
       -> data:{ quota, week_cap, week_used, week_consumed, week_pending, remaining,
                 consumption_unavailable, base_locked, user_id, policy:{starQuota, rebateRate,
                 allowedQuotas, redeemPresets:[{stars,quota}]} }
  POST /api/farm2d/redeem    (Authorization: Bearer <access_token>)
       body:{ "quota": <allowedQuota>, "reason": "farm_reward",
              "source_key": "farm2d:{clientId}:{ts36}:{rand}", "meta": {} }
       -> 200 {success:true,data:{state,version,applied,idempotent,quota}}
          403 {code:"CAP_EXCEEDED"} / 400 {code:"INSUFFICIENT_STARS"...}

规则:
  1 钻石 = 500000 额度($1)；周上限 = floor(本周真实消费 × 20%)；无基础额度、不封顶；周一0点换周。
  兑换 quota 必须落在 allowedQuotas 且 <= remaining；source_key 失败重试必须复用(幂等)。

用法:
  python redeem.py --root https://www.<HOST> --cookie-file mycookie.txt --stars 1
  python redeem.py --root ... --cookie-file ... --stars 1 --dry-run
"""
import argparse, base64, json, os, time, urllib.request, urllib.error

CK = 'new_api_refresh'
TOK = {'v': '', 'exp': 0}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36'
ROOT = ''
COOKIE_FILE = ''

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
    ck = open(COOKIE_FILE, encoding='utf-8').read().strip()
    st, dd, sc = http('POST', ROOT + '/api/user/auth/refresh', cookie=ck, body={})
    if st == 200 and dd.get('success') and dd.get('data', {}).get('access_token'):
        for c in sc:
            if c.startswith(CK + '='):
                open(COOKIE_FILE, 'w', encoding='utf-8').write(c.split(';', 1)[0].split('=', 1)[1].strip()); break
        TOK['v'] = dd['data']['access_token']; TOK['exp'] = jwt_exp(TOK['v']); return True
    print('[auth] refresh 失败:', st, dd); return False

def token():
    if not TOK['v'] or TOK['exp'] - time.time() < 120:
        if not refresh(): raise RuntimeError('auth')
    return TOK['v']

def new_source_key(uid):
    ts = base64.b32encode(int(time.time() * 1000).to_bytes(6, 'big')).decode().lower()[:8]
    rnd = base64.b32encode(os.urandom(3)).decode().lower()[:4]
    return f'farm2d:u{uid}:{ts}:{rnd}'

def main():
    global ROOT, COOKIE_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--stars', type=int, default=1, help='兑换档位(1/5/10/25)')
    ap.add_argument('--quota', type=int, default=0, help='直接指定 quota(需在 allowedQuotas 内)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--intent-dir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results'))
    args = ap.parse_args()
    ROOT = args.root.rstrip('/'); COOKIE_FILE = args.cookie_file
    os.makedirs(args.intent_dir, exist_ok=True)
    if not refresh(): raise SystemExit(2)

    st, b, _ = http('GET', ROOT + '/api/farm2d/balance', token=token())
    if st != 200 or not b.get('success'):
        print('[balance] 读取失败', st, b); raise SystemExit(3)
    d = b['data']; pol = d['policy']; uid = d.get('user_id')
    print(f"[balance] quota={d['quota']} week_consumed={d['week_consumed']} week_cap={d['week_cap']} "
          f"week_used={d['week_used']} week_pending={d.get('week_pending',0)} remaining={d['remaining']}")
    print(f"[policy] starQuota={pol['starQuota']} rebateRate={pol['rebateRate']} allowedQuotas={pol['allowedQuotas']}")
    print(f"[policy] baseWeekly={pol.get('baseWeekly')} base_locked={d.get('base_locked')} consumption_unavailable={d.get('consumption_unavailable')}")

    # 选档位
    presets = pol.get('redeemPresets', [])
    if args.quota:
        quota = args.quota
    else:
        match = [p for p in presets if p.get('stars') == args.stars]
        if not match:
            print(f"[pick] 没有 {args.stars} 钻档位，可选: " + ', '.join(f"{p['stars']}钻={p['quota']}" for p in presets))
            raise SystemExit(4)
        quota = match[0]['quota']
    if pol.get('allowedQuotas') and quota not in pol['allowedQuotas']:
        print(f"[check] quota={quota} 不在 allowedQuotas={pol['allowedQuotas']}"); raise SystemExit(5)

    # 核心门槛
    if d.get('consumption_unavailable'):
        print('[check] 消费统计暂不可用(consumption_unavailable=true)，暂停兑换')
        return
    if d['remaining'] < quota:
        need = quota - d['remaining']
        print(f"[check] 本周剩余可兑不足：remaining={d['remaining']} < 需要 {quota}（差 {need}）")
        print(f"        原因: 周上限=floor(本周真实消费×20%)；当前 week_consumed={d['week_consumed']}, week_cap={d['week_cap']}, baseWeekly={pol.get('baseWeekly')}。")
        if d['week_consumed'] == 0:
            print("        该账号本周没有任何真实 API 消费，且无基础额度 -> 一钻都兑不了。需先充值并用该账号真实调用 API 产生消费。")
        raise SystemExit(6)

    intent_fn = os.path.join(args.intent_dir, f'redeem_intent_{uid}.json')
    key = None
    if os.path.exists(intent_fn):
        try:
            prev = json.load(open(intent_fn, encoding='utf-8'))
            if prev.get('quota') == quota and prev.get('key'):
                key = prev['key']
                print(f"[idempotent] 复用上次未确认的 source_key: {key}  (若上次已成功, 本次会返回 idempotent 不重复入账)")
        except Exception:
            pass
    if not key:
        key = new_source_key(uid)
    json.dump({'quota': quota, 'key': key, 'ts': int(time.time()*1000)}, open(intent_fn, 'w', encoding='utf-8'))

    body = {'quota': quota, 'reason': 'farm_reward', 'source_key': key, 'meta': {}}
    print(f"[redeem] POST /api/farm2d/redeem quota={quota} source_key={key}")
    if args.dry_run:
        print('[dry-run] 不提交。'); return
    st, r, _ = http('POST', ROOT + '/api/farm2d/redeem', token=token(), body=body)
    print(f'[redeem] HTTP {st}')
    print(json.dumps(r, ensure_ascii=False, indent=2)[:1500])
    if st == 200 and isinstance(r, dict) and r.get('success'):
        os.remove(intent_fn)  # 已确认入账/幂等, 清除意图
        dd = r['data']
        print(f"[ok] applied={dd.get('applied')} idempotent={dd.get('idempotent')} quota_now={dd.get('quota')} "
              f"stars_now={dd.get('state',{}).get('stars')} version={dd.get('version')}")
    elif st in (429, 503) or st == 0:
        print("[unknown] 结果未知：保留 source_key，稍后用同一 key 重跑（幂等确认），切勿新建 key。")
    else:
        print("[failed] 明确拒绝：见上 code/message；不会扣钻/入账。")

if __name__ == '__main__':
    main()
