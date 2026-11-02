import asyncio
from pathlib import PurePosixPath
from shlex import quote

from deepagents.backends.protocol import (
    DeleteResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox
from opensandbox import Sandbox
from opensandbox.models.execd import (
    ExecutionHandlers,
    ExecutionInit,
    RunCommandOpts,
)
from opensandbox.models.filesystem import WriteEntry

from datetime import timedelta


class SandboxCommandStateUnknown(RuntimeError):
    """无法确认远端命令是否停止，需要后续检查沙箱状态。"""


class OpenSandboxBackend(BaseSandbox):
    """供 DeepAgents 使用的异步 OpenSandbox Backend。"""

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        command_timeout: int = 120,
    ) -> None:
        if type(command_timeout) is not int or command_timeout <= 0:
            raise ValueError("command_timeout 必须是正整数")

        self._sandbox = sandbox
        self._command_timeout = command_timeout

        # 同一实例内串行执行命令，取消时能够明确定位当前命令。
        self._command_lock = asyncio.Lock()

        # 远端状态不确定时，停止继续使用这个 Backend。
        self._usable = True

    @property
    def id(self) -> str:
        return self._sandbox.id

    def _ensure_usable(self) -> None:
        if not self._usable:
            raise SandboxCommandStateUnknown(
                "沙箱命令状态尚未确认，不能继续执行"
            )

    # BaseSandbox 的抽象同步入口。
    # 当前适配器只支持异步执行，避免把异步 SDK 强行包装成同步调用。

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        raise NotImplementedError("请使用 aexecute()")

    def upload_files(
        self,
        files: list[tuple[str, bytes]],
    ) -> list[FileUploadResponse]:
        raise NotImplementedError("请使用 aupload_files()")

    def download_files(
        self,
        paths: list[str],
    ) -> list[FileDownloadResponse]:
        raise NotImplementedError("请使用 adownload_files()")

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        seconds = self._command_timeout if timeout is None else timeout

        # 当前实现要求每条命令都有服务端超时。
        if type(seconds) is not int or seconds <= 0:
            raise ValueError("命令 timeout 必须是正整数")

        # 等待锁时取消，不需要中断远端，因为命令还没有提交。
        async with self._command_lock:
            self._ensure_usable()

            execution_id: str | None = None

            async def on_init(event: ExecutionInit) -> None:
                nonlocal execution_id
                execution_id = event.id

            try:
                # 服务端先超时，本地额外预留十秒接收结束事件。
                async with asyncio.timeout(seconds + 10):
                    execution = await self._sandbox.commands.run(
                        command,
                        opts=RunCommandOpts(
                            working_directory="/workspace",
                            timeout=timedelta(seconds=seconds),
                        ),
                        handlers=ExecutionHandlers(on_init=on_init),
                    )

                    exit_code = execution.exit_code

                    if exit_code is None and execution.error:
                        exit_code = execution.error.exit_code

                    if exit_code is None and execution.id:
                        status = (
                            await self._sandbox.commands.get_command_status(
                                execution.id
                            )
                        )
                        exit_code = status.exit_code

                    if exit_code is None:
                        raise RuntimeError("未取得远端命令退出码")

            except (asyncio.CancelledError, TimeoutError):
                # 取消本地等待后，还要中断远端进程。
                await self._interrupt_command(execution_id)
                raise

            except Exception:
                # 网络断开时，不能默认远端进程也已经结束。
                if execution_id is not None:
                    await self._interrupt_command(execution_id)
                else:
                    self._usable = False
                raise

            output = "".join(
                item.text
                for item in [
                    *execution.logs.stdout,
                    *execution.logs.stderr,
                ]
            )

            if execution.error:
                output += (
                    f"\n{execution.error.name}: "
                    f"{execution.error.value}"
                )

            # 不在这里硬截断输出：
            # BaseSandbox 的部分文件操作需要完整的 JSON 返回值。
            return ExecuteResponse(
                output=output,
                exit_code=exit_code,
                truncated=False,
            )

    async def _interrupt_command(
        self,
        execution_id: str | None,
    ) -> None:
        self._usable = False

        if execution_id is None:
            raise SandboxCommandStateUnknown(
                "命令 ID 尚未返回，无法确认远端是否停止"
            )

        try:
            async with asyncio.timeout(10):
                await self._sandbox.commands.interrupt(execution_id)

                # 中断请求成功，不直接等同于进程已经退出。
                while True:
                    status = (
                        await self._sandbox.commands.get_command_status(
                            execution_id
                        )
                    )

                    if status.running is False:
                        break

                    await asyncio.sleep(0.2)

        except Exception as exc:
            raise SandboxCommandStateUnknown(
                f"无法确认远端命令已停止：{execution_id}"
            ) from exc

        self._usable = True

    async def aupload_files(
        self,
        files: list[tuple[str, bytes]],
    ) -> list[FileUploadResponse]:
        self._ensure_usable()
        results: list[FileUploadResponse] = []

        for path, content in files:
            try:
                parent = str(PurePosixPath(path).parent)

                await self._sandbox.files.create_directories([
                    WriteEntry(path=parent, mode=755),
                ])

                await self._sandbox.files.write_files([
                    WriteEntry(
                        path=path,
                        data=content,
                        mode=644,
                    ),
                ])

            except Exception as exc:
                results.append(
                    FileUploadResponse(path=path, error=str(exc))
                )
            else:
                results.append(FileUploadResponse(path=path))

        return results

    async def adownload_files(
        self,
        paths: list[str],
    ) -> list[FileDownloadResponse]:
        self._ensure_usable()
        results: list[FileDownloadResponse] = []

        for path in paths:
            try:
                content = await self._sandbox.files.read_bytes(path)
            except Exception as exc:
                results.append(
                    FileDownloadResponse(path=path, error=str(exc))
                )
            else:
                results.append(
                    FileDownloadResponse(path=path, content=content)
                )

        return results

    async def adelete(self, file_path: str) -> DeleteResult:
        # 基类的异步删除默认可能转入同步方法，
        # 所以这里也提供原生异步实现。
        path = PurePosixPath(file_path)

        if not path.is_absolute() or path == PurePosixPath("/"):
            return DeleteResult(error="请提供有效的绝对路径，不能删除根目录")

        quoted = quote(file_path)

        exists = await self.aexecute(
            f"test -e {quoted} || test -L {quoted}"
        )

        if exists.exit_code != 0:
            return DeleteResult(error=f"路径不存在：{file_path}")

        result = await self.aexecute(f"rm -rf -- {quoted}")

        if result.exit_code != 0:
            return DeleteResult(error=result.output)

        return DeleteResult(path=file_path)