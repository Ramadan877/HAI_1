from flask import Flask, request, render_template, jsonify, session, send_from_directory, Response, stream_with_context
from werkzeug.utils import secure_filename
from flask_cors import CORS 
import openai
import requests
import os
import re
from difflib import SequenceMatcher
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

load_dotenv()
from supabase import create_client

# Supabase server/client configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_KEY')
supabase = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception as e:
        print("Warning: could not initialize Supabase client:", e)

app = Flask(__name__)
CORS(app)  

try:
    from flask_compress import Compress
    Compress(app)
except Exception:
    pass

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'sslmode': 'require'}
}
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key')

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB limit for long recordings

SUPABASE_DATABASE_URL = os.environ.get('SUPABASE_DATABASE_URL')
if SUPABASE_DATABASE_URL:
    app.config['SUPABASE_DATABASE_URL'] = SUPABASE_DATABASE_URL

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
        if not db or not os.environ.get('DATABASE_URL'):
            print('Database not configured, skipping recording save')
            return None

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
        # After saving locally to the render DB, enqueue background upload to Supabase (non-blocking)
        try:
            participant_id = None
            try:
                sess = Session.query.filter_by(session_id=session_id).first()
                participant_id = sess.participant_id if sess else None
            except Exception:
                participant_id = None

            if supabase:
                try:
                    executor.submit(
                        lambda p=file_path, s=session_id, pid=participant_id: upload_and_record_supabase(p, s, pid, version='V1')
                    )
                except Exception as e:
                    print('Failed to schedule supabase upload task:', e)
        except Exception:
            pass
        return recording.id
    except Exception as e:
        print(f"Error saving recording: {str(e)}")
        try:
            db.session.rollback()
        except:
            pass
        return None


def upload_file_to_supabase(local_path, bucket_name='V1', dest_path=None):
    """Upload a local file to Supabase storage and return public URL and size.
    This function is best-effort and will not raise to the caller if supabase is not configured.
    """
    if supabase is None:
        return None, None
    if not dest_path:
        dest_path = os.path.basename(local_path)

    try:
        with open(local_path, 'rb') as f:
            data = f.read()

        storage = supabase.storage.from_(bucket_name)
        storage.upload(dest_path, data)

        public_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{dest_path}"
        size = os.path.getsize(local_path)
        return public_url, size
    except Exception as e:
        print('Supabase upload_file_to_supabase error:', e)
        return None, None


def upload_and_record_supabase(local_path, session_id=None, participant_id=None, version='V1'):
    """High level: upload the local_path to Supabase storage bucket 'HAI' and insert a row into the
    `uploads` table. Function swallows errors to avoid affecting main app behavior.
    """
    try:
        if supabase is None:
            return None
        if not os.path.exists(local_path):
            return None

        # dest path namespaced by version/participant/session
        safe_rel = os.path.basename(local_path)
        participant_part = participant_id if participant_id else 'unknown'
        sess_part = session_id if session_id else 'no_session'
        dest_path = f"{version}/{participant_part}/{sess_part}/{safe_rel}"

        public_url, size = upload_file_to_supabase(local_path, bucket_name='V1', dest_path=dest_path)
        if public_url:
            try:
                supabase.table('uploads').insert({
                    'session_id': session_id,
                    'participant_id': participant_id,
                    'version': version,
                    'bucket': 'V1',
                    'path': dest_path,
                    'public_url': public_url,
                    'file_name': safe_rel,
                    'file_type': None,
                    'file_size': size,
                    'metadata': {'local_path': local_path}
                }).execute()
            except Exception as e:
                print('Supabase metadata insert failed:', e)
        return public_url
    except Exception as e:
        print('upload_and_record_supabase error:', e)
        return None

def create_session_record(participant_id, trial_type, version):
    """Create a new session record."""
    try:
        if not db or not os.environ.get('DATABASE_URL'):
            print('Database not configured, skipping session creation')
            return None

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
        try:
            db.session.rollback()
        except:
            pass
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
        clean_text = clean_tts_text(text)
        tts = gTTS(text=clean_text, lang='en', slow=False)
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


