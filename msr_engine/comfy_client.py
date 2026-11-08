import json
import copy
import requests
import time
import random
from pathlib import Path
from .config import COMFYUI_URL, WORKFLOW_NODE_IDS, ASPECT_RATIOS, TARGET_MEGAPIXELS, IMAGE_NODES
from .utils import console

def _get_node(wf, target_id):
    """Helper to find node ignoring trailing spaces in JSON keys."""
    clean_target = str(target_id).strip()
    for k in wf.keys():
        if str(k).strip() == clean_target:
            return wf[k]
    return None

def upload_image(image_path):
    """Uploads image to ComfyUI and returns the stored filename."""
    try:
        with open(image_path, 'rb') as f:
            files = {'image': (Path(image_path).name, f)}
            resp = requests.post(f"{COMFYUI_URL}/upload/image", files=files, timeout=(10, 300))
            if resp.status_code == 200:
                return resp.json().get("name")
    except Exception as e:
        console.print(f"[red]Upload failed: {e}[/red]")
    return None

def prepare_workflow(workflow_json, global_prompt, local_prompt, image_map, aspect_ratio_key="16:9", clip_duration=10, num_chars_max=2, scene_data=None):
    """
    SMART INJECTION: Determines which 2 images to use based on scene_data.
    Uses Dummy Image for bypassed nodes to satisfy ComfyUI Validation.
    
    Args:
         workflow_json: The base ComfyUI workflow dict.
         global_prompt: Unused (we inject neutral anchor).
         local_prompt: The action prompt string.
         image_map: Dict {role_name: stored_filename} e.g., {'hero': 'img1.png', 'villain': 'img2.png'}
                    NOTE: Keys should be treated case-insensitively.
         aspect_ratio_key: String like "16:9".
         clip_duration: Integer seconds.
         num_chars_max: Hard limit of nodes available (usually 2).
         scene_data: Dict containing 'main_character' and 'secondary_characters'.
     """
    wf = copy.deepcopy(workflow_json)
    
    # 1. Normalize Image Map Keys to Lowercase for robust matching
    normalized_image_map = {k.lower(): v for k, v in image_map.items()}
    
    # 2. Determine Active Characters for THIS SCENE
    active_roles_for_scene = []
    if scene_data:
        main_char = scene_data.get('main_character', '').lower()
        sec_chars = [sc.lower() for sc in scene_data.get('secondary_characters', [])]
        
        # Add main character first if it exists in our map
        if main_char and main_char in normalized_image_map:
            active_roles_for_scene.append(main_char)
            
        # Add secondary characters (limit to fit remaining slots)
        for sc in sec_chars:
            if sc in normalized_image_map and sc != main_char:
                active_roles_for_scene.append(sc)
                
    # Fallback: If no scene data or empty map, just take first available roles up to max
    if not active_roles_for_scene:
        all_available = list(normalized_image_map.keys())
        active_roles_for_scene = all_available[:num_chars_max]
        
    # Strictly limit to 2 slots (Node 28 and 29)
    final_injections = active_roles_for_scene[:2]
    console.print(f"[cyan]→ Scene Cast Resolution: {final_injections}[/cyan]")
    
    # 3. Identify a "Dummy" Image for Bypassed Nodes
    # We MUST provide a valid filename to every LoadImage node to pass ComfyUI Validation.
    # We use the first available image from our map as the universal dummy.
    dummy_image = list(normalized_image_map.values())[0] if normalized_image_map else "default.png"
    
    # 4. Inject Images into Nodes 28 and 29
    node_28_id = IMAGE_NODES.get(1) # Should be "28"
    node_29_id = IMAGE_NODES.get(2) # Should be "29"
    
    node_28 = _get_node(wf, node_28_id)
    node_29 = _get_node(wf, node_29_id)
    
    if not node_28 or not node_29:
        console.print("[bold red]ERROR: Could not find Node 28 or 29 in workflow template.[/bold red]")
        raise ValueError("Workflow template missing required Image Loader nodes.")

    # --- Handle PIC 1 (Node 28 - Main Character) ---
    if len(final_injections) >= 1:
        role_1 = final_injections[0]
        filename_1 = normalized_image_map[role_1]
        
        # Set Image
        node_28["inputs"]["image"] = filename_1
        
        # Ensure it is ACTIVE (remove bypass if present)
        if "bypass" in node_28:
            del node_28["bypass"]
            
        console.print(f"[dim]→ PIC 1 (Node {node_28_id}): {role_1} ({filename_1})[/dim]")
    else:
        # No primary character found? Use Dummy and Bypass
        node_28["inputs"]["image"] = dummy_image # CRITICAL: Set valid image
        node_28["bypass"] = True
        console.print(f"[yellow]⚠ PIC 1 (Node {node_28_id}): BYPASSED (Using Dummy)[/yellow]")

    # --- Handle PIC 2 (Node 29 - Secondary Character) ---
    if len(final_injections) >= 2:
        role_2 = final_injections[1]
        filename_2 = normalized_image_map[role_2]
        
        # Set Image
        node_29["inputs"]["image"] = filename_2
        
        # Ensure it is ACTIVE (remove bypass if present)
        if "bypass" in node_29:
            del node_29["bypass"]
            
        console.print(f"[dim]→ PIC 2 (Node {node_29_id}): {role_2} ({filename_2})[/dim]")
    else:
        # Only 1 character in scene (or none). USE DUMMY IMAGE AND BYPASS.
        # This prevents "Invalid image file" error because ComfyUI validates inputs 
        # even on bypassed nodes during graph construction.
        node_29["inputs"]["image"] = dummy_image # CRITICAL: Set valid image
        node_29["bypass"] = True
        console.print(f"[dim]→ PIC 2 (Node {node_29_id}): BYPASSED (Single Char Scene - Using Dummy)[/dim]")

    # 5. Inject Prompts & Parameters
    
    # Global Prompt Node
    global_node = _get_node(wf, WORKFLOW_NODE_IDS["GLOBAL_PROMPT_NODE_ID"])
    if global_node:
        # Neutral style anchor. Identity comes strictly from Images.
        neutral_prompt = "Photorealistic cinematic style, realistic texture, high fidelity, 8k resolution, consistent lighting."
        global_node["inputs"]["string"] = neutral_prompt
        
    # Local Prompt Node
    local_node = _get_node(wf, WORKFLOW_NODE_IDS["LOCAL_PROMPT_NODE_ID"])
    if local_node:
        local_node["inputs"]["string"] = local_prompt
        
    # Negative Prompt Node
    neg_node = _get_node(wf, WORKFLOW_NODE_IDS["NEGATIVE_PROMPT_NODE_ID"])
    if neg_node:
        neg_node["inputs"]["text"] = "subtitles, watermark, worst quality, blurry, jittery, distorted, inconsistent appearance"
        
    # Duration Node
    dur_node = _get_node(wf, WORKFLOW_NODE_IDS["DURATION_NODE_ID"])
    if dur_node:
        dur_node["inputs"]["value"] = clip_duration
        
    # Seed Nodes
    seed1_node = _get_node(wf, WORKFLOW_NODE_IDS["SEED_STAGE_1"])
    if seed1_node:
        seed1_node["inputs"]["noise_seed"] = random.randint(0, 2**32 - 1)
        
    seed2_node = _get_node(wf, WORKFLOW_NODE_IDS["SEED_STAGE_2"])
    if seed2_node:
        seed2_node["inputs"]["noise_seed"] = random.randint(0, 2**32 - 1)
        
    # Aspect Ratio Node (Hardcoded ID 101 based on previous analysis, adjust if needed)
    ar_node = _get_node(wf, "101")
    if ar_node:
        ar_map = {
            "16:9": "16:9 (Widescreen)",
            "9:16": "9:16 (Portrait Widescreen)",
            "1:1": "1:1 (Square)",
            "4:3": "4:3 (Standard)",
            "21:9": "21:9 (Ultrawide)"
        }
        ar_string = ar_map.get(aspect_ratio_key, "16:9 (Widescreen)")
        ar_node["inputs"]["aspect_ratio"] = ar_string
        ar_node["inputs"]["megapixels"] = TARGET_MEGAPIXELS
        
    return wf, None

