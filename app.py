# from flask import Flask, request, render_template, jsonify, session, send_from_directory
# from werkzeug.utils import secure_filename
# import openai
# import os
# from gtts import gTTS
# import whisper  
# import json
# from pydub import AudioSegment
# from tempfile import NamedTemporaryFile
# from datetime import datetime
# import logging
# import gc
# import time
# from concurrent.futures import ThreadPoolExecutor
# from functools import lru_cache
# from functools import wraps

# logging.basicConfig(level=logging.INFO, 
#                     format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# OPENAI_API_KEY = "openai_api_key_here"  
# openai.api_key = OPENAI_API_KEY

# app = Flask(__name__)
# app.secret_key = 'supersecretkey'
# executor = ThreadPoolExecutor(max_workers=5)

# UPLOAD_FOLDER = 'uploads/'
# USER_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'user_audio')
# AI_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'ai_audio')
# CONCEPT_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'concept_audio')
# LOGS_FOLDER = os.path.join(UPLOAD_FOLDER, 'Logs')
# STATIC_FOLDER = 'static'
# ALLOWED_EXTENSIONS = {'txt', 'png', 'jpg', 'jpeg', 'gif', 'pdf', 'mp4', 'wav', 'mp3', 'ogg'}

# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# app.config['USER_AUDIO_FOLDER'] = USER_AUDIO_FOLDER
# app.config['AI_AUDIO_FOLDER'] = AI_AUDIO_FOLDER
# app.config['CONCEPT_AUDIO_FOLDER'] = CONCEPT_AUDIO_FOLDER
# app.config['LOGS_FOLDER'] = LOGS_FOLDER

# os.makedirs(USER_AUDIO_FOLDER, exist_ok=True)
# os.makedirs(AI_AUDIO_FOLDER, exist_ok=True)
# os.makedirs(CONCEPT_AUDIO_FOLDER, exist_ok=True)
# os.makedirs(LOGS_FOLDER, exist_ok=True)
# os.makedirs(STATIC_FOLDER, exist_ok=True)

# def check_paths():
#     """Verify all required paths exist and are writable."""
#     paths = [
#         app.config['UPLOAD_FOLDER'],
#         app.config['USER_AUDIO_FOLDER'],
#         app.config['AI_AUDIO_FOLDER'],
#         app.config['CONCEPT_AUDIO_FOLDER'],
#         STATIC_FOLDER
#     ]
#     for path in paths:
#         if not os.path.exists(path):
#             logger.info(f"Creating path: {path}")
#             os.makedirs(path, exist_ok=True)
#         if not os.access(path, os.W_OK):
#             logger.warning(f"WARNING: Path not writable: {path}")
#             return False
#     return True

# def allowed_file(filename):
#     """Check if the file type is allowed."""
#     return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# try:
#     logger.info("Loading Whisper model...")
#     model = whisper.load_model("small")
#     logger.info("Whisper model loaded successfully")
# except Exception as e:
#     logger.error(f"Failed to load Whisper model: {str(e)}")
#     model = None

# def speech_to_text(audio_file_path):
#     """Convert audio to text using OpenAI Whisper API or local fallback."""
#     try:
#         with open(audio_file_path, "rb") as audio_file:
#             transcript = openai.Audio.transcribe(
#                 model="whisper-1",
#                 file=audio_file
#             )
#         return transcript.text
#     except Exception as e:
#         print(f"Error using OpenAI Whisper API: {str(e)}")
#         print("Falling back to local Whisper model...")
        
#         try:
#             result = model.transcribe(audio_file_path)
#             return result["text"]
#         except Exception as e2:
#             print(f"Error using local Whisper model: {str(e2)}")
#             return "Sorry, I couldn't understand the audio."

# def get_interaction_id():
#     """Generate a unique interaction ID based on timestamp."""
#     return f"INT_{datetime.now().strftime('%Y%m%d%H%M%S')}"


# def initialize_log_file(interaction_id, trial_type="Trial_1"):
#     """Initialize a new log file with header information for each server reload."""
#     timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
#     log_filename = f"{trial_type}_log_{timestamp}.txt" 
#     log_file_path = os.path.join(app.config['LOGS_FOLDER'], log_filename)
    
#     counter = 1
#     while os.path.exists(log_file_path):
#         log_filename = f"conversation_log_{timestamp}_{counter}.txt"
#         log_file_path = os.path.join(app.config['LOGS_FOLDER'], log_filename)
#         counter += 1

#     try:
#         with open(log_file_path, "w", encoding="utf-8") as file:
#             file.write("=" * 80 + "\n")
#             file.write("CONVERSATION LOG\n")
#             file.write("=" * 80 + "\n\n")
#             file.write(f"INTERACTION ID: {interaction_id}\n")
#             file.write(f"VERSION: 2\n")
#             file.write(f"TRIAL: {trial_type}\n")
#             file.write(f"TIMESTAMP: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
#             file.write("\n" + "-" * 80 + "\n\n")
        
