import os
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI

import sys
from pathlib import Path

# Add project root to sys.path if not present
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from backend.services.embeddings import search



from backend.utils.paths import podcast_artifacts

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# -------------------------------
# Cleaning Function (IMPROVED)
# -------------------------------
def clean_text_output(text: str) -> str:
    """Clean up AI-generated text to remove all formatting artifacts and fix line breaks."""
    if not text:
        return text

    # Handle various forms of escaped newlines
    text = text.replace('\\n\\n\\n', '\n\n')
    text = text.replace('\\n\\n', '\n\n')
    text = text.replace('\\n', '\n')
    
    # Handle JSON-escaped sequences
    text = text.replace('\\\\n\\\\n', '\n\n')
    text = text.replace('\\\\n', '\n')

    # Remove JSON escape characters
    text = text.replace('\\"', '"')
    text = text.replace('\\t', ' ')
    text = text.replace('\\\\', '\\')

    # Remove all markdown formatting
    text = re.sub(r'#{1,6}\s*', '', text)
    text = text.replace('**', '')
    text = text.replace('*', '')

    # Remove brackets and quotes
    text = text.replace('[', '').replace(']', '')
    text = text.replace('{', '').replace('}', '')

    # Remove surrounding quotes
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]

    # Remove emojis and special characters
    text = re.sub(r'[✨🔥🌿📝💡🎯]', '', text)

    # Fix spacing and line breaks
    text = re.sub(r' +', ' ', text)  # Multiple spaces to single space
    text = re.sub(r'\n{3,}', '\n\n', text)  # Multiple newlines to double newline
    text = re.sub(r'\n([A-Z])', r'\n\n\1', text)  # Add spacing before capitalized sentences

    return text.strip()


def apply_final_cleaning(data: dict) -> dict:
    """Apply final cleaning to all text content in the response dictionary."""
    if isinstance(data, dict):
        cleaned_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                # Apply text cleaning including post-JSON newline fixes
                cleaned_value = value
                # Handle all possible newline escape variations
                cleaned_value = cleaned_value.replace('\\n\\n\\n', '\n\n')
                cleaned_value = cleaned_value.replace('\\n\\n', '\n\n')
                cleaned_value = cleaned_value.replace('\\n', '\n')
                cleaned_value = cleaned_value.replace('\\\\n', '\n')
                cleaned_data[key] = clean_text_output(cleaned_value)
            elif isinstance(value, list):
                cleaned_data[key] = [apply_final_cleaning(item) if isinstance(item, dict) else item for item in value]
            elif isinstance(value, dict):
                cleaned_data[key] = apply_final_cleaning(value)
            else:
                cleaned_data[key] = value
        return cleaned_data
    return data


# -------------------------------
# Confidence Scoring System
# -------------------------------
def calculate_confidence(episodes: list, query: str) -> float:
    """
    Calculate confidence score based on episode relevance and query characteristics.
    
    Returns:
        float: Confidence score between 0.0 and 1.0
    """
    if not episodes:
        return 0.0
    
    # Get the highest relevance score
    highest_score = max(ep.get('score', 0) for ep in episodes)
    
    # Base confidence on highest score
    base_confidence = min(highest_score, 1.0)
    
    # Boost confidence if multiple relevant episodes
    if len([ep for ep in episodes if ep.get('score', 0) > 0.5]) >= 2:
        base_confidence += 0.1
    
    # Boost confidence for hospitality-specific queries
    hospitality_keywords = [
        'hotel', 'guest', 'service', 'hospitality', 'restaurant', 
        'booking', 'check-in', 'amenities', 'concierge', 'staff'
    ]
    if any(keyword in query.lower() for keyword in hospitality_keywords):
        base_confidence += 0.05
    
    # Cap at 1.0
    return min(base_confidence, 1.0)


def get_confidence_explanation(episodes: list, confidence: float) -> str:
    """
    Generate human-readable explanation for confidence score.
    """
    if confidence >= 0.8:
        return f"High confidence based on {len(episodes)} highly relevant episodes"
    elif confidence >= 0.5:
        return f"Medium confidence based on {len(episodes)} moderately relevant episodes"
    elif confidence >= 0.3:
        return f"Low confidence based on {len(episodes)} episodes with limited relevance"
    else:
        return "Very low confidence - drawing from general hospitality knowledge"


