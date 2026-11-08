import json
import requests
import time
import re
from datetime import datetime
# Import Config MODULE to allow dynamic attribute access
import msr_engine.config as cfg
# Import Static Constants (these don't change per project)
from .config import (
    OLLAMA_URL, OLLAMA_MODEL,
    MAX_WORDS_PER_DIALOGUE, CHARACTER_MAP, DURATION_OPTIONS,
    LANGUAGES, DEFAULT_LANGUAGE
)
from .utils import console

class StoryboardGenerationError(Exception):
    """Raised when script generation fails after all retries."""
    pass

def _call_ollama_simple(prompt_text, max_tokens=2048, temperature=0.7):
    """
    Unified Chat-based caller for ALL Ollama interactions.
    Handles Thinking Models by allocating sufficient tokens.
    Uses /api/chat instead of /api/generate for better compatibility with Qwen models.
    """
    try:
        target_model = OLLAMA_MODEL
        
        # Construct messages for Chat API
        messages = [
            {
                "role": "system", 
                "content": "You are a helpful AI assistant specialized in screenwriting. Output ONLY valid JSON or requested text. Do not include markdown fences."
            },
            {
                "role": "user", 
                "content": prompt_text
            }
        ]
        
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens, # Generous limit for thinking + output
                "top_p": 0.95
            }
        }
        
        console.print(f"[dim]📡 Sending Chat Request to {target_model} (Max Tokens: {max_tokens})...[/dim]")
        
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
        
        if resp.status_code != 200:
            console.print(f"[red]❌ Ollama HTTP Error {resp.status_code}[/red]")
            console.print(f"[dim]Response Body: {resp.text[:500]}[/dim]")
            return None
            
        data = resp.json()
        
        if "message" not in data:
            console.print(f"[red]❌ Unexpected Response Structure: {data.keys()}[/red]")
            return None
            
        message_obj = data["message"]
        response_text = message_obj.get("content", "").strip()
        thinking_content = message_obj.get("thinking", "")
        
        if thinking_content:
            console.print(f"[dim]💭 Thought Process Length: {len(thinking_content)} chars[/dim]")
            
        if not response_text:
            console.print(f"[yellow]⚠ Ollama returned EMPTY content after thinking.[/yellow]")
            console.print(f"[dim]Raw Message Keys: {list(message_obj.keys())}[/dim]")
            return None
             
        return response_text

    except Exception as e:
        console.print(f"[bold red]💥 CRITICAL Ollama Connection Error: {type(e).__name__} - {str(e)}[/bold red]")
        import traceback
        traceback.print_exc()
        return None

def _parse_llm_json(raw_text: str) -> dict:
    """
    Robustly parses JSON from LLM output, stripping markdown fences if present.
    Raises ValueError if parsing fails.
    """
    if not raw_text:
        raise ValueError("Empty response received.")
    
    clean_text = raw_text.strip()
    
    # Strip Markdown Code Blocks
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
        
    clean_text = clean_text.strip()
    
    # Find JSON bounds just in case there's extra text
    start_idx = clean_text.find('{')
    end_idx = clean_text.rfind('}')
    
    if start_idx == -1 or end_idx == -1:
        raise ValueError("No valid JSON object found in response.")
        
    json_str = clean_text[start_idx:end_idx+1]
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e}")

