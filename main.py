import sys
import os
from PyQt6.QtWidgets import QApplication
from iperf_gui.ui.main_window import MainWindow
from iperf_gui.utils.paths import resource_path

def main():
    app = QApplication(sys.argv)
    
    # Load stylesheet
    qss_path = resource_path(os.path.join("assets", "style.qss"))
    if os.path.exists(qss_path):
        with open(qss_path, 'r') as f:
            app.setStyleSheet(f.read())
    else:
        print(f"Warning: qss not found at {qss_path}")
        
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
