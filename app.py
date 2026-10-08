"""
Flask REST API for Communication Skills Scoring
"""
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

from flask_cors import CORS
from rubric_parser import RubricParser
from scoring_engine import ScoringEngine
import math
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
import imageio.v2 as imageio
import imageio_ffmpeg
import numpy as np

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Initialize parser and scoring engine
print("Initializing rubric parser...")
parser = RubricParser()
rubrics = parser.get_rubrics()

print("Initializing scoring engine...")
scorer = ScoringEngine(rubrics)
print("API ready!")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def normalize_duration(duration_raw, field_name="duration_seconds"):
    """Validate user-supplied duration values before using them for WPM."""
    if duration_raw is None:
        return None

    if isinstance(duration_raw, str):
        duration_raw = duration_raw.strip()
        if not duration_raw:
            return None

    try:
        value = float(duration_raw)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive number.")

    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be a positive number.")

    return value


# Setup local FFmpeg binary dynamically for Whisper and other subprocesses
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = os.path.dirname(ffmpeg_exe)
    
    local_bin = os.path.join(BASE_DIR, "bin")
    os.makedirs(local_bin, exist_ok=True)
    local_ffmpeg = os.path.join(local_bin, "ffmpeg.exe")
    
    if not os.path.exists(local_ffmpeg):
        try:
            os.link(ffmpeg_exe, local_ffmpeg)
            print(f"Created hardlink to FFmpeg at {local_ffmpeg}")
        except Exception as link_err:
            import shutil
            shutil.copyfile(ffmpeg_exe, local_ffmpeg)
            print(f"Copied FFmpeg to {local_ffmpeg}")
            
    if local_bin not in os.environ["PATH"]:
        os.environ["PATH"] = local_bin + os.pathsep + os.environ["PATH"]
except Exception as ffmpeg_setup_err:
    print(f"Warning: Failed to setup local FFmpeg binary: {ffmpeg_setup_err}")

# Whisper model caching
whisper_model = None
whisper_model_lock = threading.Lock()

def get_whisper_model():
    global whisper_model
    if whisper_model is None:
        with whisper_model_lock:
            if whisper_model is None:
                import whisper
                print("Loading Whisper model ('base')...")
                whisper_model = whisper.load_model('base')
                print("Whisper model loaded!")
    return whisper_model

GENERATED_DIR = os.path.join(BASE_DIR, "generated_outputs")
GENERATED_VIDEO_NAME = "generated_interview_video.mp4"
NARRATION_TEXT_NAME = "narration_script.txt"
NARRATION_WAV_NAME = "narration.wav"
VIDEO_ONLY_NAME = "generated_interview_video_silent.mp4"
VIDEO_FILE_EXTENSIONS = {
    ".3gp", ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
    ".mpeg", ".mpg", ".mts", ".ts", ".webm", ".wmv",
}
latest_generated_video_name = GENERATED_VIDEO_NAME
video_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="feedback-video")
video_jobs = {}
video_cache = {}
video_jobs_lock = threading.Lock()


def log_performance(label, started_at):
    print(f"[PERF] {label}: {time.perf_counter() - started_at:.2f} seconds")

@lru_cache(maxsize=32)
def get_font(size, bold=False):
    """Use a readable Windows font when available, with a safe fallback."""
    font_names = ["arialbd.ttf" if bold else "arial.ttf", "segoeuib.ttf" if bold else "segoeui.ttf"]
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()

def draw_wrapped_text(draw, text, xy, font, fill, max_width, line_gap=10):
    x, y = xy
    lines = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)

    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y

def extract_focus_items(results):
    criteria = sorted(
        results["criteria_scores"],
        key=lambda item: item["weighted_score"] / item["weight"] if item["weight"] else 0
    )
    return criteria[:2]

def extract_content_points(transcript):
    lower = transcript.lower()
    points = []

    checks = [
        ("name", ["name", "myself", "i am", "i'm"]),
        ("age", ["years old", "age", "year"]),
        ("school or class", ["school", "class", "grade", "studying"]),
        ("family", ["family", "mother", "father", "parents", "brother", "sister"]),
        ("interests", ["hobby", "hobbies", "enjoy", "love", "play", "interest"]),
        ("goal", ["goal", "dream", "ambition", "want to be", "aspire"])
    ]

    for label, keywords in checks:
        if any(keyword in lower for keyword in keywords):
            points.append(label)

    return points or ["personal introduction"]

