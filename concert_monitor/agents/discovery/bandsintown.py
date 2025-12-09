"""Bandsintown event discovery agent."""

import logging
from datetime import datetime, timedelta
from typing import Optional
import aiohttp

from .base_discovery import DiscoveryAgent
from ..base import AgentContext
from ...models.event import (
    Event,
    EventSource,
    EventType,
    Venue,
    Artist,
)

logger = logging.getLogger(__name__)


class BandsintownDiscoveryAgent(DiscoveryAgent):
    """
    Discovery agent for Bandsintown API.

    Specializes in artist-centric event discovery.
    """

    BASE_URL = "https://rest.bandsintown.com"

    def __init__(self, app_id: Optional[str] = None):
        self.app_id = app_id or "concert_monitor"

    @property
    def name(self) -> str:
        return "bandsintown_discovery"

    @property
    def source(self) -> EventSource:
        return EventSource.BANDSINTOWN

    @property
    def description(self) -> str:
        return "Discovers concerts from Bandsintown, best for tracking specific artists"

    def validate(self, context: AgentContext) -> Optional[str]:
        """Bandsintown works best with artist names."""
        if not context.input_data.get("artists"):
            return "Bandsintown requires artist names to search"
        return None

    async def search_events(self, context: AgentContext) -> list[Event]:
        """Search Bandsintown for artist events."""
        input_data = context.input_data
        events = []

        artists = input_data.get("artists", [])
        if not artists:
            return events

        # Search for each artist
        for artist_name in artists[:20]:  # Limit to prevent rate limiting
            artist_events = await self._get_artist_events(
                artist_name,
                context
            )
            events.extend(artist_events)

        return events

    async def _get_artist_events(
        self,
        artist_name: str,
        context: AgentContext
    ) -> list[Event]:
        """Get upcoming events for an artist."""
        events = []
        input_data = context.input_data

        try:
            # URL encode artist name
            encoded_artist = artist_name.replace(" ", "%20")

            async with aiohttp.ClientSession() as session:
                url = f"{self.BASE_URL}/artists/{encoded_artist}/events"
                params = {
                    "app_id": self.app_id,
                    "date": "upcoming",
                }

                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.debug(f"No events found for {artist_name}")
                        return events

                    data = await resp.json()

                    if isinstance(data, dict) and data.get("errorMessage"):
                        return events

                    # Filter by location if specified
                    target_city = input_data.get("city", "").lower()
                    target_state = input_data.get("state", "").lower()
                    radius = input_data.get("radius_miles", 100)

                    for raw in data:
                        event = self._parse_event(raw, artist_name)
                        if event:
                            # Apply location filter
                            if target_city and event.venue:
                                if target_city not in event.venue.city.lower():
                                    continue
                            events.append(event)

        except Exception as e:
            logger.error(f"Bandsintown search failed for {artist_name}: {e}")

        return events

    def _parse_event(self, raw: dict, artist_name: str) -> Optional[Event]:
        """Parse Bandsintown event response."""
        try:
            # Extract venue
            venue_data = raw.get("venue", {})
            venue = Venue(
                name=venue_data.get("name", ""),
                city=venue_data.get("city", ""),
                state=venue_data.get("region"),
                country=venue_data.get("country", "US"),
                latitude=float(venue_data.get("latitude", 0)) or None,
                longitude=float(venue_data.get("longitude", 0)) or None,
            )

            # Extract date
            event_date = None
            if raw.get("datetime"):
                event_date = datetime.fromisoformat(
                    raw["datetime"].replace("Z", "+00:00")
                )

            # Create artist
            artist = Artist(name=artist_name)
            if raw.get("artist"):
                artist_data = raw["artist"]
                artist = Artist(
                    name=artist_data.get("name", artist_name),
                    image_url=artist_data.get("thumb_url"),
                )

            # Build description from lineup
            lineup = raw.get("lineup", [])
            description = None
            if len(lineup) > 1:
                description = f"With: {', '.join(lineup[1:])}"

            return Event(
                external_id=raw.get("id"),
                source=EventSource.BANDSINTOWN,
                name=f"{artist_name} at {venue.name}",
                description=description,
                event_type=EventType.CONCERT,
                artists=[artist],
                headliner=artist_name,
                venue=venue,
                event_date=event_date,
                ticket_url=raw.get("url"),
                is_sold_out=raw.get("offers", [{}])[0].get("status") == "sold_out"
                if raw.get("offers") else False,
            )

        except Exception as e:
            logger.error(f"Failed to parse Bandsintown event: {e}")
            return None
