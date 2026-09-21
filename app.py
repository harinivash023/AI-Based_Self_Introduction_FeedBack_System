"""
Flask REST API for Communication Skills Scoring
"""
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

from flask_cors import CORS
from rubric_parser import RubricParser
from scoring_engine import ScoringEngine
import math
import os
import re
import subprocess
import time
import wave
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

def get_whisper_model():
    global whisper_model
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

def synthesize_narration(script_text, output_wav_path):
    text_path = os.path.join(GENERATED_DIR, NARRATION_TEXT_NAME)
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

    draw.text((54, 34), "Interview Coaching Explanation", font=title_font, fill=white)
    draw.text((58, 92), "Generated from the submitted self-introduction", font=small_font, fill="#d8e3ef")

    draw.rounded_rectangle((56, 168, 786, 610), radius=8, fill=white, outline="#c8d7e3", width=2)
    draw.rectangle((56, 168, 72, 610), fill=blue)
    draw.text((104, 206), "What this introduction communicates", font=label_font, fill=header_color)

    content_points = extract_content_points(transcript)
    point_text = "The speaker covers " + ", ".join(content_points) + "."
    explanation = (
        f"{point_text} The message works best when these ideas are delivered as one clear story: "
        "who the speaker is, what matters to them, and what they are working toward."
    )
    draw_wrapped_text(draw, explanation, (104, 256), body_font, header_color, 636, line_gap=12)

    draw.rounded_rectangle((835, 168, 1226, 414), radius=8, fill=white, outline="#c8d7e3", width=2)
    draw.text((878, 202), "Readiness score", font=label_font, fill=header_color)
    draw_score_ring(draw, (1032, 306), 70, results["overall_score"], min(progress * 1.8, 1))
    score_text = f"{results['overall_score']}/100"
    score_width = draw.textlength(score_text, font=score_font)
    draw.text((1032 - score_width / 2, 278), score_text, font=score_font, fill=accent)

    focus_items = extract_focus_items(results)
    focus_text = "Practice focus: " + "; ".join(
        f"{item['criterion']} {item['weighted_score']}/{item['weight']}"
        for item in focus_items
    )
    draw.rounded_rectangle((835, 438, 1226, 610), radius=8, fill="#fff8e1", outline="#ecd38f", width=2)
    draw.text((878, 470), "Next rehearsal", font=label_font, fill=header_color)
    draw_wrapped_text(draw, focus_text, (878, 518), get_font(24), header_color, 300, line_gap=9)

    bar_x, bar_y, bar_w = 56, 660, width - 112
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 10), radius=5, fill="#c8d7e3")
    draw.rounded_rectangle((bar_x, bar_y, bar_x + int(bar_w * progress), bar_y + 10), radius=5, fill=accent)
    draw.text((56, 628), "Narrated coaching video with audio", font=small_font, fill=muted)
    draw.rounded_rectangle((1040, 628, 1226, 674), radius=8, fill=yellow)
    draw.text((1060, 638), "Audio enabled", font=label_font, fill=header_color)

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

def generate_video_artifact(transcript, results):
    """
    Generate a narrated explainer MP4 from the submitted introduction.
    """
    import shutil

    os.makedirs(GENERATED_DIR, exist_ok=True)
    output_path = os.path.join(GENERATED_DIR, GENERATED_VIDEO_NAME)
    video_only_path = os.path.join(GENERATED_DIR, VIDEO_ONLY_NAME)
    narration_path = os.path.join(GENERATED_DIR, NARRATION_WAV_NAME)

    script_text = build_narration_script(transcript, results)

    audio_available = False
    try:
        synthesize_narration(script_text, narration_path)
        audio_available = os.path.exists(narration_path)
    except Exception as audio_error:
        audio_available = False
        print(f"Warning: narration generation failed: {audio_error}")

    duration = 8
    if audio_available:
        try:
            duration = max(get_wav_duration(narration_path), 8)
        except Exception as duration_error:
            print(f"Warning: failed to read narration duration: {duration_error}")
            duration = 8

    fps = 24
    with imageio.get_writer(video_only_path, fps=fps, codec="libx264", quality=8, macro_block_size=16) as writer:
        total_frames = int(duration * fps)
        for frame_index in range(total_frames):
            timestamp = frame_index / fps
            frame = create_explainer_frame(script_text, transcript, results, timestamp, duration)
            writer.append_data(np.asarray(frame))

    if audio_available:
        try:
            mux_audio_video(video_only_path, narration_path, output_path)
        except Exception as mux_error:
            print(f"Warning: audio muxing failed: {mux_error}")
            shutil.copyfile(video_only_path, output_path)
            audio_available = False
    else:
        shutil.copyfile(video_only_path, output_path)

    return {
        "video_url": f"/generated-video?ts={int(time.time())}",
        "video_source": "submitted_transcript_explainer",
        "duration_seconds": round(duration, 2),
        "has_audio": audio_available
    }

