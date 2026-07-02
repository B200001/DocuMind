# DocuMind — Agentic Document Intelligence

An open-source, fully local RAG + agentic document Q&A and drafting assistant.
See the implementation plan for details.

## Local setup

```bash
python -m venv .venv
make install
```

`make install` installs the shared `documind_core` package in editable mode with the Python 3.13-compatible setuptools flag. Without that flag, `pip show documind-core` can succeed while `import documind_core` fails.

Use the repo venv when running Python:

```bash
source .venv/bin/activate
# or
.venv/bin/python -c "import documind_core"
```
