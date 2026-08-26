from PyQt6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg
from collections import deque
import numpy as np

class TelemetryDashboard(QWidget):
    def __init__(self, max_len=120):
        super().__init__()
        self.max_len = max_len
        self.init_ui()
        self.reset_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Set pyqtgraph global config for sleek look
        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', '#cccccc')
        pg.setConfigOptions(antialias=True)
        
        # Bandwidth Plot (Outbound / TX)
        self.bw_tx_plot = pg.PlotWidget(title="Throughput (Outbound / TX)")
        self.bw_tx_plot.setLabel('left', 'Mbps')
        self.bw_tx_plot.setLabel('bottom', 'Time', 's')
        self.bw_tx_plot.showGrid(x=True, y=True, alpha=0.3)
        self.bw_tx_curve = self.bw_tx_plot.plot(pen=pg.mkPen(color='#00d2ff', width=2))
        
        # Bandwidth Plot (Inbound / RX)
        self.bw_rx_plot = pg.PlotWidget(title="Throughput (Inbound / RX)")
        self.bw_rx_plot.setLabel('left', 'Mbps')
        self.bw_rx_plot.setLabel('bottom', 'Time', 's')
        self.bw_rx_plot.showGrid(x=True, y=True, alpha=0.3)
        self.bw_rx_curve = self.bw_rx_plot.plot(pen=pg.mkPen(color='#00ff88', width=2))
        
        # Reliability Plot (Retransmits / Loss)
        self.rel_plot = pg.PlotWidget(title="Reliability (Retransmits / Loss %)")
        self.rel_plot.setLabel('left', 'Count / %')
        self.rel_plot.setLabel('bottom', 'Time', 's')
        self.rel_plot.showGrid(x=True, y=True, alpha=0.3)
        self.rel_curve = self.rel_plot.plot(pen=pg.mkPen(color='#d13438', width=2))
        
        layout.addWidget(self.bw_tx_plot)
        layout.addWidget(self.bw_rx_plot)
        layout.addWidget(self.rel_plot)
        
    def reset_data(self):
        self.times_tx = deque(maxlen=self.max_len)
        self.times_rx = deque(maxlen=self.max_len)
        self.bws_tx = deque(maxlen=self.max_len)
        self.bws_rx = deque(maxlen=self.max_len)
        self.times_rel = deque(maxlen=self.max_len)
        self.rels = deque(maxlen=self.max_len)
        self.current_time_tx = 0.0
        self.current_time_rx = 0.0
        self.current_time_rel = 0.0
        self.update_plots()
        
    def add_data(self, metrics):
        # Bandwidth
        direction = metrics.get('direction', 'tx')
        if 'bandwidth_mbps' in metrics:
            if direction == 'tx':
                self.times_tx.append(self.current_time_tx)
                self.current_time_tx += 0.5
                self.bws_tx.append(metrics['bandwidth_mbps'])
            else:
                self.times_rx.append(self.current_time_rx)
                self.current_time_rx += 0.5
                self.bws_rx.append(metrics['bandwidth_mbps'])
        
        # Reliability (Retransmits for TCP, Loss % for UDP)
        rel_val = None
        if 'retransmits' in metrics:
            rel_val = metrics['retransmits']
        elif 'loss_percent' in metrics:
            rel_val = metrics['loss_percent']
            
        if rel_val is not None:
            self.times_rel.append(self.current_time_rel)
            self.current_time_rel += 0.5
            self.rels.append(rel_val)
            
        self.update_plots()
        
    def update_plots(self):
        if self.times_tx:
            self.bw_tx_curve.setData(np.array(self.times_tx), np.array(self.bws_tx))
        else:
            self.bw_tx_curve.setData([], [])
            
        if self.times_rx:
            self.bw_rx_curve.setData(np.array(self.times_rx), np.array(self.bws_rx))
        else:
            self.bw_rx_curve.setData([], [])
            
        if self.times_rel:
            self.rel_curve.setData(np.array(self.times_rel), np.array(self.rels))
        else:
            self.rel_curve.setData([], [])
