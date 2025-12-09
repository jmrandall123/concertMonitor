"""SeatGeek event discovery agent."""

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
    PriceRange,
)

logger = logging.getLogger(__name__)


class SeatGeekDiscoveryAgent(DiscoveryAgent):
    """
    Discovery agent for SeatGeek API.

    Good for finding events with price information.
    """

    BASE_URL = "https://api.seatgeek.com/2"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None
    ):
        self.client_id = client_id
        self.client_secret = client_secret

    @property
    def name(self) -> str:
        return "seatgeek_discovery"

    @property
    def source(self) -> EventSource:
        return EventSource.SEATGEEK

    @property
    def description(self) -> str:
        return "Discovers events from SeatGeek with price comparisons"

    async def search_events(self, context: AgentContext) -> list[Event]:
        """Search SeatGeek for events."""
        client_id = self.client_id or context.config.get("seatgeek_client_id")

        if not client_id:
            logger.warning("No SeatGeek client ID configured")
            return []

        input_data = context.input_data
        events = []

        # Build search parameters
        params = {
            "client_id": client_id,
            "per_page": input_data.get("limit", 50),
            "type": "concert",
            "sort": "datetime_local.asc",
        }

        if self.client_secret or context.config.get("seatgeek_client_secret"):
            params["client_secret"] = (
                self.client_secret or context.config.get("seatgeek_client_secret")
            )

        # Location parameters
        if input_data.get("latitude") and input_data.get("longitude"):
            params["lat"] = input_data["latitude"]
            params["lon"] = input_data["longitude"]
            params["range"] = f"{input_data.get('radius_miles', 50)}mi"
        elif input_data.get("city"):
            # Use venue.city filter
            params["venue.city"] = input_data["city"]
            if input_data.get("state"):
                params["venue.state"] = input_data["state"]

        # Date range
        start_date = input_data.get("start_date", datetime.now())
        end_date = input_data.get("end_date", datetime.now() + timedelta(days=90))

        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date)

        params["datetime_local.gte"] = start_date.strftime("%Y-%m-%dT%H:%M:%S")
        params["datetime_local.lte"] = end_date.strftime("%Y-%m-%dT%H:%M:%S")

        # Artist filter (SeatGeek calls them "performers")
        if input_data.get("artists"):
            # Search for specific artists
            for artist_name in input_data["artists"][:5]:
                artist_events = await self._search_by_performer(
                    artist_name, params.copy(), client_id
                )
                events.extend(artist_events)
        else:
            # General concert search
            events = await self._do_search(params)

        return self._deduplicate_events(events)

    async def _search_by_performer(
        self,
        performer: str,
        params: dict,
        client_id: str
    ) -> list[Event]:
        """Search for events by performer name."""
        params["performers.slug"] = performer.lower().replace(" ", "-")

        # Also try with q parameter for broader match
        if not await self._do_search(params):
            params.pop("performers.slug", None)
            params["q"] = performer

        return await self._do_search(params)

    async def _do_search(self, params: dict) -> list[Event]:
        """Execute SeatGeek API search."""
        events = []

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.BASE_URL}/events"
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"SeatGeek API error: {resp.status}")
                        return events

                    data = await resp.json()

                    for raw in data.get("events", []):
                        event = self._parse_event(raw)
                        if event:
                            events.append(event)

        except Exception as e:
            logger.error(f"SeatGeek search failed: {e}")

        return events

    def _parse_event(self, raw: dict) -> Optional[Event]:
        """Parse SeatGeek event response."""
        try:
            # Extract venue
            venue_data = raw.get("venue", {})
            venue = Venue(
                name=venue_data.get("name", ""),
                city=venue_data.get("city", ""),
                state=venue_data.get("state"),
                country=venue_data.get("country", "US"),
                address=venue_data.get("address"),
                latitude=venue_data.get("location", {}).get("lat"),
                longitude=venue_data.get("location", {}).get("lon"),
                capacity=venue_data.get("capacity"),
            )

            # Extract performers (artists)
            artists = []
            for p in raw.get("performers", []):
                genres = []
                if p.get("genres"):
                    genres = [g.get("name", "") for g in p["genres"]]

                artist = Artist(
                    name=p.get("name", ""),
                    genres=genres,
                    image_url=p.get("image"),
                    popularity=p.get("score"),  # SeatGeek popularity score
                )
                artists.append(artist)

            # Extract price info
            price_range = None
            stats = raw.get("stats", {})
            if stats.get("lowest_price") or stats.get("highest_price"):
                price_range = PriceRange(
                    min_price=stats.get("lowest_price") or 0,
                    max_price=stats.get("highest_price") or stats.get("lowest_price") or 0,
                )

            # Extract date
            event_date = None
            if raw.get("datetime_local"):
                event_date = datetime.fromisoformat(raw["datetime_local"])

            # Determine event type
            event_type = EventType.CONCERT
            if raw.get("type") == "festival":
                event_type = EventType.FESTIVAL
            elif raw.get("type") == "theater":
                event_type = EventType.THEATER

            return Event(
                external_id=str(raw.get("id")),
                source=EventSource.SEATGEEK,
                name=raw.get("title", raw.get("short_title", "")),
                event_type=event_type,
                artists=artists,
                headliner=artists[0].name if artists else None,
                venue=venue,
                event_date=event_date,
                ticket_url=raw.get("url"),
                price_range=price_range,
                image_url=raw.get("performers", [{}])[0].get("image"),
                genres=list(set(g for a in artists for g in a.genres)),
            )

        except Exception as e:
            logger.error(f"Failed to parse SeatGeek event: {e}")
            return None

    def _deduplicate_events(self, events: list[Event]) -> list[Event]:
        """Remove duplicate events."""
        seen = set()
        unique = []
        for event in events:
            key = event.external_id or f"{event.name}_{event.event_date}"
            if key not in seen:
                seen.add(key)
                unique.append(event)
        return unique
