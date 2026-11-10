PYTHON ?= python3
export PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))

ZSH := tools/zsh_linter

.PHONY: test selftest examples zsh corpus verbose bench profile install

test: selftest examples zsh corpus

# Editable install of hparsec and the zsh-lint command into a project-local venv, so it
# works with externally managed Pythons (PEP 668). Run .venv/bin/zsh-lint afterwards.
# pip needs -e before each path.
VENV ?= .venv

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -e . -e ./tools/zsh_linter

# Built-in self-tests of the library modules
selftest:
	$(PYTHON) -B src/hparsec.py
	$(PYTHON) -B src/ady_tokenizer.py

# Example grammars (each asserts its own results)
examples:
	$(PYTHON) -B examples/expression_parser.py
	$(PYTHON) -B examples/expression_parser_lr.py

# Zsh linter unit cases and corpus run
zsh:
	$(PYTHON) -B $(ZSH)/zsh_linter.py

corpus:
	$(PYTHON) -B $(ZSH)/corpus_test.py $(ZSH)/corpus

verbose:
	$(PYTHON) -B $(ZSH)/corpus_test.py $(ZSH)/corpus -v

bench:
	$(PYTHON) -B benchmarks/benchmark_hparsec.py

profile:
	$(PYTHON) -B benchmarks/profile_hparsec.py
