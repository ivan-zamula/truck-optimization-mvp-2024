"""A fictional tree of shared roads and branches to loading sites."""

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class RoadNode:
    id: str
    x: float
    y: float
    label: str
    kind: str


@dataclass(frozen=True)
class RoadEdge:
    id: str
    source: str
    target: str
    length_m: float


class RoadNetwork:
    def __init__(self, excavators):
        self.nodes = {
            "delivery": RoadNode("delivery", 0, 0, "Delivery point", "delivery"),
        }
        self.edges = {}
        self.routes = {}
        self.destinations = {}
        shortest = min(e.distance_m for e in excavators)
        self.nodes["J1"] = RoadNode("J1", -shortest * 0.25, 0, "J1", "junction")
        self.add_edge("main", "delivery", "J1", shortest * 0.25)
        directions = [(200, 220), (180, 170), (125, 155), (265, 230)]
        for i, spec in enumerate(excavators):
            upper = i % 4 in (0, 3)
            junction = "J2" if upper else "J3"
            if junction not in self.nodes:
                x, y = self.offset(self.nodes["J1"], shortest * 0.15, 210 if upper else 150)
                self.nodes[junction] = RoadNode(junction, x, y, junction, "junction")
                self.add_edge(junction, "J1", junction, shortest * 0.15)
            end_id, bend_id = "exc:" + spec.id, "bend:" + spec.id
            source = self.nodes[junction]
            remaining = spec.distance_m - shortest * 0.4
            length1 = remaining * 0.4
            angle1, angle2 = directions[i % 4]
            bend = self.offset(source, length1, angle1)
            self.nodes[bend_id] = RoadNode(bend_id, *bend, "", "bend")
            position = self.offset(self.nodes[bend_id], remaining - length1, angle2)
            self.nodes[end_id] = RoadNode(end_id, *position, spec.id, "excavator")
            edge1, edge2 = spec.id + "-approach", spec.id + "-access"
            self.add_edge(edge1, junction, bend_id, length1)
            self.add_edge(edge2, bend_id, end_id, remaining - length1)
            self.routes[spec.id] = ["main", junction, edge1, edge2]
            self.destinations[spec.id] = end_id

    @staticmethod
    def offset(source, length, degrees):
        angle = math.radians(degrees)
        return source.x + length * math.cos(angle), source.y + length * math.sin(angle)

    def add_edge(self, id, source, target, length):
        self.edges[id] = RoadEdge(id, source, target, length)

    def route_distance(self, excavator):
        return sum(self.edges[id].length_m for id in self.routes[excavator])

    def to_dict(self):
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        return {"nodes": {id: asdict(node) for id, node in self.nodes.items()},
                "edges": {id: asdict(edge) for id, edge in self.edges.items()},
                "routes": self.routes, "destinations": self.destinations,
                "bounds": [min(xs) - 115, min(ys) - 100, max(xs) - min(xs) + 255, max(ys) - min(ys) + 205],
                "meters_per_unit": 1.0}
