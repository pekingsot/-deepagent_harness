"""迁移自手工演示的真实服务验证；每项均需独立显式启用。"""

import asyncio
import math
import os
import sys
import unittest
from datetime import timedelta


class ExternalServicesTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("HARNESS_RUN_DATABASE_INTEGRATION") == "1",
        "Requires an explicitly configured test PostgreSQL",
    )
    def test_postgres_connection(self):
        from sqlalchemy import text

        from agent_platform.bootstrap.settings import get_settings
        from agent_platform.infrastructure.persistence.database import Database

        async def verify():
            database = Database(get_settings().database_url)
            try:
                async with database.session_factory() as session:
                    self.assertEqual(await session.scalar(text("SELECT 1")), 1)
            finally:
                await database.close()

        asyncio.run(
            verify(),
            loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None,
        )

    @unittest.skipUnless(
        os.environ.get("HARNESS_RUN_EMBEDDINGS_INTEGRATION") == "1",
        "Requires the installed local BGE model",
    )
    def test_local_bge_document_and_query_vectors(self):
        from agent_platform.infrastructure.embeddings.bge import BgeEmbeddings

        embeddings = BgeEmbeddings()
        documents = ["用户希望代码注释使用中文。", "用户喜欢先计划后执行。"]
        vectors = embeddings.embed_documents(documents)
        query = embeddings.embed_query("用户希望代码注释使用什么语言？")
        self.assertEqual(len(vectors), len(documents))
        for vector in [*vectors, query]:
            self.assertEqual(len(vector), 1024)
            self.assertTrue(all(math.isfinite(value) for value in vector))
            self.assertAlmostEqual(sum(value * value for value in vector), 1.0, places=4)

    @unittest.skipUnless(
        os.environ.get("HARNESS_RUN_SANDBOX_INTEGRATION") == "1",
        "Requires an explicitly configured test OpenSandbox server",
    )
    def test_sandbox_command_and_file_roundtrip(self):
        from opensandbox import Sandbox
        from opensandbox.config import ConnectionConfig
        from opensandbox.models import WriteEntry

        async def verify():
            sandbox = await Sandbox.create(
                os.environ.get("OPENSANDBOX_TEST_IMAGE", "python:3.12"),
                timeout=timedelta(minutes=10),
                connection_config=ConnectionConfig(
                    domain=os.environ["OPENSANDBOX_DOMAIN"],
                    api_key=os.environ["OPENSANDBOX_API_KEY"],
                    use_server_proxy=True,
                ),
            )
            try:
                execution = await sandbox.commands.run("python -c 'print(1 + 1)'")
                output = "".join(item.text for item in execution.logs.stdout)
                self.assertIn("2", output.splitlines())
                await sandbox.files.write_files(
                    [
                        WriteEntry(path="/tmp/hello.txt", data="Hello World"),
                    ]
                )
                self.assertEqual(await sandbox.files.read_file("/tmp/hello.txt"), "Hello World")
            finally:
                await sandbox.destroy()

        asyncio.run(
            verify(),
            loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None,
        )
