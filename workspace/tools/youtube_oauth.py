#!/usr/bin/env python3
"""Get Google OAuth token for YouTube uploads."""
import webbrowser
import urllib.parse
import http.server
import threading
import json

# You need to create a Google Cloud project and get these credentials
# Go to: https://console.cloud.google.com/apis/credentials
CLIENT_ID = "YOUR_CLIENT_ID"  # Replace with your OAuth client ID
CLIENT_SECRET = "YOUR_CLIENT_SECRET"  # Replace with your OAuth client secret
REDIRECT_URI = "http://localhost:8088/callback"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_auth_url():
    """Generate Google OAuth URL."""
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent"
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

def exchange_code(code):
    """Exchange authorization code for tokens."""
    data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    r = requests.post("https://oauth2.googleapis.com/token", data=data)
    return r.json()

if __name__ == "__main__":
    print("=== Google OAuth Setup ===")
    print(f"\n1. Go to this URL:\n{get_auth_url()}")
    print(f"\n2. After authorization, paste the code from the callback URL")
    code = input("\nAuthorization code: ").strip()
    if code:
        tokens = exchange_code(code)
        print(f"\nAccess Token: {tokens.get('access_token', 'ERROR')}")
        print(f"Refresh Token: {tokens.get('refresh_token', 'ERROR')}")
        print("\nSave these tokens!")
