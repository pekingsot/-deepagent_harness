import unittest

from pydantic import ValidationError

from agent_platform.application.ports.repositories import RunRepository
from agent_platform.domain.common.models import Principal, RunContext


class ScaffoldContractTests(unittest.TestCase):
    def test_domain_is_strict_and_immutable(self) -> None:
        principal = Principal(tenant_id="tenant-a", project_id="project-a", user_id="user-a")
        with self.assertRaises(ValidationError):
            principal.tenant_id = "tenant-b"
        with self.assertRaises(ValidationError):
            Principal.model_validate({"tenant_id": 1, "project_id": "p", "user_id": "u"})
        with self.assertRaises(ValidationError):
            Principal.model_validate({
                "tenant_id": "a", "project_id": "p", "user_id": "u", "unexpected": True,
            })

    def test_path_like_tenant_id_is_rejected(self) -> None:
        for tenant in ("../other", "a/b", "a:b", ""):
            with self.assertRaises(ValidationError):
                Principal(tenant_id=tenant, project_id="p", user_id="u")

    def test_repository_requires_nominal_implementation(self) -> None:
        with self.assertRaises(TypeError):
            RunRepository()  # type: ignore[abstract]

    def test_context_round_trip_preserves_identity(self) -> None:
        context = RunContext(tenant_id="a", project_id="p", user_id="u")
        restored = RunContext.model_validate_json(context.model_dump_json())
        self.assertEqual(restored, context)
        self.assertTrue(context.checkpoint_thread.startswith("a:p:u:"))


if __name__ == "__main__":
    unittest.main()