@app.route('/finalize_session', methods=['POST'])
def finalize_session():
    """Endpoint called from client on unload. Upload remaining files for the participant/session to Supabase.
    This is best-effort and non-blocking from the client perspective.
    """
    try:
        data = request.get_json(silent=True) or {}
        participant_id = data.get('participant_id') or session.get('participant_id')
        session_id = data.get('session_id') or session.get('session_id')
        version = data.get('version') or 'V1'

        if not participant_id:
            return jsonify({'status':'error','message':'missing participant_id'}), 400

        # find participant folder
        folders = get_participant_folder(participant_id, session.get('trial_type',''))
        participant_folder = folders['participant_folder']

        uploaded = []
        if os.path.exists(participant_folder):
            for root, _, files in os.walk(participant_folder):
                for fname in files:
                    if fname.startswith('.'):
                        continue
                    local_path = os.path.join(root, fname)
                    try:
                        if 'executor' in globals() and executor:
                            executor.submit(lambda p=local_path, s=session_id, pid=participant_id: upload_and_record_supabase(p, s, pid, version=version))
                        else:
                            import threading
                            threading.Thread(target=upload_and_record_supabase, args=(local_path, session_id, participant_id, version), daemon=True).start()
                        uploaded.append(local_path)
                    except Exception as e:
                        print('finalize_session scheduling failed for', local_path, e)

        return jsonify({'status':'ok','scheduled':len(uploaded)}), 200
    except Exception as e:
        print('finalize_session error:', e)
        return jsonify({'status':'error','message':str(e)}), 500
    
def get_audio_filename(prefix, participant_id, interaction_number, extension='.mp3'):
    """Generate a unique audio filename with participant ID, concept name, and interaction number."""
    import inspect
    frame = inspect.currentframe().f_back
    concept_name = frame.f_locals.get('concept_name', None)
    concept_part = f"_{secure_filename(concept_name)}" if concept_name else ""
    return f"{prefix}{concept_part}_{interaction_number}_{participant_id}{extension}"

def generate_audio(text, output_path):
    """
    Generate natural tutor speech:
    - Clean text for TTS
    - Apply prosody (SSML)
    - Use OpenAI TTS or fallback to gTTS
    """

    import openai
    from gtts import gTTS
    import os

    # 1. Clean text (remove markup, reduce pauses)
    cleaned = clean_tts_text(text)

    # 2. Add SSML prosody tuning
    ssml_text = apply_ssml_prosody(cleaned)

    try:
        # 3. OpenAI TTS with SSML
        response = openai.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=ssml_text,
            format="mp3"
        )
        audio_bytes = response.read()
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return

    except Exception as e:
        print("OpenAI TTS failed, falling back to gTTS:", e)

        try:
            # 4. Make gTTS more natural by slightly slowing it down
            tts = gTTS(cleaned, lang="en", slow=False)
            tts.save(output_path)

        except Exception as e2:
            print("gTTS also failed:", e2)
            raise e2

    

