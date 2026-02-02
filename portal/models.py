"""
SQLite database models for captive portal.

This module defines the database schema for storing attendee records,
survey responses, portal configuration, and device whitelist on the
Raspberry Pi edge node.
"""

import sqlite3
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


class PortalDatabase:
    """SQLite database operations for captive portal."""
    
    def __init__(self, db_path: str = "/var/lib/crowdsurfer/portal.db"):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._init_database()
    
    def _init_database(self):
        """Create database tables if they don't exist."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        cursor = self.conn.cursor()
        
        # Attendee records table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendees (
                id TEXT PRIMARY KEY,
                global_visitor_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                zip TEXT NOT NULL,
                dob TEXT NOT NULL,
                raffle_opt_in INTEGER DEFAULT 0,
                mac_address TEXT,
                submitted_at TEXT NOT NULL,
                synced INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        
        # Create indexes for attendees
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attendees_global_visitor_id 
            ON attendees(global_visitor_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attendees_synced 
            ON attendees(synced)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attendees_email 
            ON attendees(email)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attendees_phone 
            ON attendees(phone)
        """)
        
        # Survey responses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS survey_responses (
                id TEXT PRIMARY KEY,
                global_visitor_id TEXT NOT NULL,
                attendee_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                answer TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                synced INTEGER DEFAULT 0,
                FOREIGN KEY (attendee_id) REFERENCES attendees(id)
            )
        """)
        
        # Create indexes for survey_responses
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_survey_responses_visitor_id 
            ON survey_responses(global_visitor_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_survey_responses_synced 
            ON survey_responses(synced)
        """)
        
        # Portal configuration cache table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portal_config (
                id INTEGER PRIMARY KEY,
                config_json TEXT NOT NULL,
                config_version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Device whitelist table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_whitelist (
                mac_address TEXT PRIMARY KEY,
                visitor_id TEXT,
                granted_at TEXT NOT NULL,
                expires_at TEXT
            )
        """)
        
        self.conn.commit()
    
    def create_attendee(self, data: Dict[str, Any]) -> str:
        """
        Create attendee record.
        
        Args:
            data: Dictionary containing attendee information with keys:
                - global_visitor_id: UUID string
                - event_id: Event UUID string
                - device_id: Device ID string
                - first_name: First name
                - last_name: Last name
                - email: Email address
                - phone: Phone number (10 digits)
                - zip: Zip code (5 digits)
                - dob: Date of birth (ISO format)
                - raffle_opt_in: Boolean (optional, default False)
                - mac_address: MAC address (optional)
                - submitted_at: ISO timestamp
        
        Returns:
            Attendee ID (UUID string)
        """
        attendee_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO attendees (
                id, global_visitor_id, event_id, device_id,
                first_name, last_name, email, phone, zip, dob,
                raffle_opt_in, mac_address, submitted_at, synced, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (
            attendee_id,
            data['global_visitor_id'],
            data['event_id'],
            data['device_id'],
            data['first_name'],
            data['last_name'],
            data['email'],
            data['phone'],
            data['zip'],
            data['dob'],
            1 if data.get('raffle_opt_in', False) else 0,
            data.get('mac_address'),
            data['submitted_at'],
            now
        ))
        self.conn.commit()
        
        return attendee_id
    
    def find_visitor_by_contact(self, email: str, phone: str) -> Optional[str]:
        """
        Find existing global_visitor_id by email or phone.
        
        This is used for cross-event visitor recognition and duplicate detection.
        
        Args:
            email: Email address to search for
            phone: Phone number to search for
        
        Returns:
            global_visitor_id if found, None otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT global_visitor_id 
            FROM attendees 
            WHERE email = ? OR phone = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (email, phone))
        
        row = cursor.fetchone()
        return row['global_visitor_id'] if row else None
    
    def find_recent_attendee(self, email: str, phone: str, minutes: int = 5) -> Optional[Dict[str, Any]]:
        """
        Find recent attendee by email or phone within time window.
        
        Used for duplicate detection within 5-minute window.
        
        Args:
            email: Email address to search for
            phone: Phone number to search for
            minutes: Time window in minutes (default 5)
        
        Returns:
            Attendee record dict if found, None otherwise
        """
        cursor = self.conn.cursor()
        
        # Calculate cutoff time
        cutoff = datetime.utcnow()
        from datetime import timedelta
        cutoff = cutoff - timedelta(minutes=minutes)
        cutoff_str = cutoff.isoformat()
        
        cursor.execute("""
            SELECT * 
            FROM attendees 
            WHERE (email = ? OR phone = ?) 
            AND submitted_at >= ?
            ORDER BY submitted_at DESC
            LIMIT 1
        """, (email, phone, cutoff_str))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def update_attendee(self, attendee_id: str, data: Dict[str, Any]):
        """
        Update existing attendee record.
        
        Args:
            attendee_id: Attendee ID to update
            data: Dictionary with fields to update
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE attendees 
            SET first_name = ?, last_name = ?, email = ?, phone = ?,
                zip = ?, dob = ?, raffle_opt_in = ?, submitted_at = ?
            WHERE id = ?
        """, (
            data['first_name'],
            data['last_name'],
            data['email'],
            data['phone'],
            data['zip'],
            data['dob'],
            1 if data.get('raffle_opt_in', False) else 0,
            data['submitted_at'],
            attendee_id
        ))
        self.conn.commit()
    
    def create_survey_responses(self, visitor_id: str, attendee_id: str, responses: List[Dict[str, str]]):
        """
        Create survey response records.
        
        Args:
            visitor_id: Global visitor ID
            attendee_id: Attendee ID
            responses: List of dicts with keys:
                - question_id: Question ID
                - answer: Answer text
        """
        now = datetime.utcnow().isoformat()
        cursor = self.conn.cursor()
        
        for response in responses:
            response_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO survey_responses (
                    id, global_visitor_id, attendee_id, question_id,
                    answer, submitted_at, synced
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (
                response_id,
                visitor_id,
                attendee_id,
                response['question_id'],
                response['answer'],
                now
            ))
        
        self.conn.commit()
    
    def get_unsynced_attendees(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get attendees not yet synced to cloud.
        
        Args:
            limit: Maximum number of records to return
        
        Returns:
            List of attendee record dicts
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM attendees 
            WHERE synced = 0 
            ORDER BY created_at ASC 
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_unsynced_survey_responses(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get survey responses not yet synced to cloud.
        
        Args:
            limit: Maximum number of records to return
        
        Returns:
            List of survey response record dicts
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM survey_responses 
            WHERE synced = 0 
            ORDER BY submitted_at ASC 
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def mark_synced(self, table: str, ids: List[str]):
        """
        Mark records as synced.
        
        Args:
            table: Table name ('attendees' or 'survey_responses')
            ids: List of record IDs to mark as synced
        """
        if not ids:
            return
        
        cursor = self.conn.cursor()
        placeholders = ','.join('?' * len(ids))
        cursor.execute(f"""
            UPDATE {table} 
            SET synced = 1 
            WHERE id IN ({placeholders})
        """, ids)
        self.conn.commit()
    
    def get_portal_config(self) -> Optional[Dict[str, Any]]:
        """
        Get cached portal configuration.
        
        Returns:
            Configuration dict if exists, None otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT config_json, config_version, updated_at 
            FROM portal_config 
            ORDER BY id DESC 
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        if row:
            import json
            return {
                'config': json.loads(row['config_json']),
                'version': row['config_version'],
                'updated_at': row['updated_at']
            }
        return None
    
    def update_portal_config(self, config: Dict[str, Any], version: str):
        """
        Update portal configuration cache.
        
        Args:
            config: Configuration dictionary
            version: Configuration version string
        """
        import json
        now = datetime.utcnow().isoformat()
        
        cursor = self.conn.cursor()
        
        # Delete old config
        cursor.execute("DELETE FROM portal_config")
        
        # Insert new config
        cursor.execute("""
            INSERT INTO portal_config (config_json, config_version, updated_at)
            VALUES (?, ?, ?)
        """, (json.dumps(config), version, now))
        
        self.conn.commit()
    
    def add_to_whitelist(self, mac_address: str, visitor_id: Optional[str] = None, 
                        expires_at: Optional[str] = None):
        """
        Add device MAC address to whitelist.
        
        Args:
            mac_address: Device MAC address
            visitor_id: Global visitor ID (optional)
            expires_at: Expiration timestamp (optional)
        """
        now = datetime.utcnow().isoformat()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO device_whitelist (mac_address, visitor_id, granted_at, expires_at)
            VALUES (?, ?, ?, ?)
        """, (mac_address, visitor_id, now, expires_at))
        
        self.conn.commit()
    
    def is_whitelisted(self, mac_address: str) -> bool:
        """
        Check if device MAC address is whitelisted.
        
        Args:
            mac_address: Device MAC address
        
        Returns:
            True if whitelisted, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 1 FROM device_whitelist 
            WHERE mac_address = ?
        """, (mac_address,))
        
        return cursor.fetchone() is not None
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
