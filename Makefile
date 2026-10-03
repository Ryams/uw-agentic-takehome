.PHONY: down ui-cc eval-cc smoke-cc run-cc setup up down test smoke-llm run demo-offline ui ui-offline eval eval-offline eval-live

setup:            ## install deps + enable the version-bump pre-commit hook
	uv sync
	git config core.hooksPath .githooks

up:               ## start leadgen (:8081, DEBUG=true for the answer key) + mailbox (:8025)
	cd sim-harness && DEBUG=true docker compose up --build -d

down:             ## stop the docker services AND any UI server started by `make ui*`
	cd sim-harness && docker compose down
	@pkill -f "uw_agent.server:make_app" && echo "stopped UI server" || true

test:
	uv run pytest -q

smoke-llm:        ## live check of the 3 LLM edges (needs ANTHROPIC_API_KEY in .env)
	uv run python -m uw_agent.smoke_llm

run:              ## run the queue end to end with Claude (needs `make up` and ANTHROPIC_API_KEY)
	uv run python -m uw_agent.cli run --seed 42

demo-offline:     ## same, with the rule-based stand-in instead of Claude (no API key)
	uv run python -m uw_agent.cli run --seed 42 --offline

ui:               ## underwriter UI on http://localhost:8090 (needs `make up` and ANTHROPIC_API_KEY)
	uv run uvicorn --factory uw_agent.server:make_app --port 8090

ui-offline:       ## same UI with the rule-based stand-in (no API key)
	UW_OFFLINE=1 uv run uvicorn --factory uw_agent.server:make_app --port 8090

eval:             ## all eval sets (seeded + fixed) in-process; Claude if ANTHROPIC_API_KEY is set, else the offline stand-in
	uv run python -m evals.runner

eval-offline:     ## same, forcing the rule-based stand-in (deterministic, no key)
	uv run python -m evals.runner --llm offline

eval-live:        ## seeded sets against the docker stack (needs `make up`; leadgen DEBUG=true)
	uv run python -m evals.runner --live

# --- Claude via your local Claude Code login (no API key; D26) ---
smoke-cc:         ## live check of the 3 LLM edges through `claude -p`
	UW_LLM=claude-code uv run python -m uw_agent.smoke_llm

ui-cc:            ## UI with Claude via Claude Code (needs `make up` and a logged-in `claude`)
	UW_LLM=claude-code uv run uvicorn --factory uw_agent.server:make_app --port 8090

run-cc:           ## terminal run with Claude via Claude Code
	uv run python -m uw_agent.cli run --seed 42 --llm claude-code

eval-cc:          ## all eval sets with Claude via Claude Code (slow; uses subscription usage)
	uv run python -m evals.runner --llm claude-code
