from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from pathlib import Path
from ..utils.paths import podcast_artifacts
from ..utils.state import load_manifest

styles = getSampleStyleSheet()

def _p(story, text, style="BodyText"):
    story.append(Paragraph(text, styles[style] if style in styles else styles["BodyText"]))
    story.append(Spacer(1, 0.15 * inch))

def generate_podcast_pdf(podcast: str):
    art = podcast_artifacts(podcast)
    pdf = art["pdf"]
    story = []
    mf = load_manifest(podcast)

    _p(story, f"<b>Podcast:</b> {podcast}", "Title")

    for guid, epi in mf.get("episodes", {}).items():
        title = epi.get("title", guid)
        pub = epi.get("publish_date", "")
        host = epi.get("host", "")
        guest = epi.get("guest", "")
        clean_path = Path(epi.get("files", {}).get("clean", ""))
        text = clean_path.read_text(encoding="utf-8") if clean_path.exists() else ""
        _p(story, f"<b>Episode:</b> {title}", "Heading2")
        if pub: _p(story, f"<b>Published:</b> {pub}")
        if host or guest: _p(story, f"<b>Host:</b> {host}  <b>Guest:</b> {guest}")
        _p(story, f"<b>Transcript:</b>")
        _p(story, text)

    doc = SimpleDocTemplate(str(pdf), pagesize=LETTER, title=podcast)
    doc.build(story)
    return pdf
