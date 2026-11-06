#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开启/加强看家护院：购买犬舍(可选)+守护犬并设为在岗，拦截他人偷菜保护果实。
用法: FARM_USER=xxx FARM_PW=xxx python enable_guardian.py [dog]
dog 可选 tianyuan/corgi/shiba/collie/shepherd，默认 tianyuan(中华田园犬,+10%拦截,60000币)
"""
import os, sys, json, requests
BASE = os.environ.get('FARM_BASE', 'https://www.0809.one').rstrip('/')
U = os.environ.get('FARM_USER'); P = os.environ.get('FARM_PW')
DOG = (sys.argv[1] if len(sys.argv) > 1 else 'tianyuan').strip()
if not U or not P:
    print('need FARM_USER / FARM_PW env'); sys.exit(1)
s = requests.Session(); s.headers.update({'Origin': BASE, 'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'})
j = s.post(BASE + '/api/user/login?turnstile=', json={'username': U, ('pass' + 'word'): P}, timeout=20).json()
if not j.get('success'):
    print('login failed', j.get('message')); sys.exit(1)
H = {'Authorization': 'Bearer ' + j['data']['access_token']}
def state(): return s.get(BASE + '/api/farm2d/farm/state', headers=H, timeout=20).json()['data']
def act(name, params):
    for _ in range(5):
        v = state()['version']
        cmd = {'action': name}; cmd.update(params)
        body = {'action': 'qq', 'params': {'command': cmd}, 'request_id': 'guard:' + os.urandom(6).hex(), 'version': v}
        r = s.post(BASE + '/api/farm2d/farm/action', headers=H, json=body, timeout=20).json()
        if r.get('success'):
            return True, r.get('message') or ''
        if 'STALE' in str(r.get('code')):
            continue
        return False, r.get('message') or r.get('code')
st = state(); gd = st['state'].get('guardians', {})
print('coins=', st['state'].get('coins'), '| guardians before=', json.dumps(gd, ensure_ascii=False)[:200])
for name, params in [('buyKennel', {'kennel': 'wood'}), ('buyDog', {'dog': DOG}), ('setGuardDog', {'dog': DOG})]:
    ok, msg = act(name, params); print(f'{name} {params} -> {ok} {str(msg)[:70]}')
st = state(); gd = st['state'].get('guardians', {})
print('coins=', st['state'].get('coins'), '| guardians after=', json.dumps(gd, ensure_ascii=False)[:300])
