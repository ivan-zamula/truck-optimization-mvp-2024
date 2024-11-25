import unittest
import math
from dataclasses import replace
from truck_cycle.model import ExcavatorSpec, Scenario, Simulation, TruckSpec
from truck_cycle.network import RoadNetwork


class TruckOptimizationTests(unittest.TestCase):
    def test_single_truck_partial_last_load_and_loading_duration(self):
        scenario = Scenario(trucks=(TruckSpec("T1", 10, 12, 5),),
            excavators=(ExcavatorSpec("E1", 600, 120),), target_m3=15, time_limit_seconds=500)
        model = Simulation(scenario)
        result = model.run()
        self.assertTrue(result.plan_met)
        self.assertEqual(result.delivered_m3, 15)
        self.assertEqual(result.completed_trips, 2)
        for a in model.assignments:
            self.assertAlmostEqual(a.loading_end - a.loading_start, a.volume_m3 / 600 * 3600)
            self.assertGreater(a.empty_end - a.empty_start, 120 / 12)
            self.assertGreater(a.loaded_end - a.loading_end, 120 / 6)
        self.assertEqual([a.volume_m3 for a in model.assignments], [10, 5])

    def test_default_trucks_meet_volume_without_overdispatch(self):
        model = Simulation()
        result = model.run()
        self.assertTrue(result.plan_met)
        self.assertAlmostEqual(result.delivered_m3, 120)
        self.assertAlmostEqual(sum(a.volume_m3 for a in model.assignments), 120)
        self.assertEqual({a.excavator for a in model.assignments}, {"E1", "E2", "E3"})
        for a in model.assignments:
            spec = next(t for t in model.scenario.trucks if t.id == a.truck)
            self.assertLessEqual(a.volume_m3, spec.capacity_m3)
            self.assertLessEqual(a.unloading_end, model.scenario.time_limit_seconds)
        for truck in result.trucks:
            self.assertAlmostEqual(truck["working_seconds"] + truck["waiting_seconds"] + truck["idle_seconds"], result.elapsed_seconds)

    def test_actual_timestamps_match_events_and_service_does_not_overlap(self):
        model = Simulation()
        model.run()
        for a in model.assignments:
            actual = {e.action: e.time_seconds for e in model.events if e.assignment == a.id}
            for name in ["empty_start", "empty_end", "loading_start", "loading_end", "loaded_end", "unloading_start", "unloading_end"]:
                self.assertAlmostEqual(actual[name], getattr(a, name))
        for id in [e.id for e in model.scenario.excavators] + ["unloader"]:
            spans = [(a.unloading_start, a.unloading_end) if id == "unloader" else (a.loading_start, a.loading_end)
                     for a in model.assignments if id == "unloader" or a.excavator == id]
            spans.sort()
            for left, right in zip(spans, spans[1:]):
                self.assertLessEqual(left[1], right[0] + 1e-8)

    def test_infeasible_plan_reports_deficit(self):
        result = Simulation(Scenario(time_limit_seconds=1)).run()
        self.assertFalse(result.plan_met)
        self.assertEqual(result.delivered_m3, 0)
        self.assertEqual(result.deficit_m3, 120)

    def test_delivery_at_deadline_is_counted(self):
        scenario = Scenario(trucks=(TruckSpec("T1", 10, 12, 5),),
            excavators=(ExcavatorSpec("E1", 600, 120),), target_m3=10, time_limit_seconds=500)
        finish = Simulation(scenario).run().elapsed_seconds
        self.assertTrue(Simulation(replace(scenario, time_limit_seconds=finish)).run().plan_met)
        incomplete = Simulation(replace(scenario, time_limit_seconds=finish - 0.1))
        result = incomplete.run()
        self.assertFalse(result.plan_met)
        self.assertEqual(result.delivered_m3, 0)
        self.assertIsNone(incomplete.assignments[0].unloading_end)
        self.assertEqual(result.trucks[0]["delivered_m3"], 0)
        self.assertLessEqual(result.trucks[0]["working_seconds"], result.elapsed_seconds)

    def test_invalid_parameters(self):
        for kwargs in [{"target_m3": 0}, {"time_limit_seconds": float("nan")}, {"trucks": ()},
                       {"trucks": (TruckSpec("T1", -1, 10, 5),)}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Scenario(**kwargs)

    def test_road_routes_are_continuous_and_match_configured_distances(self):
        scenario = Scenario()
        network = RoadNetwork(scenario.excavators)
        for excavator in scenario.excavators:
            previous = "delivery"
            for id in network.routes[excavator.id]:
                edge = network.edges[id]
                self.assertEqual(edge.source, previous)
                self.assertGreater(edge.length_m, 0)
                a, b = network.nodes[edge.source], network.nodes[edge.target]
                self.assertAlmostEqual(math.hypot(b.x-a.x, b.y-a.y), edge.length_m)
                previous = edge.target
            self.assertEqual(previous, network.destinations[excavator.id])
            self.assertAlmostEqual(network.route_distance(excavator.id), excavator.distance_m)
        self.assertEqual(network.routes["E2"][:2], network.routes["E3"][:2])
        self.assertNotEqual(network.routes["E1"][1], network.routes["E2"][1])

    def test_metric_geometry_after_distance_changes(self):
        network = RoadNetwork(tuple(ExcavatorSpec(f"E{i}", 180, distance)
            for i, distance in enumerate((450, 1200, 2000, 700), start=1)))
        for edge in network.edges.values():
            a, b = network.nodes[edge.source], network.nodes[edge.target]
            self.assertAlmostEqual(math.hypot(b.x-a.x, b.y-a.y), edge.length_m)
        for id, distance in zip(("E1", "E2", "E3", "E4"), (450, 1200, 2000, 700)):
            self.assertAlmostEqual(network.route_distance(id), distance)

    def test_several_trucks_travel_to_different_excavators_at_once(self):
        model = Simulation()
        model.run()
        simultaneous = False
        for t in range(1, 180):
            moving = [a for a in model.assignments if a.empty_start <= t < a.empty_end
                      and any(m.truck == a.truck and m.assignment == a.id and t-1 < m.time_seconds <= t and m.speed_m_s > 0 for m in model.motion)]
            if len(moving) >= 3 and len({a.excavator for a in moving}) >= 2:
                simultaneous = True
                break
        self.assertTrue(simultaneous)
        for a in model.assignments:
            entries = [e.segment for e in model.events if e.assignment == a.id and e.action == "road_enter"]
            route = model.network.routes[a.excavator]
            self.assertEqual(entries, route + list(reversed(route)))

    def test_actual_motion_samples_and_loaded_speed_limit(self):
        model = Simulation()
        model.run()
        specs = {t.id: t for t in model.scenario.trucks}
        for a in model.assignments:
            for loaded in (False, True):
                samples = [m for m in model.motion if m.assignment == a.id and m.loaded == loaded]
                spec = specs[a.truck]
                limit = spec.loaded_speed_m_s if loaded else spec.empty_speed_m_s
                self.assertEqual(spec.loaded_speed_m_s, spec.empty_speed_m_s / 2)
                self.assertTrue(all(0 <= m.speed_m_s <= limit for m in samples))
                self.assertAlmostEqual(samples[-1].distance_m, model.network.route_distance(a.excavator) - 15, places=1)
                for previous, current in zip(samples, samples[1:]):
                    dt = current.time_seconds - previous.time_seconds
                    self.assertIn(round(dt, 6), (0, 1))
                    self.assertAlmostEqual(current.distance_m - previous.distance_m, current.speed_m_s * dt)
                self.assertEqual(samples[-1].speed_m_s, 0)
        self.assertGreater(len(model.motion), 100)


if __name__ == "__main__":
    unittest.main()
