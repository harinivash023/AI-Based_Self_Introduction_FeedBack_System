# Self Introduction Feedback System

Interview Coach is a Python application for practicing and evaluating spoken self-introductions. It scores transcript content, speaking pace, language, clarity, and engagement using a transparent communication rubric. It also supports audio transcription and generates a short coaching video after scoring.

The repository contains two related entry points:

- A Flask web application for transcript and audio scoring.
- A standalone video-scoring pipeline under `Video_Scoring_Agent/`.

## Features

- Responsive browser interface served by Flask.
- Transcript scoring through the web UI or `POST /api/score`.
- Audio upload and speech-to-text transcription through `POST /api/score-audio`.
- Optional duration input for words-per-minute analysis.
- Rubric loaded from `Case study for interns.xlsx`.
- Overall score out of 100 with criterion and metric feedback.
- Keyword, flow, grammar, vocabulary, filler-word, pace, and positivity feedback.
- Generated MP4 coaching explanation with optional Windows narration audio.
- Standalone video-file processing and report generation.

## Technology Stack

| Technology | Where it is used | Why it is used |
| --- | --- | --- |
| Python 3.10+ | Application and scoring logic | Runtime for the API, scoring engine, NLP pipeline, and media processing. |
| Flask | `app.py` | Serves the frontend and exposes REST API endpoints. |
| Flask-CORS | Flask API | Allows browser clients to call the API when the frontend is opened separately. |
| HTML5, CSS3, vanilla JavaScript | `index.html` | Provides a lightweight responsive frontend without a frontend framework. |
| pandas and openpyxl | `rubric_parser.py` | Reads the Excel workbook and exposes the rubric to the scorer. |
| Custom Python rules | `scoring_engine.py` | Implements keyword detection, flow checks, WPM, grammar heuristics, TTR, filler rate, and positivity scoring. |
| sentence-transformers | `scoring_engine.py` | Provides optional `all-MiniLM-L6-v2` embeddings for semantic greeting matching. |
| scikit-learn | `scoring_engine.py` | Calculates cosine similarity for semantic matching. |
| OpenAI Whisper and PyTorch | Audio/video transcription | Converts speech from uploaded audio or extracted video audio into text. |
| MoviePy | Standalone video pipeline | Extracts audio from video and creates demo media. |
| Pillow, NumPy, imageio, imageio-ffmpeg | Video generation | Draws coaching frames, converts images, encodes MP4, and supplies FFmpeg. |
| PowerShell System.Speech | Windows narration | Converts the generated coaching script into a WAV file locally. |
| gTTS | Optional demo-video creation | Creates speech audio when the standalone demo video is generated. |

## Architecture

```text
Browser (index.html)
        |
        | JSON or multipart/form-data
        v
Flask API (app.py)
        |
        +--> RubricParser --> Case study for interns.xlsx
        |
        +--> ScoringEngine --> rule-based and optional NLP scoring
        |
        +--> Whisper --> transcript for uploaded audio
        |
        +--> video generation --> generated_outputs/*.mp4
```

## Rubric

| Criterion | Weight |
| --- | ---: |
| Content and Structure | 40 |
| Speech Rate | 10 |
| Language and Grammar | 20 |
| Clarity | 15 |
| Engagement | 15 |

The overall score is the sum of normalized weighted criterion scores. When duration is provided, WPM is calculated as:

```text
word_count / duration_seconds * 60
```

Without duration, the Speech Rate metric cannot be calculated.

## Project Structure

```text
.
├── app.py                         Flask API and video generation
├── index.html                     Browser UI
├── rubric_parser.py               Excel rubric loader
├── scoring_engine.py              Scoring algorithms
├── Case study for interns.xlsx    Rubric source and sample transcript
├── Sample text for case study.txt Plain-text sample transcript
├── test_scoring.py                Scoring smoke test
├── quick_test_upload.py           Audio upload API example
├── requirements.txt               Main dependencies
├── ARCHITECTURE.md                Architecture notes
├── generated_outputs/             Runtime media and scripts
└── Video_Scoring_Agent/           Standalone video pipeline
    ├── main.py                    CLI entry point
    └── agents.py                  Processing agents
```

Generated files such as `test_results.json`, `analysis_report.txt`, uploaded media, and model caches are runtime outputs.

## Requirements

