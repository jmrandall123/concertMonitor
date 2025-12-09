"""Event and venue models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class EventSource(Enum):
    """Source where event was discovered."""
    TICKETMASTER = "ticketmaster"
    BANDSINTOWN = "bandsintown"
    SEATGEEK = "seatgeek"
    SONGKICK = "songkick"
    EVENTBRITE = "eventbrite"
    MANUAL = "manual"


class EventType(Enum):
    """Type of event."""
    CONCERT = "concert"
    FESTIVAL = "festival"
    THEATER = "theater"
    COMEDY = "comedy"
    SPORTS = "sports"
    OTHER = "other"


@dataclass
class Venue:
    """Event venue information."""
    name: str
    city: str
    state: Optional[str] = None
    country: str = "US"
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    capacity: Optional[int] = None
    venue_type: Optional[str] = None  # arena, club, theater, outdoor

    @property
    def full_location(self) -> str:
        """Get formatted location string."""
        parts = [self.city]
        if self.state:
            parts.append(self.state)
        parts.append(self.country)
        return ", ".join(parts)


@dataclass
class PriceRange:
    """Ticket price range."""
    min_price: float
    max_price: float
    currency: str = "USD"

    @property
    def display(self) -> str:
        """Get display string."""
        if self.min_price == self.max_price:
            return f"${self.min_price:.0f}"
        return f"${self.min_price:.0f} - ${self.max_price:.0f}"


@dataclass
class Artist:
    """Artist performing at an event."""
    name: str
    genres: list[str] = field(default_factory=list)
    spotify_id: Optional[str] = None
    apple_music_id: Optional[str] = None
    popularity: Optional[int] = None  # 0-100 scale
    image_url: Optional[str] = None

    def matches_genre(self, target_genres: list[str]) -> bool:
        """Check if artist matches any target genres."""
        artist_genres_lower = [g.lower() for g in self.genres]
        target_genres_lower = [g.lower() for g in target_genres]
        return bool(set(artist_genres_lower) & set(target_genres_lower))


@dataclass
class Event:
    """Represents a concert, show, or ticketed event."""
    id: UUID = field(default_factory=uuid4)
    external_id: Optional[str] = None  # ID from source platform
    source: EventSource = EventSource.MANUAL

    # Basic info
    name: str = ""
    description: Optional[str] = None
    event_type: EventType = EventType.CONCERT

    # Artists/performers
    artists: list[Artist] = field(default_factory=list)
    headliner: Optional[str] = None  # Main act name

    # Venue and location
    venue: Optional[Venue] = None

    # Timing
    event_date: Optional[datetime] = None
    doors_open: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Tickets
    ticket_url: Optional[str] = None
    price_range: Optional[PriceRange] = None
    on_sale_date: Optional[datetime] = None
    is_sold_out: bool = False

    # Metadata
    image_url: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Tracking
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def primary_artist(self) -> Optional[Artist]:
        """Get the primary/headlining artist."""
        if self.artists:
            return self.artists[0]
        return None

    @property
    def all_genres(self) -> list[str]:
        """Get all genres from event and artists."""
        genres = set(self.genres)
        for artist in self.artists:
            genres.update(artist.genres)
        return list(genres)

    @property
    def location_str(self) -> str:
        """Get formatted location string."""
        if self.venue:
            return f"{self.venue.name}, {self.venue.full_location}"
        return "Location TBD"

    @property
    def date_str(self) -> str:
        """Get formatted date string."""
        if self.event_date:
            return self.event_date.strftime("%A, %B %d, %Y at %I:%M %p")
        return "Date TBD"

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "external_id": self.external_id,
            "source": self.source.value,
            "name": self.name,
            "description": self.description,
            "event_type": self.event_type.value,
            "headliner": self.headliner,
            "artists": [
                {"name": a.name, "genres": a.genres, "popularity": a.popularity}
                for a in self.artists
            ],
            "venue": {
                "name": self.venue.name,
                "city": self.venue.city,
                "state": self.venue.state,
                "country": self.venue.country,
            } if self.venue else None,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "ticket_url": self.ticket_url,
            "price_range": self.price_range.display if self.price_range else None,
            "genres": self.all_genres,
            "is_sold_out": self.is_sold_out,
        }

    def to_calendar_description(self) -> str:
        """Generate description for calendar event."""
        lines = []

        if self.artists:
            artist_names = [a.name for a in self.artists]
            lines.append(f"Artists: {', '.join(artist_names)}")

        if self.venue:
            lines.append(f"Venue: {self.venue.name}")
            if self.venue.address:
                lines.append(f"Address: {self.venue.address}")

        if self.price_range:
            lines.append(f"Tickets: {self.price_range.display}")

        if self.ticket_url:
            lines.append(f"Buy tickets: {self.ticket_url}")

        if self.description:
            lines.append(f"\n{self.description}")

        return "\n".join(lines)
