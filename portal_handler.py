"""
Portal Handler for CrowdSurfer Edge Devices

Serves captive portal, validates submissions, and grants WiFi access.
"""

import logging
import hashlib
import subprocess
import platform
import os
from typing import Dict, Any, Optional
from datetime import datetime
from config import Config, get_config
from telemetry_queue import QueueManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PortalHandler:
    """Handles captive portal serving and form submissions"""
    
    def __init__(self, config: Config, queue: QueueManager):
        self.config = config
        self.queue = queue
    
    def serve_portal(self, mac_address: str) -> str:
        """
        Serve captive portal HTML.
        
        Args:
            mac_address: Client MAC address
            
        Returns:
            HTML content for portal
        """
        if not self.config.is_assigned():
            # Device not assigned to event, show default portal
            return self._get_default_portal()
        
        # Get cached event configuration
        event_config = self.config.event_config
        
        if not event_config:
            return self._get_default_portal()
        
        # Serve cached HTML with CSS
        html_content = event_config.get('html_content', '')
        css_content = event_config.get('css_content', '')
        
        # Inject CSS into HTML
        if css_content and '<head>' in html_content:
            style_tag = f'<style>{css_content}</style>'
            html_content = html_content.replace('<head>', f'<head>{style_tag}')
        
        return html_content
    
    def validate_submission(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate portal form submission.
        
        Args:
            form_data: Form data from submission
            
        Returns:
            Validation result with errors if any
        """
        errors = []
        
        if not self.config.is_assigned():
            return {
                'valid': False,
                'errors': ['Device not assigned to event']
            }
        
        event_config = self.config.event_config
        
        if not event_config:
            return {
                'valid': False,
                'errors': ['No event configuration available']
            }
        
        # Validate required fields based on event configuration
        if event_config.get('require_email') and not form_data.get('email'):
            errors.append('Email is required')
        
        if event_config.get('require_phone') and not form_data.get('phone'):
            errors.append('Phone number is required')
        
        # Validate email format if provided
        if form_data.get('email'):
            email = form_data['email']
            if '@' not in email or '.' not in email:
                errors.append('Invalid email format')
        
        # Validate phone format if provided
        if form_data.get('phone'):
            phone = form_data['phone']
            # Remove non-digits
            digits = ''.join(c for c in phone if c.isdigit())
            if len(digits) < 10:
                errors.append('Invalid phone number')
        
        # Validate name fields
        if not form_data.get('first_name'):
            errors.append('First name is required')
        
        if not form_data.get('last_name'):
            errors.append('Last name is required')
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    def grant_wifi_access(self, mac_address: str) -> bool:
        """
        Grant WiFi access to MAC address.
        
        Args:
            mac_address: Client MAC address
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if ndsctl is available
            check_cmd = ['which', 'ndsctl'] if platform.system() != 'Windows' else ['where', 'ndsctl']
            
            result = subprocess.run(
                check_cmd,
                capture_output=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.warning("ndsctl not found, WiFi access granting disabled (testing mode)")
                # In testing mode, pretend success
                return True
            
            # Grant access using nodogsplash
            subprocess.run(
                ['ndsctl', 'auth', mac_address],
                check=True,
                timeout=5
            )
            
            logger.info(f"Granted WiFi access to {mac_address}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to grant WiFi access: {e}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout granting WiFi access to {mac_address}")
            return False
        except Exception as e:
            logger.error(f"Error granting WiFi access: {e}")
            return False
    
    def queue_submission(self, submission: Dict[str, Any]) -> bool:
        """
        Queue portal submission for sync to backend.
        
        Args:
            submission: Portal submission data
            
        Returns:
            True if queued successfully, False otherwise
        """
        try:
            # Add timestamp if not present
            if 'submission_timestamp' not in submission:
                submission['submission_timestamp'] = self._get_timestamp()
            
            # Hash MAC address for privacy
            if 'mac_address' in submission:
                mac_hash = self._hash_mac_address(submission['mac_address'])
                submission['mac_address_hash'] = mac_hash
                del submission['mac_address']  # Don't store raw MAC
            
            # Queue for sync
            self.queue.enqueue_submission(submission)
            
            logger.info(f"Queued portal submission for {submission.get('first_name')} {submission.get('last_name')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to queue submission: {e}")
            return False
    
    def handle_submission(self, form_data: Dict[str, Any], mac_address: str) -> Dict[str, Any]:
        """
        Handle complete portal submission flow.
        
        Args:
            form_data: Form data from submission
            mac_address: Client MAC address
            
        Returns:
            Response with success status and message
        """
        # Validate submission
        validation = self.validate_submission(form_data)
        
        if not validation['valid']:
            return {
                'success': False,
                'errors': validation['errors']
            }
        
        # Add MAC address to submission
        form_data['mac_address'] = mac_address
        
        # Queue submission
        if not self.queue_submission(form_data):
            return {
                'success': False,
                'errors': ['Failed to save submission']
            }
        
        # Grant WiFi access
        if not self.grant_wifi_access(mac_address):
            logger.warning(f"Submission saved but failed to grant WiFi access to {mac_address}")
        
        return {
            'success': True,
            'message': 'Thank you for your submission!'
        }
    
    def _get_default_portal(self) -> str:
        """Get default portal HTML when device is not assigned."""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>CrowdSurfer WiFi</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 50px;
                    background-color: #f5f5f5;
                }
                .container {
                    max-width: 500px;
                    margin: 0 auto;
                    background: white;
                    padding: 30px;
                    border-radius: 10px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }
                h1 {
                    color: #333;
                }
                p {
                    color: #666;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>CrowdSurfer WiFi</h1>
                <p>This device is not currently assigned to an event.</p>
                <p>Please contact the administrator.</p>
            </div>
        </body>
        </html>
        """
    
    def _hash_mac_address(self, mac_address: str) -> str:
        """Hash MAC address with SHA-256 for privacy."""
        return hashlib.sha256(mac_address.encode('utf-8')).hexdigest()
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.utcnow().isoformat() + 'Z'


def main():
    """Main entry point for portal handler (for testing)."""
    logger.info("CrowdSurfer Portal Handler")
    
    config = get_config()
    queue = QueueManager(config.QUEUE_DB)
    handler = PortalHandler(config, queue)
    
    # Test portal serving
    html = handler.serve_portal("00:11:22:33:44:55")
    print(html)
    
    return 0


if __name__ == "__main__":
    exit(main())
