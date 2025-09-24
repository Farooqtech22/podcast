import os
import time
import requests
import shutil
from pathlib import Path
from typing import Optional
from tqdm import tqdm
from requests.adapters import HTTPAdapter, Retry
from backend.utils.paths import episode_paths
from backend.utils.state import update_episode_state, episode_done_at_least

CHUNK = 1 << 16  # 64KB
MAX_RETRIES = 3
TIMEOUT = 30
MIN_FILE_SIZE = 1024  # 1KB minimum for valid audio file

# Setup session with retry strategy
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("http://", adapter)
session.mount("https://", adapter)

def download_episode(podcast: str, guid: str, title: str, audio_url: str) -> Optional[Path]:
    """Download podcast episode with resume support and error handling."""
    
    # Check if already downloaded
    if episode_done_at_least(podcast, guid, "downloaded"):
        existing_path = episode_paths(podcast, guid, title)["audio"]
        if existing_path.exists() and existing_path.stat().st_size > MIN_FILE_SIZE:
            return existing_path
        # If file is corrupted or too small, re-download
        print(f"[INFO] Re-downloading corrupted file for {title[:40]}...")

    # Validate inputs
    if not audio_url or not audio_url.startswith(('http://', 'https://')):
        raise ValueError(f"Invalid audio URL: {audio_url}")
    
    # Setup paths
    paths = episode_paths(podcast, guid, title)
    audio, part = paths["audio"], paths["audio_part"]
    audio.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Check available disk space
        _check_disk_space(audio.parent)
        
        # Handle resume
        resume_from = 0
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        if part.exists():
            resume_from = part.stat().st_size
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"
                print(f"[INFO] Resuming download from {resume_from / 1024 / 1024:.1f} MB")

        # Start download with retries
        for attempt in range(MAX_RETRIES):
            try:
                print(f"[INFO] Downloading: {title[:50]}..." + ("" if len(title) <= 50 else "..."))
                
                with session.get(
                    audio_url, 
                    headers=headers, 
                    stream=True, 
                    timeout=TIMEOUT,
                    allow_redirects=True
                ) as response:
                    
                    response.raise_for_status()
                    
                    # Handle resume responses
                    if resume_from > 0 and response.status_code not in [206, 200]:
                        print("[WARN] Server doesn't support resume, starting fresh download")
                        resume_from = 0
                        headers.pop("Range", None)
                        continue
                    
                    # Get total size
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        total_size = int(content_length)
                        if resume_from > 0 and response.status_code == 206:
                            # For partial content, add the resume position
                            total_size += resume_from
                    else:
                        total_size = resume_from  # Unknown total size
                        print("[WARN] Content-Length not provided by server")
                    
                    # Download with progress bar
                    mode = "ab" if resume_from > 0 and response.status_code == 206 else "wb"
                    if mode == "wb" and part.exists():
                        part.unlink()  # Remove partial file if starting fresh
                        resume_from = 0
                    
                    with open(part, mode) as f, tqdm(
                        total=total_size,
                        initial=resume_from,
                        unit="B",
                        unit_scale=True,
                        desc=f"📥 {title[:40]}" + ("..." if len(title) > 40 else "")
                    ) as pbar:
                        
                        downloaded_this_session = 0
                        for chunk in response.iter_content(chunk_size=CHUNK):
                            if not chunk:
                                continue
                                
                            f.write(chunk)
                            chunk_size = len(chunk)
                            pbar.update(chunk_size)
                            downloaded_this_session += chunk_size
                            
                            # Check for stalled download
                            if downloaded_this_session % (CHUNK * 100) == 0:  # Every ~6MB
                                f.flush()
                        
                        # Ensure data is written to disk
                        f.flush()
                        os.fsync(f.fileno())
                
                # Verify download
                final_size = part.stat().st_size
                if final_size < MIN_FILE_SIZE:
                    raise ValueError(f"Downloaded file too small: {final_size} bytes")
                
                print(f"[SUCCESS] Downloaded {final_size / 1024 / 1024:.1f} MB")
                break
                
            except (requests.RequestException, OSError, ValueError) as e:
                print(f"[ERROR] Download attempt {attempt + 1} failed: {str(e)}")
                if attempt == MAX_RETRIES - 1:
                    raise RuntimeError(f"Download failed after {MAX_RETRIES} attempts: {str(e)}")
                
                # Wait before retry
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"[INFO] Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                
                # Reset headers for retry
                if "Range" in headers and part.exists():
                    resume_from = part.stat().st_size
                    headers["Range"] = f"bytes={resume_from}-"

        # Safely rename partial file to final name
        _safe_file_rename(part, audio)
        
        # Verify final file
        if not audio.exists() or audio.stat().st_size < MIN_FILE_SIZE:
            raise RuntimeError("Final audio file is missing or corrupted")

        # Update episode state
        update_episode_state(
            podcast,
            guid,
            title=title,
            audio_url=audio_url,
            status="downloaded",
            files={"audio": str(audio)}
        )
        
        print(f"[SUCCESS] Episode downloaded: {audio.name}")
        return audio

    except Exception as e:
        # Cleanup on failure
        _cleanup_failed_download(part, audio)
        print(f"[ERROR] Download failed for {title[:40]}: {str(e)}")
        raise

def _check_disk_space(path: Path, min_space_gb: float = 0.5):
    """Check if there's enough disk space for download."""
    try:
        free_space = shutil.disk_usage(path).free
        min_space_bytes = min_space_gb * 1024 * 1024 * 1024
        
        if free_space < min_space_bytes:
            raise OSError(f"Insufficient disk space. Available: {free_space / 1024**3:.1f} GB, Required: {min_space_gb} GB")
    except Exception as e:
        print(f"[WARN] Could not check disk space: {e}")

def _safe_file_rename(source: Path, destination: Path, max_attempts: int = 5):
    """Safely rename file with retries for locked files."""
    for attempt in range(max_attempts):
        try:
            if destination.exists():
                destination.unlink()  # Remove existing file
            source.replace(destination)
            return
        except PermissionError as e:
            if attempt == max_attempts - 1:
                raise PermissionError(f"Could not rename {source} -> {destination}: {e}")
            print(f"[WARN] File busy, retrying rename in {attempt + 1}s (attempt {attempt + 1}/{max_attempts})")
            time.sleep(attempt + 1)  # Progressive delay

def _cleanup_failed_download(part_file: Path, audio_file: Path):
    """Clean up files after failed download."""
    try:
        if part_file.exists():
            part_file.unlink()
        if audio_file.exists() and audio_file.stat().st_size < MIN_FILE_SIZE:
            audio_file.unlink()
    except Exception as e:
        print(f"[WARN] Could not cleanup files: {e}")