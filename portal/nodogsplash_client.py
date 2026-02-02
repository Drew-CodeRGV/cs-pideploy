"""
Nodogsplash captive portal integration client.

This module provides integration with the nodogsplash captive portal daemon
to manage device whitelisting and network access control.
"""

import subprocess
import logging
import requests
from typing import Optional
import time

logger = logging.getLogger(__name__)


class NodogsplashClient:
    """Integration with nodogsplash captive portal daemon."""
    
    def __init__(self, auth_url: str = "http://localhost:2050/nodogsplash_auth/",
                 token: str = "crowdsurfer"):
        """
        Initialize nodogsplash client.
        
        Args:
            auth_url: Base URL for nodogsplash auth API
            token: Authentication token for nodogsplash
        """
        self.auth_url = auth_url
        self.token = token
    
    def whitelist_device(self, mac_address: str, duration_seconds: int = 86400) -> bool:
        """
        Grant network access to device by MAC address.
        
        This calls the nodogsplash authentication API to whitelist a device,
        allowing it to access the internet without further captive portal prompts.
        
        Args:
            mac_address: Device MAC address (format: AA:BB:CC:DD:EE:FF)
            duration_seconds: How long to grant access (default 24 hours)
        
        Returns:
            True if whitelist successful, False otherwise
        
        Example:
            >>> client = NodogsplashClient()
            >>> client.whitelist_device("AA:BB:CC:DD:EE:FF")
            True
        """
        try:
            # Build auth URL with parameters
            url = f"{self.auth_url}?token={self.token}&mac={mac_address}"
            
            # Make request with timeout
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                logger.info(f"Successfully whitelisted device {mac_address}")
                return True
            else:
                logger.error(f"Failed to whitelist device {mac_address}: HTTP {response.status_code}")
                return False
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error whitelisting device {mac_address}: {e}")
            return False
    
    def whitelist_device_with_retry(self, mac_address: str, max_retries: int = 3) -> bool:
        """
        Grant network access with retry logic.
        
        Args:
            mac_address: Device MAC address
            max_retries: Maximum number of retry attempts
        
        Returns:
            True if whitelist successful, False otherwise
        """
        for attempt in range(max_retries):
            if self.whitelist_device(mac_address):
                return True
            
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2 ** attempt
                logger.warning(f"Retry {attempt + 1}/{max_retries} for {mac_address} in {wait_time}s")
                time.sleep(wait_time)
        
        logger.error(f"Failed to whitelist {mac_address} after {max_retries} attempts")
        return False
    
    def get_client_mac(self, ip_address: str) -> Optional[str]:
        """
        Get MAC address for client IP from ARP table.
        
        This queries the system ARP table to find the MAC address associated
        with a given IP address. Used to identify devices for whitelisting.
        
        Args:
            ip_address: Client IP address
        
        Returns:
            MAC address if found, None otherwise
        
        Example:
            >>> client = NodogsplashClient()
            >>> client.get_client_mac("192.168.4.100")
            'AA:BB:CC:DD:EE:FF'
        """
        try:
            # Run arp command to get MAC address
            # Format: arp -n <ip_address>
            result = subprocess.run(
                ['arp', '-n', ip_address],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                # Parse output to extract MAC address
                # Example output:
                # Address                  HWtype  HWaddress           Flags Mask            Iface
                # 192.168.4.100            ether   aa:bb:cc:dd:ee:ff   C                     wlan0
                
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if ip_address in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            mac = parts[2]
                            # Validate MAC address format
                            if ':' in mac and len(mac) == 17:
                                logger.info(f"Found MAC {mac} for IP {ip_address}")
                                return mac.upper()
            
            logger.warning(f"Could not find MAC address for IP {ip_address}")
            return None
        
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout getting MAC for IP {ip_address}")
            return None
        except Exception as e:
            logger.error(f"Error getting MAC for IP {ip_address}: {e}")
            return None
    
    def get_client_mac_from_request(self, request_environ: dict) -> Optional[str]:
        """
        Get client MAC address from Flask/WSGI request environment.
        
        This attempts to extract the client IP from the request and then
        looks up the MAC address from the ARP table.
        
        Args:
            request_environ: Flask request.environ or WSGI environ dict
        
        Returns:
            MAC address if found, None otherwise
        """
        # Try to get client IP from various headers/environ variables
        client_ip = None
        
        # Check X-Forwarded-For header (if behind proxy)
        if 'HTTP_X_FORWARDED_FOR' in request_environ:
            client_ip = request_environ['HTTP_X_FORWARDED_FOR'].split(',')[0].strip()
        
        # Check X-Real-IP header
        elif 'HTTP_X_REAL_IP' in request_environ:
            client_ip = request_environ['HTTP_X_REAL_IP']
        
        # Fall back to REMOTE_ADDR
        elif 'REMOTE_ADDR' in request_environ:
            client_ip = request_environ['REMOTE_ADDR']
        
        if client_ip:
            logger.debug(f"Client IP from request: {client_ip}")
            return self.get_client_mac(client_ip)
        
        logger.warning("Could not determine client IP from request")
        return None
    
    def is_nodogsplash_running(self) -> bool:
        """
        Check if nodogsplash daemon is running.
        
        Returns:
            True if running, False otherwise
        """
        try:
            # Check if nodogsplash process is running
            result = subprocess.run(
                ['pgrep', '-x', 'nodogsplash'],
                capture_output=True,
                timeout=5
            )
            
            is_running = result.returncode == 0
            
            if is_running:
                logger.debug("nodogsplash daemon is running")
            else:
                logger.warning("nodogsplash daemon is not running")
            
            return is_running
        
        except Exception as e:
            logger.error(f"Error checking nodogsplash status: {e}")
            return False
    
    def get_status(self) -> dict:
        """
        Get nodogsplash status information.
        
        Returns:
            Dictionary with status information
        """
        return {
            'running': self.is_nodogsplash_running(),
            'auth_url': self.auth_url,
            'token_configured': bool(self.token)
        }


class MockNodogsplashClient(NodogsplashClient):
    """
    Mock nodogsplash client for testing and development.
    
    This mock client simulates nodogsplash behavior without requiring
    the actual daemon to be running. Useful for local development and testing.
    """
    
    def __init__(self):
        """Initialize mock client."""
        super().__init__()
        self.whitelisted_macs = set()
        logger.info("Using MockNodogsplashClient (nodogsplash not required)")
    
    def whitelist_device(self, mac_address: str, duration_seconds: int = 86400) -> bool:
        """Mock whitelist - always succeeds and tracks MAC addresses."""
        self.whitelisted_macs.add(mac_address.upper())
        logger.info(f"[MOCK] Whitelisted device {mac_address}")
        return True
    
    def get_client_mac(self, ip_address: str) -> Optional[str]:
        """Mock MAC lookup - returns a fake MAC address."""
        # Generate a fake but consistent MAC based on IP
        ip_parts = ip_address.split('.')
        if len(ip_parts) == 4:
            # Convert string parts to integers for hex formatting
            try:
                octet3 = int(ip_parts[2])
                octet4 = int(ip_parts[3])
                mac = f"AA:BB:CC:DD:{octet3:02X}:{octet4:02X}"
                logger.info(f"[MOCK] Generated MAC {mac} for IP {ip_address}")
                return mac
            except ValueError:
                pass
        return None
    
    def is_nodogsplash_running(self) -> bool:
        """Mock status check - always returns True."""
        return True
    
    def is_whitelisted(self, mac_address: str) -> bool:
        """Check if MAC is in mock whitelist."""
        return mac_address.upper() in self.whitelisted_macs
