import subprocess
import os
from PyQt6.QtCore import QThread, pyqtSignal
from .parser import IperfParser
from iperf_gui.utils.paths import resource_path

class IPerfWorker(QThread):
    # Signals to communicate with the GUI
    log_message = pyqtSignal(str)
    telemetry_data = pyqtSignal(dict)
    finished = pyqtSignal(int)  # Emit exit code
    
    def __init__(self, cmd_args):
        super().__init__()
        self.cmd_args = cmd_args
        self.process = None
        self.is_running = True
        self.parser = IperfParser()

    def run(self):
        # Locate iperf3.exe
        iperf_exe = resource_path('iperf3.exe')
        
        # Build command
        full_cmd = [iperf_exe] + self.cmd_args
        
        # Enforce interval output if not present
        if '-i' not in full_cmd:
            full_cmd.extend(['-i', '0.5'])
            
        self.log_message.emit(f"Executing: {' '.join(full_cmd)}")
        
        try:
            # We use CREATE_NO_WINDOW on Windows to prevent a console popping up
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW
                
            self.process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags
            )
            
            # Read stdout line by line
            for line in iter(self.process.stdout.readline, ''):
                if not self.is_running:
                    break
                    
                if line:
                    line_clean = line.strip()
                    self.log_message.emit(line_clean)
                    
                    # Parse telemetry
                    metrics = self.parser.parse_line(line_clean)
                    if metrics:
                        self.telemetry_data.emit(metrics)
            
            self.process.stdout.close()
            self.process.wait()
            self.finished.emit(self.process.returncode)
            
        except FileNotFoundError:
            self.log_message.emit("ERROR: iperf3.exe not found in the application directory.")
            self.finished.emit(-1)
        except Exception as e:
            self.log_message.emit(f"ERROR: {str(e)}")
            self.finished.emit(-1)

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
