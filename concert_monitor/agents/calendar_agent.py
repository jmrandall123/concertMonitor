"""Calendar integration agent."""

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from .base import Agent, AgentContext, AgentResult
from ..models.event import Event
from ..models.rating import EventRating
from ..models.user import User
from ..services.google_calendar import (
    GoogleCalendarService,
    CalendarEvent,
    create_ics_file,
)

logger = logging.getLogger(__name__)


class CalendarAddResult:
    """Result of adding events to calendar."""

    def __init__(self):
        self.added: list[tuple[Event, str]] = []  # (event, calendar_event_id)
        self.failed: list[tuple[Event, str]] = []  # (event, error_message)
        self.skipped: list[tuple[Event, str]] = []  # (event, reason)

    @property
    def total_added(self) -> int:
        return len(self.added)

    @property
    def total_failed(self) -> int:
        return len(self.failed)

    def to_dict(self) -> dict:
        return {
            "added": [
                {"event_name": e.name, "calendar_id": cid}
                for e, cid in self.added
            ],
            "failed": [
                {"event_name": e.name, "error": err}
                for e, err in self.failed
            ],
            "skipped": [
                {"event_name": e.name, "reason": r}
                for e, r in self.skipped
            ],
            "summary": {
                "total_added": self.total_added,
                "total_failed": self.total_failed,
                "total_skipped": len(self.skipped),
            }
        }


class CalendarAgent(Agent[CalendarAddResult]):
    """
    Zero-state agent for managing calendar integrations.

    Handles:
    - Adding high-rated events to user's calendar
    - Creating calendar events with proper details
    - Generating ICS files for email attachments
    - Checking for conflicts
    """

    @property
    def name(self) -> str:
        return "calendar_agent"

    @property
    def description(self) -> str:
        return "Adds recommended events to user's calendar"

    def __init__(self, calendar_service: Optional[GoogleCalendarService] = None):
        self.calendar_service = calendar_service or GoogleCalendarService()

    def validate(self, context: AgentContext) -> Optional[str]:
        """Validate calendar operation inputs."""
        if not context.input_data.get("events") and not context.input_data.get("rated_events"):
            return "No events provided to add to calendar"
        return None

    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[CalendarAddResult]
    ) -> AgentResult[CalendarAddResult]:
        """Add events to calendar based on ratings."""
        input_data = context.input_data

        # Get events and ratings
        events: list[Event] = input_data.get("events", [])
        ratings: list[EventRating] = input_data.get("ratings", [])
        user: Optional[User] = input_data.get("user")

        # Build event-to-rating mapping
        rating_map: dict[UUID, EventRating] = {
            r.event_id: r for r in ratings
        }

        # Get threshold from user preferences or default
        threshold = 8.0
        if user and user.preferences:
            threshold = user.preferences.auto_add_threshold

        add_result = CalendarAddResult()

        for event in events:
            rating = rating_map.get(event.id)

            # Check if event should be auto-added
            if not rating:
                add_result.skipped.append(
                    (event, "No rating available")
                )
                continue

            if rating.score < threshold:
                add_result.skipped.append(
                    (event, f"Rating {rating.score}/10 below threshold {threshold}")
                )
                continue

            if event.is_sold_out:
                add_result.skipped.append(
                    (event, "Event is sold out")
                )
                continue

            # Create calendar event
            try:
                calendar_event = self._create_calendar_event(event, rating)
                calendar_id = await self.calendar_service.create_event(
                    calendar_event,
                    calendar_id=user.calendar_id if user else "primary",
                )

                if calendar_id:
                    add_result.added.append((event, calendar_id))
                    rating.auto_added_to_calendar = True
                    result.add_trace(
                        f"Added '{event.name}' to calendar (rating: {rating.score})"
                    )
                else:
                    add_result.failed.append(
                        (event, "Calendar API returned no event ID")
                    )

            except Exception as e:
                logger.error(f"Failed to add event to calendar: {e}")
                add_result.failed.append((event, str(e)))
                result.add_trace(f"Failed to add '{event.name}': {e}")

        return result.success(add_result, add_result.total_added)

    def _create_calendar_event(
        self,
        event: Event,
        rating: EventRating,
    ) -> CalendarEvent:
        """Create calendar event from concert event."""
        # Determine event times
        start_time = event.event_date or datetime.now() + timedelta(days=7)
        end_time = event.end_time or (start_time + timedelta(hours=3))

        # Build description with rating explanation
        description_parts = []

        # Add rating info
        description_parts.append(
            f"🎯 Match Score: {rating.score}/10 ({rating.recommendation_tier.replace('_', ' ').title()})"
        )
        description_parts.append("")

        # Add why this was recommended
        if rating.explanation:
            description_parts.append("Why this was recommended:")
            description_parts.append(rating.explanation)
            description_parts.append("")

        # Add event details
        description_parts.append(event.to_calendar_description())

        # Add feedback prompt
        description_parts.append("")
        description_parts.append("---")
        description_parts.append(
            "Did you enjoy this event? Reply to update your preferences!"
        )

        return CalendarEvent(
            title=self._format_event_title(event),
            start_time=start_time,
            end_time=end_time,
            location=event.location_str,
            description="\n".join(description_parts),
            event_id=event.id,
            external_event_id=event.external_id,
            ticket_url=event.ticket_url,
            reminder_minutes=[60, 1440, 10080],  # 1 hour, 1 day, 1 week
        )

    def _format_event_title(self, event: Event) -> str:
        """Format calendar event title."""
        if event.headliner:
            return f"🎵 {event.headliner}"
        if event.artists:
            return f"🎵 {event.artists[0].name}"
        return f"🎵 {event.name}"

    async def generate_ics_files(
        self,
        events: list[Event],
        ratings: dict[UUID, EventRating],
    ) -> dict[UUID, str]:
        """Generate ICS file content for events (for email attachments)."""
        ics_files = {}

        for event in events:
            rating = ratings.get(event.id)
            if not rating:
                continue

            calendar_event = self._create_calendar_event(event, rating)
            ics_content = create_ics_file(calendar_event)
            ics_files[event.id] = ics_content

        return ics_files
