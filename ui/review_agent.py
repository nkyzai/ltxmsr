import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, 
    QPushButton, QWidget, QGroupBox, QMessageBox, QSplitter, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor

class ReviewDialog(QDialog):
    # Signals to communicate back to Main Window
    approved = Signal(dict)  # Emits final config with approved prompts/script
    rejected = Signal()      # Emits if user cancels
    
    def __init__(self, title, style, language, scenes_data, global_refs, local_prompts, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"CineAgent Director's Review: {title}")
        self.setGeometry(100, 100, 1400, 800)
        
        self.title = title
        self.style = style
        self.language = language
        self.scenes_data = scenes_data # List of scene dicts
        self.global_refs = global_refs # String
        self.local_prompts = local_prompts # List of strings
        
        self.current_scene_idx = 0
        self.edited_prompts = list(local_prompts) # Copy to allow editing
        self.diagnostic_report = []
        
        self.init_ui()
        self.run_diagnostics()
        self.load_scene(0)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # Header Info
        info_label = QLabel(f"<b>Title:</b> {self.title} | <b>Style:</b> {self.style} | <b>Lang:</b> {self.language}")
        info_label.setStyleSheet("padding: 10px; background-color: #2b2b2b; color: #fff; border-radius: 5px;")
        main_layout.addWidget(info_label)

        # Navigation Bar
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Prev Scene")
        self.btn_next = QPushButton("Next Scene ▶")
        self.lbl_scene_indicator = QLabel("Scene 1 / ?")
        self.lbl_scene_indicator.setAlignment(Qt.AlignCenter)
        self.lbl_scene_indicator.setStyleSheet("font-weight: bold; color: #0ff; min-width: 150px;")
        
        self.btn_prev.clicked.connect(self.prev_scene)
        self.btn_next.clicked.connect(self.next_scene)
        
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addStretch()
        nav_layout.addWidget(self.lbl_scene_indicator)
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
        self.btn_approve_scene = QPushButton("✅ Accept Scene")
        self.btn_reject_scene = QPushButton("❌ Reject Changes")
        
        self.btn_regenerate.clicked.connect(self.regenerate_suggestion)
        self.btn_approve_scene.clicked.connect(self.approve_current_scene)
        self.btn_reject_scene.clicked.connect(self.reject_current_scene)
        
        action_layout.addWidget(self.btn_regenerate)
        action_layout.addWidget(self.btn_approve_scene)
        action_layout.addWidget(self.btn_reject_scene)
        fix_layout.addLayout(action_layout)
        
        splitter.addWidget(fix_group)
        
        # Set initial sizes (Left 30%, Middle 35%, Right 35%)
        splitter.setSizes([400, 450, 450])
        main_layout.addWidget(splitter)
        
        # Global Actions Footer
        footer_layout = QHBoxLayout()
        self.btn_approve_all = QPushButton("🚀 APPROVE ALL & RENDER")
        self.btn_approve_all.setStyleSheet("background-color: #28a745; color: white; padding: 15px; font-size: 14px; font-weight: bold;")
        self.btn_approve_all.clicked.connect(self.finalize_and_close)
        
        self.btn_cancel = QPushButton("❌ CANCEL GENERATION")
        self.btn_cancel.setStyleSheet("background-color: #dc3545; color: white; padding: 15px; font-size: 14px;")
        self.btn_cancel.clicked.connect(self.rejected.emit)
        self.close()
        
        footer_layout.addWidget(self.btn_cancel)
        footer_layout.addStretch()
        footer_layout.addWidget(self.btn_approve_all)
        main_layout.addLayout(footer_layout)

    def run_diagnostics(self):
        """Simulates an AI agent checking consistency."""
        report_html = "<h3>Global Analysis</h3>"
        
        # Check 1: Title vs Genre Consistency
        if "cat" in self.title.lower() and "cyberpunk" not in self.style.lower():
             report_html += "<p class='warning'>⚠ Warning: Title mentions 'Cat' but Style is generic. Consider 'Anime' or 'Pixar-style'.</p>"
        else:
             report_html += "<p class='success'>✓ Title/Genre Alignment: Good.</p>"
             
        # Check 2: Character Gender/Voice Mismatch (The bug we fixed earlier)
        # We scan global_refs for "Woman" + "Male Voice"
        if "woman" in self.global_refs.lower() and "male voice" in self.global_refs.lower():
             report_html += "<p class='critical'>🔴 CRITICAL: Female character assigned Male Voice in Global Refs!</p>"
        else:
             report_html += "<p class='success'>✓ Audio/Visual Identity: Consistent.</p>"
             
        # Check 3: Prompt Length
        avg_len = sum(len(p) for p in self.local_prompts) / len(self.local_prompts) if self.local_prompts else 0
        if avg_len < 50:
             report_html += f"<p class='critical'>🔴 CRITICAL: Prompts too short (Avg {avg_len:.0f} chars). Risk of hallucination.</p>"
        elif avg_len > 800:
             report_html += f"<p class='warning'>⚠ Warning: Prompts very long (Avg {avg_len:.0f} chars). May confuse LTX.</p>"
        else:
             report_html += f"<p class='success'>✓ Prompt Density: Optimal ({avg_len:.0f} chars).</p>"

        self.txt_diagnosis.setHtml(report_html)

    def load_scene(self, idx):
        if idx < 0 or idx >= len(self.scenes_data):
            return
            
        self.current_scene_idx = idx
        self.lbl_scene_indicator.setText(f"Scene {idx+1} / {len(self.scenes_data)}")
        
        scene = self.scenes_data[idx]
        original_prompt = self.local_prompts[idx]
        edited_prompt = self.edited_prompts[idx]
        
        # Display Original
        self.txt_original.setPlainText(original_prompt)
        
        # Display Edited (with simple highlighting logic simulation)
        # In a real app, you'd diff these two strings. Here we just show the editable version.
        self.txt_fixed.setPlainText(edited_prompt)
        
        # Update Diagnosis for this specific scene
        self.update_scene_diagnosis(scene, original_prompt, edited_prompt)

    def update_scene_diagnosis(self, scene, orig, edited):
        html = f"<h3>Scene {self.current_scene_idx + 1} Details</h3>"
        
        # Check if role names leaked into prompt
        forbidden = ["hero", "villain", "girl", "boy"]
        leaks = [word for word in forbidden if word in orig.lower()]
        
        if leaks:
            html += f"<p class='critical'>🔴 Leak Detected: Found role names {leaks} in prompt. Should be 'Image 1'.</p>"
        else:
            html += "<p class='success'>✓ Tag Usage: Correct (Image X only).</p>"
            
        # Check Dialogue Format
        if "'" in orig or '"' in orig:
             if "Audio" not in orig:
                 html += "<p class='warning'>⚠ Dialogue present but missing 'Audio X:' prefix.</p>"
        
        # Show Character Map for context
        main_char = scene.get('main_character', '?')
        sec_chars = scene.get('secondary_characters', [])
        html += f"<hr><p><b>Cast:</b> Main: {main_char}, Secondary: {sec_chars}</p>"
        html += f"<p><b>Location:</b> {scene.get('location', '?')}</p>"
        
        self.txt_diagnosis.append(html)

    def prev_scene(self):
        self.save_current_edit()
        self.load_scene(self.current_scene_idx - 1)

    def next_scene(self):
        self.save_current_edit()
        self.load_scene(self.current_scene_idx + 1)
        
    def save_current_edit(self):
        # Save text from editor back to our internal list
        if 0 <= self.current_scene_idx < len(self.edited_prompts):
            self.edited_prompts[self.current_scene_idx] = self.txt_fixed.toPlainText()

    def approve_current_scene(self):
        self.save_current_edit()
        # Visual feedback
        self.txt_fixed.setStyleSheet("background-color: #1a2a1a; border: 2px solid #4caf50;")
        QMessageBox.information(self, "Approved", f"Scene {self.current_scene_idx+1} accepted.")

    def reject_current_scene(self):
        # Revert to original
        if 0 <= self.current_scene_idx < len(self.local_prompts):
            self.edited_prompts[self.current_scene_idx] = self.local_prompts[self.current_scene_idx]
            self.txt_fixed.setPlainText(self.local_prompts[self.current_scene_idx])
            self.txt_fixed.setStyleSheet("background-color: #2a1a1a; border: 2px solid #dc3545;")

    def regenerate_suggestion(self):
        # Mock regeneration logic
        # In production, this would call Ollama with the diagnostic errors as feedback
        current_text = self.txt_fixed.toPlainText()
        suggestion = current_text.replace("stands alert", "moves dynamically").replace("scanning for threats", "engaging target")
        self.txt_fixed.setPlainText(suggestion)
        self.txt_fixed.setStyleSheet("background-color: #1a1a2a; border: 2px solid #007acc;") # Blue flash

    def finalize_and_close(self):
        self.save_current_edit()
        
        # Package the final data
        final_payload = {
            'scenes': self.scenes_data,
            'global_refs': self.global_refs,
            'local_prompts': self.edited_prompts,
            'approved_by_user': True
        }
        
        self.approved.emit(final_payload)
        self.accept()
