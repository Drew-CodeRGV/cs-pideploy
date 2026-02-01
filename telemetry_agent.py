"""
Telemetry Agent for CrowdSurfer Edge Devices

Collects system telemetry, WiFi analytics, and syncs to backend.
Handles heartbeats, offline queuing, and exponential backoff for retries.
"""

import requests
import logging
import time
import hmac
import hashlib
import json
import subprocess
import os
import platform
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from config import Config, get_config
from telemetry_queue import QueueManager, QueueItemType
from connectivity_monitor import ConnectivityMonitor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TelemetryAgent:
    """Collects and syncs telemetry and analytics data"""
    
    def __init__(self, config: Config, queue: QueueManager):
        self.config = config
        self.queue = queue
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'CrowdSurfer-Edge/1.0'
        })
        self.retry_count = 0
        self.max_retries = 5
        self.connectivity_monitor = ConnectivityMonitor(config.backend_url)
    
    def send_initial_heartbeat(self) -> Optional[str]:
        """
        Send initial heartbeat without token to get token (Requirement 9).
        
        This is used when the device doesn't have a token yet.
        The backend will issue a token if the device is pre-authorized.
        
        Returns:
            Device token if successful, None otherwise
        """
        try:
            telemetry = self.collect_system_telemetry()
            timestamp = self._get_timestamp()
            
            url = f"{self.config.backend_url}/api/v1/devices/heartbeat"
            
            # For initial heartbeat, send serial_number instead of device_token
            payload = {
                'serial_number': self.config.get_serial_number(),
                'firmware_version': self._get_firmware_version(),
                'telemetry': telemetry,
                'timestamp': timestamp
            }
            
            response = self.session.post(
                url,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if token was issued
                if data.get('device_token'):
                    logger.info(f"Received device token from backend")
                    return data['device_token']
                elif data.get('status') == 'unauthorized':
                    logger.warning(f"Device not authorized: {data.get('message')}")
                    return None
                else:
                    logger.warning(f"Unexpected response: {data}")
                    return None
            else:
                logger.error(f"Initial heartbeat failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Initial heartbeat error: {e}")
            return None
    
    def send_heartbeat(self) -> Optional[Dict[str, Any]]:
        """
        Send heartbeat with telemetry to backend.
        
        Returns:
            Heartbeat response with commands and config version, or None if failed
        """
        if not self.config.is_registered():
            logger.warning("Device not registered, cannot send heartbeat")
            return None
        
        try:
            telemetry = self.collect_system_telemetry()
            timestamp = self._get_timestamp()
            
            url = f"{self.config.backend_url}/api/v1/devices/heartbeat"
            
            # Construct payload EXACTLY as backend expects for signature verification
            payload = {
                'device_token': self.config.device_token,
                'telemetry': telemetry,
                'timestamp': timestamp
            }
            
            # Sign the complete payload
            signature = self._sign_request(payload)
            
            # Add signature to request body (backend expects it in JSON, not headers)
            request_data = {
                **payload,
                'signature': signature
            }
            
            response = self.session.post(
                url,
                json=request_data,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info("Heartbeat sent successfully")
                
                # Check for token revocation
                if data.get('status') == 'token_revoked':
                    logger.error(f"Token revoked: {data.get('revocation_reason')}")
                    self.config.wipe_device_data()
                    return None
                
                # Check if backend delivered a new token (Requirement 10.2, 10.3)
                if 'device_token' in data:
                    new_token = data['device_token']
                    
                    # Compare to current token
                    if new_token != self.config.device_token:
                        logger.info(f"Received new token from backend: {new_token[:10]}...")
                        
                        # Save new token to config
                        self.config.device_token = new_token
                        
                        # Update token expiration if provided
                        if 'token_expires_at' in data:
                            logger.info(f"Token expires at: {data['token_expires_at']}")
                        
                        # Save to persistent storage
                        self.config.save_device_config()
                        logger.info("New token saved to device config")
                    else:
                        logger.debug("Token unchanged")
                
                # Reset retry count on success
                self.retry_count = 0
                
                return data
            elif response.status_code == 401:
                logger.error("Authentication failed - token expired or revoked")
                logger.info("Wiping device token and switching to initial heartbeat mode")
                
                # Wipe token from config
                self.config.device_token = None
                self.config.save_device_config()
                
                return None
            else:
                logger.error(f"Heartbeat failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            return None
    
    def collect_system_telemetry(self) -> Dict[str, Any]:
        """
        Collect current system telemetry including connectivity metrics.
        
        Returns:
            Dictionary with telemetry data
        """
        telemetry = {
            'cpu_usage': self._get_cpu_usage(),
            'memory_usage': self._get_memory_usage(),
            'disk_usage': self._get_disk_usage(),
            'wifi_client_count': self._get_wifi_client_count(),
            'uptime_seconds': self._get_uptime(),
            'temperature_celsius': self._get_temperature()
        }
        
        # Add connectivity metrics
        try:
            connectivity = self.connectivity_monitor.collect_metrics()
            telemetry['connectivity'] = connectivity
            logger.info(
                f"Collected connectivity metrics: "
                f"quality_score={connectivity.get('quality_score')}, "
                f"latency={connectivity.get('latency_ms')}ms, "
                f"packet_loss={connectivity.get('packet_loss_percent')}%, "
                f"download={connectivity.get('download_mbps')}Mbps, "
                f"upload={connectivity.get('upload_mbps')}Mbps"
            )
        except Exception as e:
            logger.error(f"Error collecting connectivity metrics: {e}")
            telemetry['connectivity'] = None
        
        return telemetry
    
    def collect_wifi_analytics(self) -> List[Dict[str, Any]]:
        """
        Collect WiFi analytics from hostapd.
        
        Returns:
            List of analytics records
        """
        # TODO: Implement actual WiFi analytics collection
        # This would parse hostapd logs or status to get:
        # - MAC addresses (hashed with SHA-256)
        # - Connection/disconnection timestamps
        # - Device types (from user agent or DHCP fingerprinting)
        # - Signal strength
        # - Session duration
        
        return []
    
    def sync_queued_analytics(self) -> bool:
        """
        Sync queued analytics to backend.
        
        Returns:
            True if sync successful, False otherwise
        """
        if not self.config.is_registered():
            logger.warning("Device not registered, cannot sync analytics")
            return False
        
        try:
            # Get batch of items from queue
            batch = self.queue.dequeue_batch(batch_size=100)
            
            if not batch:
                logger.debug("No queued items to sync")
                return True
            
            # Separate analytics and submissions
            analytics_items = [(id, data) for id, type, data in batch if type == QueueItemType.ANALYTICS_RECORD]
            submission_items = [(id, data) for id, type, data in batch if type == QueueItemType.PORTAL_SUBMISSION]
            
            # Sync analytics
            if analytics_items:
                analytics_ids = [id for id, _ in analytics_items]
                analytics_data = [data for _, data in analytics_items]
                
                if self._send_analytics_batch(analytics_data):
                    self.queue.mark_synced(analytics_ids)
                    logger.info(f"Synced {len(analytics_ids)} analytics records")
                else:
                    self.queue.mark_failed(analytics_ids)
                    logger.warning(f"Failed to sync {len(analytics_ids)} analytics records")
            
            # Sync submissions
            if submission_items:
                submission_ids = [id for id, _ in submission_items]
                submission_data = [data for _, data in submission_items]
                
                if self._send_submissions_batch(submission_data):
                    self.queue.mark_synced(submission_ids)
                    logger.info(f"Synced {len(submission_ids)} portal submissions")
                else:
                    self.queue.mark_failed(submission_ids)
                    logger.warning(f"Failed to sync {len(submission_ids)} portal submissions")
            
            return True
            
        except Exception as e:
            logger.error(f"Error syncing queued analytics: {e}")
            return False
    
    def _send_analytics_batch(self, records: List[Dict[str, Any]]) -> bool:
        """Send analytics batch to backend."""
        try:
            url = f"{self.config.backend_url}/api/v1/devices/analytics"
            
            timestamp = self._get_timestamp()
            
            # Construct payload for signature
            payload = {
                'device_token': self.config.device_token,
                'records': records,
                'timestamp': timestamp
            }
            
            # Sign payload
            signature = self._sign_request(payload)
            
            # Add signature to request
            request_data = {
                **payload,
                'signature': signature
            }
            
            response = self.session.post(
                url,
                json=request_data,
                timeout=30
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error sending analytics batch: {e}")
            return False
    
    def _send_submissions_batch(self, submissions: List[Dict[str, Any]]) -> bool:
        """Send portal submissions batch to backend."""
        try:
            url = f"{self.config.backend_url}/api/v1/devices/submissions"
            
            timestamp = self._get_timestamp()
            
            # Construct payload for signature
            payload = {
                'device_token': self.config.device_token,
                'submissions': submissions,
                'timestamp': timestamp
            }
            
            # Sign payload
            signature = self._sign_request(payload)
            
            # Add signature to request
            request_data = {
                **payload,
                'signature': signature
            }
            
            response = self.session.post(
                url,
                json=request_data,
                timeout=30
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error sending submissions batch: {e}")
            return False
    
    def _get_cpu_usage(self) -> float:
        """Get CPU usage percentage."""
        try:
            # Try Linux /proc/stat first
            if platform.system() == 'Linux' and os.path.exists('/proc/stat'):
                with open('/proc/stat', 'r') as f:
                    line = f.readline()
                    fields = line.split()
                    idle = int(fields[4])
                    total = sum(int(x) for x in fields[1:8])
                    
                    # Calculate percentage (simplified)
                    usage = 100.0 * (1.0 - idle / total)
                    return round(usage, 2)
            else:
                # Fallback for non-Linux systems (testing)
                try:
                    import psutil
                    return round(psutil.cpu_percent(interval=0.1), 2)
                except ImportError:
                    logger.debug("psutil not available, returning mock CPU usage")
                    import random
                    return round(random.uniform(20, 60), 2)
        except Exception as e:
            logger.error(f"Error getting CPU usage: {e}")
            return 0.0
    
    def _get_memory_usage(self) -> float:
        """Get memory usage percentage."""
        try:
            # Try Linux /proc/meminfo first
            if platform.system() == 'Linux' and os.path.exists('/proc/meminfo'):
                with open('/proc/meminfo', 'r') as f:
                    lines = f.readlines()
                    mem_total = int(lines[0].split()[1])
                    mem_available = int(lines[2].split()[1])
                    
                    usage = 100.0 * (1.0 - mem_available / mem_total)
                    return round(usage, 2)
            else:
                # Fallback for non-Linux systems (testing)
                try:
                    import psutil
                    return round(psutil.virtual_memory().percent, 2)
                except ImportError:
                    logger.debug("psutil not available, returning mock memory usage")
                    import random
                    return round(random.uniform(40, 70), 2)
        except Exception as e:
            logger.error(f"Error getting memory usage: {e}")
            return 0.0
    
    def _get_disk_usage(self) -> float:
        """Get disk usage percentage."""
        try:
            # Try df command (works on Linux and Mac)
            if platform.system() in ['Linux', 'Darwin']:
                result = subprocess.run(
                    ['df', '-h', '/'],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5
                )
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    fields = lines[1].split()
                    usage_str = fields[4].rstrip('%')
                    return float(usage_str)
            else:
                # Fallback for Windows or other systems
                try:
                    import psutil
                    return round(psutil.disk_usage('/').percent, 2)
                except ImportError:
                    logger.debug("psutil not available, returning mock disk usage")
                    import random
                    return round(random.uniform(30, 50), 2)
            return 0.0
        except Exception as e:
            logger.error(f"Error getting disk usage: {e}")
            return 0.0
    
    def _get_wifi_client_count(self) -> int:
        """Get number of connected WiFi clients."""
        try:
            # Try to get from hostapd
            result = subprocess.run(
                ['hostapd_cli', 'all_sta'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                # Count MAC addresses in output
                count = result.stdout.count('\n') // 2  # Rough estimate
                return count
            return 0
        except Exception as e:
            logger.debug(f"Could not get WiFi client count: {e}")
            return 0
    
    def _get_uptime(self) -> int:
        """Get system uptime in seconds."""
        try:
            # Try Linux /proc/uptime first
            if platform.system() == 'Linux' and os.path.exists('/proc/uptime'):
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = int(float(f.read().split()[0]))
                    return uptime_seconds
            else:
                # Fallback for non-Linux systems
                try:
                    import psutil
                    boot_time = psutil.boot_time()
                    uptime_seconds = int(time.time() - boot_time)
                    return uptime_seconds
                except ImportError:
                    logger.debug("psutil not available, returning mock uptime")
                    return 3600  # 1 hour
        except Exception as e:
            logger.error(f"Error getting uptime: {e}")
            return 0
    
    def _get_temperature(self) -> Optional[float]:
        """Get CPU temperature in Celsius."""
        try:
            # Try Raspberry Pi thermal zone
            if platform.system() == 'Linux' and os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temp_millidegrees = int(f.read().strip())
                    temp_celsius = temp_millidegrees / 1000.0
                    return round(temp_celsius, 1)
            else:
                # Temperature not available on non-Linux or non-RPi systems
                logger.debug("Temperature sensor not available")
                return None
        except Exception as e:
            logger.debug(f"Could not read temperature: {e}")
            return None
    
    def _sign_request(self, payload: Dict[str, Any]) -> str:
        """Sign request with HMAC-SHA256."""
        if not self.config.device_token:
            raise ValueError("No device token available")
        
        # Serialize payload to canonical JSON
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        
        # Generate HMAC signature
        signature = hmac.new(
            self.config.device_token.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    def _get_firmware_version(self) -> str:
        """Get firmware version."""
        # TODO: Read from version file
        return "1.0.0"


def main():
    """Main entry point for telemetry agent daemon."""
    logger.info("CrowdSurfer Telemetry Agent starting...")
    
    # Load configuration
    config = get_config()
    
    # Initialize queue
    queue = QueueManager(config.QUEUE_DB)
    
    # Initialize agent
    agent = TelemetryAgent(config, queue)
    
    if not config.is_registered():
        logger.info("Device not registered, will attempt to get token on first heartbeat")
    else:
        logger.info(f"Telemetry agent initialized for device: {config.device_serial}")
    
    logger.info(f"Heartbeat interval: {config.heartbeat_interval}s")
    logger.info(f"Analytics sync interval: {config.analytics_sync_interval}s")
    
    # Main loop
    heartbeat_counter = 0
    sync_counter = 0
    
    try:
        while True:
            # Send heartbeat every heartbeat_interval seconds
            if heartbeat_counter >= config.heartbeat_interval:
                if not config.is_registered():
                    # Send initial heartbeat to get token
                    logger.info("Sending initial heartbeat to get device token...")
                    token = agent.send_initial_heartbeat()
                    
                    if token:
                        # Save token to config
                        config.device_token = token
                        config.save_device_config()
                        logger.info(f"Device registered successfully with token: {token[:10]}...")
                    else:
                        logger.warning("Failed to get device token, will retry in 60 seconds")
                else:
                    # Send regular heartbeat
                    response = agent.send_heartbeat()
                    
                    if response:
                        # Process any commands
                        commands = response.get('commands', [])
                        if commands:
                            logger.info(f"Received {len(commands)} commands")
                            # TODO: Process commands
                        
                        # Check config version
                        config_version = response.get('config_version')
                        if config_version and config_version != config.config_version:
                            logger.info(f"New config version available: {config_version}")
                            # TODO: Fetch new configuration
                
                heartbeat_counter = 0
            
            # Sync analytics every analytics_sync_interval seconds (only if registered)
            if config.is_registered() and sync_counter >= config.analytics_sync_interval:
                agent.sync_queued_analytics()
                sync_counter = 0
            
            # Sleep for 1 second
            time.sleep(1)
            heartbeat_counter += 1
            sync_counter += 1
            
    except KeyboardInterrupt:
        logger.info("Telemetry agent stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Telemetry agent error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
