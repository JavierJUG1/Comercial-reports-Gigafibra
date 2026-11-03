"""Arma el paquete de producción de Comercial reports (desde la raíz del proyecto).

    backend\\.venv\\Scripts\\python deploy\\empaquetar.py [--base-path /comercial_reports]

1. Compila el frontend para la subruta del servidor (en frontend/dist-prod, sin tocar el dist local).
2. Ejecuta las pruebas del backend.
3. Crea release/comercial-reports_<fecha>.zip con una lista cerrada de archivos y un MANIFIESTO.txt (SHA-256).
   Nunca entran backend/.env, backend/data/ (datos de clientes), pruebas ni node_modules.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PY = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print("›", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True, shell=(os.name == "nt" and cmd[0] in ("npm", "npx")))


def files() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []

    def add(src: Path, arc: str) -> None:
        out.append((src, arc))

    for p in sorted((BACKEND / "app").glob("*.py")):
        add(p, f"backend/app/{p.name}")
    for p in sorted((BACKEND / "config").glob("*.json")):
        add(p, f"backend/config/{p.name}")
    for p in sorted((BACKEND / "scripts").glob("*.py")):
        add(p, f"backend/scripts/{p.name}")
    for name in ("requirements.txt", ".env.example"):
        add(BACKEND / name, f"backend/{name}")
    dist = FRONTEND / "dist-prod"
    for p in sorted(dist.rglob("*")):
        if p.is_file():
            add(p, "frontend/dist/" + p.relative_to(dist).as_posix())
    for p in sorted((ROOT / "deploy").iterdir()):
        if p.is_file() and p.suffix in (".service", ".locations", ".py", ".md", ".sh"):
            add(p, f"deploy/{p.name}")
    add(ROOT / "README.md", "README.md")
    for p in sorted((ROOT / "docs").glob("*.md")):
        add(p, f"docs/{p.name}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-path", default="/comercial_reports")
    ap.add_argument("--sin-pruebas", action="store_true")
    args = ap.parse_args()

    env = {**os.environ, "VITE_BASE_PATH": args.base_path}
    run(["npx", "tsc", "-b", "--noEmit"], FRONTEND)
    run(["npx", "vite", "build", "--outDir", "dist-prod", "--emptyOutDir"], FRONTEND, env)
    index = (FRONTEND / "dist-prod" / "index.html").read_text(encoding="utf-8")
    if f'src="{args.base_path}/assets/' not in index:
        print(f"✘ El frontend no quedó compilado para {args.base_path}", file=sys.stderr)
        return 1
    if not args.sin_pruebas:
        run([str(PY), "-m", "pytest", "-q"], BACKEND)

    items = files()
    banned = [a for _, a in items if a.endswith("/.env") or "/data/" in a or "/tests/" in a or "node_modules" in a]
    if banned:
        print(f"✘ Archivos no permitidos en el paquete: {banned}", file=sys.stderr)
        return 1
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    dest = release / f"comercial-reports_{stamp}.zip"
    manifest = [f"Comercial reports - Gigafibra · paquete {stamp} · BASE_PATH={args.base_path}", ""]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in items:
            z.write(src, arc)
            manifest.append(f"{hashlib.sha256(src.read_bytes()).hexdigest()}  {arc}")
        z.writestr("MANIFIESTO.txt", "\n".join(manifest) + "\n")
    shutil.rmtree(FRONTEND / "dist-prod", ignore_errors=True)
    print(f"✔ {dest} ({len(items)} archivos, {dest.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
