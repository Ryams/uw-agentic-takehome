.PHONY: setup up down test smoke-llm run demo-offline

setup:            ## install deps + enable the version-bump pre-commit hook
	uv sync
	git config core.hooksPath .githooks

up:               ## start leadgen (:8081, DEBUG=true for the answer key) + mailbox (:8025)
	cd sim-harness && DEBUG=true docker compose up --build -d

down:
	cd sim-harness && docker compose down

test:
	uv run pytest -q

smoke-llm:        ## live check of the 3 LLM edges (needs ANTHROPIC_API_KEY in .env)
	uv run python -m uw_agent.smoke_llm

run:              ## run the queue end to end with Claude (needs `make up` and ANTHROPIC_API_KEY)
	uv run python -m uw_agent.cli run --seed 42

demo-offline:     ## same, with the rule-based stand-in instead of Claude (no API key)
	uv run python -m uw_agent.cli run --seed 42 --offline
