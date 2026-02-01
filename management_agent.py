"""
Management Agent for CrowdSurfer Edge Devices

Handles device registration, configuration sync, and remote command processing.
"""

import requests
import logging
import time
import hmac
import hashlib
import json
import subprocess
from typing import Optional, Dict, Any
from datetime import datetime
from config import Config, get_config
from telemetry_queue import QueueManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ManagementAgent:
    """Manages device registration, configuration, and commands"""
    
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'CrowdSurfer-Edge/1.0'
        })
    
    def register_device(self) -> bool:
        """
        Register device with backend.
        
        Returns:
            True if registration successful, False otherwise
        """
        try:
            serial_number = self.config.get_serial_number()
            firmware_version = self._get_firmware_version()
            
            logger.info(f"Registering device: {serial_number}")
            
            url = f"{self.config.backend_url}/api/v1/devices/register"
            payload = {
                'serial_number': serial_number,
                'firmware_version': firmware_version
            }
            
            response = self.session.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Save device configuration
                self.config.device_id = data['device_id']
                self.config.device_serial = serial_number
                self.config.device_token = data['device_token']
                self.config.backend_url = data.get('backend_url', self.config.backend_url)
                self.config.heartbeat_interval = data.get('heartbeat_interval_seconds', 60)
                self.config.save_device_config()
                
                logger.info(f"Device registered successfully: ID={data['device_id']}")
                return True
            else:
                logger.error(f"Registration failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False
    
    def fetch_configuration(self) -> Optional[Dict[str, Any]]:
        """
        Fetch event configuration from backend.
        
        Returns:
            Configuration dict if successful, None otherwise
        """
        if not self.config.is_registered():
            logger.warning("Device not registered, cannot fetch configuration")
            return None
        
        try:
            url = f"{self.config.backend_url}/api/v1/devices/config"
            
            # For GET request, pass device_token as query parameter
            # Backend doesn't require signature for config endpoint
            params = {
                'device_token': self.config.device_token
            }
            
            response = self.session.get(
                url,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('configuration'):
                    config = data['configuration']
                    version = config.get('config_version', 1)
                    
                    logger.info(f"Fetched configuration version: {version}")
                    return config
                else:
                    logger.info("No configuration available (device not assigned)")
                    return None
            elif response.status_code == 401:
                logger.error("Authentication failed - token may be invalid")
                return None
            else:
                logger.error(f"Failed to fetch configuration: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching configuration: {e}")
            return None
    
    def cache_configuration(self, config: Dict[str, Any]) -> bool:
        """
        Cache configuration locally.
        
        Args:
            config: Configuration data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            version = config.get('config_version', 1)
            
            # Check if this is a new version
            if self.config.config_version and version <= self.config.config_version:
                logger.debug(f"Configuration version {version} already cached")
                return True
            
            # Save to cache
            self.config.save_event_config(config, version)
            
            logger.info(f"Cached configuration version: {version}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cache configuration: {e}")
            return False
    
    def process_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process remote command from backend.
        
        Args:
            command: Command data with type and parameters
            
        Returns:
            Command result with status and response
        """
        command_type = command.get('command_type')
        command_params = command.get('command_params', {})
        
        logger.info(f"Processing command: {command_type}")
        
        try:
            if command_type == 'config_refresh':
                return self._handle_config_refresh()
            elif command_type == 'restart':
                return self._handle_restart()
            elif command_type == 'wipe':
                return self._handle_wipe()
            elif command_type == 'update_firmware':
                return self._handle_firmware_update(command_params)
            else:
                logger.warning(f"Unknown command type: {command_type}")
                return {
                    'status': 'error',
                    'error': f"Unknown command type: {command_type}"
                }
        except Exception as e:
            logger.error(f"Command processing error: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def _handle_config_refresh(self) -> Dict[str, Any]:
        """Handle config refresh command."""
        config = self.fetch_configuration()
        
        if config:
            self.cache_configuration(config)
            return {
                'status': 'completed',
                'response': f"Configuration refreshed: version {config.get('config_version')}"
            }
        else:
            return {
                'status': 'completed',
                'response': "No configuration available"
            }
    
    def _handle_restart(self) -> Dict[str, Any]:
        """Handle restart command."""
        logger.warning("Restart command received - restarting services")
        
        try:
            import subprocess
            
            # Restart systemd services
            subprocess.run(['systemctl', 'restart', 'crowdsurfer-management'], check=True)
            subprocess.run(['systemctl', 'restart', 'crowdsurfer-telemetry'], check=True)
            subprocess.run(['systemctl', 'restart', 'crowdsurfer-portal'], check=True)
            
            return {
                'status': 'completed',
                'response': 'Services restarted successfully'
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': f"Restart failed: {str(e)}"
            }
    
    def _handle_wipe(self) -> Dict[str, Any]:
        """Handle wipe command (token revocation)."""
        logger.warning("Wipe command received - clearing device data")
        
        try:
            # Wipe device data
            self.config.wipe_device_data()
            
            return {
                'status': 'completed',
                'response': 'Device data wiped successfully'
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': f"Wipe failed: {str(e)}"
            }
    
    def _handle_firmware_update(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle firmware update command."""
        firmware_url = params.get('firmware_url')
        
        if not firmware_url:
            return {
                'status': 'error',
                'error': 'No firmware URL provided'
            }
        
        logger.info(f"Firmware update requested: {firmware_url}")
        
        # TODO: Implement firmware update logic
        # This would download the firmware, verify signature, and apply update
        
        return {
            'status': 'error',
            'error': 'Firmware update not yet implemented'
        }
    
    def apply_ssid_configuration(self, wifi_ssid: str) -> bool:
        """
        Apply SSID configuration to hostapd.
        
        Args:
            wifi_ssid: The new SSID to configure
            
        Returns:
            True if successful, False otherwise
        """
        hostapd_conf_path = '/etc/hostapd/hostapd.conf'
        previous_ssid = None
        original_lines = None
        
        try:
            logger.info(f"Applying SSID configuration: {wifi_ssid}")
            
            # Read current hostapd.conf
            try:
                with open(hostapd_conf_path, 'r') as f:
                    original_lines = f.readlines()
            except FileNotFoundError:
                logger.error(f"hostapd.conf not found at {hostapd_conf_path}")
                self._report_configuration_error('file_not_found', f"hostapd.conf not found at {hostapd_conf_path}")
                return False
            except PermissionError:
                logger.error(f"Permission denied reading {hostapd_conf_path}")
                self._report_configuration_error('permission_denied', f"Permission denied reading {hostapd_conf_path}")
                return False
            
            # Find and replace SSID line, save previous SSID
            ssid_found = False
            new_lines = []
            for line in original_lines:
                if line.strip().startswith('ssid='):
                    # Extract previous SSID
                    previous_ssid = line.strip().split('=', 1)[1] if '=' in line else None
                    new_lines.append(f'ssid={wifi_ssid}\n')
                    ssid_found = True
                    logger.info(f"Replaced SSID line: {line.strip()} -> ssid={wifi_ssid}")
                else:
                    new_lines.append(line)
            
            if not ssid_found:
                logger.error("No ssid= line found in hostapd.conf")
                self._report_configuration_error('ssid_line_not_found', "No ssid= line found in hostapd.conf")
                return False
            
            # Write updated configuration
            try:
                with open(hostapd_conf_path, 'w') as f:
                    f.writelines(new_lines)
                logger.info(f"Updated {hostapd_conf_path}")
            except PermissionError:
                logger.error(f"Permission denied writing {hostapd_conf_path}")
                self._report_configuration_error('permission_denied', f"Permission denied writing {hostapd_conf_path}")
                return False
            
            # Restart hostapd service
            try:
                logger.info("Restarting hostapd service...")
                result = subprocess.run(
                    ['systemctl', 'restart', 'hostapd'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    logger.info("hostapd service restarted successfully")
                    return True
                else:
                    logger.error(f"Failed to restart hostapd: {result.stderr}")
                    self._report_configuration_error('systemctl_restart_failed', f"Failed to restart hostapd: {result.stderr}")
                    
                    # Rollback to previous configuration
                    if original_lines:
                        logger.warning(f"Rolling back to previous SSID: {previous_ssid}")
                        try:
                            with open(hostapd_conf_path, 'w') as f:
                                f.writelines(original_lines)
                            logger.info("Rollback successful - restored previous configuration")
                        except Exception as rollback_error:
                            logger.error(f"Rollback failed: {rollback_error}")
                    
                    return False
                    
            except subprocess.TimeoutExpired:
                logger.error("Timeout restarting hostapd service")
                self._report_configuration_error('systemctl_timeout', "Timeout restarting hostapd service")
                
                # Rollback to previous configuration
                if original_lines:
                    logger.warning(f"Rolling back to previous SSID: {previous_ssid}")
                    try:
                        with open(hostapd_conf_path, 'w') as f:
                            f.writelines(original_lines)
                        logger.info("Rollback successful - restored previous configuration")
                    except Exception as rollback_error:
                        logger.error(f"Rollback failed: {rollback_error}")
                
                return False
            except Exception as e:
                logger.error(f"Error restarting hostapd: {e}")
                self._report_configuration_error('systemctl_error', f"Error restarting hostapd: {str(e)}")
                
                # Rollback to previous configuration
                if original_lines:
                    logger.warning(f"Rolling back to previous SSID: {previous_ssid}")
                    try:
                        with open(hostapd_conf_path, 'w') as f:
                            f.writelines(original_lines)
                        logger.info("Rollback successful - restored previous configuration")
                    except Exception as rollback_error:
                        logger.error(f"Rollback failed: {rollback_error}")
                
                return False
                
        except Exception as e:
            logger.error(f"Error applying SSID configuration: {e}")
            self._report_configuration_error('unexpected_error', f"Error applying SSID configuration: {str(e)}")
            return False
    
    def _report_configuration_error(self, error_type: str, error_message: str) -> None:
        """
        Report configuration error for telemetry.
        
        Args:
            error_type: Type of error (e.g., 'file_not_found', 'permission_denied')
            error_message: Detailed error message
        """
        logger.error(f"Configuration error [{error_type}]: {error_message}")
        
        # Store error details for potential telemetry reporting
        # In a full implementation, this would queue the error for upload
        # via the telemetry agent or store in a local error log
        error_data = {
            'error_type': error_type,
            'error_message': error_message,
            'timestamp': self._get_timestamp(),
            'component': 'ssid_configuration'
        }
        
        # TODO: Queue error for telemetry upload
        # For now, just log it
        logger.info(f"Error queued for telemetry: {error_data}")
    
    def _sign_request(self, payload: Dict[str, Any]) -> str:
        """
        Sign request with HMAC-SHA256.
        
        Args:
            payload: Request payload
            
        Returns:
            Hex-encoded HMAC signature
        """
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
    
    def send_heartbeat(self) -> Optional[Dict[str, Any]]:
        """
        Send heartbeat to backend.
        Supports automatic token provisioning per Requirement 9:
        - If device has no token, sends initial heartbeat with serial number only
        - Backend responds with token, which is saved locally
        - Subsequent heartbeats use token with HMAC signature
        
        Returns:
            Heartbeat response or None if failed
        """
        try:
            timestamp = self._get_timestamp()
            url = f"{self.config.backend_url}/api/v1/devices/heartbeat"
            
            # Check if device has a token
            has_token = self.config.device_token is not None and self.config.device_token != ""
            
            if not has_token:
                # Initial heartbeat without token (automatic provisioning)
                logger.info("Sending initial heartbeat (no token)")
                
                payload = {
                    'serial_number': self.config.get_serial_number(),
                    'firmware_version': self._get_firmware_version(),
                    'telemetry': {
                        'cpu_usage': 0.0,
                        'memory_usage': 0.0,
                        'disk_usage': 0.0,
                        'wifi_client_count': 0,
                        'uptime_seconds': 0
                    },
                    'timestamp': timestamp
                }
                
                # No signature for initial heartbeat
                request_data = payload
            else:
                # Authenticated heartbeat with token and signature
                logger.debug("Sending authenticated heartbeat")
                
                payload = {
                    'device_token': self.config.device_token,
                    'telemetry': {
                        'cpu_usage': 0.0,
                        'memory_usage': 0.0,
                        'disk_usage': 0.0,
                        'wifi_client_count': 0,
                        'uptime_seconds': 0
                    },
                    'timestamp': timestamp
                }
                
                # Sign the request
                signature = self._sign_request(payload)
                
                # Add signature to request body
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
                
                # Check if backend issued a token (initial heartbeat response)
                if 'device_token' in data and not has_token:
                    token = data['device_token']
                    logger.info(f"Received token from backend: {token}")
                    
                    # Save token to config
                    self.config.device_token = token
                    self.config.save_device_config()
                    logger.info("Token saved to device_config.json")
                
                # Check if backend delivered a new token (re-authorization, Requirement 10.2, 10.3)
                elif 'device_token' in data and has_token:
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
                
                logger.info("Heartbeat sent successfully")
                
                # Check for token revocation
                if data.get('status') == 'token_revoked':
                    logger.error(f"Token revoked: {data.get('revocation_reason')}")
                    self.config.wipe_device_data()
                    return None
                
                # Check for SSID configuration changes
                if 'configuration' in data and data['configuration']:
                    config = data['configuration']
                    new_ssid = config.get('wifi_ssid')
                    current_ssid = self.config.wifi_ssid
                    
                    # Graceful degradation: if wifi_ssid is missing, log warning but continue
                    if new_ssid is None:
                        logger.warning("wifi_ssid missing from heartbeat configuration - retaining current configuration")
                    elif new_ssid != current_ssid:
                        # SSID has changed
                        logger.info(f"SSID change detected: {current_ssid} -> {new_ssid}")
                        
                        # Apply new SSID configuration
                        if self.apply_ssid_configuration(new_ssid):
                            # Save to config on success
                            self.config.wifi_ssid = new_ssid
                            self.config.save_device_config()
                            logger.info(f"SSID configuration updated and saved: {new_ssid}")
                        else:
                            logger.error(f"Failed to apply SSID configuration: {new_ssid}")
                    else:
                        # SSID unchanged
                        logger.debug(f"SSID unchanged: {current_ssid}")
                else:
                    # No configuration in heartbeat response
                    logger.debug("No configuration in heartbeat response")
                
                # Process any pending commands
                commands = data.get('commands', [])
                for command in commands:
                    result = self.process_command(command)
                    logger.info(f"Command result: {result}")
                
                return data
            elif response.status_code == 401:
                logger.error("Authentication failed - token may be invalid")
                return None
            else:
                logger.error(f"Heartbeat failed: {response.status_code}")
                try:
                    error_detail = response.json()
                    logger.error(f"Error details: {error_detail}")
                except:
                    logger.error(f"Response body: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")
            return None
    
    def _get_firmware_version(self) -> str:
        """Get firmware version."""
        # TODO: Read from version file
        return "1.0.0"
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.utcnow().isoformat() + 'Z'


def main():
    """Main entry point for management agent."""
    logger.info("CrowdSurfer Management Agent starting...")
    
    # Load configuration
    config = get_config()
    agent = ManagementAgent(config)
    
    # Check if device is registered (has token)
    if config.device_token:
        logger.info(f"Device already registered: {config.device_serial}")
        logger.info(f"Token: {config.device_token[:20]}...")
    else:
        logger.info(f"Device not yet provisioned: {config.get_serial_number()}")
        logger.info("Will request token on first heartbeat (automatic provisioning)")
    
    # Fetch initial configuration if device has token
    if config.device_token:
        logger.info("Fetching initial configuration...")
        config_data = agent.fetch_configuration()
        if config_data:
            agent.cache_configuration(config_data)
    
    logger.info("Management agent initialized successfully")
    
    # Main heartbeat loop
    heartbeat_interval = 60  # seconds
    logger.info(f"Starting heartbeat loop (interval: {heartbeat_interval}s)")
    
    try:
        while True:
            try:
                # Send heartbeat
                agent.send_heartbeat()
                
                # Check for configuration updates periodically (every 5 minutes)
                if int(time.time()) % 300 == 0:
                    config_data = agent.fetch_configuration()
                    if config_data:
                        agent.cache_configuration(config_data)
                
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
            
            # Sleep until next heartbeat
            time.sleep(heartbeat_interval)
            
    except KeyboardInterrupt:
        logger.info("Management agent stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Fatal error in management agent: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
