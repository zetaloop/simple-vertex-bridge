# Build & Release

```bash
cd simple-vertex-bridge
uv sync
source .venv/bin/activate  # Linux/MacOS
# Windows CMD: .venv\Scripts\activate.bat
# Windows Pwsh: .venv\Scripts\Activate.ps1
uv pip install build twine
python -m build
python -m twine upload dist/*
```
