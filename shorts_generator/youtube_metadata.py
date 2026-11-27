import os
import json
from shorts_generator.highlights import _execute_with_fallback
from shorts_generator.logger import ui_logger

def generate_youtube_metadata(clip_metadata: dict, llm_path: str, session_id: str = "global") -> dict:
    """
    Generates YouTube Shorts metadata (Title, Description, Tags, Pinned Comment)
    using the provided LLM.
    """
    if not llm_path or not llm_path.startswith("api:"):
        return {}
        
    system = "You are an expert YouTube Shorts strategist and copywriter. Output ONLY raw JSON. No markdown."
    
    clip_title = clip_metadata.get("title", "")
    hook_text = clip_metadata.get("hook_text", "")
    hook_type = clip_metadata.get("hook_type", "curiosity_gap")
    reasoning = clip_metadata.get("virality_reason", "")
    transcript = clip_metadata.get("transcript", "")
    persona = clip_metadata.get("persona", {})
    genre = persona.get("genre", "Unknown")
    
    creator_name = clip_metadata.get("campaign_creator_name", "")
    creator_handle = clip_metadata.get("campaign_handle", "")
    
    if creator_handle.startswith("@"):
        creator_handle = creator_handle[1:]
        
    source_line = f"Source: @{creator_handle}" if creator_handle else ""
    
    desc_middle = ""
    if source_line:
        desc_middle = f"\\n\\n{source_line}"
        
    desc_template = f"Engaging 2-3 sentence description about the clip's topic{desc_middle}\\n\\nHashtags"
    
    prompt = (
        "Generate the metadata package for this YouTube Short.\n\n"
        "Return ONLY a JSON object with this exact schema:\n"
        "{\n"
        '  "yt_title": "Max 60 chars. Must be punchy and contain high-traffic SEO keywords related to the topic.",\n'
        f'  "yt_description": "{desc_template}",\n'
        '  "yt_tags": "Comma separated 3-tier mix of tags (broad, niche, specific)",\n'
        '  "yt_pinned_comment": "2-3 sentence extension of the thought matching the hook_type to drive engagement. MUST end with the exact warning: \'Warning: comment on posts with 1k+ views only.\'"\n'
        "}\n\n"
        f"Clip Details:\n"
        f"Internal Title: {clip_title}\n"
        f"Genre: {genre}\n"
        f"Hook Used: {hook_text} ({hook_type})\n"
        f"Virality Reason: {reasoning}\n"
        f"Transcript:\n{transcript}\n"
    )
    
    ui_logger.log("Generating YouTube metadata package...")
    try:
        results = _execute_with_fallback(llm_path, system, prompt, max_tokens=1000, session_id=session_id)
        if isinstance(results, list) and len(results) > 0:
            return results[0]
        if isinstance(results, dict):
            return results
    except Exception as e:
        ui_logger.log(f"Failed to generate YouTube metadata: {e}")
    
    return {}
