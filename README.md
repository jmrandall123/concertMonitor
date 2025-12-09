# Concert Monitor Agent System

An intelligent, zero-state agent architecture for monitoring upcoming concerts and events, matching them to user preferences, and automatically managing calendar invites and email digests.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ORCHESTRATOR                                       │
│  Coordinates all agents, manages workflow, handles scheduling                │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │                    │
         ▼                    ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  PREFERENCE     │  │    DISCOVERY    │  │     RATING      │  │    CALENDAR     │
│    AGENT        │  │     AGENTS      │  │     AGENT       │  │     AGENT       │
│                 │  │                 │  │                 │  │                 │
│ • Parse Spotify │  │ • Ticketmaster  │  │ • Genre match   │  │ • Google Cal    │
│ • Parse Apple   │  │ • Bandsintown   │  │ • Artist match  │  │ • Apple Cal     │
│ • Chat extract  │  │ • SeatGeek      │  │ • Venue pref    │  │ • ICS export    │
│ • Learn from FB │  │ • Songkick      │  │ • Date pref     │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │                    │
         ▼                    ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                           │
│  User Profiles │ Events │ Ratings │ Feedback │ Preferences                  │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      EMAIL DIGEST AGENT                                      │
│  Generates personalized weekly/daily digests of recommended events          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Features

- **Zero-State Agents**: Each agent is stateless and can be invoked independently
- **Multi-Source Discovery**: Aggregates events from Ticketmaster, Bandsintown, SeatGeek, etc.
- **Smart Rating System**: 1-10 rating based on user preferences with explainability
- **Automatic Calendar Integration**: Events rated 8+ automatically added to calendar
- **Email Digests**: Weekly/daily digests for events rated 7+
- **Preference Learning**: Improves recommendations based on user feedback (yes/no/maybe)

## Rating Thresholds

| Rating | Action |
|--------|--------|
| 8-10   | Auto-add to calendar with notification |
| 7      | Include in email digest, suggest adding |
| 5-6    | Include in digest as "might interest you" |
| 1-4    | Not shown unless specifically browsing |

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure API keys in `.env`:
   ```
   TICKETMASTER_API_KEY=...
   SPOTIFY_CLIENT_ID=...
   SPOTIFY_CLIENT_SECRET=...
   GOOGLE_CALENDAR_CREDENTIALS=...
   OPENAI_API_KEY=...  # For AI-powered matching
   ```

3. Run the orchestrator:
   ```bash
   python -m concert_monitor.main
   ```

## Project Structure

```
concert_monitor/
├── agents/                 # Zero-state agent implementations
│   ├── base.py            # Base agent class
│   ├── preference_agent.py # User preference extraction
│   ├── discovery/         # Event discovery agents
│   │   ├── ticketmaster.py
│   │   ├── bandsintown.py
│   │   └── seatgeek.py
│   ├── rating_agent.py    # Event rating logic
│   ├── calendar_agent.py  # Calendar integration
│   └── digest_agent.py    # Email digest generation
├── models/                # Data models
│   ├── user.py
│   ├── event.py
│   ├── preference.py
│   └── rating.py
├── services/              # External service integrations
│   ├── spotify.py
│   ├── apple_music.py
│   ├── google_calendar.py
│   └── email.py
├── orchestrator.py        # Main orchestration logic
├── config.py              # Configuration management
└── main.py               # Entry point
```

## License

MIT
