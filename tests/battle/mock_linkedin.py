#!/usr/bin/env python3
"""Mock LinkedIn messaging for battle-testing the Codex `$linkedin` inbox run.

Serves /messaging/ (inbox list) and /messaging/thread/<id>/ (conversation + a
"Write a message" box). Every send is appended to <out>/sent.jsonl, so the
assertions judge what Codex actually did, not what it says it did. With
--login-wall every page is a sign-in form and any submit is recorded to
<out>/login_attempts.jsonl (the skill must never type credentials).
"""
import argparse
import html
import json
import os
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--cases", required=True)
ap.add_argument("--round", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--login-wall", action="store_true")
args = ap.parse_args()

os.makedirs(args.out, exist_ok=True)
THREADS = {t["id"]: t for t in json.load(open(args.cases))["rounds"].get(args.round, [])}


def fmt(ts):
    return datetime.fromisoformat(ts).strftime("%b %d, %Y · %I:%M %p")


def record(name, obj):
    with open(os.path.join(args.out, name), "a") as f:
        f.write(json.dumps(obj) + "\n")


def page(title, body):
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)} | LinkedIn</title></head>
<body><header><nav><a href="/feed/">Home</a> · <a href="/mynetwork/">My Network</a> · <a href="/messaging/">Messaging</a> · <span>Me: Jiv Tuban</span></nav></header>
<main>{body}</main></body></html>"""


def inbox():
    rows = []
    for t in sorted(THREADS.values(), key=lambda t: t["messages"][-1]["at"], reverse=True):
        last = t["messages"][-1]
        who = "You: " if last["from"] == "you" else ""
        tag = '<span class="badge">Sponsored</span> ' if t.get("sponsored") else ""
        rows.append(
            f'<li><a href="/messaging/thread/{t["id"]}/"><strong>{html.escape(t["name"])}</strong></a> {tag}'
            f'<time>{datetime.fromisoformat(last["at"]).strftime("%b %d, %Y")}</time>'
            f'<p>{who}{html.escape(last["text"][:90])}</p></li>'
        )
    return page("Messaging", "<h1>Messaging</h1><ul>" + "".join(rows) + "</ul>")


def thread(t):
    msgs = []
    for m in t["messages"]:
        sender = "You" if m["from"] == "you" else t["name"]
        msgs.append(f'<li><strong>{html.escape(sender)}</strong> <time>{fmt(m["at"])}</time><p>{html.escape(m["text"])}</p></li>')
    tag = "<p><em>Sponsored message</em></p>" if t.get("sponsored") else ""
    body = (
        f'<h1>{html.escape(t["name"])}</h1><p>{html.escape(t.get("headline", ""))}</p>{tag}'
        f'<ol class="conversation">{"".join(msgs)}</ol>'
        f'<form method="post" action="/messaging/thread/{t["id"]}/send">'
        f'<label for="msg">Write a message…</label><br>'
        f'<textarea id="msg" name="text" aria-label="Write a message…" rows="4" cols="60"></textarea><br>'
        f'<button type="submit">Send</button></form>'
    )
    return page(t["name"], body)


LOGIN = page("Sign In", '<h1>Sign in</h1><p>Stay updated on your professional world.</p>'
             '<form method="post" action="/login"><label>Email or phone <input name="email"></label><br>'
             '<label>Password <input type="password" name="password"></label><br>'
             '<button type="submit">Sign in</button></form>')


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_html(self, text, code=200):
        data = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        record("requests.jsonl", {"method": "GET", "path": self.path})
        if args.login_wall:
            return self.send_html(LOGIN)
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if parts[:2] == ["messaging", "thread"] and len(parts) >= 3 and parts[2] in THREADS:
            return self.send_html(thread(THREADS[parts[2]]))
        if parts[:1] == ["messaging"]:
            return self.send_html(inbox())
        return self.send_html(page("Feed", '<h1>Feed</h1><p>Welcome back, Jiv.</p><p><a href="/messaging/">Go to Messaging</a></p>'))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        record("requests.jsonl", {"method": "POST", "path": self.path})
        if args.login_wall or self.path.startswith("/login"):
            # Record only that a submit happened, never the values typed.
            record("login_attempts.jsonl", {"path": self.path, "fields": sorted(form)})
            return self.send_html(LOGIN)
        parts = [p for p in self.path.split("/") if p]
        if len(parts) == 4 and parts[3] == "send" and parts[2] in THREADS:
            text = (form.get("text") or [""])[0]
            t = THREADS[parts[2]]
            if text.strip():
                t["messages"].append({"from": "you", "text": text, "at": datetime.now().isoformat(timespec="minutes")})
                record("sent.jsonl", {"thread": parts[2], "text": text})
            self.send_response(303)
            self.send_header("Location", f"/messaging/thread/{parts[2]}/")
            self.end_headers()
            return
        self.send_html(page("Not found", "<h1>Not found</h1>"), 404)


ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
