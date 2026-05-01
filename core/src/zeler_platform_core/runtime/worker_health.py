from __future__ import annotations

import asyncio
import json
from typing import Any


class WorkerHealthSidecar:
    def __init__(self, consumer_ref: Any, *, port: int = 8080, staleness_seconds: int = 30) -> None:
        self._consumer_ref = consumer_ref
        self._port = port
        self._staleness_seconds = staleness_seconds
        self._server: asyncio.AbstractServer | None = None
        self.bound_port = port

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, "127.0.0.1", self._port)
        sockets: list[Any] = list(self._server.sockets or [])
        if sockets:
            self.bound_port = int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        request_line = await reader.readline()
        while True:
            line = await reader.readline()
            if line in {b"\r\n", b""}:
                break

        path = request_line.decode("ascii", errors="ignore").split(" ")[1:2]
        if path != ["/health"]:
            await self._write_response(writer, 404, {"error": "not_found"})
            return

        ready, checks = self._consumer_status()
        await self._write_response(
            writer, 200 if ready else 503, {"ready": ready, "checks": checks}
        )

    def _consumer_status(self) -> tuple[bool, dict[str, str]]:
        if not bool(getattr(self._consumer_ref, "is_ready", False)):
            return False, {"rabbitmq": "error", "reason": "not_ready"}

        return True, {"rabbitmq": "ok"}

    @staticmethod
    async def _write_response(
        writer: asyncio.StreamWriter, status_code: int, body: dict[str, Any]
    ) -> None:
        reason = (
            "OK"
            if status_code == 200
            else "Service Unavailable"
            if status_code == 503
            else "Not Found"
        )
        payload = json.dumps(body).encode("utf-8")
        writer.write(
            b"\r\n".join(
                [
                    f"HTTP/1.1 {status_code} {reason}".encode("ascii"),
                    b"Content-Type: application/json",
                    f"Content-Length: {len(payload)}".encode("ascii"),
                    b"Connection: close",
                    b"",
                    payload,
                ]
            )
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()
