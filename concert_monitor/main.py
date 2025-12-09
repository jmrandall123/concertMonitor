"""
Main entry point for the Concert Monitor Agent System.

This module provides:
- CLI interface for running the system
- API server for integrations
- Scheduled task runner
"""

import asyncio
import argparse
import logging
import sys
from datetime import datetime
from uuid import uuid4

from .config import AppConfig, setup_logging
from .orchestrator import ConcertMonitorOrchestrator, OrchestratorConfig
from .models.user import User, UserPreferences, Location
from .models.preference import PreferenceProfile
from .utils.storage import JSONFileStorage, UserDataStore

logger = logging.getLogger(__name__)


async def run_demo():
    """Run a demo of the concert monitor system."""
    print("🎵 Concert Monitor Agent System - Demo Mode")
    print("=" * 50)

    # Load configuration
    config = AppConfig.from_env()
    setup_logging(config)

    # Create orchestrator
    orchestrator_config = OrchestratorConfig(
        ticketmaster_api_key=config.api.ticketmaster_api_key,
        seatgeek_client_id=config.api.seatgeek_client_id,
        seatgeek_client_secret=config.api.seatgeek_client_secret,
    )
    orchestrator = ConcertMonitorOrchestrator(orchestrator_config)

    # Create demo user
    demo_user = User(
        id=uuid4(),
        email="demo@example.com",
        name="Demo User",
        preferences=UserPreferences(
            locations=[
                Location(
                    city="New York",
                    state="NY",
                    latitude=40.7128,
                    longitude=-74.0060,
                    radius_miles=50,
                )
            ],
            preferred_days=["friday", "saturday", "sunday"],
            auto_add_threshold=8.0,
            digest_threshold=7.0,
        ),
    )

    print(f"\n📋 Demo User: {demo_user.name}")
    print(f"   Location: New York, NY (50 mile radius)")
    print(f"   Calendar threshold: {demo_user.preferences.auto_add_threshold}/10")
    print(f"   Digest threshold: {demo_user.preferences.digest_threshold}/10")

    # Create demo preferences (simulating Spotify Wrapped data)
    demo_spotify_data = {
        "year": 2024,
        "topArtists": [
            "Taylor Swift",
            "The Weeknd",
            "Drake",
            "Dua Lipa",
            "Bad Bunny",
            "Ed Sheeran",
            "Billie Eilish",
            "Post Malone",
            "Ariana Grande",
            "Kendrick Lamar",
        ],
        "topGenres": [
            "pop",
            "hip-hop",
            "r&b",
            "electronic",
            "indie",
        ],
        "minutesListened": 45000,
    }

    print("\n🎧 Processing Spotify Wrapped data...")
    print(f"   Top artists: {', '.join(demo_spotify_data['topArtists'][:5])}")
    print(f"   Top genres: {', '.join(demo_spotify_data['topGenres'])}")

    # Onboard user with preferences
    profile = await orchestrator.onboard_user(
        user=demo_user,
        spotify_data=demo_spotify_data,
    )

    print(f"\n✅ Extracted {len(profile.spotify_preferences.top_artists)} artist preferences")

    # Note: In production, this would actually call the APIs
    print("\n🔍 Discovering events...")
    print("   (In production, this would search Ticketmaster, Bandsintown, SeatGeek)")
    print("   Note: API keys required for live discovery")

    # Show what would happen
    print("\n📊 Rating Process:")
    print("   Each event is scored on:")
    print("   • Artist match (35%) - How well does the artist match your taste?")
    print("   • Genre match (20%) - Is this a genre you enjoy?")
    print("   • Location (15%) - Is it in your preferred area?")
    print("   • Timing (10%) - Is it on a day/time you prefer?")
    print("   • Price (10%) - Is it within your budget?")
    print("   • Venue (5%) - Based on venue preferences")
    print("   • Popularity (3%) - General event popularity")
    print("   • Similar events (2%) - Boost for related events")

    print("\n📅 Calendar Integration:")
    print(f"   Events rated 8/10 or higher → Auto-added to calendar")
    print(f"   Events rated 7-7.9/10 → Included in email digest")
    print(f"   Events rated 5-6.9/10 → Shown as 'might enjoy'")

    print("\n📧 Email Digest:")
    print("   Personalized weekly digest with:")
    print("   • 🔥 Must See events (8+)")
    print("   • ⭐ Recommended events (7-7.9)")
    print("   • 💡 You might also enjoy (5-6.9)")

    print("\n🔄 Feedback Loop:")
    print("   Your responses (yes/no/maybe) improve future recommendations")
    print("   The system learns from your preferences over time")

    print("\n" + "=" * 50)
    print("Demo complete! To use with real data:")
    print("1. Set up API keys in .env file")
    print("2. Connect Spotify/Apple Music account")
    print("3. Run: python -m concert_monitor --user your@email.com")
    print("=" * 50)


