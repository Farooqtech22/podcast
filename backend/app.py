import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from typing import Dict
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from the correct location
env_path = Path(__file__).parent / '.env'  # backend/.env
load_dotenv(env_path)

# Verify environment loading (remove after testing)
print(f"ENV file path: {env_path}")
print(f"ENV file exists: {env_path.exists()}")
print(f"AssemblyAI Key loaded: {bool(os.getenv('ASSEMBLYAI_API_KEY'))}")
print(f"OpenAI Key loaded: {bool(os.getenv('OPENAI_API_KEY'))}")

from backend.models.schemas import AddPodcastsRequest, QueryRequest
from backend.services.rss import parse_feed
from backend.services.download import download_episode
from backend.services.transcribe import transcribe_episode
from backend.services.clean import clean_transcript
from backend.services.pdfgen import generate_podcast_pdf
from backend.services.persona import extract_persona
from backend.services.embeddings import build_embeddings, search
from backend.services.debate import single_persona_answer, multi_persona_debate
from backend.utils.paths import podcast_dir
from backend.utils.state import load_manifest, save_manifest, update_episode_state

# Create FastAPI app (only once!)
app = FastAPI(title="AI Podcast Persona Analyzer (File-based)")

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # front
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/add_podcasts")
def add_podcasts(req: AddPodcastsRequest):
    result: Dict[str, dict] = {}
    for feed in req.feeds:
        try:
            feed_info = parse_feed(feed, latest_n=req.latest_n)
            podcast = feed_info["podcast_title"]
            podcast_dir(podcast)  # ensure folders
            mf = load_manifest(podcast)
            for ep in feed_info["episodes"]:
                guid = ep["guid"]
                mf["episodes"].setdefault(guid, {
                    "title": ep["title"],
                    "audio_url": ep["audio_url"],
                    "publish_date": ep.get("publish_date", ""),
                    "status": mf["episodes"].get(guid, {}).get("status", "")
                })
            save_manifest(podcast, mf)
            result[podcast] = {"episodes": len(feed_info["episodes"])}
        except Exception as e:
            result[feed] = {"error": str(e)}
    return {"parsed": result}

@app.post("/process_podcast")
def process_podcast(podcast: str):
    """Runs end-to-end for one podcast: download -> transcribe -> clean -> embeddings -> pdf -> persona"""
    try:
        mf = load_manifest(podcast)
        
        # Process each episode
        for guid, ep in mf["episodes"].items():
            title, url = ep["title"], ep["audio_url"]
            
            try:
                # 1) download (resume supported)
                print(f"Processing episode: {title[:50]}...")
                download_episode(podcast, guid, title, url)
                
                # 2) transcribe (idempotent & resumable via transcript_id in manifest)
                transcribe_episode(podcast, guid, title)
                
                # 3) clean
                clean_transcript(podcast, guid, title)
                
            except Exception as e:
                print(f"Error processing episode {title}: {str(e)}")
                # Continue with other episodes even if one fails
                continue

        # 4) embeddings (marks embedded for all)
        build_embeddings(podcast)

        # 5) PDF (per podcast combined)
        pdf_path = generate_podcast_pdf(podcast)
        
        # mark episodes as pdf stage reached
        mf = load_manifest(podcast)
        for guid in mf["episodes"]:
            update_episode_state(podcast, guid, status="pdf")
            
        return {"success": True, "pdf": str(pdf_path)}
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/persona")
def persona(podcast: str):
    try:
        p = extract_persona(podcast)
        return {"success": True, "persona": p}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/query_single")
def query_single(podcast: str, query: str):
    try:
        result = single_persona_answer(podcast, query)
        return result  # Return directly without wrapping
    except Exception as e:
        return {"error": str(e)}

@app.post("/query_multi")
def query_multi(req: QueryRequest):
    try:
        result = multi_persona_debate(req.podcast_names, req.query)
        return result  # Return directly without wrapping
    except Exception as e:
        return {"error": str(e)}

@app.get("/manifest")
def manifest(podcast: str):
    try:
        return {"success": True, "manifest": load_manifest(podcast)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/search")
def search_endpoint(podcast: str, q: str):
    try:
        results = search(podcast, q, top_k=5)
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}