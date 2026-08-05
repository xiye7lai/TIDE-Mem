.PHONY: install test check run docker-build

install:
	python -m pip install -r requirements-dev.txt

test:
	PYTHONPATH=. pytest -q

check: test
	python -m compileall -q tide_mem scripts
	bash -n deploy/docker-entrypoint.sh

run:
	uvicorn tide_mem.api:app --host 0.0.0.0 --port 8000

docker-build:
	docker build --tag tide-mem:0.1.0-amc2026 .
