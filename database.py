from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class Participant(db.Model):
    __tablename__ = 'participants'
    
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    sessions = db.relationship('Session', backref='participant', lazy=True, cascade='all, delete-orphan')

class Session(db.Model):
    __tablename__ = 'sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    participant_id = db.Column(db.String(50), db.ForeignKey('participants.participant_id'), nullable=False)
    trial_type = db.Column(db.String(20), nullable=False)  
    version = db.Column(db.String(10), nullable=False) 
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    # Relationships
    interactions = db.relationship('Interaction', backref='session', lazy=True, cascade='all, delete-orphan')
    recordings = db.relationship('Recording', backref='session', lazy=True, cascade='all, delete-orphan')

class Interaction(db.Model):
    __tablename__ = 'interactions'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), db.ForeignKey('sessions.session_id'), nullable=False)
    speaker = db.Column(db.String(20), nullable=False) 
    concept_name = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    attempt_number = db.Column(db.Integer, default=1)

class Recording(db.Model):
    __tablename__ = 'recordings'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), db.ForeignKey('sessions.session_id'), nullable=False)
    recording_type = db.Column(db.String(20), nullable=False)  
    file_path = db.Column(db.String(500), nullable=False) 
    original_filename = db.Column(db.String(200))
    file_size = db.Column(db.Integer)
    concept_name = db.Column(db.String(100))
    attempt_number = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserEvent(db.Model):
    __tablename__ = 'user_events'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), db.ForeignKey('sessions.session_id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)  
    event_data = db.Column(db.JSON)  
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)