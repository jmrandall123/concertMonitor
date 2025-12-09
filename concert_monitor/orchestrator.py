"""
Main orchestrator for the concert monitor agent system.

Coordinates all agents to:
1. Load/update user preferences
2. Discover events from multiple sources
3. Rate events based on preferences
4. Add high-rated events to calendar
5. Generate and send email digests
6. Process feedback for preference learning
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from .agents.base import AgentContext
from .agents.preference_agent import PreferenceAgent
from .agents.rating_agent import RatingAgent
from .agents.calendar_agent import CalendarAgent
from .agents.digest_agent import DigestAgent, DigestScheduler
from .agents.feedback_agent import FeedbackAgent
from .agents.discovery import (
    TicketmasterDiscoveryAgent,
    BandsintownDiscoveryAgent,
    SeatGeekDiscoveryAgent,
)
from .models.event import Event
from .models.preference import PreferenceProfile
from .models.rating import EventRating
from .models.user import User

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""
    # API Keys
    ticketmaster_api_key: Optional[str] = None
    seatgeek_client_id: Optional[str] = None
    seatgeek_client_secret: Optional[str] = None

    # Scheduling
    discovery_interval_hours: int = 6
    digest_check_interval_minutes: int = 60

    # Thresholds
    default_auto_add_threshold: float = 8.0
    default_digest_threshold: float = 7.0

    # Discovery settings
    discovery_days_ahead: int = 90
    max_events_per_source: int = 100


@dataclass
class OrchestratorState:
    """Current state of the orchestrator."""
    last_discovery: Optional[datetime] = None
    last_digest_check: Optional[datetime] = None
    events_cache: dict[UUID, Event] = field(default_factory=dict)
    ratings_cache: dict[tuple[UUID, UUID], EventRating] = field(default_factory=dict)


class ConcertMonitorOrchestrator:
    """
    Main orchestrator that coordinates all agents.

    This is the central controller that:
    - Runs periodic discovery tasks
    - Coordinates rating and calendar operations
    - Manages digest scheduling
    - Processes feedback loops
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        self.state = OrchestratorState()

        # Initialize agents
        self.preference_agent = PreferenceAgent()
        self.rating_agent = RatingAgent()
        self.calendar_agent = CalendarAgent()
        self.digest_agent = DigestAgent()
        self.feedback_agent = FeedbackAgent()

        # Discovery agents
        self.discovery_agents = [
            TicketmasterDiscoveryAgent(self.config.ticketmaster_api_key),
            BandsintownDiscoveryAgent(),
            SeatGeekDiscoveryAgent(
                self.config.seatgeek_client_id,
                self.config.seatgeek_client_secret,
            ),
        ]

    async def run_full_pipeline(
        self,
        user: User,
        preference_profile: PreferenceProfile,
    ) -> dict:
        """
        Run the complete pipeline for a user.

        1. Discover events
        2. Rate events
        3. Add high-rated to calendar
        4. Generate digest if needed
        """
        results = {
            "user_id": str(user.id),
            "timestamp": datetime.utcnow().isoformat(),
            "discovery": None,
            "rating": None,
            "calendar": None,
            "digest": None,
        }

        # 1. Discover events
        logger.info(f"Starting discovery for user {user.id}")
        events = await self.discover_events(user, preference_profile)
        results["discovery"] = {
            "events_found": len(events),
            "sources": list(set(e.source.value for e in events)),
        }
        logger.info(f"Discovered {len(events)} events")

        if not events:
            return results

        # 2. Rate events
        logger.info("Rating events...")
        ratings = await self.rate_events(events, user, preference_profile)
        results["rating"] = {
            "events_rated": len(ratings),
            "must_see": len([r for r in ratings if r.score >= 8]),
            "recommended": len([r for r in ratings if 7 <= r.score < 8]),
        }
        logger.info(
            f"Rated {len(ratings)} events, "
            f"{results['rating']['must_see']} must-see"
        )

        # 3. Add to calendar
        logger.info("Adding high-rated events to calendar...")
        calendar_result = await self.add_to_calendar(events, ratings, user)
        results["calendar"] = calendar_result.to_dict()
        logger.info(f"Added {calendar_result.total_added} events to calendar")

        # 4. Check if digest should be sent
        if DigestScheduler.should_send_digest(user):
            logger.info("Generating digest...")
            digest_result = await self.send_digest(events, ratings, user)
            results["digest"] = {
                "sent": digest_result.email_sent,
                "events_included": digest_result.events_included,
            }

        return results

    async def discover_events(
        self,
        user: User,
        profile: PreferenceProfile,
    ) -> list[Event]:
        """
        Discover events from all sources.

        Runs discovery agents in parallel for efficiency.
        """
        # Get combined preferences for artist searches
        combined = profile.get_combined_preferences()
        top_artists = combined.top_artist_names(20)

        # Build discovery context
        locations = []
        if user.preferences and user.preferences.locations:
            loc = user.preferences.locations[0]
            locations = [{
                "city": loc.city,
                "state": loc.state,
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "radius_miles": loc.radius_miles,
            }]

        # Build input data for discovery
        input_data = {
            "artists": top_artists,
            "start_date": datetime.now(),
            "end_date": datetime.now() + timedelta(
                days=self.config.discovery_days_ahead
            ),
            "limit": self.config.max_events_per_source,
        }

        # Add location data if available
        if locations:
            input_data.update(locations[0])

        context = AgentContext(
            user_id=user.id,
            input_data=input_data,
            config={
                "ticketmaster_api_key": self.config.ticketmaster_api_key,
                "seatgeek_client_id": self.config.seatgeek_client_id,
            },
        )

        # Run all discovery agents in parallel
        tasks = [agent.run(context) for agent in self.discovery_agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all events
        all_events = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Discovery agent failed: {result}")
                continue
            if result.data and result.data.events:
                all_events.extend(result.data.events)

        # Deduplicate events
        return self._deduplicate_events(all_events)

    async def rate_events(
        self,
        events: list[Event],
        user: User,
        profile: PreferenceProfile,
    ) -> list[EventRating]:
        """Rate all discovered events."""
        context = AgentContext(
            user_id=user.id,
            input_data={
                "events": events,
                "preference_profile": profile,
                "user": user,
            },
        )

        result = await self.rating_agent.run(context)

        if result.data:
            # Cache ratings
            for rating in result.data:
                self.state.ratings_cache[(user.id, rating.event_id)] = rating
            return result.data

        return []

    async def add_to_calendar(
        self,
        events: list[Event],
        ratings: list[EventRating],
        user: User,
    ):
        """Add high-rated events to user's calendar."""
        context = AgentContext(
            user_id=user.id,
            input_data={
                "events": events,
                "ratings": ratings,
                "user": user,
            },
        )

        result = await self.calendar_agent.run(context)
        return result.data

    async def send_digest(
        self,
        events: list[Event],
        ratings: list[EventRating],
        user: User,
    ):
        """Generate and send email digest."""
        context = AgentContext(
            user_id=user.id,
            input_data={
                "events": events,
                "ratings": ratings,
                "user": user,
            },
        )

        result = await self.digest_agent.run(context)
        return result.data

    async def process_feedback(
        self,
        feedback_items: list[dict],
        profile: PreferenceProfile,
    ):
        """Process user feedback to update preferences."""
        context = AgentContext(
            input_data={
                "feedback_items": feedback_items,
                "preference_profile": profile,
            },
        )

        result = await self.feedback_agent.run(context)
        return result.data

    async def onboard_user(
        self,
        user: User,
        spotify_data: Optional[dict] = None,
        apple_data: Optional[dict] = None,
        conversation_data: Optional[dict] = None,
    ) -> PreferenceProfile:
        """
        Onboard a new user by extracting their preferences.

        Can use Spotify Wrapped, Apple Replay, or conversation extraction.
        """
        context = AgentContext(
            user_id=user.id,
            input_data={
                "spotify_data": spotify_data,
                "apple_data": apple_data,
                "conversation_preferences": conversation_data,
            },
        )

        result = await self.preference_agent.run(context)

        if result.data:
            return result.data

        # Return empty profile if extraction failed
        return PreferenceProfile(user_id=user.id)

    def _deduplicate_events(self, events: list[Event]) -> list[Event]:
        """Remove duplicate events across sources."""
        seen = {}

        for event in events:
            # Create a key based on artist + date + venue
            key_parts = []

            if event.headliner:
                key_parts.append(event.headliner.lower())
            elif event.artists:
                key_parts.append(event.artists[0].name.lower())

            if event.event_date:
                key_parts.append(event.event_date.strftime("%Y-%m-%d"))

            if event.venue:
                key_parts.append(event.venue.name.lower())

            key = "|".join(key_parts)

            if key and key not in seen:
                seen[key] = event
                # Cache the event
                self.state.events_cache[event.id] = event

        return list(seen.values())

    async def run_scheduled_tasks(
        self,
        users: list[User],
        profiles: dict[UUID, PreferenceProfile],
    ):
        """
        Run scheduled tasks for all users.

        Called periodically by a scheduler.
        """
        current_time = datetime.utcnow()

        # Check if discovery should run
        should_discover = (
            self.state.last_discovery is None or
            (current_time - self.state.last_discovery).total_seconds() >
            self.config.discovery_interval_hours * 3600
        )

        for user in users:
            profile = profiles.get(user.id)
            if not profile:
                continue

            try:
                if should_discover:
                    await self.run_full_pipeline(user, profile)
                elif DigestScheduler.should_send_digest(user, current_time):
                    # Just send digest with cached data
                    events = list(self.state.events_cache.values())
                    ratings = [
                        r for (uid, _), r in self.state.ratings_cache.items()
                        if uid == user.id
                    ]
                    await self.send_digest(events, ratings, user)

            except Exception as e:
                logger.error(f"Failed to process user {user.id}: {e}")

        if should_discover:
            self.state.last_discovery = current_time