async def run_for_user(email: str, spotify_file: str = None, apple_file: str = None):
    """Run the full pipeline for a specific user."""
    config = AppConfig.from_env()
    setup_logging(config)

    # Initialize storage
    storage = JSONFileStorage(config.data_dir)
    data_store = UserDataStore(storage)

    # Create orchestrator
    orchestrator_config = OrchestratorConfig(
        ticketmaster_api_key=config.api.ticketmaster_api_key,
        seatgeek_client_id=config.api.seatgeek_client_id,
    )
    orchestrator = ConcertMonitorOrchestrator(orchestrator_config)

    # Load or create user
    user_data = await data_store.load_user(email)
    if user_data:
        user = User.from_dict(user_data)
        logger.info(f"Loaded existing user: {email}")
    else:
        user = User(
            email=email,
            name=email.split("@")[0],
        )
        logger.info(f"Created new user: {email}")

    # Load preferences
    spotify_data = None
    apple_data = None

    if spotify_file:
        with open(spotify_file) as f:
            spotify_data = f.read()

    if apple_file:
        with open(apple_file) as f:
            apple_data = f.read()

    # Onboard or update preferences
    profile = await orchestrator.onboard_user(
        user=user,
        spotify_data=spotify_data,
        apple_data=apple_data,
    )

    # Run the full pipeline
    logger.info("Running full pipeline...")
    results = await orchestrator.run_full_pipeline(user, profile)

    # Save updated data
    await data_store.save_user(user)
    await data_store.save_preferences(user.id, profile)

    # Output results
    print("\n📊 Pipeline Results:")
    print(f"   Events discovered: {results['discovery']['events_found']}")
    print(f"   Events rated: {results['rating']['events_rated']}")
    print(f"   Must-see events: {results['rating']['must_see']}")
    print(f"   Added to calendar: {results['calendar']['summary']['total_added']}")

    if results.get('digest'):
        print(f"   Digest sent: {results['digest']['sent']}")

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Concert Monitor Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run demo mode
  python -m concert_monitor --demo

  # Run for a specific user
  python -m concert_monitor --user your@email.com

  # Import Spotify data
  python -m concert_monitor --user your@email.com --spotify wrapped.json

  # Import Apple Music data
  python -m concert_monitor --user your@email.com --apple replay.json
        """
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode with sample data"
    )
    parser.add_argument(
        "--user",
        type=str,
        help="User email address"
    )
    parser.add_argument(
        "--spotify",
        type=str,
        help="Path to Spotify Wrapped JSON file"
    )
    parser.add_argument(
        "--apple",
        type=str,
        help="Path to Apple Music Replay JSON file"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to configuration file"
    )

    args = parser.parse_args()

    if args.demo:
        asyncio.run(run_demo())
    elif args.user:
        asyncio.run(run_for_user(
            email=args.user,
            spotify_file=args.spotify,
            apple_file=args.apple,
        ))
    else:
        parser.print_help()
        print("\n❌ Please specify --demo or --user")
        sys.exit(1)


if __name__ == "__main__":
    main()
