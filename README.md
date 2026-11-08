# CineGrapher — Idea → Storyboard → Multi-Shot Video

**CineGrapher** is a local, desktop application that turns a simple video idea (a title, style and genres) into a coherent, multi-scene cinematic video — completely end to end.

A local LLM (via **Ollama**) storyboards the narrative, writes **LTX-2.5-compliant multi-shot prompts**, self-audits those prompts against the model's strict format rules, and then **ComfyUI** generates the actual video — with reference-image character consistency and native audio.

> 🖥️ No cloud API keys, no server. Everything runs on your own GPU.

---

## ✨ Features

| Feature | Detail |
|---|---|
| 🧠 **Agentic storyboarding** | A local LLM (qwen3.8:27b by default) converts your idea into a timed, multi-scene narrative script (plot, dialogue, cast). |
| 🎬 **Multi-shot prompt engine** | Each scene is written as a single-paragraph, LTX-2.5-compliant prompt with *named cuts*, per-cut character re-description and audio state. |
| 🔁 **Automated QA loop** | An LLM "auditor" validates every prompt against LTX-2.5 rules and auto-regenerates failures (up to 2 retries per scene) before you review them. |
| 🖼️ **Character consistency** | Up to 2 reference images per scene are injected into the workflow and mapped to `Image 1` / `Image 2` to keep characters visually stable across shots. |
| ⚡ **VRAM handoff** | Ollama and ComfyUI are auto-started and auto-killed in sequence so both can share a single GPU. |
| 🎨 **Modern desktop GUI** | PySide6 (Qt) interface with a live 7-step pipeline tracker, progress bar and full log console. |
| 🌐 **Multilingual** | Script & dialogue in 10 languages — English, اردو (Roman), پښتو (Roman), العربية, فارسی, Français, Español, Deutsch, Русский, 中文. |
| 📐 **Flexible output** | Aspect ratios `16:9 · 9:16 · 1:1 · 4:3 · 21:9` · clip durations `5 / 7 / 10 / 12 / 15 / 17 / 20 s` · 1–4 characters per scene. |

---

## 🔄 How It Works

```
          ┌──────────────────────────────────────────────────────────┐
          │                        YOUR IDEA                         │
          │      title + style + genres + characters + settings      │
          └──────────────────────────────┬───────────────────────────┘
                                         ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │                OLLAMA   (local LLM — Qwen 3.8 27B)                 │
   │   1. Storyboard  → JSON scene script (plot, dialogue, cast)      │
   │   2. Global reference descriptions (character appearance)        │
   │   3. Sequential per-scene multi-shot prompts                     │
   │   4. QA audit + auto-regenerate (≤ 2 retries per scene)          │
   └───────────────────────────────────┬───────────────────────────────┘
                                        │   ⏸  Creative Review (human-in-the-loop)
                                        ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │                COMFYUI   (LTX-2 text-to-video)                  │
   │   • upload reference images     • inject prompt + cast           │
   │   • per-scene generation        • download MP4 (video + audio)   │
   └───────────────────────────────────┬───────────────────────────────┘
                                        ▼
                          🎞️  projects/<Your Title>/
                               ├── storyboard.json
                               ├── prompt_scene_001.txt …
                               └── output/scene_001.mp4 …
```

The two heavy AI back-ends **never run at the same time**: `model_manager.py` shuts down Ollama (freeing VRAM) before launching ComfyUI, and does the reverse on the way back. This is what allows a single GPU to host both models.

### Project Structure

```
ltxmsr/
├── gui_app.py               # Entry point — launches the PySide6 app
├── run.bat                  # Windows one-click launcher
├── requirements.txt         # Python dependencies
│
├── msr_engine/              # Core "brain" (framework-agnostic logic)
│   ├── config.py            # Global config: URLs, models, dirs, ratios, node IDs
│   ├── storyboarder.py      # LLM script + multi-shot prompt generation (Ollama)
│   ├── prompt_reviewer.py   # LLM QA validation + regeneration (Ollama)
│   ├── comfy_client.py      # ComfyUI API: upload, inject, queue, poll, download
│   ├── model_manager.py     # Ollama/ComfyUI lifecycle + VRAM handoff
│   ├── utils.py             # Console + helpers
│   └── dashboard.py         # Live PySide6 project dashboard
│
├── ui/
│   ├── main_window.py       # Main PySide6 GUI window
│   ├── review_agent.py      # Automated QA reviewer (storyboard + prompt audit)
│   └── workers/
│       └── generation_worker.py  # QThread that runs the 7-step pipeline
│
├── workflows/
│   └── ltx_msr_workflow.json   # Base ComfyUI node graph (LTX-2.5 + audio + upscaler)
│
└── projects/         # One isolated folder per generated video
```

---

## ⚙️ Prerequisites

