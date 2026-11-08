import sys
import os
import re
import random
import time
import json
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QGroupBox,
    QTextEdit, QProgressBar, QFileDialog, QListWidget, QListWidgetItem,
    QSplitter, QFrame, QAbstractItemView, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QGraphicsDropShadowEffect, QScrollArea,
    QCheckBox, QGridLayout, QDialog, QSizePolicy, QTabWidget, QStackedWidget,
    QToolBar, QAction
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QObject, QSize
from PySide6.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent, QPixmap, QIcon, QPainter, QPen, QTextCursor, QTextCharFormat, QPalette
import subprocess
import requests # For AI Quotes

# Import Worker
from ui.workers.generation_worker import GenerationWorker, SystemMonitor

# Import Config for constants
sys.path.append(str(Path(__file__).resolve().parent.parent))
import msr_engine.config as cfg

# Fallback Quotes
FALLBACK_QUOTES = [
    "The future belongs to those who believe in the beauty of their dreams.",
    "AI is not about replacing humans, but augmenting creativity.",
    "Every pixel tells a story; every frame builds a world.",
    "Innovation distinguishes between a leader and a follower.",
    "Technology is best when it brings people together.",
    "Simplicity is the ultimate sophistication.",
    "Creativity is intelligence having fun.",
    "Dream big, render faster."
]

class StepBox(QWidget):
    """A single visual step indicator."""
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.label_text = label
        self.state = "pending" # pending, active, done, error
        self.setFixedSize(80, 30)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        colors = {
            "pending": "#333",
            "active": "#007acc", # Blue
            "done": "#28a745",   # Green
            "error": "#dc3545"   # Red
        }
        bg_color = colors.get(self.state, "#333")
        text_color = "#fff" if self.state != "pending" else "#888"
        
        rect = self.rect()
        radius = 5
        painter.setBrush(QColor(bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, radius, radius)
        
        painter.setPen(QColor(text_color))
        font = QFont("Segoe UI", 8)
        font.setBold(self.state == "active")
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.label_text)
        
    def set_state(self, state):
        self.state = state
        self.update()

class PipelineRow(QWidget):
    """A row representing one major phase."""
    def __init__(self, title, step_labels, parent=None):
        super().__init__(parent)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #aaa; font-weight: bold; min-width: 100px;")
        
        layout = QHBoxLayout()
        layout.addWidget(self.title_label)
        
        self.step_boxes = []
        for lbl in step_labels:
            box = StepBox(lbl)
            self.step_boxes.append(box)
            layout.addWidget(box)
            
        layout.addStretch()
        self.setLayout(layout)
        
    def activate_step(self, index):
        if 0 <= index < len(self.step_boxes):
            self.step_boxes[index].set_state("active")
            for i in range(index):
                if self.step_boxes[i].state == "active":
                    self.step_boxes[i].set_state("done")

    def complete_step(self, index, success=True):
        if 0 <= index < len(self.step_boxes):
            self.step_boxes[index].set_state("done" if success else "error")

    def reset_all(self):
        for box in self.step_boxes:
            box.set_state("pending")

class CharacterCard(QFrame):
    """A beautiful card for dragging/dropping a character image + Gender Selection."""
    image_selected = Signal(str, str)
    gender_selected = Signal(str, str) 
    
    def __init__(self, role_name, index, parent=None):
        super().__init__(parent)
        self.role_name = role_name
        self.index = index
        self.image_path = None
        self.gender = "Male" # Default
        
        self.setObjectName("CharCard")
        self.setStyleSheet("""
            #CharCard { background-color: #2b2b2b; border: 1px solid #444; border-radius: 8px; padding: 10px; }
            #CharCard:hover { border: 1px solid #007acc; }
            QLabel#RoleLabel { color: #fff; font-size: 14px; font-weight: bold; }
            QLabel#StatusLbl { color: #888; font-size: 10px; }
        """)
        
        self.setMinimumHeight(220) 
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        layout = QVBoxLayout()
        layout.setSpacing(5)
        
        header_layout = QHBoxLayout()
        self.lbl_role = QLabel(f"{index}. {role_name.capitalize()}")
        self.lbl_role.setObjectName("RoleLabel")
        header_layout.addWidget(self.lbl_role)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        self.drop_area = QLabel("Drag Image Here\n(or Click to Browse)")
        self.drop_area.setAlignment(Qt.AlignCenter)
        self.drop_area.setStyleSheet("background-color: #333; border: 2px dashed #555; border-radius: 5px; color: #aaa; padding: 20px;")
        self.drop_area.setCursor(Qt.PointingHandCursor)
        self.drop_area.mousePressEvent = self.browse_file
        layout.addWidget(self.drop_area)
        
        gender_layout = QHBoxLayout()
        gender_layout.addWidget(QLabel("Gender:"))
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["Male", "Female", "Non-Binary"])
        self.gender_combo.setCurrentText("Male")
        self.gender_combo.currentTextChanged.connect(self.on_gender_changed)
        gender_layout.addWidget(self.gender_combo)
        layout.addLayout(gender_layout)
        
        self.lbl_status = QLabel("No image selected")
        self.lbl_status.setObjectName("StatusLbl")
        layout.addWidget(self.lbl_status)
        
        self.setLayout(layout)
        self.setAcceptDrops(True)

    def browse_file(self, event):
        path, _ = QFileDialog.getOpenFileName(self, f"Select Image for {self.role_name}", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.set_image(path)

    def set_image(self, path):
        self.image_path = path
        fname = Path(path).name
        self.lbl_status.setText(f"✅ Selected: {fname}")
        self.lbl_status.setStyleSheet("color: #0f0; font-weight: bold;")
        self.drop_area.setText(fname)
        self.drop_area.setStyleSheet("background-color: #1e3a2e; border: 2px solid #28a745; border-radius: 5px; color: #fff; padding: 20px; font-weight: bold;")
        self.image_selected.emit(self.role_name, path)

    def on_gender_changed(self, text):
        self.gender = text
        self.gender_selected.emit(self.role_name, text)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_area.setStyleSheet("border: 2px dashed #00ff00; background-color: #3b3b3b;")
            
    def dragLeaveEvent(self, event):
        self.drop_area.setStyleSheet("border: 2px dashed #555; background-color: #333;")
        
    def dropEvent(self, event: QDropEvent):
        self.drop_area.setStyleSheet("border: 2px dashed #555; background-color: #333;")
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(('.png', '.jpg', '.jpeg')):
                self.set_image(path)
                break

class QuoteFetcher(QObject):
    quote_received = Signal(str)
    
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.thread = None

    def start_fetch(self):
        self.thread = QThread()
        self.worker_obj = self 
        self.moveToThread(self.thread)
        self.thread.started.connect(self.run_fetch)
        self.thread.start()

    @Slot()
    def run_fetch(self):
        try:
            resp = requests.get(f"{cfg.OLLAMA_URL}/api/tags", timeout=2)
            if resp.status_code == 200:
                prompt = f"""Generate one short, inspiring, futuristic quote related to the movie concept: '{self.title}'.
Output ONLY the quote text."""
                
                gen_resp = requests.post(f"{cfg.OLLAMA_URL}/api/generate", json={
                    "model": cfg.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 50}
                }, timeout=10)
                
                if gen_resp.status_code == 200:
                    quote = gen_resp.json().get("response", "").strip()
                    if quote and len(quote) > 5:
                        self.quote_received.emit(quote)
                        return
        except Exception:
            pass
        
        self.quote_received.emit(random.choice(FALLBACK_QUOTES))
        
        if self.thread:
            self.thread.quit()
            self.thread.wait()