def generate_global_refs_from_map(title, style, num_clips, user_char_map, language_code="en", mode="full"):
    """
    Generates Global References using MANUAL GENDER INPUT from GUI.
    NO VLM ANALYSIS.
    
    Args:
        user_char_map: Dict where keys are roles ('hero', 'villain') and values are dicts:
                       {'filename': 'path/to/img.jpg', 'gender': 'Male'|'Female'|'Non-Binary'}
    """
    console.rule("STEP 1: GENERATING GLOBAL REFS (MANUAL INPUT)")
    char_descriptions = {}
    
    # 1. Build Descriptions from User Input (Gender + Role)
    # Since we removed VLM, we construct simple descriptive strings based on gender
    for role, metadata in user_char_map.items():
        gender = metadata.get('gender', 'Male')
        filename = metadata.get('filename', '')
        
        # Create a basic description placeholder. 
        # In a real scenario, you might let users type custom descriptions too, 
        # but for now, we derive it from role+gender.
        desc = f"A {gender.lower()} character playing the role of {role.capitalize()}."
        char_descriptions[role] = desc

    # 2. Build Global Refs String
    image_lines = []
    audio_lines = []
    img_counter = 1
    
    sorted_roles = sorted(char_descriptions.keys(), key=lambda x: (x != 'hero', x))
    
    for role in sorted_roles:
        desc = char_descriptions[role]
        image_lines.append(f"Image {img_counter}: {desc}")
        
        # Voice Assignment based on Manual Gender
        gender = user_char_map[role].get('gender', 'Male')
        if gender == "Female":
            voice = "Female voice"
        elif gender == "Non-Binary":
            voice = "Neutral voice"
        else:
            voice = "Male voice"
            
        audio_lines.append(f"Audio {img_counter}: {voice}, belongs only to Image {img_counter}.")
        img_counter += 1

    # Environment Description (Text Model)
    env_prompt = f"Describe a generic cinematic environment for '{title}'. One sentence. Photorealistic."
    env_desc = _call_ollama_simple(env_prompt, max_tokens=512, temperature=0.3) or "Cinematic interior, dramatic lighting."
    image_lines.append(f"Image {img_counter}: Scene, {env_desc}")
    
    global_refs = "\n\n".join(image_lines + audio_lines)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    g_path = cfg.PROMPTS_DIR / f"global_refs_{ts}.txt"
    with open(g_path, "w", encoding="utf-8") as f:
        f.write(global_refs)
        
    console.print(f"[green]✓ Global Refs Saved: {g_path.name}[/green]")
    return global_refs, char_descriptions

