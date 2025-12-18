# app/events_db.py - Event Database Management
# Place in chaithra-backend/app/events_db.py

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
import base64

# Use local DB for development
DB_PATH = "./events.db"
IMAGE_DIR = "./event_images"


def init_db():
    """Initialize database and create tables"""
    Path(IMAGE_DIR).mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            plate_number TEXT,
            speed REAL,
            confidence REAL,
            camera_id TEXT,
            board_id TEXT,
            image_path TEXT,
            metadata TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")


def save_event(event_data):
    """
    Save event to database
    
    Args:
        event_data: dict with keys:
            - event_type: str
            - timestamp: str (ISO format)
            - plate_number: str (optional)
            - speed: float (optional)
            - confidence: float (optional)
            - camera_id: str (optional)
            - board_id: str (optional)
            - image_base64: str (optional, data:image/jpeg;base64,...)
            - metadata: dict (optional, any additional data)
    
    Returns:
        event_id: str
    """
    event_id = f"EVT_{uuid.uuid4().hex[:10].upper()}"
    
    # Save image if provided
    image_path = None
    if "image_base64" in event_data:
        try:
            # Extract base64 data
            image_b64 = event_data["image_base64"]
            if "," in image_b64:
                image_b64 = image_b64.split(",")[1]
            
            # Decode and save
            image_bytes = base64.b64decode(image_b64)
            image_filename = f"{event_id}.jpg"
            image_path = f"{IMAGE_DIR}/{image_filename}"
            
            with open(image_path, "wb") as f:
                f.write(image_bytes)
            
            print(f"[DB] Saved image: {image_path}")
        except Exception as e:
            print(f"[DB] Failed to save image: {e}")
    
    # Prepare metadata
    metadata = event_data.get("metadata", {})
    metadata_json = json.dumps(metadata)
    
    # Insert into database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO events 
        (event_id, event_type, timestamp, plate_number, speed, confidence, 
         camera_id, board_id, image_path, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id,
        event_data.get("event_type", "unknown"),
        event_data.get("timestamp", datetime.now().isoformat()),
        event_data.get("plate_number"),
        event_data.get("speed"),
        event_data.get("confidence"),
        event_data.get("camera_id"),
        event_data.get("board_id"),
        image_path,
        metadata_json
    ))
    
    conn.commit()
    conn.close()
    
    print(f"[DB] Event saved: {event_id} - {event_data.get('event_type')}")
    return event_id


def get_recent_events(limit=20):
    """Get recent events for UI"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT event_id, event_type, timestamp, plate_number, speed, 
               confidence, camera_id, board_id, image_path, created_at
        FROM events
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    events = []
    for row in rows:
        event = dict(row)
        
        # Convert image to base64 for frontend
        if event["image_path"] and Path(event["image_path"]).exists():
            try:
                with open(event["image_path"], "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode()
                    event["image_base64"] = f"data:image/jpeg;base64,{image_b64}"
            except Exception as e:
                print(f"[DB] Failed to load image {event['image_path']}: {e}")
                event["image_base64"] = None
        else:
            event["image_base64"] = None
        
        events.append(event)
    
    return events


def get_event_by_id(event_id):
    """Get specific event"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events WHERE event_id = ?
    """, (event_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    event = dict(row)
    
    # Load image
    if event["image_path"] and Path(event["image_path"]).exists():
        try:
            with open(event["image_path"], "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode()
                event["image_base64"] = f"data:image/jpeg;base64,{image_b64}"
        except Exception:
            event["image_base64"] = None
    
    # Parse metadata
    if event["metadata"]:
        event["metadata"] = json.loads(event["metadata"])
    
    return event


def delete_old_events(days=30):
    """Delete events older than specified days"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM events 
        WHERE created_at < datetime('now', ? || ' days')
    """, (f"-{days}",))
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"[DB] Deleted {deleted} old events")
    return deleted