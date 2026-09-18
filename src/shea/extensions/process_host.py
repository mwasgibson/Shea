from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shea.extensions.manifest import ExtensionManifest, IsolationMode
from shea.ports.execution_boundary import IsolationLimits
from shea.security.isolation import make_preexec_fn

logger = logging.getLogger(__name__)


@dataclass
class ProcessExtensionHandle:
    manifest: ExtensionManifest
    plugin_dir: Path
    proc: subprocess.Popen[str]
    declarations: list[dict[str, Any]]

    def close(self) -> None:
        try:
            self._rpc("shutdown", {})
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        req_id = uuid.uuid4().hex
        self.proc.stdin.write(json.dumps({"id": req_id, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"extension host died: {self.manifest.id}")
        resp = json.loads(line)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "extension host error")
        return resp.get("result") or {}


def spawn_extension_host(
    manifest: ExtensionManifest,
    plugin_dir: Path,
    *,
    isolation_limits: IsolationLimits | None = None,
) -> ProcessExtensionHandle:
    if manifest.isolation is not IsolationMode.PROCESS:
        raise ValueError("spawn_extension_host requires isolation=process")

    limits = isolation_limits or IsolationLimits(
        require_new_session=True,
        memory_bytes=256 * 1024 * 1024,
        cpu_seconds=30,
        max_open_files=64,
        max_processes=16,
        forbid_core_dumps=True,
    )
    preexec = make_preexec_fn(limits)
    from shea.security.isolation import wrap_command_for_isolation
    cmd = [sys.executable, "-m", "shea.extensions.host_worker"]
    cmd = wrap_command_for_isolation(cmd, allowed_write_dir=plugin_dir)
        
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(plugin_dir),
        shell=False,
        preexec_fn=preexec,
    )
    handle = ProcessExtensionHandle(
        manifest=manifest, plugin_dir=plugin_dir, proc=proc, declarations=[]
    )
    handle._rpc(  # pyright: ignore[reportPrivateUsage]
        "configure",
        {"entrypoint": manifest.entrypoint, "plugin_dir": str(plugin_dir.resolve())},
    )
    result = handle._rpc("register_declare", {})  # pyright: ignore[reportPrivateUsage]
    handle.declarations = list(result.get("declarations") or [])
    logger.info(
        "process-isolated extension %s v%s declarations=%d",
        manifest.id,
        manifest.version,
        len(handle.declarations),
    )
    return handle