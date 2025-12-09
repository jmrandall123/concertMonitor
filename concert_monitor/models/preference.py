"""User music preference models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class ArtistPreference:
    """User's preference for a specific artist."""
    artist_name: str
    spotify_id: Optional[str] = None
    apple_music_id: Optional[str] = None

    # Preference signals
    play_count: int = 0
    is_top_artist: bool = False
    ranking: Optional[int] = None  # Position in user's top artists

    # Derived score (0-1)
    affinity_score: float = 0.5

    # Source of preference
    source: str = "manual"  # spotify, apple_music, manual, inferred

    # Event history
    events_attended: int = 0
    events_skipped: int = 0


@dataclass
class GenrePreference:
    """User's preference for a music genre."""
    genre: str

    # Preference signals
    affinity_score: float = 0.5  # 0-1 scale

    # Play stats
    total_plays: int = 0
    artist_count: int = 0  # How many liked artists in this genre

    # Feedback derived
    events_attended: int = 0
    events_declined: int = 0

    @property
    def feedback_ratio(self) -> float:
        """Ratio of attended vs declined events."""
        total = self.events_attended + self.events_declined
        if total == 0:
            return 0.5
        return self.events_attended / total


@dataclass
class MusicPreference:
    """Aggregated music preferences from streaming data."""
    # Top artists with rankings
    top_artists: list[ArtistPreference] = field(default_factory=list)

    # Genre preferences
    genres: list[GenrePreference] = field(default_factory=list)

    # Listening stats
    total_minutes_listened: int = 0
    top_tracks_count: int = 0

    # Time-based preferences (when user listens most)
    peak_listening_hours: list[int] = field(default_factory=list)

    # Source metadata
    source: str = ""  # spotify_wrapped, apple_replay, manual
    source_year: Optional[int] = None
    imported_at: datetime = field(default_factory=datetime.utcnow)

    def get_artist_affinity(self, artist_name: str) -> float:
        """Get affinity score for an artist (0-1)."""
        artist_lower = artist_name.lower()
        for pref in self.top_artists:
            if pref.artist_name.lower() == artist_lower:
                return pref.affinity_score
        return 0.0

    def get_genre_affinity(self, genre: str) -> float:
        """Get affinity score for a genre (0-1)."""
        genre_lower = genre.lower()
        for pref in self.genres:
            if pref.genre.lower() == genre_lower:
                return pref.affinity_score
        return 0.0

    def top_genres(self, n: int = 10) -> list[str]:
        """Get top N genres by affinity."""
        sorted_genres = sorted(
            self.genres,
            key=lambda g: g.affinity_score,
            reverse=True
        )
        return [g.genre for g in sorted_genres[:n]]

    def top_artist_names(self, n: int = 20) -> list[str]:
        """Get top N artist names."""
        sorted_artists = sorted(
            self.top_artists,
            key=lambda a: a.affinity_score,
            reverse=True
        )
        return [a.artist_name for a in sorted_artists[:n]]


@dataclass
class PreferenceProfile:
    """Complete user preference profile combining all sources."""
    user_id: UUID

    # Music preferences from streaming services
    spotify_preferences: Optional[MusicPreference] = None
    apple_preferences: Optional[MusicPreference] = None

    # Manually stated preferences (from conversation)
    stated_artists: list[str] = field(default_factory=list)
    stated_genres: list[str] = field(default_factory=list)
    stated_dislikes: list[str] = field(default_factory=list)

    # Learned preferences from feedback
    learned_preferences: MusicPreference = field(
        default_factory=lambda: MusicPreference(source="learned")
    )

    # Combined/computed preferences
    _combined_cache: Optional[MusicPreference] = field(default=None, repr=False)
    _cache_timestamp: Optional[datetime] = field(default=None, repr=False)

    def get_combined_preferences(self) -> MusicPreference:
        """Get combined preferences from all sources."""
        # Simple combination - weight different sources
        combined = MusicPreference(source="combined")

        artist_scores: dict[str, float] = {}
        genre_scores: dict[str, float] = {}

        # Weight: Spotify/Apple = 0.4, Manual = 0.3, Learned = 0.3
        sources = [
            (self.spotify_preferences, 0.4),
            (self.apple_preferences, 0.4),
            (self.learned_preferences, 0.3),
        ]

        for prefs, weight in sources:
            if prefs:
                for artist in prefs.top_artists:
                    name = artist.artist_name.lower()
                    current = artist_scores.get(name, 0)
                    artist_scores[name] = current + (artist.affinity_score * weight)

                for genre in prefs.genres:
                    name = genre.genre.lower()
                    current = genre_scores.get(name, 0)
                    genre_scores[name] = current + (genre.affinity_score * weight)

        # Add stated preferences with high weight
        for artist in self.stated_artists:
            name = artist.lower()
            artist_scores[name] = artist_scores.get(name, 0) + 0.8

        for genre in self.stated_genres:
            name = genre.lower()
            genre_scores[name] = genre_scores.get(name, 0) + 0.7

        # Reduce scores for dislikes
        for dislike in self.stated_dislikes:
            name = dislike.lower()
            if name in artist_scores:
                artist_scores[name] *= 0.1
            if name in genre_scores:
                genre_scores[name] *= 0.1

        # Normalize and create preference objects
        if artist_scores:
            max_artist = max(artist_scores.values())
            for name, score in artist_scores.items():
                combined.top_artists.append(
                    ArtistPreference(
                        artist_name=name,
                        affinity_score=min(score / max_artist, 1.0),
                        source="combined"
                    )
                )

        if genre_scores:
            max_genre = max(genre_scores.values())
            for name, score in genre_scores.items():
                combined.genres.append(
                    GenrePreference(
                        genre=name,
                        affinity_score=min(score / max_genre, 1.0)
                    )
                )

        return combined

    def update_from_feedback(
        self,
        artist_name: str,
        genres: list[str],
        feedback: str  # "yes", "no", "maybe"
    ) -> None:
        """Update learned preferences based on user feedback."""
        # Adjust affinity based on feedback
        adjustment = {
            "yes": 0.1,
            "maybe": 0.02,
            "no": -0.1
        }.get(feedback, 0)

        # Update artist preference
        found = False
        for pref in self.learned_preferences.top_artists:
            if pref.artist_name.lower() == artist_name.lower():
                pref.affinity_score = max(0, min(1, pref.affinity_score + adjustment))
                if feedback == "yes":
                    pref.events_attended += 1
                elif feedback == "no":
                    pref.events_skipped += 1
                found = True
                break

        if not found:
            base_score = 0.5 + adjustment
            self.learned_preferences.top_artists.append(
                ArtistPreference(
                    artist_name=artist_name,
                    affinity_score=base_score,
                    source="feedback",
                    events_attended=1 if feedback == "yes" else 0,
                    events_skipped=1 if feedback == "no" else 0
                )
            )

        # Update genre preferences
        for genre in genres:
            found = False
            for pref in self.learned_preferences.genres:
                if pref.genre.lower() == genre.lower():
                    pref.affinity_score = max(0, min(1, pref.affinity_score + adjustment * 0.5))
                    if feedback == "yes":
                        pref.events_attended += 1
                    elif feedback == "no":
                        pref.events_declined += 1
                    found = True
                    break

            if not found:
                base_score = 0.5 + (adjustment * 0.5)
                self.learned_preferences.genres.append(
                    GenrePreference(
                        genre=genre,
                        affinity_score=base_score,
                        events_attended=1 if feedback == "yes" else 0,
                        events_declined=1 if feedback == "no" else 0
                    )
                )
