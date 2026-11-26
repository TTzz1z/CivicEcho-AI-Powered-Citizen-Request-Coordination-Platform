help:
	@echo "make"
	@echo "    clean"
	@echo "        Remove Python/build artifacts."
	@echo "    lint"
	@echo "        Lint backend code with ruff."
	@echo "    test"
	@echo "        Run backend pytest suite."
	@echo "    ci-static"
	@echo "        Compile and check backend Python syntax."
	@echo "    ci-backend"
	@echo "        Run backend tests inside Docker container."


clean:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f  {} +
	rm -rf build/
	rm -rf .pytype/
	rm -rf dist/
	rm -rf docs/_build

lint:
	ruff check backend/app backend/tests

test:
	pytest -q backend/tests

ci-static:
	python -m compileall -q backend/app backend/tests
	ruff check --select E9,F63,F7,F82 backend/app backend/tests

ci-backend:
	docker compose exec -T backend pip install -r requirements-dev.txt
	docker compose exec -T backend pytest -q

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
