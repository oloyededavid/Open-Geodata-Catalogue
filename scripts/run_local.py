"""Run the OGC API Features service locally without Docker.

Uses DATABASE_URL if set; otherwise starts a temporary PostGIS cluster (scripts/pgtemp.py, needs the PostgreSQL
16 and PostGIS binaries). Loads the catalogue's vector layers, then serves pygeoapi at http://localhost:5000
until Ctrl-C. The temporary database is removed on exit.

    python scripts/run_local.py [--port 5000]
"""
import argparse
import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_postgis import load  # noqa: E402
from pgtemp import TempPostGIS  # noqa: E402
import service_check  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()
    os.environ["PYGEOAPI_SERVER_URL"] = f"http://localhost:{a.port}"
    ctx = contextlib.nullcontext(os.environ["DATABASE_URL"]) if os.environ.get("DATABASE_URL") else TempPostGIS()
    with ctx as dsn:
        tables = load(dsn)
        print(f"loaded {len(tables)} tables; serving http://localhost:{a.port}/ (Ctrl-C to stop)")
        service_check.flask_client(dsn)  # configures the environment and imports the app
        from pygeoapi.flask_app import APP
        try:
            APP.run(host="127.0.0.1", port=a.port)
        except KeyboardInterrupt:
            pass


def _stop_on_sigterm():
    """Turn SIGTERM into KeyboardInterrupt so the temporary cluster is stopped and removed."""
    import signal

    def handler(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, handler)


if __name__ == "__main__":
    _stop_on_sigterm()
    main()
