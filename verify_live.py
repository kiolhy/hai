import os, shutil, json
base = os.path.dirname(os.path.abspath(__file__))
dt = os.path.join(base, 'data_t2')
if os.path.isdir(dt): shutil.rmtree(dt)
os.environ['DATA_DIR'] = dt
os.environ['PORT'] = '8099'
os.environ['SCRIPTS_LOG_DIR'] = r'D:\project\偷菜\results'
os.environ['FARM_LIVE_JSON'] = r'D:\project\偷菜\results\farm_live.json'
os.environ['WS_STATUS_JSON'] = r'D:\project\偷菜\results\ws_status.json'
import app
app.set_site_pw('Test12345')
c = app.app.test_client(); c.get('/login')
with c.session_transaction() as s: tok = s.get('csrf')
c.post('/login', data={'csrf': tok, 'pw': 'Test12345'})
print('GET /live ->', c.get('/live').status_code)
r = c.get('/api/live').get_json()
print('api/live ok=', r.get('ok'), 'connected=', (r.get('data') or {}).get('connected'), 'counts=', (r.get('data') or {}).get('counts'))
print('api/scripts ok=', c.get('/api/scripts').get_json().get('ok'))
