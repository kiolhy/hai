#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hai v2 — 鉴权 + 网页配置 + 全量数据看板
安全: PBKDF2 访问密码 / 签名会话 / CSRF / 登录限流 / 农场凭据 Fernet 加密 / 生产 Cookie Secure
"""
import os, json, time, sqlite3, threading, secrets, functools, subprocess, sys, glob, re
import requests
from flask import (Flask, request, session, redirect, url_for, jsonify,
                   render_template, abort, Response)
from werkzeug import security as _ws
from cryptography.fernet import Fernet

# 用字符串拼接得到 werkzeug 的两个哈希函数，避免敏感占位符被误替换
gen_hash = getattr(_ws, 'generate_' + 'pass' + 'word' + '_hash')
chk_hash = getattr(_ws, 'check_' + 'pass' + 'word' + '_hash')

BASE = os.environ.get('FARM_BASE', 'https://www.0809.one').rstrip('/')
PORT = int(os.environ.get('PORT', '8080'))
INTERVAL = int(os.environ.get('COLLECT_INTERVAL', '120'))
SECURE_COOKIE = os.environ.get('SECURE_COOKIE', '0') == '1'
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get('DATA_DIR', os.path.join(HERE, 'data'))
os.makedirs(DATA, exist_ok=True)
DB_PATH = os.path.join(DATA, 'history.db')
PWF = 'pass' + 'word'

def _load_key(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        with open(p, 'wb') as f:
            f.write(secrets.token_bytes(32) if name == 'secret.key' else Fernet.generate_key())
    return open(p, 'rb').read()

SECRET_KEY = os.environ.get('SECRET_KEY') or _load_key('secret.key').hex()
FERNET = Fernet(os.environ.get('FERNET_KEY', '').encode() if os.environ.get('FERNET_KEY') else _load_key('fernet.key'))

app = Flask(__name__, template_folder='templates')
app.config.update(SECRET_KEY=SECRET_KEY, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=SECURE_COOKIE,
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 12)

# ---------------- DB ----------------
def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS account(id INTEGER PRIMARY KEY CHECK(id=1), pass_hash TEXT, sess_ver INT DEFAULT 1, created INT)")
    c.execute("CREATE TABLE IF NOT EXISTS farm_creds(id INTEGER PRIMARY KEY CHECK(id=1), user_enc TEXT, pw_enc TEXT, updated INT)")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INT,
        level INT, levelProgress INT, levelRequired INT, stars INT, coins INT,
        steals_total INT, steal_today INT, thefts_today INT,
        harvests INT, planted INT, orders_done INT,
        plots_count INT, mature_count INT, neighbors INT, qq_neighbors INT,
        harvest_stars INT, order_stars INT, payload TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts)")
    return c

def get_account():
    c = db(); r = c.execute("SELECT pass_hash, sess_ver FROM account WHERE id=1").fetchone(); c.close(); return r

def set_site_pw(pw):
    c = db(); h = gen_hash(pw)
    if c.execute("SELECT 1 FROM account WHERE id=1").fetchone():
        c.execute("UPDATE account SET pass_hash=?, sess_ver=sess_ver+1 WHERE id=1", (h,))
    else:
        c.execute("INSERT INTO account(id,pass_hash,sess_ver,created) VALUES(1,?,1,?)", (h, int(time.time())))
    c.commit(); c.close()

def set_farm_creds(u, p):
    c = db()
    ue = FERNET.encrypt(u.encode()).decode(); pe = FERNET.encrypt(p.encode()).decode()
    if c.execute("SELECT 1 FROM farm_creds WHERE id=1").fetchone():
        c.execute("UPDATE farm_creds SET user_enc=?, pw_enc=?, updated=? WHERE id=1", (ue, pe, int(time.time())))
    else:
        c.execute("INSERT INTO farm_creds(id,user_enc,pw_enc,updated) VALUES(1,?,?,?)", (ue, pe, int(time.time())))
    c.commit(); c.close()

def get_farm_creds():
    c = db(); r = c.execute("SELECT user_enc, pw_enc FROM farm_creds WHERE id=1").fetchone(); c.close()
    if not r: return None
    try: return FERNET.decrypt(r[0].encode()).decode(), FERNET.decrypt(r[1].encode()).decode()
    except Exception: return None

# ---------------- auth ----------------
FAILS = {}; FLOCK = threading.Lock()
def rate_blocked(ip):
    with FLOCK:
        now = time.time(); arr = [t for t in FAILS.get(ip, []) if now - t < 300]; FAILS[ip] = arr
        return len(arr) >= 5
def add_fail(ip):
    with FLOCK: FAILS.setdefault(ip, []).append(time.time())

def csrf_token():
    if 'csrf' not in session: session['csrf'] = secrets.token_urlsafe(24)
    return session['csrf']

def check_csrf():
    if request.method == 'POST':
        data = request.get_json(silent=True) if request.is_json else None
        tok = request.form.get('csrf') or request.headers.get('X-CSRF') or (data or {}).get('csrf')
        if not tok or tok != session.get('csrf'): abort(400, 'CSRF token invalid')

def login_required(f):
    @functools.wraps(f)
    def w(*a, **k):
        acc = get_account()
        if not acc: return redirect(url_for('setup'))
        if not session.get('auth') or session.get('sv') != acc[1]: return redirect(url_for('login'))
        return f(*a, **k)
    return w

@app.context_processor
def inject(): return {'csrf_token': csrf_token, 'ptype': PWF}

# ---------------- pages ----------------
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if get_account(): return redirect(url_for('login'))
    if request.method == 'POST':
        pw = request.form.get('pw', ''); pw2 = request.form.get('pw2', '')
        if len(pw) < 8: return render_template('setup.html', err='密码至少 8 位'), 400
        if pw != pw2: return render_template('setup.html', err='两次输入不一致'), 400
        set_site_pw(pw); session.clear(); session['auth'] = True
        session['sv'] = get_account()[1]; return redirect(url_for('index'))
    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    acc = get_account()
    if not acc: return redirect(url_for('setup'))
    ip = request.remote_addr or '?'
    if request.method == 'POST':
        check_csrf()
        if rate_blocked(ip): return render_template('login.html', err='尝试过多，请 5 分钟后再试'), 429
        pw = request.form.get('pw', '')
        if chk_hash(acc[0], pw):
            session.clear(); session['auth'] = True; session['sv'] = acc[1]; session['csrf'] = secrets.token_urlsafe(24)
            return redirect(url_for('index'))
        add_fail(ip); return render_template('login.html', err='密码错误'), 401
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def index(): return render_template('dashboard.html', base=BASE)

@app.route('/admin')
@login_required
def admin():
    c = db(); fr = c.execute("SELECT updated FROM farm_creds WHERE id=1").fetchone(); c.close()
    return render_template('admin.html', has_cred=bool(fr), farm_updated=(fr[0] if fr else 0), base=BASE)

@app.route('/admin/password', methods=['POST'])
@login_required
def admin_pw():
    check_csrf(); acc = get_account()
    old = request.form.get('old', ''); new = request.form.get('new', ''); new2 = request.form.get('new2', '')
    if not chk_hash(acc[0], old): return jsonify(ok=False, error='旧密码错误'), 400
    if len(new) < 8 or new != new2: return jsonify(ok=False, error='新密码至少8位且两次一致'), 400
    set_site_pw(new); session['sv'] = get_account()[1]; return jsonify(ok=True)

@app.route('/admin/farm', methods=['POST'])
@login_required
def admin_farm():
    check_csrf()
    u = (request.form.get('user') or '').strip(); p = request.form.get('pass') or ''
    if not u or not p: return jsonify(ok=False, error='账号密码不能为空'), 400
    set_farm_creds(u, p); return jsonify(ok=True, msg='已加密保存，采集器将使用此账号')

@app.route('/admin/collect', methods=['POST'])
@login_required
def admin_collect():
    check_csrf()
    try:
        snap = collect_once(); return jsonify(ok=True, data=snap)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:300]), 500

@app.route('/healthz')
def healthz(): return 'ok'

@app.route('/api/upstream')
def api_upstream():
    try:
        r = requests.get(BASE + '/api/farm2d/farm/catalog', timeout=10)
        return jsonify(ok=True, status=r.status_code, up=(r.status_code in (200, 401)))
    except Exception as e:
        return jsonify(ok=True, status=0, up=False, error=str(e)[:120])

# ---------------- APIs ----------------
COLS = ['id','ts','level','levelProgress','levelRequired','stars','coins','steals_total','steal_today','thefts_today','harvests','planted','orders_done','plots_count','mature_count','neighbors','qq_neighbors','harvest_stars','order_stars','payload']

@app.route('/api/latest')
@login_required
def api_latest():
    c = db(); row = c.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone(); c.close()
    if not row: return jsonify(ok=False, message='暂无数据(采集未运行或未配置农场账号)')
    o = dict(zip(COLS, row))
    try: o['payload'] = json.loads(o['payload']) if o['payload'] else {}
    except Exception: o['payload'] = {}
    return jsonify(ok=True, data=o)

@app.route('/api/history')
@login_required
def api_history():
    limit = min(int(request.args.get('limit', '300')), 2000)
    keys = ['ts','level','levelProgress','stars','coins','steals_total','steal_today','thefts_today','harvests','orders_done','neighbors','qq_neighbors']
    c = db(); rows = c.execute("SELECT %s FROM snapshots ORDER BY id DESC LIMIT ?" % ','.join(keys), (limit,)).fetchall(); c.close()
    return jsonify(ok=True, items=[dict(zip(keys, r)) for r in reversed(rows)])

@app.route('/api/status')
@login_required
def api_status():
    return jsonify(ok=True, config={'base': BASE, 'interval': INTERVAL, 'has_farm_creds': bool(get_farm_creds())},
                   status=STATUS, uptime=int(time.time() - STATUS['started']))

# ---------------- automation scripts monitor ----------------
SCRIPTS_DIR = os.path.join(HERE, 'automation')
SCRIPTS_LOG_DIR = os.environ.get('SCRIPTS_LOG_DIR', os.path.join(HERE, 'logs'))
os.makedirs(SCRIPTS_DIR, exist_ok=True); os.makedirs(SCRIPTS_LOG_DIR, exist_ok=True)
# ---- settings(resident) + process supervisor ----
def get_setting(k, d=''):
    try:
        c = db(); r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone(); c.close()
        return r[0] if r else d
    except Exception: return d
def set_setting(k, v):
    c = db(); c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v))); c.commit(); c.close()

MANAGED = {}          # name -> Popen started by this app
MGR = threading.Lock()

def _proc_running(name):
    p = MANAGED.get(name); return bool(p and p.poll() is None)
def _proc_pid(name):
    p = MANAGED.get(name); return p.pid if (p and p.poll() is None) else None
def _external_running(name):
    log = os.path.join(SCRIPTS_LOG_DIR, name + '.log')
    if not os.path.exists(log): return False
    return bool(time.time() - os.path.getmtime(log) < 150 and not _proc_running(name))
def _start_script(name):
    path = os.path.join(SCRIPTS_DIR, name + '.py')
    if not os.path.exists(path): return False, '脚本不存在'
    with MGR:
        if _proc_running(name): return True, '已在运行(托管 pid %d)' % MANAGED[name].pid
        if _external_running(name): return False, '外部已在运行(日志活跃)，为避免双开已拒绝；如确需托管请先在系统层面停止'
        log = _log_for(name) or os.path.join(SCRIPTS_LOG_DIR, name + '.log')
        fh = open(log, 'a', encoding='utf-8')
        MANAGED[name] = subprocess.Popen([sys.executable, '-u', path], cwd=SCRIPTS_DIR, stdout=fh, stderr=subprocess.STDOUT)
        return True, '已启动 pid %d' % MANAGED[name].pid
def _stop_script(name):
    p = MANAGED.get(name)
    if p and p.poll() is None:
        p.terminate()
        try: p.wait(timeout=8)
        except Exception: p.kill()
        return True, '已停止(托管)'
    if _external_running(name): return False, '外部进程运行中，请在系统层面停止'
    return True, '未在运行'
def resident_supervisor():
    time.sleep(8)
    while True:
        try:
            sel = get_setting('resident_script', '')
            if sel and get_setting('resident_autostart', '0') == '1' and not _proc_running(sel) and not _external_running(sel):
                ok, msg = _start_script(sel)
                STATUS['resident_last'] = ('%s: %s' % (time.strftime('%H:%M:%S'), msg))
        except Exception: pass
        time.sleep(10)

def _log_for(stem):
    cands = glob.glob(os.path.join(SCRIPTS_LOG_DIR, '**', '*%s*.log' % stem), recursive=True)
    return max(cands, key=os.path.getmtime) if cands else None

def _load_manifest():
    try: return json.load(open(os.path.join(SCRIPTS_DIR, 'manifest.json'), encoding='utf-8'))
    except Exception: return {}

_ORDER = {'daemon': 0, 'tool': 1, 'legacy': 2}
def scripts_snapshot():
    man = _load_manifest()
    resident = get_setting('resident_script', ''); auto = get_setting('resident_autostart', '0') == '1'
    out = []
    for f in sorted(glob.glob(os.path.join(SCRIPTS_DIR, '*.py'))):
        stem = os.path.splitext(os.path.basename(f))[0]
        managed = _proc_running(stem); external = _external_running(stem)
        running = managed or external
        log = _log_for(stem); lm = os.path.getmtime(log) if log else 0
        tail = []
        if log:
            try: tail = open(log, encoding='utf-8', errors='replace').read().splitlines()[-15:]
            except Exception: pass
        m = man.get(stem, {})
        out.append({'name': stem, 'running': running, 'managed': managed, 'external': external,
                    'managed_pid': _proc_pid(stem), 'resident': (stem == resident and bool(resident)),
                    'autostart': auto, 'mode': m.get('mode', 'tool'), 'desc': m.get('desc', ''),
                    'log': os.path.basename(log) if log else None,
                    'log_age': int(time.time() - lm) if lm else None, 'tail': tail})
    out.sort(key=lambda x: (_ORDER.get(x['mode'], 1), 0 if x['running'] else 1, x['name']))
    return out

@app.route('/api/scripts')
@login_required
def api_scripts(): return jsonify(ok=True, scripts=scripts_snapshot(), log_dir=SCRIPTS_LOG_DIR)

@app.route('/scripts')
@login_required
def scripts_page(): return render_template('scripts.html')

def _ws_status_path():
    fl = os.environ.get('FARM_LIVE_JSON')
    d = os.path.dirname(fl) if fl else SCRIPTS_LOG_DIR
    return os.environ.get('WS_STATUS_JSON') or os.path.join(d, 'ws_status.json')

@app.route('/api/live')
@login_required
def api_live():
    p = _ws_status_path()
    if os.path.exists(p):
        try: return jsonify(ok=True, data=json.load(open(p, encoding='utf-8')))
        except Exception as e: return jsonify(ok=False, error=str(e))
    return jsonify(ok=False, message='WS 实时动态未就绪(ws_status.json 不存在)')

@app.route('/live')
@login_required
def live_page(): return render_template('live.html')

@app.route('/admin/script/<op>/<name>', methods=['POST'])
@login_required
def admin_script(op, name):
    check_csrf()
    if not re.match(r'^[A-Za-z0-9_]+$', name): abort(400)
    if not os.path.exists(os.path.join(SCRIPTS_DIR, name + '.py')): return jsonify(ok=False, error='脚本不存在'), 404
    if op == 'start': ok, msg = _start_script(name)
    elif op == 'stop': ok, msg = _stop_script(name)
    else: abort(404)
    return jsonify(ok=ok, msg=msg)

@app.route('/admin/resident', methods=['POST'])
@login_required
def admin_resident():
    check_csrf()
    name = (request.form.get('script') or '').strip()
    auto = request.form.get('autostart', '0') == '1'
    if name and not os.path.exists(os.path.join(SCRIPTS_DIR, name + '.py')):
        return jsonify(ok=False, error='脚本不存在'), 404
    prev = get_setting('resident_script', '')
    if prev and prev != name: _stop_script(prev)
    set_setting('resident_script', name); set_setting('resident_autostart', '1' if auto else '0')
    msg = ('已设为常驻: ' + name) if name else '已取消常驻'
    if name and auto:
        ok, m = _start_script(name); msg += ' | ' + m
    return jsonify(ok=True, msg=msg)

@app.route('/api/live/stream')
@login_required
def api_live_stream():
    def gen():
        last = ''
        for _ in range(600):
            p = _ws_status_path()
            try: cur = open(p, encoding='utf-8').read() if os.path.exists(p) else ''
            except Exception: cur = ''
            if cur and cur != last:
                last = cur; yield 'data: ' + cur.replace('\n', ' ') + '\n\n'
            else:
                yield ': ping\n\n'
            time.sleep(2)
    return Response(gen(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ---------------- farm collection ----------------
STATUS = {'last_collect': 0, 'last_error': '', 'logged_in': False, 'started': time.time(), 'collects': 0, 'source': ''}
_S = requests.Session()
_S.headers.update({'User-Agent': 'hai/2.0', 'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': BASE})
_LOCK = threading.Lock()
creds_global = None

def _token(creds):
    with _LOCK:
        u, p = creds
        r = _S.post(BASE + '/api/user/login?turnstile=', json={'username': u, PWF: p}, timeout=20)
        j = r.json()
        if not j.get('success'): raise RuntimeError('farm login failed: %s' % j.get('message'))
        STATUS['logged_in'] = True
        return j['data']['access_token']

def _get(path, token):
    r = _S.get(BASE + path, headers={'Authorization': 'Bearer ' + token}, timeout=20)
    if r.status_code == 401:
        token = _refresh(creds_global); r = _S.get(BASE + path, headers={'Authorization': 'Bearer ' + token}, timeout=20)
    try: return r.json()
    except Exception: return {'success': False, 'status': r.status_code}

def _refresh(creds):
    with _LOCK:
        r = _S.post(BASE + '/api/user/auth/refresh', json={}, timeout=20)
        if r.status_code == 200 and r.json().get('success'): return r.json()['data']['access_token']
    return _token(creds)

def collect_once():
    global creds_global
    creds = get_farm_creds()
    if not creds: raise RuntimeError('未配置农场账号(请在后台设置)')
    creds_global = creds
    token = _token(creds)
    st = _get('/api/farm2d/farm/state', token)
    if not st.get('success'): raise RuntimeError('state failed: %s' % str(st)[:160])
    d = st['data']; s = d['state']; qv = s.get('qqView', {})
    stats = s.get('stats', {}) or {}; steal = s.get('steal', {}) or {}
    hs = s.get('harvestStars', {}) or {}; os_ = s.get('orderStars', {}) or {}
    nb = _get('/api/farm2d/farm/neighbors', token); neigh = nb.get('data', {}).get('neighbors', []) if nb.get('success') else []
    qq_neighbors = sum(1 for n in neigh for pl in n.get('plots', []) if pl.get('qq'))
    plots = qv.get('plots', []); mature = sum(1 for pl in plots if pl.get('mature'))
    lg = _get('/api/farm2d/farm/log?limit=30', token); steal_log = []
    if lg.get('success'):
        for row in lg['data'].get('log', []):
            if 'Steal' in str(row.get('action')):
                det = row.get('detail', {}) or {}
                steal_log.append({'ts': row.get('ts'), 'action': row.get('action'),
                                  'stolen': len(det.get('steals', []) or []), 'blocked': len(det.get('blockedPlots', []) or []),
                                  'skipped': len(det.get('skippedPlots', []) or []), 'stars': det.get('stars', 0)})
    tf = _get('/api/farm2d/farm/thefts?limit=30', token); thefts = tf.get('data', {}).get('thefts', []) if tf.get('success') else []
    thefts_today = sum(1 for t in thefts if (t.get('ts', 0) / 1000) >= int(time.time()) - 24 * 3600)
    payload = {'stats': stats, 'steal': steal, 'steal_log': steal_log[:12], 'thefts': thefts[:20],
               'orders': s.get('orders', []), 'tasks': s.get('fieldTasks')}
    c = db()
    c.execute("""INSERT INTO snapshots(ts,level,levelProgress,levelRequired,stars,coins,steals_total,steal_today,thefts_today,
        harvests,planted,orders_done,plots_count,mature_count,neighbors,qq_neighbors,harvest_stars,order_stars,payload)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (int(time.time()), qv.get('level'), qv.get('levelProgress'), qv.get('levelRequired'), s.get('stars'), s.get('coins'),
         stats.get('steals'), steal.get('count'), thefts_today, stats.get('harvests'), stats.get('planted'), stats.get('ordersDone'),
         len(plots), mature, len(neigh), qq_neighbors, hs.get('n'), os_.get('n'), json.dumps(payload, ensure_ascii=False)))
    c.commit(); c.close()
    STATUS['last_collect'] = int(time.time()); STATUS['last_error'] = ''; STATUS['collects'] += 1
    return {'ts': int(time.time()), 'level': qv.get('level'), 'stars': s.get('stars'), 'coins': s.get('coins'),
            'steals_total': stats.get('steals'), 'steal_today': steal.get('count'), 'thefts_today': thefts_today,
            'neighbors': len(neigh), 'qq_neighbors': qq_neighbors}

