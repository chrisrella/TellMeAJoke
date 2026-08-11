#!/usr/bin/env python3
"""
One-time TikTok OAuth setup. Opens a browser to authorize your TikTok account,
then saves the access and refresh tokens to config.json.

Run this once (and again whenever the refresh token expires):
    python3 caption-automation/tiktok_auth.py
"""

import hashlib
import base64
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

CONFIG       = Path.home() / "TellMeAJoke/config.json"
REDIRECT_URI = "http://localhost:8080/"
TOKEN_URL    = "https://open.tiktokapis.com/v2/oauth/token/"
AUTH_URL     = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES       = "video.upload,video.publish"

def load_config() -> dict:
    with open(CONFIG) as f:
        return json.load(f)


def save_config(config: dict) -> None:
    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=4)


def pkce_pair() -> tuple[str, str]:
    # 43-char urlsafe verifier — minimum RFC length, standard format TikTok expects
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
    print(f"  code     : {code[:20]}...")
    r = requests.post(TOKEN_URL, data={
        "client_key":    client_key,
        "client_secret": client_secret,
        "code":          code,
        "grant_type":    "authorization_code",
        "redirect_uri":  REDIRECT_URI,
        "code_verifier": verifier,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    print(f"  response : {r.status_code} {r.text[:200]}")
    r.raise_for_status()
    return r.json()


def main() -> None:
    config       = load_config()
    client_key   = config.get("tiktok_client_key")
    client_secret = config.get("tiktok_client_secret")

    if not client_key or not client_secret:
        print("Error: tiktok_client_key and tiktok_client_secret must be in config.json")
        sys.exit(1)

    state             = secrets.token_urlsafe(16)
    verifier, challenge = pkce_pair()
    print("Verifier :", verifier)
    print("Challenge:", challenge)
    auth_url          = build_auth_url(client_key, state, challenge)

    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            captured["code"]  = qs.get("code",  [None])[0]
            captured["state"] = qs.get("state", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Authorized! You can close this tab.</h2>")

        def log_message(self, *args):
            pass  # suppress request logs

    server = HTTPServer(("localhost", 8080), Handler)

    print(f"\nOpening TikTok authorization in your browser...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for authorization...")
    server.handle_request()

    if not captured.get("code"):
        print("No code received. Authorization may have failed.")
        sys.exit(1)

    if captured.get("state") != state:
        print("State mismatch — possible CSRF. Aborting.")
        sys.exit(1)

    print("Exchanging code for tokens...")
    try:
        tokens = exchange_code(captured["code"], verifier, client_key, client_secret)
    except requests.HTTPError as e:
        print(f"Token exchange failed: {e.response.text}")
        sys.exit(1)

    access_token  = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    if not access_token:
        print(f"Unexpected response: {tokens}")
        sys.exit(1)

    config["tiktok_access_token"]  = access_token
    config["tiktok_refresh_token"] = refresh_token or ""
    save_config(config)

    print("\nTikTok credentials saved to config.json.")
    print(f"Access token expires in: {tokens.get('expires_in', '?')} seconds")
    print("You won't need to run this again until the refresh token expires.")


if __name__ == "__main__":
    main()
