"""Fixed-step leader search and acceleration, following the original truck model."""

from dataclasses import dataclass
import math

TIME_STEP = 1.0
TRUCK_LENGTH = 15.0
LOOKAHEAD_DISTANCE = 300.0
ACCELERATION = 3.6
DECELERATION = 1.6
HEADWAY = 2.0
MIN_GAP = 25.0
EXPONENT = 4


@dataclass(frozen=True)
class MotionSample:
    time_seconds: float
    truck: str
    assignment: int
    loaded: bool
    distance_m: float
    speed_m_s: float
    segment: str


class TargetAsPotentialLeader:
    current_speed = 0.0
    is_node = True


class VehicleMotion:
    """Position is the rear of a truck; the destination is a stop line."""

    def __init__(self, network, occupancy, route, loaded, speed):
        self.network, self.occupancy = network, occupancy
        self.route = list(reversed(route)) if loaded else list(route)
        self.loaded, self.speed = loaded, speed
        self.current_edge_index = 0
        self.position = 0.0
        self.current_speed = 0.0
        self.length = TRUCK_LENGTH
        self.is_node = False
        self.leader = None
        self.leader_distance = None
        self.completed_length = 0.0

    @property
    def key(self):
        return self.route[self.current_edge_index], self.loaded

    @property
    def distance(self):
        return self.completed_length + self.position

    def can_enter(self):
        return all(v.position >= self.length + MIN_GAP for v in self.occupancy.get(self.key, []))

    def enter(self):
        self.occupancy.setdefault(self.key, []).append(self)

    def leave(self):
        if self in self.occupancy.get(self.key, []):
            self.occupancy[self.key].remove(self)

    def update_leader(self):
        self.leader = None
        self.leader_distance = None
        offset = -self.position
        for index in range(self.current_edge_index, len(self.route)):
            edge = self.network.edges[self.route[index]]
            for truck in sorted(self.occupancy.get((edge.id, self.loaded), []), key=lambda v: v.position):
                if truck is self:
                    continue
                ahead = offset + truck.position
                gap = max(0.0, ahead - self.length)
                if 0 <= ahead <= LOOKAHEAD_DISTANCE and (self.leader_distance is None or gap < self.leader_distance):
                    self.leader, self.leader_distance = truck, gap
            if self.leader is not None:
                return
            if index == len(self.route) - 1:
                gap = max(0.0, offset + edge.length_m - self.length)
                if gap <= LOOKAHEAD_DISTANCE:
                    self.leader = TargetAsPotentialLeader()
                    self.leader_distance = gap
                    return
            offset += edge.length_m
            if offset > LOOKAHEAD_DISTANCE:
                return

    def calculate_acceleration(self):
        if self.leader is not None:
            delta_v = self.current_speed - self.leader.current_speed
            desired_gap = max(0.0, self.current_speed * HEADWAY +
                self.current_speed * delta_v / (2 * math.sqrt(ACCELERATION * DECELERATION)))
            if not self.leader.is_node:
                desired_gap += MIN_GAP
            gap = max(self.leader_distance, 1e-6)
            return ACCELERATION * (1 - (self.current_speed / self.speed) ** EXPONENT - (desired_gap / gap) ** 2)
        return ACCELERATION if self.current_speed <= self.speed else 0.0

    def advance(self):
        # Same order as the source: leader -> acceleration -> speed -> position.
        self.update_leader()
        acceleration = self.calculate_acceleration()
        speed = min(self.speed, max(0.0, self.current_speed + acceleration * TIME_STEP))
        movement = speed * TIME_STEP
        if self.leader is not None:
            movement = min(movement, max(0.0, self.leader_distance))
            speed = movement / TIME_STEP
        self.current_speed = speed
        self.position += movement
        last = self.current_edge_index == len(self.route) - 1
        return last and self.leader is not None and self.leader.is_node and speed == 0.0 and self.leader_distance <= 0.05

    def cross_edges(self):
        while self.current_edge_index < len(self.route) - 1:
            edge = self.network.edges[self.route[self.current_edge_index]]
            if self.position < edge.length_m:
                break
            self.leave()
            self.position -= edge.length_m
            self.completed_length += edge.length_m
            self.current_edge_index += 1
            self.enter()