# -------------------------------
# Creative Mode Detection
# -------------------------------
def should_use_creative_mode(episodes: list, query: str, min_relevance_score: float = 0.3) -> bool:
    """
    Determine if we should use creative mode based on episode relevance and query type.
    """
    # If no episodes found, use creative mode
    if not episodes:
        return True
    
    # Check if highest scoring episode meets relevance threshold
    highest_score = max(ep.get('score', 0) for ep in episodes)
    
    # If no episodes are relevant enough, use creative mode
    if highest_score < min_relevance_score:
        return True
    
    # Check for opinion-based or creative queries
    creative_triggers = [
        'what do you think about',
        'your opinion on',
        'how do you feel about',
        'what would you do if',
        'imagine if',
        'hypothetical',
        'creative ideas for',
        'brainstorm',
        'outside the box',
        'what if',
        'suppose',
        'in your experience',
        'from your perspective',
        'thoughts on',
        'view on'
    ]
    
    query_lower = query.lower()
    if any(trigger in query_lower for trigger in creative_triggers):
        return True
    
    return False


# -------------------------------
# Creative Mode Anti-Fabrication Detection
# -------------------------------
def should_skip_synthesis(individual_responses: list) -> bool:
    """
    Determine if synthesis should be skipped because all responses are creative mode.
    This prevents fabricating discussions that never happened.
    """
    if not individual_responses:
        return True
    
    # Count creative responses (those that acknowledge they don't have episode content)
    creative_responses = 0
    total_valid_responses = 0
    
    for resp in individual_responses:
        response_text = resp.get("response", "").lower()
        
        # Skip error responses
        if "trouble accessing" in response_text:
            continue
            
        total_valid_responses += 1
        
        # Check if response acknowledges lack of episode content
        creative_indicators = [
            "while this hasn't",
            "this topic hasn't been",
            "hasn't come up in our recent episodes",
            "drawing from my broader",
            "from my hospitality experience",
            "this hasn't been a focus"
        ]
        
        if any(indicator in response_text for indicator in creative_indicators):
            creative_responses += 1
    
    # If 80% or more responses are creative mode, skip synthesis
    if total_valid_responses == 0:
        return True
        
    creative_ratio = creative_responses / total_valid_responses
    return creative_ratio >= 0.8


# -------------------------------
# Simple Creative Response for Non-Podcast Topics
# -------------------------------
def generate_simple_creative_response(query: str, podcasts: list[str]) -> str:
    """
    Generate a simple, honest response for topics outside podcast scope.
    """
    # Get the first podcast's persona for voice
    first_podcast = podcasts[0] if podcasts else "The Hospitality Expert"
    persona_path = podcast_artifacts(first_podcast).get("persona") if podcasts else None
    
    persona = {}
    if persona_path and Path(persona_path).exists():
        persona = json.loads(Path(persona_path).read_text(encoding="utf-8"))
    
    podcast_name = persona.get("podcast_name", "The Curious Concierge")
    host_style = persona.get("host_style", "Warm, conversational")
    
    # Detect if this is a factual question that needs a direct answer
    factual_indicators = [
        'who is', 'what is', 'when is', 'where is', 'how many',
        'president', 'capital', 'population', 'weather', 'temperature'
    ]
    
    is_factual = any(indicator in query.lower() for indicator in factual_indicators)
    
    prompt = f"""
You are the host of {podcast_name}, speaking in a {host_style} style.

The user asked: {query}

This question hasn't been covered in your recent podcast episodes. Respond honestly and helpfully.

CRITICAL INSTRUCTIONS:
1. Do NOT claim multiple hosts discussed this topic
2. Do NOT reference fake podcast episodes or discussions
3. Do NOT pretend to synthesize insights from multiple podcasters
4. Be completely transparent that this is outside your podcast content

{"For factual questions: Give the direct answer first, then optionally connect to hospitality if relevant." if is_factual else ""}

Response format:
- Start by acknowledging this isn't covered in your podcast episodes
- {"Provide the factual answer clearly" if is_factual else "Share your thoughts based on general knowledge"}
- Optionally mention how it might relate to hospitality (if relevant)
- Keep it conversational and authentic to your podcast personality
- Be brief and direct

Write in plain text with natural paragraph breaks.
"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=400
        )
        answer = clean_text_output(response.choices[0].message.content)
        return answer.replace('\\n\\n', '\n\n').replace('\\n', '\n')
    except Exception:
        return f"That's an interesting question! While this hasn't been a topic we've explored in our recent podcast episodes, I appreciate your curiosity. If you have any hospitality-related questions, I'd be happy to help with those."


# -------------------------------
# Honest Creative Persona Prompt Builder
# -------------------------------
def build_creative_prompt(persona: dict, query: str, scenario_type: str) -> str:
    """
    Build a creative prompt that ensures complete transparency about sources.
    """
    
    podcast_name = persona.get("podcast_name", "The Hospitality Expert")
    host_style = persona.get("host_style", "Warm, conversational")
    common_themes = persona.get("common_themes", ["hospitality trends", "guest experiences"])
    
    base_creative_persona = f"""
