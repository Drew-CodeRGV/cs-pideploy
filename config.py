"""
Configuration Management for CrowdSurfer Edge Devices

Handles device configuration, token storage, and settings management.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class Config:
    """Device configuration manager"""
    
    # Default configuration paths
    CONFIG_DIR = Path("/etc/crowdsurfer")
    DEVICE_CONF = CONFIG_DIR / "device.conf"
    CACHE_DIR = Path("/var/cache/crowdsurfer")
    QUEUE_DB = CACHE_DIR / "queue.db"
    CONFIG_CACHE = CACHE_DIR / "config.json"
    
    # Default values
    DEFAULT_BACKEND_URL = os.getenv(
        'CROWDSURFER_BACKEND_URL',
        'https://crowdsurfer.politiquera.com'
    )
    DEFAULT_HEARTBEAT_INTERVAL = 60  # seconds
    DEFAULT_ANALYTICS_SYNC_INTERVAL = 120  # seconds
    
    def __init__(self):
        self.device_id: Optional[int] = None
        self.device_serial: Optional[str] = None
        self.device_token: Optional[str] = None
        self.backend_url: str = self.DEFAULT_BACKEND_URL
        self.heartbeat_interval: int = self.DEFAULT_HEARTBEAT_INTERVAL
        self.analytics_sync_interval: int = self.DEFAULT_ANALYTICS_SYNC_INTERVAL
        self.event_config: Optional[Dict[str, Any]] = None
        self.config_version: Optional[int] = None
        self.wifi_ssid: Optional[str] = None
        
    @classmethod
    def load(cls) -> 'Config':
        """
        Load configuration from disk.
        
        Returns:
            Config instance
        """
        config = cls()
        
        # Create directories if they don't exist
        cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cls.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load device configuration
        if cls.DEVICE_CONF.exists():
            try:
                with open(cls.DEVICE_CONF, 'r') as f:
                    data = json.load(f)
                    config.device_id = data.get('device_id')
                    config.device_serial = data.get('device_serial')
                    config.device_token = data.get('device_token')
                    config.backend_url = data.get('backend_url', cls.DEFAULT_BACKEND_URL)
                    config.heartbeat_interval = data.get('heartbeat_interval', cls.DEFAULT_HEARTBEAT_INTERVAL)
                    config.analytics_sync_interval = data.get('analytics_sync_interval', cls.DEFAULT_ANALYTICS_SYNC_INTERVAL)
                    config.wifi_ssid = data.get('wifi_ssid')
                    logger.info(f"Loaded device config: {config.device_serial}")
            except Exception as e:
                logger.error(f"Failed to load device config: {e}")
        
        # Load cached event configuration
        if cls.CONFIG_CACHE.exists():
            try:
                with open(cls.CONFIG_CACHE, 'r') as f:
                    data = json.load(f)
                    config.event_config = data.get('configuration')
                    config.config_version = data.get('version')
                    logger.info(f"Loaded cached config version: {config.config_version}")
            except Exception as e:
                logger.error(f"Failed to load cached config: {e}")
        
        return config
    
    def save_device_config(self) -> None:
        """Save device configuration to disk."""
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            
            data = {
                'device_id': self.device_id,
                'device_serial': self.device_serial,
                'device_token': self.device_token,
                'backend_url': self.backend_url,
                'heartbeat_interval': self.heartbeat_interval,
                'analytics_sync_interval': self.analytics_sync_interval,
                'wifi_ssid': self.wifi_ssid
            }
            
            # Write atomically
            temp_file = self.DEVICE_CONF.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.DEVICE_CONF)
            
            # Set permissions (owner can write, group/others can read)
            # Service runs as 'crowdsurfer' user, so needs read access
            os.chmod(self.DEVICE_CONF, 0o644)
            
            logger.info(f"Saved device config: {self.device_serial}")
        except Exception as e:
            logger.error(f"Failed to save device config: {e}")
            raise
    
    def save_event_config(self, config_data: Dict[str, Any], version: int) -> None:
        """
        Save event configuration to cache.
        
        Args:
            config_data: Event configuration data
            version: Configuration version number
        """
        try:
            self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            
            data = {
                'configuration': config_data,
                'version': version,
                'cached_at': self._get_timestamp()
            }
            
            # Write atomically
            temp_file = self.CONFIG_CACHE.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.CONFIG_CACHE)
            
            self.event_config = config_data
            self.config_version = version
            
            logger.info(f"Saved event config version: {version}")
        except Exception as e:
            logger.error(f"Failed to save event config: {e}")
            raise
    
    def clear_event_config(self) -> None:
        """Clear cached event configuration."""
        try:
            if self.CONFIG_CACHE.exists():
                self.CONFIG_CACHE.unlink()
            self.event_config = None
            self.config_version = None
            logger.info("Cleared event config cache")
        except Exception as e:
            logger.error(f"Failed to clear event config: {e}")
    
    def wipe_device_data(self) -> None:
        """
        Wipe all device data (token revocation response).
        
        This clears the device token and event configuration,
        but preserves the device serial number for re-authorization.
        """
        try:
            # Clear token
            self.device_token = None
            self.device_id = None
            
            # Clear event config
            self.clear_event_config()
            
            # Save updated device config
            self.save_device_config()
            
            logger.warning("Device data wiped (token revoked)")
        except Exception as e:
            logger.error(f"Failed to wipe device data: {e}")
            raise
    
    def is_registered(self) -> bool:
        """Check if device is registered with backend."""
        return self.device_token is not None
    
    def is_assigned(self) -> bool:
        """Check if device is assigned to an event."""
        return self.event_config is not None
    
    def get_serial_number(self) -> str:
        """
        Get device serial number.
        
        If not configured, generates from Raspberry Pi serial number.
        
        Returns:
            Device serial number in format CS-SHAKA-V1-XXX
        """
        if self.device_serial:
            return self.device_serial
        
        # Generate from Raspberry Pi CPU serial
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('Serial'):
                        cpu_serial = line.split(':')[1].strip()
                        # Use last 3 digits of CPU serial
                        suffix = cpu_serial[-3:]
                        self.device_serial = f"CS-SHAKA-V1-{suffix}"
                        return self.device_serial
        except Exception as e:
            logger.error(f"Failed to read CPU serial: {e}")
        
        # Fallback to random
        import random
        suffix = f"{random.randint(0, 999):03d}"
        self.device_serial = f"CS-SHAKA-V1-{suffix}"
        return self.device_serial
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get global config instance."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config
