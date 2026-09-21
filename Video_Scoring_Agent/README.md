# Video Scoring Agent

An agentic AI application that extracts transcripts from video files and scores them based on communication skills rubrics.

## 🤖 Architecture

The system uses a multi-agent architecture:
1.  **VideoProcessorAgent**: Handles video input and audio extraction.
2.  **TranscriptionAgent**: Uses OpenAI Whisper to transcribe audio to text.
3.  **ScoringAgent**: Applies rule-based and NLP-based scoring logic using the provided rubrics.
4.  **ReportingAgent**: Generates detailed analysis reports.

## 🚀 Setup

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    *Note: You also need FFmpeg installed on your system for `moviepy` and `whisper`.*

2.  Run the application:
    ```bash
    python main.py [path_to_video.mp4]
    ```
    If no video is provided, it will generate a sample video for demonstration.

## 📂 Files
- `main.py`: Entry point and orchestrator.
- `agents.py`: Agent definitions.
- `scoring_engine.py`: Core scoring logic (reused).
- `rubric_parser.py`: Rubric extraction (reused).
- `Case study for interns.xlsx`: Rubric data source.

## 📊 Output
The tool generates:
- Console output with progress logs.
- `analysis_report.txt`: A detailed text report of the scoring.
