.PHONY: install backend frontend test

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm ci

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -I app/tests/test_business_chains.py
	cd backend && .venv/bin/python -I app/tests/test_lineage_structured.py
	cd backend && .venv/bin/python -I app/tests/test_lineage_api.py
