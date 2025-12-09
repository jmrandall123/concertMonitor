"""Event rating models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from .user import FeedbackType


@dataclass
class RatingFactors:
    """Individual factors that contribute to an event rating."""
    # Artist matching (0-1 scale, weighted heavily)
    artist_match_score: float = 0.0
    artist_match_reason: str = ""

    # Genre matching (0-1 scale)
    genre_match_score: float = 0.0
    genre_match_reason: str = ""

    # Location convenience (0-1 scale)
    location_score: float = 0.0
    distance_miles: Optional[float] = None
    location_reason: str = ""

    # Timing preference (0-1 scale)
    timing_score: float = 0.0
    timing_reason: str = ""

    # Price value (0-1 scale)
    price_score: float = 0.0
    price_reason: str = ""

    # Venue preference (0-1 scale, based on past venues)
    venue_score: float = 0.5  # Default neutral
    venue_reason: str = ""

    # Popularity/demand signal (0-1 scale)
    popularity_score: float = 0.5
    popularity_reason: str = ""

    # Similar events attended boost
    similar_events_boost: float = 0.0
    similar_events_reason: str = ""

    def get_explanation(self) -> str:
        """Get human-readable explanation of rating factors."""
        explanations = []

        if self.artist_match_score > 0.5:
            explanations.append(f"✓ {self.artist_match_reason}")
        elif self.artist_match_score < 0.3:
            explanations.append(f"○ {self.artist_match_reason}")

        if self.genre_match_score > 0.5:
            explanations.append(f"✓ {self.genre_match_reason}")

        if self.location_score > 0.7:
            explanations.append(f"✓ {self.location_reason}")
        elif self.location_score < 0.3:
            explanations.append(f"✗ {self.location_reason}")

        if self.timing_score > 0.7:
            explanations.append(f"✓ {self.timing_reason}")
        elif self.timing_score < 0.3:
            explanations.append(f"✗ {self.timing_reason}")

        if self.price_score > 0.7:
            explanations.append(f"✓ {self.price_reason}")
        elif self.price_score < 0.3:
            explanations.append(f"✗ {self.price_reason}")

        if self.similar_events_boost > 0:
            explanations.append(f"⬆ {self.similar_events_reason}")

        return "\n".join(explanations) if explanations else "No specific matches"


@dataclass
class EventRating:
    """Rating for an event based on user preferences."""
    id: UUID = field(default_factory=uuid4)

    # References
    user_id: UUID = field(default_factory=uuid4)
    event_id: UUID = field(default_factory=uuid4)

    # The rating (1-10 scale)
    score: float = 5.0

    # Breakdown of factors
    factors: RatingFactors = field(default_factory=RatingFactors)

    # Weights used for this rating
    weights_used: dict = field(default_factory=lambda: {
        "artist": 0.35,
        "genre": 0.20,
        "location": 0.15,
        "timing": 0.10,
        "price": 0.10,
        "venue": 0.05,
        "popularity": 0.03,
        "similar_boost": 0.02,
    })

    # Human readable explanation
    explanation: str = ""

    # Action taken
    auto_added_to_calendar: bool = False
    included_in_digest: bool = False

    # User feedback
    user_feedback: FeedbackType = FeedbackType.NO_RESPONSE
    feedback_received_at: Optional[datetime] = None

    # Timestamps
    rated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def calculate(
        cls,
        user_id: UUID,
        event_id: UUID,
        factors: RatingFactors,
        weights: Optional[dict] = None,
    ) -> "EventRating":
        """Calculate rating from factors using weights."""
        rating = cls(user_id=user_id, event_id=event_id, factors=factors)

        if weights:
            rating.weights_used = weights

        w = rating.weights_used

        # Calculate weighted score (0-1 scale)
        weighted_score = (
            factors.artist_match_score * w["artist"] +
            factors.genre_match_score * w["genre"] +
            factors.location_score * w["location"] +
            factors.timing_score * w["timing"] +
            factors.price_score * w["price"] +
            factors.venue_score * w["venue"] +
            factors.popularity_score * w["popularity"] +
            factors.similar_events_boost * w["similar_boost"]
        )

        # Convert to 1-10 scale
        # Use a slight curve to spread out the middle range
        rating.score = round(1 + (weighted_score * 9), 1)

        # Generate explanation
        rating.explanation = factors.get_explanation()

        return rating

    @property
    def recommendation_tier(self) -> str:
        """Get recommendation tier based on score."""
        if self.score >= 9:
            return "must_see"
        elif self.score >= 8:
            return "highly_recommended"
        elif self.score >= 7:
            return "recommended"
        elif self.score >= 5:
            return "might_enjoy"
        else:
            return "not_recommended"

    @property
    def should_auto_add(self) -> bool:
        """Check if event should be auto-added to calendar."""
        return self.score >= 8.0

    @property
    def should_include_in_digest(self) -> bool:
        """Check if event should be included in digest."""
        return self.score >= 7.0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "event_id": str(self.event_id),
            "score": self.score,
            "recommendation_tier": self.recommendation_tier,
            "explanation": self.explanation,
            "auto_added": self.auto_added_to_calendar,
            "in_digest": self.included_in_digest,
            "user_feedback": self.user_feedback.value if self.user_feedback else None,
            "factors": {
                "artist_match": self.factors.artist_match_score,
                "genre_match": self.factors.genre_match_score,
                "location": self.factors.location_score,
                "timing": self.factors.timing_score,
                "price": self.factors.price_score,
            },
            "rated_at": self.rated_at.isoformat(),
        }
