import cv2
import numpy as np
import os
import csv
import re
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

ANSWER_KEYS_FILE = 'answer_keys.json'
CORRECT_ANSWERS = {}
EXPECTED_TOTAL_QUESTIONS = 45
VALID_ANSWER_OPTIONS = {'A', 'B', 'C', 'D'}

# --- Mapping Functions ---
def map_index_to_roi_key(index):
    # Converts numerical index (1-45) to ROI key ('A01'-'C15')
    if not 1 <= index <= EXPECTED_TOTAL_QUESTIONS:
        return None
    if 1 <= index <= 15:
        return f'A{index:02d}'
    elif 16 <= index <= 30:
        return f'B{index - 15:02d}'
    else: # 31 <= index <= 45
        return f'C{index - 30:02d}'

# *** NEW HELPER FUNCTION ***
def map_roi_key_to_index(roi_key):
    # Converts ROI key ('A01'-'C15') back to numerical index (1-45)
    if not isinstance(roi_key, str) or len(roi_key) != 3:
        logging.debug(f"Invalid ROI key format (length or type): {roi_key}")
        return None
    section = roi_key[0].upper()
    try:
        num_in_section = int(roi_key[1:])
        if section == 'A' and 1 <= num_in_section <= 15:
            return num_in_section
        elif section == 'B' and 1 <= num_in_section <= 15:
            return num_in_section + 15
        elif section == 'C' and 1 <= num_in_section <= 15:
            return num_in_section + 30
        else:
            logging.debug(f"Invalid ROI key section or number range: {roi_key}")
            return None # Invalid section or number range for the section
    except ValueError:
        logging.debug(f"Invalid ROI key number part: {roi_key}")
        return None # Number part wasn't an integer

# --- load_correct_answers (remains the same, expects numerical keys in JSON) ---
def load_correct_answers():
    global CORRECT_ANSWERS
    if os.path.exists(ANSWER_KEYS_FILE):
        try:
            with open(ANSWER_KEYS_FILE, 'r') as f:
                loaded_data = json.load(f)
            validated_data = {}
            for key_name, key_data in loaded_data.items():
                # --- Validation logic remains the same ---
                if not isinstance(key_data, dict):
                    logging.warning(f"Answer key '{key_name}' in {ANSWER_KEYS_FILE} is not a dictionary. Skipping.")
                    continue
                if len(key_data) != EXPECTED_TOTAL_QUESTIONS:
                      logging.warning(f"Answer key '{key_name}' has {len(key_data)} questions, expected {EXPECTED_TOTAL_QUESTIONS}. Skipping.")
                      continue

                is_valid_key = True
                validated_answers = {}
                all_q_nums = set()
                # It still validates based on the numerical keys '1' through '45' stored in the JSON
                for q_num_str, ans_list in key_data.items():
                    try:
                        q_num = int(q_num_str)
                        if not (1 <= q_num <= EXPECTED_TOTAL_QUESTIONS):
                            raise ValueError("Question number out of range")
                        all_q_nums.add(q_num)
                    except ValueError:
                        logging.warning(f"Invalid question number '{q_num_str}' in key '{key_name}' (in JSON). Skipping key.")
                        is_valid_key = False
                        break # Stop validating this key_data

                    if not isinstance(ans_list, list) or not ans_list:
                        logging.warning(f"Answers for question '{q_num_str}' in key '{key_name}' (in JSON) are not a non-empty list. Skipping key.")
                        is_valid_key = False
                        break # Stop validating this key_data

                    valid_ans_in_list = True
                    clean_ans_list = []
                    for ans in ans_list:
                        ans_upper = str(ans).upper()
                        if ans_upper not in VALID_ANSWER_OPTIONS:
                            logging.warning(f"Invalid answer option '{ans}' for question '{q_num_str}' in key '{key_name}' (in JSON). Skipping key.")
                            is_valid_key = False
                            valid_ans_in_list = False
                            break # Stop validating this answer list
                        clean_ans_list.append(ans_upper)
                    if not valid_ans_in_list: break # Stop validating this key_data
                    validated_answers[q_num_str] = sorted(list(set(clean_ans_list))) # Store validated answers

                # Check if all questions 1-45 were found and valid
                if is_valid_key and len(all_q_nums) == EXPECTED_TOTAL_QUESTIONS:
                     # Check if the numeric keys cover the full range 1-45
                    expected_nums = set(range(1, EXPECTED_TOTAL_QUESTIONS + 1))
                    if all_q_nums == expected_nums:
                        validated_data[key_name] = validated_answers
                    else:
                         missing = sorted(list(expected_nums - all_q_nums))
                         extra = sorted(list(all_q_nums - expected_nums))
                         logging.warning(f"Answer key '{key_name}' (in JSON) has incorrect question numbers. Missing: {missing}, Extra/Invalid: {extra}. Skipping.")
                elif is_valid_key: # Valid format but wrong number of questions
                     logging.warning(f"Answer key '{key_name}' (in JSON) is missing some question numbers (found {len(all_q_nums)}). Skipping.")
                # else: The key was already marked invalid earlier

            CORRECT_ANSWERS = validated_data
            if not CORRECT_ANSWERS:
                logging.warning(f"No valid keys found in {ANSWER_KEYS_FILE} after validation.")

        except json.JSONDecodeError:
            logging.error(f"Error decoding {ANSWER_KEYS_FILE}. Check its format.")
            CORRECT_ANSWERS = {}
        except Exception as e:
            logging.error(f"Unexpected error loading answer keys: {e}")
            CORRECT_ANSWERS = {}
    else:
        logging.info(f"{ANSWER_KEYS_FILE} not found. No answer keys loaded.")
        CORRECT_ANSWERS = {}

