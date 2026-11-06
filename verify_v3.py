import os, shutil
base = os.path.dirname(os.path.abspath(__file__))
dt = os.path.join(base, 'data_t4')
if os.path.isdir(dt): shutil.rmtree(dt)
os.environ.update(DATA_DIR=dt, PORT='8099', SCRIPTS_LOG_DIR=r'D:\project\偷菜\results',
                  FARM_LIVE_JSON=r'D:\project\偷菜\results\farm_live.json', WS_STATUS_JSON=r'D:\project\偷菜\results\ws_status.json')
import app
app.set_site_pw('Test12345')
c = app.app.test_client(); c.get('/login')
with c.session_transaction() as s: tok = s.get('csrf')
c.post('/login', data={'csrf': tok, 'pw': 'Test12345'})
with c.session_transaction() as s: tok = s.get('csrf')
print('pages: /', c.get('/').status_code, '/live', c.get('/live').status_code, '/scripts', c.get('/scripts').status_code, '/admin', c.get('/admin').status_code)
print('api/scripts ok=', c.get('/api/scripts').get_json().get('ok'))
print('api/live ok=', c.get('/api/live').get_json().get('ok'))
# 选择常驻(不自动启动, 避免拉起真实进程): autostart=0
r = c.post('/admin/resident', data={'csrf': tok, 'script': 'farm_master', 'autostart': '0'}); print('set resident:', r.get_json())
print('resident now=', app.get_setting('resident_script'), app.get_setting('resident_autostart'))
ss = [x for x in app.scripts_snapshot() if x['name'] == 'farm_master'][0]
print('scripts_snapshot farm_master resident=', ss['resident'], 'mode=', ss['mode'])
# 取消常驻
r = c.post('/admin/resident', data={'csrf': tok, 'script': '', 'autostart': '0'}); print('cancel resident:', r.get_json())
print('resident after cancel=', repr(app.get_setting('resident_script')))
# CSRF 保护
r = c.post('/admin/resident', data={'script': 'farm_master', 'autostart': '0'}); print('no-csrf status=', r.status_code)
