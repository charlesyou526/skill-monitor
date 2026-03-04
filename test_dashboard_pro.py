#!/usr/bin/env python3
"""OpenClaw Skill Monitor Pro - with Email + Prometheus"""
import os, sys, json, time, sqlite3, threading, smtplib
import argparse, urllib.request, urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ============ i18n ============
class I18n:
    T = {
        'en': {'sent': '✅ Email sent to {to}', 'fail': '❌ Email failed: {err}'},
        'zh': {'sent': '✅ 邮件已发送至 {to}', 'fail': '❌ 邮件失败：{err}'}
    }
    def __init__(self, lang=None):
        loc = os.environ.get('LANG', '')
        self.lang = 'zh' if 'zh' in loc.lower() else 'en'
        if lang: self.lang = lang[:2].lower()
    def __call__(self, k, **kw):
        t = self.T.get(self.lang, self.T['en']).get(k, k)
        return t.format(**kw) if kw else t

# ============ Colors ============
class C:
    G, R, Y, B, End = '\033[92m', '\033[91m', '\033[93m', '\033[94m', '\033[0m'
    @classmethod
    def disable(cls):
        if not sys.stdout.isatty():
            for a in dir(cls):
                if a.isupper() and not a.startswith('_'): setattr(cls, a, '')
C.disable()

# ============ Proxy ============
class Proxy:
    VARS = ['http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']
    def __init__(self, bypass=None): self.bypass = bypass or ['127.0.0.1','localhost','::1']
    def __enter__(self):
        self.orig = {v:os.environ[v] for v in self.VARS if v in os.environ}
        np = os.environ.get('no_proxy','')
        os.environ['no_proxy'] = f'{np},{",".join(self.bypass)}' if np else ','.join(self.bypass)
        return self
    def __exit__(self,*a):
        for v in self.VARS:
            if v in self.orig: os.environ[v]=self.orig[v]
            elif v in os.environ: del os.environ[v]
    def opener(self): return urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())

# ============ Result Store ============
@dataclass
class Result:
    ts: str; ep: str; ok: bool; ms: float; err: str=None; det: Dict=field(default_factory=dict)

class Store:
    def __init__(self, db):
        self.db = Path(db).expanduser(); self.db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db)) as c: c.executescript('''
            CREATE TABLE IF NOT EXISTS r(id INTEGER PRIMARY KEY,ts TEXT,ep TEXT,ok INT,ms REAL,err TEXT,det TEXT);
            CREATE INDEX IF NOT EXISTS idx_ts ON r(ts); CREATE INDEX IF NOT EXISTS idx_ok ON r(ok);
        ''')
    def save(self, r: Result):
        with sqlite3.connect(str(self.db)) as c:
            c.execute('INSERT INTO r(ts,ep,ok,ms,err,det)VALUES(?,?,?,?,?,?)',
                (r.ts,r.ep,1 if r.ok else 0,r.ms,r.err,json.dumps(r.det) if r.det else None)); c.commit()
    def stats(self, hrs=24):
        since = (datetime.now()-timedelta(hours=hrs)).isoformat()
        with sqlite3.connect(str(self.db)) as c:
            c.row_factory=sqlite3.Row
            r=c.execute('SELECT COUNT(*)as t,SUM(CASE WHEN ok=1 THEN 1 END)as s,AVG(ms)as a FROM r WHERE ts>=?',(since,)).fetchone()
            return {'total':r['t']or 0,'rate':round((r['s']or 0)/(r['t']or 1)*100,1),'avg':round(r['a']or 0,1)} if r['t'] else {'total':0,'rate':0,'avg':0}
    def recent(self, n=20):
        with sqlite3.connect(str(self.db)) as c:
            c.row_factory=sqlite3.Row
            return [Result(row['ts'],row['ep'],bool(row['ok']),row['ms'],row['err'],json.loads(row['det'])if row['det']else{}) 
                    for row in c.execute('SELECT*FROM r ORDER BY ts DESC LIMIT ?',(n,))]

