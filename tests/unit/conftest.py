"""单元测试禁止外网连接和遥测导出，避免测试导入触发隐式网络请求。"""

import ipaddress
import socket
from unittest.mock import patch

_patches = []


def pytest_configure(config):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def check_address(address):
        host = address[0] if isinstance(address, tuple) else address
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise RuntimeError(f"Unit tests must not access external networks: {host}")

    def connect(client, address):
        if client.family in (socket.AF_INET, socket.AF_INET6):
            check_address(address)
        return original_connect(client, address)

    def connect_ex(client, address):
        if client.family in (socket.AF_INET, socket.AF_INET6):
            check_address(address)
        return original_connect_ex(client, address)

    def getaddrinfo(host, port, *args, **kwargs):
        if host is not None:
            check_address((host, port))
        return original_getaddrinfo(host, port, *args, **kwargs)

    _patches.extend(
        [
            patch.dict(
                "os.environ",
                {
                    "OTEL_SDK_DISABLED": "true",
                    "OTEL_TRACES_EXPORTER": "none",
                    "OTEL_METRICS_EXPORTER": "none",
                    "OTEL_LOGS_EXPORTER": "none",
                    "LANGSMITH_TRACING": "false",
                    "LANGCHAIN_TRACING_V2": "false",
                    "HF_HUB_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                },
            ),
            patch.object(socket.socket, "connect", connect),
            patch.object(socket.socket, "connect_ex", connect_ex),
            patch.object(socket, "getaddrinfo", getaddrinfo),
        ]
    )
    for item in _patches:
        item.start()


def pytest_unconfigure(config):
    for item in reversed(_patches):
        item.stop()
    _patches.clear()