@app.route('/', methods=['GET'])
@app.route('/index.html', methods=['GET'])
def home():
    """Serve the frontend."""
    return send_from_directory('.', 'index.html')

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
    """Serve the latest video generated by the score action."""
    return send_from_directory(GENERATED_DIR, GENERATED_VIDEO_NAME)

@app.route('/api/score', methods=['POST'])
def score_transcript():
    """
    Score a transcript
    Request body:
    {
        "transcript": "text to score",
        "duration_seconds": 60 (optional)
    }
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
        
        duration_seconds = data.get('duration_seconds', None)
        
        # Score the transcript
        results = scorer.calculate_score(transcript, duration_seconds)
        
        try:
            results["generated_video"] = generate_video_artifact(transcript, results)
        except Exception as video_error:
            results["generated_video"] = None
            results["video_error"] = str(video_error)
            print(f"Warning: video generation failed: {video_error}")
        
        return jsonify(results), 200
    
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
      - duration_seconds: optional number (for WPM)
    """
    try:
        if 'audio' not in request.files:
            return jsonify({"error": "Missing audio file in form-data. Field name must be 'audio'."}), 400

        audio_file = request.files['audio']
        if not audio_file or not audio_file.filename:
            return jsonify({"error": "Audio filename is empty."}), 400

        duration_seconds_raw = request.form.get('duration_seconds', None)
        manual_duration = None
        if duration_seconds_raw:
            try:
                manual_duration = float(duration_seconds_raw)
            except ValueError:
                return jsonify({"error": "duration_seconds must be a number."}), 400

        os.makedirs(GENERATED_DIR, exist_ok=True)
        filename = secure_filename(audio_file.filename)
        unique_prefix = str(int(time.time() * 1000))
        saved_audio_path = os.path.join(GENERATED_DIR, f"upload_{unique_prefix}_{filename}")
        audio_file.save(saved_audio_path)

        if not os.path.exists(saved_audio_path):
            return jsonify({"error": "Upload save failed; saved file not found on server.", "path": saved_audio_path}), 500


        # Transcribe with Whisper (using global cached model)
        try:
            model = get_whisper_model()
        except Exception as e:
            return jsonify({"error": f"Whisper model failed to load. Details: {str(e)}"}), 500

        saved_audio_abs = os.path.abspath(saved_audio_path)
        transcript_result = model.transcribe(saved_audio_abs, fp16=False)

        transcript = (transcript_result.get('text') or '').strip()

        # Auto-detect duration from the uploaded audio file itself
        detected_duration = get_audio_file_duration(saved_audio_abs)
        
        # Fallback to Whisper segment timestamps if file duration extraction failed
        if detected_duration is None:
            segments = transcript_result.get('segments') or []
            if segments:
                detected_duration = round(segments[-1]['end'], 2)
        else:
            detected_duration = round(detected_duration, 2)

        # Priority: manual override > detected > None
        duration_seconds = manual_duration if manual_duration is not None else detected_duration

        if not transcript:
            return jsonify({"error": "Transcription returned empty text."}), 400

        results = scorer.calculate_score(transcript, duration_seconds)
        results['transcript_extracted'] = transcript
        results['audio_duration_detected'] = detected_duration

        try:
            results["generated_video"] = generate_video_artifact(transcript, results)
        except Exception as video_error:
            results["generated_video"] = None
            results["video_error"] = str(video_error)
            print(f"Warning: video generation failed: {video_error}")

        return jsonify(results), 200

    except Exception as e:
        return jsonify({"error": f"Error scoring uploaded audio: {str(e)}"}), 500

if __name__ == '__main__':

    print("\n" + "="*80)
    print("Starting Communication Skills Scoring API...")
    print("API will be available at: http://localhost:5000")
    print("="*80 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