# ============ Email ============
class Email:
    def __init__(self, smtp, port, user, pwd, frm, to, i18n):
        self.smtp,self.port,self.user,self.pwd,self.frm,self.to,self.i18n = smtp,port,user,pwd,frm,to,i18n
    def send(self, subject, body_html, body_text=None):
        msg = MIMEMultipart('alternative')
        msg['Subject'],msg['From'],msg['To'] = subject, self.frm, ', '.join(self.to)
        if body_text: msg.attach(MIMEText(body_text,'plain','utf-8'))
        msg.attach(MIMEText(body_html,'html','utf-8'))
        try:
            s = smtplib.SMTP_SSL(self.smtp, self.port) if self.port==465 else smtplib.SMTP(self.smtp, self.port)
            if self.port==587: s.starttls()
            s.login(self.user, self.pwd); s.sendmail(self.frm, self.to, msg.as_string()); s.quit()
            print(f"{C.G}{self.i18n('sent', to=', '.join(self.to))}{C.End}")
            return True
        except Exception as e:
            print(f"{C.R}{self.i18n('fail', err=str(e))}{C.End}")
            return False

# ============ Prometheus ============
import http.server, socketserver
class Metrics(http.server.BaseHTTPRequestHandler):
    store=i18n=None
    def do_GET(self):
        if self.path=='/metrics':
            s=self.store.stats(24) if self.store else {'total':0,'rate':0,'avg':0}
            m=f'''# HELP skill_monitor_tests_total Total tests
# TYPE skill_monitor_tests_total counter
skill_monitor_tests_total {s['total']}
# HELP skill_monitor_success_rate Success rate 0-100
# TYPE skill_monitor_success_rate gauge
skill_monitor_success_rate {s['rate']}
# HELP skill_monitor_avg_response_ms Avg response ms
# TYPE skill_monitor_avg_response_ms gauge
skill_monitor_avg_response_ms {s['avg']}
# HELP skill_monitor_up Service up
# TYPE skill_monitor_up gauge
skill_monitor_up 1
'''
            self.send_response(200); self.send_header('Content-type','text/plain'); self.end_headers(); self.wfile.write(m.encode())
        elif self.path=='/health':
            self.send_response(200); self.send_header('Content-type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'ok':True}).encode())
        else: self.send_response(404); self.end_headers()
    def log_message(self,*a): pass

# ============ Client ============
class Client:
    def __init__(self, host, port, timeout, i18n):
        self.url=f'http://{host}:{port}'; self.to=timeout; self.i18n=i18n; self.px=Proxy()
    def _req(self, path, json_ok=True):
        start=time.time()
        try:
            with self.px:
                with self.px.opener().open(urllib.request.Request(self.url+path), timeout=self.to) as r:
                    c=r.read().decode(); ms=(time.time()-start)*1000
                    return (True, json.loads(c) if json_ok else c, None, ms) if json_ok else (True, c, None, ms)
        except urllib.error.HTTPError as e: return False,None,self.i18n('http_error',code=e.code,reason=e.reason),0
        except urllib.error.URLError as e: return False,None,self.i18n('conn_error',reason=e.reason),0
        except json.JSONDecodeError as e: return False,None,self.i18n('json_error',error=str(e)),0
        except Exception as e: return False,None,f'{type(e).__name__}: {e}',0
    def test_api(self):
        ok,data,err,ms=self._req('/api/stats')
        return {'ep':'/api/stats','ok':ok,'err':err,'ms':round(ms,1),'cnt':len(data)if ok and isinstance(data,dict)else 0}
    def test_html(self):
        ok,cnt,err,ms=self._req('/', json_ok=False)
        checks={'dt':'<!DOCTYPE html>'in(cnt or''),'tl':'OpenClaw Skill Monitor'in(cnt or''),'st':'id="stats"'in(cnt or'')}
        return {'ep':'/','ok':ok,'err':err,'ms':round(ms,1),'chk':checks,'pass':all(checks.values())if ok else False}
    def run(self):
        print(f"{C.B}🔍 {self.i18n('testing',url=self.url)}{C.End}")
        api=self.test_api(); html=self.test_html()
        print(f"   /api/stats: {C.G if api['ok']else C.R}{'✅'if api['ok']else'❌'}{C.End} {'└─ Skills:'+str(api['cnt'])if api['ok']else'└─ '+api['err']}")
        print(f"   /: {C.G if html['ok']else C.R}{'✅'if html['ok']else'❌'}{C.End} {'└─ Checks:'+str(sum(html['chk'].values()))+'/'+str(len(html['chk']))if html['ok']else'└─ '+html['err']}")
        ok=api['ok']and html['ok']and html['pass']
        print(f"\n{C.G if ok else C.R}{'✅ All passed!'if ok else'❌ Some failed'}{C.End}")
        return {'ok':ok,'api':api,'html':html,'ts':datetime.now().isoformat()}

# ============ Main ============
def main():
    p=argparse.ArgumentParser(description='Skill Monitor Pro')
    p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8899); p.add_argument('--timeout',type=int,default=10)
    p.add_argument('--lang',choices=['en','zh']); p.add_argument('--interval',type=int); p.add_argument('--schedule')
    p.add_argument('--webhook'); p.add_argument('--alert-level',choices=['info','warn','error','critical'],default='warn')
    # EMAIL ARGS - THE MISSING PIECE / 邮件参数 - 缺失的部分
    p.add_argument('--email-smtp', metavar='SERVER', help='SMTP server')
    p.add_argument('--email-port', type=int, default=465, help='SMTP port')
    p.add_argument('--email-user', metavar='USER', help='SMTP username')
    p.add_argument('--email-pass', metavar='PASS', help='SMTP password')
    p.add_argument('--email-from', metavar='ADDR', help='From address')
    p.add_argument('--email-to', nargs='+', metavar='ADDR', help='To addresses')
    p.add_argument('--email-report', choices=['daily','weekly'], help='Report frequency')
    # Prometheus / Grafana
    p.add_argument('--prometheus-port', type=int, help='Prometheus metrics port')
    # Persistence
    p.add_argument('--persist', action='store_true'); p.add_argument('--db-path', default='~/.openclaw/tools/skill-monitor/results.db')
    # Output
    p.add_argument('--export'); p.add_argument('--format',choices=['json','csv']); p.add_argument('-v','--verbose',action='store_true'); p.add_argument('-q','--quiet',action='store_true')
    a=p.parse_args()
    
    i18n=I18n(a.lang); client=Client(a.host,a.port,a.timeout,i18n)
    store=Store(a.db_path)if a.persist else None
    
    # Email setup / 邮件配置
    email=None
    if a.email_smtp and a.email_user and a.email_to:
        email=Email(a.email_smtp,a.email_port,a.email_user,a.email_pass or'',a.email_from or a.email_user,a.email_to,i18n)
    
    # Prometheus setup / Prometheus 配置
    if a.prometheus_port and store:
        Metrics.store=store; Metrics.i18n=i18n
        srv=socketserver.TCPServer(('0.0.0.0',a.prometheus_port),Metrics)
        threading.Thread(target=srv.serve_forever,daemon=True).start()
        print(f"{C.B}📈 Metrics: http://0.0.0.0:{a.prometheus_port}/metrics{C.End}")
    
    last_email=None
    def run_test():
        nonlocal last_email
        r=client.run()
        if store:
            store.save(Result(r['ts'],r['api']['ep'],r['api']['ok'],r['api']['ms'],r['api']['err'],{'cnt':r['api']['cnt']}))
            store.save(Result(r['ts'],r['html']['ep'],r['html']['ok'],r['html']['ms'],r['html']['err'],r['html']['chk']))
        # Daily email at 9 AM / 每日 9 点发邮件
        if email and a.email_report=='daily' and datetime.now().hour==9 and datetime.now().minute<5:
            if last_email is None or (datetime.now()-last_email).days>=1:
                st=store.stats(24); rec=store.recent(20)
                html=f'<h3>📊 Daily Report</h3><p>Tests: {st["total"]}, Success: {st["rate"]}%, Avg: {st["avg"]}ms</p>'
                html+='<table border=1>'+''.join(f'<tr><td>{t.ts}</td><td>{t.ep}</td><td>{"✅"if t.ok else"❌"}</td><td>{t.ms}ms</td></tr>'for t in rec)+'</table>'
                email.send(f'[Skill Monitor] Daily Report {datetime.now().date()}', html, f'Tests: {st["total"]}, Rate: {st["rate"]}%')
                last_email=datetime.now()
        return r
    
    if a.interval:
        print(f"⏰ Running every {a.interval}s (Ctrl+C to stop)")
        try:
            while True: run_test(); time.sleep(a.interval)
        except KeyboardInterrupt: print("\n⏹️  Stopped")
    else:
        r=run_test(); sys.exit(0 if r['ok']else 1)

if __name__=='__main__': main()
