API_PORT ?= 8000

.PHONY: setup db-up migrate seed-fixtures dev test e2e lint

setup:
	python3 -m compileall apps/api/app
	node --version

db-up:
	python3 apps/api/app/cli.py db-up

migrate:
	python3 apps/api/app/cli.py migrate

seed-fixtures:
	python3 apps/api/app/cli.py seed-fixtures

dev:
	PYTHONPATH=apps/api python3 apps/api/app/main.py --port $(API_PORT)

test:
	PYTHONPATH=apps/api python3 -m unittest discover -s apps/api/tests -p 'test_*.py'

e2e:
	PYTHONPATH=apps/api python3 apps/web/tests/e2e_fixture_flow.py

lint:
	PYTHONPATH=apps/api python3 -m compileall apps/api/app apps/api/tests