def build_narration_script(transcript, results):
    points = extract_content_points(transcript)
    focus_items = extract_focus_items(results)
    focus_text = " and ".join(
        f"{item['criterion']} at {item['weighted_score']} out of {item['weight']}"
        for item in focus_items
    )
    wpm = results.get("metadata", {}).get("wpm")
    pace_text = f"The speaking pace is estimated at {wpm:.0f} words per minute." if wpm else "A duration was not provided, so pace can be improved by timing the next attempt."

    return (
        "Here is an explanation of the self introduction submitted for interview practice. "
        f"The content includes {', '.join(points)}. "
        "The introduction gives the listener a quick view of the speaker's background, interests, and readiness to communicate. "
        f"The overall communication score is {results['overall_score']} out of 100. "
        f"{pace_text} "
        f"The main practice focus is {focus_text}. "
        "For the next attempt, the speaker should keep the opening confident, connect personal details smoothly, reduce filler words, and close with a clear thank you. "
        "This generated video can be used as a short coaching explanation before rehearsing again."
    )

def synthesize_narration(script_text, output_wav_path, text_path=None):
    text_path = text_path or os.path.join(GENERATED_DIR, NARRATION_TEXT_NAME)
    with open(text_path, "w", encoding="utf-8") as file:
        file.write(script_text)

    safe_text_path = text_path.replace("'", "''")
    safe_wav_path = output_wav_path.replace("'", "''")

    ps_command = (
        "Add-Type -AssemblyName System.Speech; "
        f"$text = Get-Content -Raw -LiteralPath '{safe_text_path}'; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speaker.Rate = 0; "
        "$speaker.Volume = 100; "
        f"$speaker.SetOutputToWaveFile('{safe_wav_path}'); "
        "$speaker.Speak($text); "
        "$speaker.Dispose();"
    )

    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        ps_command
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)

def get_wav_duration(path):
    with wave.open(path, "rb") as audio:
        return audio.getnframes() / float(audio.getframerate())

def get_audio_file_duration(path):
    # Try using ffmpeg command since it's already set up and guaranteed to support all formats
    try:
        import subprocess
        import re
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        # Run ffmpeg -i path
        cmd = [ffmpeg_exe, "-i", path]
        # ffmpeg prints info to stderr, so we capture stderr
        result = subprocess.run(cmd, capture_output=True, text=True, errors='ignore')
        output = result.stderr
        
        # Look for Duration: hh:mm:ss.xx
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds
    except Exception as e:
        print(f"Warning: ffmpeg duration extraction failed: {e}")

    # Fallback to moviepy
    try:
        from moviepy import AudioFileClip
        clip = AudioFileClip(path)
        duration = clip.duration
        clip.close()
        return duration
    except Exception as e:
        print(f"Warning: moviepy import failed: {e}")
            
    # Try moviepy.editor
    try:
        from moviepy.editor import AudioFileClip
        clip = AudioFileClip(path)
        duration = clip.duration
        clip.close()
        return duration
    except Exception as e:
        print(f"Warning: moviepy.editor import failed: {e}")
            
    # Try using wave (for WAV files)
    try:
        import wave
        with wave.open(path, "rb") as audio:
            return audio.getnframes() / float(audio.getframerate())
    except Exception:
        pass
        
    return None

def draw_score_ring(draw, center, radius, score, progress, fill="#0f766e"):
    start_angle = -90
    end_angle = start_angle + (360 * min(score, 100) / 100) * progress
    bounds = (
        center[0] - radius,
        center[1] - radius,
        center[0] + radius,
        center[1] + radius
    )
    draw.ellipse(bounds, outline="#d9e2ec", width=18)
    draw.arc(bounds, start=start_angle, end=end_angle, fill=fill, width=18)

