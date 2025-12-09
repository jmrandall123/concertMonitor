"""Email digest generation agent."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from .base import Agent, AgentContext, AgentResult
from ..models.event import Event
from ..models.rating import EventRating
from ..models.user import User
from ..services.email_service import (
    EmailService,
    EmailMessage,
    DigestEmailBuilder,
)

logger = logging.getLogger(__name__)


@dataclass
class DigestResult:
    """Result of digest generation and sending."""
    user_id: UUID
    email_sent: bool = False
    events_included: int = 0
    must_see_count: int = 0
    recommended_count: int = 0
    might_enjoy_count: int = 0
    error: Optional[str] = None


class DigestAgent(Agent[DigestResult]):
    """
    Zero-state agent for generating and sending email digests.

    Creates personalized digests with:
    - Must See events (8+)
    - Recommended events (7-7.9)
    - Might Enjoy events (5-6.9)
    """

    @property
    def name(self) -> str:
        return "digest_agent"

    @property
    def description(self) -> str:
        return "Generates and sends personalized email digests of recommended events"

    def __init__(
        self,
        email_service: Optional[EmailService] = None,
    ):
        self.email_service = email_service or EmailService()
        self.email_builder = DigestEmailBuilder()

    def validate(self, context: AgentContext) -> Optional[str]:
        """Validate digest generation inputs."""
        if not context.input_data.get("user"):
            return "User information required for digest"
        if not context.input_data.get("events"):
            return "No events provided for digest"
        return None

    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[DigestResult]
    ) -> AgentResult[DigestResult]:
        """Generate and send digest email."""
        input_data = context.input_data

        user: User = input_data["user"]
        events: list[Event] = input_data["events"]
        ratings: list[EventRating] = input_data.get("ratings", [])

        digest_result = DigestResult(user_id=user.id)

        # Build rating lookup
        rating_map = {r.event_id: r for r in ratings}

        # Get threshold from user preferences
        digest_threshold = 7.0
        if user.preferences:
            digest_threshold = user.preferences.digest_threshold

        # Categorize events
        must_see = []
        recommended = []
        might_enjoy = []

        for event in events:
            rating = rating_map.get(event.id)
            if not rating:
                continue

            if rating.score < digest_threshold - 2:
                continue  # Skip low-rated events

            event_data = self._event_to_digest_format(event, rating)

            if rating.score >= 8.0:
                must_see.append(event_data)
                rating.included_in_digest = True
            elif rating.score >= 7.0:
                recommended.append(event_data)
                rating.included_in_digest = True
            elif rating.score >= 5.0:
                might_enjoy.append(event_data)

        # Skip if no events to show
        total_events = len(must_see) + len(recommended) + len(might_enjoy)
        if total_events == 0:
            result.add_trace("No events meet digest threshold")
            digest_result.events_included = 0
            return result.success(digest_result, 0)

        digest_result.must_see_count = len(must_see)
        digest_result.recommended_count = len(recommended)
        digest_result.might_enjoy_count = len(might_enjoy)
        digest_result.events_included = total_events

        # Determine period label
        period = self._get_period_label(user)

        # Build email content
        html_content = self.email_builder.build_digest(
            user_name=user.name or "there",
            must_see_events=must_see,
            recommended_events=recommended,
            might_enjoy_events=might_enjoy,
            period=period,
        )

        all_events = must_see + recommended + might_enjoy
        plain_content = self.email_builder.build_plain_text(
            user_name=user.name or "there",
            events=all_events,
            period=period,
        )

        # Create and send email
        email = EmailMessage(
            to_email=user.email,
            subject=f"🎵 Your Concert Digest: {len(must_see)} must-see events!",
            html_content=html_content,
            plain_content=plain_content,
        )

        try:
            sent = await self.email_service.send_email(email)
            digest_result.email_sent = sent

            if sent:
                result.add_trace(
                    f"Sent digest to {user.email} with {total_events} events"
                )
            else:
                digest_result.error = "Email sending failed"
                result.add_trace("Failed to send digest email")

        except Exception as e:
            logger.error(f"Digest email failed: {e}")
            digest_result.error = str(e)
            result.add_trace(f"Email error: {e}")

        return result.success(digest_result, digest_result.events_included)

    def _event_to_digest_format(
        self,
        event: Event,
        rating: EventRating,
    ) -> dict:
        """Convert event and rating to digest format."""
        return {
            "id": str(event.id),
            "name": event.name,
            "date": event.date_str,
            "location": event.location_str,
            "price": event.price_range.display if event.price_range else None,
            "ticket_url": event.ticket_url,
            "rating": rating.score,
            "explanation": rating.explanation,
            "tier": rating.recommendation_tier,
            "image_url": event.image_url,
        }

    def _get_period_label(self, user: User) -> str:
        """Get the period label for the digest."""
        frequency = "weekly"
        if user.preferences:
            frequency = user.preferences.email_digest_frequency

        if frequency == "daily":
            return "Today"
        elif frequency == "weekly":
            return "This Week"
        elif frequency == "monthly":
            return "This Month"
        return "Upcoming"


class DigestScheduler:
    """
    Scheduler for digest emails.

    Determines when users should receive their digests based on preferences.
    """

    @staticmethod
    def should_send_digest(
        user: User,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """Check if user should receive digest now."""
        current_time = current_time or datetime.utcnow()

        if not user.email:
            return False

        frequency = "weekly"
        digest_day = "monday"

        if user.preferences:
            frequency = user.preferences.email_digest_frequency
            digest_day = user.preferences.digest_day

        # Check frequency
        if frequency == "daily":
            # Send daily at 9 AM
            return current_time.hour == 9

        elif frequency == "weekly":
            # Send on specified day at 9 AM
            current_day = current_time.strftime("%A").lower()
            return (
                current_day == digest_day.lower() and
                current_time.hour == 9
            )

        elif frequency == "monthly":
            # Send on 1st of month at 9 AM
            return current_time.day == 1 and current_time.hour == 9

        return False

    @staticmethod
    def get_users_for_digest(
        users: list[User],
        current_time: Optional[datetime] = None,
    ) -> list[User]:
        """Get list of users who should receive digest now."""
        return [
            user for user in users
            if DigestScheduler.should_send_digest(user, current_time)
        ]
