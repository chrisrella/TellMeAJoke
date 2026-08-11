#!/usr/bin/env python3
"""
Exchange a short-lived Facebook user token for a long-lived page token (~60 days).

Run this whenever the facebook_page_token in config.json expires:
    python3 caption-automation/facebook_auth.py

You'll need a fresh short-lived user token from:
    https://developers.facebook.com/tools/explorer
    (Generate with: pages_show_list, pages_manage_posts, pages_read_engagement, pages_read_user_content)
"""

import json
import sys
from pathlib import Path

import requests

CONFIG = Path.home() / "TellMeAJoke/config.json"
API    = "https://graph.facebook.com/v19.0"


def main() -> None:
    with open(CONFIG) as f:
        config = json.load(f)

    app_id     = config.get("instagram_app_id")
    app_secret = config.get("instagram_app_secret")
    page_id    = config.get("facebook_page_id")

    if not all([app_id, app_secret, page_id]):
        print("Error: instagram_app_id, instagram_app_secret, and facebook_page_id must be in config.json")
        sys.exit(1)

    print("Paste a short-lived user token from https://developers.facebook.com/tools/explorer")
    print("(needs: pages_show_list, pages_manage_posts, pages_read_engagement, pages_read_user_content)\n")
    short_token = input("Short-lived user token: ").strip()

    # Exchange for long-lived user token (~60 days)
    print("\nExchanging for long-lived token...")
    r = requests.get(f"{API}/oauth/access_token", params={
        "grant_type":        "fb_exchange_token",
        "client_id":         app_id,
        "client_secret":     app_secret,
        "fb_exchange_token": short_token,
    })
    if not r.ok:
        print(f"Exchange failed: {r.text}")
        sys.exit(1)
    long_user_token = r.json()["access_token"]
    print("  Got long-lived user token.")

    # Get the page access token using the long-lived user token
    print("Getting page token...")
    r = requests.get(f"{API}/{page_id}", params={
        "fields":       "name,access_token",
        "access_token": long_user_token,
    })
    if not r.ok:
        print(f"Page token fetch failed: {r.text}")
        sys.exit(1)
    data       = r.json()
    page_token = data.get("access_token")
    page_name  = data.get("name")

    if not page_token:
        print(f"No access_token in response: {data}")
        sys.exit(1)

    print(f"  Got page token for: {page_name}")

    config["facebook_page_token"] = page_token
    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=4)

    print(f"\nSaved to config.json. Token valid for ~60 days.")
    print(f"Run this script again when posting fails with a token expiry error.")


if __name__ == "__main__":
    main()
