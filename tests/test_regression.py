import pytest
import threading
import time
from io import BytesIO

import app as app_module
from app import app
from rubric_parser import RubricParser
from scoring_engine import ScoringEngine


@pytest.fixture
def scorer():
    parser = RubricParser()
    return ScoringEngine(parser.get_rubrics())


def test_invalid_duration_string_raises_value_error(scorer):
    with pytest.raises(ValueError, match="duration_seconds"):
        scorer.calculate_score("Hello everyone, my name is Alex.", duration_seconds="bad")


@pytest.mark.parametrize(
    ("word_count", "duration_seconds", "expected_wpm", "expected_score"),
    [
        (47, 20, 141.0, 6),
        (703, 300, 140.6, 6),
        (161, 60, 161.0, 2),
    ],
)
def test_speech_rate_uses_displayed_whole_wpm_for_rubric(
    scorer, word_count, duration_seconds, expected_wpm, expected_score
):
    transcript = "Hello " + "practice " * (word_count - 1)
    result = scorer.calculate_score(transcript, duration_seconds)
    speech_rate = next(
        criterion for criterion in result["criteria_scores"]
        if criterion["criterion"] == "Speech Rate"
    )
    metric = speech_rate["metrics"][0]

    assert result["word_count"] == word_count
    assert result["metadata"]["wpm"] == pytest.approx(expected_wpm)
    assert metric["wpm"] == pytest.approx(expected_wpm)
    assert metric["score"] == expected_score
    assert metric["level"] != "Unknown"


def test_text_api_does_not_use_a_supplied_speaking_duration(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "queue_video_generation",
        lambda transcript, results: {"status": "processing", "job_id": "text-duration-job"},
    )
    response = app.test_client().post(
        "/api/score",
        json={"transcript": "Hello everyone, my name is Alex.", "duration_seconds": 52},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["word_count"] == 6
    assert body["metadata"]["duration_seconds"] is None
    assert body["metadata"]["wpm"] is None


def test_empty_transcript_is_rejected_by_api():
    client = app.test_client()
    response = client.post("/api/score", json={"transcript": "   "})

    assert response.status_code == 400
    assert "empty" in response.get_json()["error"].lower()


def test_score_response_does_not_wait_for_video_generation(monkeypatch):
    video_started = threading.Event()
    release_video = threading.Event()

    def blocked_video_generation(transcript, results, job_id):
        video_started.set()
        assert release_video.wait(timeout=5)
        return {
            "video_url": f"/generated-video?file=generated_interview_video_{job_id}.mp4",
            "status": "completed",
            "job_id": job_id,
        }

    monkeypatch.setattr(app_module, "generate_video_artifact", blocked_video_generation)
    client = app.test_client()

    try:
        response = client.post(
            "/api/score",
            json={"transcript": "My name is Jordan and I enjoy solving problems."},
        )

        assert video_started.wait(timeout=2)
        assert response.status_code == 200
        body = response.get_json()
        assert body["overall_score"] >= 0
        assert body["generated_video"]["status"] == "processing"

        release_video.set()
        job_id = body["generated_video"]["job_id"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status_response = client.get(f"/api/video-status/{job_id}")
            if status_response.get_json()["status"] == "completed":
                break
            time.sleep(0.01)

        assert status_response.get_json()["status"] == "completed"
    finally:
        release_video.set()


def test_audio_route_transcribes_scores_and_queues_video(monkeypatch):
    class StubWhisperModel:
        def transcribe(self, audio_path, fp16=False):
            return {
                "text": "My name is Casey, I study engineering and enjoy reading.",
                "segments": [{"end": 3.0}],
            }

    monkeypatch.setattr(app_module, "get_whisper_model", lambda: StubWhisperModel())
    monkeypatch.setattr(app_module, "get_audio_file_duration", lambda path: 3.25)
    monkeypatch.setattr(
        app_module,
        "queue_video_generation",
        lambda transcript, results: {"status": "processing", "job_id": "audio-test-job"},
    )

    response = app.test_client().post(
        "/api/score-audio",
        data={
            "audio": (BytesIO(b"audio placeholder"), "practice.wav"),
            "duration_seconds": "60",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["transcript_extracted"].startswith("My name is Casey")
    assert body["audio_duration_detected"] == 3.25
    assert body["generated_video"]["status"] == "processing"
    assert body["metadata"]["duration_seconds"] == 3.25
    assert body["metadata"]["wpm"] == pytest.approx(body["word_count"] / 3.25 * 60)
    speech_rate = next(
        criterion for criterion in body["criteria_scores"]
        if criterion["criterion"] == "Speech Rate"
    )
    assert speech_rate["metrics"][0]["wpm"] == round(body["metadata"]["wpm"], 2)


def test_audio_duration_failure_does_not_use_whisper_segment_estimate(monkeypatch):
    class StubWhisperModel:
        def transcribe(self, audio_path, fp16=False):
            return {
                "text": "My name is Casey and I enjoy reading.",
                "segments": [{"end": 3.0}],
            }

    monkeypatch.setattr(app_module, "get_whisper_model", lambda: StubWhisperModel())
    monkeypatch.setattr(app_module, "get_audio_file_duration", lambda path: None)
    monkeypatch.setattr(
        app_module,
        "queue_video_generation",
        lambda transcript, results: {"status": "processing", "job_id": "duration-missing-job"},
    )

    response = app.test_client().post(
        "/api/score-audio",
        data={"audio": (BytesIO(b"audio placeholder"), "practice.wav")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["audio_duration_detected"] is None
    assert body["metadata"]["duration_seconds"] is None
    assert body["metadata"]["wpm"] is None


def test_audio_api_scores_141_wpm_with_existing_rubric(monkeypatch):
    transcript = "Hello " + "practice " * 46

    class StubWhisperModel:
        def transcribe(self, audio_path, fp16=False):
            return {"text": transcript}

    monkeypatch.setattr(app_module, "get_whisper_model", lambda: StubWhisperModel())
    monkeypatch.setattr(app_module, "get_audio_file_duration", lambda path: 20.0)
    monkeypatch.setattr(
        app_module,
        "queue_video_generation",
        lambda transcript, results: {"status": "processing", "job_id": "wpm-141-job"},
    )

    response = app.test_client().post(
        "/api/score-audio",
        data={"audio": (BytesIO(b"audio placeholder"), "practice.wav")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    speech_rate = next(
        criterion for criterion in body["criteria_scores"]
        if criterion["criterion"] == "Speech Rate"
    )
    assert body["word_count"] == 47
    assert body["metadata"]["wpm"] == pytest.approx(141)
    assert speech_rate["metrics"][0]["wpm"] == 141
    assert speech_rate["metrics"][0]["score"] == 6
    assert speech_rate["metrics"][0]["level"] == "Fast"


def test_audio_transcription_failure_returns_clear_message(monkeypatch):
    class FailingWhisperModel:
        def transcribe(self, audio_path, fp16=False):
            raise RuntimeError("unsupported audio encoding")

    monkeypatch.setattr(app_module, "get_whisper_model", lambda: FailingWhisperModel())
    monkeypatch.setattr(app_module, "get_audio_file_duration", lambda path: 3.0)

    response = app.test_client().post(
        "/api/score-audio",
        data={"audio": (BytesIO(b"audio placeholder"), "practice.wav")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == (
        "Unable to transcribe the uploaded audio. Please try another recording."
    )
