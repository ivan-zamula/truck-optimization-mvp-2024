import math
import unittest

from truck_cycle.model import Scenario
from truck_cycle.motion import (VehicleMotion, ACCELERATION, DECELERATION,
                                HEADWAY, MIN_GAP, EXPONENT)
from truck_cycle.network import RoadNetwork


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.network = RoadNetwork(Scenario().excavators)
        self.occupancy = {}

    def vehicle(self, excavator="E2", loaded=False, speed=12):
        return VehicleMotion(self.network, self.occupancy,
                             self.network.routes[excavator], loaded, speed)

    def test_step_uses_original_leader_acceleration_speed_position_order(self):
        follower, leader = self.vehicle(), self.vehicle()
        follower.position, follower.current_speed = 10, 5
        leader.position, leader.current_speed = 70, 3
        follower.enter()
        leader.enter()
        gap = 70 - 10 - follower.length
        desired = MIN_GAP + max(0, 5 * HEADWAY + 5 * (5-3) / (2*math.sqrt(ACCELERATION*DECELERATION)))
        acceleration = ACCELERATION * (1 - (5/12)**EXPONENT - (desired/gap)**2)
        speed = min(12, max(0, 5+acceleration), gap)
        follower.advance()
        self.assertIs(follower.leader, leader)
        self.assertAlmostEqual(follower.current_speed, speed)
        self.assertAlmostEqual(follower.position, 10+speed)

    def test_next_edge_leader_and_opposite_lane(self):
        follower, leader = self.vehicle(), self.vehicle()
        follower.position = 60
        leader.current_edge_index, leader.position = 1, 25
        leader.enter()
        follower.update_leader()
        self.assertIs(follower.leader, leader)
        self.assertEqual(follower.leader_distance, 75-60+25-15)
        leader.leave()
        leader.loaded = True
        leader.enter()
        follower.update_leader()
        self.assertIsNone(follower.leader)

    def test_branch_divergence_does_not_block_other_route(self):
        follower, leader = self.vehicle("E1"), self.vehicle("E2")
        leader.current_edge_index, leader.position = 2, 20
        leader.enter()
        follower.update_leader()
        self.assertIsNot(follower.leader, leader)

    def test_edge_crossing_preserves_excess_distance(self):
        truck = self.vehicle()
        truck.enter()
        truck.position = 82
        truck.cross_edges()
        self.assertEqual(truck.position, 7)
        self.assertEqual(truck.distance, 82)
        self.assertNotIn(truck, self.occupancy[("main", False)])
        self.assertIn(truck, self.occupancy[("J3", False)])

    def test_stopped_leader_cannot_be_crossed(self):
        follower, leader = self.vehicle(), self.vehicle()
        follower.position, follower.current_speed = 5, 12
        leader.position = 35
        follower.enter()
        leader.enter()
        for _ in range(10):
            follower.advance()
            self.assertLessEqual(follower.position + follower.length, leader.position)
        self.assertEqual(follower.current_speed, 0)

    def test_entry_waits_for_space_and_free_speed_is_capped(self):
        first, second = self.vehicle(), self.vehicle()
        first.enter()
        self.assertFalse(second.can_enter())
        first.position = 41
        self.assertTrue(second.can_enter())
        first.leave()
        second.current_speed = 11
        second.advance()
        self.assertEqual(second.current_speed, 12)

    def test_destination_requires_stop_at_node(self):
        truck = self.vehicle()
        truck.current_edge_index = len(truck.route)-1
        edge = self.network.edges[truck.key[0]]
        truck.position = edge.length_m - truck.length - 30
        truck.current_speed = 12
        truck.advance()
        self.assertGreaterEqual(edge.length_m - truck.position - truck.length, 0)
        for _ in range(200):
            if truck.advance():
                break
        else:
            self.fail("Truck did not stop at its destination")
        self.assertAlmostEqual(truck.position+truck.length, edge.length_m, places=1)
        self.assertEqual(truck.current_speed, 0)


if __name__ == "__main__":
    unittest.main()
