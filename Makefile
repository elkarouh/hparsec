PYTHON ?= python3
export PYTHONPATH := $(CURDIR)/src:$(CURDIR)/ady_helpers$(if $(PYTHONPATH),:$(PYTHONPATH))

ZSH := tools/zsh_linter

.PHONY: test selftest examples zsh corpus basic lisp verbose syntax bench profile install install-pip

test: selftest examples zsh corpus basic lisp

# Install a zsh-lint command into ~/.local/bin. The launcher runs the linter from this
# checkout, so there is no venv and no pip: hparsec is standard-library only.
# Re-run after moving the repository.
INSTALL_DIR ?= $(HOME)/.local/bin

install:
	mkdir -p $(INSTALL_DIR)
	printf '%s\n' '#!/bin/sh' 'PYTHONPATH="$(CURDIR)/src:$(CURDIR)/ady_helpers:$(CURDIR)/tools/zsh_linter$${PYTHONPATH:+:$$PYTHONPATH}" exec python3 -m zsh_linter "$$@"' > $(INSTALL_DIR)/zsh-lint
	chmod +x $(INSTALL_DIR)/zsh-lint
	@echo "installed $(INSTALL_DIR)/zsh-lint"

# Install hparsec and zsh_linter as Python packages with an installer of your choice,
# e.g. make install-pip PIP=pip_install. The installer must accept pip's arguments.
PIP ?= python3 -m pip

install-pip:
	$(PIP) install -e . -e ./tools/zsh_linter

# Built-in self-tests of the library modules
selftest:
	$(PYTHON) -B src/hparsec.py
	$(PYTHON) -B ady_helpers/ady_tokenizer.py
	$(PYTHON) -B ady_helpers/ady_tokens.py

# Example grammars (each asserts its own results)
examples:
	$(PYTHON) -B examples/expression_parser.py
	$(PYTHON) -B examples/expression_parser_lr.py

# BASIC interpreter self-tests and its example program
basic:
	$(PYTHON) -B tools/basic_interpreter/basic_interpreter.py
	$(PYTHON) -B tools/basic_interpreter/basic_interpreter.py tools/basic_interpreter/examples/functions.bas

# Lisp interpreter self-tests and its example program
lisp:
	$(PYTHON) -B tools/lisp_interpreter/lisp_interpreter.py --test
	$(PYTHON) -B tools/lisp_interpreter/lisp_interpreter.py tools/lisp_interpreter/examples/closures.scm

# Zsh linter unit cases and corpus run
zsh:
	$(PYTHON) -B $(ZSH)/zsh_linter.py

corpus:
	$(PYTHON) -B $(ZSH)/corpus_test.py $(ZSH)/corpus

# Parse-check every .sh, .zsh and .ksh file under DIR (recursively); reports only syntax errors.
# Exit status is 0 when all files parse, 2 when any fails.
# Example: make syntax DIR=~/dotfiles
DIR ?= .
syntax:
	@find "$(DIR)" -type f \( -name '*.sh' -o -name '*.zsh' -o -name '*.ksh' \) -not -path '*/.git/*' -print0 \
	  | xargs -0 -r $(PYTHON) -B $(ZSH)/zsh_linter.py --check-syntax

verbose:
	$(PYTHON) -B $(ZSH)/corpus_test.py $(ZSH)/corpus -v

bench:
	$(PYTHON) -B benchmarks/benchmark_hparsec.py

profile:
	$(PYTHON) -B benchmarks/profile_hparsec.py
