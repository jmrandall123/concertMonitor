"""Base agent framework for zero-state agents."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID, uuid4
import json
import logging

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Status of agent execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # Some results, but with errors


@dataclass
class AgentContext:
    """
    Context passed to agents for execution.

    Zero-state means all context needed for execution must be provided here.
    Agents don't maintain internal state between invocations.
    """
    # Execution context
    execution_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # User context (optional, depends on agent)
    user_id: Optional[UUID] = None
    user_data: Optional[dict] = None

    # Input data for the agent
    input_data: dict = field(default_factory=dict)

    # Configuration overrides
    config: dict = field(default_factory=dict)

    # Parent execution context (for chained agents)
    parent_execution_id: Optional[UUID] = None

    # Timeout settings
    timeout_seconds: int = 300  # 5 minutes default

    def with_input(self, **kwargs) -> "AgentContext":
        """Create new context with additional input data."""
        new_input = {**self.input_data, **kwargs}
        return AgentContext(
            execution_id=uuid4(),
            timestamp=datetime.utcnow(),
            user_id=self.user_id,
            user_data=self.user_data,
            input_data=new_input,
            config=self.config,
            parent_execution_id=self.execution_id,
            timeout_seconds=self.timeout_seconds,
        )


# Type variable for result data
T = TypeVar("T")


@dataclass
class AgentResult(Generic[T]):
    """
    Result from agent execution.

    Contains the output data, status, and any errors or metadata.
    """
    # Execution reference
    execution_id: UUID = field(default_factory=uuid4)
    agent_name: str = ""

    # Status
    status: AgentStatus = AgentStatus.PENDING

    # Output data (typed)
    data: Optional[T] = None

    # Error information
    error: Optional[str] = None
    error_details: Optional[dict] = None

    # Execution metadata
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # Metrics
    items_processed: int = 0
    items_failed: int = 0

    # Debug/tracing
    trace: list[str] = field(default_factory=list)

    def success(self, data: T, items_processed: int = 0) -> "AgentResult[T]":
        """Mark result as successful with data."""
        self.status = AgentStatus.SUCCESS
        self.data = data
        self.items_processed = items_processed
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )
        return self

    def fail(self, error: str, details: Optional[dict] = None) -> "AgentResult[T]":
        """Mark result as failed with error."""
        self.status = AgentStatus.FAILED
        self.error = error
        self.error_details = details
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )
        return self

    def partial(
        self,
        data: T,
        error: str,
        items_processed: int = 0,
        items_failed: int = 0
    ) -> "AgentResult[T]":
        """Mark result as partial success."""
        self.status = AgentStatus.PARTIAL
        self.data = data
        self.error = error
        self.items_processed = items_processed
        self.items_failed = items_failed
        self.completed_at = datetime.utcnow()
        return self

    def add_trace(self, message: str) -> None:
        """Add trace message for debugging."""
        timestamp = datetime.utcnow().isoformat()
        self.trace.append(f"[{timestamp}] {message}")

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "execution_id": str(self.execution_id),
            "agent_name": self.agent_name,
            "status": self.status.value,
            "data": self.data if not hasattr(self.data, "to_dict") else self.data.to_dict(),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "items_processed": self.items_processed,
            "items_failed": self.items_failed,
        }


class Agent(ABC, Generic[T]):
    """
    Base class for zero-state agents.

    Zero-state means:
    - No internal state between invocations
    - All context provided via AgentContext
    - Deterministic given same input
    - Can be scaled horizontally
    - Easy to test and debug

    Subclasses must implement:
    - name: Agent identifier
    - execute(): Main execution logic
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this agent."""
        pass

    @property
    def version(self) -> str:
        """Agent version for tracking."""
        return "1.0.0"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return ""

    async def run(self, context: AgentContext) -> AgentResult[T]:
        """
        Execute the agent with given context.

        This is the main entry point. It handles:
        - Result initialization
        - Error handling
        - Logging
        - Metrics

        Subclasses should override execute() instead.
        """
        result = AgentResult[T](
            execution_id=context.execution_id,
            agent_name=self.name,
            status=AgentStatus.RUNNING,
            started_at=datetime.utcnow(),
        )

        logger.info(
            f"Agent '{self.name}' starting execution",
            extra={
                "execution_id": str(context.execution_id),
                "user_id": str(context.user_id) if context.user_id else None,
            }
        )
        result.add_trace(f"Starting {self.name} v{self.version}")

        try:
            # Validate input
            validation_error = self.validate(context)
            if validation_error:
                return result.fail(f"Validation error: {validation_error}")

            result.add_trace("Validation passed")

            # Execute agent logic
            result = await self.execute(context, result)

            result.add_trace(f"Execution complete: {result.status.value}")

        except Exception as e:
            logger.exception(f"Agent '{self.name}' failed with exception")
            result.fail(str(e), {"exception_type": type(e).__name__})
            result.add_trace(f"Exception: {e}")

        logger.info(
            f"Agent '{self.name}' completed",
            extra={
                "execution_id": str(context.execution_id),
                "status": result.status.value,
                "duration_ms": result.duration_ms,
            }
        )

        return result

    @abstractmethod
    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[T]
    ) -> AgentResult[T]:
        """
        Execute the agent's main logic.

        Args:
            context: Execution context with all input data
            result: Pre-initialized result object to populate

        Returns:
            AgentResult with status and output data
        """
        pass

    def validate(self, context: AgentContext) -> Optional[str]:
        """
        Validate input context before execution.

        Returns:
            Error message if validation fails, None if valid
        """
        return None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', version='{self.version}')"


class CompositeAgent(Agent[T]):
    """
    Agent that composes multiple sub-agents.

    Useful for creating pipelines or parallel execution.
    """

    def __init__(self, agents: list[Agent]):
        self.agents = agents

    @property
    def name(self) -> str:
        agent_names = ", ".join(a.name for a in self.agents)
        return f"composite[{agent_names}]"

    async def execute_sequential(
        self,
        context: AgentContext
    ) -> list[AgentResult]:
        """Execute agents in sequence, passing results forward."""
        results = []
        current_context = context

        for agent in self.agents:
            result = await agent.run(current_context)
            results.append(result)

            if result.status == AgentStatus.FAILED:
                break

            # Pass result data to next agent
            if result.data:
                current_context = current_context.with_input(
                    previous_result=result.data
                )

        return results

    async def execute_parallel(
        self,
        context: AgentContext
    ) -> list[AgentResult]:
        """Execute all agents in parallel."""
        import asyncio

        tasks = [agent.run(context) for agent in self.agents]
        return await asyncio.gather(*tasks)

    async def execute(
        self,
        context: AgentContext,
        result: AgentResult[T]
    ) -> AgentResult[T]:
        """Default to sequential execution."""
        results = await self.execute_sequential(context)

        # Aggregate results
        all_success = all(r.status == AgentStatus.SUCCESS for r in results)
        any_success = any(r.status == AgentStatus.SUCCESS for r in results)

        if all_success:
            return result.success(
                data=[r.data for r in results],
                items_processed=sum(r.items_processed for r in results)
            )
        elif any_success:
            failed = [r for r in results if r.status == AgentStatus.FAILED]
            return result.partial(
                data=[r.data for r in results if r.data],
                error=f"{len(failed)} sub-agents failed",
                items_processed=sum(r.items_processed for r in results),
                items_failed=len(failed)
            )
        else:
            return result.fail("All sub-agents failed")
