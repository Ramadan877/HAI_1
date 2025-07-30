# Human-AI Voice Interaction (HAI) -- Version 1

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


### 4. Set Up OpenAI API Key

The application uses OpenAI's API for transcription and chat.  
Set your API key as an environment variable:

```bash
export OPENAI_API_KEY=your_openai_api_key_here
```

On Windows (Command Prompt):

```cmd
set OPENAI_API_KEY=your_openai_api_key_here
```

### 5. Run the Application

From the `V1` directory, start the Flask server:

```bash
python app.py
```

The server will start on [http://localhost:5000](http://localhost:5000).

---

## Using the UI

1. Open your browser and go to [http://localhost:5000](http://localhost:5000).
2. Enter a Participant ID and select a Task Type (Task 1, Task 2, or Test Mode).
3. Click **Start** to begin the session.
4. Use the PDF viewer to navigate concepts.
5. Click the avatar to open the chat modal and interact with the AI using your voice.

---

## File Structure

- `V1/app.py` — Main Flask backend for the first version
- `V1/templates/index.html` — Main UI template
- `V1/static/` — Static files (JS, CSS)
- `V1/resources/` — PDF and other resource files
- `V1/uploads/` — Audio and log storage

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
