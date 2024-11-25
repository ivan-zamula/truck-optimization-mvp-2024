"""Volume planning for different trucks on synthetic routes."""

from dataclasses import dataclass
import math
import re
import salabim as sim
from .network import RoadNetwork
from .motion import MotionSample, TIME_STEP, VehicleMotion

EPS = 1e-9


def positive(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class TruckSpec:
    id: str
    capacity_m3: float
    empty_speed_m_s: float
    unloading_seconds: float

    @property
    def loaded_speed_m_s(self):
        return self.empty_speed_m_s * 0.5


@dataclass(frozen=True)
class ExcavatorSpec:
    id: str
    rate_m3_h: float
    distance_m: float


@dataclass(frozen=True)
class Scenario:
    trucks: tuple[TruckSpec, ...] = (
        TruckSpec("T1", 8.0, 12.0, 15.0),
        TruckSpec("T2", 12.0, 11.0, 20.0),
        TruckSpec("T3", 16.0, 10.0, 25.0),
        TruckSpec("T4", 10.0, 13.0, 18.0),
        TruckSpec("T5", 14.0, 9.0, 22.0),
    )
    excavators: tuple[ExcavatorSpec, ...] = (
        ExcavatorSpec("E1", 144.0, 300.0),
        ExcavatorSpec("E2", 216.0, 600.0),
        ExcavatorSpec("E3", 180.0, 450.0),
    )
    target_m3: float = 120.0
    time_limit_seconds: float = 1800.0
    policy: str = "earliest_delivery"

    def __post_init__(self):
        positive("target_m3", self.target_m3)
        positive("time_limit_seconds", self.time_limit_seconds)
        if self.policy not in ("earliest_delivery", "round_robin"):
            raise ValueError("Unknown dispatch policy")
        if not self.trucks or not self.excavators:
            raise ValueError("Provide trucks and excavators")
        for group in (self.trucks, self.excavators):
            ids = [spec.id for spec in group]
            if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z0-9-]{1,16}", id) for id in ids):
                raise ValueError("Equipment IDs must be unique letters, digits or hyphens")
            for spec in group:
                for name, value in vars(spec).items():
                    if name != "id":
                        positive(name, value)


@dataclass
class Assignment:
    id: int
    truck: str
    excavator: str
    volume_m3: float
    empty_start: float
    predicted_finish: float
    empty_end: float | None = None
    loading_start: float | None = None
    loading_end: float | None = None
    loaded_end: float | None = None
    unloading_start: float | None = None
    unloading_end: float | None = None


@dataclass(frozen=True)
class Event:
    time_seconds: float
    truck: str
    excavator: str
    assignment: int
    action: str
    cargo_m3: float
    volume_m3: float
    segment: str = ""


@dataclass(frozen=True)
class Result:
    target_m3: float
    delivered_m3: float
    deficit_m3: float
    plan_met: bool
    elapsed_seconds: float
    completed_trips: int
    trucks: list[dict]
    excavators: list[dict]


class Dispatcher:
    """Reserve service slots and compare the next delivery time at each excavator."""

    def __init__(self, model):
        self.model = model
        self.loader_free = {e.id: 0.0 for e in model.scenario.excavators}
        self.unloader_free = 0.0
        self.reserved_m3 = 0.0
        self.sequence = 0

    def assign(self, truck):
        model = self.model
        remaining = model.scenario.target_m3 - model.delivered_m3 - self.reserved_m3
        if remaining <= EPS:
            return None
        volume = min(truck.capacity_m3, remaining)
        candidates = []
        now = model.env.now()
        for excavator in model.scenario.excavators:
            distance = model.network.route_distance(excavator.id)
            arrival = now + distance / truck.empty_speed_m_s
            load_start = max(arrival, self.loader_free[excavator.id])
            load_end = load_start + volume / excavator.rate_m3_h * 3600
            loaded_end = load_end + distance / truck.loaded_speed_m_s
            unload_start = max(loaded_end, self.unloader_free)
            finish = unload_start + truck.unloading_seconds
            if finish <= model.scenario.time_limit_seconds:
                candidates.append((finish, excavator.id, load_end))
        if not candidates:
            return None
        if model.scenario.policy == "earliest_delivery":
            chosen = min(candidates)
        else:
            order = [e.id for e in model.scenario.excavators]
            preferred = order[self.sequence % len(order)]
            chosen = next((a for a in candidates if a[1] == preferred), candidates[0])
        self.sequence += 1
        finish, excavator, load_end = chosen
        self.loader_free[excavator] = load_end
        self.unloader_free = finish
        self.reserved_m3 += volume
        assignment = Assignment(len(model.assignments) + 1, truck.id, excavator, volume, now, finish)
        model.assignments.append(assignment)
        return assignment