#         app.config['CURRENT_LOG_FILE'] = log_filename
#         return True
#     except Exception as e:
#         print(f"Error initializing log file: {str(e)}")
#         return False
    
# def log_interaction(speaker, concept_name, text):
#     """Log the interaction to the current log file with timestamp."""
#     try:
#         timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
#         current_log_file = app.config.get('CURRENT_LOG_FILE')
        
#         if not current_log_file:
#             interaction_id = session.get('interaction_id', get_interaction_id())
#             trial_type = session.get('trial_type', 'Trial_1')
#             initialize_log_file(interaction_id, trial_type)
#             current_log_file = app.config.get('CURRENT_LOG_FILE')
        
#         log_file_path = os.path.join(app.config['LOGS_FOLDER'], current_log_file)
        
#         with open(log_file_path, "a", encoding="utf-8") as file:
#             file.write(f"[{timestamp}] {speaker}: {text}\n\n")
            
#         print(f"Interaction logged: {speaker} in file {current_log_file}")
#         return True
#     except Exception as e:
#         print(f"Error logging interaction: {str(e)}")
#         return False
    
# def get_audio_filename(prefix, interaction_id, extension='.mp3'):
#     """Generate a unique audio filename with the interaction ID."""
#     timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
#     return f"{prefix}_{interaction_id}_{timestamp}{extension}"

# def generate_audio(text, file_path):
#     """Generate speech (audio) from the provided text using gTTS."""
#     try:
#         tts = gTTS(text=text, lang='en')
#         tts.save(file_path)
#         if os.path.exists(file_path):
#             print(f"Audio file successfully saved: {file_path}")
#             return True
#         else:
#             print(f"Failed to save audio file: {file_path}")
#             return False
#     except Exception as e:
#         print(f"Error generating audio: {str(e)}")
#         return False
    
    
# @app.route('/save_screen_recording', methods=['POST'])
# def save_screen_recording():
#     if 'screen_recording' not in request.files:
#         return jsonify({'error': 'No recording file found'}), 400
        
#     file = request.files['screen_recording']
#     trial_type = request.form.get('trial_type', 'unknown')
    
#     recording_dir = os.path.join(app.root_path, 'static', 'recordings')
#     os.makedirs(recording_dir, exist_ok=True)
    
#     timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
#     filename = f'screen_recording_{trial_type}_{timestamp}.webm'
#     filepath = os.path.join(recording_dir, filename)
    
#     file.save(filepath)
    
#     return jsonify({
#         'success': True,
#         'filename': filename,
#         'path': f'/uploads/recordings/{filename}'
#     })

# @app.route('/')
# def home():
#     """Render the home page."""
#     session['interaction_id'] = get_interaction_id()
#     session['trial_type'] = request.args.get('trial', 'Trial_1')
    
#     initialize_log_file(session['interaction_id'], session['trial_type'])
    
#     log_interaction("SYSTEM", None, f"Session initialized with trial type: {session['trial_type']}")
    
#     return render_template('index.html')

# @app.route('/resources/<path:filename>')
# def download_resource(filename):
#     """Serve resources like PDF or video files from the resources folder."""
#     return send_from_directory('resources', filename)

# @lru_cache
# def load_concepts():
#     """Load concepts from a JSON file or create if it doesn't exist."""
#     try:
#         logger.info("Loading concepts from JSON file...")
#         with open("concepts.json", "r") as file:
#             concepts = json.load(file)["concepts"]
#             logger.info(f"Loaded {len(concepts)} concepts successfully")
#             return concepts
#     except (FileNotFoundError, json.JSONDecodeError) as e:
#         logger.warning(f"Concepts file not found or invalid: {str(e)}. Creating default concepts...")
#         concepts = [
#             {
#                 "name": "Univariate Analysis",
#                 "golden_answer": "Univariate analysis examines a single variable to describe its characteristics and identify patterns in data."
#             },
#             {
#                 "name": "Measures of Central Tendency",
#                 "golden_answer": "Measures of central tendency, like mean, median, and mode, help summarize the data."
#             },
#             {
#                 "name": "Measures of Dispersion",
#                 "golden_answer": "Measures of dispersion, like variance, standard deviation, quantiles, and range, indicate how spread out the values are. This type of analysis is essential in statistics and research to understand data distributions and make informed comparisons between variables."
#             }
#         ]
        
#         try:
#             with open("concepts.json", "w") as file:
#                 json.dump({"concepts": concepts}, file, indent=4)
#             logger.info("Default concepts created and saved successfully")
#         except Exception as write_err:
#             logger.error(f"Error saving default concepts: {str(write_err)}")
        