You are the host of {podcast_name}, a hospitality podcast.

Your personality and hosting style:
- Host style: {host_style}
- You're passionate about: {", ".join(common_themes)}
- You have years of experience in hospitality and podcasting

ABSOLUTE TRANSPARENCY REQUIREMENT:
This question hasn't been covered in your recent podcast episodes. You MUST be completely honest about this.

FORBIDDEN - NEVER do any of these:
- Don't reference fake podcast episodes or guests
- Don't claim insights come from "podcasters" or "recent episodes"
- Don't pretend to synthesize non-existent podcast content
- Don't make up stories about guest interviews
- Don't reference discussions that never happened

REQUIRED - Always do this:
- Start by acknowledging this topic hasn't been covered in episodes
- Be clear you're drawing from general hospitality knowledge
- Use phrases like "While this hasn't come up in our recent episodes..."
- Be honest about your knowledge source throughout

Scenario type: {scenario_type}

FORMATTING RULES:
- Write in plain text only
- Use actual line breaks between paragraphs
- Keep your warm, conversational podcast tone
- Be authentic to your host personality
- Share practical insights and wisdom
- Always maintain transparency about sources
"""

    honest_scenario_instructions = {
        "research": f"""
The user wants insights on: {query}

You MUST start with complete transparency about sources, then provide insights:

REQUIRED opening acknowledgment:
"While we haven't explored [topic] specifically in recent episodes, I can share some thoughts from my broader hospitality perspective..."

Then provide:
- 2-3 thoughtful insights based on general industry knowledge
- Connections to broader hospitality trends from your experience
- Suggestions for where they might find more specialized information
- Keep your warm, fireside chat tone

User query: {query}
""",

        "question_crafting": f"""
The user wants interview questions about: {query}

REQUIRED opening acknowledgment:
"While this topic hasn't come up in our recent shows, based on my podcasting experience, here are some questions that could spark great conversations..."

Then create 4-5 engaging questions:
- Make them thought-provoking and story-driven
- Draw on your general podcasting experience
- Keep your conversational style

User query: {query}
""",

        "advisory": f"""
The user wants advice on: {query}

REQUIRED opening acknowledgment:
"This hasn't been a focus of our recent episodes, but from my broader hospitality experience..."

Then provide guidance:
- Share insights based on general hospitality knowledge
- Provide 2-3 practical, actionable steps
- End with encouragement in your warm style

User query: {query}
""",

        "conversational": f"""
The user asked: {query}

REQUIRED opening acknowledgment:
"That's an interesting question! While this hasn't been a focus of our recent episodes, I can offer some insights from my hospitality experience..."

Then respond warmly:
- Share your thoughts based on general hospitality knowledge
- Be conversational and engaging
- Keep it natural and true to your personality

