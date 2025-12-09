"""Apple Music integration service."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..models.preference import (
    MusicPreference,
    ArtistPreference,
    GenrePreference,
)

logger = logging.getLogger(__name__)


@dataclass
class AppleMusicConfig:
    """Apple Music API configuration."""
    developer_token: str
    team_id: str
    key_id: str
    private_key: str


class AppleMusicService:
    """Service for interacting with Apple Music and parsing Replay data."""

    BASE_URL = "https://api.music.apple.com/v1"

    def __init__(self, config: Optional[AppleMusicConfig] = None):
        self.config = config

    def parse_replay_data(self, replay_json: str) -> MusicPreference:
        """
        Parse Apple Music Replay data.

        Supports various Replay export formats.
        """
        try:
            data = json.loads(replay_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Replay JSON: {e}")
            return MusicPreference(source="apple_replay")

        prefs = MusicPreference(
            source="apple_replay",
            source_year=data.get("year", datetime.now().year),
        )

        # Parse top artists - handle different formats
        top_artists = (
            data.get("topArtists") or
            data.get("top_artists") or
            data.get("artists") or
            []
        )

        for i, artist in enumerate(top_artists):
            if isinstance(artist, str):
                name = artist
                apple_id = None
                play_count = 0
            else:
                name = (
                    artist.get("name") or
                    artist.get("artistName") or
                    artist.get("artist_name") or
                    ""
                )
                apple_id = artist.get("id") or artist.get("appleMusicId")
                play_count = artist.get("playCount", artist.get("play_count", 0))

            if name:
                # Calculate affinity based on ranking
                affinity = 1.0 - (i / max(len(top_artists), 1)) * 0.5
                prefs.top_artists.append(ArtistPreference(
                    artist_name=name,
                    apple_music_id=apple_id,
                    play_count=play_count,
                    affinity_score=affinity,
                    ranking=i + 1,
                    is_top_artist=i < 10,
                    source="apple_replay",
                ))

        # Parse top genres
        top_genres = (
            data.get("topGenres") or
            data.get("top_genres") or
            data.get("genres") or
            []
        )

        for i, genre in enumerate(top_genres):
            if isinstance(genre, str):
                genre_name = genre
            else:
                genre_name = genre.get("name") or genre.get("genre") or ""

            if genre_name:
                affinity = 1.0 - (i / max(len(top_genres), 1)) * 0.4
                prefs.genres.append(GenrePreference(
                    genre=genre_name,
                    affinity_score=affinity,
                ))

        # Parse listening stats
        prefs.total_minutes_listened = (
            data.get("minutesListened") or
            data.get("minutes_listened") or
            data.get("totalMinutes") or
            0
        )

        prefs.top_tracks_count = (
            data.get("topSongsCount") or
            data.get("top_songs_count") or
            len(data.get("topSongs", []))
        )

        return prefs

    def parse_library_export(self, library_xml: str) -> MusicPreference:
        """
        Parse iTunes/Music library XML export.

        This provides the most complete view of user's music.
        """
        # Simplified parsing - in production would use proper XML parsing
        import re

        prefs = MusicPreference(source="apple_library")
        artist_plays: dict[str, int] = {}

        # Very basic XML parsing for artist and play count
        # In production, use xml.etree.ElementTree
        artist_pattern = r"<key>Artist</key><string>([^<]+)</string>"
        play_pattern = r"<key>Play Count</key><integer>(\d+)</integer>"

        # This is a simplified approach - real implementation would
        # properly parse the XML structure
        current_artist = None
        for line in library_xml.split("\n"):
            artist_match = re.search(artist_pattern, line)
            if artist_match:
                current_artist = artist_match.group(1)

            play_match = re.search(play_pattern, line)
            if play_match and current_artist:
                plays = int(play_match.group(1))
                artist_plays[current_artist] = (
                    artist_plays.get(current_artist, 0) + plays
                )
                current_artist = None

        # Convert to preferences
        if artist_plays:
            max_plays = max(artist_plays.values())
            sorted_artists = sorted(
                artist_plays.items(),
                key=lambda x: x[1],
                reverse=True
            )

            for i, (artist, plays) in enumerate(sorted_artists[:100]):
                prefs.top_artists.append(ArtistPreference(
                    artist_name=artist,
                    play_count=plays,
                    affinity_score=plays / max_plays,
                    ranking=i + 1,
                    is_top_artist=i < 20,
                    source="apple_library",
                ))

        return prefs
