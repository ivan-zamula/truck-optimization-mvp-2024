"""Typed request models for the local simulation API."""

from dataclasses import asdict
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .model import Assignment, Event, ExcavatorSpec, Result, Scenario, TruckSpec
from .network import RoadEdge, RoadNode
from .motion import MotionSample

PositiveNumber = Annotated[float, Field(gt=0, strict=True, allow_inf_nan=False)]
EquipmentId = Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,16}$", strict=True)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TruckInput(RequestModel):
    id: EquipmentId
    capacity_m3: Annotated[float, Field(ge=1, strict=True, allow_inf_nan=False)]
    empty_speed_m_s: PositiveNumber
    unloading_seconds: PositiveNumber


class ExcavatorInput(RequestModel):
    id: EquipmentId
    rate_m3_h: PositiveNumber
    distance_m: PositiveNumber


class ScenarioRequest(RequestModel):
    trucks: list[TruckInput] = Field(
        default_factory=lambda: [TruckInput(**asdict(t)) for t in Scenario().trucks],
        min_length=1, max_length=6,
    )
    excavators: list[ExcavatorInput] = Field(
        default_factory=lambda: [ExcavatorInput(**asdict(e)) for e in Scenario().excavators],
        min_length=1, max_length=4,
    )
    target_m3: Annotated[float, Field(gt=0, le=10000, strict=True, allow_inf_nan=False)] = 120.0
    time_limit_seconds: Annotated[float, Field(gt=0, le=86400, strict=True, allow_inf_nan=False)] = 1800.0
    policy: Literal["earliest_delivery", "round_robin"] = "earliest_delivery"

    def to_scenario(self) -> Scenario:
        return Scenario(
            trucks=tuple(TruckSpec(**t.model_dump()) for t in self.trucks),
            excavators=tuple(ExcavatorSpec(**e.model_dump()) for e in self.excavators),
            target_m3=self.target_m3,
            time_limit_seconds=self.time_limit_seconds,
            policy=self.policy,
        )


class ErrorResponse(BaseModel):
    error: str


class NetworkResponse(BaseModel):
    nodes: dict[str, RoadNode]
    edges: dict[str, RoadEdge]
    routes: dict[str, list[str]]
    destinations: dict[str, str]
    bounds: list[float]
    meters_per_unit: float


class SimulationResponse(BaseModel):
    scenario: ScenarioRequest
    summary: Result
    network: NetworkResponse
    assignments: list[Assignment]
    events: list[Event]
    motion: list[MotionSample]