class Truck(sim.Component):
    def setup(self, model, spec):
        self.model, self.spec = model, spec
        self.cargo_m3 = 0.0
        self.completed_trips = 0
        self.motion_state = None

    def record(self, action, a, segment=""):
        self.model.events.append(Event(self.env.now(), self.spec.id, a.excavator,
            a.id, action, self.cargo_m3, a.volume_m3, segment))

    def travel(self, assignment, loaded):
        if self.motion_state is not None:
            self.motion_state.leave()
        speed = self.spec.loaded_speed_m_s if loaded else self.spec.empty_speed_m_s
        state = VehicleMotion(self.model.network, self.model.occupancy,
            self.model.network.routes[assignment.excavator], loaded, speed)
        self.motion_state = state
        def sample():
            self.model.motion.append(MotionSample(self.env.now(), self.spec.id, assignment.id,
                loaded, state.distance, state.current_speed, state.key[0]))
        while not state.can_enter():
            sample()
            yield self.hold(TIME_STEP)
        state.enter()
        self.record("road_enter", assignment, state.key[0])
        sample()
        while True:
            previous = state.key[0]
            arrived = state.advance()
            yield self.hold(TIME_STEP)
            sample()
            if arrived:
                self.record("road_exit", assignment, state.key[0])
                return
            state.cross_edges()
            if state.key[0] != previous:
                self.record("road_exit", assignment, previous)
                self.record("road_enter", assignment, state.key[0])
                sample()

    def process(self):
        model = self.model
        while (a := model.dispatcher.assign(self.spec)) is not None:
            self.record("empty_start", a)
            yield from self.travel(a, loaded=False)
            a.empty_end = self.env.now()
            self.record("empty_end", a)
            yield self.request(model.loaders[a.excavator])
            a.loading_start = self.env.now()
            self.record("loading_start", a)
            excavator = next(e for e in model.scenario.excavators if e.id == a.excavator)
            yield self.hold(a.volume_m3 / excavator.rate_m3_h * 3600)
            a.loading_end = self.env.now()
            model.dispatcher.loader_free[a.excavator] = max(model.dispatcher.loader_free[a.excavator], a.loading_end)
            self.cargo_m3 = a.volume_m3
            self.record("loading_end", a)
            self.release(model.loaders[a.excavator])
            self.record("loaded_start", a)
            yield from self.travel(a, loaded=True)
            a.loaded_end = self.env.now()
            self.record("loaded_end", a)
            yield self.request(model.unloader)
            a.unloading_start = self.env.now()
            self.record("unloading_start", a)
            yield self.hold(self.spec.unloading_seconds)
            a.unloading_end = self.env.now()
            model.dispatcher.unloader_free = max(model.dispatcher.unloader_free, a.unloading_end)
            model.delivered_m3 += self.cargo_m3
            model.dispatcher.reserved_m3 -= self.cargo_m3
            self.cargo_m3 = 0.0
            self.completed_trips += 1
            self.record("unloading_end", a)
            self.release(model.unloader)
            if model.delivered_m3 >= model.scenario.target_m3 - EPS:
                model.plan_time = self.env.now()
        if self.motion_state is not None:
            self.motion_state.leave()


class Simulation:
    def __init__(self, scenario=None):
        self.scenario = scenario or Scenario()
        self.network = RoadNetwork(self.scenario.excavators)
        self.env = sim.Environment(trace=False, time_unit="seconds", yieldless=False,
                                   set_numpy_random_seed=False)
        self.loaders = {e.id: sim.Resource(e.id, capacity=1, env=self.env)
                        for e in self.scenario.excavators}
        self.unloader = sim.Resource("unloader", capacity=1, env=self.env)
        self.assignments, self.events = [], []
        self.occupancy, self.motion = {}, []
        self.delivered_m3 = 0.0
        self.plan_time = None
        self.dispatcher = Dispatcher(self)
        self.trucks = [Truck(model=self, spec=spec, env=self.env) for spec in self.scenario.trucks]

    def run(self):
        self.env.run(till=self.scenario.time_limit_seconds)
        elapsed = self.plan_time if self.plan_time is not None else self.scenario.time_limit_seconds
        def interval(start, end):
            if start is None:
                return 0.0
            return max(0.0, min(elapsed, end if end is not None else elapsed) - start)
        trucks = []
        for truck in self.trucks:
            jobs = [a for a in self.assignments if a.truck == truck.spec.id]
            working = sum(interval(a.empty_start, a.empty_end) + interval(a.loading_start, a.loading_end)
                          + interval(a.loading_end, a.loaded_end) + interval(a.unloading_start, a.unloading_end) for a in jobs)
            waiting = sum(interval(a.empty_end, a.loading_start) + interval(a.loaded_end, a.unloading_start) for a in jobs)
            trucks.append({"id": truck.spec.id, "capacity_m3": truck.spec.capacity_m3,
                "completed_trips": truck.completed_trips, "delivered_m3": sum(a.volume_m3 for a in jobs if a.unloading_end is not None),
                "working_seconds": working, "waiting_seconds": waiting,
                "idle_seconds": max(0.0, elapsed - working - waiting), "utilization": working / elapsed})
        excavators = []
        for spec in self.scenario.excavators:
            busy = sum(interval(a.loading_start, a.loading_end) for a in self.assignments if a.excavator == spec.id)
            excavators.append({"id": spec.id, "busy_seconds": busy, "utilization": busy / elapsed})
        return Result(self.scenario.target_m3, self.delivered_m3,
            max(0.0, self.scenario.target_m3 - self.delivered_m3), self.plan_time is not None,
            elapsed, sum(t.completed_trips for t in self.trucks), trucks, excavators)