def queue_and_wait(workflow, timeout=1800, is_cancelled=None):
    """
    Queues the workflow and waits for completion using efficient polling.
    Args:
         workflow: The ComfyUI workflow dict to queue.
         timeout: Max seconds to wait for the job to complete.
         is_cancelled: Optional callable; if it returns True the wait is aborted.
    """
    try:
        payload = {"prompt": workflow}
        resp = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)
        if resp.status_code != 200:
            console.print(f"[red]Queue Failed: {resp.text}[/red]")
            return None
            
        prompt_id = resp.json().get("prompt_id")
        console.print(f"[green]✅ Queued Job ID: {prompt_id}[/green]")
        
        start_time = time.time()
        while True:
            # Check for user cancellation first (most responsive)
            if is_cancelled is not None:
                cancelled = is_cancelled() if callable(is_cancelled) else bool(is_cancelled)
                if cancelled:
                    console.print("[yellow]⚠️ Generation cancelled by user; aborting wait...[/yellow]")
                    return None
                    
            # Check timeout
            if time.time() - start_time > timeout:
                console.print("[red]✗ Timeout waiting for job completion.[/red]")
                return None
                
            # Poll every 2 seconds
            time.sleep(2)
            try:
                hist_resp = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=5)
                if hist_resp.status_code != 200:
                    continue
                    
                history = hist_resp.json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    status = history[prompt_id].get("status", {})
                    
                    # Check for errors first
                    if status.get("status_str") == "error":
                        console.print("[red]✗ ComfyUI Execution Error[/red]")
                        messages = status.get("messages", [])
                        for msg in messages:
                            if msg[0] == "execution_error":
                                console.print(f"[red]Detail: {msg[1]}[/red]")
                        return None
                        
                    # Look for video output
                    for node_id, output in outputs.items():
                        if "videos" in output or "gifs" in output:
                            videos = output.get("videos", output.get("gifs", []))
                            if videos:
                                elapsed = int(time.time() - start_time)
                                console.print(f"[green]✓ Job Completed in {elapsed}s[/green]")
                                return videos[0]
                                
                    # If finished but no video found (edge case)
                    if status.get("completed"):
                         console.print("[yellow]⚠ Job marked complete but no video output found.[/yellow]")
                         return None
                         
            except Exception as e:
                console.print(f"[yellow]Poll warning: {e}[/yellow]")
                continue
                
    except Exception as e:
        console.print(f"[red]Queue/Wait Error: {e}[/red]")
        return None

def download_file(file_info, output_path):
    """Downloads the generated file."""
    try:
        filename = file_info.get("filename")
        subfolder = file_info.get("subfolder", "")
        file_type = file_info.get("type", "output")
        
        params = {"filename": filename, "subfolder": subfolder, "type": file_type}
        resp = requests.get(f"{COMFYUI_URL}/view", params=params, stream=True, timeout=(10, 300))
        
        if resp.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
    except Exception as e:
        console.print(f"[red]Download Error: {e}[/red]")
    return False