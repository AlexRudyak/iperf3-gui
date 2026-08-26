from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QPushButton, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt

class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Results to CSV")
        self.setFixedSize(300, 300)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        label = QLabel("Select data points to include in export:")
        layout.addWidget(label)
        
        self.checkboxes = {}
        options = [
            'Parameter',
            'Value',
            'Avg Bandwidth (Mbps)',
            'Peak Bandwidth (Mbps)',
            'Total Retransmits',
            'Total Loss'
        ]
        
        for opt in options:
            cb = QCheckBox(opt)
            cb.setChecked(True)
            layout.addWidget(cb)
            self.checkboxes[opt] = cb
            
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        export_btn = QPushButton("Export")
        export_btn.setObjectName("start_btn")
        export_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(export_btn)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
    def get_selected_columns(self):
        return [opt for opt, cb in self.checkboxes.items() if cb.isChecked()]
