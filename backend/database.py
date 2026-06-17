import aiosqlite
import json
import logging
from pathlib import Path
from typing import Optional
import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH

logger = logging.getLogger(__name__)

async def init_db():
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_url TEXT,
                file_path TEXT,
                duration REAL,
                status TEXT DEFAULT 'processing',
                error_message TEXT,
                frame_count INTEGER DEFAULT 0,
                progress_step TEXT DEFAULT '',
                progress_pct INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                timestamp_sec REAL NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                frame_refs TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT 'MiniMax-M3',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # 迁移：为旧表添加进度字段
        cursor = await db.execute("PRAGMA table_info(videos)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "progress_step" not in columns:
            await db.execute("ALTER TABLE videos ADD COLUMN progress_step TEXT DEFAULT ''")
        if "progress_pct" not in columns:
            await db.execute("ALTER TABLE videos ADD COLUMN progress_pct INTEGER DEFAULT 0")
        await db.commit()
    logger.info("Database initialized")

async def create_video(name: str, source_url: str = None, file_path: str = None) -> int:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "INSERT INTO videos (name, source_url, file_path) VALUES (?, ?, ?)",
            (name, source_url, file_path)
        )
        await db.commit()
        return cursor.lastrowid

async def get_video(video_id: int) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM videos WHERE id = ?", (video_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def list_videos() -> list:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM videos ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_video(video_id: int, **kwargs) -> None:
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [video_id]
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(f"UPDATE videos SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals)
        await db.commit()

async def delete_video(video_id: int) -> None:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        await db.commit()

async def create_frame(video_id: int, file_path: str, timestamp_sec: float) -> int:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "INSERT INTO frames (video_id, file_path, timestamp_sec) VALUES (?, ?, ?)",
            (video_id, file_path, timestamp_sec)
        )
        await db.commit()
        return cursor.lastrowid

async def get_frames(video_id: int) -> list:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM frames WHERE video_id = ? ORDER BY timestamp_sec", (video_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_frame(frame_id: int) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def delete_frames(video_id: int) -> None:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("DELETE FROM frames WHERE video_id = ?", (video_id,))
        await db.commit()

async def create_conversation(video_id: int, title: str = None) -> int:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "INSERT INTO conversations (video_id, title) VALUES (?, ?)", (video_id, title)
        )
        await db.commit()
        return cursor.lastrowid

async def get_conversation(conversation_id: int) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def list_conversations(video_id: int = None) -> list:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        if video_id:
            async with db.execute(
                "SELECT * FROM conversations WHERE video_id = ? ORDER BY updated_at DESC", (video_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with db.execute("SELECT * FROM conversations ORDER BY updated_at DESC") as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def delete_conversation(conversation_id: int) -> None:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        await db.commit()


async def update_conversation(conversation_id: int, **kwargs) -> None:
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [conversation_id]
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(f"UPDATE conversations SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals)
        await db.commit()

async def create_message(conversation_id: int, role: str, content: str, frame_refs: list = None) -> int:
    frame_refs_json = json.dumps(frame_refs) if frame_refs else None
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "INSERT INTO messages (conversation_id, role, content, frame_refs) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, frame_refs_json)
        )
        await db.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,)
        )
        await db.commit()
        return cursor.lastrowid

async def get_messages(conversation_id: int) -> list:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at", (conversation_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                if d.get("frame_refs"):
                    d["frame_refs"] = json.loads(d["frame_refs"])
                result.append(d)
            return result


# ----- Providers -----

async def list_providers() -> list:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, base_url, api_key, model, is_default, created_at, updated_at "
            "FROM providers ORDER BY is_default DESC, id ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_provider(provider_id: int) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, base_url, api_key, model, is_default, created_at, updated_at "
            "FROM providers WHERE id = ?", (provider_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_default_provider() -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, base_url, api_key, model, is_default, created_at, updated_at "
            "FROM providers WHERE is_default = 1 LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, base_url, api_key, model, is_default, created_at, updated_at "
            "FROM providers ORDER BY id ASC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_provider(name: str, base_url: str, api_key: str, model: str) -> int:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "INSERT INTO providers (name, base_url, api_key, model) VALUES (?, ?, ?, ?)",
            (name, base_url, api_key, model)
        )
        await db.commit()
        return cursor.lastrowid


async def update_provider(provider_id: int, **kwargs) -> None:
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [provider_id]
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            f"UPDATE providers SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals
        )
        await db.commit()


async def delete_provider(provider_id: int) -> None:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        await db.commit()


async def set_default_provider(provider_id: int) -> None:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("UPDATE providers SET is_default = 0")
        await db.execute(
            "UPDATE providers SET is_default = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (provider_id,),
        )
        await db.commit()