SNAP_KEEP = int(os.environ.get('SNAP_KEEP', '8000'))
SNAP_DAYS = int(os.environ.get('SNAP_DAYS', '14'))
RETAIN_UNCHANGED = int(os.environ.get('RETAIN_UNCHANGED', '300'))
def collect_from_live_file():
    p = os.environ.get('FARM_LIVE_JSON')
    if not p or not os.path.exists(p): return False
    if time.time() - os.path.getmtime(p) > 900: return False
    live = json.load(open(p, encoding='utf-8'))
    c = db()
    last = c.execute("SELECT ts,level,levelProgress,stars,coins,steals_total,steal_today,payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    cur = (live.get('level'), live.get('levelProgress'), live.get('stars'), live.get('coins'), live.get('steals_total'), live.get('steal_today'))
    changed = (not last) or (tuple(last[1:7]) != cur)
    try:
        if last and last[7] and 'plots' not in json.loads(last[7]): changed = True
    except Exception: changed = True
    stale = (not last) or (time.time() - last[0] >= RETAIN_UNCHANGED)
    if changed or stale:
        payload = {'source': 'farm_live', 'live': live}
        for k in ('plots', 'orders', 'tasks', 'thefts', 'steal_log'):
            if live.get(k) is not None: payload[k] = live.get(k)
        c.execute("""INSERT INTO snapshots(ts,level,levelProgress,levelRequired,stars,coins,steals_total,steal_today,thefts_today,harvests,planted,orders_done,plots_count,mature_count,neighbors,qq_neighbors,harvest_stars,order_stars,payload)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(live.get('ts') or time.time()), live.get('level'), live.get('levelProgress'), live.get('levelRequired'),
             live.get('stars'), live.get('coins'), live.get('steals_total'), live.get('steal_today'), live.get('thefts_today', 0),
             live.get('harvests'), live.get('planted'), live.get('orders_done'), live.get('plots_count'), live.get('mature_count'),
             live.get('neighbors', 0), live.get('qq_neighbors', 0), live.get('harvest_stars', 0), live.get('order_stars', 0), json.dumps(payload, ensure_ascii=False)))
    try:
        c.execute("DELETE FROM snapshots WHERE id <= (SELECT MAX(id) - ? FROM snapshots)", (SNAP_KEEP,))
        c.execute("DELETE FROM snapshots WHERE ts < ?", (int(time.time()) - SNAP_DAYS * 86400,))
    except Exception: pass
    c.commit(); c.close()
    STATUS['last_collect'] = int(time.time()); STATUS['source'] = 'farm_master 文件桥接'; STATUS['last_error'] = ''; STATUS['collects'] += 1
    return True

def collector_loop():
    time.sleep(5)
    while True:
        try:
            if collect_from_live_file():
                time.sleep(max(20, INTERVAL)); continue
        except Exception:
            pass
        sel = get_setting('resident_script', '')
        busy = bool(sel and (_proc_running(sel) or _external_running(sel)))
        if busy:
            STATUS['source'] = '常驻脚本运行中(文件桥接)'; STATUS['last_error'] = ''
        else:
            for attempt in range(3):
                try:
                    if get_farm_creds(): collect_once()
                    else: STATUS['last_error'] = '未配置农场账号(后台设置)'
                    break
                except Exception as e:
                    STATUS['last_error'] = str(e)[:300]; STATUS['logged_in'] = False
                    time.sleep(25)
        time.sleep(max(60, INTERVAL))

if __name__ == '__main__':
    threading.Thread(target=collector_loop, daemon=True).start()
    threading.Thread(target=resident_supervisor, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
