import requests
from pathlib import Path

url = 'http://localhost:5000/api/score-audio'

audio_path = Path('Video_Scoring_Agent/sample_video.mp4')
# Endpoint expects audio file; for a quick test we still send mp4.
# Whisper can often handle video too; if not, convert to wav in your environment.

with audio_path.open('rb') as f:
    files = {'audio': (audio_path.name, f, 'video/mp4')}
    data = {'duration_seconds': '52'}
    r = requests.post(url, files=files, data=data)

print('status:', r.status_code)
print(r.text[:800])

