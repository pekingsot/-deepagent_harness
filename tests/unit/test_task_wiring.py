"""验证无参缓存工厂，避免服务被重复装配或缓存跨生命周期残留。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent_platform.bootstrap import wiring


class TaskWiringTests(unittest.TestCase):
    def test_no_argument_factory_reuses_service_and_can_be_reset(self) -> None:
        wiring.get_agent_task_application_service.cache_clear()
        self.addCleanup(wiring.get_agent_task_application_service.cache_clear)
        with (
            patch.object(
                wiring, "get_settings", return_value=SimpleNamespace(checkpoint_backend="redis")
            ),
            patch.object(wiring, "get_redis_checkpointer"),
            patch.object(wiring, "get_task_queue"),
            patch.object(wiring, "get_task_events"),
            patch.object(wiring, "_build_runtime") as runtime,
        ):
            first = wiring.get_agent_task_application_service()
            self.assertIs(first, wiring.get_agent_task_application_service())
            self.assertEqual(runtime.call_count, 1)
            wiring.get_agent_task_application_service.cache_clear()
            self.assertIsNot(first, wiring.get_agent_task_application_service())
