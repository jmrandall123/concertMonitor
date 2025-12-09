"""Preference extraction and management agent."""

import json
import logging
from typing import Optional
from uuid import UUID

from .base import Agent, AgentContext, AgentResult
from ..models.preference import (
    MusicPreference,
    ArtistPreference,
    GenrePreference,
    PreferenceProfile,
)
from ..services.spotify import SpotifyService
from ..services.apple_music import AppleMusicService

logger = logging.getLogger(__name__)


class PreferenceAgent(Agent[PreferenceProfile]):
    """
    Zero-state agent for extracting and managing user preferences.

    Handles:
    - Parsing Spotify Wrapped / streaming history
    - Parsing Apple Music Replay
    - Extracting preferences from conversation
    - Combining preferences from multiple sources
    """

    @property
    def name(self) -> str:
        return "preference_agent"

    @property
    def description(self) -> str:
        return "Extracts and combines user music preferences from various sources"

    def __init__(self):
        self.spotify_service = SpotifyService()
        self.apple_service = AppleMusicService()

    def validate(self, context: AgentContext) -> Optional[str]:
        """Validate that we have at least one preference source."""
        input_data = context.input_data

        has_spotify = bool(input_data.get("spotify_data"))
        has_apple = bool(input_data.get("apple_data"))
        has_conversation = bool(input_data.get("conversation_preferences"))
        has_existing = bool(input_data.get("existing_profile"))

        if not any([has_spotify, has_apple, has_conversation, has_existing]):
            return "At least one preference source required"

        if not context.user_id:
            return "user_id is required"

        return None

    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[PreferenceProfile]
    ) -> AgentResult[PreferenceProfile]:
        """Extract and combine preferences from all sources."""
        input_data = context.input_data
        user_id = context.user_id

        # Initialize or load existing profile
        existing = input_data.get("existing_profile")
        if existing and isinstance(existing, PreferenceProfile):
            profile = existing
        else:
            profile = PreferenceProfile(user_id=user_id)

        result.add_trace("Initialized preference profile")
        items_processed = 0

        # Process Spotify data
        spotify_data = input_data.get("spotify_data")
        if spotify_data:
            try:
                spotify_prefs = self._parse_spotify_data(spotify_data)
                profile.spotify_preferences = spotify_prefs
                items_processed += len(spotify_prefs.top_artists)
                result.add_trace(
                    f"Parsed Spotify data: {len(spotify_prefs.top_artists)} artists, "
                    f"{len(spotify_prefs.genres)} genres"
                )
            except Exception as e:
                logger.error(f"Failed to parse Spotify data: {e}")
                result.add_trace(f"Spotify parsing failed: {e}")

        # Process Apple Music data
        apple_data = input_data.get("apple_data")
        if apple_data:
            try:
                apple_prefs = self._parse_apple_data(apple_data)
                profile.apple_preferences = apple_prefs
                items_processed += len(apple_prefs.top_artists)
                result.add_trace(
                    f"Parsed Apple data: {len(apple_prefs.top_artists)} artists, "
                    f"{len(apple_prefs.genres)} genres"
                )
            except Exception as e:
                logger.error(f"Failed to parse Apple data: {e}")
                result.add_trace(f"Apple parsing failed: {e}")

        # Process conversation preferences
        conv_prefs = input_data.get("conversation_preferences")
        if conv_prefs:
            try:
                stated = self._extract_conversation_preferences(conv_prefs)
                profile.stated_artists.extend(stated.get("artists", []))
                profile.stated_genres.extend(stated.get("genres", []))
                profile.stated_dislikes.extend(stated.get("dislikes", []))
                items_processed += len(stated.get("artists", []))
                result.add_trace(
                    f"Extracted conversation preferences: "
                    f"{len(stated.get('artists', []))} artists, "
                    f"{len(stated.get('genres', []))} genres"
                )
            except Exception as e:
                logger.error(f"Failed to parse conversation: {e}")
                result.add_trace(f"Conversation parsing failed: {e}")

        return result.success(profile, items_processed)

    def _parse_spotify_data(self, data: dict | str) -> MusicPreference:
        """Parse Spotify data from various formats."""
        if isinstance(data, str):
            # Try to parse as JSON
            return self.spotify_service.parse_wrapped_data(data)

        # Direct dictionary format
        if "streamingHistory" in data or "streaming_history" in data:
            history = data.get("streamingHistory") or data.get("streaming_history")
            return self.spotify_service.parse_streaming_history(json.dumps(history))

        # Wrapped format
        return self.spotify_service.parse_wrapped_data(json.dumps(data))

    def _parse_apple_data(self, data: dict | str) -> MusicPreference:
        """Parse Apple Music data from various formats."""
        if isinstance(data, str):
            # Check if it's XML (library export)
            if data.strip().startswith("<?xml"):
                return self.apple_service.parse_library_export(data)
            # Otherwise treat as JSON
            return self.apple_service.parse_replay_data(data)

        return self.apple_service.parse_replay_data(json.dumps(data))

    def _extract_conversation_preferences(
        self,
        conversation: dict | str
    ) -> dict:
        """
        Extract preferences from conversation with user.

        Expected format:
        {
            "messages": [...],
            "extracted": {
                "artists": [...],
                "genres": [...],
                "dislikes": [...]
            }
        }

        Or just the extracted portion directly.
        """
        if isinstance(conversation, str):
            try:
                conversation = json.loads(conversation)
            except json.JSONDecodeError:
                return {"artists": [], "genres": [], "dislikes": []}

        # If it has extracted section, use that
        if "extracted" in conversation:
            return conversation["extracted"]

        # If it's the raw extraction
        return {
            "artists": conversation.get("artists", []),
            "genres": conversation.get("genres", []),
            "dislikes": conversation.get("dislikes", []),
        }


