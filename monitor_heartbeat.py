#!/usr/bin/env python3
"""
CrowdSurfer Edge Device - Heartbeat Monitor

Real-time monitoring tool for device heartbeats, commands, and backend communication.
Shows live updates of heartbeat status, command execution, and detailed logs.

Usage:
    python3 monitor_heartbeat.py
    
    Or install as system command:
    sudo cp monitor_heartbeat.py /usr/local/bin/crowdsurfer-monitor
    sudo chmod +x /usr/local/bin/crowdsurfer-monitor
    crowdsurfer-monitor
"""

import os
import sys
import time
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import curses
from pathlib import Path

# Configuration
LOG_DIR = "/var/log/crowdsurfer"
CACHE_DIR = "/var/cache/crowdsurfer"
CONFIG_DIR = "/etc/crowdsurfer"
QUEUE_DB = f"{CACHE_DIR}/queue.db"

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class HeartbeatMonitor:
    """Monitor heartbeat status and command execution"""
    
    def __init__(self):
        self.last_update = None
        self.heartbeat_history = []
        self.command_history = []
        self.max_history = 50
    
    def get_device_config(self) -> Dict[str, Any]:
        """Load device configuration"""
        config_file = f"{CONFIG_DIR}/device.conf"
        
        if not os.path.exists(config_file):
            return {
                'registered': False,
                'device_serial': 'NOT_REGISTERED',
                'backend_url': os.getenv('CROWDSURFER_BACKEND_URL', 'https://crowdsurfer.politiquera.com'),
                'heartbeat_interval': 60
            }
        
        try:
            with open(config_file, 'r') as f:
                data = json.load(f)
                return {
                    'registered': True,
                    'device_serial': data.get('device_serial', 'UNKNOWN'),
                    'device_id': data.get('device_id'),
                    'backend_url': data.get('backend_url', 'https://crowdsurfer.politiquera.com'),
                    'heartbeat_interval': data.get('heartbeat_interval', 60)
                }
        except Exception as e:
            return {
                'registered': False,
                'error': str(e)
            }
    
    def parse_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a log line and extract heartbeat/command information"""
        try:
            # Log format: 2026-01-28 12:34:56,789 - telemetry_agent - INFO - Message
            parts = line.split(' - ', 3)
            if len(parts) < 4:
                return None
            
            timestamp_str, module, level, message = parts
            timestamp = datetime.strptime(timestamp_str.strip(), '%Y-%m-%d %H:%M:%S,%f')
            
            return {
                'timestamp': timestamp,
                'module': module.strip(),
                'level': level.strip(),
                'message': message.strip()
            }
        except Exception:
            return None
    
    def get_recent_heartbeats(self, minutes: int = 10) -> List[Dict[str, Any]]:
        """Get recent heartbeat events from logs"""
        heartbeats = []
        telemetry_log = f"{LOG_DIR}/telemetry.log"
        
        if not os.path.exists(telemetry_log):
            return heartbeats
        
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        
        try:
            with open(telemetry_log, 'r') as f:
                # Read last 1000 lines
                lines = f.readlines()[-1000:]
                
                for line in lines:
                    parsed = self.parse_log_line(line)
                    if not parsed or parsed['timestamp'] < cutoff_time:
                        continue
                    
                    message = parsed['message']
                    
                    # Detect heartbeat events
                    if 'heartbeat' in message.lower():
                        event_type = 'unknown'
                        status = 'unknown'
                        details = message
                        
                        if 'sending heartbeat' in message.lower():
                            event_type = 'send'
                            status = 'pending'
                        elif 'heartbeat sent successfully' in message.lower():
                            event_type = 'send'
                            status = 'success'
                        elif 'heartbeat failed' in message.lower():
                            event_type = 'send'
                            status = 'failed'
                        elif 'heartbeat error' in message.lower():
                            event_type = 'send'
                            status = 'error'
                        
                        heartbeats.append({
                            'timestamp': parsed['timestamp'],
                            'event_type': event_type,
                            'status': status,
                            'level': parsed['level'],
                            'details': details
                        })
        except Exception as e:
            pass
        
        return heartbeats
    
    def get_recent_commands(self, minutes: int = 60) -> List[Dict[str, Any]]:
        """Get recent command events from logs"""
        commands = []
        management_log = f"{LOG_DIR}/management.log"
        
        if not os.path.exists(management_log):
            return commands
        
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        
        try:
            with open(management_log, 'r') as f:
                lines = f.readlines()[-1000:]
                
                for line in lines:
                    parsed = self.parse_log_line(line)
                    if not parsed or parsed['timestamp'] < cutoff_time:
                        continue
                    
                    message = parsed['message']
                    
                    # Detect command events
                    if 'command' in message.lower() or 'processing' in message.lower():
                        commands.append({
                            'timestamp': parsed['timestamp'],
                            'level': parsed['level'],
                            'message': message
                        })
        except Exception as e:
            pass
        
        return commands
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get telemetry queue status"""
        if not os.path.exists(QUEUE_DB):
            return {
                'exists': False,
                'pending': 0,
                'failed': 0
            }
        
        try:
            conn = sqlite3.connect(QUEUE_DB)
            cursor = conn.cursor()
            
            # Count pending items
            cursor.execute("SELECT COUNT(*) FROM queue WHERE status = 'pending'")
            pending = cursor.fetchone()[0]
            
            # Count failed items
            cursor.execute("SELECT COUNT(*) FROM queue WHERE status = 'failed'")
            failed = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'exists': True,
                'pending': pending,
                'failed': failed
            }
        except Exception as e:
            return {
                'exists': True,
                'error': str(e)
            }
    
    def format_timestamp(self, dt: datetime) -> str:
        """Format timestamp for display"""
        now = datetime.now()
        diff = now - dt
        
        if diff.total_seconds() < 60:
            return f"{int(diff.total_seconds())}s ago"
        elif diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds() / 60)}m ago"
        else:
            return dt.strftime('%H:%M:%S')
    
    def get_status_color(self, status: str) -> str:
        """Get color for status"""
        if status in ['success', 'completed']:
            return Colors.GREEN
        elif status in ['pending', 'queued']:
            return Colors.YELLOW
        elif status in ['failed', 'error']:
            return Colors.RED
        else:
            return Colors.CYAN
    
    def print_header(self):
        """Print monitor header"""
        config = self.get_device_config()
        
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.CYAN}CrowdSurfer Edge Device - Heartbeat Monitor{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.ENDC}\n")
        
        print(f"{Colors.BOLD}Device Information:{Colors.ENDC}")
        print(f"  Serial:            {config.get('device_serial', 'N/A')}")
        print(f"  Device ID:         {config.get('device_id', 'N/A')}")
        print(f"  Backend URL:       {config.get('backend_url', 'N/A')}")
        print(f"  Heartbeat Interval: {config.get('heartbeat_interval', 'N/A')}s")
        print(f"  Registered:        {Colors.GREEN if config.get('registered') else Colors.RED}{'Yes' if config.get('registered') else 'No'}{Colors.ENDC}")
        print()
    
    def print_heartbeat_status(self):
        """Print recent heartbeat status"""
        heartbeats = self.get_recent_heartbeats(minutes=10)
        
        print(f"{Colors.BOLD}Recent Heartbeats (last 10 minutes):{Colors.ENDC}")
        print(f"{Colors.CYAN}{'─'*80}{Colors.ENDC}")
        
        if not heartbeats:
            print(f"  {Colors.YELLOW}No heartbeat activity in last 10 minutes{Colors.ENDC}")
        else:
            # Show last 10 heartbeats
            for hb in heartbeats[-10:]:
                color = self.get_status_color(hb['status'])
                timestamp_str = self.format_timestamp(hb['timestamp'])
                status_str = hb['status'].upper().ljust(8)
                
                print(f"  {color}[{status_str}]{Colors.ENDC} {timestamp_str.ljust(10)} - {hb['details'][:60]}")
        
        print()
    
    def print_command_status(self):
        """Print recent command status"""
        commands = self.get_recent_commands(minutes=60)
        
        print(f"{Colors.BOLD}Recent Commands (last 60 minutes):{Colors.ENDC}")
        print(f"{Colors.CYAN}{'─'*80}{Colors.ENDC}")
        
        if not commands:
            print(f"  {Colors.YELLOW}No command activity in last 60 minutes{Colors.ENDC}")
        else:
            # Show last 10 commands
            for cmd in commands[-10:]:
                level_color = Colors.RED if cmd['level'] == 'ERROR' else Colors.GREEN if cmd['level'] == 'INFO' else Colors.YELLOW
                timestamp_str = self.format_timestamp(cmd['timestamp'])
                
                print(f"  {level_color}[{cmd['level'].ljust(7)}]{Colors.ENDC} {timestamp_str.ljust(10)} - {cmd['message'][:60]}")
        
        print()
    
    def print_queue_status(self):
        """Print telemetry queue status"""
        queue = self.get_queue_status()
        
        print(f"{Colors.BOLD}Telemetry Queue Status:{Colors.ENDC}")
        print(f"{Colors.CYAN}{'─'*80}{Colors.ENDC}")
        
        if not queue.get('exists'):
            print(f"  {Colors.YELLOW}Queue database not found{Colors.ENDC}")
        elif 'error' in queue:
            print(f"  {Colors.RED}Error reading queue: {queue['error']}{Colors.ENDC}")
        else:
            pending_color = Colors.YELLOW if queue['pending'] > 0 else Colors.GREEN
            failed_color = Colors.RED if queue['failed'] > 0 else Colors.GREEN
            
            print(f"  Pending items: {pending_color}{queue['pending']}{Colors.ENDC}")
            print(f"  Failed items:  {failed_color}{queue['failed']}{Colors.ENDC}")
        
        print()
    
    def print_footer(self):
        """Print monitor footer"""
        print(f"{Colors.CYAN}{'─'*80}{Colors.ENDC}")
        print(f"{Colors.BOLD}Press Ctrl+C to exit{Colors.ENDC}")
        print(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    def run(self, refresh_interval: int = 5):
        """Run the monitor with auto-refresh"""
        try:
            while True:
                # Clear screen
                os.system('clear' if os.name == 'posix' else 'cls')
                
                # Print all sections
                self.print_header()
                self.print_heartbeat_status()
                self.print_command_status()
                self.print_queue_status()
                self.print_footer()
                
                # Wait for next refresh
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print(f"\n\n{Colors.GREEN}Monitor stopped{Colors.ENDC}\n")
            sys.exit(0)


def main():
    """Main entry point"""
    # Check if running as root (needed to read logs)
    if os.geteuid() != 0:
        print(f"{Colors.YELLOW}Warning: Running without root privileges. Some logs may not be accessible.{Colors.ENDC}")
        print(f"{Colors.YELLOW}Run with sudo for full access: sudo python3 {sys.argv[0]}{Colors.ENDC}\n")
        time.sleep(2)
    
    monitor = HeartbeatMonitor()
    monitor.run(refresh_interval=5)


if __name__ == "__main__":
    main()
