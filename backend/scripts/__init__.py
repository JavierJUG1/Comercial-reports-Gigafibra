import sys

# La consola de Windows usa cp1252 por defecto: forzar UTF-8 para tildes y símbolos.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
