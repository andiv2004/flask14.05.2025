import os
import re
import requests
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, send_file, url_for, redirect, flash, jsonify, session
import urllib3
import exam_analysis
from exam_analysis import (
    analyze_exam_sheet,
    process_all_images_in_directory,
    add_correct_answer_key
)
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
import json
import csv
import logging
import hashlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_very_secret_key_123!@#')

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(APP_ROOT, 'uploads')
STATIC_FOLDER = os.path.join(APP_ROOT, 'static')
RESULTS_FOLDER = os.path.join(STATIC_FOLDER, 'results')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'tiff'}

LOGIN_NOCODB_API_KEY = os.environ.get("NOCODB_API_KEY_LOGIN", "-y8MCS6grmaJNIB1pY2PhQsVsZ1jFnbCraHY6LQg")
LOGIN_NOCODB_PROJECT_NAME = os.environ.get('NOCODB_PROJECT_NAME_LOGIN', 'LogInTest')
LOGIN_NOCODB_TABLE_NAME = os.environ.get('NOCODB_TABLE_NAME_LOGIN', 'credentiale')
LOGIN_NOCODB_BASE_URL = os.environ.get('NOCODB_BASE_URL_LOGIN', 'https://nc0.uvt.ro/')

EXAM_NOCODB_API_KEY = os.environ.get('NOCODB_API_KEY_EXAM', 'PD177ByKW09wXVNdgKVxzfqYDI3JTh3ukccDkJ1p')
EXAM_NOCODB_PROJECT_NAME = os.environ.get('NOCODB_PROJECT_NAME_EXAM', 'TestAdmitere')
EXAM_NOCODB_TABLE_NAME = os.environ.get('NOCODB_TABLE_NAME_EXAM', 'test')
EXAM_NOCODB_BASE_URL = os.environ.get('NOCODB_BASE_URL_EXAM', 'https://nc0.uvt.ro/')

SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', os.path.join(APP_ROOT, 'credentials.json'))
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '1t1HQfvnj4NgrBOFXUpY4neeSKzyGhXRy')

verificareUmanaDefault = True
try:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    pass

def encrypt_password(password_string):
    sha_signature = hashlib.sha512(password_string.encode()).hexdigest()
    return sha_signature

def verify_nocodb_login(email, password):
    if not all([LOGIN_NOCODB_API_KEY, LOGIN_NOCODB_PROJECT_NAME, LOGIN_NOCODB_TABLE_NAME, LOGIN_NOCODB_BASE_URL]):
        app.logger.error("Login NocoDB configuration is incomplete.")
        return False, None

    hashed_password_to_check = encrypt_password(password)
    base_url_cleaned = LOGIN_NOCODB_BASE_URL.rstrip('/')
    api_endpoint = f"{base_url_cleaned}/api/v1/db/data/v1/{LOGIN_NOCODB_PROJECT_NAME}/{LOGIN_NOCODB_TABLE_NAME}"
    headers = {
        "accept": "application/json",
        "xc-token": LOGIN_NOCODB_API_KEY
    }
    params = {
        "where": f"(adresa,eq,{email})"
    }

    try:
        app.logger.info(f"Attempting to fetch user: {email} from {api_endpoint}")
        response = requests.get(api_endpoint, headers=headers, params=params, verify=False, timeout=15)
        response.raise_for_status()
        data = response.json()
        app.logger.debug(f"NocoDB login response for {email}: {data}")
        user_list = data.get("list", data if isinstance(data, list) else None)

        if user_list and len(user_list) == 1:
            user_record = user_list[0]
            stored_hashed_password = user_record.get("parola")
            user_role = user_record.get("role")

            if stored_hashed_password == hashed_password_to_check:
                if user_role in ['admin', 'user']:
                    app.logger.info(f"User {email} authenticated successfully with role {user_role}.")
                    return True, user_role
                else:
                    app.logger.warning(f"User {email} authenticated but has invalid/missing role: {user_role}.")
                    return False, None
            else:
                app.logger.warning(f"Password mismatch for user {email}.")
                return False, None
        else:
            app.logger.warning(f"User {email} not found or multiple entries returned.")
            return False, None
    except requests.exceptions.HTTPError as http_err:
        app.logger.error(f"HTTP error occurred during login check: {http_err}")
        app.logger.error(f"Response content: {http_err.response.text}")
    except requests.exceptions.RequestException as req_err:
        app.logger.error(f"Request exception occurred during login check: {req_err}")
    except Exception as e:
        app.logger.error(f"An unexpected error occurred during login check: {e}", exc_info=True)
    return False, None

