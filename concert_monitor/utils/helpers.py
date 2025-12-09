"""Helper functions for the concert monitor system."""

import math
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple


def normalize_artist_name(name: str) -> str:
    """
    Normalize artist name for comparison.

    Handles:
    - Case normalization
    - "The" prefix handling
    - Special characters
    - Common variations
    """
    if not name:
        return ""

    normalized = name.lower().strip()

    # Remove "the " prefix for matching
    if normalized.startswith("the "):
        normalized = normalized[4:]

    # Remove special characters except spaces and hyphens
    normalized = re.sub(r"[^\w\s-]", "", normalized)

    # Normalize whitespace
    normalized = " ".join(normalized.split())

    return normalized


def normalize_genre(genre: str) -> str:
    """
    Normalize genre name for comparison.

    Maps common variations to standard names.
    """
    if not genre:
        return ""

    normalized = genre.lower().strip()

    # Common genre mappings
    genre_mappings = {
        "hip hop": "hip-hop",
        "hiphop": "hip-hop",
        "r and b": "r&b",
        "rnb": "r&b",
        "rhythm and blues": "r&b",
        "edm": "electronic",
        "electronica": "electronic",
        "indie rock": "indie",
        "alt rock": "alternative",
        "alt-rock": "alternative",
        "heavy metal": "metal",
        "hard rock": "rock",
        "classic rock": "rock",
        "k pop": "k-pop",
        "kpop": "k-pop",
        "j pop": "j-pop",
        "jpop": "j-pop",
    }

    return genre_mappings.get(normalized, normalized)


def calculate_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    unit: str = "miles"
) -> float:
    """
    Calculate distance between two coordinates using Haversine formula.

    Args:
        lat1, lon1: First coordinate
        lat2, lon2: Second coordinate
        unit: "miles" or "km"

    Returns:
        Distance in specified unit
    """
    # Earth's radius
    R_miles = 3959
    R_km = 6371

    R = R_miles if unit == "miles" else R_km

    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    # Haversine formula
    a = (
        math.sin(delta_lat / 2) ** 2 +
        math.cos(lat1_rad) * math.cos(lat2_rad) *
        math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def parse_date_range(
    date_str: str
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Parse a date range string into start and end datetimes.

    Supports:
    - "this week"
    - "next week"
    - "this month"
    - "next 30 days"
    - "2024-01-01 to 2024-01-31"
    - "January 2024"
    """
    date_str = date_str.lower().strip()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if date_str == "today":
        return today, today + timedelta(days=1)

    if date_str == "tomorrow":
        tomorrow = today + timedelta(days=1)
        return tomorrow, tomorrow + timedelta(days=1)

    if date_str == "this week":
        # Start from today, end on Sunday
        days_until_sunday = 6 - today.weekday()
        return today, today + timedelta(days=days_until_sunday + 1)

    if date_str == "next week":
        # Start next Monday, end next Sunday
        days_until_monday = 7 - today.weekday()
        start = today + timedelta(days=days_until_monday)
        return start, start + timedelta(days=7)

    if date_str == "this month":
        start = today.replace(day=1)
        # Get last day of month
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1)
        else:
            end = today.replace(month=today.month + 1, day=1)
        return start, end

    if date_str == "next month":
        if today.month == 12:
            start = today.replace(year=today.year + 1, month=1, day=1)
            end = start.replace(month=2, day=1)
        else:
            start = today.replace(month=today.month + 1, day=1)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1, day=1)
            else:
                end = start.replace(month=start.month + 1, day=1)
        return start, end

    # "next N days"
    match = re.match(r"next (\d+) days?", date_str)
    if match:
        days = int(match.group(1))
        return today, today + timedelta(days=days)

    # "YYYY-MM-DD to YYYY-MM-DD"
    match = re.match(
        r"(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})",
        date_str
    )
    if match:
        start = datetime.strptime(match.group(1), "%Y-%m-%d")
        end = datetime.strptime(match.group(2), "%Y-%m-%d")
        return start, end + timedelta(days=1)

    return None, None


def format_event_for_display(event: "Event", rating: Optional["EventRating"] = None) -> str:
    """Format event for text display."""
    lines = []

    # Title
    if rating:
        score_emoji = "🔥" if rating.score >= 8 else "⭐" if rating.score >= 7 else "💡"
        lines.append(f"{score_emoji} {event.name} ({rating.score}/10)")
    else:
        lines.append(f"🎵 {event.name}")

    # Date and venue
    if event.event_date:
        lines.append(f"   📅 {event.date_str}")
    if event.venue:
        lines.append(f"   📍 {event.location_str}")

    # Price
    if event.price_range:
        lines.append(f"   💰 {event.price_range.display}")

    # Rating explanation
    if rating and rating.explanation:
        lines.append(f"   ℹ️  {rating.explanation.split(chr(10))[0]}")

    return "\n".join(lines)


def chunk_list(lst: list, chunk_size: int) -> list[list]:
    """Split a list into chunks of specified size."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]
