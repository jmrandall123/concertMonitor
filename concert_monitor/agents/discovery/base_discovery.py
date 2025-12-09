"""Base class for event discovery agents."""

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..base import Agent, AgentContext, AgentResult
from ...models.event import Event, EventSource


@dataclass
class DiscoveryResult:
    """Result from event discovery."""
    events: list[Event] = field(default_factory=list)
    source: EventSource = EventSource.MANUAL
    total_found: int = 0
    has_more: bool = False
    next_page_token: Optional[str] = None


class DiscoveryAgent(Agent[DiscoveryResult]):
    """
    Base class for event discovery agents.

    Each discovery agent searches a specific source (Ticketmaster, Bandsintown, etc.)
    for events matching the search criteria.
    """

    @property
    @abstractmethod
    def source(self) -> EventSource:
        """The event source this agent discovers from."""
        pass

    def validate(self, context: AgentContext) -> Optional[str]:
        """Validate discovery search parameters."""
        input_data = context.input_data

        # Need either location or artists to search
        has_location = bool(
            input_data.get("city") or
            input_data.get("latitude") or
            input_data.get("location")
        )
        has_artists = bool(input_data.get("artists"))

        if not has_location and not has_artists:
            return "Either location or artists required for discovery"

        return None

    @abstractmethod
    async def search_events(
        self,
        context: AgentContext,
    ) -> list[Event]:
        """
        Search for events from this source.

        Override this in subclasses to implement source-specific logic.
        """
        pass

    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[DiscoveryResult]
    ) -> AgentResult[DiscoveryResult]:
        """Execute event discovery."""
        result.add_trace(f"Starting discovery from {self.source.value}")

        try:
            events = await self.search_events(context)

            discovery_result = DiscoveryResult(
                events=events,
                source=self.source,
                total_found=len(events),
            )

            result.add_trace(f"Found {len(events)} events")
            return result.success(discovery_result, len(events))

        except Exception as e:
            result.add_trace(f"Discovery failed: {e}")
            return result.fail(str(e))
