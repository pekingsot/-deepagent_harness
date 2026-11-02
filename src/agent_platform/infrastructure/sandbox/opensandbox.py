from datetime import timedelta
from functools import lru_cache
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.filesystem import WriteEntry

from agent_platform.infrastructure.sandbox.settings import (
    OpenSandboxSettings, get_opensandbox_settings,
)


class OpenSandboxClient:
    """根据项目配置创建或连接 OpenSandbox。"""

    def __init__(self, settings: OpenSandboxSettings) -> None:
        self._settings = settings

    def _connection_config(self) -> ConnectionConfig:
        return ConnectionConfig(
            domain=self._settings.domain,
            api_key=self._settings.api_key.get_secret_value(),
            protocol=self._settings.protocol,
            use_server_proxy=self._settings.use_server_proxy,
            request_timeout=timedelta(
                seconds=self._settings.request_timeout_seconds
            ),
            disable_metrics=True,
        )

    async def create(
        self,
        *,
        metadata: dict[str, str] | None = None,
    ) -> Sandbox:
        sandbox = await Sandbox.create(
            self._settings.image,
            timeout=timedelta(
                seconds=self._settings.sandbox_timeout_seconds
            ),
            ready_timeout=timedelta(
                seconds=self._settings.ready_timeout_seconds
            ),
            connection_config=self._connection_config(),
            metadata=metadata,
        )

        try:
            # 约定代码工作目录和交付物目录。
            await sandbox.files.create_directories([
                WriteEntry(path="/workspace", mode=755),
                WriteEntry(path="/deliverables", mode=755),
            ])
        except BaseException:
            # 创建后初始化失败，清理已经创建的远端资源。
            await sandbox.destroy()
            raise

        return sandbox

    async def connect(self, sandbox_id: str) -> Sandbox:
        """连接之前创建的沙箱，不创建新容器。"""
        return await Sandbox.connect(
            sandbox_id,
            connection_config=self._connection_config(),
        )

@lru_cache(maxsize=1)
def get_opensandbox_client() -> OpenSandboxClient:
    return OpenSandboxClient(
        settings=get_opensandbox_settings(),
    )