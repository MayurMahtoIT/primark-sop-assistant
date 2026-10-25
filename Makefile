.PHONY: setup up ingest down test lint eval tf-fmt tf-plan
setup:
	cp -n .env.example .env || true
up: setup
	docker compose up --build -d postgres api
ingest:
	docker compose --profile ingest run --rm ingest
down:
	docker compose down
test:
	cd backend && pip install -q -r requirements-dev.txt && pytest -q
lint:
	cd backend && ruff check . && ruff format --check .
eval:
	cd backend && python -m eval.run_eval --eval-all-k
tf-fmt:
	terraform -chdir=infra/terraform fmt -recursive
tf-plan:
	terraform -chdir=infra/terraform plan -var-file=envs/$(ENV).tfvars
