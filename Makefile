.PHONY: setup up down test smoke-llm

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