#         return concepts
        
# @app.route('/set_context', methods=['POST'])
# def set_context():
#     """Set the context for a specific concept from the provided material."""
#     concept_name = request.form.get('concept_name')
#     logger.info(f"Setting context for concept: {concept_name}")
    
#     concepts = load_concepts()
    
#     selected_concept = next((c for c in concepts if c["name"] == concept_name), None)

#     if not selected_concept:
#         logger.error(f"Invalid concept selection: {concept_name}")
#         return jsonify({'error': 'Invalid concept selection'})

#     session['concept_name'] = selected_concept["name"]
#     session['golden_answer'] = selected_concept["golden_answer"]
#     session['attempt_count'] = 0
    
#     log_interaction("SYSTEM", selected_concept["name"], 
#                     f"Context set for concept: {selected_concept['name']}")

#     logger.info(f"Context set successfully for: {selected_concept['name']}")
#     return jsonify({'message': f'Context set for {selected_concept["name"]}.'})

# @app.route('/get_intro_audio', methods=['GET'])
# def get_intro_audio():
#     """Generate the introductory audio message for the chatbot."""
#     interaction_id = session.get('interaction_id', get_interaction_id())
#     intro_text = "Hello, let us begin the self-explanation journey, just go through each concept of the following Univariate Analysis concepts, and then go on with explaining what you understood from each concept!"
    
#     intro_audio_filename = get_audio_filename('intro', interaction_id)
#     intro_audio_path = os.path.join(app.config['AI_AUDIO_FOLDER'], intro_audio_filename)

#     generate_audio(intro_text, intro_audio_path)
    
#     log_interaction("AI", "Introduction", intro_text)
    
#     if os.path.exists(intro_audio_path):
#         intro_audio_url = f"/uploads/ai_audio/{intro_audio_filename}"
#         return jsonify({'intro_audio_url': intro_audio_url})
#     else:
#         return jsonify({'error': 'Failed to generate introduction audio'}), 500
    
# @app.route('/get_concept_audio/<concept_name>', methods=['GET'])
# def get_concept_audio(concept_name):
#     """Generate concept introduction audio message."""
#     interaction_id = session.get('interaction_id', get_interaction_id())
#     safe_concept = secure_filename(concept_name)
    
#     concept_audio_filename = get_audio_filename(f'concept_{safe_concept}', interaction_id)
#     concept_audio_path = os.path.join(app.config['CONCEPT_AUDIO_FOLDER'], concept_audio_filename)
    
#     concept_intro_text = f"Now go through this concept of {concept_name}, and try explaining what you understood from this concept in your own words!"
    
#     generate_audio(concept_intro_text, concept_audio_path)
    
#     log_interaction("AI", concept_name, concept_intro_text)
    
#     return send_from_directory(app.config['CONCEPT_AUDIO_FOLDER'], concept_audio_filename)

# @app.route('/submit_message', methods=['POST'])
# def submit_message():
#     """Handle the submission of user messages and generate AI responses."""
#     user_message = request.form.get('message')
#     audio_file = request.files.get('audio')
#     concept_name = request.form.get('concept_name')
#     interaction_id = session.get('interaction_id', get_interaction_id())

#     print(f"Received concept from frontend: {concept_name}")
      
#     if not user_message and not audio_file:
#         print("Error: No message or audio received!")  
#         return jsonify({'error': 'Message or audio is required.'})

#     if not concept_name:
#         print("Error: No concept detected!")  
#         return jsonify({'error': 'Concept not detected.'})

#     concepts = load_concepts()
#     selected_concept = next((c for c in concepts if c["name"] == concept_name), None)

#     if not selected_concept:
#         print("Error: Concept not found in system!")  
#         return jsonify({'error': 'Concept not found.'})

#     print(f"Using concept: {selected_concept}")

#     if 'concept_attempts' not in session:
#         session['concept_attempts'] = {}

#     if concept_name not in session['concept_attempts']:
#         session['concept_attempts'][concept_name] = 0

#     current_attempt_count = session['concept_attempts'][concept_name]
#     print(f"Current attempt count for {concept_name}: {current_attempt_count}")

#     if audio_file:
#         user_audio_filename = get_audio_filename('user', interaction_id, '.wav')
#         audio_path = os.path.join(app.config['USER_AUDIO_FOLDER'], user_audio_filename)
#         audio_file.save(audio_path)
#         user_message = speech_to_text(audio_path)
    
#     log_interaction("USER", concept_name, user_message)

#     # Increment the attempt count AFTER generating the response
#     session['concept_attempts'][concept_name] = current_attempt_count + 1
#     print(f"Updated attempt count for {concept_name}: {session['concept_attempts'][concept_name]}")