# ==========================================
# NEW ADVANCED REVIEW DIALOG CLASS
# ==========================================
class AdvancedReviewDialog(QDialog):
    """
    Three-Column Director's Cut Review Interface.
    Left: Diagnostics | Middle: Original Draft | Right: Proposed Fix (Editable)
    """
    approved = Signal(dict)  # Emits final config with approved prompts/script
    rejected = Signal()      # Emits if user cancels
    
    def __init__(self, title, style, language, scenes_data, global_refs, local_prompts_list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"CineAgent Director's Review: {title}")
        self.setGeometry(100, 100, 1600, 900)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #eee; }
            QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 10px; padding-top: 10px; font-weight: bold; color: #ddd;}
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QPushButton { background-color: #007acc; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #005f9e; }
            QPushButton#DangerBtn { background-color: #dc3545; }
            QPushButton#SuccessBtn { background-color: #28a745; }
            QTextEdit { background-color: #252525; color: #fff; border: 1px solid #444; font-family: 'Consolas'; font-size: 10pt; }
            QLabel { color: #ccc; }
        """)
        
        self.title = title
        self.style = style
        self.language = language
        self.scenes_data = scenes_data
        self.global_refs = global_refs
        self.local_prompts_list = local_prompts_list # List of tuples (idx, path, gp, lp, sd)
        
        self.current_item_idx = 0
        self.items_to_review = [] # Flattened list of all reviewable items
        
        self._prepare_items()
        self.init_ui()
        self.load_item(0)

    def _prepare_items(self):
        """Flatten script, global refs, and prompts into a single review list."""
        # 1. Script Scenes
        for i, scene in enumerate(self.scenes_data):
            self.items_to_review.append({
                'type': 'scene',
                'id': f'Scene {i+1}',
                'original': json.dumps(scene, indent=2),
                'proposed': json.dumps(scene, indent=2), # Initially same, QA agent will modify
                'diagnostics': self._run_scene_diagnostics(scene)
            })
        
        # 2. Global Refs
        self.items_to_review.append({
            'type': 'global_ref',
            'id': 'Global References',
            'original': self.global_refs,
            'proposed': self.global_refs,
            'diagnostics': self._run_global_diag(self.global_refs)
        })
        
        # 3. Local Prompts
        for idx, (_, _, gp, lp, sd) in enumerate(self.local_prompts_list):
            self.items_to_review.append({
                'type': 'local_prompt',
                'id': f'Prompt Scene {idx+1}',
                'original': lp,
                'proposed': lp,
                'diagnostics': self._run_prompt_diag(lp, sd)
            })

    def _run_scene_diagnostics(self, scene):
        """Mock QA Agent Logic for Scenes."""
        issues = []
        if "Cinematic Location" in scene.get('location', ''):
            issues.append(("Critical", "Generic Location Detected", "Replace with specific setting matching genre."))
        if not scene.get('dialogue_snippet'):
            issues.append(("Warning", "Missing Dialogue", "Add character interaction line."))
        if len(scene.get('plot_point', '')) < 10:
            issues.append(("Warning", "Vague Action", "Describe physical movement clearly."))
        return issues

    def _run_global_diag(self, refs):
        """Mock QA Agent Logic for Global Refs."""
        issues = []
        if "man" in refs.lower() and "woman" in refs.lower():
             # Simple heuristic check for potential gender mix-up logic
             pass 
        if "Audio 1: Male voice" in refs and "Young woman" in refs:
            issues.append(("Critical", "Voice/Gender Mismatch", "Image 1 is female but assigned male voice. Change to Female voice."))
        return issues

    def _run_prompt_diag(self, prompt, scene_data):
        """Mock QA Agent Logic for Prompts."""
        issues = []
        forbidden = ["hero", "villain", "girl", "boy"]
        leaks = [w for w in forbidden if w in prompt.lower()]
        if leaks:
            issues.append(("Critical", f"Forbidden Terms: {leaks}", "Replace natural names with 'Image X' tags."))
        if "Audio" not in prompt and scene_data.get('dialogue_snippet'):
            issues.append(("Warning", "Missing Audio Tag", "Ensure dialogue is wrapped in Audio X (Image Y): format."))
        return issues

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # Header Info
        info_label = QLabel(f"<b>Title:</b> {self.title} | <b>Style:</b> {self.style} | <b>Lang:</b> {self.language}")
        info_label.setStyleSheet("padding: 10px; background-color: #2b2b2b; color: #fff; border-radius: 5px;")
        main_layout.addWidget(info_label)

        # Navigation Bar
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Prev Item")
        self.btn_next = QPushButton("Next Item ▶")
        self.lbl_indicator = QLabel("Item 1 / ?")
        self.lbl_indicator.setAlignment(Qt.AlignCenter)
        self.lbl_indicator.setStyleSheet("font-weight: bold; color: #0ff; min-width: 150px;")
        
        self.btn_prev.clicked.connect(self.prev_item)
        self.btn_next.clicked.connect(self.next_item)
        
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addStretch()
        nav_layout.addWidget(self.lbl_indicator)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_next)
        main_layout.addLayout(nav_layout)

        # --- THREE COLUMN LAYOUT ---
        splitter = QSplitter(Qt.Horizontal)
        
        # 1. LEFT: Diagnostic Report
        diag_group = QGroupBox("🔍 AI Diagnostic Report")
        diag_layout = QVBoxLayout(diag_group)
        self.txt_diagnosis = QTextEdit()
        self.txt_diagnosis.setReadOnly(True)
        self.txt_diagnosis.setStyleSheet("""
            QTextEdit { background-color: #1e1e1e; color: #eee; font-family: 'Consolas'; }
            .critical { color: #ff4444; font-weight: bold; }
            .warning { color: #ffaa00; }
            .info { color: #44aaff; }
            .success { color: #44ff44; }
        """)
        diag_layout.addWidget(self.txt_diagnosis)
        splitter.addWidget(diag_group)
        
        # 2. MIDDLE: Current Draft (Read-Only Context)
        draft_group = QGroupBox("📝 Original Draft")
        draft_layout = QVBoxLayout(draft_group)
        self.txt_original = QTextEdit()
        self.txt_original.setReadOnly(True)
        self.txt_original.setStyleSheet("background-color: #252525; color: #aaa; font-family: 'Consolas'; font-size: 9pt;")
        draft_layout.addWidget(self.txt_original)
        splitter.addWidget(draft_group)
        
        # 3. RIGHT: Proposed Fix (Editable)
        fix_group = QGroupBox("✨ Approved Version (Editable)")
        fix_layout = QVBoxLayout(fix_group)
        self.txt_fixed = QTextEdit()
        self.txt_fixed.setStyleSheet("background-color: #1a2a1a; color: #dfd; font-family: 'Consolas'; font-size: 9pt; border: 1px solid #4caf50;")
        fix_layout.addWidget(self.txt_fixed)
        
        # Action Buttons inside Right Column
        action_layout = QHBoxLayout()
        self.btn_regenerate = QPushButton("🔄 Regenerate Suggestion")
        self.btn_approve_item = QPushButton("✅ Accept Item")
        self.btn_reject_item = QPushButton("❌ Reject Changes")
        
        self.btn_regenerate.clicked.connect(self.regenerate_suggestion)
        self.btn_approve_item.clicked.connect(self.approve_current_item)
        self.btn_reject_item.clicked.connect(self.reject_current_item)
        
        action_layout.addWidget(self.btn_regenerate)
        action_layout.addWidget(self.btn_approve_item)
        action_layout.addWidget(self.btn_reject_item)
        fix_layout.addLayout(action_layout)
        
        splitter.addWidget(fix_group)
        
        # Set initial sizes (Left 30%, Middle 35%, Right 35%)
        splitter.setSizes([450, 500, 500])
        main_layout.addWidget(splitter)
        
        # Global Actions Footer
        footer_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("❌ CANCEL GENERATION")
        self.btn_cancel.setObjectName("DangerBtn")
        self.btn_cancel.clicked.connect(self.rejected.emit)
        self.close()
        
        self.btn_approve_all = QPushButton("🚀 APPROVE ALL & RENDER")
        self.btn_approve_all.setObjectName("SuccessBtn")
        self.btn_approve_all.clicked.connect(self.finalize_and_close)
        
        footer_layout.addWidget(self.btn_cancel)
        footer_layout.addStretch()
        footer_layout.addWidget(self.btn_approve_all)
        main_layout.addLayout(footer_layout)

    def load_item(self, idx):
        if idx < 0 or idx >= len(self.items_to_review):
            return
            
        self.current_item_idx = idx
        item = self.items_to_review[idx]
        
        self.lbl_indicator.setText(f"{item['id']} ({idx+1}/{len(self.items_to_review)})")
        
        # Display Original
        self.txt_original.setPlainText(item['original'])
        
        # Display Edited
        self.txt_fixed.setPlainText(item['proposed'])
        
        # Update Diagnosis
        self.update_diagnosis_view(item['diagnostics'])

    def update_diagnosis_view(self, diagnostics):
        html = "<h3>Analysis Results</h3>"
        if not diagnostics:
            html += "<p class='success'>✓ No critical issues detected. Ready for approval.</p>"
        else:
            for severity, issue, suggestion in diagnostics:
                css_class = "critical" if severity == "Critical" else "warning"
                icon = "🔴" if severity == "Critical" else "🟡"
                html += f"<p class='{css_class}'>{icon} <b>{issue}</b><br><i>Suggestion: {suggestion}</i></p>"
        
        self.txt_diagnosis.setHtml(html)

    def prev_item(self):
        self.save_current_edit()
        self.load_item(self.current_item_idx - 1)

    def next_item(self):
        self.save_current_edit()
        self.load_item(self.current_item_idx + 1)
        
    def save_current_edit(self):
        if 0 <= self.current_item_idx < len(self.items_to_review):
            self.items_to_review[self.current_item_idx]['proposed'] = self.txt_fixed.toPlainText()

    def approve_current_item(self):
        self.save_current_edit()
        # Visual feedback
        self.txt_fixed.setStyleSheet("background-color: #1a2a1a; border: 2px solid #4caf50;")
        QMessageBox.information(self, "Approved", f"{self.items_to_review[self.current_item_idx]['id']} accepted.")

    def reject_current_item(self):
        # Revert to original
        if 0 <= self.current_item_idx < len(self.items_to_review):
            orig = self.items_to_review[self.current_item_idx]['original']
            self.items_to_review[self.current_item_idx]['proposed'] = orig
            self.txt_fixed.setPlainText(orig)
            self.txt_fixed.setStyleSheet("background-color: #2a1a1a; border: 2px solid #dc3545;")

    def regenerate_suggestion(self):
        # Mock regeneration: In real app, call Ollama with diagnostic feedback
        current_text = self.txt_fixed.toPlainText()
        # Simple simulation: Add emphasis to action verbs
        suggestion = current_text.replace("stands", "moves dynamically").replace("scanning", "tracking")
        self.txt_fixed.setPlainText(suggestion)
        self.txt_fixed.setStyleSheet("background-color: #1a1a2a; border: 2px solid #007acc;") # Blue flash

    def finalize_and_close(self):
        self.save_current_edit()
        
        # Reconstruct the data structures from the flattened list
        new_scenes = []
        new_global_refs = ""
        new_local_prompts = []
        
        scene_counter = 0
        prompt_counter = 0
        
        for item in self.items_to_review:
            if item['type'] == 'scene':
                try:
                    scene_data = json.loads(item['proposed'])
                    new_scenes.append(scene_data)
                except:
                    # If JSON broken, keep original
                    new_scenes.append(json.loads(item['original']))
                    
            elif item['type'] == 'global_ref':
                new_global_refs = item['proposed']
                
            elif item['type'] == 'local_prompt':
                # We need to map back to the tuple structure expected by worker
                # Find corresponding scene data if needed, but mostly we just need the LP string
                # The worker expects: (idx, path, gp, lp, sd)
                # We'll reconstruct based on order
                lp = item['proposed']
                # Get original SD from our stored list
                _, _, _, _, sd = self.local_prompts_list[prompt_counter]
                new_local_prompts.append((prompt_counter+1, None, "", lp, sd))
                prompt_counter += 1

        final_payload = {
            'scenes': new_scenes,
            'global_refs': new_global_refs,
            'local_prompts': new_local_prompts,
            'approved_by_user': True
        }
        
        self.approved.emit(final_payload)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CineAgent: Autonomous Video Producer")
        self.setGeometry(100, 100, 1400, 900)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; color: #eee; }
            QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 10px; padding-top: 10px; font-weight: bold; color: #ddd;}
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QPushButton { background-color: #007acc; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #005f9e; }
            QPushButton:disabled { background-color: #444; color: #888; }
            QLineEdit, QComboBox, QSpinBox { background-color: #333; border: 1px solid #555; padding: 5px; border-radius: 3px; color: white; }
            QLabel { color: #ccc; }
            QScrollBar:vertical { background: #2b2b2b; width: 12px; }
            QScrollBar::handle:vertical { background: #555; min-height: 20px; border-radius: 6px; }
        """)
        
        self.project_path = None
        self.worker_thread = None
        self.worker = None
        self.monitor_thread = None
        self.quote_timer = None
        self.current_quote_idx = 0
        self.generated_videos = [] 
        self.character_cards = {}
        self.active_quote_fetcher = None
        self.review_dialog = None
        self.pending_review_data = None
        
        # Timing Variables
        self.global_start_time = None
        self.scene_start_time = None
        self.timer_interval = 1000 # 1 second
        self.elapsed_timer = QTimer()
        self.elapsed_timer.timeout.connect(self.update_timers)

        self.global_steps = ["Init", "Ollama Start", "Script Gen", "Global Refs", "Prompt Gen", "QA Review", "Ollama Stop"]
        self.scene_steps_template = ["Img Inject", "WF Prep", "Queue Job", "Gen Ph1", "Gen Ph2", "Download", "Save"]
        
        self.init_ui()
        self.start_monitor()
        self.setup_quote_rotator()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # --- LEFT PANEL ---
        left_panel = QWidget()
        left_panel.setMaximumWidth(450)
        left_layout = QVBoxLayout(left_panel)
        
        # 1. Project Setup
        proj_group = QGroupBox("1. Project Setup")
        proj_layout = QVBoxLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Enter Movie Title...")
        self.title_input.textChanged.connect(self.on_title_changed)
        proj_layout.addWidget(QLabel("Movie Title:"))
        proj_layout.addWidget(self.title_input)
        
        # NEW: Genre Selector
        genre_layout = QHBoxLayout()
        genre_layout.addWidget(QLabel("Genres (Select Multiple):"))
        self.genre_list = QListWidget()
        self.genre_list.setSelectionMode(QAbstractItemView.MultiSelection)
        genres_options = [
            "Action", "Anime", "Classic", "Comedy", "Crime", 
            "Documentary", "Drama", "Fantasy", "Horror", "Kids", 
            "Music", "Romance", "Sci-Fi", "Sports", "Thriller"
        ]
        self.genre_list.addItems(genres_options)
        self.genre_list.setMaximumHeight(100) # Compact height
        genre_layout.addWidget(self.genre_list)
        proj_layout.addLayout(genre_layout)
        
        proj_group.setLayout(proj_layout)
        left_layout.addWidget(proj_group)
        
        # 2. Character Manager (UPDATED WITH GENDER SELECTOR)
        char_group = QGroupBox("2. Characters & Mapping")
        char_layout = QVBoxLayout()
        
        num_char_layout = QHBoxLayout()
        num_char_layout.addWidget(QLabel("Num Characters:"))
        self.num_char_combo = QComboBox()
        self.num_char_combo.addItems(["1", "2", "3", "4"])
        self.num_char_combo.setCurrentIndex(0)
        self.num_char_combo.currentIndexChanged.connect(self.update_character_grid)
        num_char_layout.addWidget(self.num_char_combo)
        char_layout.addLayout(num_char_layout)
        
        self.qa_check = QCheckBox("Enable Prompt QA Reviewer")
        self.qa_check.setChecked(True)
        char_layout.addWidget(self.qa_check)
        
        self.char_scroll = QScrollArea()
        self.char_scroll.setWidgetResizable(True)
        self.char_container = QWidget()
        self.char_grid = QGridLayout(self.char_container)
        self.char_grid.setSpacing(10)
        self.char_scroll.setWidget(self.char_container)
        char_layout.addWidget(self.char_scroll)
        
        char_group.setLayout(char_layout)
        left_layout.addWidget(char_group)
        
        # 3. Settings
        settings_group = QGroupBox("3. Cinematic Settings")
        settings_layout = QVBoxLayout()
        
        settings_layout.addWidget(QLabel("Style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Photorealistic", "3D Animation", "Anime", "Cyberpunk"])
        settings_layout.addWidget(self.style_combo)
        
        dur_layout = QHBoxLayout()
        dur_layout.addWidget(QLabel("Clip Secs:"))
        self.clip_dur_spin = QSpinBox()
        self.clip_dur_spin.setRange(5, 20)
        self.clip_dur_spin.setValue(10)
        dur_layout.addWidget(self.clip_dur_spin)
        
        dur_layout.addWidget(QLabel("Total Secs:"))
        self.total_dur_spin = QSpinBox()
        self.total_dur_spin.setRange(10, 600)
        self.total_dur_spin.setValue(60)
        dur_layout.addWidget(self.total_dur_spin)
        settings_layout.addLayout(dur_layout)
        
        settings_layout.addWidget(QLabel("Aspect Ratio:"))
        self.ar_combo = QComboBox()
        self.ar_combo.addItems(list(cfg.ASPECT_RATIOS.keys()))
        settings_layout.addWidget(self.ar_combo)
        
        settings_layout.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        for code, name in cfg.LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        settings_layout.addWidget(self.lang_combo)
        
        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)
        
        # 4. Action Buttons
        btn_layout = QHBoxLayout()
        
        self.generate_btn = QPushButton("GENERATE VIDEO")
        self.generate_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.generate_btn.setStyleSheet("background-color: #28a745; color: white; padding: 15px; font-size: 14px; border-radius: 5px;")
        self.generate_btn.clicked.connect(self.start_generation)
        self.generate_btn.setEnabled(False)
        
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.stop_btn.setStyleSheet("background-color: #dc3545; color: white; padding: 15px; font-size: 14px; border-radius: 5px;")
        self.stop_btn.clicked.connect(self.stop_generation)
        self.stop_btn.setEnabled(False)
        
        btn_layout.addWidget(self.generate_btn, stretch=2)
        btn_layout.addWidget(self.stop_btn, stretch=1)
        
        left_layout.addLayout(btn_layout)
        left_layout.addStretch()
        
        # --- RIGHT PANEL ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        stats_group = QGroupBox("System Health & Timeline")
        stats_layout = QVBoxLayout()
        
        hw_layout = QHBoxLayout()
        self.lbl_cpu = QLabel("CPU: 0%")
        self.lbl_ram = QLabel("RAM: 0%")
        self.lbl_gpu = QLabel("GPU: 0%")
        self.lbl_vram = QLabel("VRAM: 0/0 MB")
        self.lbl_temp = QLabel("Temp: 0°C")
        for lbl in [self.lbl_cpu, self.lbl_ram, self.lbl_gpu, self.lbl_vram, self.lbl_temp]:
            lbl.setStyleSheet("font-weight: bold; color: #0ff;")
            hw_layout.addWidget(lbl)
        stats_layout.addLayout(hw_layout)
        
        time_layout = QHBoxLayout()
        self.lbl_total_elapsed = QLabel("Total Elapsed: 00:00")
        self.lbl_scene_elapsed = QLabel("Current Scene: 00:00")
        self.lbl_avg_scene = QLabel("Avg Per Scene: --:--")
        for lbl in [self.lbl_total_elapsed, self.lbl_scene_elapsed, self.lbl_avg_scene]:
            lbl.setStyleSheet("color: #ffd700; font-weight: bold;")
            time_layout.addWidget(lbl)
        stats_layout.addLayout(time_layout)
        
        tl_layout = QHBoxLayout()
        self.lbl_start_time = QLabel("Start: --:--:--")
        self.lbl_end_time = QLabel("End: --:--:--")
        self.lbl_total_scenes = QLabel("Total: 0")
        self.lbl_gen_scenes = QLabel("Done: 0")
        for lbl in [self.lbl_start_time, self.lbl_end_time, self.lbl_total_scenes, self.lbl_gen_scenes]:
            lbl.setStyleSheet("color: #aaa;")
            tl_layout.addWidget(lbl)
        stats_layout.addLayout(tl_layout)
        
        stats_group.setLayout(stats_layout)
        right_layout.addWidget(stats_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #444; border-radius: 5px; text-align: center; color: white; background-color: #2b2b2b; }
            QProgressBar::chunk { background-color: #007acc; width: 10px; }
        """)
        right_layout.addWidget(self.progress_bar)
        
        tracker_group = QGroupBox("Production Pipeline")
        tracker_layout = QVBoxLayout(tracker_group)
        self.tracker_scroll = QScrollArea()
        self.tracker_scroll.setWidgetResizable(True)
        self.tracker_container = QWidget()
        self.tracker_grid = QVBoxLayout(self.tracker_container)
        self.tracker_grid.setAlignment(Qt.AlignTop)
        self.global_row = PipelineRow("GLOBAL SETUP", self.global_steps)
        self.tracker_grid.addWidget(self.global_row)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #444; max-height: 1px;")
        self.tracker_grid.addWidget(sep)
        self.tracker_scroll.setWidget(self.tracker_container)
        tracker_layout.addWidget(self.tracker_scroll)
        right_layout.addWidget(tracker_group, stretch=2)
        
        prompt_viewer_group = QGroupBox("Live Prompt Preview")
        pv_layout = QVBoxLayout(prompt_viewer_group)
        self.lbl_current_scene = QLabel("Waiting for generation...")
        self.lbl_current_scene.setStyleSheet("color: #0ff; font-weight: bold;")
        pv_layout.addWidget(self.lbl_current_scene)
        
        self.txt_live_prompt = QTextEdit()
        self.txt_live_prompt.setReadOnly(True)
        self.txt_live_prompt.setStyleSheet("background-color: #111; color: #0f0; font-family: 'Consolas'; font-size: 9pt;")
        self.txt_live_prompt.setMaximumHeight(150)
        pv_layout.addWidget(self.txt_live_prompt)
        right_layout.addWidget(prompt_viewer_group)
        
        self.lbl_quote = QLabel("")
        self.lbl_quote.setAlignment(Qt.AlignCenter)
        self.lbl_quote.setWordWrap(True)
        self.lbl_quote.setStyleSheet("color: #ffd700; font-style: italic; font-size: 11pt; padding: 5px; background-color: #2b2b2b; border-radius: 5px;")
        right_layout.addWidget(self.lbl_quote)
        
        gallery_group = QGroupBox("Generated Videos")
        gallery_layout = QVBoxLayout()
        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_container = QWidget()
        self.gallery_layout_inner = QHBoxLayout(self.gallery_container)
        self.gallery_layout_inner.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.gallery_scroll.setWidget(self.gallery_container)
        gallery_layout.addWidget(self.gallery_scroll)
        gallery_group.setLayout(gallery_layout)
        right_layout.addWidget(gallery_group, stretch=1)
        
        splitter = QSplitter()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([450, 950])
        main_layout.addWidget(splitter)
        
        self.update_character_grid()
        
    def update_character_grid(self):
        while self.char_grid.count():
            item = self.char_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        self.character_cards.clear()
        
        count = int(self.num_char_combo.currentText())
        all_roles = ["hero", "heroine", "villain", "sidekick"]
        active_roles = all_roles[:count]
        
        cols = 2 
        
        for i, role in enumerate(active_roles):
            idx = i + 1
            card = CharacterCard(role, idx)
            card.image_selected.connect(lambda r, p, c=card: self.on_char_image_selected(r, p, c))
            
            row = i // cols
            col = i % cols
            self.char_grid.addWidget(card, row, col)
            self.character_cards[role] = card
            
        self.check_generate_enabled()

    def on_char_image_selected(self, role, path, card):
        pass

    def check_generate_enabled(self):
        has_title = len(self.title_input.text().strip()) > 0
        self.generate_btn.setEnabled(has_title)

    def on_title_changed(self, text):
        self.check_generate_enabled()
        
    def create_project_folder(self, title):
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.project_path = cfg.PROJECTS_ROOT / f"{safe_title}_{ts}"
        for d in ["characters", "scripts", "prompts", "output"]:
            (self.project_path / d).mkdir(parents=True, exist_ok=True)
            
    def start_monitor(self):
        self.monitor_thread = SystemMonitor()
        self.monitor_thread.stats_updated.connect(self.update_stats)
        self.monitor_thread.start()
        
    def setup_quote_rotator(self):
        self.quote_timer = QTimer()
        self.quote_timer.timeout.connect(self.trigger_ai_quote)
        self.quote_timer.start(20000)
        self.trigger_ai_quote()

    def trigger_ai_quote(self):
        if self.worker_thread and self.worker_thread.isRunning():
            return
        title = self.title_input.text().strip() or "General Creativity"
        if self.active_quote_fetcher:
            return
        self.active_quote_fetcher = QuoteFetcher(title)
        self.active_quote_fetcher.quote_received.connect(self.on_quote_fetched)
        self.active_quote_fetcher.start_fetch()

    def on_quote_fetched(self, quote):
        self.lbl_quote.setText(f"💡 {quote}")
        self.active_quote_fetcher = None
        
    def update_stats(self, stats):
        self.lbl_cpu.setText(f"CPU: {stats['cpu']:.0f}%")
        self.lbl_ram.setText(f"RAM: {stats['ram']:.0f}%")
        self.lbl_gpu.setText(f"GPU: {stats['gpu_load']:.0f}%")
        self.lbl_vram.setText(f"VRAM: {stats['vram_used']:.0f}/{stats['vram_total']:.0f} MB")
        self.lbl_temp.setText(f"Temp: {stats['gpu_temp']:.0f}°C")
        self.lbl_gpu.setStyleSheet(f"color: {'#f00' if stats['gpu_load'] > 90 else '#0ff'}; font-weight: bold;")
        
    def add_video_to_gallery(self, video_path):
        btn = QPushButton(Path(video_path).name)
        btn.setToolTip(str(video_path))
        btn.setStyleSheet("background-color: #333; color: #fff; padding: 10px; border-radius: 5px; text-align: left;")
        btn.clicked.connect(lambda checked, p=video_path: self.open_video(p))
        self.gallery_layout_inner.addWidget(btn)
        self.generated_videos.append(video_path)
        
    def open_video(self, path):
        try:
            subprocess.Popen([str(path)], shell=True)
        except Exception as e:
            pass

    def log_pipeline_event(self, scope, step_index, status="active"):
        if scope == "global":
            if status == "active":
                self.global_row.activate_step(step_index)
            elif status == "done":
                self.global_row.complete_step(step_index, True)
            elif status == "error":
                self.global_row.complete_step(step_index, False)
                
        elif scope.startswith("scene_"):
            scene_num = int(scope.split("_")[1])
            scene_row = None
            for i in range(self.tracker_grid.count()):
                widget = self.tracker_grid.itemAt(i).widget()
                if isinstance(widget, PipelineRow) and widget.title_label.text() == f"SCENE {scene_num}":
                    scene_row = widget
                    break
            
            if not scene_row:
                scene_row = PipelineRow(f"SCENE {scene_num}", self.scene_steps_template)
                self.tracker_grid.addWidget(scene_row)
                
            if status == "active":
                scene_row.activate_step(step_index)
            elif status == "done":
                scene_row.complete_step(step_index, True)
            elif status == "error":
                scene_row.complete_step(step_index, False)

    def update_timers(self):
        if not self.global_start_time:
            return
            
        now = time.time()
        total_secs = int(now - self.global_start_time)
        mins, secs = divmod(total_secs, 60)
        self.lbl_total_elapsed.setText(f"Total Elapsed: {mins:02d}:{secs:02d}")
        
        if self.scene_start_time:
            scene_secs = int(now - self.scene_start_time)
            sm, ss = divmod(scene_secs, 60)
            self.lbl_scene_elapsed.setText(f"Current Scene: {sm:02d}:{ss:02d}")
            
            completed_scenes = int(self.lbl_gen_scenes.text().split(":")[1].strip())
            if completed_scenes > 0:
                avg_secs = total_secs / completed_scenes
                am, as_ = divmod(int(avg_secs), 60)
                self.lbl_avg_scene.setText(f"Avg Per Scene: {am:02d}:{as_:02d}")

    def start_generation(self):
        if not self.title_input.text().strip():
            return
            
        if not self.project_path:
            self.create_project_folder(self.title_input.text())
            
        user_char_map = {}
        # Collect images AND genders
        for role, card in self.character_cards.items():
            if card.image_path:
                import shutil
                dest = self.project_path / "characters" / Path(card.image_path).name
                if not dest.exists():
                    shutil.copy(card.image_path, dest)
                # Store both filename and gender in the map value as a dict
                user_char_map[role] = {
                    "filename": dest.name,
                    "gender": card.gender
                }
            else:
                # If no image, still record gender for text-only fallback logic if needed
                user_char_map[role] = {
                    "filename": None,
                    "gender": card.gender
                }
                 
        selected_genres = [item.text() for item in self.genre_list.selectedItems()]
        if not selected_genres:
            selected_genres = ["Action"] # Default fallback
            
        config_data = {
            'project_path': str(self.project_path),
            'title': self.title_input.text(),
            'style': self.style_combo.currentText(),
            'genres': selected_genres, # <--- PASS THIS TO WORKER            
            'num_clips': max(1, self.total_dur_spin.value() // self.clip_dur_spin.value()),
            'clip_duration': self.clip_dur_spin.value(),
            'language': self.lang_combo.currentData(),
            'aspect_ratio': self.ar_combo.currentText(),
            'mode': 'mixed',
            'char_map': user_char_map, # Now contains dicts with gender
            'enable_qa': self.qa_check.isChecked(),
            'num_chars': int(self.num_char_combo.currentText())
        }
        
        self.global_start_time = time.time()
        self.scene_start_time = None
        self.elapsed_timer.start(self.timer_interval)
        
        self.generate_btn.setEnabled(False)
        self.stop_btn.setEnabled(True) 
        self.progress_bar.setValue(0)
        self.lbl_start_time.setText(f"Start: {datetime.now().strftime('%H:%M:%S')}")
        self.lbl_end_time.setText("End: --:--:--")
        self.lbl_total_scenes.setText(f"Total: {config_data['num_clips']}")
        self.lbl_gen_scenes.setText("Done: 0")
        self.lbl_total_elapsed.setText("Total Elapsed: 00:00")
        self.lbl_scene_elapsed.setText("Current Scene: 00:00")
        self.lbl_avg_scene.setText("Avg Per Scene: --:--")
        self.txt_live_prompt.clear()
        self.lbl_current_scene.setText("Initializing...")
        
        self.global_row.reset_all()
        for i in reversed(range(self.tracker_grid.count())):
            widget = self.tracker_grid.itemAt(i).widget()
            if isinstance(widget, PipelineRow) and widget.title_label.text().startswith("SCENE"):
                widget.setParent(None)
        
        if self.monitor_thread:
            self.monitor_thread.pause()
            
        self.worker_thread = QThread()
        self.worker = GenerationWorker(config_data)
        self.worker.moveToThread(self.worker_thread)
        
        self.worker_thread.started.connect(self.worker.run)
        self.worker.pipeline_signal.connect(self.log_pipeline_event)
        self.worker.video_ready_signal.connect(self.add_video_to_gallery)
        self.worker.current_prompt_signal.connect(self.on_prompt_updated)
        # Connect the new review signal
        self.worker.review_request_signal.connect(self.open_review_dialog)
        self.worker.finished_signal.connect(self.on_finished)
        
        self.worker_thread.start()

    def on_prompt_updated(self, scene_label, prompt_text):
        self.lbl_current_scene.setText(f"🎬 {scene_label} Prompt:")
        self.txt_live_prompt.setPlainText(prompt_text)
        cursor = self.txt_live_prompt.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.txt_live_prompt.setTextCursor(cursor)
        self.scene_start_time = time.time()

    def stop_generation(self):
        reply = QMessageBox.question(self, 'Stop Generation', 'Are you sure you want to stop?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.worker:
                self.worker.cancel()
            # Do NOT call cleanup here. Let the worker handle it via finished_signal.

    def on_finished(self, success, msg):
        self.elapsed_timer.stop()
        self.generate_btn.setEnabled(True)
        self.stop_btn.setEnabled(False) 
        self.lbl_end_time.setText(f"End: {datetime.now().strftime('%H:%M:%S')}")
        
        if success:
            QMessageBox.information(self, "Complete", "Video generation finished successfully!")
        else:
            if msg != "Stopped by User" and msg != "Cancelled by User":
                QMessageBox.critical(self, "Error", f"Generation Failed:\n{msg}")
        
        # DEFERRED CLEANUP TO PREVENT DEADLOCK
        QTimer.singleShot(0, self._perform_thread_cleanup)

    def _perform_thread_cleanup(self):
        """Safe thread cleanup executed from Main Thread."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            if not self.worker_thread.wait(5000):
                print("Warning: Worker thread did not exit cleanly.")
                self.worker_thread.terminate()
                self.worker_thread.wait()
                
        self.worker_thread = None
        self.worker = None
        
        if self.monitor_thread:
            self.monitor_thread.resume()
            
        QTimer.singleShot(2000, self.trigger_ai_quote)

    def closeEvent(self, event):
        self.elapsed_timer.stop()
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait(2000)
            
        if self.worker and self.worker_thread and self.worker_thread.isRunning():
            self.worker.cancel()
            self.worker_thread.quit()
            if not self.worker_thread.wait(5000):
                self.worker_thread.terminate()
                self.worker_thread.wait()
        
        try:
            from msr_engine.model_manager import cleanup_after_ollama, cleanup_after_comfyui
            cleanup_after_ollama()
            cleanup_after_comfyui()
        except:
            pass
            
        event.accept()

    def open_review_dialog(self, scenes_data, global_refs, local_prompts_list):
        """Slot called by Worker when prompts are ready for review."""
        # Extract metadata from config for dialog initialization
        title = self.config_data.get('title', 'Untitled') if hasattr(self, 'config_data') else self.title_input.text()
        style = self.config_data.get('style', 'Photorealistic') if hasattr(self, 'config_data') else self.style_combo.currentText()
        lang = self.config_data.get('language', 'en') if hasattr(self, 'config_data') else self.lang_combo.currentData()
        
        self.review_dialog = AdvancedReviewDialog(
            title=title,
            style=style,
            language=lang,
            scenes_data=scenes_data,
            global_refs=global_refs,
            local_prompts_list=local_prompts_list,
            parent=self
        )
        
        # Connect signals
        self.review_dialog.approved.connect(self.on_review_approved)
        self.review_dialog.rejected.connect(self.on_review_rejected)
        
        self.review_dialog.show()
        
    def on_review_approved(self, payload):
        """User clicked Approve All"""
        if self.worker:
            self.worker.apply_reviews(
                payload['scenes'],
                payload['global_refs'],
                payload['local_prompts']
            )
        # Close dialog
        if self.review_dialog:
            self.review_dialog.close()
            self.review_dialog = None
            
    def on_review_rejected(self):
        """User cancelled"""
        if self.worker:
            self.worker.cancel()
        if self.review_dialog:
            self.review_dialog.close()
            self.review_dialog = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())