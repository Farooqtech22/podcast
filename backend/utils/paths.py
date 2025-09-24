import os, re
from pathlib import Path
import dotenv

# Load .env from the backend directory (where this file's parent directory contains .env)
env_path = Path(__file__).parent.parent / '.env'  # backend/.env
dotenv.load_dotenv(env_path)

BASE_DATA_DIR = Path(os.getenv("BASE_DATA_DIR", "../data")).resolve()
SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# Debug: Print the resolved path (remove after confirming it works)
print(f"BASE_DATA_DIR resolved to: {BASE_DATA_DIR}")

def safe_name(name: str) -> str:
    return SAFE_CHARS.sub("_", name).strip("_")

def podcast_dir(name: str) -> Path:
    p = BASE_DATA_DIR / safe_name(name)
    (p / "episodes").mkdir(parents=True, exist_ok=True)
    return p

def episode_paths(podcast: str, guid: str, title: str):
    base = podcast_dir(podcast) / "episodes"
    stem = safe_name((guid or title) or "episode")[:120]
    return {
        "audio": base / f"{stem}.mp3",
        "audio_part": base / f"{stem}.mp3.part",
        "raw": base / f"{stem}_raw.txt",
        "clean": base / f"{stem}_clean.txt",
        "meta": base / f"{stem}.meta.json",
    }

def podcast_artifacts(podcast: str):
    base = podcast_dir(podcast)
    return {
        "pdf": base / f"{safe_name(podcast)}.pdf",
        "persona": base / "persona.json",
        "faiss": base / "embeddings.faiss",
        "faiss_meta": base / "embeddings_meta.json",
        "manifest": base / "manifest.json",
        "lock": base / ".processing.lock",
    }