def generate_narrative_script(title, style, num_clips, clip_duration, language_code="en", available_roles=None, genres=None):
    """
    DETERMINISTIC SCRIPT GENERATION WITH GENRE CONTEXT.
    Filters locations based on selected genres.
    """
    console.rule("STEP 2A: GENERATING NARRATIVE SCRIPT (GENRE-AWARE)")
    lang_name = LANGUAGES.get(language_code, "English")
    
    if not available_roles:
        available_roles = ["hero"]
    if not genres:
        genres = ["Action"] # Default
        
    # --- GENRE-SPECIFIC LOCATION POOLS ---
    genre_locations_map = {
        "Action": ["Explosive Construction Site", "High-Speed Highway Chase", "Rooftop Parkour Course", "Abandoned Warehouse Fight"],
        "Sci-Fi": ["Neon-Lit Cyberpunk Street", "Zero-G Space Station Corridor", "Alien Planet Surface", "Holographic Command Center"],
        "Fantasy": ["Ancient Dragon's Lair", "Enchanted Forest Clearing", "Floating Castle Spire", "Mystical Rune Circle"],
        "Horror": ["Dark Abandoned Hospital Hallway", "Foggy Graveyard at Midnight", "Creepy Victorian Manor Basement", "Isolated Cabin in Snowstorm"],
        "Romance": ["Sunset Beach Boardwalk", "Cozy Rainy Cafe Interior", "Parisian Balcony at Night", "Autumn Park Bench"],
        "Comedy": ["Chaotic Office Breakroom", "Slippery Banana Peel Street Corner", "Awkward Dinner Party Table", "Misunderstanding in Elevator"],
        "Thriller": ["Dimly Lit Interrogation Room", "Surveillance Van Interior", "Crowded Subway Platform Rush Hour", "Empty Parking Garage at 3 AM"],
        "Drama": ["Courtroom Gallery", "Hospital Waiting Room", "Family Living Room Argument", "Rain-Soaked Cemetery Funeral"],
        "Anime": ["Shibuya Crossing Night", "Dojo Training Grounds", "School Rooftop Sunset", "Mech Hangar Bay"],
        "Classic": ["Black and White Film Noir Street", "Grand Ballroom Dance Floor", "Vintage Car Drive Through Countryside", "Library Study Desk"],
        "Sports": ["Stadium Arena Crowd View", "Locker Room Pre-Game Huddle", "Gym Weightlifting Area", "Outdoor Tennis Court Match Point"],
        "Kids": ["Colorful Playground Slide", "Magical Toy Store Aisle", "Cartoon Animal Forest Path", "Birthday Party Backyard"],
        "Music": ["Concert Stage Spotlights", "Recording Studio Booth", "Backstage Dressing Room Chaos", "Street Busker Corner"],
        "Crime": ["Police Precinct Bullpen", "Heist Vault Door Mechanism", "Alleyway Drug Deal Shadow", "Detective's Cluttered Desk"],
        "Documentary": ["Nature Reserve Observation Blind", "Urban Street Interview Setup", "Historical Archive Room", "Industrial Factory Floor Tour"]
    }
    
    # Merge pools for selected genres
    active_locations = []
    for g in genres:
        if g in genre_locations_map:
            active_locations.extend(genre_locations_map[g])
            
    # Fallback if somehow empty
    if not active_locations:
        active_locations = ["Cinematic Urban Setting", "Natural Landscape Vista"]

    times_pool = ["Day", "Night", "Dusk", "Dawn", "Golden Hour", "Midnight"]
    
    scenes_data = []
    
    # Build Skeleton
    for i in range(1, num_clips + 1):
        main_char = available_roles[(i - 1) % len(available_roles)]
        sec_chars = []
        if len(available_roles) > 1:
            sec_idx = (i) % len(available_roles)
            if available_roles[sec_idx] != main_char:
                sec_chars.append(available_roles[sec_idx])
                
        loc = active_locations[(i - 1) % len(active_locations)]
        tod = times_pool[(i - 1) % len(times_pool)]
        
        scenes_data.append({
            "scene_id": i,
            "main_character": main_char,
            "secondary_characters": sec_chars,
            "location": loc,
            "time_of_day": tod,
            "plot_point": "",      
            "dialogue_snippet": "", 
            "visual_state_end": ""  
        })

    console.print(f"[cyan]Filling creative content for {num_clips} scenes...[/cyan]")
    console.print(f"[dim]→ Active Genres: {', '.join(genres)}[/dim]")
    
    # Fill Content via Ollama
    for idx, scene in enumerate(scenes_data):
        if idx >= num_clips: break 
        
        main_c = scene['main_character'].capitalize()
        sec_c_list = [s.capitalize() for s in scene['secondary_characters']]
        sec_str = f" and {', '.join(sec_c_list)}" if sec_c_list else ""
        location = scene['location']
        tod = scene['time_of_day']
        
        success = False
        last_error = None
        
        for attempt in range(2):
            temp = 0.8 if attempt == 0 else 0.5 
            
            # INJECT GENRES INTO PROMPT
            genres_str = ", ".join(genres)
            
            prompt = f"""You are a Professional Screenwriter. Write a brief cinematic beat for a {style} video.
Movie Title: "{title}"
Primary Genres: {genres_str}

Scene Context:
Characters: {main_c}{sec_str}
Location: {location}
Time: {tod}
Language: {lang_name} ({language_code})

Requirements:
1. 'plot_point': Describe ONE specific physical action or interaction. 
   - CRITICAL: The action MUST fit the tone of [{genres_str}]. 
   - Example: If Horror, focus on tension/fear. If Comedy, focus on slapstick/misunderstanding.
   - Max 2 sentences. Be vivid.
   
2. 'dialogue_snippet': Provide ONE line of dialogue spoken by {main_c}. Max 10 words. 
   - MUST BE IN {lang_name}. 
   - Tone must match [{genres_str}].
   
3. 'visual_state_end': Describe the final frame composition.

Output ONLY a valid JSON object with keys: plot_point, dialogue_snippet, visual_state_end. No markdown."""

            try:
                raw_response = _call_ollama_simple(prompt, max_tokens=2048, temperature=temp)
                
                if not raw_response:
                    raise ValueError("Ollama returned empty response.")
                
                content_data = _parse_llm_json(raw_response)
                
                if 'plot_point' not in content_data or 'dialogue_snippet' not in content_data:
                    raise KeyError("Missing required keys.")
                
                scene['plot_point'] = content_data['plot_point']
                scene['dialogue_snippet'] = content_data['dialogue_snippet']
                scene['visual_state_end'] = content_data.get('visual_state_end', 'Fade out.')
                
                success = True
                break
                
            except Exception as e:
                last_error = e
                console.print(f"[yellow]⚠ Scene {idx+1} Attempt {attempt+1} Failed: {str(e)}[/yellow]")
                time.sleep(1)
        
        if not success:
            raise StoryboardGenerationError(f"Failed to generate script for Scene {idx+1}. Last Error: {last_error}")

    console.print(f"[green]✓ Script Complete: All {num_clips} scenes filled creatively.[/green]")
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_path = cfg.SCRIPTS_DIR / f"narrative_script_{ts}.json"
    final_script = {"scenes": scenes_data}
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(final_script, f, indent=2, ensure_ascii=False)
        
    return scenes_data

