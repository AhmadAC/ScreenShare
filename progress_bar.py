import sys
import time

class ConsoleProgressBar:
    """Console progress bar with spinner, elapsed time indicator, and step descriptions."""
    def __init__(self, task="Processing"):
        self.current_step = 0
        self.task = task
        self.detail = ""
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.start_time = time.time()

    def update(self, percent, task=None, detail=""):
        self.current_step = max(0, min(100, percent))
        if task:
            self.task = task
        self.detail = detail
        self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_chars)
        spinner = self.spinner_chars[self.spinner_idx]

        bar_len = 24
        filled_len = int(bar_len * (self.current_step / 100.0))
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed)}s"

        det = f" | {self.detail}" if self.detail else ""
        if len(det) > 36:
            det = det[:33] + "..."

        line = f"\r{spinner} [{bar}] {self.current_step:3d}% ({elapsed_str}) {self.task}{det}"
        sys.stdout.write(line.ljust(85))
        sys.stdout.flush()

    def finish(self, message="Complete!"):
        bar = "█" * 24
        elapsed = time.time() - self.start_time
        line = f"\r✔ [{bar}] 100% ({int(elapsed)}s) {message}"
        sys.stdout.write(line.ljust(85) + "\n")
        sys.stdout.flush()