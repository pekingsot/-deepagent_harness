import unittest

from pydantic import ValidationError

from agent_platform.domain.repositories.agent_task_repository import AgentTaskRepository
from agent_platform.domain.types.common import Principal, TaskContext
from agent_platform.infrastructure.harness.runtime.checkpoint_namespace import checkpoint_thread


class ScaffoldContractTests(unittest.TestCase):
    def test_domain_is_strict_and_immutable(self) -> None:
        principal = Principal(tenant_id=1, project_id="project-a", user_id=2)
        with self.assertRaises(ValidationError):
            principal.tenant_id = 3
        with self.assertRaises(ValidationError):
            Principal.model_validate({"tenant_id": "1", "project_id": "p", "user_id": 2})
        with self.assertRaises(ValidationError):
            Principal.model_validate(
                {
                    "tenant_id": 1,
                    "project_id": "p",
                    "user_id": 2,
                    "unexpected": True,
                }
            )

    def test_path_like_tenant_id_is_rejected(self) -> None:
        for tenant in ("../other", "a/b", "a:b", ""):
            with self.assertRaises(ValidationError):
                Principal(tenant_id=tenant, project_id="p", user_id=2)

    def test_repository_requires_nominal_implementation(self) -> None:
        with self.assertRaises(TypeError):
            AgentTaskRepository()  # type: ignore[abstract]

    def test_context_round_trip_preserves_identity(self) -> None:
        context = TaskContext(tenant_id=1, project_id="p", user_id=2)
        restored = TaskContext.model_validate_json(context.model_dump_json())
        self.assertEqual(restored, context)
        self.assertTrue(checkpoint_thread(context).startswith("1:p:2:"))


if __name__ == "__main__":
    unittest.main()
