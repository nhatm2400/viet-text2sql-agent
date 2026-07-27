# viet-text2sql-agent — task runner.
# No Docker anywhere. Every target runs as a plain OS process in a virtualenv.
#
# Windows note: these targets work under GNU make (Git Bash / MSYS2 / choco install make).
# Without make, run the command shown under each target directly — they are plain one-liners.

ifeq ($(OS),Windows_NT)
	VENV_BIN := .venv/Scripts
	PY_BOOT  := python
else
	VENV_BIN := .venv/bin
	PY_BOOT  := python3
endif

PY   := $(VENV_BIN)/python
PIP  := $(VENV_BIN)/pip
CONFIG ?= eval/configs/baseline.yaml

.PHONY: venv lock seed demo-offline smoke test lint fmt run-api run-ui eval clean help

help:
	@echo "venv          create/sync .venv and install the project (editable) + dev extras"
	@echo "lock          freeze the current venv into requirements.lock"
	@echo "seed          run db/seed.py against DATABASE_URL (no-op with a message if unset)"
	@echo "demo-offline  run the agent loop on the 5 seed questions, OFFLINE_MODE=1"
	@echo "smoke         offline eval on the 5 seed items -> eval/results/<run_id>/summary.md"
	@echo "test          pytest (offline; no DB, no network)"
	@echo "lint          ruff check + format check"
	@echo "run-api       uvicorn t2sql.api.main:app --reload"
	@echo "run-ui        streamlit run ui/streamlit_app.py"
	@echo "eval          make eval CONFIG=eval/configs/baseline.yaml (online run)"

venv:
	$(PY_BOOT) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

lock:
	$(PY) -m pip freeze --exclude-editable > requirements.lock

seed:
	$(PY) db/seed.py

# --offline sets OFFLINE_MODE=1 from inside Python, so these targets need no shell-specific
# env-var prefix and behave identically on Windows cmd, PowerShell and POSIX shells.
demo-offline:
	$(PY) -m t2sql.agent.demo --offline

smoke:
	$(PY) -m eval.harness.runner --config eval/configs/baseline.yaml --offline

test:
	$(PY) -m pytest

lint:
	$(VENV_BIN)/ruff check .
	$(VENV_BIN)/ruff format --check .

fmt:
	$(VENV_BIN)/ruff format .
	$(VENV_BIN)/ruff check --fix .

run-api:
	$(VENV_BIN)/uvicorn t2sql.api.main:app --host 0.0.0.0 --port 8000 --reload

run-ui:
	$(VENV_BIN)/streamlit run ui/streamlit_app.py --server.port 8501

eval:
	$(PY) -m eval.harness.runner --config $(CONFIG)

clean:
	$(PY) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache','.ruff_cache']]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
