.PHONY: build test
build:
	npm run build --prefix frontend
	npm run build --prefix mcp
test:
	.venv/bin/python backend/manage.py test core.tests ordering.tests --noinput
	npm test --prefix mcp