# --- save_correct_answers (remains the same, saves numerical keys to JSON) ---
def save_correct_answers():
    global CORRECT_ANSWERS
    try:
        # Saves the CORRECT_ANSWERS dict which uses numerical keys ('1', '2',...)
        with open(ANSWER_KEYS_FILE, 'w') as f:
            json.dump(CORRECT_ANSWERS, f, indent=4, sort_keys=True) # Sort keys numerically '1', '10', '2', ...
    except IOError as e:
        logging.error(f"Error saving answer keys to {ANSWER_KEYS_FILE}: {e}")

# *** MODIFIED FUNCTION ***
def add_correct_answer_key(key_name, answers_input_string):
    global CORRECT_ANSWERS
    key_name = key_name.strip()
    if not key_name:
        return False, "Answer key name cannot be empty."
    # Allow spaces in key names now
    if not re.match("^[a-zA-Z0-9_\\- ]+$", key_name):
         return False, "Answer key name can only contain letters, numbers, spaces, underscores, and hyphens."

    parsed_answers = {} # Stores { '1': ['A'], '2': ['B'], ... }
    question_numbers_found = set() # Stores numerical indices {1, 2, ...}

    # Normalize input string (replace newlines with semicolons)
    normalized_string = answers_input_string.replace('\n', ';').replace('\r', '')
    question_parts = [part.strip() for part in normalized_string.split(';') if part.strip()]

    if not question_parts:
        return False, "Answers string is empty or contains only whitespace."

    # --- Parsing Loop ---
    for part in question_parts:
        if ':' not in part:
            return False, f"Invalid format: Missing ':' separator in segment '{part}'. Expected format 'A01:A' or 'B10:C,D'."

        roi_key_str, ans_str = part.split(':', 1)
        roi_key_str = roi_key_str.strip().upper() # Ensure uppercase like A01, B05
        ans_str = ans_str.strip()

        # Convert ROI Key (e.g., 'A01') to numerical index (e.g., 1)
        q_num = map_roi_key_to_index(roi_key_str)

        if q_num is None:
            return False, f"Invalid question identifier format or range: '{roi_key_str}'. Must be A01-A15, B01-B15, or C01-C15."

        # Check for duplicate numerical question index
        if q_num in question_numbers_found:
            return False, f"Duplicate question number '{q_num}' (from '{roi_key_str}') found."
        question_numbers_found.add(q_num)

        # Validate answers string is not empty
        if not ans_str:
            return False, f"Missing answers for question '{roi_key_str}'."

        # Parse and validate answer options (A, B, C, D)
        current_q_answers = []
        # Split by comma, strip whitespace, convert to upper, filter out empty strings
        ans_parts = [a.strip().upper() for a in ans_str.split(',') if a.strip()]
        if not ans_parts: # Handles cases like "A01:," or "A01: "
             return False, f"No valid answer options found for question '{roi_key_str}' after splitting by comma."

        for ans_opt in ans_parts:
            if ans_opt not in VALID_ANSWER_OPTIONS:
                return False, f"Invalid answer option '{ans_opt}' for question '{roi_key_str}'. Must be one of {VALID_ANSWER_OPTIONS}."
            current_q_answers.append(ans_opt)

        if not current_q_answers:
            # This case should technically be caught by 'if not ans_parts' above, but belts and braces
             return False, f"No answers collected for question '{roi_key_str}'."

        # Store answers sorted and unique, using the NUMERICAL index string as the key
        parsed_answers[str(q_num)] = sorted(list(set(current_q_answers)))

    # --- Final Validation ---
    # Check if exactly the expected number of unique questions were found
    if len(question_numbers_found) != EXPECTED_TOTAL_QUESTIONS:
        expected_set = set(range(1, EXPECTED_TOTAL_QUESTIONS + 1))
        missing_nums = sorted(list(expected_set - question_numbers_found))
        extra_nums = sorted(list(question_numbers_found - expected_set)) # Should be empty if count is low, but check anyway
        err_msg = f"Incorrect number of questions provided. Found {len(question_numbers_found)}, expected {EXPECTED_TOTAL_QUESTIONS}."
        if missing_nums:
            # Convert missing numbers back to ROI keys for better user feedback
            missing_keys = [map_index_to_roi_key(n) for n in missing_nums]
            err_msg += f" Missing questions for indices: {missing_keys}."
        # if extra_nums: # This case implies len > EXPECTED_TOTAL_QUESTIONS, handled by the count check generally
        #     err_msg += f" Extra/invalid indices found: {extra_nums}."
        return False, err_msg

    # All checks passed, add/update the key in the main dictionary
    CORRECT_ANSWERS[key_name] = parsed_answers
    save_correct_answers() # Save changes to the JSON file
    return True, f"Answer key '{key_name}' added/updated successfully with {len(parsed_answers)} questions."


