#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SpringBlox Tools — live value server.
Serves the static site from ../site and exposes:
  GET  /api/values   -> combined live values JSON
  GET  /api/status   -> pipeline status
  POST /api/refresh  -> trigger an immediate re-scrape (?game=mm2|adoptme|bloxfruits|all)

A background scheduler re-scrapes each source automatically:
  Blox Fruits every 3h, MM2 & Adopt Me every 12h (configurable in scrape.GAME_META).
"""
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.abspath(os.path.join(PIPELINE_DIR, '..', 'site'))
VALUES_FILE = os.path.join(SITE_DIR, 'data', 'values.json')
PORT = 8000

sys.path.insert(0, PIPELINE_DIR)
import scrape  # noqa: E402

STATUS = {
    'running': False,
    'lastError': None,
    'lastRefreshedAt': None,
    'lastGames': [],
    'serverStartedAt': scrape.now_iso(),
}
_status_lock = threading.Lock()
_game_locks = {g: threading.Lock() for g in scrape.GAMES}
_game_last_run = {g: 0.0 for g in scrape.GAMES}


def _read_values():
    try:
        with open(VALUES_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        return {'generatedAt': None, 'games': {}, 'changes': {}, 'error': str(e)}


def _game_age_seconds(payload, game):
    try:
        g = payload['games'][game]
        ts = g['generatedAt'].replace('Z', '+00:00')
        dt = datetime.fromisoformat(ts)
        return time.time() - dt.timestamp()
    except Exception:
        return float('inf')


def refresh_game(game):
    """Scrape one game and merge into values.json. Returns item count."""
    with _game_locks[game]:
        items = scrape.scrape_game(game)
        scrape.build_outputs({game: items})
        _game_last_run[game] = time.time()
        return len(items)


def _scheduler_loop():
    while True:
        try:
            payload = _read_values()
            for game in scrape.GAMES:
                hours = scrape.GAME_META[game]['refreshHours']
                if _game_age_seconds(payload, game) > hours * 3600:
                    print(f"[scheduler] refreshing {game} (older than {hours}h)", flush=True)
                    try:
                        with _status_lock:
                            STATUS['running'] = True
                            STATUS['lastGames'] = [game]
                        n = refresh_game(game)
                        print(f"[scheduler] {game}: {n} items refreshed", flush=True)
                        with _status_lock:
                            STATUS['lastRefreshedAt'] = scrape.now_iso()
                            STATUS['lastError'] = None
                    except Exception as e:  # noqa: BLE001
                        print(f"[scheduler] {game} FAILED: {e}", flush=True)
                        with _status_lock:
                            STATUS['lastError'] = f"{game}: {e}"
                    finally:
                        with _status_lock:
                            STATUS['running'] = False
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] loop error: {e}", flush=True)
        time.sleep(300)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_DIR, **kwargs)

    def log_message(self, fmt, *args):  # quiet access log
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # allow the sandboxed preview (opaque origin) to fetch everything
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        # never let the browser serve a stale page copy
        if self.path in ('/', '/index.html') or self.path.startswith('/index.html'):
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/values':
            return self._send_json(_read_values())
        if parsed.path == '/api/status':
            payload = _read_values()
            per_game = {g: payload['games'][g]['generatedAt'] for g in payload.get('games', {})}
            counts = {g: payload['games'][g]['count'] for g in payload.get('games', {})}
            with _status_lock:
                st = dict(STATUS)
            st['perGameGeneratedAt'] = per_game
            st['counts'] = counts
            return self._send_json(st)
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/refresh':
            qs = urllib.parse.parse_qs(parsed.query)
            game = (qs.get('game', ['all'])[0] or 'all').lower()
            games = scrape.GAMES if game == 'all' else ([game] if game in scrape.GAMES else None)
            if not games:
                return self._send_json({'error': f'unknown game: {game}'}, 400)
            already = any((_game_locks[g].locked() for g in games))
            if already:
                return self._send_json({'status': 'busy', 'games': games}, 202)

            def work():
                try:
                    with _status_lock:
                        STATUS['running'] = True
                        STATUS['lastGames'] = games
                    for g in games:
                        n = refresh_game(g)
                        print(f"[refresh] {g}: {n} items", flush=True)
                    with _status_lock:
                        STATUS['lastRefreshedAt'] = scrape.now_iso()
                        STATUS['lastError'] = None
                except Exception as e:  # noqa: BLE001
                    with _status_lock:
                        STATUS['lastError'] = str(e)
                    print(f"[refresh] failed: {e}", flush=True)
                finally:
                    with _status_lock:
                        STATUS['running'] = False

            threading.Thread(target=work, daemon=True).start()
            return self._send_json({'status': 'started', 'games': games}, 202)
        return self._send_json({'error': 'not found'}, 404)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    os.chdir(SITE_DIR)
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    srv = Server(('0.0.0.0', PORT), Handler)
    print(f"SpringBlox live server on :{PORT} serving {SITE_DIR}", flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
