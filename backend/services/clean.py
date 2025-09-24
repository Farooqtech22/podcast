import re
from ..utils.paths import episode_paths
from ..utils.state import update_episode_state, episode_done_at_least

AD_PATTERNS = [
    r"this episode is sponsored by.*?$",
    r"use code [A-Z0-9]{4,}.*?$",
    r"promo code.*?$",
]
HEAD_TAIL = [r"^\s*intro[:\-].*?$", r"^\s*outro[:\-].*?$"]
MULTIWS = re.compile(r"\s+")

def clean_transcript(podcast: str, guid: str, title: str):
    if episode_done_at_least(podcast, guid, "cleaned"):
        return episode_paths(podcast, guid, title)["clean"]
    paths = episode_paths(podcast, guid, title)
    raw, clean = paths["raw"], paths["clean"]
    txt = raw.read_text(encoding="utf-8") if raw.exists() else ""
    for pat in AD_PATTERNS + HEAD_TAIL:
        txt = re.sub(pat, " ", txt, flags=re.IGNORECASE | re.MULTILINE)
    txt = MULTIWS.sub(" ", txt).strip()
    clean.write_text(txt, encoding="utf-8")
    update_episode_state(podcast, guid, status="cleaned", files={"clean": str(clean)})
    return clean
