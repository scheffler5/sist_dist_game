import time
import logging
import os
from typing import List, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongodb:27017")
DB_NAME = os.environ.get("MONGO_DB", "guessgame")


class Database:
    def __init__(self):
        self._client: AsyncIOMotorClient = None
        self._db = None

    async def connect(self):
        try:
            self._client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            self._db = self._client[DB_NAME]
            await self._client.admin.command("ping")
            logger.info(f"MongoDB conectado em {MONGO_URI}")
            await self._db.chat.create_index([("game_id", 1), ("timestamp", -1)])
        except Exception as e:
            logger.warning(f"MongoDB não disponível: {e}. Chat sem persistência.")
            self._client = None
            self._db = None

    async def save_chat_message(
        self,
        game_id: str,
        player_id: str,
        player_name: str,
        message: str,
    ):
        if self._db is None:
            return

        doc = {
            "game_id": game_id,
            "player_id": player_id,
            "player_name": player_name,
            "message": message,
            "timestamp": int(time.time() * 1000),
        }
        await self._db.chat.insert_one(doc)

    async def get_chat_history(
        self,
        game_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        if self._db is None:
            return []

        cursor = (
            self._db.chat.find(
                {"game_id": game_id},
                {"_id": 0},
            )
            .sort("timestamp", 1)
            .limit(limit)
        )
        return [doc async for doc in cursor]

    async def delete_chat(self, game_id: str) -> int:
        if self._db is None:
            return 0
        result = await self._db.chat.delete_many({"game_id": game_id})
        return result.deleted_count

    async def close(self):
        if self._client:
            self._client.close()


db = Database()
