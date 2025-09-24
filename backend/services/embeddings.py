import json
from pathlib import Path
from sentence_transformers import SentenceTransformer
import faiss
from ..utils.paths import podcast_artifacts
from ..utils.state import load_manifest, update_episode_state, episode_done_at_least

def build_embeddings(podcast: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    if all([episode_done_at_least(podcast, guid, "embedded") for guid in load_manifest(podcast)["episodes"]]):
        # if previously embedded for all, return existing
        return podcast_artifacts(podcast)["faiss"]

    model = SentenceTransformer(model_name)
    mf = load_manifest(podcast)

    texts, metas = [], []
    for guid, epi in mf.get("episodes", {}).items():
        clean = Path(epi.get("files", {}).get("clean", ""))
        if clean.exists():
            txt = clean.read_text(encoding="utf-8")
            texts.append(txt)
            metas.append({"guid": guid, "title": epi.get("title", guid)})
    if not texts:
        return None

    embs = model.encode(texts, show_progress_bar=True)
    dim = embs.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embs)

    art = podcast_artifacts(podcast)
    faiss.write_index(index, str(art["faiss"]))
    Path(art["faiss_meta"]).write_text(json.dumps(metas, indent=2), encoding="utf-8")

    # mark each episode embedded
    for guid in mf["episodes"]:
        update_episode_state(podcast, guid, status="embedded")

    return art["faiss"]

def search(podcast: str, query: str, top_k: int = 5, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    art = podcast_artifacts(podcast)
    if not Path(art["faiss"]).exists(): return []
    model = SentenceTransformer(model_name)
    qv = model.encode([query])
    index = faiss.read_index(str(art["faiss"]))
    D, I = index.search(qv, top_k)
    metas = json.loads(Path(art["faiss_meta"]).read_text(encoding="utf-8"))
    results = []
    for idx, dist in zip(I[0], D[0]):
        if idx < len(metas):
            results.append({"title": metas[idx]["title"], "guid": metas[idx]["guid"], "score": float(dist)})
    return results
