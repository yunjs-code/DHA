"""app.main REST API / 정적 파일 / WebSocket 회귀 테스트.

Blue Agent 훅(app/attacks.py, app/blue_agent/*) 삽입 이후에도 기존
/gcs, /attacker, REST API가 정상 동작하는지 확인한다. 실제 SITL이
없는 환경에서도 결정적으로 검증 가능한 경로(404/503/400/409 등)만
다루고, 살아있는 SITL 연결이 필요한 200 성공 경로는 범위 밖이다.
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app

DRONE_IDS = ("drone-01", "drone-02", "drone-03")


class TestMainRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    # ── REST: 조회 ──────────────────────────────────────────────────────────

    def test_api_drones_shape(self) -> None:
        res = self.client.get("/api/drones")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        for drone_id in DRONE_IDS:
            self.assertIn(drone_id, data)
            self.assertIn("connected", data[drone_id])
            self.assertIn("ready", data[drone_id])

    def test_api_debug_shape(self) -> None:
        res = self.client.get("/api/debug")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        for drone_id in DRONE_IDS:
            self.assertIn(drone_id, data)

    # ── REST: 명령 ──────────────────────────────────────────────────────────

    def test_command_unknown_drone_404(self) -> None:
        res = self.client.post(
            "/api/command",
            json={"drone_id": "drone-99", "cmd": "ARM", "params": {}},
        )
        self.assertEqual(res.status_code, 404)
        self.assertIn("알 수 없는 드론", res.json()["error"])

    def test_command_not_ready_503(self) -> None:
        # 테스트 환경에는 실제 SITL이 없으므로 항상 not-ready 상태
        res = self.client.post(
            "/api/command",
            json={"drone_id": "drone-01", "cmd": "ARM", "params": {}},
        )
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["error"], "SITL 미연결")

    # ── REST: 공격 (asyncio.create_task만 스케줄, 즉시 응답) ───────────────────

    def test_attack_start_unknown_scenario_400(self) -> None:
        res = self.client.post(
            "/api/attack/start",
            json={"drone_id": "drone-01", "scenario": "nope", "params": {}},
        )
        self.assertEqual(res.status_code, 400)

    def test_attack_start_duplicate_409_then_stop(self) -> None:
        res = self.client.post(
            "/api/attack/start",
            json={"drone_id": "drone-02", "scenario": "blackout",
                  "params": {"warmup": 1, "watch": 1}},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["started"])
        attack_id = data["attack_id"]
        self.assertEqual(attack_id, "att03_drone-02")

        res2 = self.client.post(
            "/api/attack/start",
            json={"drone_id": "drone-02", "scenario": "blackout", "params": {}},
        )
        self.assertEqual(res2.status_code, 409)

        res3 = self.client.post("/api/attack/stop", json={"attack_id": attack_id})
        self.assertEqual(res3.status_code, 200)
        self.assertTrue(res3.json()["stopped"])

        res4 = self.client.post("/api/attack/stop", json={"attack_id": "att99_none"})
        self.assertEqual(res4.status_code, 200)
        self.assertFalse(res4.json()["stopped"])

    def test_attack_status_shape(self) -> None:
        res = self.client.get("/api/attack/status")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), dict)

    # ── 정적 파일 ───────────────────────────────────────────────────────────

    def test_gcs_static_index(self) -> None:
        res = self.client.get("/gcs/")
        self.assertEqual(res.status_code, 200)

    def test_attacker_static_index(self) -> None:
        res = self.client.get("/attacker/")
        self.assertEqual(res.status_code, 200)

    # ── WebSocket ──────────────────────────────────────────────────────────

    def test_ws_gcs_connect(self) -> None:
        with self.client.websocket_connect("/ws/gcs"):
            pass

    def test_ws_attacker_connect(self) -> None:
        with self.client.websocket_connect("/ws/attacker"):
            pass


if __name__ == "__main__":
    unittest.main()
