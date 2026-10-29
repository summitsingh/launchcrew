"""Local approval UI. All actions stop at approval and export."""
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .receipts import approve_receipt, load_receipt, save_receipt
from .run import run_pipeline

ROOT = Path(__file__).resolve().parents[1]


def create_server(host='127.0.0.1', port=0, root=ROOT):
    root = Path(root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # No request content, headers, or environment values in logs.

        def respond(self, status, content, kind='text/html; charset=utf-8', download=False):
            data = content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            if download:
                self.send_header('Content-Disposition', 'attachment; filename="launchcrew-pack.json"')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.route(False)

        def do_POST(self):
            self.route(True)

        def route(self, post):
            try:
                # Reject cross-origin form submissions. No CORS support.
                if post:
                    origin = self.headers.get('Origin')
                    if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                        return self.respond(403, 'Cross-origin request refused')
                    if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                        return self.respond(403, 'Cross-origin request refused')
                path = urlsplit(self.path).path
                if path == '/' and not post:
                    profiles = [json.loads((root / 'agents' / (n + '.json')).read_text())
                                for n in ('scout', 'maker', 'checker')]
                    body = '<h1>LaunchCrew</h1><p>Demo data only. Approval plus export only.</p>'
                    body += '<form method="post" action="/run"><label>Idea, price, audience <input name="idea" required maxlength="1000" value="Vegan leather wallet, $49, for Austin commuters"></label><button>Run</button></form>'
                    for profile in profiles:
                        body += '<h2>' + html.escape(profile['name']) + '</h2>'
                        body += '<pre>' + html.escape(json.dumps({k: profile[k] for k in ('role', 'personality', 'expertise', 'decision_rules')}, indent=2)) + '</pre>'
                    body += '<p>Agent CLI tools: see README, Agent tools.</p><h2>Demo facts</h2><pre>'
                    return self.respond(200, body + html.escape((root / 'facts/demo_facts.json').read_text()) + '</pre>')
                if path == '/run' and post:
                    size = int(self.headers.get('Content-Length', '0'))
                    if size <= 0 or size > 8192:
                        return self.respond(400, 'Invalid form size')
                    form = parse_qs(self.rfile.read(size).decode())
                    idea = form.get('idea', [''])[0].strip()
                    if not idea or len(idea) > 1000:
                        return self.respond(400, 'Enter one sentence with price and audience')
                    run_id = 'web_' + uuid4().hex
                    run_pipeline(idea, root / 'facts/demo_facts.json', root / 'agents', root / 'runs' / (run_id + '.json'))
                    self.send_response(303)
                    self.send_header('Location', '/run/' + run_id)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                match = re.fullmatch(r'/run/([A-Za-z0-9_-]+)(?:/(approve|export|receipt.json))?', path)
                if not match:
                    return self.respond(404, 'Run not found')
                run_id, action = match.groups()
                receipt_path = root / 'runs' / (run_id + '.json')
                receipt = load_receipt(receipt_path)
                if post and action == 'approve':
                    approve_receipt(receipt, 'web_human')
                    save_receipt(receipt, receipt_path)
                    return self.respond(200, '<p>Approved for export.</p><a href="/run/' + run_id + '">View run</a>')
                if post:
                    return self.respond(405, 'Method not allowed')
                if action == 'export':
                    # Shared binding gate without mutation or local output.
                    from .human_review import export_view
                    try:
                        view = export_view(receipt)
                    except ValueError as error:
                        return self.respond(403, str(error))
                    return self.respond(200, json.dumps(view, indent=2), 'application/json', True)
                if action == 'receipt.json':
                    return self.respond(200, json.dumps(receipt, indent=2), 'application/json')
                if action:
                    return self.respond(405, 'Method not allowed')
                body = '<h1>LaunchCrew run ' + run_id + '</h1>'
                for field in ('status', 'scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2', 'checker_v2', 'approval_state', 'summary', 'visual_verification', 'audit'):
                    body += '<h2>' + field + '</h2><pre>' + html.escape(json.dumps(receipt.get(field), indent=2)) + '</pre>'
                body += '<form method="post" action="/run/' + run_id + '/approve"><button>Approve for export</button></form>'
                body += '<p><a href="/run/' + run_id + '/receipt.json">Receipt JSON</a> | <a href="/run/' + run_id + '/export">Export pack JSON</a></p>'
                return self.respond(200, body)
            except FileNotFoundError:
                self.respond(404, 'Run not found')
            except ValueError:
                self.respond(400, 'Request refused: ValueError')
            except Exception as error:
                self.respond(500, type(error).__name__)

    return HTTPServer((host, port), Handler)


def main():
    # Container binding is an explicit deployment configuration, local is the default.
    server = create_server(os.environ.get('LAUNCHCREW_HOST', '127.0.0.1'),
                           int(os.environ.get('LAUNCHCREW_PORT', os.environ.get('PORT', '8765'))))
    print('LaunchCrew approval UI started', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
