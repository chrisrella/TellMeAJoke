#!/usr/bin/env python3
"""
One-time YouTube OAuth setup. Opens a browser to authorize your Google account,
then saves the refresh token to config.json.

Run this once:
    python3 caption-automation/youtube_auth.py
"""

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SECRETS = Path.home() / "TellMeAJoke/client_secrets.json"
CONFIG  = Path.home() / "TellMeAJoke/config.json"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    if not SECRETS.exists():
        print(f"Error: client_secrets.json not found at {SECRETS}")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS), SCOPES)
    creds = flow.run_local_server(port=0)

    with open(CONFIG) as f:
        config = json.load(f)

    config["youtube_client_id"]     = creds.client_id
    config["youtube_client_secret"] = creds.client_secret
    config["youtube_refresh_token"] = creds.refresh_token

    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=4)

    print("\nYouTube credentials saved to config.json.")
    print("You won't need to run this again unless you revoke access.")


if __name__ == "__main__":
    main()