def create_explainer_frame(script_text, transcript, results, timestamp, duration, size=(1280, 720)):
    width, height = size
    image = Image.new("RGB", size, "#eef4f8")
    draw = ImageDraw.Draw(image)

    header_color = "#17202a"
    accent = "#0f766e"
    blue = "#2563eb"
    yellow = "#f5b942"
    muted = "#657281"
    white = "#ffffff"

    title_font = get_font(42, bold=True)
    body_font = get_font(28)
    small_font = get_font(22)
    label_font = get_font(24, bold=True)
    score_font = get_font(50, bold=True)

    progress = min(timestamp / max(duration, 1), 1)
    wave_offset = int(24 * math.sin(timestamp * 1.4))

    draw.rectangle((0, 0, width, height), fill="#eef4f8")
    draw.polygon(
        [(0, 0), (width, 0), (width, 150 + wave_offset), (0, 235 - wave_offset)],
        fill=header_color
    )
    draw.polygon(
        [(0, height), (width, height), (width, height - 120 + wave_offset), (0, height - 48 - wave_offset)],
        fill="#dfeaf2"
    )

    draw.text((54, 34), "Self-Introduction Feedback", font=title_font, fill=white)
    draw.text((58, 92), "Personalized feedback based on your introduction", font=small_font, fill="#d8e3ef")

    draw.rounded_rectangle((56, 168, 786, 610), radius=8, fill=white, outline="#c8d7e3", width=2)
    draw.rectangle((56, 168, 72, 610), fill=blue)
    draw.text((104, 206), "Introduction Overview", font=label_font, fill=header_color)

    content_points = extract_content_points(transcript)
    point_text = "The speaker covers " + ", ".join(content_points) + "."
    explanation = (
        f"{point_text} The message works best when these ideas are delivered as one clear story: "
        "who the speaker is, what matters to them, and what they are working toward."
    )
    draw_wrapped_text(draw, explanation, (104, 256), body_font, header_color, 636, line_gap=12)

    draw.rounded_rectangle((835, 168, 1226, 414), radius=8, fill=white, outline="#c8d7e3", width=2)
    draw.text((878, 202), "Overall Score", font=label_font, fill=header_color)
    draw_score_ring(draw, (1032, 306), 70, results["overall_score"], min(progress * 1.8, 1))
    score_text = f"{results['overall_score']}/100"
    score_width = draw.textlength(score_text, font=score_font)
    draw.text((1032 - score_width / 2, 278), score_text, font=score_font, fill=accent)

    focus_items = extract_focus_items(results)
    focus_text = "\n".join(
        f"{item['criterion']}: {float(item['weighted_score']):g}/{float(item['weight']):g}"
        for item in focus_items
    )
    draw.rounded_rectangle((835, 438, 1226, 610), radius=8, fill="#fff8e1", outline="#ecd38f", width=2)
    draw.text((878, 470), "Practice Focus", font=label_font, fill=header_color)
    draw_wrapped_text(draw, focus_text, (878, 518), get_font(24), header_color, 300, line_gap=9)

    bar_x, bar_y, bar_w = 56, 660, width - 112
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 10), radius=5, fill="#c8d7e3")
    draw.rounded_rectangle((bar_x, bar_y, bar_x + int(bar_w * progress), bar_y + 10), radius=5, fill=accent)
    draw.text((56, 628), "AI Feedback Video", font=small_font, fill=muted)
    draw.rounded_rectangle((1040, 628, 1226, 674), radius=8, fill=yellow)
    draw.text((1060, 638), "Audio On", font=label_font, fill=header_color)

    return image

def mux_audio_video(video_path, audio_path, output_path):
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg_path,
        "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)

def generate_video_artifact(transcript, results, job_id=None):
    """
    Generate a narrated explainer MP4 from the submitted introduction.
    """
    import shutil

    video_started = time.perf_counter()
    job_id = job_id or uuid.uuid4().hex
    os.makedirs(GENERATED_DIR, exist_ok=True)
    output_name = f"generated_interview_video_{job_id}.mp4"
    video_only_name = f"generated_interview_video_silent_{job_id}.mp4"
    narration_name = f"narration_{job_id}.wav"
    narration_text_name = f"narration_script_{job_id}.txt"
    output_path = os.path.join(GENERATED_DIR, output_name)
    video_only_path = os.path.join(GENERATED_DIR, video_only_name)
    narration_path = os.path.join(GENERATED_DIR, narration_name)
    narration_text_path = os.path.join(GENERATED_DIR, narration_text_name)

    script_text = build_narration_script(transcript, results)

    audio_available = False
    narration_started = time.perf_counter()
    try:
        synthesize_narration(script_text, narration_path, narration_text_path)
        audio_available = os.path.exists(narration_path)
    except Exception as audio_error:
        audio_available = False
        print(f"Warning: narration generation failed: {audio_error}")
    finally:
        log_performance("Narration", narration_started)

    duration = 8
    if audio_available:
        try:
            duration = max(get_wav_duration(narration_path), 8)
        except Exception as duration_error:
            print(f"Warning: failed to read narration duration: {duration_error}")
            duration = 8

    fps = 12
    frame_generation_seconds = 0.0
    encoding_started = time.perf_counter()
    with imageio.get_writer(video_only_path, fps=fps, codec="libx264", quality=8, macro_block_size=16) as writer:
        total_frames = int(duration * fps)
        for frame_index in range(total_frames):
            timestamp = frame_index / fps
            frame_started = time.perf_counter()
            frame = create_explainer_frame(script_text, transcript, results, timestamp, duration)
            frame_generation_seconds += time.perf_counter() - frame_started
            writer.append_data(np.asarray(frame))
    encoding_seconds = time.perf_counter() - encoding_started
    print(f"[PERF] Frame generation: {frame_generation_seconds:.2f} seconds")
    print(f"[PERF] Video encoding: {max(0, encoding_seconds - frame_generation_seconds):.2f} seconds")

    if audio_available:
        mux_started = time.perf_counter()
        try:
            mux_audio_video(video_only_path, narration_path, output_path)
        except Exception as mux_error:
            print(f"Warning: audio muxing failed: {mux_error}")
            shutil.copyfile(video_only_path, output_path)
            audio_available = False
        finally:
            log_performance("Audio/video muxing", mux_started)
    else:
        shutil.copyfile(video_only_path, output_path)

    log_performance("Video generation", video_started)
    return {
        "video_url": f"/generated-video?file={output_name}&ts={int(time.time())}",
        "video_source": "submitted_transcript_explainer",
        "duration_seconds": round(duration, 2),
        "has_audio": audio_available,
        "status": "completed",
        "job_id": job_id
    }


