"""
MSR Producer - Real-Time Generation Dashboard
Tracks total scenes, elapsed time, per-scene duration, and output status.
UPDATED: Handles Cold Start vs Warm State timing for accurate ETAs.
"""

import time
from datetime import datetime
from .utils import console

class GenerationDashboard:
    def __init__(self, total_scenes, estimated_sec_per_scene=300):
        self.total_scenes = total_scenes
        self.completed_scenes = 0
        self.failed_scenes = 0
        self.start_time = None
        self.scene_start_times = {}  # Track individual scene start times
        self.scene_durations = []   # List of durations for completed scenes
        
        # Initial estimate (usually cold start is higher, but we start conservative)
        self.current_estimated_sec_per_scene = estimated_sec_per_scene
        
        # Output tracking
        self.files_downloaded = 0
        self.output_folder = ""

    def start(self):
        """Call this right before the generation loop begins."""
        self.start_time = time.time()
        console.rule("📊 GENERATION DASHBOARD STARTED")
        console.print(f"[bold cyan]Total Scenes:[/bold cyan] {self.total_scenes}")
        console.print(f"[bold cyan]Initial Est. Time Per Scene:[/bold cyan] ~{self.current_estimated_sec_per_scene}s")
        console.print(f"[dim](Note: Scene 1 may take longer due to model loading/CUDA compilation)[/dim]")
        console.print(f"[bold cyan]Start Time:[/bold cyan] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        console.print("-" * 50)

    def begin_scene(self, scene_index):
        """Call this when starting a specific scene."""
        self.scene_start_times[scene_index] = time.time()
        elapsed_total = int(time.time() - self.start_time)
        
        # Special message for Scene 1
        if scene_index == 1:
            console.print(f"[yellow]⚡ Scene 1/{self.total_scenes} started... (Cold Start: Loading Models & Compiling Kernels)[/yellow]")
        else:
            console.print(f"[dim]Scene {scene_index}/{self.total_scenes} started... (Global Elapsed: {elapsed_total}s)[/dim]")

    def complete_scene(self, scene_index, success=True, downloaded=False):
        """Call this when a scene finishes generation."""
        if scene_index not in self.scene_start_times:
            return
            
        end_time = time.time()
        duration = int(end_time - self.scene_start_times[scene_index])
        
        if success:
            self.completed_scenes += 1
            self.scene_durations.append(duration)
            if downloaded:
                self.files_downloaded += 1
                
            # UPDATE ESTIMATE LOGIC
            if scene_index == 1:
                # After Scene 1, we know the "Warm" time is likely lower. 
                # But for safety, let's look at the last 3 scenes if available, 
                # or just use the current duration as the new baseline if it's stable.
                # Actually, Scene 1 is usually the outlier. Let's wait for Scene 2 to adjust.
                pass 
            
            if scene_index >= 2:
                # Calculate average of all warm scenes (excluding Scene 1 if possible, or including it if only 2 scenes done)
                warm_durations = self.scene_durations[1:] if len(self.scene_durations) > 1 else self.scene_durations
                if warm_durations:
                    avg_warm = sum(warm_durations) / len(warm_durations)
                    # Smooth the estimate slightly to account for variance
                    self.current_estimated_sec_per_scene = int(avg_warm)
            
            remaining_scenes = self.total_scenes - self.completed_scenes
            remaining_est = self.current_estimated_sec_per_scene * remaining_scenes
            
            console.print(f"[green]✓ Scene {scene_index} Completed[/green] | "
                          f"Duration: [bold]{duration}s[/bold] | "
                          f"Avg (Warm): {self.current_estimated_sec_per_scene}s | "
                          f"ETA Remaining: ~{remaining_est//60}m {int(remaining_est%60)}s")
        else:
            self.failed_scenes += 1
            console.print(f"[red]✗ Scene {scene_index} Failed[/red] | Duration: {duration}s")

    def finish(self):
        """Call this after all scenes are processed."""
        total_elapsed = int(time.time() - self.start_time)
        hours = total_elapsed // 3600
        minutes = (total_elapsed % 3600) // 60
        seconds = total_elapsed % 60
        
        console.rule("📊 GENERATION SUMMARY")
        console.print(f"[bold green]Total Scenes Processed:[/bold green] {self.completed_scenes + self.failed_scenes}")
        console.print(f"[bold green]Successful:[/bold green] {self.completed_scenes}")
        console.print(f"[bold red]Failed:[/bold red] {self.failed_scenes}")
        console.print(f"[cyan]Files Downloaded to Project:[/cyan] {self.files_downloaded}")
        console.print(f"[yellow]Total Generation Time:[/yellow] {hours}h {minutes}m {seconds}s")
        
        if self.scene_durations:
            fastest = min(self.scene_durations)
            slowest = max(self.scene_durations)
            average = sum(self.scene_durations) / len(self.scene_durations)
            
            # Separate Cold vs Warm stats if we have enough data
            if len(self.scene_durations) > 1:
                cold_time = self.scene_durations[0]
                warm_avg = sum(self.scene_durations[1:]) / len(self.scene_durations[1:])
                console.print(f"[dim]Cold Start (Scene 1): {cold_time}s | Avg Warm Time: {warm_avg:.1f}s[/dim]")
            
            console.print(f"[dim]Overall Fastest: {fastest}s | Slowest: {slowest}s | Average: {average:.1f}s[/dim]")
        
        console.print("\n[bold magenta]Dashboard Closed.[/bold magenta]")