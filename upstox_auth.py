import os
import requests
from urllib.parse import urlencode, urlparse, parse_qs
from core.config import settings

def main():
    api_key = settings.UPSTOX_API_KEY
    api_secret = settings.UPSTOX_API_SECRET
    redirect_uri = settings.UPSTOX_REDIRECT_URI

    if not api_key or not api_secret or not redirect_uri:
        print("Please configure UPSTOX_API_KEY, UPSTOX_API_SECRET, and UPSTOX_REDIRECT_URI in your .env file.")
        return

    # Generate login URL
    auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={api_key}&redirect_uri={redirect_uri}"
    
    print("=" * 60)
    print("1. Click the link below to login to Upstox:")
    print(auth_url)
    print("=" * 60)
    print("2. After successful login, you will be redirected to your REDIRECT_URI.")
    print("   The URL will look like: https://your-redirect-uri/?code=xxxxxx")
    
    redirected_url = input("\nPaste the full redirected URL here: ").strip()
    
    try:
        parsed_url = urlparse(redirected_url)
        code = parse_qs(parsed_url.query)['code'][0]
    except Exception as e:
        print("Failed to parse the code from the URL. Ensure you copied the full URL.")
        return
        
    print(f"\nExtracted Code: {code}")
    print("Exchanging code for access token...")
    
    # Exchange code for token
    url = "https://api.upstox.com/v2/login/authorization/token"
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'code': code,
        'client_id': api_key,
        'client_secret': api_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get('access_token')
        print("=" * 60)
        print("SUCCESS! Your Access Token is:")
        print(access_token)
        print("\nCopy this value and add it to your .env file as:")
        print(f"UPSTOX_ACCESS_TOKEN={access_token}")
        print("=" * 60)
    else:
        print(f"Failed to get token: {response.text}")

if __name__ == "__main__":
    main()
