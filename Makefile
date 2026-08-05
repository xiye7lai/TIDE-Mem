.PHONY: install test check run docker-up docker-down

install:
	python -m pip install -r requirements-dev.txt

test:
	PYTHONPATH=. pytest -q

check: test
	python -m compileall -q tide_mem scripts
	bash -n deploy/docker-entrypoint.sh

run:
	uvicorn tide_mem.api:app --host 0.0.0.0 --port 8000

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
