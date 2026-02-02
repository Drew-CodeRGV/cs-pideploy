"""
Flask portal server for captive portal.

This module provides the web server for the captive portal, handling
registration form submissions, survey responses, and portal configuration.
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from portal.models import PortalDatabase
from portal.validators import FormValidator
from portal.nodogsplash_client import NodogsplashClient, MockNodogsplashClient
from config import get_config

logger = logging.getLogger(__name__)


class PortalServer:
    """Main Flask application for captive portal."""
    
    def __init__(self, db_path: str = "/var/lib/crowdsurfer/portal.db",
                 use_mock_nodogsplash: bool = False):
        """
        Initialize portal server.
        
        Args:
            db_path: Path to SQLite database
            use_mock_nodogsplash: Use mock nodogsplash client for testing
        """
        self.app = Flask(__name__, 
                        static_folder='static',
                        static_url_path='/portal/static')
        CORS(self.app)
        
        self.db = PortalDatabase(db_path)
        self.config = get_config()
        
        # Initialize nodogsplash client
        if use_mock_nodogsplash:
            self.nodogsplash = MockNodogsplashClient()
            logger.info("Using mock nodogsplash client")
        else:
            self.nodogsplash = NodogsplashClient()
        
        self._register_routes()
    
    def _register_routes(self):
        """Register Flask routes."""
        
        @self.app.route('/portal/register', methods=['POST'])
        def register():
            """Handle registration form submission."""
            return self.register_attendee()
        
        @self.app.route('/portal/survey', methods=['POST'])
        def survey():
            """Handle survey submission."""
            return self.submit_survey()
        
        @self.app.route('/portal/config', methods=['GET'])
        def config():
            """Get portal configuration."""
            return self.get_portal_config()
        
        @self.app.route('/portal/static/<path:filename>')
        def serve_static(filename):
            """Serve static files."""
            return send_from_directory('static', filename)
        
        @self.app.route('/portal/health', methods=['GET'])
        def health():
            """Health check endpoint."""
            return jsonify({
                'status': 'ok',
                'nodogsplash': self.nodogsplash.get_status()
            })
    
    def register_attendee(self) -> tuple:
        """
        Register new attendee and grant network access.
        
        Steps:
        1. Validate form data
        2. Check for existing visitor by phone/email (duplicate detection)
        3. Generate or reuse Global Visitor ID
        4. Store attendee record
        5. Whitelist device MAC in nodogsplash
        6. Return visitor_id and survey redirect
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            # Get form data
            data = request.get_json()
            
            if not data:
                return jsonify({
                    'success': False,
                    'error': 'No data provided'
                }), 400
            
            # Validate form data
            is_valid, errors = FormValidator.validate_registration(data)
            
            if not is_valid:
                return jsonify({
                    'success': False,
                    'errors': errors
                }), 400
            
            # Check for recent duplicate submission (within 5 minutes)
            recent_attendee = self.db.find_recent_attendee(
                data['email'], 
                data['phone'],
                minutes=5
            )
            
            if recent_attendee:
                # Update existing record
                logger.info(f"Updating recent attendee: {recent_attendee['id']}")
                
                self.db.update_attendee(recent_attendee['id'], {
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'email': data['email'],
                    'phone': data['phone'],
                    'zip': data['zip'],
                    'dob': data['dob'],
                    'raffle_opt_in': data.get('raffle_opt_in', False),
                    'submitted_at': datetime.utcnow().isoformat()
                })
                
                visitor_id = recent_attendee['global_visitor_id']
                attendee_id = recent_attendee['id']
            
            else:
                # Check for existing visitor from previous events (cross-event recognition)
                existing_visitor_id = self.db.find_visitor_by_contact(
                    data['email'],
                    data['phone']
                )
                
                # Generate or reuse Global Visitor ID
                if existing_visitor_id:
                    visitor_id = existing_visitor_id
                    logger.info(f"Reusing visitor ID for returning attendee: {visitor_id}")
                else:
                    visitor_id = str(uuid.uuid4())
                    logger.info(f"Generated new visitor ID: {visitor_id}")
                
                # Get client MAC address
                mac_address = self.nodogsplash.get_client_mac_from_request(request.environ)
                
                # Create attendee record
                attendee_data = {
                    'global_visitor_id': visitor_id,
                    'event_id': self.config.event_config.get('event_id') if self.config.event_config else 'unknown',
                    'device_id': str(self.config.device_id) if self.config.device_id else 'unknown',
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'email': data['email'],
                    'phone': data['phone'],
                    'zip': data['zip'],
                    'dob': data['dob'],
                    'raffle_opt_in': data.get('raffle_opt_in', False),
                    'mac_address': mac_address,
                    'submitted_at': datetime.utcnow().isoformat()
                }
                
                attendee_id = self.db.create_attendee(attendee_data)
                logger.info(f"Created attendee record: {attendee_id}")
            
            # Whitelist device in nodogsplash
            mac_address = self.nodogsplash.get_client_mac_from_request(request.environ)
            
            if mac_address:
                success = self.nodogsplash.whitelist_device_with_retry(mac_address)
                
                if success:
                    # Add to local whitelist
                    self.db.add_to_whitelist(mac_address, visitor_id)
                    logger.info(f"Whitelisted device: {mac_address}")
                else:
                    logger.error(f"Failed to whitelist device: {mac_address}")
                    # Continue anyway - attendee data is saved
            else:
                logger.warning("Could not determine client MAC address")
            
            # Check if survey questions are configured
            portal_config = self.db.get_portal_config()
            show_survey = False
            
            if portal_config and portal_config['config'].get('survey_questions'):
                show_survey = len(portal_config['config']['survey_questions']) > 0
            
            # Return success response
            return jsonify({
                'success': True,
                'visitor_id': visitor_id,
                'attendee_id': attendee_id,
                'show_survey': show_survey,
                'redirect_url': f'/portal/survey?visitor_id={visitor_id}' if show_survey else None
            }), 200
        
        except Exception as e:
            logger.error(f"Error registering attendee: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500
    
    def submit_survey(self) -> tuple:
        """
        Store survey responses.
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            # Get survey data
            data = request.get_json()
            
            if not data:
                return jsonify({
                    'success': False,
                    'error': 'No data provided'
                }), 400
            
            visitor_id = data.get('visitor_id')
            responses = data.get('responses', [])
            
            if not visitor_id:
                return jsonify({
                    'success': False,
                    'error': 'visitor_id is required'
                }), 400
            
            # If no responses provided, that's okay (survey is optional)
            if not responses or len(responses) == 0:
                logger.info(f"No survey responses provided for visitor {visitor_id}")
                return jsonify({
                    'success': True,
                    'message': 'Thank you!'
                }), 200
            
            # Find attendee by visitor_id
            attendees = self.db.get_unsynced_attendees(limit=1000)
            attendee_id = None
            
            for attendee in attendees:
                if attendee['global_visitor_id'] == visitor_id:
                    attendee_id = attendee['id']
                    break
            
            if not attendee_id:
                logger.warning(f"Could not find attendee for visitor {visitor_id}")
                # Still return success - don't block user
                return jsonify({
                    'success': True,
                    'message': 'Thank you!'
                }), 200
            
            # Validate and store survey responses
            portal_config = self.db.get_portal_config()
            question_types = {}
            
            if portal_config and portal_config['config'].get('survey_questions'):
                for q in portal_config['config']['survey_questions']:
                    question_types[q['id']] = q['type']
            
            # Validate each response
            valid_responses = []
            for response in responses:
                question_id = response.get('question_id')
                answer = response.get('answer', '')
                
                # Skip empty answers
                if not answer or not answer.strip():
                    continue
                
                # Validate if we have question type
                if question_id in question_types:
                    is_valid, error = FormValidator.validate_survey_response(
                        response,
                        question_types[question_id]
                    )
                    
                    if not is_valid:
                        logger.warning(f"Invalid survey response: {error}")
                        continue
                
                valid_responses.append(response)
            
            # Store valid responses
            if valid_responses:
                self.db.create_survey_responses(visitor_id, attendee_id, valid_responses)
                logger.info(f"Stored {len(valid_responses)} survey responses for visitor {visitor_id}")
            
            return jsonify({
                'success': True,
                'message': 'Thank you for your feedback!'
            }), 200
        
        except Exception as e:
            logger.error(f"Error submitting survey: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500
    
    def get_portal_config(self) -> tuple:
        """
        Get cached portal configuration.
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            portal_config = self.db.get_portal_config()
            
            if portal_config:
                return jsonify(portal_config['config']), 200
            else:
                # Return default config if none cached
                return jsonify({
                    'event': {
                        'name': 'Event',
                        'header_image_url': None
                    },
                    'candidate': {
                        'name': 'Candidate',
                        'photo_url': None,
                        'slogan': ''
                    },
                    'raffle': {
                        'enabled': False,
                        'prize_description': ''
                    },
                    'survey_questions': []
                }), 200
        
        except Exception as e:
            logger.error(f"Error getting portal config: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500
    
    def update_portal_config(self, config: Dict[str, Any], version: str):
        """
        Update portal configuration from heartbeat.
        
        Args:
            config: Configuration dictionary
            version: Configuration version string
        """
        try:
            self.db.update_portal_config(config, version)
            logger.info(f"Updated portal config to version {version}")
        except Exception as e:
            logger.error(f"Error updating portal config: {e}", exc_info=True)
            raise
    
    def run(self, host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
        """
        Run Flask development server.
        
        Args:
            host: Host to bind to
            port: Port to bind to
            debug: Enable debug mode
        """
        self.app.run(host=host, port=port, debug=debug)


def create_app(db_path: str = "/var/lib/crowdsurfer/portal.db",
               use_mock_nodogsplash: bool = False) -> Flask:
    """
    Create Flask application instance.
    
    Args:
        db_path: Path to SQLite database
        use_mock_nodogsplash: Use mock nodogsplash client for testing
    
    Returns:
        Flask application instance
    """
    server = PortalServer(db_path, use_mock_nodogsplash)
    return server.app


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run server
    server = PortalServer(
        db_path="/tmp/portal_test.db",
        use_mock_nodogsplash=True
    )
    
    logger.info("Starting portal server on http://0.0.0.0:5000")
    server.run(debug=True)
