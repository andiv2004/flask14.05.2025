import requests
import json
import os
import urllib3

import hashlib

def encrypt_string(hash_string):
    sha_signature = \
        hashlib.sha256(hash_string.encode()).hexdigest()
    return sha_signature

NOCODB_BASE_NAME = "LogInTest"
NOCODB_TABLE_NAME = "credentiale"
NOCODB_URL = "https://nc0.uvt.ro"
API_TOKEN = os.environ.get("NOCODB_API_KEY", "-y8MCS6grmaJNIB1pY2PhQsVsZ1jFnbCraHY6LQg")

try:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    pass

base_url_cleaned = NOCODB_URL.rstrip('/')
api_endpoint = f"{base_url_cleaned}/api/v1/db/data/v1/{NOCODB_BASE_NAME}/{NOCODB_TABLE_NAME}"

headers = {
    "accept": "application/json",
    "Content-Type": "application/json",
    "xc-token": API_TOKEN
}

email_address = input("address: ")
password = input("password: ")
role= input("role: ")

def encrypt_string(hash_string):
    sha_signature = \
        hashlib.sha512(hash_string.encode()).hexdigest()
    return sha_signature


payload = {
    "adresa": email_address,
    "parola": encrypt_string(password),
    "role": role
}

try:
    print(f"\nSending data to: {api_endpoint}")
    response = requests.post(
        api_endpoint,
        headers=headers,
        json=payload,
        verify=False,
        timeout=20
    )
    response.raise_for_status()
    print("Works")
    try:
        print("Response Data:")
        print(json.dumps(response.json(), indent=2))
    except json.JSONDecodeError:
        print("Response was not JSON:", response.text)

except requests.exceptions.HTTPError as http_err:
    print(f"\nHTTP error occurred: {http_err}")
    print(f"Status Code: {http_err.response.status_code}")
    response_text = http_err.response.text
    print("Response Content:", response_text)

    if "BASE_NOT_FOUND" in response_text or "PROJECT_NOT_FOUND" in response_text:
        print("\n---> Error: BASE_NOT_FOUND or PROJECT_NOT_FOUND reported by NocoDB.")
        print(f"---> Base name '{NOCODB_BASE_NAME}' or permissions may be incorrect.")
    elif http_err.response.status_code == 503:
        print("\n---> Error: 503 Service Unavailable. Check server status.")

except requests.exceptions.ConnectionError as conn_err:
    print(f"\nConnection error occurred: {conn_err}")

except requests.exceptions.Timeout as timeout_err:
    print(f"\nRequest timed out: {timeout_err}")

except requests.exceptions.RequestException as req_err:
    print(f"\nAn unexpected error occurred during the request: {req_err}")

except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")
