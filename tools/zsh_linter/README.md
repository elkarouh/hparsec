# zsh-lint

Lints zsh scripts. It is built on [hparsec](../..), so install hparsec first.

    pip install . ./tools/zsh_linter     # from the repository root
    python -m zsh_linter ~/.zshrc deploy.zsh
    cat script.zsh | python -m zsh_linter -

Findings print as `file:line:col: RULE message`. The exit status is 0 when
clean, 1 when there are findings, and 2 on a parse error.
