from flask import Flask, render_template, request, redirect, url_for, flash
import requests
import json
import os
import urllib3
import hashlib
import logging

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_for_dev_123!@#')

# --- NocoDB Configuration ---
NOCODB_BASE_NAME = "LogInTest"
NOCODB_TABLE_NAME = "credentiale"
NOCODB_URL = "https://nc0.uvt.ro"
API_TOKEN = os.environ.get("NOCODB_API_KEY", "-y8MCS6grmaJNIB1pY2PhQsVsZ1jFnbCraHY6LQg")

# --- Disable InsecureRequestWarning ---
try:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    pass

# --- Password Encryption Function (SHA512) ---
def encrypt_password_sha512(password_string):
    sha_signature = hashlib.sha512(password_string.encode()).hexdigest()
    return sha_signature

@app.route('/', methods=['GET', 'POST'])
def user_creator_page():
    if request.method == 'POST':
        email_address = request.form.get('email_address')
        password = request.form.get('password')
        role = request.form.get('role')

        if not email_address or not password or not role:
            flash("All fields (Email, Password, Role) are required.", "error")
            return redirect(url_for('user_creator_page'))

        base_url_cleaned = NOCODB_URL.rstrip('/')
        api_endpoint = f"{base_url_cleaned}/api/v1/db/data/v1/{NOCODB_BASE_NAME}/{NOCODB_TABLE_NAME}"

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "xc-token": API_TOKEN
        }

        payload = {
            "adresa": email_address,
            "parola": encrypt_password_sha512(password),
            "role": role
        }

        try:
            log_payload = {k: (v if k != 'parola' else '***') for k, v in payload.items()}
            app.logger.info(f"Sending data to NocoDB endpoint: {api_endpoint} with payload: {log_payload}")

            response = requests.post(
                api_endpoint,
                headers=headers,
                json=payload,
                verify=False,
                timeout=20
            )
            response.raise_for_status()

            flash(f"User '{email_address}' (Role: {role}) submitted successfully to NocoDB!", "success")
            try:
                response_json = response.json()
                app.logger.info(f"NocoDB Response Data: {json.dumps(response_json, indent=2)}")
            except json.JSONDecodeError:
                app.logger.info(f"NocoDB success response was not JSON: {response.text}")
                flash("Received a non-JSON success response from NocoDB.", "info")

        except requests.exceptions.HTTPError as http_err:
            error_message = f"HTTP error occurred: {http_err}"
            response_text = getattr(http_err.response, 'text', 'No response text available')
            status_code = getattr(http_err.response, 'status_code', 'N/A')
            app.logger.error(f"HTTP error: {http_err}, Status Code: {status_code}, Response: {response_text}")
            flash(f"Failed to create user. NocoDB Error: {status_code} - {response_text}", "error")
            if "BASE_NOT_FOUND" in response_text or "PROJECT_NOT_FOUND" in response_text:
                flash("Detail: BASE_NOT_FOUND or PROJECT_NOT_FOUND. Check NocoDB base/project name or API token permissions.", "warning")
            elif status_code == 503:
                flash("Detail: 503 Service Unavailable. Check NocoDB server status.", "warning")

        except requests.exceptions.ConnectionError as conn_err:
            app.logger.error(f"Connection error: {conn_err}")
            flash(f"Connection error: Could not connect to NocoDB at {NOCODB_URL}.", "error")
        except requests.exceptions.Timeout as timeout_err:
            app.logger.error(f"Request timed out: {timeout_err}")
            flash("Request to NocoDB timed out.", "error")
        except requests.exceptions.RequestException as req_err:
            app.logger.error(f"Unexpected request error: {req_err}")
            flash(f"An unexpected error occurred during the request: {req_err}", "error")
        except Exception as e:
            app.logger.error(f"An unexpected general error: {e}", exc_info=True)
            flash(f"An unexpected error occurred: {e}", "error")

        return redirect(url_for('user_creator_page'))

    return render_template('create_user_form.html')

if __name__ == '__main__':
    if API_TOKEN == "-y8MCS6grmaJNIB1pY2PhQsVsZ1jFnbCraHY6LQg":
        print("\nINFO: Using default API_TOKEN. For production, set the NOCODB_API_KEY environment variable.")
        print("Example (Linux/macOS): export NOCODB_API_KEY='your_real_api_key_here'")
        print("Example (Windows CMD): set NOCODB_API_KEY=your_real_api_key_here")
        print("Example (Windows PowerShell): $env:NOCODB_API_KEY='your_real_api_key_here'\n")
    if app.secret_key == 'a_default_secret_key_for_dev_123!@#':
        print("INFO: Using a default Flask secret key. Set FLASK_SECRET_KEY environment variable for better security.\n")

    logging.basicConfig(level=logging.INFO) # To see app.logger output
    app.run(debug=True, port=5003)