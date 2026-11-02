import os
import unittest


@unittest.skipUnless(
    os.environ.get("HARNESS_RUN_SANDBOX_INTEGRATION") == "1",
    "需要显式启用真实沙箱测试",
)
class OpenSandboxBackendIntegrationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_command_and_files(self):
        from agent_platform.infrastructure.harness.backends.opensandbox import (
            OpenSandboxBackend,
        )
        from agent_platform.infrastructure.sandbox.opensandbox import (
            OpenSandboxClient,
        )
        from agent_platform.infrastructure.sandbox.settings import (
            get_opensandbox_settings,
        )

        settings = get_opensandbox_settings()
        print("沙箱地址：", settings.protocol, settings.domain)
        client = OpenSandboxClient(settings)

        sandbox = await client.create(
            metadata={"purpose": "backend-integration-test"}
        )

        try:
            backend = OpenSandboxBackend(
                sandbox,
                command_timeout=settings.command_timeout_seconds,
            )

            # 验证命令执行。
            execution = await backend.aexecute(
                "python -c 'print(1 + 1)'"
            )
            self.assertEqual(execution.exit_code, 0)
            self.assertIn("2", execution.output.splitlines())

            # 验证基类的文件写入能力。
            written = await backend.awrite(
                "/deliverables/hello.txt",
                "Hello World",
            )
            self.assertIsNone(written.error)

            # 验证基类的文件读取能力。
            read = await backend.aread("/deliverables/hello.txt")
            self.assertIsNone(read.error)

            # 验证文件下载。
            downloaded = await backend.adownload_files([
                "/deliverables/hello.txt",
            ])
            self.assertIsNone(downloaded[0].error)
            self.assertEqual(
                downloaded[0].content,
                b"Hello World",
            )

            # 验证文件删除。
            deleted = await backend.adelete(
                "/deliverables/hello.txt"
            )
            self.assertIsNone(deleted.error)

        finally:
            # 这里只销毁本次测试创建的临时沙箱。
            await sandbox.destroy()