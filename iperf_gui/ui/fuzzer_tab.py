from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QGroupBox, 
                             QFormLayout, QComboBox, QSpinBox, QPushButton)
from PyQt6.QtCore import pyqtSignal

class FuzzerTab(QWidget):
    start_sweep_signal = pyqtSignal(str, int, int, int, int, int) # param, start, end, step, dur, cd
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        group = QGroupBox("Linear Parameter Sweep")
        form_layout = QFormLayout(group)
        form_layout.setSpacing(10)
        
        # Parameter Selection
        self.param_combo = QComboBox()
        self.param_combo.addItem("MSS / MTU (-M)", "-M")
        self.param_combo.addItem("Window Size (-w)", "-w")
        form_layout.addRow("Target Parameter:", self.param_combo)
        
        # Sweep Range
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, 1000000)
        self.start_spin.setValue(500)
        form_layout.addRow("Start Value:", self.start_spin)
        
        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, 1000000)
        self.end_spin.setValue(1500)
        form_layout.addRow("End Value:", self.end_spin)
        
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 100000)
        self.step_spin.setValue(100)
        form_layout.addRow("Step Value:", self.step_spin)
        
        # Timing
        self.dur_spin = QSpinBox()
        self.dur_spin.setRange(1, 3600)
        self.dur_spin.setValue(5)
        form_layout.addRow("Duration per iteration (s):", self.dur_spin)
        
        self.cd_spin = QSpinBox()
        self.cd_spin.setRange(0, 3600)
        self.cd_spin.setValue(2)
        form_layout.addRow("Cooldown between tests (s):", self.cd_spin)
        
        # Button
        self.start_btn = QPushButton("Start Sweep")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.clicked.connect(self._on_start)
        
        layout.addWidget(group)
        layout.addWidget(self.start_btn)
        layout.addStretch()
        
    def _on_start(self):
        param = self.param_combo.currentData()
        start = self.start_spin.value()
        end = self.end_spin.value()
        step = self.step_spin.value()
        dur = self.dur_spin.value()
        cd = self.cd_spin.value()
        
        self.start_sweep_signal.emit(param, start, end, step, dur, cd)
