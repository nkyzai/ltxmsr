import sys
import os
import time
import json
import psutil
import traceback
import threading # CRITICAL: Added for review synchronization
from pathlib import Path

# Use pynvml for Python 3.12+ compatibility
try:
    from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetUtilizationRates, nvmlDeviceGetMemoryInfo, nvmlDeviceGetTemperature, NVML_TEMPERATURE_GPU, NVMLError
    HAS_NVML = True
except ImportError:
    HAS_NVML = False

from PySide6.QtCore import QObject, Signal, Slot, QThread

# Add parent dir to path to import msr_engine
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import msr_engine.config as cfg
from msr_engine.storyboarder import (
    generate_global_refs_from_map, 
    generate_narrative_script, 
    get_required_characters, 
    generate_sequential_prompts
)
from msr_engine.prompt_reviewer import validate_ltx_prompt, regenerate_prompt_with_feedback
from msr_engine.comfy_client import upload_image, prepare_workflow, queue_and_wait, download_file
from msr_engine.model_manager import prepare_for_ollama, cleanup_after_ollama, prepare_for_comfyui, cleanup_after_comfyui

class SystemMonitor(QThread):
    """Thread to monitor system stats every 1 second."""
    stats_updated = Signal(dict)
    
    def __init__(self):
        super().__init__()
        self._stop_flag = False
        self._paused = False  # Flag to pause monitoring during heavy gen

    def stop(self):
        """Request the monitor loop to exit cleanly."""
        self._stop_flag = True

    def pause(self):
        """Suspend statistics emission to save resources."""
        self._paused = True

    def resume(self):
        """Resume statistics emission."""
        self._paused = False

    def run(self):
        if HAS_NVML:
            try:
                nvmlInit()
            except NVMLError:
                pass

        while not self._stop_flag:
            if not self._paused:
                try:
                    cpu = psutil.cpu_percent()
                    ram = psutil.virtual_memory().percent
                    
                    gpu_load = 0
                    gpu_temp = 0
                    vram_used = 0
                    vram_total = 1
                    
                    if HAS_NVML:
                        try:
                            handle = nvmlDeviceGetHandleByIndex(0)
                            util = nvmlDeviceGetUtilizationRates(handle)
                            gpu_load = util.gpu
                            
                            mem = nvmlDeviceGetMemoryInfo(handle)
                            vram_used = mem.used / (1024 * 1024) # MB
                            vram_total = mem.total / (1024 * 1024) # MB
                            
                            gpu_temp = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
                        except NVMLError:
                            pass
                    
                    self.stats_updated.emit({
                        "cpu": cpu,
                        "ram": ram,
                        "gpu_load": gpu_load,
                        "gpu_temp": gpu_temp,
                        "vram_used": vram_used,
                        "vram_total": vram_total
                    })
                except Exception:
                    pass
            time.sleep(1)
        
        # Release the NVML driver handle on shutdown
        if HAS_NVML:
            try:
                nvmlShutdown()
            except Exception:
                pass

