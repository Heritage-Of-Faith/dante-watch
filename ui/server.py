#!/usr/bin/env python3
"""Tiny read-only web UI for dante-watch. Python 3.9 stdlib only, no root.

  python3 ui/server.py [--port 8787] [--logdir <dir>]

Serves ui/index.html and three JSON/SSE endpoints over today's log file
(<logdir>/YYYY-MM-DD.log, written by dante-watch.py):

  GET /              -> ui/index.html
  GET /api/status    -> running / iface / master / devices / counts
  GET /api/events    -> ?since=<n>  events with index >= n (default: last 200)
  GET /api/stream    -> text/event-stream of lines appended from now on

Never writes anything. Log lines it cannot parse are ignored.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = pathlib.Path(__file__).resolve().parent          # <repo>/ui
REPO = HERE.parent
DEFAULT_LOGDIR = REPO / "log"
INDEX = HERE / "index.html"

LEVELS = ("INFO", "NEW", "CLOCK", "PING", "LINK", "ERROR")
DEFAULT_TAIL = 200
PING_EVERY = 15.0       # SSE keep-alive comment interval
POLL_S = 0.5            # file poll interval for the stream

# "<ISO ts> <LEVEL><pad> <msg>" -- level padded to 5 so there may be >1 space
LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([A-Z]{2,5})\s+(.*)$")
DEVICE_RE = re.compile(r"^device\s+(\S+)\s+(\d+\.\d+\.\d+\.\d+)\s*$")
PING_RE = re.compile(r"^(\S+)\s+(\d+\.\d+\.\d+\.\d+)\s+(unreachable|back)\b")
MASTER_RE = re.compile(r"^PTP master now\s+(.+?)(?:,\s*was\b.*)?$")
START_RE = re.compile(r"^start on\s+(\S+)")

LOGDIR = DEFAULT_LOGDIR


# ---------------------------------------------------------------- log parsing

def today_log() -> pathlib.Path:
    return LOGDIR / (datetime.date.today().isoformat() + ".log")


def parse_line(line: str):
    """-> (ts, level, msg) or None for anything that is not a log line."""
    m = LINE_RE.match(line.rstrip("\r\n"))
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3).rstrip()


def read_lines(path: pathlib.Path):
    """Complete lines only (split on '\\n', like the stream counts them). A trailing
    partial line (watchdog mid-write) is left out so 'next' matches the stream index."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return None
    end = data.rfind("\n") + 1
    return data[:end].split("\n")[:-1] if end else []


def event_dict(i, parsed):
    ts, level, msg = parsed
    return {"i": i, "ts": ts, "level": level, "msg": msg}


