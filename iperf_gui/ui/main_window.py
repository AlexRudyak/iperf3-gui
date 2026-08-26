import csv
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGroupBox, QLabel, QLineEdit, QPushButton, 
                             QTextEdit, QTabWidget, QComboBox, QCheckBox, 
                             QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QIcon, QRegularExpressionValidator, QIntValidator
from iperf_gui.core.engine import IPerfWorker
from iperf_gui.core.fuzzer import FuzzEngine
from iperf_gui.ui.dashboard import TelemetryDashboard
from iperf_gui.ui.fuzzer_tab import FuzzerTab
from iperf_gui.ui.dialogs import ExportDialog
from iperf_gui.utils.paths import resource_path
import os

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("iperf3 Advanced GUI & Fuzzer")
        self.resize(1000, 700)
        
        icon_path = resource_path(os.path.join("assets", "app_icon.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.worker = None
        self.fuzz_engine = FuzzEngine()
        self.fuzz_engine.log_message.connect(self.log_message)
        self.fuzz_engine.telemetry_data.connect(self.update_telemetry)
        self.fuzz_engine.sweep_finished.connect(self.on_fuzz_finished)
        
        self.init_ui()
        
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        
        # Left Panel (Controls)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0,0,0,0)
        
        # Tabs for Normal / Fuzzer
        self.tabs = QTabWidget()
        
        # Normal Mode Tab
        normal_tab = QWidget()
        normal_layout = QVBoxLayout(normal_tab)
        
        # Connection Group
        conn_group = QGroupBox("Connection Parameters")
        conn_layout = QVBoxLayout(conn_group)
        
        # Target IP
        h_ip = QHBoxLayout()
        h_ip.addWidget(QLabel("Target IP/Host:"))
        self.ip_input = QLineEdit("127.0.0.1")
        h_ip.addWidget(self.ip_input)
        conn_layout.addLayout(h_ip)
        
        # Port
        h_port = QHBoxLayout()
        h_port.addWidget(QLabel("Port (-p):"))
        self.port_input = QLineEdit("5201")
        self.port_input.setValidator(QIntValidator(1, 65535))
        h_port.addWidget(self.port_input)
        conn_layout.addLayout(h_port)
        
        # Mode
        h_mode = QHBoxLayout()
        h_mode.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Client (-c)", "Server (-s)"])
        h_mode.addWidget(self.mode_combo)
        conn_layout.addLayout(h_mode)
        
        normal_layout.addWidget(conn_group)
        
        # L3/L4 Settings Group
        settings_group = QGroupBox("L3/L4 Stress & TCP Options")
        settings_layout = QVBoxLayout(settings_group)
        
        # Protocol
        h_proto = QHBoxLayout()
        h_proto.addWidget(QLabel("Protocol:"))
        self.proto_combo = QComboBox()
        self.proto_combo.addItems(["TCP (Default)", "UDP (-u)", "SCTP (--sctp)"])
        h_proto.addWidget(self.proto_combo)
        settings_layout.addLayout(h_proto)
        
        # Data Rate
        h_rate = QHBoxLayout()
        h_rate.addWidget(QLabel("Target Rate (-b):"))
        self.rate_input = QLineEdit()
        self.rate_unit = QComboBox()
        self.rate_unit.addItems(["M", "K", "G"])
        h_rate.addWidget(self.rate_input)
        h_rate.addWidget(self.rate_unit)
        settings_layout.addLayout(h_rate)
        
        # Parallel Streams
        h_parallel = QHBoxLayout()
        h_parallel.addWidget(QLabel("Parallel Streams (-P):"))
        self.parallel_input = QLineEdit("1")
        self.parallel_input.setValidator(QIntValidator(1, 128))
        h_parallel.addWidget(self.parallel_input)
        settings_layout.addLayout(h_parallel)
        
        # Extra Args (Workaround for unsupported TCP options)
        h_extra = QHBoxLayout()
        h_extra.addWidget(QLabel("Extra Custom Args:"))
        self.extra_input = QLineEdit()
        h_extra.addWidget(self.extra_input)
        settings_layout.addLayout(h_extra)
        
        # Checkboxes
        self.reverse_cb = QCheckBox("Reverse (-R)")
        self.bidir_cb = QCheckBox("Bidir (--bidir)")
        self.zerocopy_cb = QCheckBox("Zero-Copy (-Z)")
        
        h_checks = QHBoxLayout()
        h_checks.addWidget(self.reverse_cb)
        h_checks.addWidget(self.bidir_cb)
        h_checks.addWidget(self.zerocopy_cb)
        settings_layout.addLayout(h_checks)
        
        normal_layout.addWidget(settings_group)
        
        # Execution Controls
        h_exec = QHBoxLayout()
        self.start_btn = QPushButton("Start Test")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.clicked.connect(self.start_test)
        
        self.stop_btn = QPushButton("Stop / Kill")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.clicked.connect(self.stop_test)
        self.stop_btn.setEnabled(False)
        
        h_exec.addWidget(self.start_btn)
        h_exec.addWidget(self.stop_btn)
        normal_layout.addLayout(h_exec)
        normal_layout.addStretch()
        
        self.tabs.addTab(normal_tab, "Standard Test")
        
        # Fuzzer Tab
        self.fuzzer_tab = FuzzerTab()
        self.fuzzer_tab.start_sweep_signal.connect(self.start_fuzz_sweep)
        self.tabs.addTab(self.fuzzer_tab, "Fuzz / Sweep")
        
        left_layout.addWidget(self.tabs)
        left_panel.setMinimumWidth(380)
        
        # Right Panel (Graphs & Console)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0,0,0,0)
        
        self.dashboard = TelemetryDashboard()
        right_layout.addWidget(self.dashboard, stretch=2)
        
        # Export / Clear Buttons
        h_graph_ctrl = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Graphs")
        self.clear_btn.clicked.connect(self.dashboard.reset_data)
        
        self.export_btn = QPushButton("Export Sweep Results (CSV)")
        self.export_btn.clicked.connect(self.export_results)
        self.export_btn.setEnabled(False) # Enabled after fuzzing
        
        h_graph_ctrl.addWidget(self.clear_btn)
        h_graph_ctrl.addWidget(self.export_btn)
        h_graph_ctrl.addStretch()
        right_layout.addLayout(h_graph_ctrl)
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        right_layout.addWidget(self.console, stretch=1)
        
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        
    def build_base_args(self):
        args = []
        if self.mode_combo.currentIndex() == 0:
            args.extend(["-c", self.ip_input.text()])
        else:
            args.append("-s")
            
        args.extend(["-p", self.port_input.text()])
        
        if self.proto_combo.currentIndex() == 1:
            args.append("-u")
        elif self.proto_combo.currentIndex() == 2:
            args.append("--sctp")
            
        if self.rate_input.text():
            args.extend(["-b", f"{self.rate_input.text()}{self.rate_unit.currentText()}"])
            
        if int(self.parallel_input.text()) > 1:
            args.extend(["-P", self.parallel_input.text()])
            
        if self.reverse_cb.isChecked():
            args.append("-R")
        if self.bidir_cb.isChecked():
            args.append("--bidir")
        if self.zerocopy_cb.isChecked():
            args.append("-Z")
            
        if self.extra_input.text():
            args.extend(self.extra_input.text().split())
            
        return args

    def start_test(self):
        if not self.ip_input.text():
            QMessageBox.warning(self, "Validation Error", "Target IP is required.")
            return
            
        self.dashboard.reset_data()
        self.console.clear()
        
        args = self.build_base_args()
        
        self.worker = IPerfWorker(args)
        self.worker.log_message.connect(self.log_message)
        self.worker.telemetry_data.connect(self.update_telemetry)
        self.worker.finished.connect(self.test_finished)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start()
        
    def stop_test(self):
        if self.worker:
            self.worker.stop()
        if self.fuzz_engine.is_running:
            self.fuzz_engine.stop()

    def test_finished(self, exit_code):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log_message(f"Test finished with exit code {exit_code}")
        
    def start_fuzz_sweep(self, param, start, end, step, dur, cd):
        self.console.clear()
        self.dashboard.reset_data()
        base_args = self.build_base_args()
        self.fuzz_engine.start_sweep(base_args, param, start, end, step, dur, cd)
        
        self.stop_btn.setEnabled(True)
        self.tabs.setTabEnabled(0, False)
        
    def on_fuzz_finished(self):
        self.stop_btn.setEnabled(False)
        self.tabs.setTabEnabled(0, True)
        if self.fuzz_engine.results:
            self.export_btn.setEnabled(True)
            QMessageBox.information(self, "Fuzzing Complete", "Sweep finished. You can now export the results.")

    def update_telemetry(self, metrics):
        self.dashboard.add_data(metrics)

    def log_message(self, msg):
        self.console.append(msg)
        
    def export_results(self):
        if not self.fuzz_engine.results:
            return
            
        dialog = ExportDialog(self)
        if dialog.exec():
            cols = dialog.get_selected_columns()
            if not cols:
                QMessageBox.warning(self, "Export Error", "No columns selected.")
                return
                
            path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
            if path:
                try:
                    with open(path, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
                        writer.writeheader()
                        for row in self.fuzz_engine.results:
                            writer.writerow(row)
                    QMessageBox.information(self, "Success", f"Results exported to {path}")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to export: {str(e)}")
