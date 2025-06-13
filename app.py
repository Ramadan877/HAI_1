from flask import Flask, request, render_template, jsonify, session, send_from_directory
from werkzeug.utils import secure_filename
import openai
import os
import re
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
import shutil
import tempfile
import atexit
import signal
from functools import lru_cache


logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = openai.OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://api.openai.com/v1"
)

app = Flask(__name__)
app.secret_key = 'supersecretkey'
executor = ThreadPoolExecutor(max_workers=5)

UPLOAD_FOLDER = 'uploads/'
CONCEPT_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'concept_audio')
USER_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'User Data')

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CONCEPT_AUDIO_FOLDER'] = CONCEPT_AUDIO_FOLDER
app.config['USER_AUDIO_FOLDER'] = USER_AUDIO_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONCEPT_AUDIO_FOLDER, exist_ok=True)
os.makedirs(USER_AUDIO_FOLDER, exist_ok=True)

def get_participant_folder(participant_id, trial_type):
    """Get or create the participant's folder structure."""
    trial_folder_map = {
        'Trial_1': 'main_task_1',
        'Trial_2': 'main_task_2',
        'Test': 'test_task'
    }
    
    trial_folder_name = trial_folder_map.get(trial_type, trial_type.lower())
    
    participant_folder = os.path.join(USER_AUDIO_FOLDER, str(participant_id))
    trial_folder = os.path.join(participant_folder, trial_folder_name)
    screen_recordings_folder = os.path.join(trial_folder, 'Screen Recordings')

    os.makedirs(participant_folder, exist_ok=True)
    os.makedirs(trial_folder, exist_ok=True)
    os.makedirs(screen_recordings_folder, exist_ok=True)

    
    return {
        'participant_folder': participant_folder,
        'trial_folder': trial_folder,
        'screen_recordings_folder': screen_recordings_folder
    }

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

whisper_model = None

def get_whisper_model():
    global whisper_model
    if whisper_model is None:
        try:
            print("Loading Whisper model...")
            whisper_model = whisper.load_model("small")
            print("Whisper model loaded successfully")
        except Exception as e:
            print(f"Failed to load Whisper model: {str(e)}")
    return whisper_model

@lru_cache(maxsize=32)
def get_cached_audio(text):
    """Cache generated audio to avoid regenerating the same text."""
    temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
    temp_path = temp_file.name
    temp_file.close()
    
    try:
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(temp_path)
        return temp_path
    except Exception as e:
        print(f"Error in cached audio generation: {str(e)}")
        return None

@lru_cache(maxsize=32)
def cached_transcribe(audio_file_path_hash):
    """Helper function to enable caching of transcription results"""
    model = get_whisper_model()
    if model:
        result = model.transcribe(audio_file_path_hash)
        return result["text"]
    return "Transcription failed."

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
            return "Your audio input could not be processed."

def get_interaction_id(participant_id=None):
    """Generate a unique interaction ID based on timestamp."""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    if participant_id:
        return f"{participant_id}_{timestamp}"
    return timestamp

