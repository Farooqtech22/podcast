import json
from typing import Dict
from .paths import podcast_artifacts

# manifest keeps episode progress for resume/idempotency
# status order: downloaded -> transcribed -> cleaned -> embedded -> pdf

def load_manifest(podcast: str) -> Dict:
    mf = podcast_artifacts(podcast)["manifest"]
    if mf.exists():
        return json.loads(mf.read_text(encoding="utf-8"))
    return {"podcast_name": podcast, "episodes": {}}

def save_manifest(podcast: str, data: Dict):
    mf = podcast_artifacts(podcast)["manifest"]
    mf.write_text(json.dumps(data, indent=2), encoding="utf-8")

def update_episode_state(podcast: str, guid: str, **kwargs):
    mf = load_manifest(podcast)
    epi = mf["episodes"].get(guid, {})
    epi.update(kwargs)
    mf["episodes"][guid] = epi
    save_manifest(podcast, mf)

def episode_done_at_least(podcast: str, guid: str, stage: str) -> bool:
    mf = load_manifest(podcast)
    epi = mf["episodes"].get(guid)
    if not epi: return False
    order = ["downloaded", "transcribed", "cleaned", "embedded", "pdf"]
    try:
        return order.index(epi.get("status", "")) >= order.index(stage)
    except ValueError:
        return False
