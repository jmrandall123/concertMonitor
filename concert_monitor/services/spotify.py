"""Spotify integration service."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import aiohttp

from ..models.preference import (
    MusicPreference,
    ArtistPreference,
    GenrePreference,
)

logger = logging.getLogger(__name__)


@dataclass
class SpotifyConfig:
    """Spotify API configuration."""
    client_id: str
    client_secret: str
    redirect_uri: str = "http://localhost:8080/callback"


class SpotifyService:
    """Service for interacting with Spotify API and parsing user data."""

    BASE_URL = "https://api.spotify.com/v1"
    AUTH_URL = "https://accounts.spotify.com/api/token"

    def __init__(self, config: Optional[SpotifyConfig] = None):
        self.config = config
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None

    async def get_user_top_artists(
        self,
        access_token: str,
        time_range: str = "medium_term",  # short_term, medium_term, long_term
        limit: int = 50
    ) -> list[ArtistPreference]:
        """Fetch user's top artists from Spotify API."""
        artists = []

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {access_token}"}
            url = f"{self.BASE_URL}/me/top/artists"
            params = {"time_range": time_range, "limit": limit}

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch top artists: {resp.status}")
                    return artists

                data = await resp.json()

                for i, item in enumerate(data.get("items", [])):
                    # Calculate affinity score based on ranking
                    # Top artist gets 1.0, decreasing from there
                    affinity = 1.0 - (i / limit) * 0.5  # Range: 0.5 to 1.0

                    artists.append(ArtistPreference(
                        artist_name=item["name"],
                        spotify_id=item["id"],
                        affinity_score=affinity,
                        ranking=i + 1,
                        is_top_artist=i < 10,
                        source="spotify",
                    ))

        return artists

    async def get_user_top_genres(
        self,
        access_token: str,
        time_range: str = "medium_term"
    ) -> list[GenrePreference]:
        """Extract top genres from user's top artists."""
        genre_counts: dict[str, int] = {}
        artists = await self.get_user_top_artists(access_token, time_range)

        # Fetch artist details to get genres
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {access_token}"}

            for artist in artists[:50]:  # Top 50 artists
                if not artist.spotify_id:
                    continue

                url = f"{self.BASE_URL}/artists/{artist.spotify_id}"
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for genre in data.get("genres", []):
                            genre_counts[genre] = genre_counts.get(genre, 0) + 1

        # Convert to preferences
        if not genre_counts:
            return []

        max_count = max(genre_counts.values())
        genres = [
            GenrePreference(
                genre=genre,
                affinity_score=count / max_count,
                artist_count=count
            )
            for genre, count in genre_counts.items()
        ]

        return sorted(genres, key=lambda g: g.affinity_score, reverse=True)

    def parse_wrapped_data(self, wrapped_json: str) -> MusicPreference:
        """
        Parse Spotify Wrapped data export.

        Expects JSON format from Spotify data export or Wrapped share.
        """
        try:
            data = json.loads(wrapped_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Wrapped JSON: {e}")
            return MusicPreference(source="spotify_wrapped")

        prefs = MusicPreference(
            source="spotify_wrapped",
            source_year=data.get("year", datetime.now().year),
        )

        # Parse top artists
        top_artists = data.get("topArtists", data.get("top_artists", []))
        for i, artist in enumerate(top_artists):
            if isinstance(artist, str):
                name = artist
                spotify_id = None
            else:
                name = artist.get("name", artist.get("artistName", ""))
                spotify_id = artist.get("id", artist.get("spotifyId"))

            if name:
                affinity = 1.0 - (i / max(len(top_artists), 1)) * 0.5
                prefs.top_artists.append(ArtistPreference(
                    artist_name=name,
                    spotify_id=spotify_id,
                    affinity_score=affinity,
                    ranking=i + 1,
                    is_top_artist=True,
                    source="spotify_wrapped",
                ))

        # Parse genres
        top_genres = data.get("topGenres", data.get("top_genres", []))
        for i, genre in enumerate(top_genres):
            if isinstance(genre, str):
                genre_name = genre
            else:
                genre_name = genre.get("name", genre.get("genre", ""))

            if genre_name:
                affinity = 1.0 - (i / max(len(top_genres), 1)) * 0.4
                prefs.genres.append(GenrePreference(
                    genre=genre_name,
                    affinity_score=affinity,
                ))

        # Parse listening stats
        prefs.total_minutes_listened = data.get(
            "minutesListened",
            data.get("total_minutes", 0)
        )

        return prefs

    def parse_streaming_history(self, history_json: str) -> MusicPreference:
        """
        Parse Spotify streaming history from data export.

        This gives more granular data than Wrapped.
        """
        try:
            history = json.loads(history_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse streaming history: {e}")
            return MusicPreference(source="spotify_history")

        prefs = MusicPreference(source="spotify_history")

        # Count plays per artist
        artist_plays: dict[str, int] = {}
        total_ms = 0

        for entry in history:
            artist = entry.get("artistName", entry.get("master_metadata_album_artist_name", ""))
            ms_played = entry.get("msPlayed", entry.get("ms_played", 0))

            if artist:
                artist_plays[artist] = artist_plays.get(artist, 0) + 1
                total_ms += ms_played

        prefs.total_minutes_listened = total_ms // 60000

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
                    source="spotify_history",
                ))

        return prefs
