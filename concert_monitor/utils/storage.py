"""Storage utilities for persisting data."""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class Storage(ABC):
    """Abstract base class for storage implementations."""

    @abstractmethod
    async def save(self, key: str, data: Any) -> bool:
        """Save data with given key."""
        pass

    @abstractmethod
    async def load(self, key: str) -> Optional[Any]:
        """Load data by key."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete data by key."""
        pass

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys with optional prefix filter."""
        pass


class JSONFileStorage(Storage):
    """
    Simple JSON file-based storage.

    Good for development and small-scale deployments.
    """

    def __init__(self, base_path: str = "./data"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        """Get file path for a key."""
        # Sanitize key for filesystem
        safe_key = key.replace("/", "_").replace("\\", "_")
        return self.base_path / f"{safe_key}.json"

    async def save(self, key: str, data: Any) -> bool:
        """Save data to JSON file."""
        try:
            path = self._get_path(key)

            # Convert data to JSON-serializable format
            serializable = self._make_serializable(data)

            with open(path, "w") as f:
                json.dump(serializable, f, indent=2, default=str)

            return True
        except Exception as e:
            logger.error(f"Failed to save {key}: {e}")
            return False

    async def load(self, key: str) -> Optional[Any]:
        """Load data from JSON file."""
        try:
            path = self._get_path(key)

            if not path.exists():
                return None

            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {key}: {e}")
            return None

    async def delete(self, key: str) -> bool:
        """Delete JSON file."""
        try:
            path = self._get_path(key)

            if path.exists():
                path.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to delete {key}: {e}")
            return False

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys (file names without .json)."""
        try:
            keys = []
            for path in self.base_path.glob("*.json"):
                key = path.stem
                if not prefix or key.startswith(prefix):
                    keys.append(key)
            return keys
        except Exception as e:
            logger.error(f"Failed to list keys: {e}")
            return []

    def _make_serializable(self, obj: Any) -> Any:
        """Convert object to JSON-serializable format."""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, "to_dict"):
            return obj.to_dict()
        elif hasattr(obj, "__dict__"):
            return self._make_serializable(obj.__dict__)
        return obj


class UserDataStore:
    """
    High-level store for user data.

    Handles users, preferences, ratings, and feedback.
    """

    def __init__(self, storage: Storage):
        self.storage = storage

    async def save_user(self, user: "User") -> bool:
        """Save user data."""
        return await self.storage.save(f"user_{user.id}", user.to_dict())

    async def load_user(self, user_id: UUID) -> Optional[dict]:
        """Load user data."""
        return await self.storage.load(f"user_{user_id}")

    async def save_preferences(
        self,
        user_id: UUID,
        preferences: "PreferenceProfile"
    ) -> bool:
        """Save user preferences."""
        data = {
            "user_id": str(user_id),
            "spotify": preferences.spotify_preferences.__dict__ if preferences.spotify_preferences else None,
            "apple": preferences.apple_preferences.__dict__ if preferences.apple_preferences else None,
            "stated_artists": preferences.stated_artists,
            "stated_genres": preferences.stated_genres,
            "stated_dislikes": preferences.stated_dislikes,
            "updated_at": datetime.utcnow().isoformat(),
        }
        return await self.storage.save(f"preferences_{user_id}", data)

    async def load_preferences(self, user_id: UUID) -> Optional[dict]:
        """Load user preferences."""
        return await self.storage.load(f"preferences_{user_id}")

    async def save_ratings(
        self,
        user_id: UUID,
        ratings: list["EventRating"]
    ) -> bool:
        """Save event ratings for user."""
        data = {
            "user_id": str(user_id),
            "ratings": [r.to_dict() for r in ratings],
            "updated_at": datetime.utcnow().isoformat(),
        }
        return await self.storage.save(f"ratings_{user_id}", data)

    async def load_ratings(self, user_id: UUID) -> Optional[dict]:
        """Load event ratings for user."""
        return await self.storage.load(f"ratings_{user_id}")

    async def save_feedback(
        self,
        user_id: UUID,
        event_id: UUID,
        feedback: str
    ) -> bool:
        """Save user feedback for an event."""
        data = {
            "user_id": str(user_id),
            "event_id": str(event_id),
            "feedback": feedback,
            "timestamp": datetime.utcnow().isoformat(),
        }
        key = f"feedback_{user_id}_{event_id}"
        return await self.storage.save(key, data)

    async def list_users(self) -> list[str]:
        """List all user IDs."""
        keys = await self.storage.list_keys("user_")
        return [k.replace("user_", "") for k in keys]
