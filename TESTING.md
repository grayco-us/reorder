# Development checks

Use Python 3.13 in a virtual environment. The regression baseline is Home Assistant
2025.12.5 with its matching frontend 20251203.3; both are pinned in
`requirements-test.txt`. Reorder's `frontend`/`panel_custom` dependencies are real in
these tests, not mocked away.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_panel.mjs
```

The base Home Assistant wheel does not install every integration requirement.
Preinstall the pinned frontend before starting tests. Relying on HA's runtime
installer from a global interpreter can install it into a user-site directory absent
from the already-running process's import path, causing `frontend`/`panel_custom`
setup errors across the suite. CI uses a virtual environment, disables user-site
fallback, and verifies the frontend package against HA's own manifest before tests.
When changing the HA baseline, update both pins together.

Tests use temporary Home Assistant configurations and mocked Zinc transport, with
synthetic credentials. Do not supply live credentials or connect a production HA
instance. The optional Playwright browser test uses only intercepted local fixtures;
it is separate from the Python CI dependency setup.
