"""Arranca la plataforma (API + frontend compilado) en un solo proceso.

Uso (desde la raíz del proyecto):
    backend\\.venv\\Scripts\\python backend\\scripts\\serve.py --host 0.0.0.0 --port 8010
    backend\\.venv\\Scripts\\python backend\\scripts\\serve.py --env-file ruta\\otro.env

Debe quedar un solo proceso: la sincronización automática vive dentro de él.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):  # tildes legibles en la consola y en los logs de Windows
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if args.env_file:
        os.environ["TVA_ENV_FILE"] = str(Path(args.env_file).resolve())
    sys.path.insert(0, str(BACKEND))
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, workers=1, proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
