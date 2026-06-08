"""orca_code.core.event_bus — Publish-subscribe event bus for agent communication.

Inspired by Proma's AgentEventBus: decouples the main loop, tool execution,
sub-agent lifecycle, and UI rendering through typed events.

Event types:
  tool_start, tool_result, tool_error     — tool execution lifecycle
  agent_start, agent_done, agent_error    — sub-agent lifecycle
  stream_chunk, stream_done               — LLM streaming
  permission_request, permission_result   — permission flow
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Callable, Dict, List


class EventType(Enum):
    """Standard event types in the Orca Code event system."""
    # Tool lifecycle
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # Sub-agent lifecycle
    AGENT_START = "agent_start"
    AGENT_DONE = "agent_done"
    AGENT_ERROR = "agent_error"

    # LLM streaming
    STREAM_CHUNK = "stream_chunk"
    STREAM_DONE = "stream_done"
    STREAM_ERROR = "stream_error"

    # Permission
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESULT = "permission_result"

    # Session
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Memory
    MEMORY_SAVED = "memory_saved"
    MEMORY_SEARCHED = "memory_searched"

    # Task system (TaskCreate/Update/Get/List)
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_DELETED = "task_deleted"


class AgentEvent:
    """An event in the Orca Code event system.

    Attributes:
        type: The event type.
        data: Event payload (varies by type).
        timestamp: Unix timestamp when the event was created.
        source: Optional identifier of the component that emitted the event.
    """

    def __init__(self, event_type: EventType, data: Any = None, source: str = ""):
        import time
        self.type = event_type
        self.data = data
        self.timestamp = time.time()
        self.source = source

    def __repr__(self) -> str:
        return f"AgentEvent({self.type.value}, src={self.source or '?'})"


EventCallback = Callable[[AgentEvent], None]


class EventBus:
    """Thread-safe publish-subscribe event bus.

    Usage:
        bus = EventBus()

        @bus.on(EventType.TOOL_START)
        def log_tool_start(event: AgentEvent):
            print(f"Tool started: {event.data}")

        bus.emit(AgentEvent(EventType.TOOL_START, {"name": "read_file"}))

        bus.off(EventType.TOOL_START, log_tool_start)
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[EventCallback]] = {
            et: [] for et in EventType
        }
        self._lock = threading.Lock()

    def on(self, event_type: EventType) -> Callable[[EventCallback], EventCallback]:
        """Decorator: register a callback for an event type.

        Usage:
            @bus.on(EventType.TOOL_START)
            def handler(event): ...
        """
        def decorator(callback: EventCallback) -> EventCallback:
            self.subscribe(event_type, callback)
            return callback
        return decorator

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """Register a callback for an event type."""
        with self._lock:
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """Remove a callback for an event type."""
        with self._lock:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass

    def emit(self, event: AgentEvent) -> None:
        """Publish an event to all subscribers. Errors in callbacks are logged
        but never propagated — one misbehaving subscriber must not break others."""
        with self._lock:
            subscribers = list(self._subscribers[event.type])

        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "EventBus: unhandled error in subscriber %s for event %s",
                    getattr(callback, "__name__", str(callback)),
                    event.type.value,
                )

    def clear(self) -> None:
        """Remove all subscribers from all event types."""
        with self._lock:
            for et in EventType:
                self._subscribers[et].clear()

    @property
    def subscriber_count(self) -> Dict[EventType, int]:
        """Return a mapping of event types to subscriber counts (for debugging)."""
        with self._lock:
            return {et: len(subs) for et, subs in self._subscribers.items()}


# Global event bus instance (singleton for the process)
_event_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get or create the global EventBus singleton."""
    global _event_bus
    if _event_bus is None:
        with _bus_lock:
            if _event_bus is None:
                _event_bus = EventBus()
    return _event_bus
