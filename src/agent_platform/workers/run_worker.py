"""Minimal worker entry point; queue consumption will be added when a queue adapter is chosen."""

import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger(__name__).info(
        "Worker scaffold ready. Bind JobQueue and AgentRuntime before enabling consumption."
    )


if __name__ == "__main__":
    main()