- Python 3.10 or newer. Python 3.11 is recommended.
- Windows, macOS, or Linux.
- Internet access on the first run if Whisper or the sentence-transformer model is not cached.
- Enough memory and disk space for PyTorch and the Whisper `base` model.
- Windows PowerShell for narrated video audio.

The root `requirements.txt` is the main dependency file. It includes the Flask, transcription, and video-generation dependencies required by the web application.

## Installation

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation for the current session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

`imageio-ffmpeg` provides the FFmpeg binary used by the application. A system FFmpeg installation can still help when troubleshooting MoviePy.

## Run the Web Application

```powershell
python app.py
```

Open <http://localhost:5000>. Flask serves the frontend and API from the same process.

To use the interface:

1. Paste a self-introduction into the transcript field.
2. Enter the recording duration when available.
3. Select **Score and generate video**.
4. Review the overall score, detailed metrics, feedback, and generated video.

For audio scoring, choose an audio file and select **Upload audio and score**. Whisper transcribes the file, the same scoring engine evaluates it, and the application generates the coaching artifact.

The first audio request may take longer because Whisper loads its model. The sentence-transformer model is loaded only when semantic greeting matching is needed. If it cannot be loaded, rule-based scoring continues.

## API Reference

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/api/health` | Check API status. |
| GET | `/api/rubrics` | Return the active rubric. |
| GET | `/api/sample` | Return the sample transcript. |
| POST | `/api/score` | Score a transcript supplied as JSON. |
| POST | `/api/score-audio` | Transcribe and score an uploaded audio file. |
| GET | `/generated-video` | Serve the latest generated MP4. |

### Transcript request

```json
{
  "transcript": "Hello everyone, my name is Alex. I enjoy reading. Thank you for listening.",
  "duration_seconds": 20
}
```

PowerShell example:

```powershell
$body = @{ transcript = "Hello everyone, my name is Alex. Thank you for listening."; duration_seconds = 20 } | ConvertTo-Json
Invoke-RestMethod http://localhost:5000/api/score -Method Post -ContentType "application/json" -Body $body
```

### Audio request

Send a `multipart/form-data` request with:

- `audio`: required audio file.
- `duration_seconds`: optional numeric override.

If duration is not supplied, the server attempts to detect it from the media file or Whisper timestamps.

## Run Tests

Run the scoring smoke test from the repository root:

```powershell
python test_scoring.py
```

The test loads the workbook sample, scores it for 52 seconds, prints each criterion, and writes `test_results.json`.

With the server running, check the API:

```powershell
Invoke-RestMethod http://localhost:5000/api/health
Invoke-RestMethod http://localhost:5000/api/sample
```

`quick_test_upload.py` is an example client for posting `Video_Scoring_Agent/sample_video.mp4` to `/api/score-audio`.

## Standalone Video Pipeline

```powershell
cd Video_Scoring_Agent
python main.py ..\Task_explanation_video.mp4
```

Or provide another video path:

```powershell
python main.py C:\path\to\your\video.mp4
```

The standalone pipeline:

1. Extracts audio with `VideoProcessorAgent`.
2. Transcribes audio with `TranscriptionAgent` and Whisper.
3. Scores the transcript with the shared rubric and scoring engine.
4. Writes the result to `analysis_report.txt`.

If no video path is supplied, the script attempts to create a sample video using gTTS and MoviePy.

## Troubleshooting

- **Workbook not found:** Run commands from the repository root. The parser expects `Case study for interns.xlsx` in the current working directory.
- **Frontend says the backend is unavailable:** Start `python app.py` and open `http://localhost:5000`.
- **Whisper fails to load:** Check internet access, disk space, and PyTorch installation.
- **Narration fails:** Narration uses Windows PowerShell `System.Speech`; the generated video may still be returned without audio.
- **FFmpeg or MoviePy errors:** Confirm that `imageio-ffmpeg` is installed. A system FFmpeg installation may also be required for the standalone pipeline.
- **Port 5000 is busy:** Stop the other process or change the port at the bottom of `app.py`.

## Limitations

- Grammar and sentiment are lightweight heuristics rather than full grammar correction or general sentiment analysis.
- Rubric loading depends on the workbook name and the `Rubrics` worksheet.
- Generated files use fixed names, so a new score replaces the previous generated video.
- `app.py` uses Flask debug mode and is intended for local development, not production deployment without hardening.