User query: {query}
"""
    }

    return base_creative_persona + honest_scenario_instructions.get(scenario_type, honest_scenario_instructions["conversational"])


# -------------------------------
# Scenario Detection
# -------------------------------
def detect_scenario_type(query: str) -> str:
    """Detect which type of content scenario the user is requesting."""
    query_lower = query.lower()

    if any(word in query_lower for word in ['trends', 'identify', 'research', 'top 3', 'shaping']):
        return 'research'
    elif any(word in query_lower for word in ['questions', 'interview', 'craft', 'preparing']):
        return 'question_crafting'
    elif any(word in query_lower for word in ['advice', 'advising', 'recommend', 'strategic']):
        return 'advisory'
    elif any(word in query_lower for word in ['episode outline', 'outline', 'content creation']):
        return 'episode_outline'
    elif any(word in query_lower for word in ['promo', 'promotional', 'script', 'season launch']):
        return 'promotional_script'
    elif any(word in query_lower for word in ['social media', 'instagram', 'twitter', 'linkedin']):
        return 'social_media'
    elif any(word in query_lower for word in ['newsletter', 'weekly', 'digest', 'email']):
        return 'newsletter'
    elif any(word in query_lower for word in ['general advice', 'launching', 'brand', 'pillars']):
        return 'general_advice'
    else:
        return 'conversational'


# -------------------------------
# Episode Retrieval
# -------------------------------
def get_relevant_episodes(podcasts: list[str], query: str, limit: int = 5):
    """Get relevant episodes from podcasts with transcript snippets."""
    all_episodes = []
    for podcast in podcasts:
        hits = search(podcast, query, top_k=limit)
        for hit in hits:
            all_episodes.append({
                'podcast': podcast,
                'title': hit.get('title', 'Untitled Episode'),
                'guid': hit.get('guid', ''),
                'text': hit.get('text', ''),
                'score': hit.get('score', 0)
            })

    all_episodes.sort(key=lambda x: x['score'], reverse=True)
    return all_episodes[:limit]


# -------------------------------
# Prompt Builder with Persona (Database Mode)
# -------------------------------
def build_prompt(persona: dict, query: str, context_text: str, scenario_type: str) -> str:
    """
    Build a unified persona-driven prompt for LLM using actual episode content.
    """

    base_persona = f"""
You are {persona.get("podcast_name", "a hospitality expert")}.

Act as a professional podcaster and subject-matter expert in hospitality.
Your host style is: {persona.get("host_style", "Warm, conversational")}.

You should:
- Speak in your podcasting style ({persona.get("host_style", "conversational")}).
- Draw insights from themes like {", ".join(persona.get("common_themes", []))}.
- When possible, reference typical guests (e.g., {", ".join(persona.get("guest_archetypes", []))}).
- Naturally weave in questions such as {", ".join(persona.get("signature_questions", []))}.
- Always provide specific, podcast-backed insights (not generic advice).
- Reference the episode content provided when relevant.

Scenario type: {scenario_type}

IMPORTANT FORMATTING RULES:
- Write in plain text only. No markdown, no hashtags, no formatting symbols, no emojis.
- Use actual line breaks between paragraphs (just press Enter to create new lines).
- NEVER write \\n, \\n\\n, or any escape sequences - use real paragraph breaks.
- Keep tone consistent with the persona's podcast style.
- Be professional, insightful, but conversational.
- Reference transcript content when possible.
    """

    scenario_instructions = {
        "research": f"""
The user wants hospitality research and insights.
Instructions:
- Identify 2-3 key trends from available podcast content
- For each trend: write 2-3 sentences + direct transcript quote + reference episode
- Suggest one resource (like a podcast episode) where the user can learn more
- Keep it playful but professional, like chatting by the fire.

Available content:
{context_text}

User query:
{query}
        """,

        "question_crafting": f"""
The user wants interview questions.
Instructions:
- Create 3-5 open-ended, unique, narrative-driven questions
- Make them spark deep, story-rich conversation
- Write naturally, as if you were speaking them in a podcast.

Available content:
{context_text}

User query:
{query}
        """,

        "advisory": f"""
The user wants strategic business advice.
Instructions:
- Give one strategic recommendation with transcript backing
- Suggest 2 actionable steps
- End with a warm, coffee-chat style wrap-up.

Available content:
{context_text}

User query:
{query}
        """,

        "conversational": f"""
Respond naturally and conversationally to the user's question.
- Draw on podcast content when relevant
- Keep it warm, curious, and styled like your podcast
- Avoid generic filler; share the real scoop.

Available content:
{context_text}

