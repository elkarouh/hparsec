PYTHON ?= python3
export PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))

ZSH := tools/zsh_linter

.PHONY: test selftest examples zsh corpus verbose bench profile install

test: selftest examples zsh corpus

# Install a zsh-lint command into ~/.local/bin. The launcher runs the linter from this
# checkout, so there is no venv and no pip: hparsec is standard-library only.
# Re-run after moving the repository.
INSTALL_DIR ?= $(HOME)/.local/bin

install:
	mkdir -p $(INSTALL_DIR)
	printf '%s\n' '#!/bin/sh' 'PYTHONPATH="$(CURDIR)/src:$(CURDIR)/tools/zsh_linter$${PYTHONPATH:+:$$PYTHONPATH}" exec python3 -m zsh_linter "$$@"' > $(INSTALL_DIR)/zsh-lint
	chmod +x $(INSTALL_DIR)/zsh-lint
	@echo "installed $(INSTALL_DIR)/zsh-lint"

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
