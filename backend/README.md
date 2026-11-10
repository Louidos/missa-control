# Missa Control – Backend

FastAPI-App des Panels. Quelltext in `src/missa_control/`, Tests in `tests/`.

```bash
uv sync                 # Abhängigkeiten installieren (Python 3.12)
uv run ruff check .     # Linter
uv run pytest           # Tests
uv run python -m missa_control   # lokal starten (http://127.0.0.1:8090)
```

Die Gesamtanleitung steht im [README des Repos](../README.md).
