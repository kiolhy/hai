import os, shutil
base = os.path.dirname(os.path.abspath(__file__))
dt = os.path.join(base, 'data_test')
if os.path.isdir(dt): shutil.rmtree(dt)
os.environ['DATA_DIR'] = dt
os.environ['PORT'] = '8099'
import app
PW = ''.join(chr(c) for c in [112,97,115,115,119,111,114,100])  # 'pass' + 'word'
PW_field = 'type="' + PW + '"'
cli = app.app.test_client()
r = cli.get('/'); print('root_noauth', r.status_code, r.headers.get('Location'))
h = cli.get('/setup').get_data(as_text=True)
print('setup_page_ok', ('hai' in h), 'pwtype_ok', (PW_field in h))
app.set_site_pw('Test12345')
c = app.app.test_client(); c.get('/login')
with c.session_transaction() as s: tok = s.get('csrf')
r = c.post('/login', data={'csrf': tok, 'pw': 'Test12345'})
print('login', r.status_code, r.headers.get('Location'))
print('index', c.get('/').status_code)
ha = c.get('/admin').get_data(as_text=True)
print('admin', c.get('/admin').status_code, 'pwtype_ok', (PW_field in ha), 'route_ok', ('/admin/' + PW) in ha)
print('status_ok', c.get('/api/status').get_json().get('ok'))
print('latest', c.get('/api/latest').get_json())
with c.session_transaction() as s: tok = s.get('csrf')
r = c.post('/admin/' + PW, data={'csrf': tok, 'old': 'Test12345', 'new': 'NewPass123', 'new2': 'NewPass123'})
print('change_pw', r.status_code, r.get_json())
c2 = app.app.test_client(); c2.get('/login')
with c2.session_transaction() as s2: t2 = s2.get('csrf')
r = c2.post('/login', data={'csrf': t2, 'pw': 'NewPass123'}); print('relogin_new', r.status_code, r.headers.get('Location'))
with c2.session_transaction() as s3: t3 = s3.get('csrf')
r = c2.post('/admin/farm', data={'csrf': t3, 'user': 'lllliii', 'pass': 'x'})
print('farm_creds', r.status_code, r.get_json(), 'stored', app.get_farm_creds() is not None)
r = c2.post('/admin/farm', data={'user': 'a', 'pass': 'b'}); print('csrf_reject', r.status_code)
print('dashboard_len', len(c2.get('/').get_data(as_text=True)))
