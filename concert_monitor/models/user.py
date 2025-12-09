"""User model and preferences."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class FeedbackType(Enum):
    """User feedback on calendar invites."""
    YES = "yes"          # User attended or wants to attend
    NO = "no"            # User not interested
    MAYBE = "maybe"      # User is considering
    NO_RESPONSE = None   # No feedback yet


@dataclass
class Location:
    """Geographic location for event filtering."""
    city: str
    state: Optional[str] = None
    country: str = "US"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_miles: int = 50  # Search radius


@dataclass
class UserPreferences:
    """User's event preferences and settings."""
    # Location preferences
    locations: list[Location] = field(default_factory=list)
    willing_to_travel_miles: int = 100

    # Time preferences
    preferred_days: list[str] = field(default_factory=lambda: [
        "friday", "saturday", "sunday"
    ])
    earliest_time: str = "17:00"  # 5 PM
    latest_time: str = "23:00"    # 11 PM

    # Calendar settings
    auto_add_threshold: float = 8.0  # Rating threshold for auto-add
    digest_threshold: float = 7.0    # Rating threshold for digest inclusion

    # Notification preferences
    email_digest_frequency: str = "weekly"  # daily, weekly, monthly
    digest_day: str = "monday"  # For weekly digests
    notify_on_calendar_add: bool = True

    # Budget preferences
    max_ticket_price: Optional[float] = None
    preferred_price_range: tuple[float, float] = (0, 200)


@dataclass
class User:
    """Represents a user of the concert monitor system."""
    id: UUID = field(default_factory=uuid4)
    email: str = ""
    name: str = ""

    # Preferences
    preferences: UserPreferences = field(default_factory=UserPreferences)

    # Music taste source
    spotify_connected: bool = False
    apple_music_connected: bool = False
    spotify_user_id: Optional[str] = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_digest_sent: Optional[datetime] = None

    # Calendar integration
    google_calendar_connected: bool = False
    apple_calendar_connected: bool = False
    calendar_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "email": self.email,
            "name": self.name,
            "spotify_connected": self.spotify_connected,
            "apple_music_connected": self.apple_music_connected,
            "google_calendar_connected": self.google_calendar_connected,
            "created_at": self.created_at.isoformat(),
            "preferences": {
                "auto_add_threshold": self.preferences.auto_add_threshold,
                "digest_threshold": self.preferences.digest_threshold,
                "email_digest_frequency": self.preferences.email_digest_frequency,
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Create from dictionary."""
        prefs = UserPreferences(
            auto_add_threshold=data.get("preferences", {}).get("auto_add_threshold", 8.0),
            digest_threshold=data.get("preferences", {}).get("digest_threshold", 7.0),
        )
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            email=data.get("email", ""),
            name=data.get("name", ""),
            preferences=prefs,
            spotify_connected=data.get("spotify_connected", False),
            apple_music_connected=data.get("apple_music_connected", False),
            google_calendar_connected=data.get("google_calendar_connected", False),
        )
