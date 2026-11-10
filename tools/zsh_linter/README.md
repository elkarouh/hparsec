# zsh-lint

Lints zsh scripts. It is built on [hparsec](../..), so install hparsec first.

    make install                         # from the repository root, puts zsh-lint in ~/.local/bin
    zsh-lint ~/.zshrc deploy.zsh
    cat script.zsh | zsh-lint -

To check a whole directory tree for syntax errors only, from the repository root:

    make syntax DIR=~/dotfiles

It checks `.sh`, `.zsh` and `.ksh` files. Findings print as `file:line:col: RULE message`. The exit status is 0 when
clean, 1 when there are findings, and 2 on a parse error.

## Style rules

`style_rules.py` adds line-level style rules ported from the ksh checker scripts. They run on the
script with comments blanked out, and report with the same `file:line:col: RULE message` format:

| Rule | Checks |
|---|---|
| ZSH010 | `test` in a condition; use `[[ ... ]]` |
| ZSH011 | comparison with `""` or `''`; use `-z` or `-n` |
| ZSH012 | `! -n` or `! -z`; use the opposite |
| ZSH013 | negated comparison; use the opposite operator |
| ZSH014 | `-n` or `-z` on a name without `$` |
| ZSH015 | `{name` without `$` (brace expansion such as `a.{x,y}` is reported) |
| ZSH016 | whitespace in `${...}` |
| ZSH017 | numeric comparison with `<`, `>`, `=` or `!=`; use `-lt` and the like |
| ZSH018 | `typeset -i N=` with no value |
| ZSH019 | `>>&`; use `>&` |
| ZSH020 | `wc \| awk` with nothing between them |
| ZSH021 | trailing blanks |
| ZSH022 | braces around `$0`, `$1`, `$?`, `$@`, `$*` and the like |
| ZSH023 | `$*`; use `$@` |
| ZSH029 | `${NF}`, or `$NF` in a script without awk |
| ZSH030 | `tee` followed by `2>&1` on the same line |
| ZSH031 | `${VAR}=value` |
| ZSH032 | `[[ ]] && [[ ]]`; combine the tests |
| ZSH033 | `name ()`; use `function name` |
| ZSH034 | `.$(cm_where`; use `!` |
| ZSH035 | `2>&1 >file`; redirect stderr after the file |
| ZSH036 | `Log ... >&2` |
| ZSH037 | `Log` level without `-i`, `-w`, `-s` or `-f` |
| ZSH038 | `y/n` prompt; use the `confirm` script |
| ZSH040 | trailing blank inside a `Log` message |
| ZSH041 | `alias_get` with `Value`; use `-q` |
| ZSH042 | `cd -`; use `cd "${OLDPWD}"` |
| ZSH043 | unquoted first argument of `tr` |
| ZSH044 | tab character |
| ZSH045 | unquoted file mask in `cfmu_ftps_list` or `cfmu_ftps_get` |
| ZSH046 | `bmw VAR \| awk`; use `bmw -V VAR` |
| ZSH047 | `.LATEST` alias; use `.LATEST_GOOD` |
| ZSH048 | `CFMU_OS` |

These rules are line-based, so they can report a pattern inside a string or a multi-line construct. ZSH017
also reports `==` and `!=` against a number, which is a string test in zsh. Rule numbers skip the ones
that are not implemented: ZSH009 already covers `$name` without braces, so the ksh rule for
`$OPC_USER` (braces are forbidden) is not implemented. The variable-flow and return-code checks are
not implemented either.
