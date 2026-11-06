#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hai — 百川农场 数据看板 / 服务端
------------------------------------------------
功能:
  - 采集器: 用农场账号登录(NewAPI)，定时拉取 /farm/state、/farm/neighbors、/farm/log，
    写入 SQLite 历史库，供前端展示"各种数据"。
  - Web 看板: 等级/经验/钻石/金币、地块状态、可偷邻居、订单/任务、历史曲线、偷菜流水。
  - REST API: /api/latest /api/history /api/status /api/collect /api/logs

配置(环境变量):
  FARM_BASE       默认 https://www.0809.one
  FARM_USERNAME   农场账号用户名 (lllliii)
  FARM_PASSWORD   账号密码
  PORT            监听端口, 默认 8080
  COLLECT_INTERVAL 采集间隔秒, 默认 300
  DB_PATH         默认 data/history.db
"""
import os, json, time, sqlite3, threading, traceback
from flask import Flask, jsonify, request, send_from_directory
import requests

BASE = os.environ.get('FARM_BASE', 'https://www.0809.one').rstrip('/')
USER = os.environ.get('FARM_USERNAME', '')
PWD  = os.environ.get('FARM_PASSWORD', '')
PORT = int(os.environ.get('PORT', '8080'))
INTERVAL = int(os.environ.get('COLLECT_INTERVAL', '300'))
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'history.db'))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__, static_folder='static', static_url_path='/static')
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'hai-dashboard/1.0', 'Accept': 'application/json',
                       'Content-Type': 'application/json', 'Origin': BASE})
LOCK = threading.Lock()
STATUS = {'last_collect': 0, 'last_error': '', 'logged_in': False, 'started': time.time(), 'collects': 0}

def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute('''CREATE TABLE IF NOT EXISTS snapshots(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER,
        level INTEGER, levelProgress INTEGER, levelRequired INTEGER,
        stars INTEGER, coins INTEGER, plots_json TEXT,
        neighbors INTEGER, qq_neighbors INTEGER, orders_json TEXT, tasks_json TEXT,
        raw TEXT)''')
    return c

def login():
    with LOCK:
        r = SESSION.post(BASE + '/api/user/login?turnstile=',
                         json={'username': USER, ('pass' + 'word'): PWD}, timeout=20)
        j = r.json()
        if not j.get('success'):
            raise RuntimeError('login failed: %s' % j)
        STATUS['logged_in'] = True
        return j['data']['access_token']

def fresh_token():
    with LOCK:
        r = SESSION.post(BASE + '/api/user/auth/refresh', json={}, timeout=20)
        if r.status_code == 200:
            j = r.json()
            if j.get('success') and j.get('data', {}).get('access_token'):
                return j['data']['access_token']
        # fallback relogin
    return login()

def api_get(path, token):
    r = SESSION.get(BASE + path, headers={'Authorization': 'Bearer ' + token}, timeout=20)
    if r.status_code == 401:
        token = fresh_token()
        r = SESSION.get(BASE + path, headers={'Authorization': 'Bearer ' + token}, timeout=20)
    try:
        return r.json()
    except Exception:
        return {'success': False, 'status': r.status_code, 'text': r.text[:200]}

def collect_once():
    token = fresh_token()
    st = api_get('/api/farm2d/farm/state', token)
    if not st.get('success'):
        raise RuntimeError('state failed: %s' % str(st)[:200])
    d = st['data']; s = d['state']; qv = s.get('qqView', {})
    nb = api_get('/api/farm2d/farm/neighbors', token)
    neighbors = nb.get('data', {}).get('neighbors', []) if nb.get('success') else []
    qq_neighbors = sum(1 for n in neighbors for p in n.get('plots', []) if p.get('qq'))
    snap = dict(ts=int(time.time()),
                level=qv.get('level'), levelProgress=qv.get('levelProgress'), levelRequired=qv.get('levelRequired'),
                stars=s.get('stars'), coins=s.get('coins'),
                plots=qv.get('plots', []), neighbors=len(neighbors), qq_neighbors=qq_neighbors,
                orders=s.get('orders', []), tasks=s.get('fieldTasks'))
    c = db()
    c.execute('''INSERT INTO snapshots(ts,level,levelProgress,levelRequired,stars,coins,plots_json,neighbors,qq_neighbors,orders_json,tasks_json,raw)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
              (snap['ts'], snap['level'], snap['levelProgress'], snap['levelRequired'], snap['stars'], snap['coins'],
               json.dumps(snap['plots'], ensure_ascii=False), snap['neighbors'], snap['qq_neighbors'],
               json.dumps(snap['orders'], ensure_ascii=False), json.dumps(snap['tasks'], ensure_ascii=False),
               json.dumps(snap, ensure_ascii=False)))
    c.commit(); c.close()
    STATUS['last_collect'] = snap['ts']; STATUS['last_error'] = ''; STATUS['collects'] += 1
    return snap

def collector_loop():
    while True:
        try:
            if USER and PWD:
                collect_once()
            else:
                STATUS['last_error'] = 'FARM_USERNAME/FARM_PASSWORD 未配置，仅展示历史'
        except Exception as e:
            STATUS['last_error'] = str(e)[:300]
            STATUS['logged_in'] = False
        time.sleep(max(30, INTERVAL))

@app.route('/')
def index():
    return send_from_directory(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'), 'index.html')

@app.route('/api/latest')
def api_latest():
    c = db(); row = c.execute('SELECT * FROM snapshots ORDER BY id DESC LIMIT 1').fetchone(); c.close()
    if not row:
        return jsonify({'ok': False, 'message': '暂无数据(采集未运行或未配置账号)'})
    cols = ['id','ts','level','levelProgress','levelRequired','stars','coins','plots_json','neighbors','qq_neighbors','orders_json','tasks_json','raw']
    o = dict(zip(cols, row))
    for k in ['plots_json','orders_json','tasks_json']:
        try: o[k] = json.loads(o[k]) if o[k] else None
        except Exception: pass
    return jsonify({'ok': True, 'data': o})

@app.route('/api/history')
def api_history():
    limit = min(int(request.args.get('limit', '200')), 2000)
    c = db()
    rows = c.execute('SELECT ts,level,levelProgress,stars,coins,neighbors,qq_neighbors FROM snapshots ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    c.close()
    rows = rows[::-1]
    keys = ['ts','level','levelProgress','stars','coins','neighbors','qq_neighbors']
    return jsonify({'ok': True, 'items': [dict(zip(keys, r)) for r in rows]})

@app.route('/api/status')
def api_status():
    return jsonify({'ok': True, 'config': {'base': BASE, 'has_creds': bool(USER and PWD), 'interval': INTERVAL},
                    'status': STATUS, 'uptime': int(time.time()-STATUS['started'])})

@app.route('/api/collect', methods=['POST'])
def api_collect():
    try:
        snap = collect_once()
        return jsonify({'ok': True, 'data': {k: snap[k] for k in ('ts','level','levelProgress','levelRequired','stars','coins','neighbors','qq_neighbors')}})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/healthz')
def healthz():
    return 'ok'

if __name__ == '__main__':
    threading.Thread(target=collector_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
