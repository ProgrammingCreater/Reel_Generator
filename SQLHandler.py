import sqlite3
from pathlib import Path


class SQLHandler:
    """
    Handles all database operations for the Reel Generator.
    Tables:
        media  — one row per imported file (photo or video)
        clips  — one row per usable segment (scene-detected or full video, or photo)
        reels  — one row per rendered reel, storing the recipe used
    """

    def __init__(self, db_path="databases/media.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.createTables()

    # ------------------------------------------------------------------ #
    #  Schema                                                              #
    # ------------------------------------------------------------------ #

    def createTables(self):
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id          TEXT PRIMARY KEY,
                path        TEXT NOT NULL UNIQUE,
                media_type  TEXT NOT NULL,
                duration    REAL,
                date_added  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clips (
                id               TEXT PRIMARY KEY,
                media_id         TEXT NOT NULL,
                start_time       REAL,
                end_time         REAL,
                display_duration REAL,
                usage_count      INTEGER DEFAULT 0,
                last_used        TEXT,
                FOREIGN KEY (media_id) REFERENCES media (id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reels (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe       TEXT NOT NULL,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP,
                output_path  TEXT
            )
        """)

        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Media methods                                                       #
    # ------------------------------------------------------------------ #

    def add_media(self, media_id, path, media_type, duration=None):
        self.conn.execute(
            "INSERT OR IGNORE INTO media (id, path, media_type, duration) VALUES (?, ?, ?, ?)",
            (media_id, path, media_type, duration)
        )
        self.conn.commit()

    def get_all_media(self, media_type=None):
        cursor = self.conn.cursor()
        if media_type:
            cursor.execute("SELECT * FROM media WHERE media_type = ?", (media_type,))
        else:
            cursor.execute("SELECT * FROM media")
        return cursor.fetchall()

    def media_exists(self, media_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM media WHERE id = ?", (media_id,))
        return cursor.fetchone() is not None

    # ------------------------------------------------------------------ #
    #  Clip methods                                                        #
    # ------------------------------------------------------------------ #

    def add_clip(self, clip_id, media_id, start_time=None, end_time=None, display_duration=None):
        self.conn.execute(
            "INSERT OR IGNORE INTO clips "
            "(id, media_id, start_time, end_time, display_duration) "
            "VALUES (?, ?, ?, ?, ?)",
            (clip_id, media_id, start_time, end_time, display_duration)
        )
        self.conn.commit()

    def get_clips_weighted(self, media_type=None):
        cursor = self.conn.cursor()
        if media_type:
            cursor.execute("""
                SELECT clips.*, media.path, media.media_type
                FROM clips
                JOIN media ON clips.media_id = media.id
                WHERE media.media_type = ?
                ORDER BY clips.usage_count ASC
            """, (media_type,))
        else:
            cursor.execute("""
                SELECT clips.*, media.path, media.media_type
                FROM clips
                JOIN media ON clips.media_id = media.id
                ORDER BY clips.usage_count ASC
            """)
        return cursor.fetchall()

    def get_all_clips(self):
        """Return every clip joined with its media row, no ordering."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT clips.*, media.path, media.media_type
            FROM clips
            JOIN media ON clips.media_id = media.id
        """)
        return cursor.fetchall()

    def increment_usage(self, clip_id):
        self.conn.execute(
            "UPDATE clips "
            "SET usage_count = usage_count + 1, last_used = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (clip_id,)
        )
        self.conn.commit()

    def clip_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clips")
        return cursor.fetchone()[0]

    # ------------------------------------------------------------------ #
    #  Reel / history methods                                              #
    # ------------------------------------------------------------------ #

    def save_reel(self, recipe_json, output_path):
        self.conn.execute(
            "INSERT INTO reels (recipe, output_path) VALUES (?, ?)",
            (recipe_json, output_path)
        )
        self.conn.commit()

    def get_all_reels(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM reels")
        return cursor.fetchall()

    # ------------------------------------------------------------------ #
    #  Clear                                                               #
    # ------------------------------------------------------------------ #

    def clear_all(self):
        """
        Wipe all rows from every table and reset the reels auto-increment
        counter. Does NOT delete the actual media files from disk.
        """
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("DELETE FROM reels")
        cursor.execute("DELETE FROM clips")
        cursor.execute("DELETE FROM media")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'reels'")
        cursor.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Teardown                                                            #
    # ------------------------------------------------------------------ #

    def close(self):
        self.conn.close()