def run_video_job(job_id, cache_key, transcript, results):
    global latest_generated_video_name
    try:
        video_data = generate_video_artifact(transcript, results, job_id)
        with video_jobs_lock:
            latest_generated_video_name = f"generated_interview_video_{job_id}.mp4"
            video_jobs[job_id].update({
                "status": "completed",
                "generated_video": video_data,
                "artifact_path": os.path.join(GENERATED_DIR, f"generated_interview_video_{job_id}.mp4")
            })
    except Exception as video_error:
        print(f"[VIDEO] Generation failed for job {job_id}: {video_error}")
        with video_jobs_lock:
            video_jobs[job_id].update({"status": "failed", "error": str(video_error)})
            if video_cache.get(cache_key) == job_id:
                video_cache.pop(cache_key, None)


def queue_video_generation(transcript, results):
    cache_payload = json.dumps(
        {"transcript": transcript, "results": results},
        sort_keys=True,
        ensure_ascii=True,
        default=str
    )
    cache_key = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()

    with video_jobs_lock:
        existing_job_id = video_cache.get(cache_key)
        if existing_job_id:
            existing_job = video_jobs.get(existing_job_id)
            if existing_job and existing_job["status"] == "processing":
                return {"status": "processing", "job_id": existing_job_id}
            if (existing_job and existing_job["status"] == "completed"
                    and os.path.isfile(existing_job["artifact_path"])):
                return deepcopy(existing_job["generated_video"])

        job_id = uuid.uuid4().hex
        video_jobs[job_id] = {"status": "processing"}
        video_cache[cache_key] = job_id
        video_executor.submit(run_video_job, job_id, cache_key, transcript, deepcopy(results))

    return {"status": "processing", "job_id": job_id}

@app.route('/', methods=['GET'])
@app.route('/index.html', methods=['GET'])
def home():
    """Serve the frontend."""
    return send_from_directory(BASE_DIR, 'index.html')


@app.before_request
def start_request_timer():
    if request.path in ("/api/score", "/api/score-audio"):
        request.environ["perf_started_at"] = time.perf_counter()


@app.after_request
def log_request_time(response):
    started_at = request.environ.get("perf_started_at")
    if started_at is not None:
        log_performance("API request", started_at)
        log_performance("Total", started_at)
    return response


@app.route('/api', methods=['GET'])
def api_info():
    """API information endpoint."""
    return jsonify({
        "message": "Communication Skills Scoring API",
        "version": "1.0",
        "endpoints": {
            "/api/score": "POST - Score a transcript",
            "/api/rubrics": "GET - Get rubrics",
            "/api/sample": "GET - Get sample transcript"
        }
    })

@app.route('/generated-video', methods=['GET'])
def generated_video():
    """Serve a generated video, retaining the legacy latest-video URL."""
    with video_jobs_lock:
        latest_filename = latest_generated_video_name
    filename = request.args.get("file", latest_filename)
    if (filename != GENERATED_VIDEO_NAME
            and not re.fullmatch(r"generated_interview_video_[0-9a-f]{32}\.mp4", filename)):
        return jsonify({"error": "Video not found."}), 404
    return send_from_directory(GENERATED_DIR, filename)


