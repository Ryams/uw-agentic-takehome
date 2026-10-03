.PHONY: setup up down test

setup:            ## install deps
	uv sync

up:               ## start leadgen (:8081, DEBUG=true for the answer key) + mailbox (:8025)
	cd sim-harness && DEBUG=true docker compose up --build -d

down:
	cd sim-harness && docker compose down

test:
	uv run pytest -q
