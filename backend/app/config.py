from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # storage
    database_url: str = "sqlite:///./data/qadam.db"
    recordings_dir: str = "./data/recordings"
    cors_origins: str = "http://localhost:5173"
    seed_demo: bool = True

    # speech-to-text (faster-whisper)
    whisper_model: str = "small"  # tiny | base | small | medium | large-v3
    whisper_device: str = "cpu"  # cpu | cuda
    whisper_compute_type: str = "int8"  # int8 on CPU, float16 on GPU
    whisper_language: str = ""  # "" = auto-detect, or "ru", "kk", "en"...

    # NLP step: "placeholder" (rules) | "llm" (self-hosted model, falls back to rules) | "none"
    drafter: str = "placeholder"
    # LLM drafter: any OpenAI-compatible server (llama.cpp `llama-server`, Ollama /v1).
    llm_base_url: str = "http://localhost:8080/v1"
    llm_model: str = "qwen"  # llama-server ignores it, Ollama needs the pulled tag (e.g. "qwen3:1.7b")
    llm_mode: str = "extract"  # refine | extract | full, see services/llm_drafting.py
    llm_timeout_sec: float = 120  # per request; one CPU core is slow
    llm_max_tokens: int = 400

    # LiveKit (audio calls). url = what the BROWSER connects to, api_url = what the BACKEND calls.
    livekit_url: str = "ws://localhost:7880"
    livekit_api_url: str = "http://localhost:7880"
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # auth. Empty jwt_secret = random per process (fine for dev, logs everyone out on restart).
    jwt_secret: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cookie_secure: bool = False  # set true behind HTTPS
    bcrypt_rounds: int = 12
    # Bootstrap admin, created on startup if no user has this email.
    admin_email: str = ""
    admin_password: str = ""
    admin_name: str = "Администратор"
    # Password of the seeded demo users (SEED_DEMO=true).
    demo_password: str = "qadam-demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
