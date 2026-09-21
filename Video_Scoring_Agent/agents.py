import os
import whisper
from moviepy import VideoFileClip
from scoring_engine import ScoringEngine
from rubric_parser import RubricParser
import json

class Agent:
    def __init__(self, name):
        self.name = name

    def log(self, message):
        print(f"[{self.name}] {message}")

BASE_DIR = os.path.dirname(__file__)


class VideoProcessorAgent(Agent):
    def __init__(self):
        super().__init__("VideoProcessor")

    def extract_audio(self, video_path, output_audio_path=None):
        """Extract audio to a deterministic absolute temp path.

        Using absolute paths avoids WinError 2 when the working directory differs
        between extraction and transcription.
        """
        self.log(f"Processing video: {video_path}")
        try:
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")

            video = VideoFileClip(video_path)
            self.log(f"Video duration: {video.duration} seconds")

            output_dir = os.path.join(BASE_DIR, "generated_outputs")
            os.makedirs(output_dir, exist_ok=True)

            if output_audio_path is None:
                # Unique filename per run to avoid stale/missing files.
                output_audio_path = os.path.join(
                    output_dir, f"temp_audio_{int(video.duration * 1000)}.mp3"
                )

            # Ensure absolute path (helps when main.py is launched from elsewhere)
            if not os.path.isabs(output_audio_path):
                output_audio_path = os.path.abspath(output_audio_path)

            # Write audio to the desired path and verify it exists.
            video.audio.write_audiofile(output_audio_path, logger=None)

            if not os.path.exists(output_audio_path):
                raise FileNotFoundError(
                    "Audio extraction failed; file not found after write: "
                    f"{output_audio_path} (abs: {os.path.abspath(output_audio_path)})"
                )

            self.log(f"Audio extracted to: {output_audio_path}")
            return output_audio_path, video.duration
        except Exception as e:
            self.log(f"Error extracting audio: {str(e)}")
            raise



class TranscriptionAgent(Agent):
    def __init__(self, model_size="base"):
        super().__init__("Transcriber")
        self.log(f"Loading Whisper model ({model_size})...")
        self.model = whisper.load_model(model_size)
        self.log("Model loaded.")

    def transcribe(self, audio_path):
        # Always normalize to absolute path for better diagnostics
        audio_path_abs = os.path.abspath(audio_path)
        self.log(f"Transcribing audio: {audio_path_abs}")

        # Fail fast with a clear error if the extracted file isn't actually present.
        if not os.path.exists(audio_path_abs):
            raise FileNotFoundError(
                f"Audio file not found for transcription: {audio_path_abs} (exists={os.path.exists(audio_path_abs)})"
            )

        result = self.model.transcribe(audio_path_abs)
        transcript = result["text"]
        self.log("Transcription complete.")
        return transcript



class ScoringAgent(Agent):
    def __init__(self):
        super().__init__("Scorer")
        self.parser = RubricParser()
        self.rubrics = self.parser.get_rubrics()
        self.engine = ScoringEngine(self.rubrics)

    def score_transcript(self, transcript, duration):
        self.log("Scoring transcript based on rubrics...")
        results = self.engine.calculate_score(transcript, duration_seconds=duration)
        self.log(f"Scoring complete. Overall Score: {results['overall_score']}")
        return results

class ReportingAgent(Agent):
    def __init__(self):
        super().__init__("Reporter")

    def generate_report(self, results, transcript):
        self.log("Generating final report...")
        
        report = []
        report.append("="*60)
        report.append("VIDEO ANALYSIS REPORT")
        report.append("="*60)
        report.append(f"\nTRANSCRIPT:\n{transcript.strip()}\n")
        report.append("-" * 60)
        report.append(f"OVERALL SCORE: {results['overall_score']}/100")
        report.append("-" * 60)
        
        report.append("\nDETAILED BREAKDOWN:")
        for criterion in results['criteria_scores']:
            report.append(f"\n{criterion['criterion']} (Weight: {criterion['weight']}%)")
            report.append(f"Score: {criterion['weighted_score']}/{criterion['weight']}")
            
            for metric in criterion['metrics']:
                report.append(f"  - {metric['metric']}: {metric['score']}/{metric['max_score']}")
                report.append(f"    Feedback: {metric['feedback']}")
                
        report.append("\n" + "="*60)
        
        final_report = "\n".join(report)
        print(final_report)
        
        # Save to file
        with open("analysis_report.txt", "w", encoding="utf-8") as f:
            f.write(final_report)
        
        self.log("Report saved to analysis_report.txt")
        return final_report
