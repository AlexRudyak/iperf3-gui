import re

class IperfParser:
    def __init__(self):
        # Regex to capture bandwidth (e.g. 950 Mbits/sec) and retransmits (e.g. 0 Retr) or packet loss
        # Sample UDP: [  5]   0.00-1.00   sec   128 KBytes  1.05 Mbits/sec  0.005 ms  0/162 (0%)  
        # Sample TCP: [  5]   0.00-1.00   sec   114 MBytes   954 Mbits/sec    0             187 KBytes
        # Sample bidir: [ TX-C] or [ RX-C]
        self.bw_pattern = re.compile(r'(\d+(?:\.\d+)?)\s+(Kbits/sec|Mbits/sec|Gbits/sec|bits/sec)')
        self.retr_pattern = re.compile(r'\s+(\d+)\s+Retr', re.IGNORECASE)
        self.loss_pattern = re.compile(r'(\d+)/(\d+)\s+\((.*?)\%\)')
        
        # We can look for TX or RX tags in the prefix if --bidir is used,
        # or we might look for 'sender' or 'receiver' strings if available.
        self.prefix_pattern = re.compile(r'\[\s*(.*?)\s*\]')

    def parse_line(self, line):
        """
        Parses a single line of iperf3 stdout.
        Returns a dict with extracted metrics or None if not a telemetry line.
        """
        metrics = {}
        
        # Check if it's a summary line
        if "- - - - - -" in line:
            return None
            
        direction = 'tx' # Default to outbound
        if "RX-C" in line or "RX-S" in line or "receiver" in line:
            direction = 'rx'
        elif "TX-C" in line or "TX-S" in line or "sender" in line:
            direction = 'tx'

        # Bandwidth
        bw_match = self.bw_pattern.search(line)
        if bw_match:
            val = float(bw_match.group(1))
            unit = bw_match.group(2)
            # Normalize to Mbps for the graph
            if "Kbits" in unit:
                val /= 1000
            elif "Gbits" in unit:
                val *= 1000
            elif unit == "bits/sec":
                val /= 1000000
            metrics['bandwidth_mbps'] = val
            metrics['direction'] = direction

        # Retransmits (TCP)
        retr_match = self.retr_pattern.search(line)
        if retr_match:
            metrics['retransmits'] = int(retr_match.group(1))
        
        # Packet Loss (UDP)
        loss_match = self.loss_pattern.search(line)
        if loss_match:
            lost = int(loss_match.group(1))
            total = int(loss_match.group(2))
            percent = float(loss_match.group(3))
            metrics['loss_percent'] = percent
            metrics['loss_count'] = lost
            
        return metrics if metrics else None
