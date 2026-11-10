PYTHON ?= python3
export PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))

ZSH := examples/zsh_linter

.PHONY: test selftest examples zsh corpus verbose bench profile

test: selftest examples zsh corpus

# Built-in self-tests of the library modules
selftest:
	$(PYTHON) -B src/hek_parsec.py
	$(PYTHON) -B src/hek_tokenize.py

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
