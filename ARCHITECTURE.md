# Current Architecture

## Supported inputs and output

The application accepts:

1. Typed transcript text
2. Uploaded audio

It returns a score and feedback, then generates a feedback MP4 asynchronously. User-uploaded video scoring is not supported.

## Web application

```text
Browser UI (index.html)
       │
       ├── Text ── POST /api/score ─────────────────┐
       │                                            │
       └── Audio ─ POST /api/score-audio             │
                    │                               │
                    └── Whisper transcription ──────┤
                                                    ▼
                                               Transcript
                                                    │
                                                    ▼
                                         Shared scoring engine
                                         ├── Rubric parser
                                         │    ├── rubric_parser.py
                                         │    └── shared_rubric.py
                                         └── Scoring implementation
                                              ├── scoring_engine.py
                                              └── shared_scoring.py
                                                    │
                                          Score and feedback
                                                    │
                                                    ▼
                                       Background video generation
                                                    │
                                      Job status and generated MP4
                                                    │
                                                    ▼
                                                  Browser
```

The two top-level modules are compatibility imports: `rubric_parser.py` imports `RubricParser` from `shared_rubric.py`, and `scoring_engine.py` imports `ScoringEngine` from `shared_scoring.py`. Flask initializes the parser and scorer in `app.py`; both text and audio routes call that same scorer.

## Request flows

### Text

```text
Browser → POST /api/score → scoring engine → score and feedback
                                      └────→ background feedback-video job
```

The text route requires a non-empty transcript and does not accept a duration.

### Audio

```text
Browser → POST /api/score-audio → audio file → Whisper → transcript
                                                        │
                                                        ▼
                                                  scoring engine
                                                        │
                                     score, feedback, and video job
```

The route attempts to detect recording duration and uses it for Speech Rate when available. It rejects video uploads.

### Generated feedback video

```text
Score and feedback
       ↓
Single-worker background executor
       ↓
Render frames and encode an MP4
       ↓
GET /api/video-status/<job_id>
       ↓
GET /generated-video
       ↓
Browser video player
```

The scoring response does not wait for video generation. It includes a job ID; the browser polls the status endpoint and loads the MP4 when the job completes. Video rendering uses Pillow, imageio, imageio-ffmpeg, and NumPy. Windows narration is optional.

## Scoring categories

| Category | Weight |
| --- | ---: |
| Content & Structure | 40 |
| Speech Rate | 10 |
| Language & Grammar | 20 |
| Clarity | 15 |
| Engagement | 15 |

The category weights total 100. Detailed scoring rules and feedback are implemented in `shared_scoring.py`; rubric criteria and the sample transcript loader are in `shared_rubric.py`. The workbook is read to provide the sample transcript.

## API routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` and `/index.html` | Browser UI |
| GET | `/api` | Basic API information |
| GET | `/api/health` | Health check |
| GET | `/api/rubrics` | Rubric data |
| GET | `/api/sample` | Sample transcript |
| POST | `/api/score` | Score text |
| POST | `/api/score-audio` | Transcribe and score audio |
| GET | `/api/video-status/<job_id>` | Feedback-video job status |
| GET | `/generated-video` | Generated MP4 |

## Not part of the current architecture

- Video uploads as a user input
- Video-to-audio extraction for transcript scoring
- Standalone video-scoring CLI or report-generation pipeline
