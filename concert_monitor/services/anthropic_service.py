"""Anthropic Claude integration for AI-powered features."""

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AnthropicConfig:
    """Anthropic API configuration."""
    api_key: str
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024


class AnthropicService:
    """
    Service for AI-powered features using Claude.

    Used for:
    - Extracting preferences from natural conversation
    - Generating personalized event descriptions
    - Smart matching explanations
    """

    def __init__(self, config: Optional[AnthropicConfig] = None):
        self.config = config
        self._client = None

    def _get_client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None and self.config:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.config.api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
        return self._client

    async def extract_preferences_from_conversation(
        self,
        messages: list[dict],
    ) -> dict:
        """
        Extract music preferences from a conversation.

        Uses Claude to understand natural language descriptions of
        music taste and extract structured preferences.

        Args:
            messages: List of conversation messages with 'role' and 'content'

        Returns:
            Structured preferences dict with artists, genres, dislikes
        """
        client = self._get_client()
        if not client:
            return self._fallback_extraction(messages)

        system_prompt = """You are a music preference extraction assistant.
Analyze the conversation and extract the user's music preferences.

Return a JSON object with:
- artists: list of artist names the user likes
- genres: list of music genres the user enjoys
- dislikes: list of artists or genres the user doesn't like
- venues: any venue preferences mentioned
- other_notes: any other relevant preferences

Be thorough but only include what's explicitly stated or strongly implied."""

        try:
            # Format conversation for Claude
            conversation = "\n".join(
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in messages
            )

            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"Extract music preferences from this conversation:\n\n{conversation}\n\nReturn only valid JSON."
                }]
            )

            # Parse JSON from response
            response_text = response.content[0].text
            return json.loads(response_text)

        except Exception as e:
            logger.error(f"Claude preference extraction failed: {e}")
            return self._fallback_extraction(messages)

    async def generate_event_recommendation_text(
        self,
        event: dict,
        rating: dict,
        user_preferences: dict,
    ) -> str:
        """
        Generate a personalized recommendation explanation.

        Creates a natural language explanation of why an event
        was recommended for the user.
        """
        client = self._get_client()
        if not client:
            return rating.get("explanation", "Based on your music preferences.")

        try:
            prompt = f"""Given this event and user preferences, write a brief (2-3 sentences)
personalized explanation of why this event is recommended.

Event: {json.dumps(event)}
Rating: {rating.get('score')}/10
User's top artists: {user_preferences.get('top_artists', [])[:5]}
User's top genres: {user_preferences.get('top_genres', [])[:5]}

Be specific about the match. Mention the artist/genre connection."""

            response = client.messages.create(
                model=self.config.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Claude recommendation text failed: {e}")
            return rating.get("explanation", "Based on your music preferences.")

    async def analyze_artist_similarity(
        self,
        artist_name: str,
        user_top_artists: list[str],
    ) -> tuple[float, str]:
        """
        Analyze how similar an artist is to user's favorites.

        Returns a similarity score (0-1) and explanation.
        """
        client = self._get_client()
        if not client:
            return 0.5, "Unable to analyze similarity"

        try:
            prompt = f"""Rate how likely someone who loves these artists would enjoy {artist_name}:
{', '.join(user_top_artists[:10])}

Return JSON with:
- score: 0.0 to 1.0 (1.0 = perfect match)
- reason: brief explanation (1 sentence)

Consider genre, style, era, and typical fan overlap."""

            response = client.messages.create(
                model=self.config.model,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )

            result = json.loads(response.content[0].text)
            return result.get("score", 0.5), result.get("reason", "")

        except Exception as e:
            logger.error(f"Claude artist similarity failed: {e}")
            return 0.5, "Unable to analyze similarity"

    def _fallback_extraction(self, messages: list[dict]) -> dict:
        """
        Fallback preference extraction without LLM.

        Uses simple keyword matching.
        """
        from ..agents.preference_agent import ConversationPreferenceExtractor

        extractor = ConversationPreferenceExtractor()
        return extractor.extract_from_messages(messages)
