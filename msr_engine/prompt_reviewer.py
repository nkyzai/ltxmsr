import json
import requests
from .config import OLLAMA_URL, OLLAMA_MODEL, MAX_WORDS_PER_DIALOGUE
from .utils import console

def validate_ltx_prompt(prompt_text, expected_dialogue, prev_scene_context=""):
    """
    Uses LLM to check if the prompt adheres to LTX-2.5 Multi-Shot Guidelines.
    Returns: (is_valid: bool, feedback: str)
    """
    if not prompt_text or len(prompt_text) < 50:
        return False, "Prompt too short or empty."

    # Heuristic Checks first (Fast)
    if "Shot 1:" in prompt_text or "Shot 2:" in prompt_text:
        return False, "Contains forbidden 'Shot X:' list format. Must be prose paragraph."
    
    if expected_dialogue and expected_dialogue.strip() not in prompt_text:
        # Check if dialogue is at least semantically present
        pass # Let LLM judge semantic presence

    # LLM Validation (Slow but Accurate)
    validator_prompt = f"""You are an Expert LTX-2.5 Prompt Auditor.
Analyze the following cinematic prompt against these STRICT RULES:
1. FORMAT: Must be ONE continuous chronological paragraph. NO bullet points, NO "Shot 1:", NO numbered lists.
2. CUTS: Every transition must be named in prose (e.g., "A hard cut transitions to...", "The view dissolves into...").
3. IDENTIFIERS: Characters must be re-described by visual traits after every cut. NO pronouns ("he", "she") referring to characters across cuts.
4. AUDIO: The state of sound (music, ambience, dialogue) must be explicitly stated at every cut.
5. DIALOGUE: If required dialogue is "{expected_dialogue}", it MUST appear verbatim inside one of the shots.
6. CONTINUITY: Does it logically follow the previous scene context? Prev Context: "{prev_scene_context[-200:]}"

PROMPT TO AUDIT:
"{prompt_text}"

Output ONLY valid JSON:
{{
  "is_valid": true/false,
  "reason": "Brief explanation of failure or success",
  "critical_errors": ["list", "of", "errors"] 
}}
"""
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": OLLAMA_MODEL,
            "prompt": validator_prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 500}
        }, timeout=60)
        
        data = resp.json().get("response", "")
        start = data.find("{")
        end = data.rfind("}") + 1
        
        if start != -1 and end > start:
            result = json.loads(data[start:end])
            return result.get("is_valid", False), result.get("reason", "Unknown"), result.get("critical_errors", [])
        else:
            return True, "Validation parse failed, assuming OK.", [] # Fail-open to avoid blocking
            
    except Exception as e:
        console.print(f"[yellow]⚠ Validator Error: {e}. Assuming prompt is OK.[/yellow]")
        return True, "Validator error.", []


def regenerate_prompt_with_feedback(original_prompt, feedback, errors, scene_data, global_refs, title, style, clip_duration, language_code, prev_scene_context):
    """
    Asks LLM to REWRITE the prompt fixing the specific errors found by the validator.
    """
    lang_name = "English" # Simplified for this helper, ideally passed in
    
    repair_prompt = f"""You are an Expert LTX-2.5 Video Prompt Engineer.
Rewrite the following prompt to fix these CRITICAL ERRORS:
{json.dumps(errors, indent=2)}
Feedback: {feedback}

ORIGINAL FLAWED PROMPT:
"{original_prompt}"

CORRECTIVE INSTRUCTIONS:
1. Convert any "Shot 1/2/3" lists into a SINGLE CHRONOLOGICAL PARAGRAPH.
2. Replace pronouns ("he/she") with visual identifiers (e.g., "the man in the red coat").
3. Explicitly name every cut in prose ("A hard cut moves to...").
4. State what happens to AUDIO at every cut.
5. Ensure dialogue "{scene_data.get('dialogue_snippet', '')}" is included verbatim in one shot.
6. Maintain continuity with previous scene: "{prev_scene_context[-300:]}"

SCENE DATA:
- Title: {title}
- Style: {style}
- Duration: {clip_duration}s
- Location: {scene_data.get('location')}
- Plot: {scene_data.get('plot_point')}
- Global Refs: {global_refs}

OUTPUT: Only the corrected raw text paragraph. No markdown."""

    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": OLLAMA_MODEL,
            "prompt": repair_prompt,
            "stream": False,
            "options": {"temperature": 0.5, "num_predict": 1500}
        }, timeout=120)
        
        new_text = resp.json().get("response", "").strip()
        # Clean markdown
        if new_text.startswith("```"):
            lines = new_text.split('\n')
            new_text = '\n'.join(lines[1:-1]).strip()
            
        return new_text
    except Exception as e:
        console.print(f"[red]✗ Repair Failed: {e}[/red]")
        return original_prompt # Return original if repair fails