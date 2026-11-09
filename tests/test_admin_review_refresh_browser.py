"""Actual browser reload during a delayed save, with a local fixture HTTP server.

Run directly with Playwright installed. No source DB or production connections.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT/'static/js/validation-review.js').read_text(encoding='utf-8')
    values, writes = {}, []
    started = threading.Event()
    fail = [False]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, value, status=200, content_type='application/json'):
            data = (json.dumps(value) if content_type=='application/json' else value).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type+'; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            parsed = urlparse(self.path)
            query = {k:v[0] for k,v in parse_qs(parsed.query).items()}
            kind = query.get('type','null_check')
            check = values.get(kind, {'checked':False})
            if parsed.path=='/check/':
                return self.respond({'success':True,'check':check})
            if parsed.path=='/api/':
                return self.respond(dict(success=True,total=7,counts={'corrected':7},items=[dict(
                    table_name='public.fixture',country='SEG',product='REF',retailer='Amazon',
                    total=7,counts={'corrected':7},check=check)]))
            html = '<meta charset="utf-8"><section id="validation-review" data-kind="'+kind+'" data-label="검수" data-api="/api/" data-check-api="/check/" data-review-user="1">'
            html += '<input type="hidden" name="csrfmiddlewaretoken" value="test-token"><button id="vr-back">뒤로</button><div id="vr-save-status" hidden></div><div id="vr-body"></div></section>'
            html += '<script>function initFilterBar(){};function getSelectedDate(){return "2026-11-09";}</script><script>'+source+'</script>'
            self.respond(html, content_type='text/html')

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers['X-CSRFToken']=='test-token'
            writes.append(payload)
            started.set()
            time.sleep(1.2)  # List GET can finish before this save commits.
            if fail[0]:
                fail[0] = False
                return self.respond({'error':'Fixture save failed'},status=500)
            check = dict(checked=payload['checked'],actor='admin',updated_at='2026-11-09T12:00:00+09:00')
            values[payload['type']] = check
            self.respond({'success':True,'check':check})

    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on('pageerror',lambda e:errors.append(str(e)))
            for kind in ('null_check','cross_field','format_check','field_missing'):
                page.goto(f'http://127.0.0.1:{server.server_port}/?type={kind}')
                checkbox = page.locator('[data-check-index="0"]')
                checkbox.wait_for()
                started.clear()
                checkbox.check()
                # Reload without waiting for the server to receive or commit.
                page.reload()
                page.locator('[data-check-index="0"]:checked').wait_for(timeout=15000)
                assert 'admin' in page.locator('.vr-check-info').inner_text()
                assert '7' in page.locator('[data-index="0"]').inner_text()
                started.clear()
                checkbox.uncheck()
                assert started.wait(3)
                page.reload()
                checkbox.wait_for(timeout=15000)
                assert not checkbox.is_checked()
                assert not values[kind]['checked']
                assert page.locator('.vr-retailer-card').count()==1
                print('PASS',kind,'immediate reload after check/uncheck; card retained',flush=True)
            fail[0] = True
            started.clear()
            checkbox.check()
            assert started.wait(3)
            page.reload()
            checkbox.wait_for(timeout=20000)
            assert not checkbox.is_checked()
            assert page.locator('#vr-save-status').is_visible()
            assert page.locator('#vr-save-status').inner_text()
            assert len(writes)==9  # Recovery only polls; never replays old writes.
            print('PASS failed save stays unchecked with a visible message; no duplicate POST',flush=True)
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__=='__main__':
    main()
