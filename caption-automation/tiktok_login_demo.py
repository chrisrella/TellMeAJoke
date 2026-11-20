#!/usr/bin/env python3
"""
TikTok OAuth demo server for TikTok API review.

Runs at http://localhost:8080/ and serves a full end-to-end demo:
  GET /           → landing page with "Connect with TikTok" button
  GET /connect    → generates PKCE, redirects to TikTok OAuth
  GET /?code=...  → handles callback, exchanges code for token, saves to config.json

Usage:
    python3 caption-automation/tiktok_login_demo.py

After authorizing in the browser, the access token is saved to config.json.
You can then post a video with:
    python3 caption-automation/tiktok.py "clip.mp4" --private
"""

import hashlib
import base64
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

CONFIG        = Path.home() / "TellMeAJoke/config.json"
REDIRECT_URI  = "http://127.0.0.1:8080/"
TOKEN_URL     = "https://open.tiktokapis.com/v2/oauth/token/"
AUTH_URL      = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES        = "user.info.basic,video.upload,video.publish"

# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tell Me A Joke — Connect with TikTok</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f0f0f;
    color: #fff;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .card {
    background: #1a1a1a;
    border-radius: 20px;
    padding: 56px 48px;
    max-width: 480px;
    width: 90%;
    text-align: center;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }
  .logo { font-size: 48px; margin-bottom: 12px; }
  h1 { font-size: 26px; font-weight: 700; margin-bottom: 8px; }
  .subtitle {
    color: #888;
    font-size: 15px;
    line-height: 1.5;
    margin-bottom: 36px;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: #000;
    color: #fff;
    border: 2px solid #fff;
    padding: 16px 32px;
    border-radius: 50px;
    font-size: 16px;
    font-weight: 700;
    text-decoration: none;
    transition: background 0.2s, color 0.2s;
    cursor: pointer;
  }
  .btn:hover { background: #fff; color: #000; }
  .tiktok-icon { width: 22px; height: 22px; fill: currentColor; }
  .scopes {
    margin-top: 28px;
    font-size: 12px;
    color: #555;
    line-height: 1.6;
  }
  .scope-pill {
    display: inline-block;
    background: #2a2a2a;
    border-radius: 100px;
    padding: 3px 10px;
    margin: 2px;
    color: #aaa;
    font-size: 11px;
  }
</style>
</head>
<body>
<div class="card">
  <div class="logo">🎤</div>
  <h1>Tell Me A Joke</h1>
  <p class="subtitle">
    Connect your TikTok account to enable automated video posting.<br>
    Your videos will be published using the TikTok Content Posting API.
  </p>
  <a class="btn" href="/connect">
    <svg class="tiktok-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5
               2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1V9.01
               a6.33 6.33 0 00-.79-.05 6.34 6.34 0 00-6.34 6.34 6.34 6.34 0 006.34 6.34
               6.34 6.34 0 006.33-6.34V8.69a8.11 8.11 0 004.74 1.52V6.76a4.84 4.84 0 01-1-.07z"/>
    </svg>
    Connect with TikTok
  </a>
  <div class="scopes">
    Requesting permissions:<br>
    <span class="scope-pill">user.info.basic</span>
    <span class="scope-pill">video.upload</span>
    <span class="scope-pill">video.publish</span>
  </div>
</div>
</body>
</html>"""

SUCCESS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Connected — Tell Me A Joke</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f0f0f;
    color: #fff;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .card {{
    background: #1a1a1a;
    border-radius: 20px;
    padding: 56px 48px;
    max-width: 480px;
    width: 90%;
    text-align: center;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }}
  .check {{ font-size: 56px; margin-bottom: 16px; }}
  h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 10px; color: #4ade80; }}
  p {{ color: #888; font-size: 15px; line-height: 1.6; }}
  .token-box {{
    margin-top: 28px;
    background: #0f0f0f;
    border-radius: 12px;
    padding: 16px 20px;
    text-align: left;
    font-family: monospace;
    font-size: 12px;
    color: #4ade80;
    word-break: break-all;
  }}
  .label {{ color: #555; font-size: 11px; margin-bottom: 4px; }}
</style>
</head>
<body>
<div class="card">
  <div class="check">✅</div>
  <h1>TikTok Connected!</h1>
  <p>Your account is now linked. Access token saved to config.json.<br>
     You can close this window and start posting.</p>
  <div class="token-box">
    <div class="label">ACCESS TOKEN (truncated)</div>
    {token_preview}
  </div>
</div>
</body>
</html>"""

ERROR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Error — Tell Me A Joke</title>
<style>
  body {{ font-family: sans-serif; background:#0f0f0f; color:#fff;
          display:flex; align-items:center; justify-content:center; min-height:100vh; }}
  .card {{ background:#1a1a1a; border-radius:16px; padding:40px; max-width:420px;
           text-align:center; }}
  h1 {{ color:#f87171; margin-bottom:12px; }}
  p {{ color:#888; font-size:14px; }}
</style>
</head>
<body>
<div class="card">
  <h1>⚠️ Authorization Failed</h1>
  <p>{error}</p>
</div>
</body>
</html>"""

# ---------------------------------------------------------------------------
# OAuth helpers (copied from tiktok_auth.py)
# ---------------------------------------------------------------------------

def pkce_pair() -> tuple[str, str]:
    verifier  = secrets.token_urlsafe(32)[:43]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(client_key: str, state: str, challenge: str) -> str:
    params = {
        "client_key":            client_key,
        "response_type":         "code",
        "scope":                 SCOPES,
        "redirect_uri":          REDIRECT_URI,
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, verifier: str, client_key: str, client_secret: str) -> dict:
    r = requests.post(TOKEN_URL, data={
        "client_key":    client_key,
        "client_secret": client_secret,
        "code":          code,
        "grant_type":    "authorization_code",
        "redirect_uri":  REDIRECT_URI,
        "code_verifier": verifier,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DemoHandler(BaseHTTPRequestHandler):
    # Shared state across requests (class-level)
    oauth_state   = ""
    oauth_verifier = ""
    client_key    = ""
    client_secret = ""
    done_event    = None   # threading.Event, signals main thread to exit

    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        # ── Landing page ──────────────────────────────────────────────────
        if parsed.path == "/" and not qs.get("code") and not qs.get("error"):
            self._send_html(LANDING_HTML)

        # ── Initiate OAuth ────────────────────────────────────────────────
        elif parsed.path == "/connect":
            state              = secrets.token_urlsafe(16)
            verifier, challenge = pkce_pair()
            DemoHandler.oauth_state    = state
            DemoHandler.oauth_verifier = verifier
            auth_url = build_auth_url(DemoHandler.client_key, state, challenge)
            self.send_response(302)
            self.send_header("Location", auth_url)
            self.end_headers()

        # ── OAuth callback ────────────────────────────────────────────────
        elif parsed.path == "/" and qs.get("code"):
            code          = qs["code"][0]
            returned_state = qs.get("state", [None])[0]

            if returned_state != DemoHandler.oauth_state:
                self._send_html(ERROR_HTML.format(error="State mismatch — possible CSRF attack."), 400)
                return

            try:
                tokens = exchange_code(
                    code,
                    DemoHandler.oauth_verifier,
                    DemoHandler.client_key,
                    DemoHandler.client_secret,
                )
            except requests.HTTPError as e:
                self._send_html(ERROR_HTML.format(error=f"Token exchange failed: {e.response.text}"), 500)
                return

            access_token  = tokens.get("access_token", "")
            refresh_token = tokens.get("refresh_token", "")

            # Save to config.json
            config_path = Path.home() / "TellMeAJoke/config.json"
            with open(config_path) as f:
                config = json.load(f)
            config["tiktok_access_token"]  = access_token
            config["tiktok_refresh_token"] = refresh_token
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)

            token_preview = access_token[:40] + "…" if access_token else "(none)"
            self._send_html(SUCCESS_HTML.format(token_preview=token_preview))

            # Signal main thread to shut down after response is sent
            if DemoHandler.done_event:
                threading.Timer(1.5, DemoHandler.done_event.set).start()

        elif qs.get("error"):
            err = qs.get("error_description", [qs["error"][0]])[0]
            self._send_html(ERROR_HTML.format(error=err), 400)

        else:
            self.send_response(404)
            self.end_headers()

    def _send_html(self, body: str, status: int = 200) -> None:
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        pass  # keep output clean for demo


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config_path = Path.home() / "TellMeAJoke/config.json"
    if not config_path.exists():
        print("Error: config.json not found")
        sys.exit(1)
    with open(config_path) as f:
        config = json.load(f)

    client_key    = config.get("tiktok_client_key")
    client_secret = config.get("tiktok_client_secret")
    if not client_key or not client_secret:
        print("Error: tiktok_client_key and tiktok_client_secret must be in config.json")
        sys.exit(1)

    DemoHandler.client_key    = client_key
    DemoHandler.client_secret = client_secret
    DemoHandler.done_event    = threading.Event()

    server = HTTPServer(("127.0.0.1", 8080), DemoHandler)
    server.timeout = 1.0  # check done_event every second

    local_url = "http://127.0.0.1:8080/"
    print(f"\n{'─'*50}")
    print(f"  Tell Me A Joke — TikTok OAuth Demo")
    print(f"{'─'*50}")
    print(f"  Opening: {local_url}")
    print(f"  Also open: https://chrisrella.github.io/TellMeAJoke/tiktok-connect.html")
    print(f"  Press Ctrl+C to stop.\n")
    webbrowser.open(local_url)

    # Serve until OAuth completes or Ctrl+C
    while not DemoHandler.done_event.is_set():
        server.handle_request()

    print("\nTikTok credentials saved to config.json.")
    print("Next step: python3 caption-automation/tiktok.py \"clip.mp4\" --private\n")


if __name__ == "__main__":
    main()