@app.route('/list_recent_recordings')
def list_recent_recordings():
    """Return latest N recordings from DB with file existence checks."""
    try:
        n = int(request.args.get('n', 20))
        recs = Recording.query.order_by(Recording.created_at.desc()).limit(n).all()
        out = []
        base = app.config.get('UPLOAD_FOLDER', 'uploads')
        for r in recs:
            fp = r.file_path or ''
            if fp and not os.path.isabs(fp):
                full = os.path.normpath(os.path.join(base, fp))
            else:
                full = fp
            exists = os.path.exists(full) if full else False
            size = os.path.getsize(full) if exists else None
            session_rec = Session.query.filter_by(session_id=r.session_id).first()
            participant_id = session_rec.participant_id if session_rec else None
            out.append({
                'id': r.id,
                'session_id': r.session_id,
                'participant_id': participant_id,
                'recording_type': r.recording_type,
                'file_path_db': r.file_path,
                'file_path_resolved': full,
                'exists': exists,
                'size': size,
                'created_at': r.created_at
            })
        return jsonify({'status': 'ok', 'recent_recordings': out})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for deployment platforms."""
    return jsonify({'status': 'healthy', 'service': 'HAI V1'}), 200


def synthesize_with_openai(text, voice='alloy', fmt='mp3'):
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OpenAI API key not configured')
    url = 'https://api.openai.com/v1/audio/speech'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    payload = {'model': 'gpt-4o-mini-tts', 'voice': voice, 'input': text}
    resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
    resp.raise_for_status()
    audio_bytes = resp.content
    content_type = 'audio/mpeg' if fmt.lower() in ('mp3','mpeg') else 'audio/webm'
    return audio_bytes, content_type


@app.route('/stream_submit_message_v1', methods=['POST'])
def stream_submit_message_v1():
    """Streaming version of the tutor response using the full V2 logic."""
    try:
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')

        if not participant_id or not trial_type:
            return "Session error: Missing participant or trial type.", 400

        concept_name = request.form.get('concept_name', '').strip()
        concepts = load_concepts()

        matched = next((c for c in concepts if c.lower() == concept_name.lower()), None)
        if not matched:
            return "Concept not found", 400

        concept_name = matched
        golden_answer = concepts[concept_name]['golden_answer']

        # Attempts + history
        concept_attempts = session.get('concept_attempts', {})
        attempt_count = concept_attempts.get(concept_name, 0)

        conv_store = session.get('conversation_history', {})
        conversation_history = conv_store.get(concept_name, [])

        # Get transcript
        user_transcript = request.form.get('message', '').strip()
        if not user_transcript and 'audio' not in request.files:
            return "No input detected", 400

        # Audio transcription
        if 'audio' in request.files:
            audio_file = request.files['audio']
            if audio_file:
                folders = get_participant_folder(participant_id, trial_type)
                audio_filename = get_audio_filename('user', participant_id, attempt_count + 1)
                audio_path = os.path.join(folders['participant_folder'], audio_filename)
                audio_file.save(audio_path)

                try:
                    with open(audio_path, "rb") as af:
                        user_transcript = openai.Audio.transcribe(
                            model="whisper-1",
                            file=af
                        )["text"]
                except:
                    user_transcript = speech_to_text(audio_path)

        if not user_transcript:
            return "Failed to transcribe message.", 400

        # ----------------------------------------------
        # META-QUESTION HANDLING (same as submit_message)
        # ----------------------------------------------
        if is_meta_question(user_transcript):
            left = attempts_left(concept_name)
            if left > 0:
                response_text = (
                    f"Yes — please go through the concept of {concept_name} and "
                    f"explain it in your own words; {format_attempts_left(concept_name)}."
                )
            else:
                response_text = (
                    f"You’ve already used all 3 tries for {concept_name}. "
                    f"Let’s move on to the next one."
                )

            # Logging
            log_interaction("User", concept_name, user_transcript)
            log_interaction("AI", concept_name, response_text)
            log_interaction_to_db_only("USER", concept_name, user_transcript, attempt_count)
            log_interaction_to_db_only("AI", concept_name, response_text, attempt_count)

            # Audio
            folders = get_participant_folder(participant_id, trial_type)
            ai_audio_filename = get_audio_filename('ai', participant_id, attempt_count)
            ai_audio_path = os.path.join(folders['participant_folder'], ai_audio_filename)
            generate_audio(response_text, ai_audio_path)

            meta = json.dumps({
                'ai_audio_url': ai_audio_filename,
                'attempt_count': attempt_count,
                'response': response_text
            })

            def generate():
                yield response_text
                yield "\n__JSON__START__" + meta + "__JSON__END__\n"

            return Response(stream_with_context(generate()), content_type='text/plain; charset=utf-8')

        # ----------------------------------------------
        # USE YOUR TUTOR LOGIC (V2 ENGINE)
        # ----------------------------------------------
        response_text = generate_response(
            user_message=user_transcript,
            concept_name=concept_name,
            golden_answer=golden_answer,
            attempt_count=attempt_count,
            conversation_history=conversation_history
        )

        # ----------------------------------------------
        # ATTEMPT LOGIC (same as submit_message)
        # ----------------------------------------------
        import re
        from difflib import SequenceMatcher

        def norm(t):
            return re.sub(r'[^a-z0-9\s]', '', (t or '').lower())

        sim = SequenceMatcher(None, norm(user_transcript), norm(golden_answer)).ratio()

        if sim >= 0.80:
            new_attempt = 3
        else:
            new_attempt = min(attempt_count + 1, 3)

        session['concept_attempts'][concept_name] = new_attempt
        session.modified = True

        # ----------------------------------------------
        # LOGGING (file + DB)
        # ----------------------------------------------
        log_interaction("User", concept_name, user_transcript)
        log_interaction("AI", concept_name, response_text)
        log_interaction_to_db_only("USER", concept_name, user_transcript, attempt_count)
        log_interaction_to_db_only("AI", concept_name, response_text, new_attempt)

        # ----------------------------------------------
        # AUDIO GENERATION
        # ----------------------------------------------
        folders = get_participant_folder(participant_id, trial_type)
        ai_audio_filename = get_audio_filename('ai', participant_id, new_attempt)
        ai_audio_path = os.path.join(folders['participant_folder'], ai_audio_filename)
        generate_audio(response_text, ai_audio_path)

        # ----------------------------------------------
        # STREAM TO FRONTEND
        # ----------------------------------------------
        meta = json.dumps({
            'ai_audio_url': ai_audio_filename,
            'attempt_count': new_attempt,
            'response': response_text
        })

        def generate():
            yield response_text
            yield "\n__JSON__START__" + meta + "__JSON__END__\n"

        return Response(stream_with_context(generate()), content_type='text/plain; charset=utf-8')

    except Exception as e:
        print("Error in stream_submit_message_v1:", str(e))
        return f"Error: {str(e)}", 500


def ssml_wrap(text):
    """Safe SSML wrapper without aggressive prosody manipulation."""
    try:
        def esc(t):
            return (t.replace('&', '&amp;')
                     .replace('<', '&lt;')
                     .replace('>', '&gt;'))

        safe = esc(text)
        return f"<speak>{safe}</speak>"
    except:
        return text



def clean_tts_text(text: str) -> str:
    """
    Smooth TTS by reducing unnatural pauses and improving flow.
    Designed for gTTS and OpenAI TTS.
    """
    import re

    if not text:
        return ""

    # Strip markdown, urls and formatting garbage
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'[*_#`~<>^{}\[\]|]', '', text)
    text = re.sub(r'[\\/]', ' ', text)

    # Normalize spaces
    text = re.sub(r'\s+', ' ', text).strip()

    # Reduce long punctuation pauses
    text = text.replace("...", ".").replace("..", ".")

    # Convert mid-sentence periods → commas (reduces pauses)
    text = re.sub(r'\.\s+(?=[a-zA-Z])', ', ', text)

    # Avoid double commas or weird spacing
    text = re.sub(r',\s*,', ', ', text)

    # Fix negative numbers ("-1" → "negative one")
    text = re.sub(r'(?<!\d)-(?=\d)', 'NEGATIVE_SIGN_PLACEHOLDER', text)
    text = re.sub(r'\b-(\d+)\b', r'negative \1', text)
    text = text.replace("NEGATIVE_SIGN_PLACEHOLDER", " negative ")

    # Ensure clean ending
    if not text.endswith(('.', '!', '?')):
        text += "."

    return text



@app.route('/synthesize', methods=['POST'])
def synthesize():
    try:
        data = request.get_json() or request.form
        text = data.get('text') if data else None
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        voice = data.get('voice', 'alloy')
        fmt = data.get('format', 'mp3')
        try:
            clean_text = clean_tts_text(text)
            ssml_text = ssml_wrap(clean_text, rate='5%', pitch='0%', break_ms=220)
            audio_bytes, content_type = synthesize_with_openai(ssml_text, voice=voice, fmt=fmt)
            return (audio_bytes, 200, {'Content-Type': content_type, 'Content-Disposition': 'inline; filename="tts.' + fmt + '"'})
        except Exception as openai_err:
            print('OpenAI TTS failed or rejected SSML, falling back to gTTS:', str(openai_err))
        try:
            from io import BytesIO
            bio = BytesIO()
            tts = gTTS(text=clean_text, lang='en')
            tts.write_to_fp(bio)
            bio.seek(0)
            return (bio.read(), 200, {'Content-Type': 'audio/mpeg', 'Content-Disposition': 'inline; filename="tts.mp3"'})
        except Exception as e:
            print('gTTS fallback failed:', str(e))
            return jsonify({'error': 'TTS synthesis failed'}), 500
    except Exception as e:
        print('Synthesize endpoint error:', str(e))
        return jsonify({'error': str(e)}), 500

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
    
    selected_concept_key = next(
        (k for k in concepts.keys() if k.lower() == concept_name.lower()),
        None
    )
    
    if not selected_concept_key:
        logger.error(f"Invalid concept selection: {concept_name}")
        return jsonify({'error': 'Invalid concept selection'})
    
    selected_concept = concepts[selected_concept_key]
    session['concept_name'] = selected_concept_key
    session['golden_answer'] = selected_concept.get("golden_answer", "")
    
    if 'concept_attempts' not in session:
        session['concept_attempts'] = {}
    session['concept_attempts'][selected_concept_key] = 0
    session.modified = True

    log_interaction("SYSTEM", selected_concept_key, 
                    f"Context set for concept: {selected_concept_key}")

    logger.info(f"Context set successfully for: {selected_concept_key}")
    return jsonify({'message': f'Context set for {selected_concept_key}.'})

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
    """Handle user message submission and generate AI response (V2-style natural replies)."""
    try:
        participant_id = session.get('participant_id')
        trial_type = session.get('trial_type')

        if not participant_id or not trial_type:
            return jsonify({'status': 'error','message':'Participant ID or trial type not found'}), 400

        # -------------------------------
        # 1) Load concept + validate
        # -------------------------------
        concept_name = request.form.get('concept_name', '').strip()
        concepts = load_concepts()

        matched = next((c for c in concepts if c.lower() == concept_name.lower()), None)
        if not matched:
            return jsonify({'status':'error','message':'Concept not found'}), 400

        concept_name = matched
        golden_answer = concepts[concept_name]['golden_answer']

        # -------------------------------
        # 2) Load attempts + conversation history
        # -------------------------------
        concept_attempts = session.get('concept_attempts', {})
        attempt_count = concept_attempts.get(concept_name, 0)

        conv_store = session.get('conversation_history', {})
        conversation_history = conv_store.get(concept_name, [])

        # -------------------------------
        # 3) Retrieve or transcribe user message
        # -------------------------------
        user_transcript = request.form.get('message', '').strip()

        if 'audio' in request.files:
            audio_file = request.files['audio']
            if audio_file:
                folders = get_participant_folder(participant_id, trial_type)
                audio_filename = get_audio_filename('user', participant_id, attempt_count + 1)
                audio_path = os.path.join(folders['participant_folder'], audio_filename)
                audio_file.save(audio_path)

                try:
                    with open(audio_path, "rb") as af:
                        user_transcript = openai.Audio.transcribe(
                            model="whisper-1",
                            file=af
                        )["text"]
                except Exception:
                    user_transcript = speech_to_text(audio_path)

        if not user_transcript:
            return jsonify({'status':'error','message':'No user message received'}), 400

        # -------------------------------
        # 4) META-QUESTION HANDLING ("Do I need to explain?")
        # -------------------------------
        if is_meta_question(user_transcript):
            left = attempts_left(concept_name)
            if left > 0:
                response = (
                    f"Yes — please go through the concept of {concept_name} and "
                    f"explain it in your own words; {format_attempts_left(concept_name)}."
                )
            else:
                response = (
                    f"You’ve already used all 3 tries for {concept_name}. "
                    f"Let’s move on to the next one."
                )

            # logging
            log_interaction("User", concept_name, user_transcript)
            log_interaction("AI", concept_name, response)
            log_interaction_to_db_only("USER", concept_name, user_transcript, attempt_count)
            log_interaction_to_db_only("AI", concept_name, response, attempt_count)

            # save audio
            folders = get_participant_folder(participant_id, trial_type)
            ai_audio_filename = get_audio_filename('ai', participant_id, attempt_count + 1)
            ai_audio_path = os.path.join(folders['participant_folder'], ai_audio_filename)
            generate_audio(response, ai_audio_path)

            # update convo memory
            conv_store.setdefault(concept_name, []).append(f"User: {user_transcript}")
            conv_store[concept_name].append(f"AI: {response}")
            session['conversation_history'] = conv_store
            session.modified = True

            return jsonify({
                'status': 'success',
                'response': response,
                'user_transcript': user_transcript,
                'ai_audio_url': ai_audio_filename,
                'attempt_count': attempt_count,
                'should_move_to_next': (left <= 0)
            })

        # -------------------------------
        # 5) Generate V2-style natural tutor reply
        # -------------------------------
        response = generate_response(
            user_message=user_transcript,
            concept_name=concept_name,
            golden_answer=golden_answer,
            attempt_count=attempt_count,
            conversation_history=conversation_history
        )

        # -------------------------------
        # 6) Update attempts (natural logic)
        # -------------------------------
        # Detect similarity early before increment
        import re
        from difflib import SequenceMatcher
        def norm(t): return re.sub(r'[^a-z0-9\s]', '', (t or '').lower())
        sim = SequenceMatcher(None, norm(user_transcript), norm(golden_answer)).ratio()

        if sim >= 0.80:
            new_attempt = 3     # mark as complete
        else:
            new_attempt = min(attempt_count + 1, 3)

        session['concept_attempts'][concept_name] = new_attempt

        # -------------------------------
        # 7) Logging (file + DB)
        # -------------------------------
        log_interaction("User", concept_name, user_transcript)
        log_interaction("AI", concept_name, response)
        log_interaction_to_db_only("USER", concept_name, user_transcript, attempt_count + 1)
        log_interaction_to_db_only("AI", concept_name, response, attempt_count + 1)

        # -------------------------------
        # 8) Save AI audio
        # -------------------------------
        folders = get_participant_folder(participant_id, trial_type)
        ai_audio_filename = get_audio_filename('ai', participant_id, new_attempt)
        ai_audio_path = os.path.join(folders['participant_folder'], ai_audio_filename)
        generate_audio(response, ai_audio_path)

        # -------------------------------
        # 9) Update conversation history
        # -------------------------------
        conv_store.setdefault(concept_name, []).append(f"User: {user_transcript}")
        conv_store[concept_name].append(f"AI: {response}")
        session['conversation_history'] = conv_store
        session.modified = True

        # -------------------------------
        # 10) Return result
        # -------------------------------
        return jsonify({
            'status': 'success',
            'response': response,
            'user_transcript': user_transcript,
            'ai_audio_url': ai_audio_filename,
            'attempt_count': new_attempt,
            'should_move_to_next': (new_attempt >= 3)
        })

    except Exception as e:
        print(f"Error in submit_message: {str(e)}")
        return jsonify({'status':'error','message':str(e)}), 500


        def _normalize_for_check(text):
            import re
            return re.sub(r'[^a-z0-9\s]', '', (text or '').lower().strip())

        try:
            user_norm_check = _normalize_for_check(user_transcript)
            golden_norm_check = _normalize_for_check(golden_answer)
            pre_similarity = SequenceMatcher(None, user_norm_check, golden_norm_check).ratio()
        except Exception:
            pre_similarity = 0.0

        is_similar_enough = (pre_similarity >= 0.8)

        response = generate_response(user_transcript, concept_name, golden_answer, attempt_count, conversation_history)
        
        if 'conversation_history' not in session:
            session['conversation_history'] = {}
        if concept_name not in session['conversation_history']:
            session['conversation_history'][concept_name] = []
        
        session['conversation_history'][concept_name].append(f"User: {user_transcript}")
        session['conversation_history'][concept_name].append(f"AI: {response}")
        
        if len(session['conversation_history'][concept_name]) > 10:
            session['conversation_history'][concept_name] = session['conversation_history'][concept_name][-10:]
        
        session.modified = True

        if is_similar_enough:
            concept_attempts[concept_name] = 3
        else:
            concept_attempts[concept_name] = min(attempt_count + 1, 3)
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

            returned_attempt = session['concept_attempts'].get(concept_name, attempt_count + 1)
            should_move_flag = (returned_attempt >= 3)

            return jsonify({
                'status': 'success',
                'response': response,
                'user_transcript': user_transcript,
                'ai_audio_url': ai_audio_filename,
                'attempt_count': returned_attempt,
                'should_move_to_next': should_move_flag
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


# ------------------------------------------------------------
# SEMANTIC SIMILARITY (Replacement for SequenceMatcher)
# ------------------------------------------------------------

import openai
import numpy as np

def semantic_similarity(a: str, b: str) -> float:
    """
    Uses OpenAI embeddings to compute real semantic similarity.
    Much more natural than keyword/character similarity.
    Output: 0.0 – 1.0
    """

    if not a or not b:
        return 0.0

    try:
        emb = openai.embeddings.create(
            model="text-embedding-3-small",
            input=[a, b]
        )

        e1 = np.array(emb.data[0].embedding)
        e2 = np.array(emb.data[1].embedding)

        cos_sim = np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2))
        return float(max(0, min(1, cos_sim)))

    except Exception as e:
        print("Embedding error:", e)
        return 0.0


def apply_ssml_prosody(text: str) -> str:
    """
    Wraps tutor feedback text in SSML prosody tags for smoother, more natural speech.
    This works for OpenAI TTS and most modern TTS engines that support SSML.
    """
    import html

    # Escape to avoid XML issues
    safe_text = html.escape(text)

    # Prosody tuning:
    # - Slightly slower rate (teaching style)
    # - Slightly higher pitch for friendlier tone
    # - lightweight sentence-level pauses
    # - Reduce falling tone between sentences
    ssml = f"""
