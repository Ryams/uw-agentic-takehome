.PHONY: setup up down test

setup:            ## install deps + enable the version-bump pre-commit hook
	uv sync
	git config core.hooksPath .githooks

up:               ## start leadgen (:8081, DEBUG=true for the answer key) + mailbox (:8025)
	cd sim-harness && DEBUG=true docker compose up --build -d

down:
	cd sim-harness && docker compose down

test:
	uv run pytest -q
