.PHONY: test
test:
	PYTHONPATH=./src pytest src/test/ --html=src/test/reports/pytest_report.html -c src/test/conftest.py --sandbox
test-no-sandbox:
	PYTHONPATH=./src pytest src/test/ --html=src/test/reports/pytest_report.html -c src/test/conftest.py
compile-teal:
	PYTHONPATH=./src python src/teal/compile.py