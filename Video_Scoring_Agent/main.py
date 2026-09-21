import os
import sys

# Setup local FFmpeg binary dynamically for Whisper and other subprocesses
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agents import VideoProcessorAgent, TranscriptionAgent, ScoringAgent, ReportingAgent

def create_dummy_video(filename="sample_video.mp4"):
    """Creates a dummy video with a self-introduction audio for testing."""
    # Lazy imports — moviepy and gTTS are only needed when creating a dummy video,
    # not during the normal video-scoring flow.
    try:
        from moviepy import ColorClip, AudioFileClip
        from gtts import gTTS
    except ImportError as imp_err:
        print(f"[create_dummy_video] Missing dependency: {imp_err}")
        print("Run: pip install moviepy gTTS")
        raise
    print("Creating dummy video for demonstration...")
    
    # Sample text from the case study
    text = """Hello everyone, myself Muskan, studying in class 8th B section from Christ Public School. 
    I am 13 years old. I live with my family. There are 3 people in my family, me, my mother and my father.
    One special thing about my family is that they are very kind hearted to everyone and soft spoken. 
    One thing I really enjoy is play, playing cricket and taking wickets.
    A fun fact about me is that I see in mirror and talk by myself. 
    One thing people don't know about me is that I once stole a toy from one of my cousin.
    My favorite subject is science because it is very interesting. 
    Through science I can explore the whole world and make the discoveries and improve the lives of others. 
    Thank you for listening."""
    
    # Generate audio
    tts = gTTS(text=text, lang='en')
    tts.save("temp_tts.mp3")
    
    # Create video
    audio = AudioFileClip("temp_tts.mp3")
    clip = ColorClip(size=(640, 480), color=(0, 0, 255), duration=audio.duration)
    
    # Add text (optional, might fail if ImageMagick not installed, so skipping text on video for safety)
    # txt_clip = TextClip("Self Introduction", fontsize=70, color='white')
    # txt_clip = txt_clip.set_pos('center').set_duration(audio.duration)
    # video = CompositeVideoClip([clip, txt_clip])
    
    video = clip.with_audio(audio)
    video.write_videofile(filename, fps=24, logger=None)
    
    # Cleanup
    os.remove("temp_tts.mp3")
    print(f"Dummy video created: {filename}")
    return filename

def main():
    print("Initializing Video Scoring System (Agentic Architecture)...")
    
    # Check for video file
    video_path = "sample_video.mp4"
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
    
    if not os.path.exists(video_path):
        try:
            create_dummy_video(video_path)
        except Exception as e:
            print(f"Could not create dummy video: {e}")
            print("Please provide a video file path as an argument.")
            return

    # Initialize Agents
    video_agent = VideoProcessorAgent()
    transcriber_agent = TranscriptionAgent()
    scoring_agent = ScoringAgent()
    reporting_agent = ReportingAgent()

    try:
        # 1. Extract Audio
        audio_path, duration = video_agent.extract_audio(video_path)

        # 2. Transcribe
        transcript = transcriber_agent.transcribe(audio_path)

        # 3. Score
        results = scoring_agent.score_transcript(transcript, duration)

        # 4. Report
        reporting_agent.generate_report(results, transcript)

        # Cleanup
        if os.path.exists(audio_path):
            os.remove(audio_path)
            print(f"[System] Cleaned up temporary file: {audio_path}")

    except Exception as e:
        print(f"\n[ERROR] An error occurred during the process: {str(e)}")

if __name__ == "__main__":
    main()