def watchdog_running() -> bool:
    # A python process whose script is dante-watch.py. Not pgrep -f: that also
    # matches any shell/editor whose command line mentions the file name.
    try:
        r = subprocess.run(["ps", "-axo", "args="], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            argv = line.split()
            if len(argv) >= 2 and os.path.basename(argv[0]).startswith("python") \
                    and os.path.basename(argv[1]) == "dante-watch.py":
                return True
        return False
    except Exception:
        return False


def build_status():
    path = today_log()
    lines = read_lines(path)
    status = {
        "running": watchdog_running(),
        "log_file": str(path) if lines is not None else None,
        "iface": None,
        "master": None,
        "last_event_ts": None,
        "devices": {},
        "counts": {lv: 0 for lv in LEVELS},
    }
    if lines is None:
        return status
    devices = status["devices"]
    counts = status["counts"]
    for raw in lines:
        p = parse_line(raw)
        if not p:
            continue
        ts, level, msg = p
        status["last_event_ts"] = ts
        counts[level] = counts.get(level, 0) + 1
        if level == "INFO":
            m = START_RE.match(msg)
            if m:
                status["iface"] = m.group(1)
                devices.clear()          # a restart rediscovers; forget the old set
                status["master"] = None
                continue
        if level in ("INFO", "NEW"):
            m = DEVICE_RE.match(msg)
            if m:
                devices[m.group(1)] = {"ip": m.group(2), "up": True}
                continue
        if level == "CLOCK":
            m = MASTER_RE.match(msg)
            if m:
                status["master"] = m.group(1).strip()
                continue
        if level == "PING":
            m = PING_RE.match(msg)
            if m:
                name, ip, state = m.groups()
                d = devices.setdefault(name, {"ip": ip, "up": True})
                d["ip"] = ip
                d["up"] = (state == "back")
    return status


def build_events(since):
    lines = read_lines(today_log()) or []
    n = len(lines)
    start = max(0, n - DEFAULT_TAIL) if since is None else max(0, since)
    events = []
    for i in range(start, n):
        p = parse_line(lines[i])
        if p:
            events.append(event_dict(i, p))
    return {"next": n, "events": events}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "dante-watch-ui/1"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):      # quiet; errors still go to stderr
        if not self.path.startswith("/api/"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, code=404):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routing
    def do_GET(self):
        url = urlparse(self.path)
        route = url.path.rstrip("/") or "/"
        try:
            if route in ("/", "/index.html"):
                return self.serve_index()
            if route == "/api/status":
                return self.send_json(build_status())
            if route == "/api/events":
                return self.serve_events(parse_qs(url.query))
            if route == "/api/stream":
                return self.serve_stream()
            return self.send_text("not found", 404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def serve_index(self):
        try:
            body = INDEX.read_bytes()
        except FileNotFoundError:
            return self.send_text("ui/index.html missing", 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_events(self, qs):
        since = None
        raw = qs.get("since", [None])[0]
        if raw not in (None, ""):
            try:
                since = int(raw)
            except ValueError:
                return self.send_json({"error": "since must be an integer"}, 400)
        self.send_json(build_events(since))

    def serve_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.write(b": connected\n\n")
        self.wfile.flush()

        path = today_log()
        f = None
        index = 0           # line number of the next line we will read
        skip_existing = True   # on connect, start after what is already there
        last_ping = time.time()
        try:
            while True:
                # roll over at midnight: new file, read it from the top
                cur = today_log()
                if cur != path:
                    if f:
                        f.close()
                    f, path, index, skip_existing = None, cur, 0, False
                if f is None:
                    try:
                        f = open(path, "r", encoding="utf-8", errors="replace")
                    except (FileNotFoundError, PermissionError):
                        f = None
                        skip_existing = False   # file not there yet: everything it gets is new
                    else:
                        if skip_existing:
                            with open(path, "rb") as g:
                                data = g.read()
                            end = data.rfind(b"\n") + 1      # after the last complete line
                            index = data.count(b"\n", 0, end)
                            f.seek(end)
                            skip_existing = False
                if f is not None:
                    try:
                        if os.path.getsize(path) < f.tell():
                            f.seek(0); index = 0        # truncated: start over
                    except OSError:
                        f.close(); f = None
                    while f is not None:
                        pos = f.tell()
                        line = f.readline()
                        if not line:
                            break
                        if not line.endswith("\n"):
                            f.seek(pos)                  # partial write; retry next poll
                            break
                        p = parse_line(line)
                        if p:
                            self.wfile.write(("data: " + json.dumps(event_dict(index, p)) + "\n\n").encode("utf-8"))
                            self.wfile.flush()
                        index += 1
                now = time.time()
                if now - last_ping >= PING_EVERY:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = now
                time.sleep(POLL_S)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            if f:
                f.close()


# ---------------------------------------------------------------- main

def main():
    global LOGDIR
    ap = argparse.ArgumentParser(description="dante-watch web UI")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--logdir", default=str(DEFAULT_LOGDIR))
    args = ap.parse_args()
    LOGDIR = pathlib.Path(args.logdir).expanduser().resolve()

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    print("dante-watch ui: http://0.0.0.0:%d  logdir=%s" % (args.port, LOGDIR), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