<speak>
  <prosody rate="95%" pitch="+2%">
      {safe_text.replace('.', '<break time="300ms"/>')}
  </prosody>
</speak>
""".strip()

    return ssml


def generate_response(user_message, concept_name, golden_answer, attempt_count, conversation_history=None):
    """
    Unified tutoring logic combining:
    - V2 pipeline structure (filler → English check → heuristics → GPT)
    - V1 interaction design (no fake praise, confusion handling, natural tone)
    - Semantic similarity (OpenAI embeddings)
    """

    import re
    import openai
    import numpy as np

    # -------------------------------------------------
    # 0. Basic validation
    # -------------------------------------------------
    if not golden_answer or not concept_name:
        return (
            "I can’t provide feedback yet because the concept context isn’t set. "
            "Please make sure both the concept and golden answer are defined."
        )

    # -------------------------------------------------
    # 1. Filler / unclear message detection (KEEP V1 LOGIC)
    # -------------------------------------------------
    def is_filler(s):
        if not s or not str(s).strip():
            return True
        s2 = str(s).strip().lower()
        fillers = {
            'ok','okay','yes','no','mm','mmm','hmm','uh','uhh','fine','sure',
            'i dont know','idk','not sure'
        }
        if s2 in fillers:
            return True
        if len(s2) < 3:
            return True
        if re.match(r'^[\.\,\-\s]+$', s2):
            return True
        return False

    if is_filler(user_message):
        if attempt_count >= 2:
            return f"{golden_answer} You can now move on to the next concept."
        return (
            f"I couldn’t quite understand your explanation — it was too brief. "
            f"Try explaining {concept_name} in your own words using full sentences."
        )

    # -------------------------------------------------
    # 2. English detection
    # -------------------------------------------------
    def is_likely_english(text):
        if not text or not str(text).strip():
            return False
        txt = str(text)
        letters = [c for c in txt if c.isalpha()]
        if not letters:
            return bool(re.search(r'[A-Za-z]', txt))
        total_letters = len(letters)
        latin = sum(1 for c in letters if 'a' <= c.lower() <= 'z')
        return (latin / total_letters) >= 0.6

    if not is_likely_english(user_message):
        return "Please repeat your explanation in English so I can give feedback."

    # -------------------------------------------------
    # 3. SEMANTIC SIMILARITY via embeddings
    # -------------------------------------------------
    def semantic_similarity(a: str, b: str) -> float:
        try:
            emb = openai.embeddings.create(
                model="text-embedding-3-small",
                input=[a, b]
            )
            e1 = np.array(emb.data[0].embedding)
            e2 = np.array(emb.data[1].embedding)
            cos_sim = np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2))
            return float(max(0, min(1, cos_sim)))
        except Exception as e:
            print("Embedding error:", e)
            return 0.0

    sim = semantic_similarity(user_message, golden_answer)

    if sim >= 0.80:
        similarity_bucket = "high"
    elif sim >= 0.55:
        similarity_bucket = "medium"
    elif sim >= 0.35:
        similarity_bucket = "low"
    else:
        similarity_bucket = "very_low"

    # -------------------------------------------------
    # 4. Early acceptance (ONLY if clearly correct)
    # -------------------------------------------------
    if sim >= 0.88:
        if attempt_count >= 2:
            return f"{golden_answer} You’re correct. You can now move on to the next concept."
        return "Nice explanation — you’ve captured the essential idea. You can move on to the next concept."

    # -------------------------------------------------
    # 5. Conversation history block
    # -------------------------------------------------
    history_block = ""
    if conversation_history:
        history_block = "\n".join(conversation_history[-6:])

    # -------------------------------------------------
    # 6. NATURAL TUTOR SYSTEM PROMPT (V2 + V1 MERGED)
    # -------------------------------------------------
    system_prompt = f"""
