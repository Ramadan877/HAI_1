# Human-AI Voice Interaction (HAI) — Version 1

This repository contains a Human-AI Voice Interaction system designed for research and educational purposes. The system allows users to interact with an AI tutor using voice, focusing on self-explanation tasks around statistical concepts.

## Features

- Interactive web UI for Human-AI voice conversations
- PDF slide viewer for concept navigation
- Audio recording, transcription, and AI feedback
- Session and participant management
- Logging and audio file management

---

## Getting Started

### 1. Clone the Repository

Open your terminal and run:

```bash
git clone https://github.com/Ramadan877/HAI_1.git
cd HAI
```

### 2. Set Up Python Environment

It is recommended to use a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

Navigate to the `V1` directory and install the required packages:

```bash
cd V1
pip install -r requirements.txt
```


### 4. Set Up Environment Variables

The application requires several environment variables for proper operation.  
Create a `.env` file in the V1 directory with the following variables:

```bash
# OpenAI API Configuration
OPENAI_API_KEY=your_openai_api_key_here

# Database Configuration (PostgreSQL)
DATABASE_URL=postgresql://username:password@hostname:port/database_name

# Security Configuration
SECRET_KEY=your_secret_key_here

# Cloud Storage Configuration (Optional - for S3 backup)
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=your_aws_region
CLOUD_STORAGE_BUCKET=your_s3_bucket_name
```

**Required Variables:**
- `OPENAI_API_KEY`: Your OpenAI API key for transcription and AI responses
- `DATABASE_URL`: PostgreSQL database connection string for data storage
- `SECRET_KEY`: Secret key for Flask session security

**Optional Variables:**
- AWS credentials: For cloud backup of audio files (can work without S3)

### 5. Set Up Database

The application uses PostgreSQL for data storage. The database tables will be created automatically when you first run the application.

**Database Features:**
- Participant and session management
- Interaction logging (all conversations)
- Recording metadata storage
- Data export functionality

### 6. Run the Application

From the `V1` directory, start the Flask server:

```bash
python app.py
```

The server will start on [http://localhost:5000](http://localhost:5000).

### 7. Data Export (Research Data Collection)

The application includes comprehensive data export functionality for research purposes:

- **Data Dashboard**: Visit `/data_dashboard` to view statistics and recent sessions
- **Complete Export**: Visit `/export_complete_data` to download all data (database + files)
- **CSV Export**: Visit `/export_csv` to download database data as CSV files
- **File Browser**: Visit `/browse_files` to browse local user data files
- **Participant Export**: Visit `/export_participant/<participant_id>` for individual participant data

All exports maintain the original User_Data folder structure for consistency with your existing data organization.

---

## Using the UI

1. Open your browser and go to [http://localhost:5000](http://localhost:5000).
2. Enter a Participant ID and select a Task Type (Task 1, Task 2, or Test Mode).
3. Click **Start** to begin the session.
4. Use the PDF viewer to navigate concepts.
5. Click the avatar to open the chat modal and interact with the AI using your voice.

---

## File Structure

- `V1/app.py` — Main Flask backend with database integration and data export
- `V1/database.py` — Database models and configuration
- `V1/templates/index.html` — Main UI template
- `V1/static/` — Static files (JS, CSS)
- `V1/resources/` — PDF and other resource files
- `V1/uploads/User Data/` — Participant audio files and logs (preserved structure)
- `V1/requirements.txt` — Python dependencies including database packages
- `V1/.env` — Environment variables (create this file)

---

## Troubleshooting

- Ensure your microphone is enabled and accessible by your browser.
- If you encounter issues with audio transcription, check your OpenAI API key and internet connection.
- For local Whisper model fallback, ensure you have the necessary dependencies and model files.

---

## License

This project is for academic and research use.  
For other uses, please contact the repository owner.

---

## Acknowledgements

- [Flask](https://flask.palletsprojects.com/)
- [OpenAI](https://openai.com/)
- [gTTS](https://pypi.org/project/gTTS/)
- [Whisper](https://github.com/openai/whisper)

---

*For questions or contributions, please open an issue or pull request.*
