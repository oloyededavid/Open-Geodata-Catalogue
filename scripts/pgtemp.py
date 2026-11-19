"""A throwaway PostgreSQL + PostGIS cluster for tests and local runs.

Creates a cluster in a temporary directory with initdb, starts it on a free port, creates database `geodata`
and the postgis extension, and removes everything on exit. When run as root the server runs as the
`postgres` user (PostgreSQL refuses to run as root).

    with TempPostGIS() as dsn: ...
    python scripts/pgtemp.py            # start one and wait (Ctrl-C to stop); prints the DSN
"""
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

PG_BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TempPostGIS:
    def __init__(self, port=None):
        self.port = port or free_port()
        self.dir = None

    def _run(self, *cmd, **kw):
        if os.geteuid() == 0:
            cmd = ("runuser", "-u", "postgres", "--") + cmd
        return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="geocat-pg-"))
        if os.geteuid() == 0:
            shutil.chown(self.dir, "postgres")
        data = self.dir / "data"
        self._run(str(PG_BIN / "initdb"), "-D", str(data), "-A", "trust", "-U", "postgres", "-E", "UTF8")
        self._run(str(PG_BIN / "pg_ctl"), "-D", str(data), "-l", str(self.dir / "server.log"), "-w",
                  "-o", f"-p {self.port} -k {self.dir} -c listen_addresses=127.0.0.1 -c fsync=off", "start")
        for _ in range(50):
            if subprocess.run([str(PG_BIN / "pg_isready"), "-h", "127.0.0.1", "-p", str(self.port)],
                              capture_output=True).returncode == 0:
                break
            time.sleep(0.2)
        base = f"postgresql://postgres@127.0.0.1:{self.port}"
        subprocess.run(["psql", f"{base}/postgres", "-qc", "CREATE DATABASE geodata"], check=True, capture_output=True)
        subprocess.run(["psql", f"{base}/geodata", "-qc", "CREATE EXTENSION postgis"], check=True, capture_output=True)
        self.dsn = f"{base}/geodata"
        return self.dsn

    def __exit__(self, *exc):
        try:
            self._run(str(PG_BIN / "pg_ctl"), "-D", str(self.dir / "data"), "-m", "fast", "-w", "stop")
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


def _stop_on_sigterm():
    """Turn SIGTERM into KeyboardInterrupt so the temporary cluster is stopped and removed."""
    import signal

    def handler(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, handler)


if __name__ == "__main__":
    _stop_on_sigterm()
    with TempPostGIS(int(os.environ.get("PGPORT_TEMP", 0)) or None) as dsn:
        print(dsn, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
