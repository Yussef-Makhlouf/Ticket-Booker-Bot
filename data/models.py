"""
Pydantic data models for the booking system.
Shared across services, handlers, and core engine.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
import time


class BookingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    PAYMENT_PENDING = "payment_pending"
    CANCELLED = "cancelled"


class SeatSource(str, Enum):
    DOM = "dom"
    CANVAS = "canvas"
    API = "api"
    OCR = "ocr"


@dataclass
class Seat:
    """Represents a single seat on the venue map."""
    id: str = ""
    section: str = ""
    row: str = ""
    number: str = ""
    price: int = 0
    is_available: bool = True
    click_x: float = 0.0
    click_y: float = 0.0
    click_selector: str = ""

    @property
    def display_name(self) -> str:
        parts = [self.section, self.row, self.number]
        return "-".join(p for p in parts if p)


@dataclass
class SeatMap:
    """Result of seat map analysis."""
    source: SeatSource = SeatSource.DOM
    seats: List[Seat] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)
    section_coordinates: Dict[str, tuple] = field(default_factory=dict)
    canvas_width: float = 0.0
    canvas_height: float = 0.0
    scan_time: float = 0.0

    @property
    def available_count(self) -> int:
        return sum(1 for s in self.seats if s.is_available)


@dataclass
class PriceTier:
    """A pricing tier / category."""
    id: str = ""
    name: str = ""
    price: int = 0
    section: str = ""
    available_seats: int = 0
    popularity_score: float = 0.0


@dataclass
class EventData:
    """Extracted event information."""
    name: str = ""
    event_type: str = "general"  # match, concert, general
    teams: List[str] = field(default_factory=list)
    date: str = ""
    time: str = ""
    venue: str = ""
    city: str = ""
    price_range: Dict[str, int] = field(default_factory=lambda: {"min": 0, "max": 0})
    sections: List[Dict[str, str]] = field(default_factory=list)
    image_url: str = ""
    description: str = ""
    url: str = ""
    is_logged_in: bool = False
    extraction_time: float = 0.0


@dataclass
class UserPrefs:
    """User booking preferences."""
    user_id: int = 0
    budget_conscious: bool = True
    preferred_section: str = ""
    preferred_price_max: int = 0
    auto_select_best: bool = True


@dataclass
class BookingRequest:
    """A complete booking request."""
    user_id: int = 0
    event_url: str = ""
    tickets: int = 1
    team: str = ""
    section: str = ""
    price_tier: str = ""
    preferences: UserPrefs = field(default_factory=UserPrefs)
    timestamp: float = field(default_factory=time.time)

    @property
    def booking_url(self) -> str:
        base = self.event_url.split("?")[0]
        if base.endswith("/book"):
            return base
        return base.rstrip("/") + "/book"


@dataclass
class BookingResult:
    """Result of a booking attempt."""
    success: bool = False
    error_code: str = ""
    message: str = ""
    checkout_url: str = ""
    event_name: str = ""
    tickets: int = 0
    section: str = ""
    seats: List[str] = field(default_factory=list)
    total_price: int = 0
    duration: float = 0.0
    attempts: int = 0
    action_required: str = ""
    debug_info: Dict[str, Any] = field(default_factory=dict)
    screenshot_path: str = ""


@dataclass
class BookingPrep:
    """Pre-processed booking data from parallel preparation."""
    event_data: EventData = field(default_factory=EventData)
    is_logged_in: bool = False
    seat_map: Optional[SeatMap] = None
    price_tiers: List[PriceTier] = field(default_factory=list)
    prep_time: float = 0.0


@dataclass
class HealthStatus:
    """System health snapshot."""
    uptime_seconds: float = 0.0
    total_bookings: int = 0
    successful_bookings: int = 0
    failed_bookings: int = 0
    success_rate: float = 0.0
    avg_booking_time: float = 0.0
    active_browsers: int = 0
    pool_size: int = 0
    cache_hit_rate: float = 0.0
    last_error: str = ""
    last_error_time: float = 0.0
