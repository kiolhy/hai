import os, shutil, sqlite3
base = os.path.dirname(os.path.abspath(__file__))
dt = os.path.join(base, 'data_t3')
if os.path.isdir(dt): shutil.rmtree(dt)
os.environ['DATA_DIR'] = dt
os.environ['PORT'] = '8099'
os.environ['SCRIPTS_LOG_DIR'] = r'D:\project\偷菜\results'
os.environ['FARM_LIVE_JSON'] = r'D:\project\偷菜\results\farm_live.json'
os.environ['WS_STATUS_JSON'] = r'D:\project\偷菜\results\ws_status.json'
import app
print('IMPORT OK')
ss = app.scripts_snapshot(); print('scripts=', len(ss), 'fields=', sorted(ss[0].keys()))
print('resident_default=', repr(app.get_setting('resident_script','')))
def cnt():
    c = sqlite3.connect(app.DB_PATH); n = c.execute('select count(*) from snapshots').fetchone()[0]; c.close(); return n
print('count0=', cnt())
print('collect1=', app.collect_from_live_file(), 'count1=', cnt())
print('collect2=', app.collect_from_live_file(), 'count2=', cnt(), '(unchanged should NOT grow)')
print('SSE route present:', any(getattr(r,'rule','') =='/api/live/stream' for r in app.app.url_map.iter_rules()))
print('resident route present:', any(getattr(r,'rule','') =='/admin/resident' for r in app.app.url_map.iter_rules()))