def generate_sequential_prompts(global_refs, scenes_structure, title, style, clip_duration, mode="full", char_map=None, language_code="en"):
    """
    Generates MULTI-SHOT Local Prompts for LTX-2.5.
    Splits the scene action into 2-4 distinct camera shots based on duration.
    Maps Roles -> Image Tags dynamically.
    """
    console.rule("STEP 2B: GENERATING MULTI-SHOT LOCAL PROMPTS")
    final_prompts_list = []
    
    # 1. Build Role -> Image Tag Map from Global Refs
    role_to_image_tag = {}
    if char_map:
        sorted_roles = sorted(char_map.keys(), key=lambda x: (x != 'hero', x))
        for i, role in enumerate(sorted_roles):
            role_to_image_tag[role.lower()] = f"Image {i+1}"
    else:
        role_to_image_tag['hero'] = "Image 1"
        
    console.print(f"[dim]→ Role Mapping: {role_to_image_tag}[/dim]")
    
    # Define Shot Templates for Variety
    SHOT_ANGLES = [
        "Wide establishing shot, showing full environment",
        "Medium shot, waist-up framing, focus on character interaction",
        "Close-up shot, extreme detail on facial expression and eyes",
        "Low angle dynamic shot, emphasizing power and movement",
        "Over-the-shoulder perspective, intimate dialogue framing",
        "Tracking shot, moving alongside the subject"
    ]

    prev_context_summary = "" 
    
    for i, scene in enumerate(scenes_structure, 1):
        console.print(f"[cyan]Generating Multi-Shot Prompt for Scene {i}...[/cyan]")
        
        main_char_raw = scene.get('main_character', 'hero').lower()
        sec_chars_raw = [sc.lower() for sc in scene.get('secondary_characters', [])]
        dialogue = scene.get('dialogue_snippet', '')
        location = scene.get('location', 'Unknown Location')
        plot_action = scene.get('plot_point', 'Action happens.')
        visual_end = scene.get('visual_state_end', 'Fade out.')
        
        # 2. Resolve Roles to Tags
        main_tag = role_to_image_tag.get(main_char_raw, "Image 1")
        sec_tags = [role_to_image_tag.get(sc, None) for sc in sec_chars_raw if role_to_image_tag.get(sc)]
        sec_tags = [t for t in sec_tags if t] # Filter out Nones
        
        # 3. Determine Number of Shots Based on Duration
        # Rule of thumb: ~5 seconds per distinct shot for good pacing in AI video
        num_shots = max(2, min(4, int(clip_duration / 5)))
        
        # 4. Split Plot Action into Sub-beats
        # Simple heuristic: If there's dialogue, put it in the middle/end shot.
        # Otherwise, split the sentence by commas or periods.
        beats = []
        if '.' in plot_action:
            parts = [p.strip() for p in plot_action.split('.') if p.strip()]
        elif ',' in plot_action:
            parts = [p.strip() for p in plot_action.split(',') if p.strip()]
        else:
            parts = [plot_action]
            
        # Ensure we have enough beats for the number of shots
        while len(parts) < num_shots:
            parts.append("Continuing motion.") # Filler
            
        # Trim to exact number of shots
        parts = parts[:num_shots]
        
        # 5. Construct Individual Shot Descriptions
        shot_descriptions = []
        time_step = round(clip_duration / num_shots, 1)
        
        for s_idx, beat_text in enumerate(parts):
            # Select Camera Angle cyclically
            angle_desc = SHOT_ANGLES[s_idx % len(SHOT_ANGLES)]
            
            # Sanitize Beat Text (Replace Role Names with Tags)
            sanitized_beat = beat_text
            for role, tag in role_to_image_tag.items():
                pattern = rf'\b{re.escape(role)}\b'
                sanitized_beat = re.sub(pattern, tag, sanitized_beat, flags=re.IGNORECASE)
                
            # Add Spatial Context if applicable
            spatial_note = ""
            if s_idx == 0:
                spatial_note = f"{main_tag} is CENTER FRAME."
            elif sec_tags:
                spatial_note = f"{sec_tags[0]} visible in background."
                
            # Combine into a cohesive shot line
            shot_line = f"Shot {s_idx+1} [{angle_desc}]: {sanitized_beat}. {spatial_note}"
            shot_descriptions.append(shot_line)
            
        # 6. Assemble FINAL MULTI-SHOT PROMPT TEMPLATE
        # Structure: 
        # - Global Style Anchor
        # - Sequential Shot List
        # - Dialogue Injection (if any)
        # - Technical Specs
        
        shots_block = "\n".join(shot_descriptions)
        
        audio_line = ""
        if dialogue:
            speaker_tag = main_tag
            try:
                audio_idx = int(speaker_tag.split()[1]) # Extract number from "Image 1"
                # Place dialogue in the last shot typically, or distribute if complex
                audio_line = f"\nDialogue in Final Shot ({speaker_tag}): '{dialogue}'."
            except IndexError:
                pass # Skip if malformed tag

        template = f"""Cinematic Video Generation Instructions for LTX-2.5:
Style: {style}, Photorealistic, 8K, High Detail.
Setting: {location}.
Duration: {clip_duration} seconds.

SEQUENCE OF SHOTS:
{shots_block}

{audio_line}

CONSTRAINTS:
- Maintain consistent character identity across all shots using reference images.
- Smooth transitions between camera angles.
- Lighting must remain consistent throughout the sequence.
- No subtitles, no watermarks.
- Motion blur appropriate for realistic speed.

TECHNICAL SPECS:
Camera: Dynamic movement matching shot descriptions.
Lighting: Cinematic, dramatic, volumetric fog if outdoor night.
Render Quality: Ultra-high fidelity, ray-traced reflections."""

        final_prompt = template.strip()
        
        l_path = cfg.PROMPTS_DIR / f"prompt_scene_{i:03d}_multishot.txt"
        with open(l_path, "w", encoding="utf-8") as f:
            f.write(final_prompt)
            
        # Store tuple: (index, path, global_ref_unused, local_prompt, scene_data)
        final_prompts_list.append((i, l_path, "", final_prompt, scene))
        
    return final_prompts_list

def get_required_characters(scenes_structure):
    """Extracts unique character roles from the narrative script."""
    roles = set()
    for scene in scenes_structure:
        char = scene.get('main_character', 'hero')
        if char: roles.add(char.lower())
        # Also check secondary
        for sc in scene.get('secondary_characters', []):
            roles.add(sc.lower())
    return list(roles)