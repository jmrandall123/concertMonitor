"""Event rating agent - scores events based on user preferences."""

import logging
import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from .base import Agent, AgentContext, AgentResult
from ..models.event import Event
from ..models.preference import PreferenceProfile, MusicPreference
from ..models.rating import EventRating, RatingFactors
from ..models.user import User, Location

logger = logging.getLogger(__name__)


class RatingAgent(Agent[list[EventRating]]):
    """
    Zero-state agent for rating events based on user preferences.

    Takes events and a preference profile, returns rated events with
    explanations for each rating.

    Rating factors:
    - Artist match (35%): Direct match with preferred artists
    - Genre match (20%): Match with preferred genres
    - Location (15%): Distance from preferred location
    - Timing (10%): Day of week and time preferences
    - Price (10%): Within budget preferences
    - Venue (5%): Based on past venue preferences
    - Popularity (3%): General event popularity
    - Similar events (2%): Boost for attending similar events
    """

    @property
    def name(self) -> str:
        return "rating_agent"

    @property
    def description(self) -> str:
        return "Rates events based on user preferences with explainable scoring"

    def validate(self, context: AgentContext) -> Optional[str]:
        """Validate rating inputs."""
        if not context.input_data.get("events"):
            return "No events provided to rate"
        if not context.input_data.get("preference_profile"):
            return "No preference profile provided"
        return None

    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[list[EventRating]]
    ) -> AgentResult[list[EventRating]]:
        """Rate all provided events."""
        input_data = context.input_data

        events: list[Event] = input_data["events"]
        profile: PreferenceProfile = input_data["preference_profile"]
        user: Optional[User] = input_data.get("user")

        # Get combined preferences
        combined_prefs = profile.get_combined_preferences()

        ratings = []
        for event in events:
            try:
                rating = self._rate_event(
                    event=event,
                    profile=profile,
                    combined_prefs=combined_prefs,
                    user=user,
                    user_id=context.user_id,
                )
                ratings.append(rating)
                result.add_trace(
                    f"Rated '{event.name}': {rating.score}/10 "
                    f"({rating.recommendation_tier})"
                )
            except Exception as e:
                logger.error(f"Failed to rate event {event.id}: {e}")
                result.add_trace(f"Failed to rate event: {e}")

        # Sort by score descending
        ratings.sort(key=lambda r: r.score, reverse=True)

        return result.success(ratings, len(ratings))

    def _rate_event(
        self,
        event: Event,
        profile: PreferenceProfile,
        combined_prefs: MusicPreference,
        user: Optional[User],
        user_id: Optional[UUID],
    ) -> EventRating:
        """Calculate rating for a single event."""
        factors = RatingFactors()

        # 1. Artist match (most important)
        factors.artist_match_score, factors.artist_match_reason = (
            self._calculate_artist_match(event, combined_prefs, profile)
        )

        # 2. Genre match
        factors.genre_match_score, factors.genre_match_reason = (
            self._calculate_genre_match(event, combined_prefs)
        )

        # 3. Location score
        if user and user.preferences.locations:
            factors.location_score, factors.location_reason, factors.distance_miles = (
                self._calculate_location_score(event, user.preferences.locations)
            )
        else:
            factors.location_score = 0.5
            factors.location_reason = "No location preference set"

        # 4. Timing score
        if user:
            factors.timing_score, factors.timing_reason = (
                self._calculate_timing_score(event, user)
            )
        else:
            factors.timing_score = 0.5
            factors.timing_reason = "No timing preference set"

        # 5. Price score
        if user:
            factors.price_score, factors.price_reason = (
                self._calculate_price_score(event, user)
            )
        else:
            factors.price_score = 0.5
            factors.price_reason = "No price preference set"

        # 6. Venue preference (default neutral without history)
        factors.venue_score = 0.5
        factors.venue_reason = "No venue history"

        # 7. Popularity score
        factors.popularity_score, factors.popularity_reason = (
            self._calculate_popularity_score(event)
        )

        # 8. Similar events boost
        factors.similar_events_boost = 0.0
        factors.similar_events_reason = ""

        # Calculate final rating
        return EventRating.calculate(
            user_id=user_id or UUID(int=0),
            event_id=event.id,
            factors=factors,
        )

    def _calculate_artist_match(
        self,
        event: Event,
        prefs: MusicPreference,
        profile: PreferenceProfile,
    ) -> tuple[float, str]:
        """Calculate artist match score."""
        if not event.artists:
            return 0.3, "No artist information available"

        # Check for direct artist matches
        pref_artists_lower = {a.artist_name.lower() for a in prefs.top_artists}
        stated_artists_lower = {a.lower() for a in profile.stated_artists}
        all_preferred = pref_artists_lower | stated_artists_lower

        best_match = 0.0
        matched_artist = None

        for artist in event.artists:
            artist_lower = artist.name.lower()

            # Exact match with stated preference
            if artist_lower in stated_artists_lower:
                return 1.0, f"'{artist.name}' is one of your stated favorite artists"

            # Exact match with streaming preference
            if artist_lower in pref_artists_lower:
                # Get affinity score
                for pref in prefs.top_artists:
                    if pref.artist_name.lower() == artist_lower:
                        if pref.affinity_score > best_match:
                            best_match = pref.affinity_score
                            matched_artist = artist.name
                        break

            # Partial match (contains)
            for pref_artist in all_preferred:
                if pref_artist in artist_lower or artist_lower in pref_artist:
                    if 0.7 > best_match:
                        best_match = 0.7
                        matched_artist = artist.name

        if matched_artist:
            return best_match, f"'{matched_artist}' matches your music taste"

        return 0.2, "Artist not in your usual listening history"

    def _calculate_genre_match(
        self,
        event: Event,
        prefs: MusicPreference,
    ) -> tuple[float, str]:
        """Calculate genre match score."""
        event_genres = [g.lower() for g in event.all_genres]
        if not event_genres:
            return 0.3, "No genre information available"

        pref_genres = {g.genre.lower(): g.affinity_score for g in prefs.genres}

        if not pref_genres:
            return 0.5, "No genre preferences set"

        best_match = 0.0
        matched_genre = None

        for genre in event_genres:
            # Exact match
            if genre in pref_genres:
                if pref_genres[genre] > best_match:
                    best_match = pref_genres[genre]
                    matched_genre = genre
                continue

            # Partial match (e.g., "indie rock" matches "rock")
            for pref_genre, score in pref_genres.items():
                if pref_genre in genre or genre in pref_genre:
                    if score * 0.8 > best_match:
                        best_match = score * 0.8
                        matched_genre = genre

        if matched_genre:
            return best_match, f"'{matched_genre}' matches your genre preferences"

        return 0.2, "Genre doesn't match your usual taste"

    def _calculate_location_score(
        self,
        event: Event,
        locations: list[Location],
    ) -> tuple[float, str, Optional[float]]:
        """Calculate location convenience score."""
        if not event.venue:
            return 0.5, "No venue location available", None

        # Check for city match
        for loc in locations:
            if (event.venue.city.lower() == loc.city.lower() and
                (not loc.state or event.venue.state == loc.state)):
                return 1.0, f"In your preferred city ({loc.city})", 0.0

        # Calculate distance if coordinates available
        if event.venue.latitude and event.venue.longitude:
            for loc in locations:
                if loc.latitude and loc.longitude:
                    distance = self._haversine_distance(
                        loc.latitude, loc.longitude,
                        event.venue.latitude, event.venue.longitude
                    )

                    if distance <= loc.radius_miles:
                        score = 1.0 - (distance / loc.radius_miles) * 0.3
                        return (
                            score,
                            f"{distance:.0f} miles from {loc.city}",
                            distance
                        )

        # City not in preferences
        return 0.4, f"In {event.venue.city}, not your primary location", None

    def _haversine_distance(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        """Calculate distance between two points in miles."""
        R = 3959  # Earth's radius in miles

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def _calculate_timing_score(
        self,
        event: Event,
        user: User,
    ) -> tuple[float, str]:
        """Calculate timing preference score."""
        if not event.event_date:
            return 0.5, "No event date available"

        prefs = user.preferences
        day_name = event.event_date.strftime("%A").lower()
        event_hour = event.event_date.hour

        # Check preferred days
        day_match = day_name in [d.lower() for d in prefs.preferred_days]

        # Check time range
        earliest = int(prefs.earliest_time.split(":")[0])
        latest = int(prefs.latest_time.split(":")[0])
        time_match = earliest <= event_hour <= latest

        if day_match and time_match:
            return 1.0, f"Perfect timing on {day_name.capitalize()}"
        elif day_match:
            return 0.7, f"Good day ({day_name.capitalize()}) but timing may not be ideal"
        elif time_match:
            return 0.6, f"Good time but {day_name.capitalize()} isn't your preferred day"
        else:
            return 0.3, f"Weekday evening event"

    def _calculate_price_score(
        self,
        event: Event,
        user: User,
    ) -> tuple[float, str]:
        """Calculate price value score."""
        if not event.price_range:
            return 0.5, "No price information available"

        prefs = user.preferences
        min_price = event.price_range.min_price
        max_price = event.price_range.max_price

        # Check max budget
        if prefs.max_ticket_price and max_price > prefs.max_ticket_price:
            return 0.2, f"Above your ${prefs.max_ticket_price:.0f} budget"

        # Check preferred range
        pref_min, pref_max = prefs.preferred_price_range

        if min_price >= pref_min and max_price <= pref_max:
            return 1.0, f"In your preferred price range ({event.price_range.display})"
        elif min_price < pref_max:
            return 0.7, f"Partially in your price range ({event.price_range.display})"
        else:
            return 0.4, f"Above preferred range ({event.price_range.display})"

    def _calculate_popularity_score(
        self,
        event: Event,
    ) -> tuple[float, str]:
        """Calculate event popularity score."""
        # Check artist popularity
        if event.artists:
            avg_popularity = sum(
                a.popularity or 50 for a in event.artists
            ) / len(event.artists)
            normalized = avg_popularity / 100

            if normalized > 0.8:
                return normalized, "Very popular artist"
            elif normalized > 0.5:
                return normalized, "Moderately popular artist"
            else:
                return normalized, "Lesser known artist (could be a hidden gem!)"

        return 0.5, "Unknown popularity"