def initialize_log_file(interaction_id, participant_id=None, trial_type="Trial_1"):
    """Initialize a new log file with header information for each server reload."""
    if not participant_id:
        return False
        
    folders = get_participant_folder(participant_id, trial_type)
    log_filename = f"conversation_log_{participant_id}.txt"
    log_file_path = os.path.join(folders['trial_folder'], log_filename)

    try:
        with open(log_file_path, "w", encoding="utf-8") as file:
            file.write("=" * 80 + "\n")
            file.write("CONVERSATION LOG\n")
            file.write("=" * 80 + "\n\n")
            file.write(f"PARTICIPANT ID: {participant_id}\n")
            file.write(f"INTERACTION ID: {interaction_id}\n")
            file.write(f"VERSION: 1\n")
            file.write(f"TRIAL: {trial_type}\n")
            file.write(f"TIMESTAMP: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write("\n" + "-" * 80 + "\n\n")
        
        app.config['CURRENT_LOG_FILE'] = log_filename
        return True
    except Exception as e:
        print(f"Error initializing log file: {str(e)}")
        return False
    
def log_interaction(speaker, concept_name, message):
    """Log an interaction to the current log file."""
    try:
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')

        if not participant_id or not trial_type:
            print("Error logging interaction: Missing participant_id or trial_type in session")
            return False
            
        folders = get_participant_folder(participant_id, trial_type)
        log_file_path = os.path.join(folders['trial_folder'], f"conversation_log_{participant_id}.txt")
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(log_file_path, "a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {speaker} ({concept_name}): {message}\n")
        return True
    except Exception as e:
        print(f"Error logging interaction: {str(e)}")
        return False
    
def get_audio_filename(prefix, participant_id, interaction_number, extension='.mp3'):
    """Generate a unique audio filename with participant ID and interaction number."""
    return f"{prefix}_{interaction_number}_{participant_id}{extension}"

def generate_audio(text, file_path):
    """Generate speech (audio) from the provided text using gTTS with proper file handling."""
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            temp_path = temp_file.name
        
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(temp_path)
        
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            if os.path.exists(file_path):
                os.remove(file_path)
            shutil.move(temp_path, file_path)
            return True
                
        return False
                
    except Exception as e:
        print(f"Error generating audio: {str(e)}")
        return False

@app.route('/save_screen_recording', methods=['POST'])
def save_screen_recording():
    try:
        if 'screen_recording' not in request.files:
            app.logger.error('No screen recording file provided')
            return jsonify({'error': 'No screen recording file provided'}), 400
            
        screen_recording = request.files['screen_recording']
        trial_type = request.form.get('trial_type')
        participant_id = request.form.get('participant_id')
        
        app.logger.info(f'Received screen recording request - Participant: {participant_id}, Trial: {trial_type}')
        
        if not all([screen_recording, trial_type, participant_id]):
            app.logger.error('Missing required parameters')
            return jsonify({'error': 'Missing required parameters'}), 400
            
        folders = get_participant_folder(participant_id, trial_type)
        
        screen_recordings_dir = os.path.join(folders['trial_folder'], 'Screen Recordings')
        os.makedirs(screen_recordings_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'screen_recording_{timestamp}.webm'
        filepath = os.path.join(screen_recordings_dir, filename)
        
        app.logger.info(f'Saving screen recording to: {filepath}')
        
        screen_recording.save(filepath)
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            app.logger.info(f'Screen recording saved successfully: {filepath}')
            return jsonify({
                'status': 'success',
                'message': 'Screen recording saved successfully',
                'filepath': filepath
            })
        else:
            app.logger.error('Failed to save screen recording - file not created or empty')
            return jsonify({'error': 'Failed to save screen recording'}), 500
        
    except Exception as e:
        app.logger.error(f"Error saving screen recording: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/')
def home():
    """Render the home page."""
    session['interaction_id'] = get_interaction_id()
    session['trial_type'] = request.args.get('trial', 'Trial_1')        
    session['concept_attempts'] = {}

    initialize_log_file(session['interaction_id'], session['trial_type'])
    
    initialize_log_file(session['interaction_id'], None, session['trial_type'])
    
    return render_template('index.html')

@app.route('/resources/<path:filename>')
def download_resource(filename):
    """Serve resources like PDF or video files from the resources folder."""
    return send_from_directory('resources', filename)

@lru_cache
def load_concepts():
    """Load concepts from JSON file or create default concepts if file doesn't exist."""
    try:
        concepts_file = 'concepts.json'
        if os.path.exists(concepts_file):
            with open(concepts_file, 'r') as f:
                concepts = json.load(f)
                print(f"Loaded concepts: {list(concepts.keys())}")  # Debug print
                return concepts
        else:
            default_concepts = {
                "Correlation": {
                    "golden_answer": "Correlation describes the strength and direction of a relationship between two variables, ranging from -1 to 1. A value close to 1 indicates a strong positive relationship, while a value close to -1 indicates a strong negative one. Importantly, correlation does not imply causation. It only shows that two variables change together. A third variable may influence both, which is why identifying extraneous variables is essential."
                },
                "Confounders": {
                    "golden_answer": "Confounders are variables that influence both the independent and dependent variables, creating a spurious association. They can lead to incorrect conclusions about causality. Identifying and controlling for confounders is crucial in research to ensure accurate interpretation of relationships between variables."
                },
                "Moderators": {
                    "golden_answer": "Moderators are variables that affect the strength or direction of the relationship between two other variables. They can either strengthen, weaken, or reverse the relationship. Understanding moderators helps in identifying when and for whom a particular relationship holds true."
                }
            }
            with open(concepts_file, 'w') as f:
                json.dump(default_concepts, f, indent=4)
            print(f"Created default concepts: {list(default_concepts.keys())}")  # Debug print
            return default_concepts
    except Exception as e:
        print(f"Error loading concepts: {str(e)}")
        return {}
        
@app.route('/set_context', methods=['POST'])
def set_context():
    """Set the context for a specific concept from the provided material."""
    concept_name = request.form.get('concept_name')
    slide_number = request.form.get('slide_number', '0')
    logger.info(f"Setting context for concept: {concept_name}")
    concepts = load_concepts()
    
    selected_concept = next((c for c in concepts if c["name"] == concept_name), None)

    if not selected_concept:
        logger.error(f"Invalid concept selection: {concept_name}")
        return jsonify({'error': 'Invalid concept selection'})

    session['concept_name'] = selected_concept["name"]
    session['golden_answer'] = selected_concept["golden_answer"]
    
    if 'concept_attempts' not in session:
        session['concept_attempts'] = {}
    session['concept_attempts'][concept_name] = 0
    session.modified = True

    log_interaction("SYSTEM", selected_concept["name"], 
                    f"Context set for concept: {selected_concept['name']}")

    logger.info(f"Context set successfully for: {selected_concept['name']}")
    return jsonify({'message': f'Context set for {selected_concept["name"]}.'})

@app.route('/change_concept', methods=['POST'])
def change_concept():
    """Log when a user navigates to a different slide/concept."""
    data = request.get_json()
    slide_number = data.get('slide_number', 'unknown')
    concept_name = data.get('concept_name', 'unknown')
    
    if 'concept_attempts' not in session:
        session['concept_attempts'] = {}
    session['concept_attempts'][concept_name] = 0
    session.modified = True
    
    print(f"Concept changed to: {concept_name}")
    print(f"Reset attempt count for concept: {concept_name}")
    print("Current session state:", dict(session))

    message = f"User navigated to slide [{slide_number}] with the concept: [{concept_name}]"
    log_interaction("SYSTEM", concept_name, message)
    
    return jsonify({'status': 'success', 'message': 'Navigation and concept change logged'})

@app.route('/log_interaction_event', methods=['POST'])
def log_interaction_event():
    """Log user interaction events like chat window open/close, audio controls, etc."""
    data = request.get_json()
    event_type = data.get('event_type')
    event_details = data.get('details', {})
    concept_name = data.get('concept_name')
    
    message = f"User {event_type}"
    if event_type == "CHAT_WINDOW":
        message = f"User {event_details.get('action', 'unknown')} the chat window"
    elif event_type == "AUDIO_PLAYBACK":
        message = f"User {event_details.get('action', 'unknown')} audio playback at {event_details.get('timestamp', '0')} seconds"
    elif event_type == "AUDIO_SPEED":
        message = f"User changed audio speed to {event_details.get('speed', '1')}x"
    elif event_type == "RECORDING":
        action = event_details.get('action', 'unknown')
        timestamp = event_details.get('timestamp', '')
        if action == 'started':
            message = f"User started recording at {timestamp}"
        elif action == 'stopped':
            message = f"User stopped recording at {timestamp}"
        elif action == 'submitted':
            blob_size = event_details.get('blobSize', 'unknown')
            duration = event_details.get('duration', 'unknown')
            message = f"User submitted recording (size: {blob_size} bytes, duration: {duration}s) at {timestamp}"
        
    log_interaction("SYSTEM", concept_name, message)
    
    return jsonify({'status': 'success', 'message': 'Event logged successfully'})
    
@app.route('/get_intro_audio', methods=['GET'])
def get_intro_audio():
    """Generate the introductory audio message for the chatbot."""
    try:
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')
        
        if not participant_id or not trial_type:
            return jsonify({
                'status': 'error',
                'message': 'Participant ID or trial type not found in session'
            }), 400
            
        folders = get_participant_folder(participant_id, trial_type)
        intro_text = "Hello, let us begin the self-explanation journey! We'll be exploring the concept of Extraneous Variables, focusing on Correlation, Confounders, and Moderators. Please go through each concept and explain what you understand about them in your own words!"
        
        intro_audio_filename = f"intro_{participant_id}.mp3"
        intro_audio_path = os.path.join(folders['trial_folder'], intro_audio_filename)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if generate_audio(intro_text, intro_audio_path):
                    log_interaction("AI", "Introduction", intro_text)
                    
                    if os.path.exists(intro_audio_path) and os.path.getsize(intro_audio_path) > 0:
                        trial_folder_map = {
                            'Trial_1': 'main_task_1',
                            'Trial_2': 'main_task_2',
                            'Test': 'test_task'
                        }
                        trial_folder_name = trial_folder_map.get(trial_type, trial_type.lower())
                        intro_audio_url = f"/uploads/user_audio/{participant_id}/{trial_folder_name}/{intro_audio_filename}"
                        return jsonify({
                            'status': 'success',
                            'intro_audio_url': intro_audio_url,
                            'intro_text': intro_text
                        })
                    
                print(f"Attempt {attempt + 1} failed, retrying...")
                time.sleep(1)
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(1)
                
        return jsonify({
            'status': 'error',
            'message': 'Failed to generate introduction audio after multiple attempts'
        }), 500
        
    except Exception as e:
        print(f"Error in get_intro_audio: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
        
@app.route('/get_concept_audio/<concept_name>', methods=['GET'])
def get_concept_audio(concept_name):
    """Generate concept introduction audio message."""
    try:
        interaction_id = session.get('interaction_id', get_interaction_id())
        participant_id = session.get('participant_id')
        
        if not participant_id:
            return jsonify({
                'status': 'error',
                'message': 'Participant ID not found in session'
            }), 400
            
        folders = get_participant_folder(participant_id)
        safe_concept = secure_filename(concept_name)
        
        concept_audio_filename = get_audio_filename(f'concept_{safe_concept}', interaction_id)
        concept_audio_path = os.path.join(folders['ai_audio_folder'], concept_audio_filename)
        
        concept_intro_text = f"Now, let's explore the concept of {concept_name}. Please explain what you understand about this concept in your own words!"
        
        generate_audio(concept_intro_text, concept_audio_path)
        
        log_interaction("AI", concept_name, concept_intro_text)

        return send_from_directory(
            os.path.join(folders['ai_audio_folder']),
            concept_audio_filename,
            mimetype='audio/wav'
        )
    except Exception as e:
        print(f"Error in get_concept_audio: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/submit_message', methods=['POST'])
def submit_message():
    """Handle user message submission and generate AI response."""
    try:
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')
        
        if not participant_id or not trial_type:
            return jsonify({
                'status': 'error',
                'message': 'Participant ID or trial type not found in session'
            }), 400

        concept_name = request.form.get('concept_name', '').strip()
        print(f"Received concept from frontend: {concept_name}")  # Debug print

        concepts = load_concepts()
        print(f"Available concepts: {list(concepts.keys())}")  # Debug print
        
        concept_found = False
        for concept in concepts:
            if concept.lower() == concept_name.lower():
                concept_name = concept  
                concept_found = True
                print(f"Found matching concept: {concept}")  # Debug print
                break

        if not concept_found:
            print(f"Error: Concept '{concept_name}' not found in system!")
            return jsonify({
                'status': 'error',
                'message': 'Concept not found'
            }), 400

        golden_answer = concepts[concept_name]['golden_answer']
        
        concept_attempts = session.get('concept_attempts', {})
        attempt_count = concept_attempts.get(concept_name, 0)
        
        if 'audio' in request.files:
            audio_file = request.files['audio']
            if audio_file:
                audio_filename = get_audio_filename('user', participant_id, attempt_count + 1)
                folders = get_participant_folder(participant_id, trial_type)
                audio_path = os.path.join(folders['trial_folder'], audio_filename)
                audio_file.save(audio_path)
                
                try:
                    with open(audio_path, "rb") as audio_file:
                        user_transcript = openai.Audio.transcribe(
                            model="whisper-1",
                            file=audio_file
                        ).text
                except Exception as e:
                    print(f"OpenAI transcription failed, falling back to local model: {str(e)}")
                    user_transcript = speech_to_text(audio_path)
                
                if not user_transcript:
                    return jsonify({
                        'status': 'error',
                        'message': 'Failed to transcribe audio'
                    }), 400

        response = generate_response(user_transcript, concept_name, golden_answer, attempt_count)
        
        concept_attempts[concept_name] = attempt_count + 1
        session['concept_attempts'] = concept_attempts
        
        ai_audio_filename = get_audio_filename('ai', participant_id, attempt_count + 1)
        ai_audio_path = os.path.join(folders['trial_folder'], ai_audio_filename)
        
        if generate_audio(response, ai_audio_path):
            log_interaction("User", concept_name, user_transcript)
            log_interaction("AI", concept_name, response)
            
            return jsonify({
                'status': 'success',
                'response': response,
                'user_transcript': user_transcript,
                'ai_audio_url': ai_audio_filename,
                'attempt_count': attempt_count + 1,
                'should_move_to_next': attempt_count >= 2 
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to generate AI audio response'
            }), 500
            
    except Exception as e:
        print(f"Error in submit_message: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

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
        user_prompt += "\nIf the explanation is correct, communicate this to the user. If it is not correct, provide general feedback and a broad hint to guide the user."
    elif attempt_count == 1:
        user_prompt += "\nIf the explanation is correct, communicate this to the user. If it is not correct, provide more specific feedback and highlight key elements the user missed."
    elif attempt_count == 2:
        user_prompt += "\nIf the explanation is correct, communicate this to the user. If it is not correct, provide the correct explanation, as the user has made multiple attempts."
    else:
        user_prompt += "\nLet the user know they have completed three self-explanation attempts. Instruct them to stop here and tell them to continue with the next concept."

    history = [
        {"role": "system", "content": base_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "developer", "content": base_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=200,
            temperature=0.7,
        )

        ai_response = response.choices[0].message.content

        history.append({"role": "assistant", "content": ai_response})
        
        if 'conversation_history' not in session:
            session['conversation_history'] = []
        session['conversation_history'].append(history)
        session.modified = True

        return ai_response
    except Exception as e:
        return f"Error generating AI response: {str(e)}"

@app.route('/pdf')
def serve_pdf():
    """Serve the PDF file for the current concept."""
    return send_from_directory('resources', 'Extraneous Variables.pdf')

@app.route('/uploads/<folder_type>/<participant_id>/<trial_type>/<filename>')
def serve_audio(folder_type, participant_id, trial_type, filename):
    """Serve the audio files from the participant's folder."""
    try:
        if folder_type == 'concept_audio':
            base_path = CONCEPT_AUDIO_FOLDER
        else:
            trial_folder_map = {
                'trial_1': 'main_task_1',
                'trial_2': 'main_task_2',
                'test': 'test_task'
            }
            trial_folder_name = trial_folder_map.get(trial_type.lower(), trial_type.lower())
            base_path = os.path.join(USER_AUDIO_FOLDER, participant_id, trial_folder_name)
            
        if not os.path.exists(os.path.join(base_path, filename)):
            print(f"File not found: {os.path.join(base_path, filename)}")
            return jsonify({'error': 'Audio file not found'}), 404
            
        return send_from_directory(
            base_path,
            filename,
            mimetype='audio/mpeg'
        )
    except Exception as e:
        print(f"Error serving audio: {str(e)}")
        return jsonify({'error': 'Error serving audio file'}), 500

@app.route('/set_trial_type', methods=['POST'])
def set_trial_type():
    """Set the trial type and participant ID for the session."""
    try:
        data = request.get_json()
        trial_type = data.get('trial_type')
        participant_id = data.get('participant_id')        

        if not trial_type or not participant_id:
            return jsonify({
                'status': 'error',
                'message': 'Missing trial type or participant ID'
            }), 400

        valid_types = ["Trial_1", "Trial_2", "Test"]
        if trial_type not in valid_types:
            print(f"Invalid trial type: {trial_type}")  # Debug print
            return jsonify({
                "error": "Invalid trial type",
                "received_data": data
            }), 400
        old_trial_type = session.get('trial_type', 'None')

        interaction_id = get_interaction_id(participant_id)

        session['trial_type'] = trial_type
        session['participant_id'] = participant_id
        session['interaction_id'] = interaction_id
        session['concept_attempts'] = {}

        folders = get_participant_folder(participant_id, trial_type)
        
        log_file_path = os.path.join(folders['trial_folder'], f"conversation_log_{participant_id}.txt")
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(f"Session started for participant {participant_id} with trial type {trial_type}\n")

        return jsonify({
            'status': 'success',
            'message': f'Trial type set to {trial_type}'
        })

        initialize_log_file(interaction_id, participant_id, trial_type)

        log_interaction("SYSTEM", None, f"Trial type changed from {old_trial_type} to {trial_type} for participant {participant_id}")

        print(f"Successfully set trial type for participant {participant_id}")  # Debug print

        return jsonify({
            'status': 'success',
            'trial_type': trial_type,
            'interaction_id': interaction_id
        })
    except Exception as e:
        print(f"Error in set_trial_type: {str(e)}")  # Debug print
        return jsonify({
            "error": f"Server error: {str(e)}",
            "type": "server_error"
        }), 500

def cleanup_recordings():
    """Cleanup function called when server shuts down."""
    try:
        app.logger.info("Cleaning up recordings...")
        
        for participant_id in os.listdir(USER_AUDIO_FOLDER):
            participant_dir = os.path.join(USER_AUDIO_FOLDER, participant_id)
            if os.path.isdir(participant_dir):
                for trial_type in os.listdir(participant_dir):
                    trial_dir = os.path.join(participant_dir, trial_type)
                    if os.path.isdir(trial_dir):
                        screen_recordings_dir = os.path.join(trial_dir, 'Screen Recordings')
                        if os.path.exists(screen_recordings_dir):
                            for filename in os.listdir(screen_recordings_dir):
                                if filename.endswith('.webm'):
                                    filepath = os.path.join(screen_recordings_dir, filename)
                                    if os.path.getsize(filepath) > 0:
                                        app.logger.info(f"Verified recording: {filepath}")
                                    else:
                                        app.logger.warning(f"Removing incomplete recording: {filepath}")
                                        os.remove(filepath)
        
        app.logger.info("Cleanup completed successfully")
    except Exception as e:
        app.logger.error(f"Error during cleanup: {str(e)}")

atexit.register(cleanup_recordings)

def handle_sigterm(signum, frame):
    cleanup_recordings()
    exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

@app.route('/shutdown', methods=['PsOST'])
def shutdown():
    """Handle graceful server shutdown."""
    try:
        cleanup_recordings()
        return jsonify({'status': 'success', 'message': 'Server shutting down'})
    except Exception as e:
        app.logger.error(f"Error during shutdown: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    startup_interaction_id = get_interaction_id()
    # app.run(port=5000)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)






























