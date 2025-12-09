"""Ticketmaster event discovery agent."""

import logging
from datetime import datetime, timedelta
from typing import Optional
import aiohttp

from .base_discovery import DiscoveryAgent, DiscoveryResult
from ..base import AgentContext, AgentResult
from ...models.event import (
    Event,
    EventSource,
    EventType,
    Venue,
    Artist,
    PriceRange,
)

logger = logging.getLogger(__name__)


class TicketmasterDiscoveryAgent(DiscoveryAgent):
    """
    Discovery agent for Ticketmaster API.

    Searches Ticketmaster's Discovery API for concerts and events.
    """

    BASE_URL = "https://app.ticketmaster.com/discovery/v2"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "ticketmaster_discovery"

    @property
    def source(self) -> EventSource:
        return EventSource.TICKETMASTER

    @property
    def description(self) -> str:
        return "Discovers concerts and events from Ticketmaster"

    async def search_events(self, context: AgentContext) -> list[Event]:
        """Search Ticketmaster for events."""
        if not self.api_key:
            self.api_key = context.config.get("ticketmaster_api_key")

        if not self.api_key:
            logger.warning("No Ticketmaster API key configured")
            return []

        input_data = context.input_data
        events = []

        # Build search parameters
        params = {
            "apikey": self.api_key,
            "size": input_data.get("limit", 50),
            "sort": "date,asc",
            "classificationName": "Music",  # Focus on music events
        }

        # Location search
        if input_data.get("latitude") and input_data.get("longitude"):
            params["latlong"] = f"{input_data['latitude']},{input_data['longitude']}"
            params["radius"] = input_data.get("radius_miles", 50)
            params["unit"] = "miles"
        elif input_data.get("city"):
            params["city"] = input_data["city"]
            if input_data.get("state"):
                params["stateCode"] = input_data["state"]

        # Date range
        start_date = input_data.get("start_date", datetime.now())
        end_date = input_data.get("end_date", datetime.now() + timedelta(days=90))

        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date)

        params["startDateTime"] = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["endDateTime"] = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Artist/keyword search
        if input_data.get("artists"):
            # Search for specific artists
            for artist_name in input_data["artists"][:5]:  # Limit to 5 artists
                artist_events = await self._search_by_keyword(
                    artist_name, params.copy()
                )
                events.extend(artist_events)
        else:
            # General search in area
            events = await self._search_by_keyword("", params)

        return self._deduplicate_events(events)

    async def _search_by_keyword(
        self,
        keyword: str,
        params: dict
    ) -> list[Event]:
        """Search Ticketmaster with optional keyword."""
        events = []

        if keyword:
            params["keyword"] = keyword

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.BASE_URL}/events.json"
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Ticketmaster API error: {resp.status}"
                        )
                        return events

                    data = await resp.json()

                    # Parse embedded events
                    embedded = data.get("_embedded", {})
                    raw_events = embedded.get("events", [])

                    for raw in raw_events:
                        event = self._parse_event(raw)
                        if event:
                            events.append(event)

        except Exception as e:
            logger.error(f"Ticketmaster search failed: {e}")

        return events

    def _parse_event(self, raw: dict) -> Optional[Event]:
        """Parse Ticketmaster event response into Event model."""
        try:
            # Extract venue
            venue = None
            venues = raw.get("_embedded", {}).get("venues", [])
            if venues:
                v = venues[0]
                venue = Venue(
                    name=v.get("name", ""),
                    city=v.get("city", {}).get("name", ""),
                    state=v.get("state", {}).get("stateCode"),
                    country=v.get("country", {}).get("countryCode", "US"),
                    address=v.get("address", {}).get("line1"),
                    latitude=float(v.get("location", {}).get("latitude", 0)) or None,
                    longitude=float(v.get("location", {}).get("longitude", 0)) or None,
                )

            # Extract artists
            artists = []
            attractions = raw.get("_embedded", {}).get("attractions", [])
            for a in attractions:
                artist = Artist(
                    name=a.get("name", ""),
                    genres=[
                        c.get("name", "")
                        for c in a.get("classifications", [])
                        if c.get("segment", {}).get("name") == "Music"
                    ],
                )
                artists.append(artist)

            # Extract price range
            price_range = None
            price_ranges = raw.get("priceRanges", [])
            if price_ranges:
                p = price_ranges[0]
                price_range = PriceRange(
                    min_price=p.get("min", 0),
                    max_price=p.get("max", 0),
                    currency=p.get("currency", "USD"),
                )

            # Extract date/time
            dates = raw.get("dates", {})
            start = dates.get("start", {})
            event_date = None
            if start.get("dateTime"):
                event_date = datetime.fromisoformat(
                    start["dateTime"].replace("Z", "+00:00")
                )
            elif start.get("localDate"):
                event_date = datetime.strptime(start["localDate"], "%Y-%m-%d")

            # Extract genres from classifications
            genres = []
            for classification in raw.get("classifications", []):
                if classification.get("genre", {}).get("name"):
                    genres.append(classification["genre"]["name"])
                if classification.get("subGenre", {}).get("name"):
                    genres.append(classification["subGenre"]["name"])

            # Get image
            images = raw.get("images", [])
            image_url = None
            if images:
                # Prefer higher resolution
                sorted_images = sorted(
                    images,
                    key=lambda x: x.get("width", 0),
                    reverse=True
                )
                image_url = sorted_images[0].get("url")

            return Event(
                external_id=raw.get("id"),
                source=EventSource.TICKETMASTER,
                name=raw.get("name", ""),
                event_type=EventType.CONCERT,
                artists=artists,
                headliner=artists[0].name if artists else None,
                venue=venue,
                event_date=event_date,
                ticket_url=raw.get("url"),
                price_range=price_range,
                is_sold_out=dates.get("status", {}).get("code") == "offsale",
                image_url=image_url,
                genres=genres,
            )

        except Exception as e:
            logger.error(f"Failed to parse Ticketmaster event: {e}")
            return None

    def _deduplicate_events(self, events: list[Event]) -> list[Event]:
        """Remove duplicate events based on external_id."""
        seen = set()
        unique = []
        for event in events:
            if event.external_id and event.external_id not in seen:
                seen.add(event.external_id)
                unique.append(event)
            elif not event.external_id:
                unique.append(event)
        return unique
