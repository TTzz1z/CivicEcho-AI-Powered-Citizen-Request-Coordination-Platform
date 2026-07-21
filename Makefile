help:
	@echo "make"
	@echo "    clean"
	@echo "        Remove Python/build artifacts."
	@echo "    formatter"
	@echo "        Apply black formatting to code."
	@echo "    lint"
	@echo "        Lint code with flake8, and check if black formatter should be applied."
	@echo "    types"
	@echo "        Check for type errors using pytype."
	@echo "    validate"
	@echo "        Runs the rasa data validate to verify data."
	@echo "    train"
	@echo "        Trains the verified Tingting baseline in Docker."
	@echo "    test"
	@echo "        Runs the rasa test suite checking for issues."
	@echo "    crossval"
	@echo "        Runs the rasa cross validation tests and creates results.md"
	@echo "    shell"
	@echo "        Runs the rasa train and rasa shell for testing"


clean:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f  {} +
	rm -rf build/
	rm -rf .pytype/
	rm -rf dist/
	rm -rf docs/_build

formatter:
	black actions --line-length 79

lint:
	flake8 actions
	black --check actions

types:
	pytype --keep-going actions

validate:
	docker compose run --rm rasa data validate

train:
	docker compose run --rm rasa train --fixed-model-name tingting-v1.0.0.tar.gz

test:
	docker compose run --rm rasa test core --stories tests/test_conversations.yml --model models/tingting-v1.0.0.tar.gz --fail-on-prediction-errors
	docker compose run --rm rasa test nlu --nlu tests/test_nlu.yml --model models/tingting-v1.0.0.tar.gz
	docker compose run --rm --no-deps --entrypoint python rasa -m unittest discover -s tests -p test_public_request_actions.py -v

crossval:
	rasa test nlu -f 5 --cross-validation
	python format_results.py

shell:
	docker compose run --rm rasa shell --model models/tingting-v1.0.0.tar.gz --debug

ci-static:
	python -m compileall -q backend/app backend/tests actions channels tests
	ruff check --select E9,F63,F7,F82 backend/app backend/tests actions channels tests

ci-backend:
	docker compose exec -T backend pip install -r requirements-dev.txt
	docker compose exec -T backend pytest -q

ci-actions:
	docker compose exec -T action_server python -m unittest discover -s /app/tests -p 'test_public_request_actions.py' -v
	docker compose exec -T action_server python -m unittest discover -s /app/tests -p 'test_ticket_gateway.py' -v

ci-rasa:
	docker compose run --rm --no-deps rasa data validate
	docker compose run --rm --no-deps rasa test core --stories tests/test_conversations.yml --model models/tingting-v1.0.0.tar.gz --fail-on-prediction-errors --out results/round7-core

ci-integration:
	docker compose up -d --build --wait
	docker compose exec -T -e LOCAL_SEED_PASSWORD backend python -m app.seed_local
	python scripts/docker_round4_integration.py

demo:
	docker compose up -d --build --wait
	docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE=demo backend python -m app.seed

seed:
	docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE backend python -m app.seed

reset-db:
	docker compose down -v --remove-orphans
	docker compose up -d --build --wait
	docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE=demo backend python -m app.seed

e2e:
	sh scripts/run-e2e.sh

migration-current:
	docker compose exec -T backend alembic current
