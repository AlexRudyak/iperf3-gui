import csv
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from .engine import IPerfWorker

class FuzzEngine(QObject):
    # Signals
    sweep_started = pyqtSignal()
    sweep_finished = pyqtSignal()
    iteration_started = pyqtSignal(int, int, str) # current, total, desc
    iteration_finished = pyqtSignal(dict) # Results of iteration
    log_message = pyqtSignal(str)
    telemetry_data = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.is_running = False
        self.sweep_params = []
        self.current_idx = 0
        self.base_args = []
        
        self.worker = None
        self.results = []
        
        # Accumulators for current iteration
        self.current_bws = []
        self.current_retransmits = 0
        self.current_loss = 0
        
    def start_sweep(self, base_args, param_flag, start_val, end_val, step_val, duration, cooldown):
        if self.is_running:
            return
            
        self.base_args = base_args
        self.param_flag = param_flag
        self.duration = duration
        self.cooldown = cooldown
        
        # Build parameter list (Linear sweep)
        self.sweep_params = list(range(start_val, end_val + step_val, step_val))
        if not self.sweep_params:
            self.log_message.emit("Invalid sweep parameters (start > end with positive step?)")
            return
            
        self.is_running = True
        self.current_idx = 0
        self.results = []
        self.sweep_started.emit()
        self.log_message.emit(f"Starting sweep for {param_flag} from {start_val} to {end_val} (Step: {step_val})")
        
        self._run_next_iteration()
        
    def _run_next_iteration(self):
        if not self.is_running or self.current_idx >= len(self.sweep_params):
            self._finish_sweep()
            return
            
        param_val = self.sweep_params[self.current_idx]
        self.log_message.emit(f"--- Iteration {self.current_idx + 1}/{len(self.sweep_params)}: {self.param_flag} = {param_val} ---")
        self.iteration_started.emit(self.current_idx + 1, len(self.sweep_params), f"{self.param_flag} {param_val}")
        
        # Reset accumulators
        self.current_bws = []
        self.current_retransmits = 0
        self.current_loss = 0
        
        # Build args
        args = self.base_args.copy()
        args.extend([self.param_flag, str(param_val)])
        args.extend(['-t', str(self.duration)])
        
        # Start worker
        self.worker = IPerfWorker(args)
        self.worker.log_message.connect(self.log_message.emit)
        self.worker.telemetry_data.connect(self._handle_telemetry)
        self.worker.finished.connect(self._iteration_done)
        self.worker.start()
        
    def _handle_telemetry(self, metrics):
        self.telemetry_data.emit(metrics)
        if 'bandwidth_mbps' in metrics:
            self.current_bws.append(metrics['bandwidth_mbps'])
        if 'retransmits' in metrics:
            self.current_retransmits += metrics['retransmits']
        if 'loss_count' in metrics:
            self.current_loss += metrics['loss_count']
            
    def _iteration_done(self, exit_code):
        if not self.is_running:
            return
            
        # Calculate iteration results
        avg_bw = sum(self.current_bws) / len(self.current_bws) if self.current_bws else 0
        peak_bw = max(self.current_bws) if self.current_bws else 0
        
        res = {
            'Parameter': self.param_flag,
            'Value': self.sweep_params[self.current_idx],
            'Avg Bandwidth (Mbps)': round(avg_bw, 2),
            'Peak Bandwidth (Mbps)': round(peak_bw, 2),
            'Total Retransmits': self.current_retransmits,
            'Total Loss': self.current_loss
        }
        self.results.append(res)
        self.iteration_finished.emit(res)
        
        self.current_idx += 1
        
        if self.current_idx < len(self.sweep_params):
            self.log_message.emit(f"Cooldown for {self.cooldown} seconds...")
            QTimer.singleShot(self.cooldown * 1000, self._run_next_iteration)
        else:
            self._finish_sweep()
            
    def _finish_sweep(self):
        self.is_running = False
        self.log_message.emit("Fuzzing sweep finished.")
        self.sweep_finished.emit()
        
    def stop(self):
        self.is_running = False
        if self.worker:
            self.worker.stop()
            self.worker.wait()
