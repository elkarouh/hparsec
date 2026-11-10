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

ZSH003, ZSH004 and ZSH008 cover ksh rules 49 (backticks), 1 (`[ ]` instead of `[[ ]]`) and 12 (`<<<`). Their messages now use the ksh wording.

The rules ported from the ksh checker scripts are lint methods on the grammar's nodes, so they read the parse
tree: `command` checks the command name and its arguments, `pipeline` its stages, `test_construct` and
`dbl_test_construct` the words of a test, and so on. A node's `check()` returns its own findings, and
`__default__.lint()` visits the children. The rules on single words (ZSH016, ZSH022, ZSH023, ZSH029, ZSH034,
ZSH038, ZSH047 to ZSH049) read the tokens, like ZSH009. Trailing blanks and tabs (ZSH021, ZSH044) read the source
lines, because the tree has no whitespace; here-document bodies are skipped.

| Rule | Checks |
|---|---|
| ZSH010 | the `test` command; use `[[ ... ]]` |
| ZSH011 | comparison with `""` or `''`; use `-z` or `-n` |
| ZSH012 | `! -n` or `! -z`; use the opposite |
| ZSH013 | negated comparison; use the opposite operator |
| ZSH014 | `-n` or `-z` on a name without `$` |
| ZSH015 | a `{name}` word without `$` (brace expansion such as `{a,b}` is not reported) |
| ZSH016 | whitespace in `${...}` |
| ZSH017 | numeric comparison with `<`, `>`, `=` or `!=`; use `-lt` and the like |
| ZSH018 | `typeset -i N=` with no value |
| ZSH020 | `wc \| awk` with no option to `wc` |
| ZSH021 | trailing blanks |
| ZSH022 | braces around `$0`, `$1`, `$?`, `$@`, `$*` and the like |
| ZSH023 | `$*`; use `$@` |
| ZSH029 | `$NF` or `${NF}` expanded by the shell (awk programs in single quotes are not) |
| ZSH030 | `tee` with `2>&1` after a pipe |
| ZSH032 | `[[ ]] && [[ ]]`; combine the tests |
| ZSH033 | `name ()`; use `function name` |
| ZSH034 | `.$(cm_where` in a path; use `!` |
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
| ZSH049 | `${OPC_USER}` or `${OPC_SERVICE_NAME}`; write them without braces |
| ZSH050 | `[[ ]]` test with no `$` in it (file and option tests are skipped) |
| ZSH051 | a bare word after `&&` or `\|\|` inside `[[ ]]` |

ksh rule 13 (`>>&1`) and rule 30 (`${VAR}=value`) have no code: the grammar does not parse those forms, so
zsh-lint reports a parse error for them. ZSH017 also reports `==` and `!=` against a number, which is a string
test in zsh. `OPC_USER` and `OPC_SERVICE_NAME` are exempt from ZSH009 and its fix, because OML/OBM reads them as
literals. ZSH049 reports their braced form instead.

## Fixes

`zsh-lint --format script.zsh` prints the script rendered from its tree: one statement per line, block bodies
indented by four spaces, and comments where they were written. Here-documents and multi-line strings are
written as they are. `zsh-lint --format --fix script.zsh` also fixes the findings of the rules
in `AUTO_FIXES`. The node that reports a finding also renders the fix in its `to_source`, so what is
reported is what is fixed:

| Rule | Fix |
|---|---|
| ZSH002 | quote an expansion used as an assignment value: `x=$a` becomes `x="$a"` |
| ZSH004 | `[ ... ]` becomes `[[ ... ]]` |
| ZSH009 | `$name` becomes `${name}` |
| ZSH010 | `test ...` becomes `[[ ... ]]` |
| ZSH018 | `typeset -i N=` becomes `typeset -i N=0` |
| ZSH022 | `${1}` becomes `$1` |
| ZSH033 | `name () {` becomes `function name {`; in zsh both forms behave the same |

ZSH004 and ZSH010 are fixed only where `[[ ]]` reads the words the same way: no expansion, no glob character,
no `-a`, `-o`, parentheses, `<` or `>`. Other findings are reported only. ZSH035 in particular is not fixed,
because moving `2>&1` changes where stderr goes.

## Variable and return-code checks

These follow names and return codes through the tree, ported from the ksh checkers. Each node reports the
names it assigns or uses through `variables()`, and a node that holds statements compares what one statement
leaves in `$?` with what the next one tests.

| Rule | Checks |
|---|---|
| ZSH052 | a name is used but never assigned in the file (may be set by a caller or a config file) |
| ZSH053 | a name is assigned but never used, unless it is exported |
| ZSH054 | a read-only or define_configuration name is assigned |
| ZSH055 | `$?` is tested right after a pipe into `tee` |
| ZSH056 | `$?` is tested right after `typeset VAR=$(...)` |
| ZSH057 | `$?` is tested after a call to a function that calls `exit` |

A name counts as assigned anywhere in the file, whatever the order. `NAME=value` as a command argument
(`alias`, `env`) does not count. ZSH052 reports names that come from the environment or a config file, such as
prompt variables, so expect it on any real configuration. A few names a login shell or a terminal normally sets
are exempt; that list is a zsh addition, not from the ksh checker.