User query:
{query}
        """
    }

    return base_persona + scenario_instructions.get(scenario_type, scenario_instructions["conversational"])


# -------------------------------
# Enhanced Single Persona Answer with Confidence
# -------------------------------
def single_persona_answer_with_confidence(podcast: str, query: str):
    """
    Enhanced single persona function that returns confidence metadata and ensures transparency.
    """
    scenario_type = detect_scenario_type(query)
    
    # Get relevant episodes
    episodes = get_relevant_episodes([podcast], query, 3)
    
    # Calculate confidence
    confidence = calculate_confidence(episodes, query)
    
    # Load persona
    persona_path = podcast_artifacts(podcast)["persona"]
    persona = {}
    if Path(persona_path).exists():
        persona = json.loads(Path(persona_path).read_text(encoding="utf-8"))

    # Decide mode based on confidence
    use_creative_mode = confidence < 0.7  # Use creative mode if confidence is low
    
    if use_creative_mode:
        # Creative mode with strict transparency
        prompt = build_creative_prompt(persona, query, scenario_type)
        temperature = 0.9
        max_tokens = 700
        source_type = "creative"
    else:
        # Database mode
        context_text = ""
        for ep in episodes[:3]:
            context_text += f"Episode: {ep['title']}\n"
            if ep['text']:
                snippet = ep['text'][:600] + "..." if len(ep['text']) > 600 else ep['text']
                context_text += f"Content: {snippet}\n\n"
        
        prompt = build_prompt(persona, query, context_text, scenario_type)
        temperature = 0.8
        max_tokens = 800
        source_type = "database"

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        answer = clean_text_output(response.choices[0].message.content)
        answer = answer.replace('\\n\\n', '\n\n').replace('\\n', '\n')
        
        return {
            "answer": answer,
            "confidence": confidence,
            "source": source_type,
            "explanation": get_confidence_explanation(episodes, confidence),
            "episodes_count": len(episodes),
            "highest_score": max([ep.get('score', 0) for ep in episodes]) if episodes else 0,
            "scenario_type": scenario_type,
            "metadata": {
                "episodes_used": [{"title": ep["title"], "score": ep["score"]} for ep in episodes],
                "processing_mode": "creative" if use_creative_mode else "content_based",
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        return {
            "answer": f"Oh, what a wonderful question! As your host here at {persona.get('podcast_name', 'The Hospitality Expert')}, I'd love to dive deep into that topic with you. Pull up a chair by the fire - though I'm having a bit of technical trouble accessing my podcast treasure chest right now. How about we try that question again in just a moment?",
            "confidence": 0.0,
            "source": "error",
            "explanation": "Technical error occurred",
            "episodes_count": len(episodes),
            "highest_score": 0,
            "scenario_type": scenario_type,
            "error": str(e)
        }


# -------------------------------
# Enhanced Single Persona Answer (Backward Compatible)
# -------------------------------
def single_persona_answer(podcast: str, query: str):
    """
    Original function - returns just the answer for backward compatibility.
    Use single_persona_answer_with_confidence() for enhanced features.
    """
    result = single_persona_answer_with_confidence(podcast, query)
    return result["answer"]


# -------------------------------
# Enhanced Multi Persona Debate with Anti-Fabrication Logic
# -------------------------------
def multi_persona_debate_with_confidence(podcasts: list[str], query: str):
    """
    Enhanced multi persona function that prevents fabrication of non-existent discussions.
    """
    scenario_type = detect_scenario_type(query)

    # Handle historical queries
    if any(term in query.lower() for term in ['2023', '2022', '2021', 'before 2024', 'pre-2024']):
        return {
            "synthesis": "Oh, I'd love to spill tea from those earlier years, but my podcast treasure chest starts in May 2024! How about we explore what's been buzzing in hospitality since then?",
            "individual_responses": [],
            "insights_count": 0,
            "scenario_type": "edge_case",
            "confidence": 1.0,
            "source": "system_boundary",
            "explanation": "Query outside available data range"
        }

    # Gather episodes across all podcasts
    all_episodes = get_relevant_episodes(podcasts, query, 10)
    
    # Calculate overall confidence
    overall_confidence = calculate_confidence(all_episodes, query)
    
    # Individual responses with confidence
    individual_responses = []
    for podcast in podcasts:
        try:
            podcast_result = single_persona_answer_with_confidence(podcast, query)
            individual_responses.append({
                "podcast": podcast,
                "response": podcast_result["answer"],
                "confidence": podcast_result["confidence"],
                "source": podcast_result["source"]
            })
        except Exception:
            individual_responses.append({
                "podcast": podcast,
                "response": f"Having trouble accessing {podcast} insights right now.",
                "confidence": 0.0,
                "source": "error"
            })

    # CRITICAL: Check if we should skip synthesis to prevent fabrication
    if should_skip_synthesis(individual_responses):
        # Return a simple, honest response instead of fake synthesis
        simple_response = generate_simple_creative_response(query, podcasts)
        
        return {
            "synthesis": simple_response,
            "individual_responses": individual_responses,
            "insights_count": len([r for r in individual_responses if r["confidence"] > 0]),
            "scenario_type": scenario_type,
            "episodes_referenced": len(all_episodes),
            "confidence": 0.0,  # Low confidence since it's creative
            "source": "simple_creative",
            "explanation": "Topic not covered in podcast episodes - providing general response",
            "metadata": {
                "synthesis_skipped": True,
                "reason": "All responses were creative mode - preventing fabrication of non-existent discussions",
                "timestamp": datetime.now().isoformat()
            }
        }

    # If we reach here, we have genuine episode content to synthesize
    synthesis_context = ""
    for resp in individual_responses:
        if "trouble accessing" not in resp["response"]:
            synthesis_context += f"{resp['podcast']}: {resp['response']}\n\n"

    # Create synthesis based on actual content
    episode_context = ""
    for ep in all_episodes[:5]:
        episode_context += f"From {ep['podcast']} - {ep['title']}: {ep['text'][:500]}...\n\n"

    synthesis_prompt = f"""