#     ai_response = generate_response(
#         user_message,
#         selected_concept["name"],
#         selected_concept["golden_answer"],
#         current_attempt_count  # Pass the current count (not incremented yet)
#     )


#     if not ai_response:
#         print("Error: AI response generation failed!")  
#         return jsonify({'error': 'AI response generation failed.'})

#     print(f"AI Response: {ai_response}") 

#     log_interaction("AI", concept_name, ai_response)

#     ai_response_filename = get_audio_filename('ai_response', interaction_id)
#     audio_response_path = os.path.join(app.config['AI_AUDIO_FOLDER'], ai_response_filename)
#     generate_audio(ai_response, audio_response_path)

#     if not os.path.exists(audio_response_path):
#         print("Error: AI audio file not created!")  
#         return jsonify({'error': 'AI audio generation failed.'})

#     ai_audio_url = f"/uploads/ai_audio/{ai_response_filename}"
#     return jsonify({
#         'response': ai_response,
#         'ai_audio_url': ai_audio_url,
#         'user_transcript': user_message 
#     })

# def generate_response(user_message, concept_name, golden_answer, attempt_count):
#     """Generate a response dynamically using OpenAI GPT."""

#     if not golden_answer or not concept_name:
#         return "As your tutor, I'm not able to provide you with feedback without having context about your explanation. Please ensure the context is set."
    
#     base_prompt = f"""
#     Context: {concept_name}
#     Golden Answer: {golden_answer}
#     User Explanation: {user_message}
    
#     You are a friendly and encouraging tutor, helping a student refine their understanding of a concept in a supportive way. Your goal is to evaluate the student's explanation of this concept and provide warm, engaging feedback:
#         - If the user's explanation includes all the relevant aspects of the golden answer, celebrate their effort and reinforce their confidence. Inform them that their explanation is correct and they have completed the self-explanation for this concept. Instruct them to proceed to the next concept.
#         - If the explanation is partially correct, acknowledge their progress and gently guide them toward refining their answer.
#         - If it's incorrect, provide constructive and positive feedback without discouraging them. Offer hints and encouragement.
#         - Do not provide the golden answer or parts of it directly. Instead, guide the user to arrive at it themselves.
#     Use a conversational tone, making the user feel comfortable and motivated to keep trying but refrain from using emojis in the text.
#     Ignore any emojis that are part of the user's explanation.
#     If the user is not talking about the current concept, guide them back to the task of self-explaining the current concept.
#     """

#     user_prompt = f"""
#     User Explanation: {user_message}
#     """

#     if attempt_count == 0:
#         user_prompt += "\nThis is the user's first attempt. If the explanation is correct, communicate this to the user. If it is not correct, provide general feedback and a broad hint to guide the user."
#     elif attempt_count == 1:
#         user_prompt += "\nThis is the user's second attempt. If the explanation is correct, communicate this to the user. If it is not correct, provide more specific feedback and highlight key elements the user missed."
#     elif attempt_count == 2:
#         user_prompt += "\nThis is the user's third attempt. If the explanation is correct, communicate this to the user. If it is not correct, provide the correct explanation, as the user has made multiple attempts."
#     else:
#         user_prompt += "\nLet the user know they have completed three self-explanation attempts. Instruct them to stop here and tell them to continue with the next concept."

#     try:
#         response = openai.ChatCompletion.create(
#             model="gpt-4o-mini",
#             messages=[{"role": "system", "content": base_prompt},
#                       {"role": "user", "content": user_prompt}],
#             max_tokens=200,
#             temperature=0.7,
#         )

#         ai_response = response.choices[0].message.content
#         attempt_count += 1
#         session['attempt_count'] = attempt_count
#         return ai_response
#     except Exception as e:
#         return f"Error generating AI response: {str(e)}"



# @app.route('/uploads/<folder>/<filename>')
# def serve_audio(folder, filename):
#     """Serve the audio files from the uploads folder."""
#     print(f"Serving audio from folder: {folder}, file: {filename}")
    
#     full_path = os.path.join(app.config['UPLOAD_FOLDER'], folder, filename)
#     exists = os.path.exists(full_path)
#     print(f"Looking for file at: {full_path} - Exists: {exists}")
    
#     return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], folder), filename)
    
# @app.route('/pdf')
# def serve_pdf():
#     return send_from_directory('resources', 'Univariate Analysis.pdf')

# @app.route('/set_trial_type', methods=['POST'])
# def set_trial_type():
#     """Set the trial type (Trial_1, Trial_2, or Test) via POST request from frontend."""
#     data = request.get_json()
#     trial_type = data.get('trial_type', 'Trial_1')

#     valid_types = ["Trial_1", "Trial_2", "Test"]
#     if trial_type not in valid_types:
#         return jsonify({"error": "Invalid trial type"}), 400

#     old_trial_type = session.get('trial_type', 'None')