| Requirement | Notes |
|---|---|
| **OS** | Windows 10/11 (the default launcher & auto-start are Windows-oriented; see [Platform notes](#-platform-notes)) |
| **GPU** | NVIDIA GPU with **CUDA** + a recent driver. LTX-2.5 + Qwen 3.8 27B are memory-hungry — **16 GB+ VRAM** strongly recommended (the VRAM-handoff design lets you *time-share* the same VRAM between the two models). |
| **Python** | 3.10 – 3.12 (64-bit) |
| **Disk** | ~30–50 GB free for the LTX-2.5 + CLIP + VAE models and Ollama model. |
| **Internet** | Needed on first run to pull the Ollama model and (optionally) the ComfyUI models. |

---

## 📦 Installation

### 1. Clone & create a virtual environment

```powershell
git clone <YOUR_REPO_URL> ltxmsr
cd ltxmsr

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # PowerShell
# OR: .venv\Scripts\activate        # CMD

# Install Python dependencies
pip install -r requirements.txt
```

`requirements.txt` installs: **PySide6**, **requests**, **rich**, **beautifulsoup4**.

### 2. Install Ollama + the LLM

1. Install [Ollama](https://ollama.com/download) (the desktop app is the easiest).
2. Pull the default model (27B — swap for a smaller/larger one in `config.py` if you prefer):

```powershell
ollama pull qwen3.8:27b
# A lighter fallback if you have less VRAM:
# ollama pull qwen3.8:14b
```

> Ollama serves by default at `http://localhost:11434`. LTXMSR talks to it over HTTP, so as long as `ollama serve` is running (the desktop app keeps it running), that's all that's needed.

### 3. Install ComfyUI + LTX-2.5 models

LTXMSR **auto-starts** ComfyUI (it expects a portable install — see the path note below). You need ComfyUI plus the **LTX-2** text-to-video model family.

Download these model files into your ComfyUI folders:

| Model | ComfyUI folder | Default filename in the workflow |
|---|---|---|
| LTX-2.5 distilled checkpoint | `models/unet/` (GGUF) | `ltx2_38k-distilled-lora-0.08d2_v2.1151.safetensors` |
| Spatial upsampler LoRA | `models/loras/` | `ltx2-spatial-upsampler-lora-1.0.safetensors` |
| T5-XXL (fp16) CLIP | `models/clip/` | `t5xxl_fp16.safetensors` |
| CLIP-L | `models/clip/` | `clip_l.safetensors` |
| LTX-2 **video** VAE | `models/vae/` | `ltx2_video_vae.safetensors` |
| LTX-2 **audio** VAE | `models/vae/` | `ltx2_audio_vae.safetensors` |

> 📌 **Model names matter.** The workflow references the exact filenames above. Either rename your downloads to match, or open `workflows/ltx_msr_workflow.json` and update the node inputs to your actual filenames.

### 4. Point LTXMSR at *your* ComfyUI

By default the auto-start expects a Windows portable install at:

```
F:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\run_nvidia_gpu.bat
```

If your install is elsewhere, edit the top of `msr_engine/model_manager.py`:

```python
_COMFYUI_DIR  = Path(r"YOUR\PATH\TO\ComfyUI_windows_portable")
_COMFYUI_BAT  = _COMFYUI_DIR / "run_nvidia_gpu.bat"
```

<details>
<summary><b>💡 Alternative: run ComfyUI yourself (skip auto-start)</b></summary>

If you prefer to manage ComfyUI manually, just make sure it's already running at
`http://127.0.0.1:8188` (set `COMFYUI_URL` in `config.py` if different) before you
start generation. The pipeline will detect that it's online and proceed.
</details>

---

## 🎛️ Configuration

All knobs live in `msr_engine/config.py`:

| Setting | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `qwen3.8:27b` | LLM used for script/prompt/QA |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI API endpoint |
| `LTX_MODEL` | `LTX-2.5` | Target video model name (used in prompt framing) |
| `ASPECT_RATIOS` | `16:9 · 9:16 · 1:1 · 4:3 · 21:9` | Output aspect ratios (drives width/height) |
| `TARGET_MEGAPIXELS` | `0.5` | Output resolution budget (~944×530 @ 16:9) |
| `DURATION_OPTIONS` | `[5, 7, 10, 12, 15, 17, 20]` | Allowed clip durations (seconds) |
| `LANGUAGES` | 10 codes | `en, ur-roman, ps-roman, ar, fa, fr, es, de, ru, zh` |
| `MAX_WORDS_PER_DIALOGUE` | `18` | Dialogue length cap per shot (~1.8 words/sec pacing) |
| `CHARACTER_MAP` | hero · villain · heroin · sidekick | Roles the LLM may cast |
| `WORKFLOW_NODE_IDS` | see file | ComfyUI node IDs that get injected at runtime |

`WORKFLOW_NODE_IDS` maps each logical value (prompt, image slots, seed, width/height, frames, etc.) to the node ID in `workflows/ltx_msr_workflow.json`. If you swap in a different workflow graph, update these IDs to match.

---

## 🚀 Usage

### Launch

```powershell
# Windows one-click (from the project root):
run.bat

# …or directly:
python gui_app.py
```

### GUI walkthrough

1. **Project Setup** — enter a **title**, pick a **style**, toggle on **genres**, and choose your **language**.
2. **Characters** — add 1–3 roles (e.g. `hero`, `villain`) and optionally attach a **reference image** to each (PNG/JPG) to lock in their appearance.
3. **Output** — pick the **number of scenes** and the **clip duration** (each scene = one clip).
4. **Generate** — click **Generate**. The 7-step pipeline tracker lights up as it goes:

   `1 Storyboard → 2 Global Refs → 3 Prompt Gen → 4 QA Review → ⏸ Review → 5 ComfyUI prep → 6 Per-Scene`

5. **Creative Review** — the pipeline **pauses** so you can inspect the generated storyboard and prompts in the output folder, approve, or cancel.
6. **Watch it render** — ComfyUI generates each scene (video + audio), and every MP4 is saved to `projects/<Your Title>/output/`.

> Each run writes to its own isolated folder under `projects/`, so previous generations are never overwritten.

---

## 📏 The LTX-2.5 Multi-Shot Prompt Spec

LTX-2.5 is famously strict about how multi-shot video prompts must be written. LTXMSR bakes these rules into **both** the prompt-generation instructions and the automated QA auditor, so every prompt you get should already comply:

- **Single chronological paragraph** — no `Shot 1: / Shot 2:` lists or bullets. All cuts flow as continuous prose.
- **Named, physical cuts** — each transition is a *named cut* (hard cut, match cut, …) described with what stays still and what moves.
- **Re-describe characters after every cut** — after each cut, re-describe each active character's appearance from scratch. **No pronouns** after a cut (he/she/they) — LTX-2.5 loses track of identities otherwise.
- **≤ 2 active characters per shot** — any third character is only *implied off-screen*, never shown.
- **Audio state at every cut** — the prompt must state what is heard across the cut (dialogue, SFX, ambient bed).
- **Dialogue verbatim, in exactly one shot** — each line of dialogue appears only once, in the shot where it is spoken.
- **Spatial anchors** — characters are positioned using the reference images (`Image 1`, `Image 2`) so the model keeps them consistent across shots.
- **Continuity with the previous scene** — when Scene N+1 starts, its prompt re-grounds the world from Scene N's ending.

Toggle **"Automated QA Validation (LTX-2.5 Rule Check)"** in the GUI to have the LLM auditor enforce these rules and regenerate any failing prompts automatically.

---

## 🛠️ Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Could not connect to Ollama` | Ollama isn't running, or the model isn't pulled. Run `ollama pull qwen3.8:27b` and confirm `ollama serve` is up. |
| `ComfyUI is not reachable` / prep fails | ComfyUI not running or not at `COMFYUI_URL`. Start it, or run it manually (see [Alternative](#-installation)). |
| **VRAM out of memory** during generation | Lower `TARGET_MEGAPIXELS` / clip duration, or use a smaller Ollama model. Confirm Ollama is fully killed before ComfyUI starts (check Task Manager). |
| `Invalid image file` from ComfyUI | Reference image missing/corrupt. The code injects a dummy image + bypass when a slot is empty — re-check your chosen reference paths. |
| Wrong resolution / aspect | Check `ASPECT_RATIOS`, `TARGET_MEGAPIXELS` in `config.py` and that the matching node IDs exist in your workflow JSON. |
| Node IDs "not found" warnings | You swapped the workflow graph. Update `WORKFLOW_NODE_IDS` in `config.py` to the real node IDs. |
| Zombie ComfyUI after a crash | The app kills the process tree on exit, but a hard crash may leave it. `taskkill /F /IM python.exe` or kill via Task Manager. |
| Fonts/emoji look odd in the GUI | Cosmetic only — install a color emoji font for Windows console, or ignore. |

---

## 🖥️ Platform notes

- **Windows is the first-class target.** The auto-start (`run_nvidia_gpu.bat`), the `taskkill /F /T` cleanup, and the console-close event handlers are all Windows-specific.
- **Linux/macOS** — the code falls back to `os.killpg` / POSIX signals where possible, but the ComfyUI auto-start assumes a Windows portable install. On other OSes, run ComfyUI yourself and let LTXMSR connect to the API.

---

## 📁 Output

```
projects/<Your Title>/
├── storyboard.json         # Full multi-scene script (source of truth)
├── prompt_scene_001.txt    # LTX-2.5-compliant prompt per scene
├── prompt_scene_002.txt
└── output/
    ├── scene_001.mp4
    └── scene_002.mp4
```

Stitch the per-scene MP4s in your order (or a tool like `ffmpeg`) to assemble the final video.

---

## 🧰 Development

Quick sanity tests (manual, not a CI suite):

```powershell
python test_ollama.py        # verify Ollama + model respond
python test_comfyui.py       # verify ComfyUI API is reachable
python test_storyboard.py    # run storyboard generation in isolation
```

---

## 📄 License

© 2026. For personal/educational use. LTX-2.5, ComfyUI and Ollama are third-party projects — see their respective licenses and model license terms.

---

<p align="center"><b>Idea → Storyboard → Multi-Shot Video — locally.</b></p>


