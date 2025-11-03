"""
WHOOP OAuth Authentication Script

This script helps you authenticate with WHOOP and get access/refresh tokens.
It will:
1. Open your browser to WHOOP's authorization page
2. You log in and authorize the app
3. WHOOP redirects back with an authorization code
4. This script exchanges the code for access + refresh tokens
5. Saves tokens to the database
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import webbrowser
import json
import time
import secrets
from urllib.parse import urlparse, parse_qs
from integrations.whoop_client import WhoopClient
from integrations.db import set_user_setting

# WHOOP OAuth Configuration
# Get these from https://developer.whoop.com after creating an application
CLIENT_ID = "e5f4865c-bb54-4b81-9919-a5ea3954b650"  # Replace with your WHOOP client ID
CLIENT_SECRET = "97ed9713ba6d7e7f4ab0cfaa1306d99d337957f2396fefd97fcbbe5ff8cf4d87"  # Replace with your WHOOP client secret
REDIRECT_URI = "http://localhost:8501/"  # Must match what you set in WHOOP developer portal

print("=" * 80)
print("WHOOP AUTHENTICATION")
print("=" * 80)
print()
print("This script will help you authenticate with WHOOP API.")
print()

# Check if credentials are configured
if CLIENT_ID == "your_client_id_here" or CLIENT_SECRET == "your_client_secret_here":
    print("ERROR: You need to configure your WHOOP credentials first!")
    print()
    print("Steps:")
    print("1. Go to https://developer.whoop.com")
    print("2. Create an application")
    print("3. Get your Client ID and Client Secret")
    print("4. Edit this file (scripts/whoop_auth.py) and replace:")
    print("   - CLIENT_ID")
    print("   - CLIENT_SECRET")
    print("   - REDIRECT_URI (if different)")
    print()
    sys.exit(1)

# Step 1: Generate authorization URL with state parameter
state = secrets.token_urlsafe(32)  # Generate random state for security
auth_url = (
    f"https://api.prod.whoop.com/oauth/oauth2/auth?"
    f"client_id={CLIENT_ID}&"
    f"redirect_uri={REDIRECT_URI}&"
    f"response_type=code&"
    f"state={state}&"
    f"scope=read:recovery read:sleep read:workout read:profile read:body_measurement offline"
)

print("Step 1: Opening WHOOP authorization page in your browser...")
print()
print("If the browser doesn't open automatically, copy this URL:")
print(auth_url)
print()

# Open browser
webbrowser.open(auth_url)

print("Step 2: After authorizing, you'll be redirected to:")
print(f"  {REDIRECT_URI}?code=XXXXXX")
print()
print("The page may show an error (that's OK - we just need the code from the URL)")
print()

# Get authorization code from user
auth_code = input("Paste the FULL redirect URL here (or just the 'code' parameter): ").strip()

# Extract code if they pasted the full URL
if auth_code.startswith("http"):
    parsed = urlparse(auth_code)
    params = parse_qs(parsed.query)

    # Verify state parameter for security
    if 'state' in params:
        returned_state = params['state'][0]
        if returned_state != state:
            print()
            print("ERROR: State parameter mismatch - possible security issue")
            sys.exit(1)

    if 'code' in params:
        auth_code = params['code'][0]
    else:
        print()
        print("ERROR: Could not find 'code' parameter in URL")
        if 'error' in params:
            print(f"Error: {params['error'][0]}")
            print(f"Description: {params.get('error_description', [''])[0]}")
        sys.exit(1)

print()
print(f"Authorization code: {auth_code[:20]}...")
print()

# Step 3: Exchange code for tokens
print("Step 3: Exchanging authorization code for tokens...")
print()

client = WhoopClient()

try:
    # Exchange code for tokens
    token_response = client._exchange_code_for_token(auth_code, REDIRECT_URI)

    access_token = token_response.get('access_token')
    refresh_token = token_response.get('refresh_token')
    expires_in = token_response.get('expires_in', 3600)

    if not access_token or not refresh_token:
        print("ERROR: Failed to get tokens from WHOOP")
        print(f"Response: {token_response}")
        sys.exit(1)

    print("✅ Successfully got tokens!")
    print()

    # Step 4: Save tokens to database
    print("Step 4: Saving tokens to database...")

    # Save tokens using user_settings table
    set_user_setting('whoop_access_token', access_token)
    set_user_setting('whoop_refresh_token', refresh_token)
    set_user_setting('whoop_token_expires_at', str(int(time.time()) + expires_in))

    print("✅ Tokens saved to database!")
    print()

    # Step 4b: Update secrets.toml file
    print("Step 4b: Updating .streamlit/secrets.toml...")

    secrets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.streamlit')
    secrets_file = os.path.join(secrets_dir, 'secrets.toml')

    # Create .streamlit directory if it doesn't exist
    os.makedirs(secrets_dir, exist_ok=True)

    # Read existing secrets if file exists
    existing_secrets = {}
    if os.path.exists(secrets_file):
        with open(secrets_file, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    existing_secrets[key.strip()] = value.strip()

    # Update WHOOP tokens
    existing_secrets['WHOOP_ACCESS_TOKEN'] = f'"{access_token}"'
    existing_secrets['WHOOP_REFRESH_TOKEN'] = f'"{refresh_token}"'
    existing_secrets['WHOOP_CLIENT_ID'] = f'"{CLIENT_ID}"'
    existing_secrets['WHOOP_CLIENT_SECRET'] = f'"{CLIENT_SECRET}"'

    # Write back to secrets.toml
    with open(secrets_file, 'w') as f:
        f.write("# Streamlit secrets configuration\n")
        f.write("# Auto-updated by whoop_auth.py\n\n")
        for key, value in existing_secrets.items():
            f.write(f"{key} = {value}\n")

    print("✅ secrets.toml updated!")
    print()

    # Step 5: Test the tokens
    print("Step 5: Testing tokens by fetching your profile...")
    print()

    # Create a new client instance with the fresh tokens
    client.access_token = access_token
    client.refresh_token = refresh_token
    client.headers["Authorization"] = f"Bearer {access_token}"

    try:
        profile = client.get_user_profile()

        if profile:
            print("✅ Authentication successful!")
            print()
            print(f"User ID: {profile.get('user_id')}")
            print(f"First Name: {profile.get('first_name')}")
            print(f"Last Name: {profile.get('last_name')}")
            print()
            print("You can now run: python integrations/whoop_sync.py")
            print()
        else:
            print("⚠️ Could not fetch profile. Tokens saved but may not be working.")
            print()
    except Exception as e:
        print(f"⚠️ Could not test authentication: {e}")
        print("Tokens are saved. Try running: python integrations/whoop_sync.py")
        print()

except Exception as e:
    print(f"❌ ERROR: {e}")
    print()
    print("If you get a 400 Bad Request error, the authorization code may have expired.")
    print("Authorization codes are single-use and expire quickly.")
    print("Please run this script again to get a new code.")
    print()
    sys.exit(1)

print("=" * 80)
print("AUTHENTICATION COMPLETE")
print("=" * 80)