#     session['trial_type'] = trial_type
#     session['interaction_id'] = get_interaction_id()
#     session['concept_attempts'] = {}

#     initialize_log_file(session['interaction_id'], trial_type)

#     log_interaction("SYSTEM", None, f"Trial type changed from {old_trial_type} to {trial_type}")

#     return jsonify({
#         'status': 'success',
#         'trial_type': trial_type,
#         'interaction_id': session['interaction_id']
#     })

# if __name__ == '__main__':
#     startup_interaction_id = get_interaction_id()
#     app.run(port=5000)
#     # app.run(host='0.0.0.0', port=5000)































from flask import Flask, request, render_template, jsonify, session, send_from_directory
from werkzeug.utils import secure_filename
import openai
import os
from gtts import gTTS
import whisper  
import json
from pydub import AudioSegment
from tempfile import NamedTemporaryFile
from datetime import datetime
import logging
import gc
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from functools import wraps

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OPENAI_API_KEY = "openai_api_key_here"  
openai.api_key = OPENAI_API_KEY

app = Flask(__name__)
app.secret_key = 'supersecretkey'
executor = ThreadPoolExecutor(max_workers=5)

UPLOAD_FOLDER = 'uploads/'
USER_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'user_audio')
AI_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'ai_audio')
CONCEPT_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'concept_audio')
LOGS_FOLDER = os.path.join(UPLOAD_FOLDER, 'Logs')
STATIC_FOLDER = 'static'
ALLOWED_EXTENSIONS = {'txt', 'png', 'jpg', 'jpeg', 'gif', 'pdf', 'mp4', 'wav', 'mp3', 'ogg'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['USER_AUDIO_FOLDER'] = USER_AUDIO_FOLDER
app.config['AI_AUDIO_FOLDER'] = AI_AUDIO_FOLDER
app.config['CONCEPT_AUDIO_FOLDER'] = CONCEPT_AUDIO_FOLDER
app.config['LOGS_FOLDER'] = LOGS_FOLDER

os.makedirs(USER_AUDIO_FOLDER, exist_ok=True)
os.makedirs(AI_AUDIO_FOLDER, exist_ok=True)
os.makedirs(CONCEPT_AUDIO_FOLDER, exist_ok=True)
os.makedirs(LOGS_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

def check_paths():
    """Verify all required paths exist and are writable."""
    paths = [
        app.config['UPLOAD_FOLDER'],
        app.config['USER_AUDIO_FOLDER'],
        app.config['AI_AUDIO_FOLDER'],
        app.config['CONCEPT_AUDIO_FOLDER'],
        STATIC_FOLDER
    ]
    for path in paths:
        if not os.path.exists(path):
            logger.info(f"Creating path: {path}")
            os.makedirs(path, exist_ok=True)
        if not os.access(path, os.W_OK):
            logger.warning(f"WARNING: Path not writable: {path}")
            return False
    return True

def allowed_file(filename):
    """Check if the file type is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

try:
    logger.info("Loading Whisper model...")
    model = whisper.load_model("small")
    logger.info("Whisper model loaded successfully")
except Exception as e:
    logger.error(f"Failed to load Whisper model: {str(e)}")
    model = None

def speech_to_text(audio_file_path):
    """Convert audio to text using OpenAI Whisper API or local fallback."""
    try:
        with open(audio_file_path, "rb") as audio_file:
            transcript = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file
            )
        return transcript.text
    except Exception as e:
        print(f"Error using OpenAI Whisper API: {str(e)}")
        print("Falling back to local Whisper model...")
        
        try:
            result = model.transcribe(audio_file_path)
            return result["text"]
        except Exception as e2:
            print(f"Error using local Whisper model: {str(e2)}")
            return "Sorry, I couldn't understand the audio."

def get_interaction_id():
    """Generate a unique interaction ID based on timestamp."""
    return f"INT_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def initialize_log_file(interaction_id, trial_type="Trial_1"):
    """Initialize a new log file with header information for each server reload."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = f"{trial_type}_log_{timestamp}.txt" 
    log_file_path = os.path.join(app.config['LOGS_FOLDER'], log_filename)
    
    counter = 1
    while os.path.exists(log_file_path):
        log_filename = f"conversation_log_{timestamp}_{counter}.txt"
        log_file_path = os.path.join(app.config['LOGS_FOLDER'], log_filename)
        counter += 1

    try:
        with open(log_file_path, "w", encoding="utf-8") as file:
            file.write("=" * 80 + "\n")
            file.write("CONVERSATION LOG\n")
            file.write("=" * 80 + "\n\n")
            file.write(f"INTERACTION ID: {interaction_id}\n")
            file.write(f"VERSION: 2\n")
            file.write(f"TRIAL: {trial_type}\n")
            file.write(f"TIMESTAMP: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write("\n" + "-" * 80 + "\n\n")
        
        app.config['CURRENT_LOG_FILE'] = log_filename
        return True
    except Exception as e:
        print(f"Error initializing log file: {str(e)}")
        return False
    
def log_interaction(speaker, concept_name, text):
    """Log the interaction to the current log file with timestamp."""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        current_log_file = app.config.get('CURRENT_LOG_FILE')
        
        if not current_log_file:
            interaction_id = session.get('interaction_id', get_interaction_id())
            trial_type = session.get('trial_type', 'Trial_1')
            initialize_log_file(interaction_id, trial_type)
            current_log_file = app.config.get('CURRENT_LOG_FILE')
        
        log_file_path = os.path.join(app.config['LOGS_FOLDER'], current_log_file)
        
        with open(log_file_path, "a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {speaker}: {text}\n\n")
            
        print(f"Interaction logged: {speaker} in file {current_log_file}")
        return True
    except Exception as e:
        print(f"Error logging interaction: {str(e)}")
        return False
    
def get_audio_filename(prefix, interaction_id, extension='.mp3'):
    """Generate a unique audio filename with the interaction ID."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{prefix}_{interaction_id}_{timestamp}{extension}"

def generate_audio(text, file_path):
    """Generate speech (audio) from the provided text using gTTS."""
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(file_path)
        if os.path.exists(file_path):
            print(f"Audio file successfully saved: {file_path}")
            return True
        else:
            print(f"Failed to save audio file: {file_path}")
            return False
    except Exception as e:
        print(f"Error generating audio: {str(e)}")
        return False
    
    
@app.route('/save_screen_recording', methods=['POST'])
def save_screen_recording():
    if 'screen_recording' not in request.files:
        return jsonify({'error': 'No recording file found'}), 400
        
    file = request.files['screen_recording']
    trial_type = request.form.get('trial_type', 'unknown')
    
    recording_dir = os.path.join(app.root_path, 'static', 'recordings')
    os.makedirs(recording_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'screen_recording_{trial_type}_{timestamp}.webm'
    filepath = os.path.join(recording_dir, filename)
    
    file.save(filepath)
    
    return jsonify({
        'success': True,
        'filename': filename,
        'path': f'/uploads/recordings/{filename}'
    })

@app.route('/')
def home():
    """Render the home page."""
    session['interaction_id'] = get_interaction_id()
    session['trial_type'] = request.args.get('trial', 'Trial_1')
    
    initialize_log_file(session['interaction_id'], session['trial_type'])
    
    log_interaction("SYSTEM", None, f"Session initialized with trial type: {session['trial_type']}")
    
    return render_template('index.html')

@app.route('/resources/<path:filename>')
def download_resource(filename):
    """Serve resources like PDF or video files from the resources folder."""
    return send_from_directory('resources', filename)

@lru_cache
def load_concepts():
    """Load concepts from a JSON file or create if it doesn't exist."""
    try:
        logger.info("Loading concepts from JSON file...")
        with open("concepts.json", "r") as file:
            concepts = json.load(file)["concepts"]
            logger.info(f"Loaded {len(concepts)} concepts successfully")
            return concepts
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Concepts file not found or invalid: {str(e)}. Creating default concepts...")
        concepts = [
            {
                "name": "Univariate Analysis",
                "golden_answer": "Univariate analysis examines a single variable to describe its characteristics and identify patterns in data."
            },
            {
                "name": "Measures of Central Tendency",
                "golden_answer": "Measures of central tendency, like mean, median, and mode, help summarize the data."
            },
            {
                "name": "Measures of Dispersion",
                "golden_answer": "Measures of dispersion, like variance, standard deviation, quantiles, and range, indicate how spread out the values are. This type of analysis is essential in statistics and research to understand data distributions and make informed comparisons between variables."
            }
        ]
        
        try:
            with open("concepts.json", "w") as file:
                json.dump({"concepts": concepts}, file, indent=4)
            logger.info("Default concepts created and saved successfully")
        except Exception as write_err:
            logger.error(f"Error saving default concepts: {str(write_err)}")
        
        return concepts
        
@app.route('/set_context', methods=['POST'])
def set_context():
    """Set the context for a specific concept from the provided material."""
    concept_name = request.form.get('concept_name')
    logger.info(f"Setting context for concept: {concept_name}")
    
    concepts = load_concepts()
    
    selected_concept = next((c for c in concepts if c["name"] == concept_name), None)

    if not selected_concept:
        logger.error(f"Invalid concept selection: {concept_name}")
        return jsonify({'error': 'Invalid concept selection'})

    session['concept_name'] = selected_concept["name"]
    session['golden_answer'] = selected_concept["golden_answer"]
    session['attempt_count'] = 0
    
    log_interaction("SYSTEM", selected_concept["name"], 
                    f"Context set for concept: {selected_concept['name']}")

    logger.info(f"Context set successfully for: {selected_concept['name']}")
    return jsonify({'message': f'Context set for {selected_concept["name"]}.'})

@app.route('/get_intro_audio', methods=['GET'])
def get_intro_audio():
    """Generate the introductory audio message for the chatbot."""
    interaction_id = session.get('interaction_id', get_interaction_id())
    intro_text = "Hello, let us begin the self-explanation journey, just go through each concept of the following Univariate Analysis concepts, and then go on with explaining what you understood from each concept!"
    
    intro_audio_filename = get_audio_filename('intro', interaction_id)
    intro_audio_path = os.path.join(app.config['AI_AUDIO_FOLDER'], intro_audio_filename)

    generate_audio(intro_text, intro_audio_path)
    
    log_interaction("AI", "Introduction", intro_text)
    
    if os.path.exists(intro_audio_path):
            intro_audio_url = f"/uploads/ai_audio/{intro_audio_filename}"
            return jsonify({
                'intro_audio_url': intro_audio_url,
                'intro_text': intro_text
            })
    else:
            return jsonify({'error': 'Failed to generate introduction audio'}), 500

@app.route('/get_concept_audio/<concept_name>', methods=['GET'])
def get_concept_audio(concept_name):
    """Generate concept introduction audio message."""
    interaction_id = session.get('interaction_id', get_interaction_id())
    safe_concept = secure_filename(concept_name)
    
    concept_audio_filename = get_audio_filename(f'concept_{safe_concept}', interaction_id)
    concept_audio_path = os.path.join(app.config['CONCEPT_AUDIO_FOLDER'], concept_audio_filename)
    
    concept_intro_text = f"Now go through this concept of {concept_name}, and try explaining what you understood from this concept in your own words!"
    
    generate_audio(concept_intro_text, concept_audio_path)
    
    log_interaction("AI", concept_name, concept_intro_text)
    
    return send_from_directory(app.config['CONCEPT_AUDIO_FOLDER'], concept_audio_filename)

@app.route('/submit_message', methods=['POST'])
def submit_message():
    """Handle the submission of user messages and generate AI responses."""
    user_message = request.form.get('message')
    audio_file = request.files.get('audio')
    concept_name = request.form.get('concept_name')
    interaction_id = session.get('interaction_id', get_interaction_id())

    print(f"Received concept from frontend: {concept_name}")
      
    if not user_message and not audio_file:
        print("Error: No message or audio received!")  
        return jsonify({'error': 'Message or audio is required.'})

    if not concept_name:
        print("Error: No concept detected!")  
        return jsonify({'error': 'Concept not detected.'})

    concepts = load_concepts()
    selected_concept = next((c for c in concepts if c["name"] == concept_name), None)

    if not selected_concept:
        print("Error: Concept not found in system!")  
        return jsonify({'error': 'Concept not found.'})

    print(f"Using concept: {selected_concept}")

    if 'concept_attempts' not in session:
        session['concept_attempts'] = {}

    if concept_name not in session['concept_attempts']:
        session['concept_attempts'][concept_name] = 0

    current_attempt_count = session['concept_attempts'][concept_name]
    print(f"Current attempt count for {concept_name}: {current_attempt_count}")

    if audio_file:
        user_audio_filename = get_audio_filename('user', interaction_id, '.wav')
        audio_path = os.path.join(app.config['USER_AUDIO_FOLDER'], user_audio_filename)
        audio_file.save(audio_path)
        user_message = speech_to_text(audio_path)
    
    log_interaction("USER", concept_name, user_message)

    ai_response = generate_response(
        user_message,
        selected_concept["name"],
        selected_concept["golden_answer"],
        current_attempt_count
    )

    if not ai_response:
        print("Error: AI response generation failed!")  
        return jsonify({'error': 'AI response generation failed.'})

    print(f"AI Response: {ai_response}") 

    # Increment the attempt count AFTER generating the response
    session['concept_attempts'][concept_name] = current_attempt_count + 1
    session.modified = True  # Ensure session changes are saved
    print(f"Updated attempt count for {concept_name}: {session['concept_attempts'][concept_name]}")

    log_interaction("AI", concept_name, ai_response)

    ai_response_filename = get_audio_filename('ai_response', interaction_id)
    audio_response_path = os.path.join(app.config['AI_AUDIO_FOLDER'], ai_response_filename)
    generate_audio(ai_response, audio_response_path)

    if not os.path.exists(audio_response_path):
        print("Error: AI audio file not created!")  
        return jsonify({'error': 'AI audio generation failed.'})

    # Check if this was the third attempt and include a flag in the response
    should_move_to_next = current_attempt_count >= 2  # This is the third attempt (index 2)
    
    ai_audio_url = f"/uploads/ai_audio/{ai_response_filename}"
    return jsonify({
        'response': ai_response,
        'ai_audio_url': ai_audio_url,
        'user_transcript': user_message,
        'should_move_to_next': should_move_to_next,
        'attempt_count': current_attempt_count + 1
    })

def generate_response(user_message, concept_name, golden_answer, attempt_count):
    """Generate a response dynamically using OpenAI GPT."""

    if not golden_answer or not concept_name:
        return "As your tutor, I'm not able to provide you with feedback without having context about your explanation. Please ensure the context is set."
    
    base_prompt = f"""
    Context: {concept_name}
    Golden Answer: {golden_answer}
    User Explanation: {user_message}
    
    You are a friendly and encouraging tutor, helping a student refine their understanding of a concept in a supportive way. Your goal is to evaluate the student's explanation of this concept and provide warm, engaging feedback:
        - If the user's explanation includes all the relevant aspects of the golden answer, celebrate their effort and reinforce their confidence. Inform them that their explanation is correct and they have completed the self-explanation for this concept. Instruct them to proceed to the next concept.
        - If the explanation is partially correct, acknowledge their progress and gently guide them toward refining their answer.
        - If it's incorrect, provide constructive and positive feedback without discouraging them. Offer hints and encouragement.
        - Do not provide the golden answer or parts of it directly. Instead, guide the user to arrive at it themselves.
    Use a conversational tone, making the user feel comfortable and motivated to keep trying but refrain from using emojis in the text.
    Ignore any emojis that are part of the user's explanation.
    If the user is not talking about the current concept, guide them back to the task of self-explaining the current concept.
    """

    user_prompt = f"""
    User Explanation: {user_message}
    """

    if attempt_count == 0:
        user_prompt += "\nThis is the user's first attempt at explaining this concept. If the explanation is correct, communicate this to the user. If it is not correct, provide general feedback and a broad hint to guide the user."
    elif attempt_count == 1:
        user_prompt += "\nThis is the user's second attempt at explaining this concept. If the explanation is correct, communicate this to the user. If it is not correct, provide more specific feedback and highlight key elements the user missed."
    elif attempt_count >= 2:
        user_prompt += "\nThis is the user's third or final attempt at explaining this concept. If the explanation is correct, communicate this to the user. If it is not correct, provide the correct explanation in a supportive way, and EXPLICITLY tell them to move on to the next concept by saying 'Please move on to the next concept now.'"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": base_prompt},
                      {"role": "user", "content": user_prompt}],
            max_tokens=200,
            temperature=0.7,
        )

        ai_response = response.choices[0].message.content
        return ai_response
    except Exception as e:
        return f"Error generating AI response: {str(e)}"

@app.route('/change_concept', methods=['POST'])
def change_concept():
    """Handle notification from frontend when user changes concepts/slides"""
    data = request.get_json()
    new_concept = data.get('concept_name')
    
    if not new_concept:
        return jsonify({'error': 'No concept name provided'}), 400
    
    log_interaction("SYSTEM", new_concept, f"User navigated to concept: {new_concept}")
    
    session['current_concept'] = new_concept
    session.modified = True
    
    return jsonify({'status': 'success', 'current_concept': new_concept})
    
@app.route('/uploads/<folder>/<filename>')
def serve_audio(folder, filename):
    """Serve the audio files from the uploads folder."""
    print(f"Serving audio from folder: {folder}, file: {filename}")
    
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], folder, filename)
    exists = os.path.exists(full_path)
    print(f"Looking for file at: {full_path} - Exists: {exists}")
    
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], folder), filename)
    
@app.route('/pdf')
def serve_pdf():
    return send_from_directory('resources', 'Univariate Analysis.pdf')

@app.route('/set_trial_type', methods=['POST'])
def set_trial_type():
    """Set the trial type (Trial_1, Trial_2, or Test) via POST request from frontend."""
    data = request.get_json()
    trial_type = data.get('trial_type', 'Trial_1')

    valid_types = ["Trial_1", "Trial_2", "Test"]
    if trial_type not in valid_types:
        return jsonify({"error": "Invalid trial type"}), 400

    old_trial_type = session.get('trial_type', 'None')

    session['trial_type'] = trial_type
    session['interaction_id'] = get_interaction_id()
    session['concept_attempts'] = {}

    initialize_log_file(session['interaction_id'], trial_type)

    log_interaction("SYSTEM", None, f"Trial type changed from {old_trial_type} to {trial_type}")

    return jsonify({
        'status': 'success',
        'trial_type': trial_type,
        'interaction_id': session['interaction_id']
    })

if __name__ == '__main__':
    startup_interaction_id = get_interaction_id()
    app.run(port=5000)
    # app.run(host='0.0.0.0', port=5000)

















