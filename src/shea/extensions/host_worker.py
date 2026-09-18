from __future__ import annotations

import importlib
import json
import sys
import typing
from typing import Any


def _read() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return typing.cast(dict[str, Any], json.loads(line))


def _write(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> None:
    # Handshake: parent sends {"method":"configure","params":{...}}
    plugin_obj: Any = None
    while True:
        msg = _read()
        if msg is None:
            break
        req_id = str(msg.get("id", ""))
        method = str(msg.get("method", ""))
        params: dict[str, Any] = msg.get("params") or {}
        try:
            if method == "configure":
                entry = str(params["entrypoint"])  # "module:Class"
                plugin_dir = str(params["plugin_dir"])
                if plugin_dir not in sys.path:
                    sys.path.insert(0, plugin_dir)
                mod_name, _, cls_name = entry.partition(":")
                mod = importlib.import_module(mod_name)
                cls = getattr(mod, cls_name)
                plugin_obj = cls()
                _write({"id": req_id, "ok": True, "result": {"name": getattr(plugin_obj, "name", mod_name)}, "error": None})
            elif method == "register_declare":
                # Plugin may only *declare* tools/events; parent applies under proxy.
                declarations: list[dict[str, Any]] = []
                if plugin_obj is not None and hasattr(plugin_obj, "declare"):
                    declarations = list(plugin_obj.declare() or [])
                _write({"id": req_id, "ok": True, "result": {"declarations": declarations}, "error": None})
            elif method == "shutdown":
                _write({"id": req_id, "ok": True, "result": {}, "error": None})
                break
            else:
                _write({"id": req_id, "ok": False, "result": None, "error": f"unknown method {method}"})
        except Exception as exc:
            _write({"id": req_id, "ok": False, "result": None, "error": str(exc)})

if __name__ == "__main__":
    main()