"""Configuration management for the concert monitor system."""

import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class APIConfig:
    """API configuration for external services."""
    # Ticketmaster
    ticketmaster_api_key: Optional[str] = None
    ticketmaster_api_secret: Optional[str] = None

    # SeatGeek
    seatgeek_client_id: Optional[str] = None
    seatgeek_client_secret: Optional[str] = None

    # Spotify
    spotify_client_id: Optional[str] = None
    spotify_client_secret: Optional[str] = None
    spotify_redirect_uri: str = "http://localhost:8080/callback/spotify"

    # Apple Music (requires developer account)
    apple_music_team_id: Optional[str] = None
    apple_music_key_id: Optional[str] = None
    apple_music_private_key: Optional[str] = None

    # Google Calendar
    google_calendar_credentials: Optional[str] = None

    # OpenAI (for AI-powered matching)
    openai_api_key: Optional[str] = None

    # Email (SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    email_from: Optional[str] = None


@dataclass
class SchedulingConfig:
    """Scheduling configuration."""
    discovery_interval_hours: int = 6
    digest_check_interval_minutes: int = 60
    preference_decay_days: int = 30
    cache_ttl_hours: int = 24


@dataclass
class RatingConfig:
    """Rating algorithm configuration."""
    # Default thresholds
    auto_add_threshold: float = 8.0
    digest_threshold: float = 7.0

    # Weight configuration
    weights: dict = field(default_factory=lambda: {
        "artist": 0.35,
        "genre": 0.20,
        "location": 0.15,
        "timing": 0.10,
        "price": 0.10,
        "venue": 0.05,
        "popularity": 0.03,
        "similar_boost": 0.02,
    })


@dataclass
class DiscoveryConfig:
    """Event discovery configuration."""
    days_ahead: int = 90
    max_events_per_source: int = 100
    default_radius_miles: int = 50
    enabled_sources: list[str] = field(default_factory=lambda: [
        "ticketmaster",
        "bandsintown",
        "seatgeek",
    ])


@dataclass
class AppConfig:
    """Main application configuration."""
    # Environment
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Sub-configurations
    api: APIConfig = field(default_factory=APIConfig)
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)
    rating: RatingConfig = field(default_factory=RatingConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)

    # Data storage
    data_dir: str = "./data"
    database_url: Optional[str] = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables."""
        api = APIConfig(
            ticketmaster_api_key=os.getenv("TICKETMASTER_API_KEY"),
            ticketmaster_api_secret=os.getenv("TICKETMASTER_API_SECRET"),
            seatgeek_client_id=os.getenv("SEATGEEK_CLIENT_ID"),
            seatgeek_client_secret=os.getenv("SEATGEEK_CLIENT_SECRET"),
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            google_calendar_credentials=os.getenv("GOOGLE_CALENDAR_CREDENTIALS"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            email_from=os.getenv("EMAIL_FROM"),
        )

        scheduling = SchedulingConfig(
            discovery_interval_hours=int(os.getenv("DISCOVERY_INTERVAL_HOURS", "6")),
            digest_check_interval_minutes=int(os.getenv("DIGEST_CHECK_INTERVAL_MINUTES", "60")),
        )

        rating = RatingConfig(
            auto_add_threshold=float(os.getenv("AUTO_ADD_THRESHOLD", "8.0")),
            digest_threshold=float(os.getenv("DIGEST_THRESHOLD", "7.0")),
        )

        return cls(
            environment=os.getenv("ENVIRONMENT", "development"),
            debug=os.getenv("DEBUG", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            api=api,
            scheduling=scheduling,
            rating=rating,
            data_dir=os.getenv("DATA_DIR", "./data"),
            database_url=os.getenv("DATABASE_URL"),
        )

    @classmethod
    def from_file(cls, path: str) -> "AppConfig":
        """Load configuration from JSON file."""
        config_path = Path(path)
        if not config_path.exists():
            logger.warning(f"Config file not found: {path}, using defaults")
            return cls()

        with open(config_path) as f:
            data = json.load(f)

        return cls(
            environment=data.get("environment", "development"),
            debug=data.get("debug", True),
            log_level=data.get("log_level", "INFO"),
            api=APIConfig(**data.get("api", {})),
            scheduling=SchedulingConfig(**data.get("scheduling", {})),
            rating=RatingConfig(**data.get("rating", {})),
            discovery=DiscoveryConfig(**data.get("discovery", {})),
            data_dir=data.get("data_dir", "./data"),
            database_url=data.get("database_url"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary (excluding secrets)."""
        return {
            "environment": self.environment,
            "debug": self.debug,
            "log_level": self.log_level,
            "scheduling": {
                "discovery_interval_hours": self.scheduling.discovery_interval_hours,
                "digest_check_interval_minutes": self.scheduling.digest_check_interval_minutes,
            },
            "rating": {
                "auto_add_threshold": self.rating.auto_add_threshold,
                "digest_threshold": self.rating.digest_threshold,
                "weights": self.rating.weights,
            },
            "discovery": {
                "days_ahead": self.discovery.days_ahead,
                "max_events_per_source": self.discovery.max_events_per_source,
                "enabled_sources": self.discovery.enabled_sources,
            },
            "api_keys_configured": {
                "ticketmaster": bool(self.api.ticketmaster_api_key),
                "seatgeek": bool(self.api.seatgeek_client_id),
                "spotify": bool(self.api.spotify_client_id),
                "google_calendar": bool(self.api.google_calendar_credentials),
                "email": bool(self.api.smtp_username),
            },
        }


def setup_logging(config: AppConfig) -> None:
    """Configure logging based on app config."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format=log_format,
    )

    # Reduce noise from third-party libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
