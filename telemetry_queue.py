"""
Queue Manager for CrowdSurfer Edge Devices

Manages local SQLite queue for offline operation.
Handles analytics records and portal submissions with prioritization.
"""

import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class QueueItemType(Enum):
    """Queue item types with priority"""
    PORTAL_SUBMISSION = 1  # Highest priority
    ANALYTICS_RECORD = 2   # Lower priority


class QueueManager:
    """Manages local queue for offline data storage"""
    
    # Storage limits
    MAX_QUEUE_SIZE_MB = 100
    MAX_ANALYTICS_RECORDS = 10000
    MAX_SUBMISSIONS = 1000
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize SQLite database schema."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS queue_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_type INTEGER NOT NULL,
                        priority INTEGER NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        retry_count INTEGER DEFAULT 0,
                        last_retry_at TEXT
                    )
                """)
                
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_queue_priority 
                    ON queue_items(priority, created_at)
                """)
                
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_queue_type 
                    ON queue_items(item_type)
                """)
                
                conn.commit()
                logger.info(f"Initialized queue database: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def enqueue_analytics(self, record: Dict[str, Any]) -> None:
        """
        Enqueue analytics record.
        
        Args:
            record: Analytics record data
        """
        try:
            # Check storage limits
            if self._get_analytics_count() >= self.MAX_ANALYTICS_RECORDS:
                logger.warning("Analytics queue full, dropping oldest record")
                self._drop_oldest_analytics()
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO queue_items (item_type, priority, data, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    QueueItemType.ANALYTICS_RECORD.value,
                    QueueItemType.ANALYTICS_RECORD.value,
                    json.dumps(record),
                    self._get_timestamp()
                ))
                conn.commit()
                logger.debug("Enqueued analytics record")
        except Exception as e:
            logger.error(f"Failed to enqueue analytics: {e}")
            raise
    
    def enqueue_submission(self, submission: Dict[str, Any]) -> None:
        """
        Enqueue portal submission (higher priority).
        
        Args:
            submission: Portal submission data
        """
        try:
            # Check storage limits
            if self._get_submission_count() >= self.MAX_SUBMISSIONS:
                logger.error("Submission queue full, cannot accept more submissions")
                raise ValueError("Submission queue full")
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO queue_items (item_type, priority, data, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    QueueItemType.PORTAL_SUBMISSION.value,
                    QueueItemType.PORTAL_SUBMISSION.value,
                    json.dumps(submission),
                    self._get_timestamp()
                ))
                conn.commit()
                logger.info("Enqueued portal submission")
        except Exception as e:
            logger.error(f"Failed to enqueue submission: {e}")
            raise
    
    def dequeue_batch(self, batch_size: int = 100) -> List[Tuple[int, QueueItemType, Dict[str, Any]]]:
        """
        Dequeue batch of items in priority order.
        
        Portal submissions are dequeued before analytics records.
        Within each type, items are dequeued in chronological order.
        
        Args:
            batch_size: Maximum number of items to dequeue
            
        Returns:
            List of (id, item_type, data) tuples
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT id, item_type, data
                    FROM queue_items
                    ORDER BY priority ASC, created_at ASC
                    LIMIT ?
                """, (batch_size,))
                
                items = []
                for row in cursor:
                    item_id, item_type_value, data_json = row
                    item_type = QueueItemType(item_type_value)
                    data = json.loads(data_json)
                    items.append((item_id, item_type, data))
                
                logger.debug(f"Dequeued {len(items)} items")
                return items
        except Exception as e:
            logger.error(f"Failed to dequeue batch: {e}")
            return []
    
    def mark_synced(self, item_ids: List[int]) -> None:
        """
        Remove successfully synced items from queue.
        
        Args:
            item_ids: List of item IDs to remove
        """
        if not item_ids:
            return
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                placeholders = ','.join('?' * len(item_ids))
                conn.execute(f"""
                    DELETE FROM queue_items
                    WHERE id IN ({placeholders})
                """, item_ids)
                conn.commit()
                logger.info(f"Marked {len(item_ids)} items as synced")
        except Exception as e:
            logger.error(f"Failed to mark items as synced: {e}")
    
    def mark_failed(self, item_ids: List[int]) -> None:
        """
        Increment retry count for failed items.
        
        Args:
            item_ids: List of item IDs that failed to sync
        """
        if not item_ids:
            return
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                placeholders = ','.join('?' * len(item_ids))
                conn.execute(f"""
                    UPDATE queue_items
                    SET retry_count = retry_count + 1,
                        last_retry_at = ?
                    WHERE id IN ({placeholders})
                """, [self._get_timestamp()] + item_ids)
                conn.commit()
                logger.warning(f"Marked {len(item_ids)} items as failed")
        except Exception as e:
            logger.error(f"Failed to mark items as failed: {e}")
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with queue statistics
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get counts by type
                cursor = conn.execute("""
                    SELECT item_type, COUNT(*) as count
                    FROM queue_items
                    GROUP BY item_type
                """)
                
                stats = {
                    'analytics_count': 0,
                    'submission_count': 0,
                    'total_count': 0
                }
                
                for row in cursor:
                    item_type_value, count = row
                    if item_type_value == QueueItemType.ANALYTICS_RECORD.value:
                        stats['analytics_count'] = count
                    elif item_type_value == QueueItemType.PORTAL_SUBMISSION.value:
                        stats['submission_count'] = count
                    stats['total_count'] += count
                
                # Get database size
                stats['size_mb'] = self.db_path.stat().st_size / (1024 * 1024)
                
                return stats
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {
                'analytics_count': 0,
                'submission_count': 0,
                'total_count': 0,
                'size_mb': 0
            }
    
    def cleanup_old_records(self, days: int = 7) -> int:
        """
        Clean up old records that failed to sync.
        
        Args:
            days: Number of days to keep records
            
        Returns:
            Number of records deleted
        """
        try:
            cutoff_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)
            cutoff_str = cutoff_date.isoformat() + 'Z'
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM queue_items
                    WHERE created_at < ?
                """, (cutoff_str,))
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old records")
                
                return deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup old records: {e}")
            return 0
    
    def _get_analytics_count(self) -> int:
        """Get count of analytics records in queue."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM queue_items
                    WHERE item_type = ?
                """, (QueueItemType.ANALYTICS_RECORD.value,))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to get analytics count: {e}")
            return 0
    
    def _get_submission_count(self) -> int:
        """Get count of portal submissions in queue."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM queue_items
                    WHERE item_type = ?
                """, (QueueItemType.PORTAL_SUBMISSION.value,))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to get submission count: {e}")
            return 0
    
    def _drop_oldest_analytics(self) -> None:
        """Drop oldest analytics record to make room."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    DELETE FROM queue_items
                    WHERE id = (
                        SELECT id FROM queue_items
                        WHERE item_type = ?
                        ORDER BY created_at ASC
                        LIMIT 1
                    )
                """, (QueueItemType.ANALYTICS_RECORD.value,))
                conn.commit()
                logger.debug("Dropped oldest analytics record")
        except Exception as e:
            logger.error(f"Failed to drop oldest analytics: {e}")
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.utcnow().isoformat() + 'Z'
