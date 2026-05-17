PYTHON ?= python

.PHONY: install test examples clean

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m unittest -v

examples:
	$(PYTHON) compiler.py examples/hello.f
	$(PYTHON) compiler.py examples/factorial.f
	$(PYTHON) compiler.py examples/prime.f
	$(PYTHON) compiler.py examples/sumarr.f
	$(PYTHON) compiler.py examples/conversor.f
	$(PYTHON) compiler.py examples/subdobro.f
	$(PYTHON) compiler.py examples/tabmult.f
	$(PYTHON) compiler.py examples/media.f

clean:
	rm -f examples/*.vm
	rm -rf __pycache__ */__pycache__
	rm -f parser.out parsetab.py
