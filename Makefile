.PHONY: install test clean all plots cpu io-http io-disk scaling mixed pitfalls

PYTHON := PYTHONPATH=. .venv/bin/python
PIP := .venv/bin/pip
PYTEST := PYTHONPATH=. .venv/bin/pytest

install:
	$(PIP) install -r requirements.txt

test:
	$(PYTEST) tests/ -v

cpu:
	$(PYTHON) experiments/01_cpu_primes.py

io-http:
	$(PYTHON) experiments/02_io_http.py

io-disk:
	$(PYTHON) experiments/03_io_disk.py

scaling:
	$(PYTHON) experiments/04_scaling.py

mixed:
	$(PYTHON) experiments/05_mixed.py

all: cpu io-http io-disk scaling mixed

plots:
	@for csv in results/*.csv; do \
		base=$$(basename $$csv .csv); \
		if [ "$$base" = "04_scaling" ]; then \
			$(PYTHON) -c "from pathlib import Path; from lab.plot import scaling_line; scaling_line(Path('$$csv'), Path('results/$$base.png'))"; \
		else \
			$(PYTHON) -c "from pathlib import Path; from lab.plot import compare_bar; compare_bar(Path('$$csv'), Path('results/$$base.png'))"; \
		fi; \
		echo "  regenerated results/$$base.png"; \
	done

pitfalls:
	@for f in pitfalls/*.py; do \
		echo "=== $$f ==="; \
		timeout 70 $(PYTHON) $$f || true; \
		echo; \
	done

clean:
	rm -rf results/* tmp_data/*