# --- analyze_exam_sheet (No changes needed here) ---
# This function uses map_index_to_roi_key to generate ROIs keys ('A01', etc.)
# but crucially, it uses the 'index' value (1-45) stored in the ROI dict
# to look up the correct answer in CORRECT_ANSWERS, which still uses
# numerical keys ('1', '2', ...) thanks to the modifications above.
def analyze_exam_sheet(image_path, output_dir='static', answer_key_name='DefaultKey'):
    student_id = os.path.splitext(os.path.basename(image_path))[0]
    logging.info(f"Analyzing exam for student: {student_id} using answer key: {answer_key_name}")

    current_available_keys = list(CORRECT_ANSWERS.keys())
    if not current_available_keys:
        logging.critical(f"CRITICAL: No answer keys loaded. Cannot proceed with analysis for {student_id}.")
        return student_id, 0.0, {}, None, None

    if answer_key_name not in CORRECT_ANSWERS:
        fallback_key = current_available_keys[0]
        logging.warning(f"Warning: Answer key '{answer_key_name}' not found. Using '{fallback_key}' as fallback.")
        answer_key_name = fallback_key

    correct_answers_dict_for_key = CORRECT_ANSWERS.get(answer_key_name)

    if not correct_answers_dict_for_key or len(correct_answers_dict_for_key) != EXPECTED_TOTAL_QUESTIONS:
        num_found = len(correct_answers_dict_for_key) if correct_answers_dict_for_key else 'None'
        logging.error(f"Error: Selected answer key '{answer_key_name}' is invalid or incomplete ({num_found} vs {EXPECTED_TOTAL_QUESTIONS} expected questions). Cannot grade.")
        return student_id, 0.0, {}, None, None

    BLUE_DETECTION_THRESHOLD = 2
    DISPLAY_MAX_HEIGHT = 1100

    FORM_MARGIN_TOP_A = 1355
    FORM_MARGIN_LEFT_A = 459
    QUESTION_HEIGHT_A = 57
    OPTION_WIDTH_A = 100
    OPTION_GAP_A = 20
    QUESTION_GAP_A = 46
    NUM_QUESTIONS_A = 15

    FORM_MARGIN_TOP_B = 1355
    FORM_MARGIN_LEFT_B = 1169
    QUESTION_HEIGHT_B = QUESTION_HEIGHT_A
    OPTION_WIDTH_B = OPTION_WIDTH_A
    OPTION_GAP_B = OPTION_GAP_A
    QUESTION_GAP_B = QUESTION_GAP_A
    NUM_QUESTIONS_B = 15

    FORM_MARGIN_TOP_C = 1355
    FORM_MARGIN_LEFT_C = 1870
    QUESTION_HEIGHT_C = QUESTION_HEIGHT_A
    OPTION_WIDTH_C = OPTION_WIDTH_A
    OPTION_GAP_C = OPTION_GAP_A
    QUESTION_GAP_C = QUESTION_GAP_A
    NUM_QUESTIONS_C = 15

    TOTAL_QUESTIONS_FROM_ROIS = NUM_QUESTIONS_A + NUM_QUESTIONS_B + NUM_QUESTIONS_C
    if EXPECTED_TOTAL_QUESTIONS != TOTAL_QUESTIONS_FROM_ROIS:
        logging.warning(f"Warning: EXPECTED_TOTAL_QUESTIONS ({EXPECTED_TOTAL_QUESTIONS}) does not match calculated total questions from ROI definitions ({TOTAL_QUESTIONS_FROM_ROIS}). Please check definitions.")

    if not os.path.exists(image_path):
        logging.error(f"Error: Image file not found at '{image_path}'")
        return student_id, 0.0, {}, None, None
    image = cv2.imread(image_path)
    if image is None:
        logging.error(f"Error: Could not read image file '{image_path}'")
        return student_id, 0.0, {}, None, None

    display_image = image.copy()
    img_height, img_width = image.shape[:2]

    ROIs = {}
    question_index_counter = 1

    for i in range(NUM_QUESTIONS_A):
        question_id_def = map_index_to_roi_key(question_index_counter)
        if question_id_def is None: continue
        y_start = FORM_MARGIN_TOP_A + i * (QUESTION_HEIGHT_A + QUESTION_GAP_A)
        y_end = y_start + QUESTION_HEIGHT_A
        ROIs[question_id_def] = {'index': question_index_counter, 'options': {}}
        for j, option in enumerate(['A', 'B', 'C', 'D']):
            x_start = FORM_MARGIN_LEFT_A + j * (OPTION_WIDTH_A + OPTION_GAP_A)
            x_end = x_start + OPTION_WIDTH_A
            ROIs[question_id_def]['options'][option] = (x_start, y_start, x_end, y_end)
        question_index_counter += 1

    for i in range(NUM_QUESTIONS_B):
        question_id_def = map_index_to_roi_key(question_index_counter)
        if question_id_def is None: continue
        y_start = FORM_MARGIN_TOP_B + i * (QUESTION_HEIGHT_B + QUESTION_GAP_B)
        y_end = y_start + QUESTION_HEIGHT_B
        ROIs[question_id_def] = {'index': question_index_counter, 'options': {}}
        for j, option in enumerate(['A', 'B', 'C', 'D']):
            x_start = FORM_MARGIN_LEFT_B + j * (OPTION_WIDTH_B + OPTION_GAP_B)
            x_end = x_start + OPTION_WIDTH_B
            ROIs[question_id_def]['options'][option] = (x_start, y_start, x_end, y_end)
        question_index_counter += 1

    for i in range(NUM_QUESTIONS_C):
        question_id_def = map_index_to_roi_key(question_index_counter)
        if question_id_def is None: continue
        y_start = FORM_MARGIN_TOP_C + i * (QUESTION_HEIGHT_C + QUESTION_GAP_C)
        y_end = y_start + QUESTION_HEIGHT_C
        ROIs[question_id_def] = {'index': question_index_counter, 'options': {}}
        for j, option in enumerate(['A', 'B', 'C', 'D']):
            x_start = FORM_MARGIN_LEFT_C + j * (OPTION_WIDTH_C + OPTION_GAP_C)
            x_end = x_start + OPTION_WIDTH_C
            ROIs[question_id_def]['options'][option] = (x_start, y_start, x_end, y_end)
        question_index_counter += 1

    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_blue_ink = np.array([80, 30, 30])
    upper_blue_ink = np.array([140, 255, 255])
    blue_ink_mask = cv2.inRange(hsv_image, lower_blue_ink, upper_blue_ink)

    kernel = np.ones((3,3), np.uint8)
    blue_ink_mask = cv2.morphologyEx(blue_ink_mask, cv2.MORPH_OPEN, kernel, iterations=1)
    blue_ink_mask = cv2.morphologyEx(blue_ink_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    detected_answers_storage = {}
    q_ids_in_processing_order = sorted(ROIs.keys(), key=lambda qid_sort_key: (qid_sort_key[0], int(qid_sort_key[1:])))

    for current_question_id in q_ids_in_processing_order:
        question_data = ROIs[current_question_id]
        options_dict_for_q = question_data['options']
        # *** CRUCIAL: Use the stored numerical index for answer key lookup ***
        question_numeric_index_str = str(question_data['index'])

        detected_answers_storage[current_question_id] = 'no response'
        has_primary_answer_for_question = False

        for option_letter_key in sorted(options_dict_for_q.keys()):
            x1, y1, x2, y2 = options_dict_for_q[option_letter_key]

            y1_c, y2_c = max(0, y1), min(img_height, y2)
            x1_c, x2_c = max(0, x1), min(img_width, x2)

            if y1_c >= y2_c or x1_c >= x2_c:
                logging.warning(f"Warning: Invalid ROI coordinates for {current_question_id} option {option_letter_key}: {(x1,y1,x2,y2)}. Skipped.")
                continue

            cv2.rectangle(display_image, (x1_c, y1_c), (x2_c, y2_c), (255, 0, 0), 4)

            roi_mask_segment = blue_ink_mask[y1_c:y2_c, x1_c:x2_c]

            blue_pixel_count = cv2.countNonZero(roi_mask_segment)
            total_pixel_count_in_roi = (x2_c - x1_c) * (y2_c - y1_c)
            blue_percentage = (blue_pixel_count / total_pixel_count_in_roi) * 100 if total_pixel_count_in_roi > 0 else 0.0

            if blue_percentage > BLUE_DETECTION_THRESHOLD:
                if not has_primary_answer_for_question:
                    detected_answers_storage[current_question_id] = option_letter_key
                    has_primary_answer_for_question = True

                    # *** Look up correct answer using the numerical index string ***
                    actual_correct_answers_list = correct_answers_dict_for_key.get(question_numeric_index_str, [])
                    cleaned_detected_ans_highlight = option_letter_key.strip().upper()

                    if cleaned_detected_ans_highlight in actual_correct_answers_list:
                        cv2.rectangle(display_image, (x1_c, y1_c), (x2_c, y2_c), (0, 255, 0), 6)
                    else:
                        cv2.rectangle(display_image, (x1_c, y1_c), (x2_c, y2_c), (0, 0, 255), 6)

                else:
                    cv2.rectangle(display_image, (x1_c, y1_c), (x2_c, y2_c), (0, 165, 255), 6)
                    logging.info(f"Multiple marks detected for {current_question_id}. Kept first: '{detected_answers_storage[current_question_id]}'. Additional: '{option_letter_key}'. Marked as 'multiple'.")
                    if detected_answers_storage[current_question_id] != "multiple":
                         detected_answers_storage[current_question_id] = "multiple"

    sorted_detected_answers = dict(sorted(detected_answers_storage.items(), key=lambda item: (item[0][0], int(item[0][1:]))))

    grade = 0.0
    correct_count = 0

    logging.info("\n--- Grading Details ---")
    for question_id_for_grading in q_ids_in_processing_order:
        question_data_grading = ROIs[question_id_for_grading]
        # *** Use the stored numerical index string for grading lookup ***
        question_numeric_index_str_grading = str(question_data_grading['index'])
        detected_answer = sorted_detected_answers.get(question_id_for_grading, 'no response')
        # *** Look up correct answers using the numerical index string ***
        correct_answers = correct_answers_dict_for_key.get(question_numeric_index_str_grading, [])
        correct_answers_str = ",".join(correct_answers) if correct_answers else "N/A"

        is_correct = False
        cleaned_detected_answer = detected_answer.strip().upper()
        if cleaned_detected_answer != 'NO RESPONSE' and cleaned_detected_answer != 'MULTIPLE':
            if cleaned_detected_answer in correct_answers:
                is_correct = True
                correct_count += 1

        # Log using the A01-style key for readability
        logging.info(f"Q: {question_id_for_grading}, Detected: '{detected_answer}', Correct: '{correct_answers_str}', MarkedCorrect: {is_correct}")

    logging.info("--- End Grading Details ---\n")

    if EXPECTED_TOTAL_QUESTIONS > 0:
        grade = (correct_count / EXPECTED_TOTAL_QUESTIONS) * 10.0
    else:
        grade = 0.0

    logging.info(f"Total questions expected: {EXPECTED_TOTAL_QUESTIONS}")
    logging.info(f"Correct count: {correct_count}")
    logging.info(f"Calculated Grade: {grade:.2f}/10")

    safe_student_id = re.sub(r'[^\w\.-]', '_', student_id)
    safe_answer_key_name = re.sub(r'[^\w\.-]', '_', answer_key_name)
    annotated_img_filename = f'{safe_student_id}_analyzed_{safe_answer_key_name}.png'
    csv_filename = f'{safe_student_id}_answers_{safe_answer_key_name}.csv'
    output_img_path = os.path.join(output_dir, annotated_img_filename)
    output_csv_path = os.path.join(output_dir, csv_filename)

    try:
        if display_image.shape[0] > DISPLAY_MAX_HEIGHT:
            scale_factor = DISPLAY_MAX_HEIGHT / display_image.shape[0]
            new_width = int(display_image.shape[1] * scale_factor)
            display_image_resized = cv2.resize(display_image, (new_width, DISPLAY_MAX_HEIGHT), interpolation=cv2.INTER_AREA)
            cv2.imwrite(output_img_path, display_image_resized)
        else:
            cv2.imwrite(output_img_path, display_image)
        logging.info(f"Annotated image saved as '{output_img_path}'")
    except Exception as e:
        logging.error(f"Error saving annotated image: {e}")
        output_img_path = None

    try:
        with open(output_csv_path, mode='w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            # CSV uses A01-style QuestionID
            writer.writerow(['StudentID', 'QuestionID', 'DetectedAnswer', 'CorrectAnswer(s)', 'IsCorrect', 'AnswerKeyUsed'])

            for question_csv in q_ids_in_processing_order: # 'A01', 'B01', etc.
                q_data_csv = ROIs[question_csv]
                # *** Get numerical index string for correct answer lookup ***
                q_idx_csv = str(q_data_csv['index'])
                detected_ans_for_csv = sorted_detected_answers.get(question_csv, 'no response')
                # *** Look up correct answer list using numerical index string ***
                correct_ans_list_for_csv = correct_answers_dict_for_key.get(q_idx_csv, [])
                correct_ans_str_for_csv = ",".join(correct_ans_list_for_csv) if correct_ans_list_for_csv else 'N/A'
                is_correct_val = 'No'
                det_ans_upper = detected_ans_for_csv.upper()
                if det_ans_upper != 'NO RESPONSE' and det_ans_upper != 'MULTIPLE':
                    if det_ans_upper in correct_ans_list_for_csv:
                         is_correct_val = 'Yes'

                # Write A01-style key to CSV
                writer.writerow([student_id, question_csv, detected_ans_for_csv, correct_ans_str_for_csv, is_correct_val, answer_key_name])
        logging.info(f"Detected answers saved to '{output_csv_path}'")
    except Exception as e:
        logging.error(f"Error saving CSV file: {e}")
        output_csv_path = None

    return student_id, grade, sorted_detected_answers, output_img_path, output_csv_path


# --- process_all_images_in_directory (No changes needed) ---
def process_all_images_in_directory(directory='uploads', output_dir='static/results', answer_key_name='DefaultKey'):
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
        except OSError as e:
            logging.error(f"Error creating output directory {output_dir}: {e}")
            return []

    logging.info(f"Starting batch processing in directory: {directory} using answer key: {answer_key_name}")
    safe_answer_key_name = re.sub(r'[^\w\.-]', '_', answer_key_name)
    summary_csv_filename = f'exam_results_summary_{safe_answer_key_name}.csv'
    summary_csv_path = os.path.join(output_dir, summary_csv_filename)
    processed_results = []

    try:
        with open(summary_csv_path, mode='w', newline='') as csvfile_summary:
            summary_writer = csv.writer(csvfile_summary)
            summary_writer.writerow(['StudentID', 'Grade', 'OriginalFilename', 'AnnotatedImage', 'AnswersCSV', 'AnswerKeyUsed'])

            files_to_process = []
            try:
                valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff')
                files_to_process = [f for f in os.listdir(directory) if f.lower().endswith(valid_extensions)]
            except Exception as e:
                 logging.error(f"Error listing files in {directory}: {e}")
                 return []

            if not files_to_process:
                logging.info(f"No compatible image files found in {directory}.")
                return []

            for filename in files_to_process:
                image_path = os.path.join(directory, filename)
                logging.info(f"\nProcessing: {filename}")
                student_id_from_filename = os.path.splitext(filename)[0]

                try:
                    s_id, grade_val, _, annotated_img_path_res, csv_file_path_res = analyze_exam_sheet(
                        image_path,
                        output_dir=output_dir,
                        answer_key_name=answer_key_name
                    )

                    if s_id is not None:
                        result_status = "Success" if grade_val is not None else "Analysis Incomplete"
                        processed_results.append({
                            "student_id": s_id,
                            "grade": grade_val,
                            "original_filename": filename,
                            "status": result_status
                        })
                        annotated_img_basename = os.path.basename(annotated_img_path_res) if annotated_img_path_res else 'Save_Failed'
                        csv_basename = os.path.basename(csv_file_path_res) if csv_file_path_res else 'Save_Failed'
                        summary_writer.writerow([
                            s_id,
                            f"{grade_val:.2f}" if grade_val is not None else 'N/A',
                            filename,
                            annotated_img_basename,
                            csv_basename,
                            answer_key_name
                        ])
                    else:
                        logging.warning(f"Analysis returned None for student ID for {filename}. Skipping summary row.")
                        processed_results.append({"student_id": student_id_from_filename, "grade": None, "original_filename": filename, "status": "Analysis Failed (No ID)"})

                except Exception as e:
                    logging.exception(f"A critical error occurred during processing of {filename}: {e}")
                    summary_writer.writerow([student_id_from_filename, 'Error', filename, 'Processing Error', 'Processing Error', answer_key_name])
                    processed_results.append({"student_id": student_id_from_filename, "grade": None, "original_filename": filename, "status": "Processing Error"})

    except IOError as e:
        logging.error(f"Error creating or writing to summary CSV {summary_csv_path}: {e}")
        return []
    logging.info(f"\nBatch processing finished. Summary saved to {summary_csv_path}")
    return processed_results


# --- Main execution block (No changes needed) ---
if __name__ == '__main__':
    # Setup directories
    if not os.path.exists('uploads'): os.makedirs('uploads')
    if not os.path.exists('static/results'): os.makedirs('static/results', exist_ok=True)

    # Create a dummy image if uploads folder is empty
    dummy_image_name = 'sample_exam_test.png'; dummy_image_path = os.path.join('uploads', dummy_image_name)
    try:
        upload_files = os.listdir('uploads')
        if not any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff')) for f in upload_files):
            dummy_img_array = np.zeros((2500, 2000, 3), dtype=np.uint8) # Example dimensions
            cv2.putText(dummy_img_array, "Dummy Image - Scan Here", (100, 1200), cv2.FONT_HERSHEY_SIMPLEX, 3, (255,255,255), 5)
            cv2.imwrite(dummy_image_path, dummy_img_array)
            logging.info(f"Created dummy image: {dummy_image_path} because 'uploads' was empty.")
    except FileNotFoundError:
         logging.info("'uploads' directory not found initially, created.")
         # Optionally create dummy image here too if needed after creating the directory
    except Exception as e:
         logging.error(f"Could not check uploads or create dummy image: {e}")

    # --- Direct Test ---
    logging.info("\nStarting direct test of exam_analysis.py...")

    # Example of adding a key using the NEW format for testing
    new_format_key_name = "Test Key New Format"
    new_format_answers = "; ".join([f"{map_index_to_roi_key(i)}:A" for i in range(1, EXPECTED_TOTAL_QUESTIONS + 1)])
    # Modify one answer for variety: e.g., B05 (index 20) to B,D
    new_format_answers = new_format_answers.replace("B05:A", "B05:B,D")
    # print("Generated Test Key String:\n", new_format_answers) # Optional: print to verify format

    load_correct_answers() # Load any existing keys first
    success, msg = add_correct_answer_key(new_format_key_name, new_format_answers)
    if success:
        logging.info(f"Successfully added test key '{new_format_key_name}'.")
        test_key_name = new_format_key_name # Use the newly added key for the test run
    else:
        logging.error(f"Failed to add test key '{new_format_key_name}': {msg}")
        # Fallback to existing key if adding failed
        available_keys_for_test = list(CORRECT_ANSWERS.keys())
        if available_keys_for_test:
            test_key_name = available_keys_for_test[0]
            logging.warning(f"Using first available key '{test_key_name}' for testing instead.")
        else:
            test_key_name = None
            logging.error("Error: No answer keys available and adding test key failed. Cannot run test processing.")

    # Run batch processing if a key is available
    if test_key_name:
        logging.info(f"Using answer key for testing: '{test_key_name}'")
        results = process_all_images_in_directory('uploads', output_dir='static/results', answer_key_name=test_key_name)
        logging.info("\nTest Batch Processing Results:")
        if results:
            for res in results:
                grade_str = f"{res.get('grade'):.2f}" if res.get('grade') is not None else "N/A"
                logging.info(f"   Student: {res.get('student_id')}, Grade: {grade_str}, File: {res.get('original_filename')}, Status: {res.get('status')}")
        else:
            logging.info("   No results generated (check for errors above).")
    else:
        logging.info("Skipping test processing as no answer key could be set.")