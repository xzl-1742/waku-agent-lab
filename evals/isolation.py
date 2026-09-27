"""Offline eval isolation, installed before importing Waku or collecting tests.

Only synthetic dotenv files beneath the scratch directory can be loaded.
Python children inherit the guard through sitecustomize; native executables
are outside this Python guard and must be mocked by tests.
"""

from __future__ import annotations

import atexit
import ipaddress
import os
import socket
import sys
import tempfile
from pathlib import Path

_installed = False
_scratch = None
ROOT = Path(__file__).resolve().parents[1]
# These are process plumbing, never application settings or credentials.
_PROCESS_ENV = {
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "LANG", "LC_ALL", "TERM", "VIRTUAL_ENV",
}


def install() -> Path:
    global _installed, _scratch
    if _installed:
        return Path(os.environ["WAKU_EVAL_ROOT"])
    _installed = True
    inherited = os.environ.get("WAKU_EVAL_ROOT")
    if inherited:
        scratch = Path(inherited).resolve()
    else:
        _scratch = tempfile.TemporaryDirectory(prefix="waku-offline-")
        atexit.register(_scratch.cleanup)
        scratch = Path(_scratch.name).resolve()
        clean = {k: v for k, v in os.environ.items() if k.upper() in _PROCESS_ENV}
        os.environ.clear()
        os.environ.update(clean)
        os.environ.update({
            "WAKU_EVAL_ROOT": str(scratch), "WAKU_HOME": str(scratch / "home"),
            "HOME": str(scratch), "USERPROFILE": str(scratch),
            "APPDATA": str(scratch / "appdata"), "LOCALAPPDATA": str(scratch / "local"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        })
        # A child's first import installs the same guards before its -c / -m code.
        (scratch / "sitecustomize.py").write_text(
            "from evals.isolation import install\ninstall()\n", encoding="utf-8"
        )
        os.environ["PYTHONPATH"] = os.pathsep.join((str(scratch), str(ROOT)))
    sys.dont_write_bytecode = True
    _guard_dotenv(scratch)
    _guard_network()
    return scratch


def _guard_dotenv(scratch: Path) -> None:
    import dotenv
    import dotenv.main

    original_find = dotenv.find_dotenv
    original_load = dotenv.load_dotenv

    def find(*args, **kwargs):
        # Discovery is off unless a test explicitly exercises a synthetic file.
        if os.environ.get("WAKU_EVAL_ALLOW_DOTENV") != "1":
            return ""
        if not Path.cwd().resolve().is_relative_to(scratch):
            raise RuntimeError("Offline dotenv discovery must stay inside eval scratch")
        result = original_find(*args, **kwargs)
        return result if result and Path(result).resolve().is_relative_to(scratch) else ""

    def load(dotenv_path=None, *args, **kwargs):
        if not dotenv_path:
            dotenv_path = find(usecwd=True)
        if not dotenv_path:
            return False
        if not Path(dotenv_path).resolve().is_relative_to(scratch):
            raise RuntimeError("Offline eval blocked dotenv outside eval scratch")
        return original_load(dotenv_path, *args, **kwargs)

    dotenv.find_dotenv = dotenv.main.find_dotenv = find
    dotenv.load_dotenv = dotenv.main.load_dotenv = load


def _guard_network() -> None:
    def check(host):
        if host in (None, "localhost", b"localhost"):
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise OSError("Offline eval blocked external network access")

    def wrap_address(fn):
        def guarded(sock, address, *args, **kwargs):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                check(address[0])
            return fn(sock, address, *args, **kwargs)
        return guarded

    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        check(host)
        return original_getaddrinfo(host, *args, **kwargs)

    def wrap_host(fn):
        def guarded(host, *args):
            check(host)
            return fn(host, *args)
        return guarded

    original_sendto = socket.socket.sendto

    def sendto(sock, data, *args):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check(args[-1][0])
        return original_sendto(sock, data, *args)

    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = wrap_host(socket.gethostbyname)
    socket.gethostbyname_ex = wrap_host(socket.gethostbyname_ex)
    socket.socket.connect = wrap_address(socket.socket.connect)
    socket.socket.connect_ex = wrap_address(socket.socket.connect_ex)
    socket.socket.sendto = sendto
