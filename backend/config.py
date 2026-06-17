import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
FRAMES_DIR = DATA_DIR / "frames"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
UPLOADS_DIR = DATA_DIR / "uploads"
VIDEO_INDEXES_DIR = DATA_DIR / "video_indexes"
DB_PATH = DATA_DIR / "videos.db"
STATIC_DIR = PROJECT_ROOT / "static"

for d in [DATA_DIR, FRAMES_DIR, TRANSCRIPTS_DIR, UPLOADS_DIR, VIDEO_INDEXES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")

FRAME_INTERVAL_SEC = int(os.getenv("FRAME_INTERVAL_SEC", "30"))
FRAME_MAX_COUNT = int(os.getenv("FRAME_MAX_COUNT", "60"))
FRAME_SCALE = int(os.getenv("FRAME_SCALE", "1280"))
FRAME_QUALITY = int(os.getenv("FRAME_QUALITY", "3"))

VIDEO_INDEX_CHUNK_SECONDS = int(os.getenv("VIDEO_INDEX_CHUNK_SECONDS", "720"))
VIDEO_INDEX_MAX_FRAMES_PER_CHUNK = int(os.getenv("VIDEO_INDEX_MAX_FRAMES_PER_CHUNK", "6"))
VIDEO_INDEX_CHAT_CONTEXT_CHARS = int(os.getenv("VIDEO_INDEX_CHAT_CONTEXT_CHARS", "16000"))

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", "2048"))
UPLOAD_ALLOWED_EXT = frozenset({
    ".txt", ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".mkv", ".ogg", ".flac"
})

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