You are The Curious Concierge synthesizing insights from actual podcast episodes.

The podcasters have discussed: {query}

Individual perspectives (based on recent episodes):
{synthesis_context}

Relevant episode content:
{episode_context}

Create a warm synthesis based on actual podcast content that:
1. Identifies shared themes from episode discussions
2. Highlights unique perspectives from different shows
3. Includes specific quotes or insights from episodes when possible
4. Provides actionable recommendations
5. Maintains your fireside chat personality

Scenario type: {scenario_type}
FORMATTING: Write in plain text with natural paragraph breaks.
"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": synthesis_prompt}],
            temperature=0.8,
            max_tokens=800
        )
        synthesis = clean_text_output(response.choices[0].message.content)
    except Exception:
        synthesis = "What a fascinating question! I'm having a bit of trouble accessing all my podcast notes right now, but I can tell there are some rich perspectives across these shows."

    successful_responses = len([r for r in individual_responses if r["confidence"] > 0])

    response_data = {
        "synthesis": synthesis,
        "individual_responses": individual_responses,
        "insights_count": successful_responses,
        "scenario_type": scenario_type,
        "episodes_referenced": len(all_episodes),
        "confidence": overall_confidence,
        "source": "database",
        "explanation": get_confidence_explanation(all_episodes, overall_confidence),
        "metadata": {
            "total_episodes_found": len(all_episodes),
            "average_individual_confidence": sum(r["confidence"] for r in individual_responses) / len(individual_responses) if individual_responses else 0,
            "processing_mode": "content_based",
            "synthesis_skipped": False,
            "timestamp": datetime.now().isoformat()
        }
    }

    return apply_final_cleaning(response_data)


# -------------------------------
# Enhanced Multi Persona Debate (Backward Compatible)
# -------------------------------
def multi_persona_debate(podcasts: list[str], query: str):
    """
    Original function - returns standard format for backward compatibility.
    Use multi_persona_debate_with_confidence() for enhanced features.
    """
    result = multi_persona_debate_with_confidence(podcasts, query)
    
    # Return in original format
    return {
        "synthesis": result["synthesis"],
        "individual_responses": [
            {"podcast": r["podcast"], "response": r["response"]} 
            for r in result["individual_responses"]
        ],
        "insights_count": result["insights_count"],
        "scenario_type": result["scenario_type"],
        "episodes_referenced": result["episodes_referenced"]
    }


# -------------------------------
# Testing Functions
# -------------------------------
def test_anti_fabrication():
    """Test the anti-fabrication logic."""
    # Simulate creative mode responses
    creative_responses = [
        {
            "podcast": "Test1",
            "response": "While this hasn't come up in our recent episodes, I can share some thoughts...",
            "confidence": 0.1,
            "source": "creative"
        },
        {
            "podcast": "Test2", 
            "response": "This topic hasn't been a focus of our podcast lately, but from my experience...",
            "confidence": 0.2,
            "source": "creative"
        }
    ]
    
    # Test if synthesis should be skipped
    skip_result = should_skip_synthesis(creative_responses)
    print(f"Should skip synthesis for creative responses: {skip_result}")
    
    # Simulate content-based responses
    content_responses = [
        {
            "podcast": "Test1",
            "response": "In our recent episode about hotel trends, we discussed...",
            "confidence": 0.8,
            "source": "database"
        }
    ]
    
    skip_result2 = should_skip_synthesis(content_responses)
    print(f"Should skip synthesis for content responses: {skip_result2}")

# Uncomment to test:
# test_anti_fabrication(