class GenerationWorker(QObject):
    log_signal = Signal(str, str)       # (level, message)
    progress_signal = Signal(int, int)  # (current_scene, total_scenes)
    finished_signal = Signal(bool, str) # (success, message)
    video_ready_signal = Signal(str)    # (path_to_video)
    pipeline_signal = Signal(str, int, str) # (scope, step_index, status)
    current_prompt_signal = Signal(str, str) # (scene_label, prompt_text)
    
    # NEW SIGNAL FOR REVIEW REQUEST
    # Emits: (scenes_data_list, global_refs_string, local_prompts_tuple_list)
    review_request_signal = Signal(list, str, list) 

    def __init__(self, config_data):
        super().__init__()
        self.config = config_data
        self.is_cancelled = False
        
        # State flags to prevent double cleanup
        self.ollama_active = False
        self.comfyui_active = False
        
        # Timing variables
        self.global_start_time = None
        self.scene_start_times = {}
        
        # NEW VARIABLES FOR REVIEW PAUSE
        self.awaiting_review = False
        self.review_lock = threading.Lock() # Protects shared state
        self.final_scenes = None
        self.final_global_refs = None
        self.final_prompts = None

    def emit_pipe(self, scope, step_idx, status="active"):
        self.pipeline_signal.emit(scope, step_idx, status)

    def cleanup(self):
        """Ensures cleanup happens exactly once per service."""
        if self.ollama_active:
            try:
                cleanup_after_ollama()
                self.ollama_active = False
                self.log_signal.emit("info", "Ollama cleaned up.")
            except Exception as e:
                self.log_signal.emit("warn", f"Ollama cleanup warning: {e}")
                
        if self.comfyui_active:
            try:
                cleanup_after_comfyui()
                self.comfyui_active = False
                self.log_signal.emit("info", "ComfyUI cleaned up.")
            except Exception as e:
                self.log_signal.emit("warn", f"ComfyUI cleanup warning: {e}")

    @Slot()
    def run(self):
        try:
            self.global_start_time = time.time()
            self.emit_pipe("global", 0, "active") # Init
            
            # 1. Setup Paths
            cfg.CURRENT_PROJECT_PATH = Path(self.config['project_path'])
            cfg.CHARACTERS_DIR = cfg.CURRENT_PROJECT_PATH / "characters"
            cfg.SCRIPTS_DIR = cfg.CURRENT_PROJECT_PATH / "scripts"
            cfg.PROMPTS_DIR = cfg.CURRENT_PROJECT_PATH / "prompts"
            cfg.OUTPUT_DIR = cfg.CURRENT_PROJECT_PATH / "output"
            
            for d in [cfg.CHARACTERS_DIR, cfg.SCRIPTS_DIR, cfg.PROMPTS_DIR, cfg.OUTPUT_DIR]:
                d.mkdir(parents=True, exist_ok=True)
            
            self.emit_pipe("global", 0, "done")
            self.emit_pipe("global", 1, "active") # Ollama Start
            
            # Check cancellation early
            if self.is_cancelled: raise RuntimeError("Cancelled by user")

            # 2. Phase 1: Ollama Content Generation
            prepare_for_ollama()
            self.ollama_active = True
            self.emit_pipe("global", 1, "done")
            self.emit_pipe("global", 2, "active") # Script Gen
            
            title = self.config['title']
            style = self.config['style']
            num_clips = self.config['num_clips']
            clip_dur = self.config['clip_duration']
            lang = self.config['language']
            user_char_map = self.config['char_map'] # Dict: role -> {'filename': ..., 'gender': ...}
            enable_qa = self.config.get('enable_qa', True)
            num_chars = self.config.get('num_chars', 1)
            
            # NEW: Extract Genres
            genres = self.config.get('genres', ["Action"])             
                    
            # PASS AVAILABLE ROLES TO SCRIPT GENERATOR
            available_roles = list(user_char_map.keys())
            
            scenes_structure = generate_narrative_script(
                title, style, num_clips, clip_dur, lang, 
                available_roles=available_roles,
                genres=genres  # <--- ADD THIS PARAMETER
            )
            if not scenes_structure:
                raise RuntimeError("Failed to generate narrative script.")
            self.emit_pipe("global", 2, "done")
            
            self.emit_pipe("global", 3, "active") # Global Refs
            g_refs, _ = generate_global_refs_from_map(title, style, num_clips, user_char_map, lang)
            self.emit_pipe("global", 3, "done")
            
            self.emit_pipe("global", 4, "active") # Prompt Gen
            raw_prompt_files = generate_sequential_prompts(
                g_refs, scenes_structure, title, style, clip_dur, 
                mode=self.config['mode'], char_map=user_char_map, language_code=lang
            )
            if not raw_prompt_files:
                raise RuntimeError("No prompts were generated. Aborting.")
            self.emit_pipe("global", 4, "done")
            
            # --- REAL QA LOOP (Optional, runs before Human Review) ---
            reviewed_prompts = []
            prev_context = ""
            
            if enable_qa:
                self.emit_pipe("global", 5, "active") # QA Review Start
                self.log_signal.emit("info", "Running Automated QA Validation...")
                
                for i, (_, _, gp, lp, sd) in enumerate(raw_prompt_files, 1):
                    if self.is_cancelled: break
                    
                    dialogue = sd.get('dialogue_snippet', '')
                    retries = 0
                    current_lp = lp
                    
                    # Max 2 retries per scene
                    while retries < 2:
                        is_valid, reason, errors = validate_ltx_prompt(current_lp, dialogue, prev_context)
                        
                        if is_valid:
                            self.log_signal.emit("success", f"Scene {i} Passed Auto-QA.")
                            break
                        
                        self.log_signal.emit("warn", f"Scene {i} Failed Auto-QA: {reason}. Regenerating...")
                        
                        # Regenerate with feedback
                        current_lp = regenerate_prompt_with_feedback(
                            current_lp, reason, errors, sd, gp, 
                            title, style, clip_dur, lang, prev_context
                        )
                        retries += 1
                    
                    if retries >= 2:
                        self.log_signal.emit("error", f"Scene {i} Exhausted Retries. Using last attempt.")
                    
                    # Save reviewed prompt
                    reviewed_prompts.append((i, None, gp, current_lp, sd))
                    prev_context = current_lp
                
                self.emit_pipe("global", 5, "done")
                # Replace original prompts with auto-reviewed ones
                raw_prompt_files = reviewed_prompts
            else:
                self.emit_pipe("global", 5, "done") # Skipped Auto-QA

            # --- HUMAN-IN-THE-LOOP REVIEW STEP ---
            self.log_signal.emit("info", "⏸️ Pausing for Creative Review...")
            self.awaiting_review = True
            
            # Emit signal to Main Window to open Dialog
            # We pass copies so UI doesn't mutate worker state directly during edit
            self.review_request_signal.emit(
                [s.copy() for s in scenes_structure], 
                g_refs, 
                [(idx, path, gp, lp, sd.copy()) for idx, path, gp, lp, sd in raw_prompt_files]
            )
            
            # Block until user approves/cancels
            # We use a simple poll loop because Qt signals/slots across threads can be tricky with blocking waits
            while self.awaiting_review and not self.is_cancelled:
                time.sleep(0.5) # Poll every 500ms
            
            if self.is_cancelled:
                raise RuntimeError("Cancelled by user during review.")
            
            # Use the reviewed data
            scenes_structure = self.final_scenes
            g_refs = self.final_global_refs
            raw_prompt_files = self.final_prompts
            
            self.log_signal.emit("success", "✅ Reviews Approved. Resuming Pipeline...")
            # -------------------------------------------

            # Switch to ComfyUI
            self.emit_pipe("global", 6, "active") # Ollama Stop
            self.cleanup() # Kills Ollama
            self.emit_pipe("global", 6, "done")
            
            # Check cancellation again
            if self.is_cancelled: raise RuntimeError("Cancelled by user")

            # 3. Phase 2: ComfyUI Generation
            if not prepare_for_comfyui():
                raise RuntimeError("Failed to start ComfyUI")
            self.comfyui_active = True
            
            # Upload Images
            uploaded_map = {} # Role -> Stored Filename
            self.log_signal.emit("info", "Uploading character images to ComfyUI...")
            
            # CRITICAL FIX: Parse the new dict structure {'filename': ..., 'gender': ...}
            for role, metadata in user_char_map.items():
                # Handle both old string format and new dict format for robustness
                if isinstance(metadata, dict):
                    filename = metadata.get('filename')
                else:
                    filename = metadata # Fallback for old format
                
                if not filename:
                    continue
                    
                p = cfg.CHARACTERS_DIR / filename
                if p.exists():
                    s = upload_image(str(p))
                    if s: 
                        uploaded_map[role] = s
                        self.log_signal.emit("info", f"Uploaded {role}: {s}")
                    else:
                        self.log_signal.emit("warn", f"Failed to upload {role}: {filename}")
                else:
                    self.log_signal.emit("warn", f"Image file missing on disk: {p}")
            
            if not uploaded_map and user_char_map: 
                # If no images uploaded but characters were defined, this is a fatal error for MSRs
                raise RuntimeError("No character images could be uploaded to ComfyUI. Check filenames/paths.")
                 
            default_img = list(uploaded_map.values())[0] if uploaded_map else None
            
            # Load Workflow
            with open(cfg.WORKFLOW_FILE, "r", encoding="utf-8") as f:
                wf = json.load(f)
            
            total = len(raw_prompt_files)
            success_count = 0
            
            self.log_signal.emit("info", f"=== GENERATING {total} SCENES ===")
            
            for i, (_, _, gp, lp, sd) in enumerate(raw_prompt_files, 1):
                if self.is_cancelled:
                    break
                
                scope = f"scene_{i}"
                self.scene_start_times[i] = time.time() # Record start for this scene
                
                # EMIT CURRENT PROMPT TO GUI
                self.current_prompt_signal.emit(f"Scene {i}", lp)
                
                self.emit_pipe(scope, 0, "active") # Img Inject
                
                # Prepare Workflow with Multi-Image Support
                mod_wf, _ = prepare_workflow(
                    wf, gp, lp, uploaded_map, 
                    aspect_ratio_key=self.config['aspect_ratio'],
                    clip_duration=clip_dur,
                    scene_data=sd  
                )
                
                self.emit_pipe(scope, 0, "done")
                self.emit_pipe(scope, 1, "active") # WF Prep
                self.emit_pipe(scope, 1, "done")
                self.emit_pipe(scope, 2, "active") # Queue Job
                
                out = queue_and_wait(mod_wf, is_cancelled=lambda: self.is_cancelled)
                self.emit_pipe(scope, 2, "done")
                
                if out:
                    self.emit_pipe(scope, 3, "active") # Gen Ph1
                    self.emit_pipe(scope, 3, "done")
                    self.emit_pipe(scope, 4, "active") # Gen Ph2
                    self.emit_pipe(scope, 4, "done")
                    
                    op = cfg.OUTPUT_DIR / f"scene_{i:03d}.mp4"
                    self.emit_pipe(scope, 5, "active") # Download
                    if download_file(out, op):
                        success_count += 1
                        self.emit_pipe(scope, 5, "done")
                        self.emit_pipe(scope, 6, "active") # Save
                        self.emit_pipe(scope, 6, "done")
                        self.video_ready_signal.emit(str(op))
                    else:
                        self.emit_pipe(scope, 5, "error")
                else:
                    self.emit_pipe(scope, 2, "error")
                
                time.sleep(1)
            
            self.cleanup()
            self.finished_signal.emit(True, f"Done: {success_count}/{total}")
            
        except Exception as e:
            self.log_signal.emit("error", f"CRASH: {str(e)}\n{traceback.format_exc()}")
            self.cleanup()
            # Determine if it was a cancellation or a real error
            msg = "Cancelled by User" if self.is_cancelled else str(e)
            self.finished_signal.emit(not self.is_cancelled, msg)

    @Slot()
    def cancel(self):
        self.is_cancelled = True
        # If stuck in review wait, release it immediately
        if self.awaiting_review:
            self.awaiting_review = False

    @Slot(list, str, list)
    def apply_reviews(self, edited_scenes, edited_global, edited_prompts):
        """Called by Main Window when user clicks Approve in ReviewDialog."""
        with self.review_lock:
            self.final_scenes = edited_scenes
            self.final_global_refs = edited_global
            self.final_prompts = edited_prompts
            self.awaiting_review = False # Release the worker loop
        self.log_signal.emit("success", "Reviews applied. Continuing generation...")