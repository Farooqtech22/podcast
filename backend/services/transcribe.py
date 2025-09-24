import os
import time
import requests
import ssl
import urllib3
from pathlib import Path
from requests.adapters import HTTPAdapter, Retry
from ..utils.paths import episode_paths
from ..utils.state import update_episode_state, episode_done_at_least, load_manifest

# Completely disable SSL warnings and verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    urllib3.disable_warnings(urllib3.exceptions.SubjectAltNameWarning)
    urllib3.disable_warnings(urllib3.exceptions.InsecurePlatformWarning)
except AttributeError:
    # These warnings don't exist in all urllib3 versions
    pass

# AssemblyAI API settings
A_KEY = os.getenv("ASSEMBLYAI_API_KEY")
A_BASE = "https://api.assemblyai.com/v2"
HEADERS = {"authorization": A_KEY}

# Create custom SSL context that's very permissive
def create_ssl_context():
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_ciphers('DEFAULT@SECLEVEL=1')
    return context

# Custom HTTPAdapter that forces SSL context
class SSLAdapter(HTTPAdapter):
    def __init__(self, ssl_context=None, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = self.ssl_context
        kwargs['ssl_version'] = ssl.PROTOCOL_TLS
        return super().init_poolmanager(*args, **kwargs)

# Create session with aggressive SSL bypass
def create_session():
    session = requests.Session()
    
    # Disable all SSL verification
    session.verify = False
    session.trust_env = False
    
    # Create permissive SSL context
    ssl_context = create_ssl_context()
    
    # Setup retry strategy
    retries = Retry(
        total=2,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    
    # Mount adapter with custom SSL context
    adapter = SSLAdapter(ssl_context=ssl_context, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session

# Global session
session = create_session()

def _upload_file_chunks(path: Path) -> str:
    """Upload file in smaller chunks to avoid SSL timeout."""
    url = f"{A_BASE}/upload"
    chunk_size = 5 * 1024 * 1024  # 5MB chunks
    
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            
            try:
                r = session.post(
                    url,
                    headers=HEADERS,
                    data=chunk,
                    timeout=60,
                    verify=False
                )
                r.raise_for_status()
            except Exception as e:
                print(f"Chunk upload failed: {e}")
                raise
    
    return r.json()["upload_url"]

def _upload_file_httpx(path: Path) -> str:
    """Alternative upload using httpx library."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx not installed. Run: pip install httpx")
    
    url = f"{A_BASE}/upload"
    
    # Create httpx client with SSL disabled
    with httpx.Client(
        verify=False,
        timeout=600,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)
    ) as client:
        with open(path, "rb") as f:
            try:
                r = client.post(url, headers=HEADERS, content=f)
                r.raise_for_status()
                return r.json()["upload_url"]
            except Exception as e:
                print(f"HTTPX upload failed: {e}")
                raise

def _upload_file_curl(path: Path) -> str:
    """Fallback using curl subprocess."""
    import subprocess
    import json
    import tempfile
    
    url = f"{A_BASE}/upload"
    
    # Create temporary file for curl output
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as temp_file:
        temp_path = temp_file.name
    
    try:
        # Build curl command
        curl_cmd = [
            'curl',
            '-X', 'POST',
            '-H', f'authorization: {A_KEY}',
            '-H', 'Content-Type: application/octet-stream',
            '--data-binary', f'@{path}',
            '--insecure',  # Disable SSL verification
            '--connect-timeout', '60',
            '--max-time', '600',
            '--output', temp_path,
            url
        ]
        
        print("Trying curl upload (bypassing Python SSL issues)...")
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=700)
        
        if result.returncode != 0:
            raise RuntimeError(f"Curl failed: {result.stderr}")
        
        # Read response
        with open(temp_path, 'r') as f:
            response = json.load(f)
        
        if 'upload_url' not in response:
            raise RuntimeError(f"Invalid response: {response}")
        
        return response['upload_url']
        
    finally:
        # Cleanup temp file
        try:
            os.unlink(temp_path)
        except:
            pass

def _upload_file(path: Path) -> str:
    """Upload entire file to AssemblyAI with multiple fallback methods."""
    file_size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Uploading {file_size_mb:.1f} MB file...")
    
    # List of upload methods to try
    upload_methods = [
        ("Standard requests", _upload_file_standard),
        ("HTTPX library", _upload_file_httpx),
        ("Curl subprocess", _upload_file_curl),
    ]
    
    for method_name, method_func in upload_methods:
        try:
            print(f"Trying {method_name}...")
            upload_url = method_func(path)
            print(f"✓ {method_name} succeeded!")
            return upload_url
            
        except Exception as e:
            print(f"✗ {method_name} failed: {str(e)[:100]}")
            if method_func == upload_methods[-1][1]:  # Last method
                raise RuntimeError(f"All upload methods failed. Last error: {e}")
            continue

def _upload_file_standard(path: Path) -> str:
    """Standard upload method with aggressive SSL bypass."""
    url = f"{A_BASE}/upload"
    
    # Try different approaches
    approaches = [
        {"method": "single", "timeout": 300},
        {"method": "chunked", "timeout": 600},
    ]
    
    for approach in approaches:
        try:
            if approach["method"] == "chunked":
                return _upload_file_chunks(path)
            else:
                with open(path, "rb") as f:
                    r = session.post(
                        url,
                        headers=HEADERS,
                        data=f,
                        timeout=approach["timeout"],
                        verify=False
                    )
                    r.raise_for_status()
                    return r.json()["upload_url"]
                    
        except Exception as e:
            if approach == approaches[-1]:  # Last approach
                raise e
            continue

def transcribe_episode(podcast: str, guid: str, title: str) -> Path:
    """Download → Upload → Transcribe → Poll until transcript ready."""
    if episode_done_at_least(podcast, guid, "transcribed"):
        return episode_paths(podcast, guid, title)["raw"]

    paths = episode_paths(podcast, guid, title)
    raw = paths["raw"]

    # If already transcribed, skip
    if raw.exists() and raw.stat().st_size > 0:
        update_episode_state(podcast, guid, status="transcribed", files={"raw": str(raw)})
        return raw

    mf = load_manifest(podcast)
    epi = mf["episodes"].get(guid, {})
    tid = epi.get("transcript_id")

    if not tid:
        # Check if audio file exists
        if not paths["audio"].exists():
            raise FileNotFoundError(f"Audio file not found: {paths['audio']}")
        
        print(f"Uploading audio file: {paths['audio'].name}")
        upload_url = _upload_file(paths["audio"])
        
        print(f"Starting transcription job...")
        job = session.post(f"{A_BASE}/transcript", headers=HEADERS, json={
            "audio_url": upload_url,
            "speaker_labels": False,
            "auto_highlights": False
        }, timeout=30, verify=False)
        job.raise_for_status()
        
        tid = job.json()["id"]
        update_episode_state(podcast, guid, transcript_id=tid)
        print(f"Transcription job created with ID: {tid}")

    # Poll AssemblyAI until done
    print("Polling for transcription completion...")
    poll_count = 0
    while True:
        try:
            r = session.get(f"{A_BASE}/transcript/{tid}", headers=HEADERS, timeout=30, verify=False)
            r.raise_for_status()
            j = r.json()
            
            status = j["status"]
            print(f"Transcription status: {status} (poll #{poll_count + 1})")

            if status == "completed":
                text = j.get("text", "")
                if not text:
                    raise RuntimeError("Transcription completed but no text returned")
                
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(text, encoding="utf-8")
                update_episode_state(podcast, guid, status="transcribed", files={"raw": str(raw)})
                print(f"Transcription saved to: {raw}")
                return raw

            if status == "error":
                error_msg = j.get('error', 'Unknown error')
                raise RuntimeError(f"AssemblyAI transcription error: {error_msg}")
            
            poll_count += 1
            if poll_count > 360:  # 30 minutes max
                raise RuntimeError("Transcription timeout: exceeded 30 minutes")
            
            time.sleep(5)
            
        except requests.exceptions.RequestException as e:
            print(f"Network error while polling (attempt {poll_count + 1}): {e}")
            if poll_count > 10:
                raise RuntimeError(f"Too many network errors while polling: {e}")
            time.sleep(10)
            poll_count += 1