import feedparser
import re

def extract_host_guest_info(title: str, description: str = "", author: str = ""):
    """Extract host and guest information from episode metadata."""
    host = ""
    guest = ""
    
    # Common patterns for guest identification
    guest_patterns = [
        r"with\s+([^:,\-\n]+)",  # "Episode with John Smith"
        r"guest:?\s*([^,\-\n]+)",  # "Guest: Jane Doe"
        r"featuring\s+([^,\-\n]+)",  # "Featuring Mike Wilson"
        r"interviews?\s+([^,\-\n]+)",  # "Interview Sarah Johnson"
    ]
    
    # Try to find guest in title first
    title_lower = title.lower()
    for pattern in guest_patterns:
        match = re.search(pattern, title_lower)
        if match:
            guest = match.group(1).strip().title()
            break
    
    # If no guest found in title, try description
    if not guest and description:
        desc_lower = description.lower()
        for pattern in guest_patterns:
            match = re.search(pattern, desc_lower)
            if match:
                guest = match.group(1).strip().title()
                break
    
    # Extract host information
    if author:
        host = author
    elif "behind the stays" in title_lower:
        host = "Behind the Stays"
    
    # Clean up extracted names
    if guest:
        # Remove common suffixes and clean up
        guest = re.sub(r'\s+(talks?|discusses?|on|about).*$', '', guest, flags=re.IGNORECASE)
        guest = guest.strip(' ,-')
    
    return host, guest

def parse_feed(feed_url: str, latest_n: int = 20):
    d = feedparser.parse(feed_url)
    podcast_title = d.feed.get("title", feed_url)
    
    # Extract podcast-level host info
    podcast_author = d.feed.get("author", "")
    podcast_host = podcast_author or podcast_title
    
    episodes = []
    for e in d.entries[:latest_n]:
        guid = getattr(e, "id", getattr(e, "guid", e.get("link", e.get("title", ""))))
        audio_url = None
        
        # Find audio URL
        if "links" in e:
            for l in e.links:
                if l.get("rel") == "enclosure" and str(l.get("type", "")).startswith("audio"):
                    audio_url = l.get("href")
                    break
        if not audio_url and getattr(e, "enclosures", None):
            audio_url = e.enclosures[0].get("href")
        if not audio_url:
            continue
        
        # Extract episode metadata
        title = e.get("title", guid)
        description = e.get("description", "") or e.get("summary", "")
        episode_author = e.get("author", "")
        
        # Extract host and guest info
        host, guest = extract_host_guest_info(title, description, episode_author)
        
        # Fallback to podcast-level host if no episode-specific host found
        if not host:
            host = podcast_host
        
        episodes.append({
            "guid": guid,
            "title": title,
            "audio_url": audio_url,
            "publish_date": e.get("published", ""),
            "host": host,
            "guest": guest,
            "description": description[:500] + "..." if len(description) > 500 else description,
        })
        
        # Debug output to see what's being extracted
        print(f"Parsed episode: {title[:50]}...")
        print(f"  Host: {host}")
        print(f"  Guest: {guest}")
    
    return {"podcast_title": podcast_title, "episodes": episodes}