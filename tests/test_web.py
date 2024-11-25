from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import unittest

from fastapi.testclient import TestClient

from truck_cycle.model import Scenario, Simulation
from truck_cycle.web import app


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_interface_defaults_and_openapi(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Truck Optimization", page.text)
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        defaults = self.client.get("/api/defaults").json()
        self.assertEqual(len(defaults["trucks"]), 5)
        self.assertEqual(len(defaults["excavators"]), 3)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/simulate", schema["paths"])
        self.assertIn("ScenarioRequest", schema["components"]["schemas"])
        self.assertIn("SimulationResponse", schema["components"]["schemas"])
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_simulation_matches_direct_model(self):
        expected = asdict(Simulation().run())
        response = self.client.post("/api/simulate", json={})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["summary"], expected)
        self.assertIn("routes", result["network"])
        self.assertTrue(result["assignments"])
        self.assertTrue(result["events"])
        self.assertTrue(result["motion"])
        self.assertEqual(result["network"]["meters_per_unit"], 1)
        self.assertEqual(len(result["network"]["bounds"]), 4)

    def test_custom_equipment_and_target(self):
        scenario = self.client.get("/api/defaults").json()
        scenario["target_m3"] = 60
        scenario["trucks"][0]["capacity_m3"] = 10
        response = self.client.post("/api/simulate", json=scenario)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["delivered_m3"], 60)
        self.assertEqual(response.json()["scenario"]["trucks"][0]["capacity_m3"], 10)

    def test_invalid_input_keeps_browser_error_contract(self):
        duplicate = self.client.get("/api/defaults").json()
        duplicate["trucks"][1]["id"] = duplicate["trucks"][0]["id"]
        wrong_speed = self.client.get("/api/defaults").json()
        wrong_speed["trucks"][0]["loaded_speed_m_s"] = 100
        for payload in [wrong_speed, [], {"target_m3": 0}, {"target_m3": True}, {"target_m3": "120"},
                        {"extra": 1}, {"trucks": []}, duplicate]:
            with self.subTest(payload=payload):
                response = self.client.post("/api/simulate", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIsInstance(response.json()["error"], str)
        for body in ['{"target_m3":NaN}', '{"target_m3":', ' ' * 32769]:
            response = self.client.post("/api/simulate", content=body, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("error", response.json())

    def test_concurrent_requests_do_not_mix_environments(self):
        targets = [40, 60, 80, 100]
        expected = {target: asdict(Simulation(Scenario(target_m3=target)).run()) for target in targets}

        def request(target):
            response = self.client.post("/api/simulate", json={"target_m3": target})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["summary"], expected[target])

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(request, targets))


if __name__ == "__main__":
    unittest.main()