You are a friendly, intelligent tutor guiding a student through the concept "{concept_name}"
as part of a self-explanation learning activity.

You must ALWAYS respond naturally — like a human tutor — NOT like a scripted rule engine.

Follow this interaction model strictly:

1. CLASSIFY THE STUDENT'S MESSAGE INTERNALLY (do NOT say the label):
   - A genuine attempt to explain the concept,
   - A sign of confusion (“I don't get it”, “I don’t know what to do”),
   - A procedural/meta question (“should I explain this?”, “what do I do?”),
   - Off-topic or unrelated content.

2. GENERAL BEHAVIOR:
   - Respond in warm, plain English.
   - Use no more than 3 short sentences.
   - Never give generic praise when the answer is clearly wrong or very low similarity.
   - If similarity_bucket = "very_low", treat it as incorrect.
   - Never say “you’re on the right track” unless the meaning is truly close.

3. ATTEMPT LOGIC:
   Attempt {attempt_count + 1} of 3.
   - Attempt 1:
       If incorrect → gently say it doesn't describe the concept and give ONE broad guiding hint.
       If partially correct → acknowledge what’s right and point out one missing piece.
   - Attempt 2:
       Give clearer guidance but DO NOT reveal the golden answer.
       Correct ONE key misunderstanding.
       Ask ONE focused question.
   - Attempt 3:
       If correct → confirm and tell them to move to the next concept.
       If still incorrect → give a brief 1–2 sentence explanation of the concept (paraphrased),
         then tell them to move to the next concept.

4. CONFUSION:
   If the student shows confusion:
       - Normalize their confusion (“It’s okay if this feels unclear.”)
       - Provide a simple way to start (“Try describing what changes when X changes.”)
       - Ask ONE guiding question.

5. META QUESTIONS:
   If the student asks what to do:
       - Briefly remind them that they should explain the concept in their own words.
       - Invite them to begin (“You can start by describing…”).

6. OFF-TOPIC ANSWERS:
   If the answer is unrelated:
       - Say clearly but kindly that it doesn’t define the concept.
       - Give ONE sentence about the kind of idea the concept involves.
       - Ask them to try again with that focus.

Golden Answer (DO NOT reveal before attempt 3):
{golden_answer}

Similarity bucket: {similarity_bucket}

Recent conversation:
{history_block if history_block else "(no prior turns)"}

Your response must be a natural-sounding tutor reply,
following the above rules, no more than 3 short sentences.
"""

    # -------------------------------------------------
    # 7. GPT response generation
    # -------------------------------------------------
    user_prompt = f'The student said: "{user_message}". Respond as the tutor.'

    try:
        result = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=150,
            temperature=0.55
        )
        return result.choices[0].message.content.strip()

    except Exception as e:
        return f"Error generating AI response: {str(e)}"


def is_meta_question(text: str) -> bool:
    if not text:
        return False
    t = text.lower().strip()

    cues = [
        "do i have to", "should i", "am i supposed to",
        "do you want me to", "what should i do",
        "how do i start", "how to proceed",
        "next step", "what now"
    ]

    return any(c in t for c in cues)


def detect_language_openai(text: str) -> str:
    """
    Uses OpenAI to detect the language of the input text.
    Returns the language name in lowercase, e.g. 'english', 'german', 'arabic'.
    """

    if not text or not text.strip():
        return "unknown"

    try:
        result = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Detect the language of the next user message. Answer ONLY with the language name."},
                {"role": "user", "content": text}
            ],
            max_tokens=5,
            temperature=0
        )
        lang = result.choices[0].message.content.strip().lower()
        return lang

    except Exception as e:
        print("Language detection failed:", str(e))
        return "unknown"


def attempts_left(concept_name: str) -> int:
    tries = session.get('concept_attempts', {}).get(concept_name, 0)
    return max(0, 3 - int(tries))

def format_attempts_left(concept_name: str) -> str:
    left = attempts_left(concept_name)
    if left <= 0:
        return "you’ve used all your tries for this concept."
    return f"you still have {left} {'try' if left == 1 else 'tries'} left"


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
    """Export all available user/AI audio, screen recordings, and logs as a ZIP. No CSV/Excel/database fallback."""
    try:
        import zipfile
        from io import BytesIO
        from flask import Response
        import os
        from datetime import datetime

        zip_buffer = BytesIO()
        files_found = False

        folders_to_export = [
            app.config.get('USER_AUDIO_FOLDER'),
            app.config.get('CONCEPT_AUDIO_FOLDER'),
        ]

        user_audio_base = app.config.get('USER_AUDIO_FOLDER', '')

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for folder in folders_to_export:
                if folder and os.path.exists(folder):
                    for root, dirs, files in os.walk(folder):
                        for file in files:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.relpath(file_path, app.config['UPLOAD_FOLDER'])
                            archive_path = f"Exported_Data/{rel_path}"
                            try:
                                zip_file.write(file_path, archive_path)
                                files_found = True
                            except Exception as e:
                                print(f"Could not add file {file_path}: {str(e)}")
            log_path = os.path.join(app.config['UPLOAD_FOLDER'], 'conversation_log.txt')
            if os.path.exists(log_path):
                zip_file.write(log_path, 'Exported_Data/conversation_log.txt')
                files_found = True

        zip_buffer.seek(0)

        if files_found and zip_buffer.getvalue():
            filename_prefix = "HAI_V1_Files_Export"
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


@app.route('/diagnose_uploads')
def diagnose_uploads():
    """Return a JSON summary of upload folders and environment info for debugging."""
    try:
        def sample_files(base, limit=50):
            out = []
            if not base or not os.path.exists(base):
                return out
            for root, dirs, files in os.walk(base):
                for f in files:
                    path = os.path.join(root, f)
                    try:
                        out.append({'path': os.path.relpath(path, base), 'size': os.path.getsize(path), 'mtime': os.path.getmtime(path)})
                    except Exception:
                        out.append({'path': os.path.relpath(path, base), 'size': None, 'mtime': None})
                    if len(out) >= limit:
                        return out
            return out

        upload_folder = app.config.get('UPLOAD_FOLDER')
        user_audio_folder = app.config.get('USER_AUDIO_FOLDER')
        concept_audio_folder = app.config.get('CONCEPT_AUDIO_FOLDER')

        data = {
            'upload_folder': upload_folder,
            'upload_exists': os.path.exists(upload_folder) if upload_folder else False,
            'user_audio_folder': user_audio_folder,
            'user_audio_exists': os.path.exists(user_audio_folder) if user_audio_folder else False,
            'concept_audio_folder': concept_audio_folder,
            'concept_audio_exists': os.path.exists(concept_audio_folder) if concept_audio_folder else False,
            'sample_upload_files': sample_files(upload_folder, limit=200),
            'sample_user_audio_files': sample_files(user_audio_folder, limit=200),
            'openai_api_key_present': bool(os.environ.get('OPENAI_API_KEY')),
        }
        return jsonify({'status': 'ok', 'diagnostic': data})
    except Exception as e:
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

if __name__ == '__main__':
    startup_interaction_id = get_interaction_id()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


    startup_interaction_id = get_interaction_id()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