class ConversationPreferenceExtractor:
    """
    Extracts music preferences from natural language conversation.

    This uses pattern matching and could be enhanced with LLM integration.
    """

    # Common genre keywords
    GENRE_KEYWORDS = {
        "rock", "pop", "hip-hop", "hip hop", "rap", "r&b", "rnb",
        "country", "jazz", "blues", "electronic", "edm", "house",
        "techno", "classical", "metal", "punk", "indie", "alternative",
        "folk", "soul", "funk", "reggae", "latin", "k-pop", "kpop",
    }

    # Positive indicators
    POSITIVE_PATTERNS = [
        "i like", "i love", "i enjoy", "fan of", "into",
        "favorite", "favourite", "listen to", "really into",
    ]

    # Negative indicators
    NEGATIVE_PATTERNS = [
        "don't like", "hate", "can't stand", "not into",
        "dislike", "not a fan", "avoid",
    ]

    def extract_from_text(self, text: str) -> dict:
        """Extract preferences from free-form text."""
        text_lower = text.lower()

        artists = []
        genres = []
        dislikes = []

        # Find genres mentioned positively
        for genre in self.GENRE_KEYWORDS:
            for pattern in self.POSITIVE_PATTERNS:
                if f"{pattern} {genre}" in text_lower:
                    genres.append(genre)
                    break

            for pattern in self.NEGATIVE_PATTERNS:
                if f"{pattern} {genre}" in text_lower:
                    dislikes.append(genre)
                    break

        # This is a simplified extraction
        # In production, would use NER or LLM for artist extraction

        return {
            "artists": list(set(artists)),
            "genres": list(set(genres)),
            "dislikes": list(set(dislikes)),
        }

    def extract_from_messages(self, messages: list[dict]) -> dict:
        """Extract preferences from conversation messages."""
        combined_text = " ".join(
            msg.get("content", "") for msg in messages
            if msg.get("role") == "user"
        )
        return self.extract_from_text(combined_text)
