import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME = "AI Video Factory"

    # R2 / S3 Config
    R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY", "")
    R2_SECRET_KEY = os.getenv("R2_SECRET_KEY", "")
    R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "")
    R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

    # Redis / Celery
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # API Keys
    PLENXAI_API_KEY = os.getenv("PLENXAI_API_KEY", "")
    PLENXAI_JWT_TOKEN = os.getenv("PLENXAI_JWT_TOKEN", "")
    PLENXAI_BASE_URL = os.getenv("PLENXAI_BASE_URL", "https://plenxai.com")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ai_video_factory.db")

    # TTS
    TTS_VOICE = os.getenv("TTS_VOICE", "vi-VN-HoaiMyNeural")

    # Temp directory for processing
    TEMP_DIR = os.getenv("TEMP_DIR", "tmp_processing")

    # Video defaults
    DEFAULT_VIDEO_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", "kling-3.0")
    DEFAULT_VIDEO_MODE = os.getenv("DEFAULT_VIDEO_MODE", "i2v")
    DEFAULT_VIDEO_QUALITY = os.getenv("DEFAULT_VIDEO_QUALITY", "1080p")
    DEFAULT_VIDEO_DURATION = int(os.getenv("DEFAULT_VIDEO_DURATION", "5"))
    DEFAULT_ASPECT_RATIO = os.getenv("DEFAULT_ASPECT_RATIO", "9:16")

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "credentials.json")

settings = Settings()
