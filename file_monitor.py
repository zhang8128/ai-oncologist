import os
import time
import hashlib
from datetime import datetime
import json
import difflib
from protein_analyzer import ProteinAnalyzer

class FileMonitor:
    def __init__(self, directory_to_watch):
        self.directory = directory_to_watch
        self.state_file = "memlog/file_states.json"
        self.changes_file = "memlog/file_changes.log"
        self.analyzer = ProteinAnalyzer()
        self.file_states = {}
        self.initialize_state()
        
    def get_file_hash(self, filepath):
        """Calculate MD5 hash of file contents."""
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def get_file_content(self, filepath):
        """Get file content as a list of lines."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.readlines()
        except UnicodeDecodeError:
            return []

    def initialize_state(self):
        """Initialize or update the state with current files."""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                self.file_states = json.load(f)
        
        for filename in os.listdir(self.directory):
            filepath = os.path.join(self.directory, filename)
            if os.path.isfile(filepath):
                current_content = self.get_file_content(filepath)
                self.file_states[filename] = {
                    'hash': self.get_file_hash(filepath),
                    'mtime': os.path.getmtime(filepath),
                    'size': os.path.getsize(filepath),
                    'content': current_content
                }
        
        self.save_state()

    def save_state(self):
        """Save current file states."""
        with open(self.state_file, 'w') as f:
            json.dump(self.file_states, f, indent=4)

    def log_change(self, message, content=None):
        """Log changes with timestamp and optional content."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.changes_file, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] {message}\n")
            if content:
                f.write("Content:\n")
                f.write(content)
                f.write("\n" + "-"*50 + "\n")

    def handle_file_change(self, filename, content, change_type="modified"):
        """Handle a file change event by processing content and updating state."""
        # Log the change
        self.log_change(f"File {change_type}: {filename}", content)
        
        # Process the content for protein targets
        print(f"\nProcessing {change_type} file: {filename}")
        self.analyzer.analyze_content(filename, content)

    def check_for_changes(self):
        """Check for any changes in the monitored directory."""
        current_files = {}
        
        # Get current state of all files
        for filename in os.listdir(self.directory):
            filepath = os.path.join(self.directory, filename)
            if os.path.isfile(filepath):
                current_content = self.get_file_content(filepath)
                current_hash = self.get_file_hash(filepath)
                current_files[filename] = {
                    'hash': current_hash,
                    'mtime': os.path.getmtime(filepath),
                    'size': os.path.getsize(filepath),
                    'content': current_content
                }

                # Handle new files
                if filename not in self.file_states:
                    self.handle_file_change(filename, ''.join(current_content), "new")
                # Handle modified files
                elif current_hash != self.file_states[filename]['hash']:
                    self.handle_file_change(filename, ''.join(current_content), "modified")

        # Handle deleted files
        for filename in self.file_states:
            if filename not in current_files:
                self.handle_file_change(
                    filename, 
                    ''.join(self.file_states[filename]['content']), 
                    "deleted"
                )

        # Update state
        self.file_states = current_files
        self.save_state()

    def monitor(self, interval=5):
        """Start monitoring the directory with specified interval."""
        print(f"Starting to monitor directory: {self.directory}")
        print(f"Changes will be logged to: {self.changes_file}")
        print(f"Relevant sources will be saved to: memlog/relevant_sources.json")
        print("Press Ctrl+C to stop monitoring")
        
        try:
            while True:
                self.check_for_changes()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped")

if __name__ == "__main__":
    monitor = FileMonitor("papers")
    monitor.monitor()
