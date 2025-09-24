from pathlib import Path
import json, re, os
from collections import Counter
from openai import OpenAI
from ..utils.paths import podcast_artifacts
from ..utils.state import load_manifest

# Heuristic fallback cues
QUESTION_CUES = ["how do you", "what's one", "tell me about", "walk me through", "why did you", "what should be"]
THEMES = ["sustainability", "luxury", "design", "technology", "operations", "staff", "guest"]

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def extract_persona(podcast: str):
    mf = load_manifest(podcast)
    texts = []
    for _, epi in mf.get("episodes", {}).items():
        clean_path = Path(epi.get("files", {}).get("clean", ""))
        if clean_path.exists():
            texts.append(clean_path.read_text(encoding="utf-8").lower())
    text = "\n".join(texts)

    # ---------- Heuristic Persona (Fallback) ----------
    tone = "Conversational" if (text.count("i think") + text.count("you know")) > 5 else "Analytical"
    theme_counts = {t: len(re.findall(rf"\b{re.escape(t)}\b", text)) for t in THEMES}
    common_themes = [k for k, v in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True) if v > 0][:5]
    signature_questions = [q for q in QUESTION_CUES if q in text][:5]

    guest_words = ["founder", "designer", "architect", "gm", "chef", "owner"]
    guest_archetypes = [w for w in guest_words if re.search(rf"\b{w}\b", text)]

    heuristic_persona = {
        "podcast_name": podcast,
        "host_style": f"{tone}, data-aware",
        "common_themes": common_themes or ["hospitality"],
        "signature_questions": signature_questions or ["What's one operational hack you swear by?"],
        "guest_archetypes": guest_archetypes or ["hotel founder", "interior designer"]
    }

    # ---------- GPT Enhancement ----------
    try:
        prompt = f"""
You are analyzing the podcast "{podcast}".
Based on these transcripts, generate a structured persona profile in JSON format only:

{{
  "podcast_name": "{podcast}",
  "host_style": "string describing tone and approach",
  "common_themes": ["theme1", "theme2", "theme3"],
  "signature_questions": ["question1", "question2", "question3", "question4", "question5", "question6", "question7", "question8", "question9", "question10", "question11", "question12", "question13", "question14", "question15", "question16", "question17", "question18", "question19", "question20"],
  "guest_archetypes": ["archetype1", "archetype2", "archetype3", "archetype4", "archetype5", "archetype6", "archetype7", "archetype8", "archetype9", "archetype10", "archetype11", "archetype12", "archetype13", "archetype14", "archetype15", "archetype16", "archetype17", "archetype18", "archetype19", "archetype20"]
}}

Transcripts (sampled):
{text[:4000]}

Existing heuristic persona for reference:
{json.dumps(heuristic_persona, indent=2)}

Respond with ONLY the JSON object, no additional text.
        """

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are an expert podcast persona analyst. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ]
        )

        # Fixed: Use .content instead of ["content"]
        gpt_persona = response.choices[0].message.content

        # Try parsing as JSON, fallback to text wrapping
        try:
            persona = json.loads(gpt_persona)
        except json.JSONDecodeError:
            persona = heuristic_persona
            persona["gpt_notes"] = gpt_persona

    except Exception as e:
        # If OpenAI call fails → fallback to heuristic only
        persona = heuristic_persona
        persona["warning"] = f"OpenAI persona enhancement failed: {str(e)}"

    # ---------- Save Persona ----------
    art = podcast_artifacts(podcast)
    Path(art["persona"]).write_text(json.dumps(persona, indent=2), encoding="utf-8")
    return persona