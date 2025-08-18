from flask import Flask, request, render_template, jsonify, session, send_from_directory
from werkzeug.utils import secure_filename
from flask_cors import CORS 
import openai
import os
import re
from gtts import gTTS
import whisper  
import json
import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)
try:
    from pydub import AudioSegment
except ImportError as e:
    import warnings
    warnings.filterwarnings("ignore")
    
    class MockAudioSegment:
        @classmethod
        def empty(cls):
            return cls()
        
        @classmethod
        def from_mp3(cls, file):
            return cls()
        
        @classmethod
        def from_file(cls, file):
            return cls()
        
        def __add__(self, other):
            return self
    
    AudioSegment = MockAudioSegment
    print("Warning: Using mock AudioSegment due to audioop compatibility issues")

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
from dotenv import load_dotenv
from database import db, Participant, Session, Interaction, Recording, UserEvent
import uuid

# Import cloud storage functionality (optional - won't break if module is missing)
try:
    from cloud_storage import upload_user_data_to_cloud
    CLOUD_STORAGE_AVAILABLE = True
    print("Cloud storage module loaded successfully")
except ImportError as e:
    CLOUD_STORAGE_AVAILABLE = False
    print(f"Cloud storage module not available: {str(e)}")
    def upload_user_data_to_cloud(*args, **kwargs):
        print("Cloud storage not available - skipping upload")
        pass

load_dotenv()

app = Flask(__name__)
CORS(app)  

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key')

db.init_app(app)

with app.app_context():
    db.create_all()


def save_interaction_to_db(session_id, speaker, concept_name, message, attempt_number=1):
    """Save interaction to database."""
    try:
        interaction = Interaction(
            session_id=session_id,
            speaker=speaker,
            concept_name=concept_name,
            message=message,
            attempt_number=attempt_number
        )
        db.session.add(interaction)
        db.session.commit()
    except Exception as e:
        print(f"Error saving interaction: {str(e)}")
        db.session.rollback()

def save_recording_to_db(session_id, recording_type, file_path, original_filename, 
                        file_size, concept_name=None, attempt_number=None):
    """Save recording metadata to database."""
    try:
        recording = Recording(
            session_id=session_id,
            recording_type=recording_type,
            file_path=file_path,
            original_filename=original_filename,
            file_size=file_size,
            concept_name=concept_name,
            attempt_number=attempt_number
        )
        db.session.add(recording)
        db.session.commit()
        return recording.id
    except Exception as e:
        print(f"Error saving recording: {str(e)}")
        db.session.rollback()
        return None

def create_session_record(participant_id, trial_type, version):
    """Create a new session record."""
    try:
        participant = Participant.query.filter_by(participant_id=participant_id).first()
        if not participant:
            participant = Participant(participant_id=participant_id)
            db.session.add(participant)
        
        session_id = f"{participant_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        session_record = Session(
            session_id=session_id,
            participant_id=participant_id,
            trial_type=trial_type,
            version=version
        )
        db.session.add(session_record)
        db.session.commit()
        return session_id
    except Exception as e:
        print(f"Error creating session: {str(e)}")
        db.session.rollback()
        return None

def save_audio_with_cloud_backup(audio_data, filename, session_id, recording_type, concept_name=None, attempt_number=None):
    """Save audio locally."""
    try:
        local_path = os.path.join('uploads/', filename)
        
        if hasattr(audio_data, 'save'):
            audio_data.save(local_path)
        else:
            with open(local_path, 'wb') as f:
                f.write(audio_data)
        
        return local_path, None
    except Exception as e:
        print(f"Error in save_audio_with_cloud_backup: {str(e)}")
        return None, None

def log_interaction_to_db_only(speaker, concept_name, message, attempt_number=1):
    """Log interaction to database only - separate from file logging."""
    try:
        session_id = session.get('session_id')
        if session_id:
            save_interaction_to_db(session_id, speaker, concept_name, message, attempt_number)
    except Exception as e:
        print(f"Error logging interaction to database: {str(e)}")

def initialize_session_in_db():
    """Initialize session in database when user starts - call this in set_trial_type."""
    try:
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')
        
        if participant_id and trial_type:
            session_id = create_session_record(participant_id, trial_type, "V1")
            if session_id:
                session['session_id'] = session_id
                return session_id
    except Exception as e:
        print(f"Error initializing session in database: {str(e)}")
    return None



OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

executor = ThreadPoolExecutor(max_workers=5)

UPLOAD_FOLDER = 'uploads/'
CONCEPT_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'concept_audio')
USER_AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, 'User Data')
STATIC_FOLDER = 'static'
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'webm'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CONCEPT_AUDIO_FOLDER'] = CONCEPT_AUDIO_FOLDER
app.config['USER_AUDIO_FOLDER'] = USER_AUDIO_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONCEPT_AUDIO_FOLDER, exist_ok=True)
os.makedirs(USER_AUDIO_FOLDER, exist_ok=True)

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_participant_folder(participant_id, trial_type):
    """Get or create the participant's folder structure."""
    participant_folder = os.path.join(USER_AUDIO_FOLDER, str(participant_id))
    screen_recordings_folder = os.path.join(participant_folder, 'Screen Recordings')

    os.makedirs(participant_folder, exist_ok=True)
    os.makedirs(screen_recordings_folder, exist_ok=True)

    return {
        'participant_folder': participant_folder,
        'screen_recordings_folder': screen_recordings_folder
    }

def check_paths():
    """Verify all required paths exist and are writable."""
    paths = [
        app.config['UPLOAD_FOLDER'],
        app.config['USER_AUDIO_FOLDER'],
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

model = None

whisper_model = None
whisper_loading = False

def get_whisper_model():
    global whisper_model, whisper_loading
    if whisper_model is None and not whisper_loading:
        try:
            whisper_loading = True
            print("Loading Whisper model...")
            whisper_model = whisper.load_model("small")
            print("Whisper model loaded successfully")
        except Exception as e:
            print(f"Failed to load Whisper model: {str(e)}")
            whisper_model = None
        finally:
            whisper_loading = False
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

def speech_to_text(audio_file_path):
    """Convert audio to text using OpenAI Whisper API or local fallback."""
    try:
        with open(audio_file_path, "rb") as audio_file:
            transcript = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file
            )
        return transcript["text"]
    except Exception as e:
        print(f"Error using OpenAI Whisper API: {str(e)}")
        print("Falling back to local Whisper model...")
        
        try:
            model = get_whisper_model()
            if model:
                result = model.transcribe(audio_file_path)
                return result["text"]
            else:
                return "Whisper model not available"
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
    log_file_path = os.path.join(folders['participant_folder'], log_filename)

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
            print(f"Skipping file logging - session not fully initialized (participant_id: {participant_id}, trial_type: {trial_type})")
            return True  
            
        folders = get_participant_folder(participant_id, trial_type)
        log_file_path = os.path.join(folders['participant_folder'], f"conversation_log_{participant_id}.txt")
        
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
        app.logger.info(f"Received screen recording request. Files: {list(request.files.keys())}")
        app.logger.info(f"Form data: {list(request.form.keys())}")

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
        
        screen_recordings_dir = folders['screen_recordings_folder']
        os.makedirs(screen_recordings_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'screen_recording_{timestamp}.webm'
        filepath = os.path.join(screen_recordings_dir, filename)
        
        app.logger.info(f'Saving screen recording to: {filepath}')
        
        screen_recording.save(filepath)
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            app.logger.info(f'Screen recording saved successfully: {filepath}')
            return 'OK', 200
        else:
            app.logger.error('Failed to save screen recording - file not created or empty')
            return jsonify({'error': 'Failed to save screen recording'}), 500
        
    except Exception as e:
        app.logger.error(f"Error saving screen recording: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for deployment platforms."""
    return jsonify({'status': 'healthy', 'service': 'HAI V1'}), 200

@app.route('/')
def home():
    """Render the home page."""
    session['interaction_id'] = get_interaction_id()
    session['trial_type'] = request.args.get('trial', 'Trial_1')        
    session['concept_attempts'] = {}
    
    return render_template('index.html')

@app.route('/resources/<path:filename>')
def download_resource(filename):
    """Serve resources like PDF or video files from the resources folder."""
    try:
        return send_from_directory('resources', filename)
    except FileNotFoundError:
        return jsonify({'error': f'Resource file {filename} not found'}), 404
    except Exception as e:
        print(f"Error serving resource {filename}: {str(e)}")
        return jsonify({'error': f'Error serving resource file {filename}'}), 500

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
        intro_audio_path = os.path.join(folders['participant_folder'], intro_audio_filename)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if generate_audio(intro_text, intro_audio_path):
                    log_interaction("AI", "Introduction", intro_text)
                    
                    if os.path.exists(intro_audio_path) and os.path.getsize(intro_audio_path) > 0:
                        intro_audio_url = f"/uploads/User Data/{participant_id}/{intro_audio_filename}"
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
        trial_type = session.get('trial_type')
        
        if not participant_id:
            return jsonify({
                'status': 'error',
                'message': 'Participant ID not found in session'
            }), 400
            
        folders = get_participant_folder(participant_id, trial_type)
        safe_concept = secure_filename(concept_name)
        
        concept_audio_filename = get_audio_filename(f'concept_{safe_concept}', interaction_id)
        concept_audio_path = os.path.join(folders['participant_folder'], concept_audio_filename)
        
        concept_intro_text = f"Now, let's explore the concept of {concept_name}. Please explain what you understand about this concept in your own words!"
        
        generate_audio(concept_intro_text, concept_audio_path)
        
        log_interaction("AI", concept_name, concept_intro_text)

        return send_from_directory(
            folders['participant_folder'],  
            concept_audio_filename,
            mimetype='audio/mpeg'
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
                audio_path = os.path.join(folders['participant_folder'], audio_filename)
                audio_file.save(audio_path)
                
                try:
                    with open(audio_path, "rb") as audio_file:
                        user_transcript = openai.Audio.transcribe(
                            model="whisper-1",
                            file=audio_file
                        )["text"]
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
        ai_audio_path = os.path.join(folders['participant_folder'], ai_audio_filename)
        
        if generate_audio(response, ai_audio_path):
            log_interaction("User", concept_name, user_transcript)
            log_interaction("AI", concept_name, response)
            
            log_interaction_to_db_only("USER", concept_name, user_transcript, attempt_count + 1)
            log_interaction_to_db_only("AI", concept_name, response, attempt_count + 1)
                
            session_id = session.get('session_id')
            if session_id:
                with open(audio_path, 'rb') as f:
                    audio_data = f.read()
                save_audio_with_cloud_backup(
                    audio_data, audio_filename, session_id, 
                    'user_audio', concept_name, attempt_count + 1
                )
                    
                with open(ai_audio_path, 'rb') as f:
                    ai_audio_data = f.read()
                save_audio_with_cloud_backup(
                    ai_audio_data, ai_audio_filename, session_id, 
                    'ai_audio', concept_name, attempt_count + 1
                )

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
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": base_prompt},
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
    try:
        return send_from_directory('resources', 'Extraneous Variables.pdf')
    except FileNotFoundError:
        return jsonify({'error': 'PDF file not found'}), 404
    except Exception as e:
        print(f"Error serving PDF: {str(e)}")
        return jsonify({'error': 'Error serving PDF file'}), 500

@app.route('/uploads/User Data/<participant_id>/<filename>')
def serve_audio_new(participant_id, filename):
    """Serve the audio files from the participant's folder (new structure without trial subfolder)."""
    try:
        base_path = os.path.join(USER_AUDIO_FOLDER, participant_id)
        
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

@app.route('/uploads/<folder_type>/<participant_id>/<trial_type>/<filename>')
def serve_audio(folder_type, participant_id, trial_type, filename):
    """Serve the audio files from the participant's folder (legacy route for backward compatibility)."""
    try:
        if folder_type == 'concept_audio':
            base_path = CONCEPT_AUDIO_FOLDER
        else:
            base_path = os.path.join(USER_AUDIO_FOLDER, participant_id)
            
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
            print(f"Invalid trial type: {trial_type}")
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

        db_session_id = initialize_session_in_db()

        initialize_log_file(interaction_id, participant_id, trial_type)

        log_interaction("SYSTEM", None, f"Trial type changed from {old_trial_type} to {trial_type} for participant {participant_id}")
        log_interaction_to_db_only("SYSTEM", "Session", f"Trial type set to {trial_type} for participant {participant_id}")

        print(f"Successfully set trial type for participant {participant_id}")

        return jsonify({
            'status': 'success',
            'trial_type': trial_type,
            'interaction_id': interaction_id,
            'session_id': db_session_id  
        })
    except Exception as e:
        print(f"Error in set_trial_type: {str(e)}")
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
                screen_recordings_dir = os.path.join(participant_dir, 'Screen Recordings')
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

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/backup_to_cloud', methods=['POST'])
def backup_to_cloud():
    """Manual backup endpoint - no longer functional but kept for compatibility."""
    try:
        return jsonify({'status': 'info', 'message': 'Cloud backup functionality has been removed. Use /export_complete_data to download User Data.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================== DATA EXPORT FUNCTIONALITY ===========================

@app.route('/data_dashboard')
def data_dashboard():
    """Display a simple dashboard for data export and management."""
    try:
        total_participants = Participant.query.count()
        total_sessions = Session.query.count()
        total_interactions = Interaction.query.count()
        total_recordings = Recording.query.count()
        
        recent_sessions = Session.query.order_by(Session.started_at.desc()).limit(10).all()
        
        stats = {
            'total_participants': total_participants,
            'total_sessions': total_sessions,
            'total_interactions': total_interactions,
            'total_recordings': total_recordings,
            'recent_sessions': [
                {
                    'session_id': s.session_id,
                    'participant_id': s.participant_id,
                    'trial_type': s.trial_type,
                    'version': s.version,
                    'started_at': s.started_at.strftime('%Y-%m-%d %H:%M:%S') if s.started_at else 'N/A'
                } for s in recent_sessions
            ]
        }
        
        return jsonify({
            'status': 'success',
            'message': 'HAI V1 Data Dashboard',
            'stats': stats
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/export_research_data')
def export_research_data():
    """Export comprehensive research data including all interactions and analysis."""
    try:
        import zipfile
        import csv
        from io import StringIO, BytesIO
        
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            
            # 1. Detailed Participants Data
            participants = Participant.query.all()
            if participants:
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(['Participant_ID', 'Created_At', 'Total_Sessions', 'Total_Interactions', 'Trial_Types', 'Versions_Used'])
                
                for p in participants:
                    sessions = Session.query.filter_by(participant_id=p.participant_id).all()
                    sessions_count = len(sessions)
                    trial_types = list(set([s.trial_type for s in sessions if s.trial_type]))
                    versions = list(set([s.version for s in sessions if s.version]))
                    
                    total_interactions = 0
                    for s in sessions:
                        interactions_count = Interaction.query.filter_by(session_id=s.session_id).count()
                        total_interactions += interactions_count
                    
                    writer.writerow([
                        p.participant_id, 
                        p.created_at, 
                        sessions_count, 
                        total_interactions,
                        '; '.join(trial_types),
                        '; '.join(versions)
                    ])
                
                zip_file.writestr('01_Participants_Summary.csv', csv_buffer.getvalue())
            
            # 2. Detailed Sessions Data
            sessions = Session.query.order_by(Session.started_at.desc()).all()
            if sessions:
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(['Session_ID', 'Participant_ID', 'Trial_Type', 'Version', 'Started_At', 'Ended_At', 'Duration_Minutes', 'Total_Interactions'])
                
                for s in sessions:
                    interactions_count = Interaction.query.filter_by(session_id=s.session_id).count()
                    duration = None
                    if s.started_at and s.ended_at:
                        duration = (s.ended_at - s.started_at).total_seconds() / 60
                    
                    writer.writerow([
                        s.session_id,
                        s.participant_id,
                        s.trial_type,
                        s.version,
                        s.started_at,
                        s.ended_at,
                        round(duration, 2) if duration else '',
                        interactions_count
                    ])
                
                zip_file.writestr('02_Sessions_Detail.csv', csv_buffer.getvalue())
            
            # 3. All Interactions with Full Text
            interactions = Interaction.query.order_by(Interaction.timestamp.desc()).all()
            if interactions:
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(['Session_ID', 'Participant_ID', 'Timestamp', 'Speaker', 'Concept_Name', 'Message_Text', 'Attempt_Number', 'Character_Count', 'Word_Count'])
                
                for i in interactions:
                    session = Session.query.filter_by(session_id=i.session_id).first()
                    participant_id = session.participant_id if session else 'Unknown'
                    
                    char_count = len(i.message) if i.message else 0
                    word_count = len(i.message.split()) if i.message else 0
                    
                    writer.writerow([
                        i.session_id,
                        participant_id,
                        i.timestamp,
                        i.speaker,
                        i.concept_name,
                        i.message,
                        i.attempt_number,
                        char_count,
                        word_count
                    ])
                
                zip_file.writestr('03_All_Interactions.csv', csv_buffer.getvalue())
            
            # 4. User Explanations Only (Research Gold)
            user_interactions = Interaction.query.filter_by(speaker='USER').order_by(Interaction.timestamp.desc()).all()
            if user_interactions:
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(['Participant_ID', 'Session_ID', 'Timestamp', 'Concept_Name', 'User_Explanation', 'Attempt_Number', 'Word_Count'])
                
                for i in user_interactions:
                    session = Session.query.filter_by(session_id=i.session_id).first()
                    participant_id = session.participant_id if session else 'Unknown'
                    word_count = len(i.message.split()) if i.message else 0
                    
                    writer.writerow([
                        participant_id,
                        i.session_id,
                        i.timestamp,
                        i.concept_name,
                        i.message,
                        i.attempt_number,
                        word_count
                    ])
                
                zip_file.writestr('04_User_Explanations_RESEARCH_DATA.csv', csv_buffer.getvalue())
            
            # 5. Concept-wise Analysis
            concepts = ['Correlation', 'Confounders', 'Moderators']
            for concept in concepts:
                concept_interactions = Interaction.query.filter_by(concept_name=concept, speaker='USER').all()
                if concept_interactions:
                    csv_buffer = StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerow(['Participant_ID', 'Session_ID', 'Timestamp', 'User_Explanation', 'Attempt_Number', 'Word_Count'])
                    
                    for i in concept_interactions:
                        session = Session.query.filter_by(session_id=i.session_id).first()
                        participant_id = session.participant_id if session else 'Unknown'
                        word_count = len(i.message.split()) if i.message else 0
                        
                        writer.writerow([
                            participant_id,
                            i.session_id,
                            i.timestamp,
                            i.message,
                            i.attempt_number,
                            word_count
                        ])
                    
                    zip_file.writestr(f'05_Concept_{concept}_Explanations.csv', csv_buffer.getvalue())
        
            # 6. Summary Statistics
            csv_buffer = StringIO()
            writer = csv.writer(csv_buffer)
            writer.writerow(['Metric', 'Value'])
            
            total_participants = Participant.query.count()
            total_sessions = Session.query.count()
            total_interactions = Interaction.query.count()
            user_interactions_count = Interaction.query.filter_by(speaker='USER').count()
            ai_interactions_count = Interaction.query.filter_by(speaker='AI').count()
            
            avg_interactions_per_session = total_interactions / total_sessions if total_sessions > 0 else 0
            avg_sessions_per_participant = total_sessions / total_participants if total_participants > 0 else 0
            
            writer.writerow(['Total Participants', total_participants])
            writer.writerow(['Total Sessions', total_sessions])
            writer.writerow(['Total Interactions', total_interactions])
            writer.writerow(['User Explanations', user_interactions_count])
            writer.writerow(['AI Responses', ai_interactions_count])
            writer.writerow(['Avg Interactions per Session', round(avg_interactions_per_session, 2)])
            writer.writerow(['Avg Sessions per Participant', round(avg_sessions_per_participant, 2)])
            
            zip_file.writestr('00_Research_Summary_Statistics.csv', csv_buffer.getvalue())
        
        zip_buffer.seek(0)
        
        from flask import Response
        return Response(
            zip_buffer.getvalue(),
            mimetype='application/zip',
            headers={'Content-Disposition': f'attachment; filename=HAI_V1_Research_Data_Complete_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'}
        )
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/export_complete_data')
def export_complete_data():
    """Export available user data - files if they exist, otherwise comprehensive database export."""
    try:
        import zipfile
        import csv
        from io import StringIO, BytesIO
        
        zip_buffer = BytesIO()
        files_found = False
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            
            user_data_path = app.config['USER_AUDIO_FOLDER']
            if os.path.exists(user_data_path):
                print(f"Checking for User Data files in: {user_data_path}")
                
                for participant_id in os.listdir(user_data_path):
                    participant_path = os.path.join(user_data_path, participant_id)
                    
                    if os.path.isdir(participant_path):
                        participant_files = []
                        for root, dirs, files in os.walk(participant_path):
                            participant_files.extend(files)
                        
                        if participant_files:  
                            files_found = True
                            print(f"Found {len(participant_files)} files for participant: {participant_id}")
                            
                            for root, dirs, files in os.walk(participant_path):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    rel_path = os.path.relpath(file_path, user_data_path)
                                    archive_path = f"User_Data/{rel_path}"
                                    
                                    try:
                                        zip_file.write(file_path, archive_path)
                                        print(f"Added: {archive_path}")
                                    except Exception as e:
                                        print(f"Could not add file {file_path}: {str(e)}")
            
            if not files_found:
                print("No user files found - creating database export instead")
                
                interactions = Interaction.query.join(Session).order_by(Session.started_at.desc(), Interaction.created_at.asc()).all()
                if interactions:
                    csv_buffer = StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerow([
                        'Session_ID', 'Participant_ID', 'Trial_Type', 'Version', 
                        'Speaker', 'Concept_Name', 'Message', 'Attempt_Number', 
                        'Interaction_Time', 'Session_Started'
                    ])
                    
                    for interaction in interactions:
                        session = Session.query.filter_by(session_id=interaction.session_id).first()
                        writer.writerow([
                            interaction.session_id,
                            session.participant_id if session else 'Unknown',
                            session.trial_type if session else 'Unknown',
                            session.version if session else 'Unknown',
                            interaction.speaker,
                            interaction.concept_name,
                            interaction.message,
                            interaction.attempt_number,
                            interaction.created_at,
                            session.started_at if session else 'Unknown'
                        ])
                    
                    zip_file.writestr('All_Interactions_Data.csv', csv_buffer.getvalue())
                
                participants = Participant.query.all()
                if participants:
                    csv_buffer = StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerow(['Participant_ID', 'Total_Sessions', 'Total_Interactions', 'Created_At', 'Trial_Types'])
                    
                    for p in participants:
                        sessions = Session.query.filter_by(participant_id=p.participant_id).all()
                        sessions_count = len(sessions)
                        trial_types = list(set([s.trial_type for s in sessions if s.trial_type]))
                        
                        total_interactions = 0
                        for s in sessions:
                            interactions_count = Interaction.query.filter_by(session_id=s.session_id).count()
                            total_interactions += interactions_count
                        
                        writer.writerow([
                            p.participant_id, 
                            sessions_count, 
                            total_interactions, 
                            p.created_at,
                            '; '.join(trial_types)
                        ])
                    
                    zip_file.writestr('Participants_Summary.csv', csv_buffer.getvalue())
                
                readme_content = """HAI V1 Data Export - Database Only

IMPORTANT NOTICE:
================
This export contains database records only. Audio/video files are not available 
due to Render's ephemeral storage system.

WHAT'S INCLUDED:
===============
- All_Interactions_Data.csv: Complete conversation logs with timestamps
- Participants_Summary.csv: Participant statistics and trial information

MISSING DATA:
=============
- Audio recordings (user voice inputs)
- AI-generated audio responses
- Screen recordings
- Log files

For future data collection, consider implementing persistent storage 
(AWS S3, Google Cloud, etc.) to preserve audio/video files.

Export generated: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                zip_file.writestr('README.txt', readme_content)
            
            else:
                participants = Participant.query.all()
                if participants:
                    csv_buffer = StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerow(['Participant_ID', 'Total_Sessions', 'Total_Interactions', 'Created_At'])
                    
                    for p in participants:
                        sessions_count = Session.query.filter_by(participant_id=p.participant_id).count()
                        session_ids = [s.session_id for s in Session.query.filter_by(participant_id=p.participant_id).all()]
                        interactions_count = Interaction.query.filter(Interaction.session_id.in_(session_ids)).count() if session_ids else 0
                        
                        writer.writerow([p.participant_id, sessions_count, interactions_count, p.created_at])
                    
                    zip_file.writestr('Database_Summary.csv', csv_buffer.getvalue())
        
        zip_buffer.seek(0)
        
        if zip_buffer.getvalue():
            from flask import Response
            filename_prefix = "HAI_V1_Files_Export" if files_found else "HAI_V1_Database_Export"
            return Response(
                zip_buffer.getvalue(),
                mimetype='application/zip',
                headers={'Content-Disposition': f'attachment; filename={filename_prefix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'}
            )
        else:
            return jsonify({
                'status': 'error', 
                'message': 'No data available for export. Please ensure participants have completed interactions.'
            }), 404
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/export_latest_session')
def export_latest_session():
    """Export only the most recent session data for each participant."""
    try:
        import zipfile
        import csv
        from io import StringIO, BytesIO
        
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            
            latest_sessions = []
            participants = Participant.query.all()
            
            for participant in participants:
                latest_session = Session.query.filter_by(participant_id=participant.participant_id)\
                                                .order_by(Session.started_at.desc()).first()
                if latest_session:
                    latest_sessions.append(latest_session)
            
            if latest_sessions:
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow([
                    'Participant_ID', 'Session_ID', 'Trial_Type', 'Version',
                    'Speaker', 'Concept_Name', 'Message', 'Attempt_Number', 
                    'Interaction_Time', 'Session_Started'
                ])
                
                for session in latest_sessions:
                    interactions = Interaction.query.filter_by(session_id=session.session_id)\
                                                      .order_by(Interaction.created_at.asc()).all()
                    
                    for interaction in interactions:
                        writer.writerow([
                            session.participant_id,
                            interaction.session_id,
                            session.trial_type,
                            session.version,
                            interaction.speaker,
                            interaction.concept_name,
                            interaction.message,
                            interaction.attempt_number,
                            interaction.created_at,
                            session.started_at
                        ])
                
                zip_file.writestr('Latest_Session_Interactions.csv', csv_buffer.getvalue())
                
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(['Participant_ID', 'Session_ID', 'Trial_Type', 'Version', 'Started_At', 'Total_Interactions'])
                
                for session in latest_sessions:
                    interactions_count = Interaction.query.filter_by(session_id=session.session_id).count()
                    writer.writerow([
                        session.participant_id,
                        session.session_id,
                        session.trial_type,
                        session.version,
                        session.started_at,
                        interactions_count
                    ])
                
                zip_file.writestr('Latest_Sessions_Summary.csv', csv_buffer.getvalue())
        
        zip_buffer.seek(0)
        
        if zip_buffer.getvalue():
            from flask import Response
            return Response(
                zip_buffer.getvalue(),
                mimetype='application/zip',
                headers={'Content-Disposition': f'attachment; filename=HAI_V1_Latest_Sessions_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'}
            )
        else:
            return jsonify({
                'status': 'error', 
                'message': 'No recent session data available for export.'
            }), 404
            
    except Exception as e:
        print(f"Latest session export error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/browse_files')
def browse_files():
    """Browse local files in User Data folder."""
    try:
        user_data_path = app.config['USER_AUDIO_FOLDER']
        file_structure = {}
        
        if os.path.exists(user_data_path):
            for root, dirs, files in os.walk(user_data_path):
                rel_path = os.path.relpath(root, user_data_path)
                if rel_path == '.':
                    rel_path = 'root'
                
                file_structure[rel_path] = {
                    'directories': dirs,
                    'files': [
                        {
                            'name': f,
                            'size': os.path.getsize(os.path.join(root, f)),
                            'modified': datetime.fromtimestamp(os.path.getmtime(os.path.join(root, f))).strftime('%Y-%m-%d %H:%M:%S')
                        } for f in files
                    ]
                }
        
        return jsonify({
            'status': 'success',
            'file_structure': file_structure,
            'base_path': user_data_path
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================== END DATA EXPORT FUNCTIONALITY ===========================

@app.route('/diagnostic_filesystem')
def diagnostic_filesystem():
    """Diagnostic route to check file system status on Render."""
    try:
        diagnostic_info = {
            'current_working_directory': os.getcwd(),
            'upload_folder_exists': os.path.exists(UPLOAD_FOLDER),
            'user_data_folder_exists': os.path.exists(USER_AUDIO_FOLDER),
            'user_data_folder_path': USER_AUDIO_FOLDER,
            'folder_contents': {},
            'disk_info': {},
            'environment_vars': {
                'PORT': os.environ.get('PORT', 'Not set'),
                'RENDER': os.environ.get('RENDER', 'Not set'),
                'DATABASE_URL': 'Set' if os.environ.get('DATABASE_URL') else 'Not set'
            }
        }
        
        if os.path.exists(UPLOAD_FOLDER):
            diagnostic_info['folder_contents']['uploads'] = os.listdir(UPLOAD_FOLDER)
            
        if os.path.exists(USER_AUDIO_FOLDER):
            user_data_contents = []
            for root, dirs, files in os.walk(USER_AUDIO_FOLDER):
                rel_path = os.path.relpath(root, USER_AUDIO_FOLDER)
                user_data_contents.append({
                    'path': rel_path,
                    'directories': dirs,
                    'files': files,
                    'file_count': len(files)
                })
            diagnostic_info['folder_contents']['user_data'] = user_data_contents
        
        try:
            import shutil
            total, used, free = shutil.disk_usage('/')
            diagnostic_info['disk_info'] = {
                'total_gb': round(total / (1024**3), 2),
                'used_gb': round(used / (1024**3), 2),
                'free_gb': round(free / (1024**3), 2)
            }
        except:
            diagnostic_info['disk_info'] = 'Unable to get disk info'
            
        total_recordings = Recording.query.count()
        recordings_with_files = Recording.query.filter(Recording.file_path.isnot(None)).count()
        
        diagnostic_info['database_info'] = {
            'total_recordings_in_db': total_recordings,
            'recordings_with_file_paths': recordings_with_files,
            'sample_recording_paths': [r.file_path for r in Recording.query.limit(5).all() if r.file_path]
        }
        
        return jsonify({
            'status': 'success',
            'diagnostic': diagnostic_info
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'error_type': type(e).__name__
        }), 500

# =========================== CLOUD STORAGE ENDPOINTS ===========================

@app.route('/trigger_cloud_upload', methods=['POST'])
def trigger_cloud_upload():
    """Manually trigger cloud upload for current participant."""
    try:
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')
        
        if not participant_id or not trial_type:
            return jsonify({
                'status': 'error',
                'message': 'No active participant session found'
            }), 400
        
        if CLOUD_STORAGE_AVAILABLE:
            # Trigger immediate upload (with minimal delay)
            upload_user_data_to_cloud(participant_id, trial_type, USER_AUDIO_FOLDER, version="V1", delay_seconds=2)
            
            return jsonify({
                'status': 'success',
                'message': f'Cloud upload initiated for participant {participant_id}'
            })
        else:
            return jsonify({
                'status': 'info',
                'message': 'Cloud storage not configured'
            })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/on_page_unload', methods=['POST'])
def on_page_unload():
    """Handle page unload event - trigger cloud upload."""
    try:
        data = request.get_json() or {}
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')
        
        if participant_id and trial_type:
            print(f"Page unload detected for participant {participant_id}")
            
            # Log the page unload event
            try:
                log_interaction("SYSTEM", "Page_Unload", f"User closed/left page - triggering cloud backup")
                log_interaction_to_db_only("SYSTEM", "Page_Unload", f"Page unload event for participant {participant_id}")
            except Exception as log_error:
                print(f"Error logging page unload: {str(log_error)}")
            
            # Trigger cloud upload with slight delay to ensure all files are saved
            if CLOUD_STORAGE_AVAILABLE:
                upload_user_data_to_cloud(participant_id, trial_type, USER_AUDIO_FOLDER, version="V1", delay_seconds=3)
            
            return jsonify({
                'status': 'success',
                'message': 'Page unload processed, cloud backup initiated' if CLOUD_STORAGE_AVAILABLE else 'Page unload processed (cloud storage not available)'
            })
        else:
            return jsonify({
                'status': 'info',
                'message': 'No active session to backup'
            })
            
    except Exception as e:
        print(f"Error in page unload handler: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# =========================== END CLOUD STORAGE ENDPOINTS ===========================

if __name__ == '__main__':
    startup_interaction_id = get_interaction_id()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


