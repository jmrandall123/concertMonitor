"""Feedback processing agent for preference learning."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from .base import Agent, AgentContext, AgentResult
from ..models.event import Event
from ..models.preference import PreferenceProfile
from ..models.rating import EventRating
from ..models.user import User, FeedbackType

logger = logging.getLogger(__name__)


@dataclass
class FeedbackResult:
    """Result of processing user feedback."""
    feedback_processed: int = 0
    preferences_updated: bool = False
    artist_adjustments: list[tuple[str, float]] = None  # (artist, adjustment)
    genre_adjustments: list[tuple[str, float]] = None   # (genre, adjustment)

    def __post_init__(self):
        if self.artist_adjustments is None:
            self.artist_adjustments = []
        if self.genre_adjustments is None:
            self.genre_adjustments = []


class FeedbackAgent(Agent[FeedbackResult]):
    """
    Zero-state agent for processing user feedback and updating preferences.

    Handles:
    - Processing yes/no/maybe responses from calendar invites
    - Updating preference scores based on attendance
    - Learning from implicit signals (ticket purchases, etc.)
    """

    @property
    def name(self) -> str:
        return "feedback_agent"

    @property
    def description(self) -> str:
        return "Processes user feedback to improve future recommendations"

    # Adjustment factors for different feedback types
    FEEDBACK_ADJUSTMENTS = {
        FeedbackType.YES: 0.15,
        FeedbackType.NO: -0.10,
        FeedbackType.MAYBE: 0.03,
        FeedbackType.NO_RESPONSE: 0.0,
    }

    def validate(self, context: AgentContext) -> Optional[str]:
        """Validate feedback processing inputs."""
        if not context.input_data.get("feedback_items"):
            return "No feedback items provided"
        if not context.input_data.get("preference_profile"):
            return "No preference profile provided"
        return None

    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[FeedbackResult]
    ) -> AgentResult[FeedbackResult]:
        """Process feedback and update preferences."""
        input_data = context.input_data

        feedback_items: list[dict] = input_data["feedback_items"]
        profile: PreferenceProfile = input_data["preference_profile"]

        feedback_result = FeedbackResult()

        for item in feedback_items:
            try:
                adjustment = self._process_feedback_item(item, profile)
                if adjustment:
                    feedback_result.feedback_processed += 1
                    feedback_result.artist_adjustments.extend(
                        adjustment.get("artists", [])
                    )
                    feedback_result.genre_adjustments.extend(
                        adjustment.get("genres", [])
                    )
                    result.add_trace(
                        f"Processed feedback for event {item.get('event_id')}"
                    )
            except Exception as e:
                logger.error(f"Failed to process feedback: {e}")
                result.add_trace(f"Feedback processing error: {e}")

        feedback_result.preferences_updated = feedback_result.feedback_processed > 0

        return result.success(feedback_result, feedback_result.feedback_processed)

    def _process_feedback_item(
        self,
        item: dict,
        profile: PreferenceProfile,
    ) -> Optional[dict]:
        """Process a single feedback item."""
        feedback_type = item.get("feedback")
        if isinstance(feedback_type, str):
            feedback_type = FeedbackType(feedback_type)

        if feedback_type == FeedbackType.NO_RESPONSE:
            return None

        event_data = item.get("event", {})
        artists = event_data.get("artists", [])
        genres = event_data.get("genres", [])

        adjustments = {"artists": [], "genres": []}

        # Get base adjustment for this feedback type
        base_adjustment = self.FEEDBACK_ADJUSTMENTS.get(feedback_type, 0)

        # Update preferences for each artist
        for artist in artists:
            artist_name = artist.get("name") if isinstance(artist, dict) else artist
            if artist_name:
                profile.update_from_feedback(
                    artist_name=artist_name,
                    genres=genres,
                    feedback=feedback_type.value,
                )
                adjustments["artists"].append((artist_name, base_adjustment))

        # Track genre adjustments
        for genre in genres:
            adjustments["genres"].append((genre, base_adjustment * 0.5))

        return adjustments

    async def process_calendar_response(
        self,
        event: Event,
        rating: EventRating,
        response: str,  # "yes", "no", "maybe"
        profile: PreferenceProfile,
    ) -> FeedbackResult:
        """
        Process a calendar invite response.

        This is a convenience method for processing single responses.
        """
        try:
            feedback_type = FeedbackType(response.lower())
        except ValueError:
            feedback_type = FeedbackType.NO_RESPONSE

        # Update the rating record
        rating.user_feedback = feedback_type
        rating.feedback_received_at = datetime.utcnow()

        # Build feedback item
        item = {
            "event_id": str(event.id),
            "feedback": feedback_type,
            "event": {
                "artists": [{"name": a.name} for a in event.artists],
                "genres": event.all_genres,
            }
        }

        # Process it
        adjustment = self._process_feedback_item(item, profile)

        return FeedbackResult(
            feedback_processed=1 if adjustment else 0,
            preferences_updated=adjustment is not None,
            artist_adjustments=adjustment.get("artists", []) if adjustment else [],
            genre_adjustments=adjustment.get("genres", []) if adjustment else [],
        )


class ImplicitFeedbackProcessor:
    """
    Processes implicit feedback signals.

    Implicit signals include:
    - Clicking ticket links
    - Adding events to calendar manually
    - Viewing event details multiple times
    - Time spent on event pages
    """

    # Signal weights
    SIGNAL_WEIGHTS = {
        "ticket_click": 0.05,
        "calendar_add": 0.08,
        "multiple_views": 0.03,
        "share": 0.04,
        "ticket_purchase": 0.15,  # Strongest signal
    }

    def process_signal(
        self,
        signal_type: str,
        event: Event,
        profile: PreferenceProfile,
    ) -> float:
        """
        Process an implicit feedback signal.

        Returns the adjustment applied.
        """
        weight = self.SIGNAL_WEIGHTS.get(signal_type, 0)

        if weight == 0:
            return 0.0

        # Apply positive adjustment to artists and genres
        for artist in event.artists:
            profile.update_from_feedback(
                artist_name=artist.name,
                genres=event.all_genres,
                feedback="yes" if weight > 0.05 else "maybe",
            )

        return weight

    def decay_old_preferences(
        self,
        profile: PreferenceProfile,
        decay_factor: float = 0.95,
    ) -> None:
        """
        Apply decay to old preferences.

        This helps ensure recent taste is weighted more heavily.
        """
        for artist in profile.learned_preferences.top_artists:
            # Decay affinity slightly
            artist.affinity_score *= decay_factor

        for genre in profile.learned_preferences.genres:
            genre.affinity_score *= decay_factor
