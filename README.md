# Self-Introduction Feedback System

A Flask application for practicing spoken self-introductions. Submit a typed transcript or an audio recording to receive a rubric-based score and actionable feedback. Audio is transcribed locally with Whisper. After scoring, the app generates a short MP4 feedback video asynchronously and makes it available in the browser.

**Current inputs:** text and audio. **Current outputs:** score, detailed feedback, and a generated feedback video. User-uploaded video scoring is not supported.

## Key Highlights

- Text and audio submissions use the same scoring engine.
- Audio submissions follow an audio → Whisper transcript → scoring workflow.
- The rubric evaluates Content & Structure, Speech Rate, Language & Grammar, Clarity, and Engagement.
- Content feedback identifies introduction sections and supporting evidence. Grammar feedback includes suggested corrections when available.
- Feedback-video generation runs in a background worker; the API returns a job ID for browser polling.
- Rubric and scoring implementations are shared in `shared_rubric.py` and `shared_scoring.py`.

## Architecture

```text
Browser UI (index.html)
  ├── Text ── POST /api/score ───────────────────┐
  └── Audio ─ POST /api/score-audio ─ Whisper ──┤
                                                v
                                      Transcript scoring
                                      ├── rubric_parser.py
                                      │     └── shared_rubric.py
                                      └── scoring_engine.py
                                            └── shared_scoring.py
                                                │
                                       Score and feedback
                                                │
                                      Background video worker
                                                │
                                       Generated MP4
                                                │
                                       Browser polling/player
```

`rubric_parser.py` and `scoring_engine.py` are compatibility import modules. The corresponding shared modules contain the implementations used by the Flask app.

## Scoring

| Category | Weight | Evaluation |
| --- | ---: | --- |
| Content & Structure | 40 | Greeting, name, education, skills, projects, experience, achievements, career goal, and closing |
| Speech Rate | 10 | Words per minute when audio duration is available |
| Language & Grammar | 20 | Grammar, sentence structure, vocabulary, repetition, sentence completeness, and writing mechanics |
| Clarity | 15 | Configured filler-word rate |
| Engagement | 15 | Positive/negative word-list heuristic |

The overall score is out of 100. Content section points are normalized to the category weight; optional experience and achievement sections are handled separately from required/recommended sections. Language & Grammar can use local LanguageTool for suggestions, with built-in grammar checks as a fallback. Content section detection can use sentence-transformer similarity in addition to rules.

Speech rate is calculated as `word_count / duration_seconds * 60`. The text endpoint does not accept duration, so it does not produce a WPM score. For audio submissions, the server attempts to detect duration from the uploaded file.

These scores are practice feedback, not a formal assessment. Engagement and several other checks are lightweight heuristics.

## Technology Stack

| Technology | Use |
| --- | --- |
| Python | Application, transcription integration, and scoring |
| Flask, Flask-CORS | Web server, API routes, and cross-origin support |
| HTML, CSS, JavaScript | Browser interface; no frontend framework |
| pandas, openpyxl | Read the workbook sample transcript |
| OpenAI Whisper, PyTorch | Local audio transcription using the `base` model |
| sentence-transformers, scikit-learn | Optional semantic section matching and cosine similarity |
| language-tool-python, Java | Local grammar and writing suggestions |
| NumPy, Pillow, imageio, imageio-ffmpeg | Render and encode generated feedback videos |
| MoviePy | Optional fallback for detecting uploaded-audio duration |
| PowerShell `System.Speech` | Optional Windows narration for generated videos |

Dependencies are listed in [`requirements.txt`](./requirements.txt). The workbook `Case study for interns.xlsx` is required at startup because the rubric parser loads the sample transcript from it. No project-specific environment variables or API keys are required.

## Project Structure

```text
.
├── app.py                         # Flask API, Whisper audio flow, and feedback-video worker
├── index.html                     # Text/audio UI, feedback display, video polling/player
├── rubric_parser.py               # Compatibility import for shared rubric parser
├── shared_rubric.py               # Rubric definitions and workbook sample loader
├── scoring_engine.py              # Compatibility import for shared scoring engine
├── shared_scoring.py              # Authoritative scoring implementation
├── Case study for interns.xlsx    # Workbook containing the sample transcript
├── requirements.txt               # Application dependencies
├── tests/
│   ├── test_regression.py         # API, audio, and feedback-video workflow tests
│   └── test_scoring_enhancements.py
├── README.md
└── ARCHITECTURE.md
```

Generated audio, video, and other runtime files are written under `generated_outputs/`.

## Setup

Requirements:

- Python and the packages declared in `requirements.txt`
- Internet access on first run to download model files if they are not cached
- Java for LanguageTool's local grammar suggestions; built-in grammar checks remain available if LanguageTool cannot start
- Windows PowerShell for optional generated-video narration

Create a virtual environment and install dependencies from the project root.

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run Locally

```bash
python app.py
```

Open <http://localhost:5000>, enter a transcript or upload an audio recording, then review the score and feedback. The browser polls for the generated feedback video and displays it when ready.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/` | Serve the browser interface |
| GET | `/index.html` | Serve the browser interface |
| GET | `/api` | Return basic API information |
| GET | `/api/health` | Health check |
| GET | `/api/rubrics` | Return rubric data |
| GET | `/api/sample` | Return the workbook sample transcript |
| POST | `/api/score` | Score a text transcript |
| POST | `/api/score-audio` | Transcribe and score an uploaded audio file |
| GET | `/api/video-status/<job_id>` | Check feedback-video job status |
| GET | `/generated-video` | Serve a generated MP4 |

### Score text

```bash
curl -X POST http://localhost:5000/api/score \
  -H "Content-Type: application/json" \
  -d "{\"transcript\":\"Hello. My name is Alex, and I study computer science.\"}"
```

The response includes the overall score, word count, category results, metadata, and feedback-video job information.

### Score audio

Send `multipart/form-data` with an `audio` file field:

```bash
curl -X POST http://localhost:5000/api/score-audio \
  -F "audio=@introduction.wav"
```

The server transcribes the recording with Whisper, scores the resulting transcript, and returns the transcript, detected duration when available, scoring results, and video-job information. Video files are rejected.

### Feedback-video status

When the scoring response contains `generated_video.status: "processing"`, poll:

```text
GET /api/video-status/<job_id>
```

On completion, the response contains the generated video's URL.

## Tests

Run the automated tests from the project root:

```bash
python -m pytest -q tests
```

## Screenshots and Demo

Screenshots are not currently included. Add the browser interface and scoring-result screenshots here when available.

## Limitations and Future Improvements

Current limitations:

- Scoring uses a mix of heuristics and locally loaded models; feedback should be treated as guidance.
- Text submissions do not include speaking duration, so Speech Rate cannot be calculated for them.
- Narration for generated feedback videos uses Windows PowerShell; video generation can fall back to a silent MP4.
- Flask's development server is configured for local use and should be hardened before public deployment.

Possible future improvements (not implemented):

- Support video uploads by extracting their audio, transcribing it with Whisper, and passing the transcript to the existing scoring engine.
- Calibrate heuristic scoring against human-reviewed examples.
- Add deployment configuration and production server support.