@app.route('/api/video-status/<job_id>', methods=['GET'])
def video_status(job_id):
    with video_jobs_lock:
        job = video_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Video job not found."}), 404
        response = {"status": job["status"], "job_id": job_id}
        if job["status"] == "completed":
            response["generated_video"] = deepcopy(job["generated_video"])
        elif job["status"] == "failed":
            response["error"] = "Feedback generated successfully, but the video could not be generated."
    return jsonify(response), 200

@app.route('/api/score', methods=['POST'])
def score_transcript():
    """
    Score a transcript
    Request body: {"transcript": "text to score"}
    """
    try:
        data = request.get_json()
        
        if not data or 'transcript' not in data:
            return jsonify({
                "error": "Missing transcript in request body"
            }), 400
        
        transcript = data['transcript'].strip()
        
        if not transcript:
            return jsonify({
                "error": "Transcript cannot be empty"
            }), 400
        
        scoring_started = time.perf_counter()
        results = scorer.calculate_score(transcript)
        log_performance("Scoring", scoring_started)
        results["generated_video"] = queue_video_generation(transcript, results)
        
        return jsonify(results), 200
    
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as e:
        return jsonify({
            "error": f"Error scoring transcript: {str(e)}"
        }), 500

@app.route('/api/rubrics', methods=['GET'])
def get_rubrics():
    """Get the rubrics structure"""
    return jsonify(rubrics), 200

@app.route('/api/sample', methods=['GET'])
def get_sample():
    """Get sample transcript"""
    sample = parser.get_sample_transcript()
    return jsonify({
        "transcript": sample,
        "description": "Sample self-introduction transcript"
    }), 200

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

@app.route('/api/score-audio', methods=['POST'])
def score_audio():
    """Score an uploaded self-introduction audio by converting speech to text (Whisper).

        Request (multipart/form-data):
            - audio: required audio file
    """
    try:
        if 'audio' not in request.files:
            return jsonify({"error": "Missing audio file in form-data. Field name must be 'audio'."}), 400

        audio_file = request.files['audio']
        if not audio_file or not audio_file.filename:
            return jsonify({"error": "Audio filename is empty."}), 400

        filename = secure_filename(audio_file.filename)
        extension = os.path.splitext(filename)[1].lower()
        if audio_file.mimetype.lower().startswith("video/") or extension in VIDEO_FILE_EXTENSIONS:
            return jsonify({"error": "Video uploads are not supported. Please upload an audio file."}), 400

        os.makedirs(GENERATED_DIR, exist_ok=True)
        unique_prefix = uuid.uuid4().hex
        saved_audio_path = os.path.join(GENERATED_DIR, f"upload_{unique_prefix}_{filename}")
        audio_file.save(saved_audio_path)

        if not os.path.exists(saved_audio_path):
            return jsonify({"error": "Upload save failed; saved file not found on server.", "path": saved_audio_path}), 500


        saved_audio_abs = os.path.abspath(saved_audio_path)
        duration_started = time.perf_counter()
        detected_duration = get_audio_file_duration(saved_audio_abs)
        if detected_duration is not None:
            try:
                detected_duration = round(normalize_duration(detected_duration), 2)
            except ValueError:
                detected_duration = None
        log_performance("Audio duration detection", duration_started)

        # Transcribe with Whisper (using the global cached model).
        try:
            model = get_whisper_model()
        except Exception as e:
            print(f"[WHISPER] Model load failed: {e}")
            return jsonify({"error": "Unable to transcribe the uploaded audio. Please try another recording."}), 500

        transcription_started = time.perf_counter()
        try:
            transcript_result = model.transcribe(saved_audio_abs, fp16=False)
        except Exception as e:
            log_performance("Transcription", transcription_started)
            print(f"[WHISPER] Transcription failed: {e}")
            return jsonify({"error": "Unable to transcribe the uploaded audio. Please try another recording."}), 400
        log_performance("Transcription", transcription_started)

        transcript = (transcript_result.get('text') or '').strip()

        if not transcript:
            return jsonify({"error": "Unable to transcribe the uploaded audio. Please try another recording."}), 400

        scoring_started = time.perf_counter()
        results = scorer.calculate_score(transcript, detected_duration)
        log_performance("Scoring", scoring_started)
        results['transcript_extracted'] = transcript
        results['audio_duration_detected'] = detected_duration
        results["generated_video"] = queue_video_generation(transcript, results)

        return jsonify(results), 200

    except Exception as e:
        return jsonify({"error": f"Error scoring uploaded audio: {str(e)}"}), 500

if __name__ == '__main__':

    print("\n" + "="*80)
    print("Starting Communication Skills Scoring API...")
    print("API will be available at: http://localhost:5000")
    print("="*80 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