@app.route('/login', methods=['GET', 'POST'])
def login_route():
    if session.get('logged_in'):
        return redirect(url_for('main_route'))

    if request.method == 'POST':
        email = request.form.get('email_address')
        password = request.form.get('password')

        if not email or not password:
            flash('Email and password are required.', 'error')
            return render_template('login.html')

        is_authenticated, user_role = verify_nocodb_login(email, password)

        if is_authenticated:
            session['logged_in'] = True
            session['user_email'] = email
            session['user_role'] = user_role
            flash('Logged in successfully!', 'success')
            return redirect(url_for('main_route'))
        else:
            flash('Invalid email, password, or role assignment. Please try again.', 'error')
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout')
def logout_route():
    session.pop('logged_in', None)
    session.pop('user_email', None)
    session.pop('user_role', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login_route'))

def get_available_answer_keys():
    keys = list(exam_analysis.CORRECT_ANSWERS.keys())
    if not keys:
        exam_analysis.load_correct_answers()
        keys = list(exam_analysis.CORRECT_ANSWERS.keys())
    return keys

def get_google_drive_service():
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            app.logger.error(f"Google Service Account file not found: {SERVICE_ACCOUNT_FILE}")
            return None
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        app.logger.error(f"Error creating Google Drive service: {e}", exc_info=True)
        return None

def upload_to_drive(file_path, filename, folder_id, is_temporary=False):
    if not os.path.exists(file_path):
        app.logger.error(f"File not found for Drive upload: {file_path}")
        return None, "File not found for upload", None

    effective_folder_id = folder_id
    if not effective_folder_id or effective_folder_id == 'YOUR_ACTUAL_GOOGLE_DRIVE_FOLDER_ID_HERE':
        env_folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', GOOGLE_DRIVE_FOLDER_ID)
        if env_folder_id and env_folder_id != 'YOUR_ACTUAL_GOOGLE_DRIVE_FOLDER_ID_HERE':
            effective_folder_id = env_folder_id
            app.logger.info(f"Using Folder ID from env: {effective_folder_id}")
        else:
            app.logger.error("Google Drive Folder ID is not configured correctly.")
            return None, "Google Drive Folder ID not configured", None
            
    service = get_google_drive_service()
    if not service:
        return None, "Failed to initialize Google Drive service", None
    try:
        meta = {'name': filename, 'parents': [effective_folder_id], 'properties': {'is_temporary_upload': str(is_temporary).lower()}}
        media = MediaFileUpload(file_path, resumable=True)
        file = service.files().create(body=meta, media_body=media, fields='id,webViewLink').execute()
        service.permissions().create(fileId=file['id'], body={'type': 'anyone', 'role': 'reader'}).execute()
        app.logger.info(f"Uploaded '{filename}' (ID: {file.get('id')}) to GDrive Folder '{effective_folder_id}'. Temp: {is_temporary}. Link: {file.get('webViewLink')}")
        return file.get('webViewLink'), None, file.get('id')
    except Exception as e:
        app.logger.error(f"Error uploading '{filename}' to Google Drive (Folder ID used: {effective_folder_id}): {e}", exc_info=True)
        if "notFound" in str(e) and effective_folder_id in str(e):
            return None, f"Google Drive API reported 'File not found' for Folder ID: {effective_folder_id}. Ensure it's correct and you have access.", None
        return None, f"Google Drive upload error: {str(e)}", None

def delete_drive_file(file_id):
    if not file_id: return False, "No file ID provided for deletion"
    service = get_google_drive_service()
    if not service: return False, "Failed to initialize Google Drive service for deletion"
    try:
        service.files().delete(fileId=file_id).execute()
        app.logger.info(f"Successfully deleted file ID: {file_id} from Google Drive.")
        return True, "File deleted successfully"
    except Exception as e:
        app.logger.error(f"Error deleting file ID {file_id} from Google Drive: {e}", exc_info=True)
        return False, f"Error deleting file: {str(e)}"

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_to_nocodb(student_id, answers, grade, drive_link=None, drive_file_id=None, answer_key_used=None):
    current_exam_api_key = os.environ.get('NOCODB_API_KEY_EXAM', EXAM_NOCODB_API_KEY)
    current_exam_base_url = os.environ.get('NOCODB_BASE_URL_EXAM', EXAM_NOCODB_BASE_URL)
    current_exam_project_name = os.environ.get('NOCODB_PROJECT_NAME_EXAM', EXAM_NOCODB_PROJECT_NAME)
    current_exam_table_name = os.environ.get('NOCODB_TABLE_NAME_EXAM', EXAM_NOCODB_TABLE_NAME)

    if (not current_exam_api_key or current_exam_api_key == 'YOUR_NOCODB_API_KEY_HERE' or
        current_exam_base_url == 'https://your.nocodb.instance.com' or not current_exam_base_url or
        not current_exam_project_name or not current_exam_table_name):
        app.logger.warning("Exam NocoDB not configured correctly. Skipping send.")
        return False, "Exam NocoDB not configured in app or environment variables", None

    headers = {'xc-token': current_exam_api_key}
    ans_str = "; ".join([f"{q_id}: {a}" for q_id, a in sorted(answers.items(), key=lambda item: (item[0][0], int(item[0][1:])))])

    payload = {
        "student_id": student_id,
        "grade": grade,
        "answers": ans_str,
        "num_questions": len(answers) if answers else 0
    }
    if drive_link: payload["link_drive"] = drive_link
    if drive_file_id: payload["drive_file_id"] = drive_file_id
    if answer_key_used: payload["answer_key_used"] = answer_key_used

    base_url_cleaned = current_exam_base_url.rstrip('/')
    data_url = f"{base_url_cleaned}/api/v1/db/data/v1/{current_exam_project_name}/{current_exam_table_name}"
    app.logger.info(f"Attempting Exam NocoDB POST to: {data_url} for Student ID: {student_id}")
    try:
        resp = requests.post(data_url, json=payload, headers=headers, verify=False, timeout=15)
        if resp.status_code in (200, 201):
            app.logger.info(f"Exam NocoDB success for {student_id}. Response: {resp.text[:200]}")
            return True, "Data saved to Exam NocoDB", resp.json()
        else:
            app.logger.error(f"Exam NocoDB Error {resp.status_code} for {student_id}: {resp.text}")
            error_detail = resp.text
            try:
                error_json = resp.json()
                if isinstance(error_json, dict) and 'msg' in error_json:
                    error_detail = error_json['msg']
            except json.JSONDecodeError:
                pass 
            return False, f"Exam NocoDB Error {resp.status_code}: {error_detail}", None
    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout connecting to Exam NocoDB: {data_url}")
        return False, "Timeout connecting to Exam NocoDB.", None
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Exam NocoDB RequestException: {e}")
        return False, f"Exam NocoDB connection error: {e}", None
    except Exception as e:
        app.logger.error(f"Exam NocoDB unexpected error: {e}", exc_info=True)
        return False, f"Exam NocoDB unexpected error: {e}", None

@app.route('/', methods=['GET', 'POST'])
def main_route():
    if not session.get('logged_in'):
        return redirect(url_for('login_route'))

    current_user_role = session.get('user_role')
    verificare_umana = session.get('verificare_umana', verificareUmanaDefault)
    available_answer_keys = get_available_answer_keys()
    
    active_mode = session.get('active_mode', 'single')
    if request.args.get('mode') in ['single', 'batch', 'keys']:
        active_mode = request.args.get('mode')
        session['active_mode'] = active_mode

    if current_user_role == 'user' and active_mode == 'keys':
        flash("You do not have permission to access the 'Manage Answer Keys' page.", "warning")
        active_mode = 'single'
        session['active_mode'] = 'single'
        if request.method == 'GET':
            return redirect(url_for('main_route', mode='single'))

    if active_mode != 'single':
        session.pop('single_scan_step', None); session.pop('single_scan_student_id', None)
        session.pop('single_scan_selected_key', None); session.pop('single_scan_results_data', None)
    if active_mode != 'batch':
        session.pop('batch_results_for_display', None); session.pop('pending_batch_verification_data', None)

    single_scan_step = session.get('single_scan_step', 1)
    single_scan_student_id = session.get('single_scan_student_id')
    single_scan_selected_key = session.get('single_scan_selected_key', available_answer_keys[0] if available_answer_keys else None)
    single_scan_results_data = session.get('single_scan_results_data')

    batch_results_for_display = session.get('batch_results_for_display', [])
    pending_batch_verification_data = session.get('pending_batch_verification_data')
    selected_answer_key_batch = session.get('selected_answer_key_batch', available_answer_keys[0] if available_answer_keys else None)
    form_action_error_on_keys = session.get('form_action_error_on_keys', False)
    session['form_action_error_on_keys'] = False 

    if request.method == 'POST':
        if not session.get('logged_in'):
            flash("Your session expired. Please log in again.", "warning")
            return redirect(url_for('login_route'))

        form_action = request.form.get('form_action', '')
        active_mode_on_submit = request.form.get('active_mode_on_submit', active_mode)
        
        if current_user_role == 'user' and active_mode_on_submit == 'keys':
            flash("You do not have permission to access this section.", "warning")
            active_mode_on_submit = 'single' # Force to a permitted mode
        
        session['active_mode'] = active_mode_on_submit
        active_mode = active_mode_on_submit

        if form_action == 'manage_answer_key' and current_user_role == 'user':
            flash("You do not have permission to manage answer keys.", "error")
            session['active_mode'] = 'single'
            return redirect(url_for('main_route', mode='single'))

        if form_action == 'single_scan_step_1':
            session['single_scan_student_id'] = request.form.get('student_id_input', '').strip()
            if session['single_scan_student_id']:
                session['single_scan_step'] = 2; session.pop('single_scan_results_data', None)
            else: flash("Student ID cannot be empty.", "error")
            return redirect(url_for('main_route', mode='single'))

        elif form_action == 'single_scan_step_2':
            session['single_scan_selected_key'] = request.form.get('answer_key_select_single')
            if session['single_scan_selected_key'] not in available_answer_keys:
                flash("Invalid answer key selected.", "error"); session['single_scan_step'] = 2
            else: session['single_scan_step'] = 3
            return redirect(url_for('main_route', mode='single'))

        elif form_action == 'single_scan_step_3':
            student_id = session.get('single_scan_student_id'); selected_key = session.get('single_scan_selected_key')
            if not student_id or not selected_key:
                flash("Student ID or Answer Key missing. Please start over.", "error"); session['single_scan_step'] = 1; return redirect(url_for('main_route', mode='single'))
            if 'exam_image' not in request.files or request.files['exam_image'].filename == '':
                flash('No file selected.', 'error'); return redirect(url_for('main_route', mode='single'))

            file = request.files['exam_image']
            if file and allowed_file(file.filename):
                safe_s_id=re.sub(r'[^\w.-]+','_',student_id); safe_k=re.sub(r'[^\w.-]+','_',selected_key)
                temp_fname = secure_filename(f"temp_single_{safe_s_id}_{safe_k}_{os.path.splitext(file.filename)[1]}")
                temp_img_path = os.path.join(UPLOAD_FOLDER, temp_fname)
                try:
                    file.save(temp_img_path)
                    app.logger.info(f"Analyzing single image: {temp_img_path} with key {selected_key}")
                    s_id, grade, answers, out_img_path, out_csv_path = analyze_exam_sheet(temp_img_path, RESULTS_FOLDER, selected_key)

                    if s_id is None and grade is None: 
                        app.logger.error(f"Analysis function returned None for {temp_img_path}")
                        flash('Error during image analysis. Check logs.', 'error')
                        if os.path.exists(temp_img_path): os.remove(temp_img_path)
                        return redirect(url_for('main_route', mode='single'))

                    if os.path.exists(temp_img_path): os.remove(temp_img_path)

                    rel_img_path = None
                    if out_img_path and os.path.exists(out_img_path):
                        if out_img_path.startswith(STATIC_FOLDER + os.sep):
                            rel_img_path = os.path.relpath(out_img_path, STATIC_FOLDER).replace("\\","/")
                        else:
                            rel_img_path = os.path.join(os.path.basename(RESULTS_FOLDER), os.path.basename(out_img_path)).replace("\\","/")
                            if not os.path.exists(os.path.join(STATIC_FOLDER, rel_img_path)):
                                app.logger.warning(f"Constructed relative path for annotated image seems incorrect: {rel_img_path}. Full: {out_img_path}")
                                rel_img_path = None 
                    else:
                        app.logger.warning(f"Annotated image path invalid or file missing: {out_img_path}")

                    session['single_scan_results_data'] = {
                        'student_id': s_id,
                        'input_student_id': student_id,
                        'grade': grade,
                        'answers': answers,
                        'annotated_img_filename': rel_img_path,
                        'csv_filename': os.path.basename(out_csv_path) if out_csv_path and os.path.exists(out_csv_path) else None,
                        'selected_answer_key': selected_key
                        }
                    session['single_scan_step'] = 4
                    flash('Analysis complete.', 'success')

                except Exception as e:
                    app.logger.error(f"Error during single scan step 3: {e}", exc_info=True)
                    flash(f'Analysis error: {e}', 'error')
                    if os.path.exists(temp_img_path):
                        try: os.remove(temp_img_path)
                        except OSError: pass
            else: flash('Invalid file type. Allowed: png, jpg, jpeg, bmp, tiff', 'error')
            return redirect(url_for('main_route', mode='single'))

        elif form_action == 'initiate_batch_analysis':
            key_for_batch = request.form.get('answer_key_batch_select')
            if not key_for_batch or key_for_batch not in available_answer_keys:
                flash("Invalid or no answer key selected for batch.", "error")
            else:
                session['selected_answer_key_batch'] = key_for_batch
                app.logger.info(f"Starting batch analysis with key: {key_for_batch}")
                batch_summary = process_all_images_in_directory(UPLOAD_FOLDER, RESULTS_FOLDER, key_for_batch)

                display_results, pending_verify_data_list = [], []
                successful_analyses = 0
                failed_analyses = 0

                for item in batch_summary:
                    s_id = item.get('student_id')
                    grade = item.get('grade')
                    orig_fname = item.get('original_filename')
                    analysis_status = item.get('status', 'Analysis Unknown') 
                    student_id_from_filename = os.path.splitext(orig_fname)[0] if orig_fname else "UnknownFile"

                    if analysis_status.startswith("Success") or analysis_status.startswith("Analysis Incomplete"):
                        successful_analyses += 1
                        current_s_id_for_files = s_id if s_id else f"UnknownID_{student_id_from_filename}"
                        safe_s_id_b=re.sub(r'[^\w.-]+','_', current_s_id_for_files)
                        safe_k_b=re.sub(r'[^\w.-]+','_',key_for_batch)
                        
                        annot_base = f'{safe_s_id_b}_analyzed_{safe_k_b}.png'
                        csv_base = f'{safe_s_id_b}_answers_{safe_k_b}.csv'
                        
                        local_annot = os.path.join(RESULTS_FOLDER, annot_base)
                        local_csv = os.path.join(RESULTS_FOLDER, csv_base)

                        current_answers = {}
                        if os.path.exists(local_csv):
                            try:
                                with open(local_csv, 'r', newline='') as csv_f:
                                    reader = csv.DictReader(csv_f)
                                    for row in reader:
                                        current_answers[row['QuestionID']] = row['DetectedAnswer']
                            except Exception as csv_e:
                                app.logger.error(f"Error reading CSV {local_csv} for batch display: {csv_e}")

                        d_link, up_err, f_id = None, "Verification Disabled", None
                        drive_upload_status_for_display = "Verification Disabled"
                        
                        if verificare_umana:
                            if os.path.exists(local_annot):
                                temp_drive_filename = f"TEMP_{s_id if s_id else student_id_from_filename}_{safe_k_b}.png"
                                d_link,up_err,f_id = upload_to_drive(local_annot, temp_drive_filename, GOOGLE_DRIVE_FOLDER_ID, True)
                                drive_upload_status_for_display = "Temp Upload OK" if f_id else f"Temp Upload Failed: {up_err}"
                            else:
                                drive_upload_status_for_display = "Annot. Img Missing for Upload"
                        
                        display_results.append({
                            'student_id':s_id if s_id else f"(from file: {student_id_from_filename})",
                            'grade':grade,
                            'original_filename':orig_fname,
                            'status': drive_upload_status_for_display,
                            'drive_link':d_link,
                            'answer_key_used':key_for_batch
                            })

                        if f_id and verificare_umana:
                            pending_verify_data_list.append({
                                'student_id':s_id, 
                                'grade':grade,
                                'temp_drive_file_id':f_id,
                                'answers':current_answers,
                                'local_annotated_image_path':local_annot,
                                'local_csv_path':local_csv,
                                'answer_key_used':key_for_batch,
                                'original_filename':orig_fname
                                })
                        elif verificare_umana and not f_id:
                            app.logger.warning(f"Skipping item {orig_fname} for batch verification due to Drive temp upload failure or missing annotated image.")
                    else: 
                        failed_analyses +=1
                        display_results.append({
                            'student_id': s_id if s_id else f"(from file: {student_id_from_filename})", 
                            'grade':None,
                            'original_filename':orig_fname,
                            'status': analysis_status,
                            'drive_link': None,
                            'answer_key_used':key_for_batch
                            })

                session['batch_results_for_display'] = display_results
                if pending_verify_data_list and verificare_umana:
                    session['pending_batch_verification_data'] = json.dumps(pending_verify_data_list)
                else:
                    session.pop('pending_batch_verification_data', None) 

                flash(f"Batch processing finished. Succeeded: {successful_analyses}, Failed: {failed_analyses}.", "info")
            return redirect(url_for('main_route', mode='batch'))

        elif form_action == 'manage_answer_key':
            key_name = request.form.get('key_name_manage', '').strip()
            answers_str = request.form.get('answers_string_manage', '').strip()

            if not key_name or not answers_str:
                flash("Key name and answers string cannot be empty.", "error")
                session['form_action_error_on_keys'] = True
            else:
                success, msg = add_correct_answer_key(key_name, answers_str)
                flash(msg, "success" if success else "error")
                if not success:
                    session['form_action_error_on_keys'] = True
                else:
                    available_answer_keys = get_available_answer_keys() 

            session['active_mode'] = 'keys'
            return redirect(url_for('main_route', mode='keys'))

    return render_template('index.html',
                            active_mode=active_mode,
                            user_role=current_user_role,
                            verificare_umana=verificare_umana,
                            answer_keys=available_answer_keys,
                            expected_total_questions=exam_analysis.EXPECTED_TOTAL_QUESTIONS,
                            single_scan_step=single_scan_step,
                            single_scan_student_id=single_scan_student_id,
                            single_scan_selected_key=single_scan_selected_key,
                            single_scan_results_data=single_scan_results_data,
                            batch_results_for_display=batch_results_for_display,
                            pending_batch_verification_data_exists=bool(pending_batch_verification_data),
                            selected_answer_key_batch=selected_answer_key_batch,
                            UPLOAD_FOLDER_NAME=os.path.basename(UPLOAD_FOLDER),
                            form_action_error_on_keys=form_action_error_on_keys)

@app.route('/reset_single_scan')
def reset_single_scan_flow():
    if not session.get('logged_in'):
        return redirect(url_for('login_route'))
    session.pop('single_scan_step', None); session.pop('single_scan_student_id', None)
    session.pop('single_scan_selected_key', None); session.pop('single_scan_results_data', None)
    flash("Single scan process reset.", "info"); session['active_mode'] = 'single'
    return redirect(url_for('main_route', mode='single'))

@app.route('/download_csv/<filename>')
def download_csv(filename):
    if not session.get('logged_in'):
        return redirect(url_for('login_route'))
    if not filename or not re.match(r'^[\w\.\-]+$', filename) or '..' in filename or '/' in filename or '\\' in filename:
        flash('Invalid filename.', 'error'); return redirect(url_for('main_route'))
    
    safe_path = os.path.join(RESULTS_FOLDER, secure_filename(filename))

    if not os.path.abspath(safe_path).startswith(os.path.abspath(RESULTS_FOLDER)):
        flash('Access denied to file location.', 'error'); return redirect(url_for('main_route', mode=session.get('active_mode','single')))

    if not os.path.isfile(safe_path):
        flash('CSV file not found.', 'error'); return redirect(url_for('main_route', mode=session.get('active_mode','single')))
    try:
        return send_file(safe_path, as_attachment=True)
    except Exception as e:
        app.logger.error(f"Error sending file {safe_path}: {e}", exc_info=True)
        flash('Could not download file.', 'error')
        return redirect(url_for('main_route', mode=session.get('active_mode','single')))

@app.route('/send_single_exam_to_nocodb_action', methods=['POST'])
def send_single_exam_to_nocodb_route():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Session expired. Please log in.'}), 401
        
    verificare_umana = session.get('verificare_umana', verificareUmanaDefault)
    if not verificare_umana: return jsonify({'success': False, 'message': 'Verification disabled.'}), 403
    try:
        data=request.json; s_id=data.get('student_id'); grade=data.get('grade'); ans=data.get('answers')
        rel_img=data.get('annotated_img_filename'); ak=data.get('answer_key_used'); csv_base=data.get('csv_filename')

        if not all([s_id, grade is not None, ans, rel_img, ak]):
            app.logger.warning(f"Missing data for NocoDB send: ID={s_id}, Grade={grade}, Answers exist={bool(ans)}, Img={rel_img}, Key={ak}")
            return jsonify({'success':False,'message':'Missing data.'}),400

        full_img=os.path.join(STATIC_FOLDER,rel_img)
        if not os.path.exists(full_img):
            app.logger.error(f"Annotated image missing for NocoDB send: {full_img} (relative was {rel_img})")
            return jsonify({'success':False,'message':'Annotated image missing on server.'}),404

        safe_s_id_n = re.sub(r'[^\w.-]+','_',s_id)
        safe_ak_n = re.sub(r'[^\w.-]+','_',ak)
        drive_fn=f"Student_{safe_s_id_n}_Key_{safe_ak_n}.png"
        link,err,f_id=upload_to_drive(full_img,drive_fn,GOOGLE_DRIVE_FOLDER_ID,False)
        if err:
            app.logger.error(f"Drive upload failed during NocoDB send: {err}")
            return jsonify({'success':False,'message':f"Drive upload error: {err}"}),500

        noco_ok,noco_msg,_=send_to_nocodb(s_id,ans,grade,link,f_id,ak)
        if noco_ok:
            try:
                if os.path.exists(full_img):os.remove(full_img)
                if csv_base:
                    csv_full_path = os.path.join(RESULTS_FOLDER,csv_base)
                    if os.path.exists(csv_full_path): os.remove(csv_full_path)
            except OSError as e:
                app.logger.warning(f"Error cleaning up local files after NocoDB success: {e}")
            session.pop('single_scan_results_data',None)
            session['single_scan_step']=1
            session.pop('single_scan_student_id',None)
            session.pop('single_scan_selected_key',None)
            return jsonify({'success':True,'message':'Data saved successfully! Redirecting...','drive_link':link}),200
        else:
            app.logger.error(f"NocoDB send failed: {noco_msg}. Cleaning up Drive file {f_id}.")
            if f_id: delete_drive_file(f_id)
            return jsonify({'success':False,'message':f'NocoDB Error: {noco_msg}'}),500
    except Exception as e:
        app.logger.error(f"Server error during single exam send: {e}", exc_info=True)
        return jsonify({'success':False,'message':f'Server error: {e}'}),500

@app.route('/verify_batch_action', methods=['POST'])
def verify_batch_action_route():
    if not session.get('logged_in'):
        flash("Your session expired. Please log in again.", "warning")
        return redirect(url_for('login_route'))
        
    ver_umana=session.get('verificare_umana',verificareUmanaDefault); action=request.form.get('action','')
    if not ver_umana: flash("Verification disabled. Cannot perform batch action.","warning"); return redirect(url_for('main_route',mode='batch'))

    pending_js=session.get('pending_batch_verification_data')
    if not pending_js: flash("No pending batch data found in session.","warning"); return redirect(url_for('main_route',mode='batch'))

    try:
        items=json.loads(pending_js);total=len(items);ok_cnt,err_cnt,skip_cnt=0,0,0
        app.logger.info(f"Processing batch action '{action}' for {total} items.")

        for item_index, i in enumerate(items):
            s,g,tmp_fid,ans_d,l_img,l_csv,ak_u,orig_fu=(i.get(k) for k in ['student_id','grade','temp_drive_file_id','answers','local_annotated_image_path','local_csv_path','answer_key_used','original_filename'])

            if not all([s,g is not None,tmp_fid,l_img,ak_u,orig_fu]):
                app.logger.warning(f"Skipping item {item_index+1}/{total} due to missing data: ID={s}, Grade={g}, TmpFID={tmp_fid}, Img={l_img}, Key={ak_u}, OrigF={orig_fu}")
                skip_cnt+=1
                if tmp_fid: delete_drive_file(tmp_fid) 
                continue

            if action=='approve':
                final_fid_b=None 
                try:
                    if not os.path.exists(l_img):
                        app.logger.error(f"Approve failed for {s}: Local annotated image '{l_img}' not found. Deleting temp Drive file.")
                        delete_drive_file(tmp_fid)
                        err_cnt+=1
                        continue

                    safe_s_id_vb = re.sub(r'[^\w.-]+','_',s)
                    safe_ak_vb = re.sub(r'[^\w.-]+','_',ak_u)
                    fnl_drv_fn=f"Student_{safe_s_id_vb}_Key_{safe_ak_vb}.png"
                    fnl_link,up_err_b,final_fid_b=upload_to_drive(l_img,fnl_drv_fn,GOOGLE_DRIVE_FOLDER_ID,False)

                    if up_err_b:
                        app.logger.error(f"Approve failed for {s}: Final Drive upload error: {up_err_b}")
                        delete_drive_file(tmp_fid) 
                        err_cnt+=1
                        continue

                    delete_drive_file(tmp_fid) 

                    n_ok,n_msg,_=send_to_nocodb(s,ans_d,g,fnl_link,final_fid_b,ak_u)

                    if n_ok:
                        ok_cnt+=1
                        try:
                            if os.path.exists(l_img):os.remove(l_img)
                            if l_csv and os.path.exists(l_csv): os.remove(l_csv)
                            orig_file_path = os.path.join(UPLOAD_FOLDER,orig_fu) 
                            if os.path.exists(orig_file_path): os.remove(orig_file_path)
                            app.logger.info(f"Approved and cleaned up local files for {s}")
                        except OSError as e:
                            app.logger.warning(f"Error cleaning local files for {s} after approval: {e}")
                    else:
                        app.logger.error(f"Approve failed for {s}: NocoDB error: {n_msg}. Deleting final Drive file {final_fid_b}.")
                        if final_fid_b: delete_drive_file(final_fid_b) 
                        err_cnt+=1
                except Exception as approve_e:
                    app.logger.error(f"Unexpected error during approval for {s}: {approve_e}", exc_info=True)
                    if final_fid_b: delete_drive_file(final_fid_b)
                    if tmp_fid: delete_drive_file(tmp_fid) 
                    err_cnt+=1

            elif action=='reject':
                try:
                    if tmp_fid:delete_drive_file(tmp_fid)
                    if os.path.exists(l_img):os.remove(l_img)
                    if l_csv and os.path.exists(l_csv):os.remove(l_csv)
                    ok_cnt+=1
                    app.logger.info(f"Rejected and cleaned up files for {s}")
                except Exception as reject_e:
                    app.logger.error(f"Error during rejection cleanup for {s}: {reject_e}", exc_info=True)
                    err_cnt+=1
            else:
                app.logger.warning(f"Unknown batch action '{action}' for item {item_index+1}. Skipping.")
                skip_cnt+=1

        if action=='approve':
            msg = f"Batch Approval: {ok_cnt}/{total-skip_cnt} items processed. {err_cnt} errors. {skip_cnt} skipped due to data issues."
            flash(msg, "info" if err_cnt==0 else ("warning" if ok_cnt > 0 else "error"))
        elif action=='reject':
            msg = f"Batch Rejection: {ok_cnt}/{total-skip_cnt} items handled. {err_cnt} errors. {skip_cnt} skipped."
            flash(msg, "info" if err_cnt==0 else "warning")
        else:
            flash(f"Unknown action '{action}' performed. Skipped: {skip_cnt}", "warning")

        session.pop('pending_batch_verification_data',None);session.pop('batch_results_for_display',None)
    except json.JSONDecodeError:
        flash("Error decoding pending batch data. Please re-run batch analysis.","error")
        session.pop('pending_batch_verification_data', None); session.pop('batch_results_for_display', None)
    except Exception as e:
        flash(f"Error processing batch verification: {e}","error")
        app.logger.error(f"Error during batch verification action: {e}", exc_info=True)

    return redirect(url_for('main_route',mode='batch'))

@app.route('/toggle_verificare_umana_action', methods=['POST'])
def toggle_verificare_umana_route():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Session expired. Please log in.'}), 401
    curr=session.get('verificare_umana',verificareUmanaDefault); session['verificare_umana']=not curr
    app.logger.info(f"Toggled Human Verification to: {session['verificare_umana']}")
    return jsonify({'success':True,'verificare_umana':session['verificare_umana']})

if __name__ == '__main__':
    LOGIN_NOCODB_API_KEY = os.environ.get("NOCODB_API_KEY_LOGIN", LOGIN_NOCODB_API_KEY)
    LOGIN_NOCODB_PROJECT_NAME = os.environ.get('NOCODB_PROJECT_NAME_LOGIN', LOGIN_NOCODB_PROJECT_NAME)
    LOGIN_NOCODB_TABLE_NAME = os.environ.get('NOCODB_TABLE_NAME_LOGIN', LOGIN_NOCODB_TABLE_NAME)
    LOGIN_NOCODB_BASE_URL = os.environ.get('NOCODB_BASE_URL_LOGIN', LOGIN_NOCODB_BASE_URL)

    EXAM_NOCODB_API_KEY = os.environ.get('NOCODB_API_KEY_EXAM', EXAM_NOCODB_API_KEY)
    EXAM_NOCODB_PROJECT_NAME = os.environ.get('NOCODB_PROJECT_NAME_EXAM', EXAM_NOCODB_PROJECT_NAME)
    EXAM_NOCODB_TABLE_NAME = os.environ.get('NOCODB_TABLE_NAME_EXAM', EXAM_NOCODB_TABLE_NAME)
    EXAM_NOCODB_BASE_URL = os.environ.get('NOCODB_BASE_URL_EXAM', EXAM_NOCODB_BASE_URL)
    
    GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', GOOGLE_DRIVE_FOLDER_ID)
    SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', SERVICE_ACCOUNT_FILE)
    
    exam_analysis.load_correct_answers() 
    app.run(debug=True, port=5002)