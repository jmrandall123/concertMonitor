"""External service integrations."""

from .spotify import SpotifyService
from .apple_music import AppleMusicService
from .google_calendar import GoogleCalendarService
from .email_service import EmailService

__all__ = [
    "SpotifyService",
    "AppleMusicService",
    "GoogleCalendarService",
    "EmailService",
]
