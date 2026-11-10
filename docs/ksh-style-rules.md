# ksh coding style rules

These rules are derived from a small grep-based checker script (`ksh_style_check`, not in this repository). The script
strips comments from one ksh file, runs 15 grep checks over it and prints every matching line with the rule it
breaks. Its own header warns that "there might be some false positive, so the results have to be analyzed carefully".

Each rule below gives the rule as an instruction, the grep pattern the script uses to find violations, the rationale
(quoted from the script's comments where it has one), and the false positives and gaps of the pattern. Where a pattern
looks buggy or too broad, that is said under **Pattern issues** and the pattern is left as the script has it.

Patterns are GNU grep basic regular expressions (BRE), so `|` is a literal character and `\|` is alternation. The
claims about what a pattern does or misses were checked by running it with GNU grep against small sample lines.

Overlap with this repository: [`tools/zsh_linter`](../tools/zsh_linter) also checks `.ksh` files. Its rule ZSH004
("prefer `[[ ... ]]` over `[ ... ]`") matches rule 1, and ZSH008 (here-string `<<<` used) matches rule 12. Its rule
ZSH009 ("write `${name}` instead of `$name`") conflicts with rule 9 for the two variables that rule names.

| # | Rule | Theme |
|---|------|-------|
| 1 | Use `[[ ]]` instead of `[ ]` | Tests |
| 2 | Use `[[ ]]` instead of `test` | Tests |
| 3 | Use `-n` / `-z` instead of comparing with `""` or `''` | Tests |
| 4 | Use `-n` / `-z` instead of `! -z` / `! -n` | Tests |
| 5 | Use the opposite operator instead of negating a comparison | Tests |
| 6 | Put `$` before every `{VAR}` | Variables, quoting and braces |
| 7 | Put `$` before every variable inside `[[ ]]` | Variables, quoting and braces |
| 8 | Never put whitespace inside `${...}` | Variables, quoting and braces |
| 9 | Write `$OPC_SERVICE_NAME` and `$OPC_USER` without braces | Variables, quoting and braces |
| 10 | Compare numbers with numeric operators | Arithmetic |
| 11 | Give `typeset -i` an explicit value | typeset |
| 12 | Do not use the here-string `<<<` | Redirections |
| 13 | Duplicate file descriptors with `>&`, not `>>&` | Redirections |
| 14 | Use `wc -l`, `wc -w` or `wc -c` instead of `wc \| awk` | Commands and pipelines |
| 15 | No trailing blanks | Whitespace |

The order above groups the rules by theme, so it is not the order of the checks in the script.

## Where each rule lives in zsh-lint

The rules are implemented in `tools/zsh_linter` as ZSH codes. The mapping is below. Rules 18, 19, 21 and 22 describe how the checker works, so they have no code. Rule 26 is not a check in the script, so it has no code. Rules 36 and 46 are marked "under test, not approved" in the scripts and are not implemented. Rules 13 and 30 have no code: the zsh grammar does not parse `>>&1` or `${VAR}=value`, so zsh-lint reports a parse error for them.

| Rule | zsh-lint | Rule | zsh-lint |
|---|---|---|---|
| 1 | ZSH004 | 27 | ZSH022 |
| 2 | ZSH010 | 28 | ZSH023 |
| 3 | ZSH011 | 29 | ZSH029 |
| 4 | ZSH012 | 30 | (parse error) |
| 5 | ZSH013 | 31 | ZSH014 |
| 6 | ZSH015 | 32 | ZSH032 |
| 7 | ZSH050 | 33 | ZSH033 |
| 8 | ZSH016 | 34 | ZSH051 |
| 9 | ZSH049 (and ZSH009 exempts the names) | 35 | ZSH034 |
| 10 | ZSH017 | 37 | ZSH030 |
| 11 | ZSH018 | 38 | ZSH035 |
| 12 | ZSH008 | 39 | ZSH036 |
| 13 | (parse error) | 40 | ZSH037 |
| 14 | ZSH020 | 41 | ZSH038 |
| 15 | ZSH021 | 42 | ZSH042 |
| 16 | ZSH052 | 43 | ZSH043 |
| 17 | ZSH053 | 44 | ZSH045 |
| 20 | ZSH054 | 45 | ZSH046 |
| 23 | ZSH055 | 47 | ZSH040 |
| 24 | ZSH056 | 48 | ZSH041 |
| 25 | ZSH057 | 49 | ZSH003 |
| | | 50 | ZSH047 |
| | | 51 | ZSH044 |
| | | 52 | ZSH048 |

## Before the checks: comment stripping

The script first removes comments, so that a variable named in a comment is not reported, and keeps the empty lines so
that line numbers still match the original file:

```sh
sed -e 's/[[:blank:]]*[[:blank:]]#.*//' -e 's/^#.*//' ${ORIG_FILE} > ${TMP}
```

A `#` counts as a comment only at the start of a line or after a blank, so `${MY_VAR#CHAR_I_REMOVE}`, `$#` and `16#ff`
survive.

**Pattern issues.** The sed does not know about quotes or here-documents. `echo "Total: 3 # items"` becomes
`echo "Total: 3`, so every check after that sees a line with an unclosed quote. A blank followed by `#` inside a
here-document is cut as well. The first expression also removes the blanks in front of a trailing comment, so rule 15
can never fire on a line that ends with a comment.

## Tests

### 1. Use `[[ ]]` instead of `[ ]`

```sh
grep -n -H -e "[[:space:]]*if[[:space:]]*[[][[:space:]]" \
           -e "\(if[[:space:]]\|while[[:space:]]\|^[[:space:]]*\)[[:space:]]*[[][[:space:]]" \
           -e "\(if\|while\)[[:space:]]*[^[][[:space:]]*[[][[:space:]]"
```

The first pattern is for `if [`, the second for `while [` and a `[` at the start of a line, and the third for an odd
construct the others miss: `while ([ ! -z "$1" ]); do`. A `[[ ` never matches, because the character after the first
`[` must be a blank.

**Rationale.** "The single square brackets shall be replaced by double square brackets." The script adds a warning for
the conversion: inside `[[ ]]` no filename expansion happens, so `[ -f ${VAR} ]` with `VAR='*.log'` tests the expanded
file names while `[[ -f ${VAR} ]]` tests a file literally named `*.log`. When `${VAR}` holds a pattern, the `if` has to
be `eval`'ed.

**False positives.** A line in a here-document or a string that starts with `[ `. Any word that ends in `if` or
`while` before `[ `, such as `diff [ `, matches the first and third patterns. Those are rare in practice.

**Pattern issues.**
- The first pattern is redundant, because everything it matches is also matched by the second. Its leading
  `[[:space:]]*` has no effect in a pattern that is not anchored.
- `until [`, and a `[ ` after `&&`, `||`, `;` or `|` in the middle of a line, are not found. For example
  `x && [ -n "$a" ]` passes.

### 2. Use `[[ ]]` instead of `test`

```sh
grep -n -H -e "\(if\|while\) test "
```

**Rationale.** "Using test instead of [[ in conditions." This is the same rule as rule 1, written with `test`.

**Gaps.** `until test`, and `test` used outside `if` and `while` (`test -f x && ...`), are not found.

### 3. Use `-n` / `-z` instead of comparing with `""` or `''`

Write `[[ -n ${X} ]]` instead of `[[ ${X} != "" ]]`, and `[[ -z ${X} ]]` instead of `[[ ${X} = "" ]]`.

```sh
grep -n -H -e '[[].*=[[:blank:]]*"".*[]]' \
           -e '[[].*""[[:blank:]][!]*=.*[]]' \
           -e "[[].*=[[:blank:]]*[''][''].*[]]" \
           -e "[[].*[''][''][[:blank:]][!]*=.*[]]"
```

The first two patterns look for `""` on the right and on the left of `=`, `==` or `!=`. The last two do the same for
`''`.

**Rationale.** "`!= ""` or `!= ''` construct shall be replaced by -n, `= ""` or `= ''` construct shall be replaced
by -z."

**False positives.** The pattern only needs some `[` before the `=""` and some `]` after it on the same line, so an
assignment of an empty string next to a subscript or a test matches. `[[ -n $a ]] && b=""; c[1]=1` is reported. The
same applies to awk code such as `awk '{a[$1]=""} END {...}'`, and to sed expressions.

**Pattern issues.** The patterns with `""` on the left require exactly one blank before the operator, so
`[[ ""  = $x ]]` (two blanks) passes.

### 4. Use `-n` / `-z` instead of `! -z` / `! -n`

Write `-n` instead of `! -z`, and `-z` instead of `! -n`.

```sh
grep -n -H 'if.*![[:blank:]]*-[nz] '
```

**Rationale.** "! -z construct shall be replaced by -n, ! -n construct shall be replaced by -z."

**Pattern issues.** The line must contain `if`, so `[[ ! -z $x ]] && ...` and `while [[ ! -n $x ]]` pass.
`if ! [[ -z $x ]]` also passes, although it is the same double negation. The space after `-z` is required, so
`! -z"$x"` passes too.

### 5. Use the opposite operator instead of negating a comparison

| Instead of | Write |
|---|---|
| `! ${VAR} -eq` | `${VAR} -ne` |
| `! ${VAR} -ne` | `${VAR} -eq` |
| `! ${VAR} =` | `${VAR} !=` |
| `! ${VAR} !=` | `${VAR} =` |

```sh
grep -n -H -e '\[.*! $.* \(-eq\|-ne\|!=\|=\)'
```

A `$` that is not at the end of a BRE is a literal character, so `! $` matches `!`, a space and a dollar sign.

**Rationale.** The script gives only the mapping above. The negated form is legal, so this is a rule about readability.

**False positives.** Everything between `[` and the operator is `.*`, so `! $` and the operator can come from
different commands on the same line, such as `[[ -n $a ]] && ! $func && [[ b = c ]]`.

**Pattern issues.**
- `-lt`, `-le`, `-gt` and `-ge` are not covered, so `[[ ! $x -lt 1 ]]` (which should be `$x -ge 1`) passes.
- The `$` must follow `! ` directly, so a quoted operand passes: `[[ ! "$x" -eq 1 ]]`.

## Variables, quoting and braces

### 6. Put `$` before every `{VAR}`

```sh
grep -n -H "[^$][{][[:alpha:]]" | grep -v -e "awk" -e perl
```

**Rationale.** "Test of not forgetting the dollar before the variable name." Lines that mention `awk` or `perl` are
skipped, "as these can be perl/awk scripts".

**False positives.** Brace expansion (`cp a.{txt,bak} /tmp`), braces inside strings (`echo "{name}"`), and the body
lines of a multi-line awk or perl program, which do not contain the words `awk` or `perl` themselves.

**Pattern issues.**
- This pattern is broad. Any `{` followed by a letter matches, and lines are dropped only when they contain `awk` or
  `perl`.
- `[^$]` needs a character before the `{`, so a `{VAR}` at the very start of a line is not found.
- The `awk` / `perl` filter hides a real `{VAR}` mistake on any line that also calls awk or perl. It also hides
  every line when the temporary file's path contains `awk` or `perl`, because the filter runs on grep's
  `file:line:text` output.

### 7. Put `$` before every variable inside `[[ ]]`

```sh
grep -n -H "[[][[][[:blank:]][^$]*$" \
  | grep -v -e -d -e -f -e -x -e -s -e -r -e -a -e -h -e -t -e \` \
  | grep -v -- -e
```

The first grep finds lines that contain `[[ ` and no `$` after it. The other two drop lines that contain a file
test (`-d -f -x -s -r -a -h -t -e`) or a backtick.

**Rationale.** "If we test for something that is not a filename, nor the return of a subcall, then surely we have a
variable." A `$( )` subcall already contains a `$`, so only backticks need excluding.

**False positives.**
- Tests with only literal operands, such as `[[ 1 -eq 1 ]]` or `[[ -n foo ]]`.
- Option tests, such as `[[ -o noclobber ]]`.
- File tests that are not in the exclusion list: `-w`, `-L`, `-p`, `-S`, `-b`, `-c`, `-g`, `-u`, `-k`, `-O`, `-G`,
  `-N`, `-nt` and `-ot`. For example, `[[ -w /tmp ]]` is reported.

**Pattern issues.**
- The exclusion is too broad and drops real violations. `-e` is a substring of `-eq`, so `[[ count -eq 3 ]]`, which is
  exactly the missing-`$` case this rule is for, is never reported, while `[[ count -ne 3 ]]` is. `-a` and `-t` are
  substrings of any option such as `--all` or `-type` on the same line.
- Any `$` later on the line hides the test: `[[ -n foo ]] && echo $bar` passes.

### 8. Never put whitespace inside `${...}`

```sh
grep -n -H -e '$[{][[:alnum:]_]*[[:space:]][[:space:]]*[^[:space:]}]*[}]'
```

The comment says this check was written to "find bugs as I2_094456", which looks like an internal bug-tracker
reference.

**Rationale.** "Space in the variable name is not possible." This finds `${MY VAR}` and `${VAR }`. Operators such as
`${VAR:- default}` are not reported, because the name stops at the `:`.

**False positives.** ksh93's non-forking command substitution `${ cmd;}` is valid ksh93, and it is reported when the
`}` follows the last word directly (`X=${ pwd;}`). With a space before the `}`, as in `${ pwd; }`, it is not reported.

### 9. Write `$OPC_SERVICE_NAME` and `$OPC_USER` without braces

```sh
grep -n -H -e '$[{]OPC_SERVICE_NAME[^[:alnum:]_]' -e '$[{]OPC_USER[^[:alnum:]_]'
```

There is deliberately no `}` in the pattern, so `${OPC_SERVICE_NAME#TOTO}` is reported as well. The
`[^[:alnum:]_]` still allows a new variable whose name starts with the same text, such as `${OPC_SERVICE_NAME_FOR_ME}`.

**Rationale.** The script does not say. This rule is specific to the project the script was written for. It is a guess,
not checked, that some tool substitutes these two names literally in the form `$NAME`.

**Note.** This is the opposite of the zsh linter's ZSH009 (`${name}` instead of `$name`). Running both on the same
files would report one of the two forms whichever way the code is written.

## Arithmetic

### 10. Compare numbers with numeric operators

Use `-lt`, `-le`, `-gt` and `-ge` instead of `<` and `>`, and `-eq` and `-ne` instead of `=` and `!=`.

```sh
grep -n -H -e "[><=][[:space:]][[:space:]]*[0-9][0-9]*[[:space:]][[:space:]]*]" \
           -e "[><=][[:space:]][[:space:]]*[0-9][0-9]*[[:space:]][[:space:]]*[|&].*]"
```

The patterns look for `<`, `>` or `=` followed by an integer literal and the closing `]`, or by `||` / `&&` and a later
`]`. "Checking = on the right hand side of the operator is enough to match !=, == and =."

**Rationale.** `<`, `>` and `=` compare strings. The script's comments show a session with this:

```sh
$ if [[ 010 < 1 ]];   then echo inferior; else echo greater; fi
inferior
$ if [[ 010 -lt 1 ]]; then echo inferior; else echo greater; fi
greater
```

The same session shows that with `A` set to `00` or `-0`, `[[ ${A} = 0 ]]` is false while `[[ ${A} -eq 0 ]]` is true.

**False positives.** A deliberate string comparison with a number, such as `[[ ${VERSION} = 2 ]]` when `VERSION` may
be `2.1`.

**Pattern issues.** Only an unquoted, non-negative integer on the right-hand side is found. These pass:
- `[[ 0 = $x ]]`, with the number on the left.
- `[[ $x = "0" ]]`, with the number in quotes.
- `[[ $x = -1 ]]`, with a negative number.
- A test whose closing `]` is on another line.

## typeset

### 11. Give `typeset -i` an explicit value

Write `typeset -i N=0`, not `typeset -i N=`.

```sh
grep -n -H -e 'typeset -i .*=$'
```

**Rationale.** "typeset -i implicitly sets the value to 0 if nothing is given, so make it explicit, so nobody adds a
test on emptiness of the variable." An empty assignment to an integer gives `0`, so `[[ -z $N ]]` can never be true.

**Pattern issues.**
- The check only finds an `=` at the very end of the line. `typeset -i N` with no `=` at all passes, although the
  comment suggests every integer should have an explicit value. Whether the bare form was meant to be allowed is
  unclear from the script.
- `integer N=`, the ksh built-in alias for `typeset -i`, passes, and so does `typeset -i N= ` with a trailing blank.

## Redirections

### 12. Do not use the here-string `<<<`

```sh
grep -n -H -e '[^<]<<<[^<]'
```

**Rationale.** "<<< operator is not ksh and we develop in ksh." This is true for ksh88 (the `/usr/bin/ksh` of older
AIX, HP-UX and Solaris) and for pdksh. ksh93 does support `<<<`, so the rule really means "stay compatible with ksh88".
Use `print -r -- "$x" | cmd` or a here-document instead.

**Pattern issues.** `[^<]` needs a character on each side, so `<<<` at the very start or end of a line is not found.
`<<<` inside a quoted string is reported.

### 13. Duplicate file descriptors with `>&`, not `>>&`

Write `2>&1`, not `2>>&1`.

```sh
grep -n -H -e '>>[[:space:]]*&'
```

**Rationale.** "As you're redirecting file descriptors only one '>' is needed." Appending makes no sense for a
descriptor duplication. The script does not say how its target ksh treats `>>&`.

## Commands and pipelines

### 14. Use `wc -l`, `wc -w` or `wc -c` instead of `wc | awk`

```sh
grep -n -H -e 'wc[[:space:]][[:space:]]*|[[:space:]][[:space:]]*awk'
```

**Rationale.** "Use wc -l, wc -w or wc -c instead of wc | awk." Ask `wc` for the one count you want instead of picking
a column out of its output.

**Pattern issues.** The pattern is narrower than the rule. It needs `wc`, blanks, `|`, blanks and `awk` with nothing
else in between, so it only finds a bare `wc | awk`. These pass:
- `wc -l file | awk '{print $1}'`
- `wc file | awk ...`
- `wc|awk`, with no blanks

If the aim is to forbid every `wc ... | awk`, the pattern needs `wc[[:space:]].*|[[:space:]]*awk`.

**Tip.** People often add the awk because `wc -l file` prints the file name and some Unixes pad the count with blanks.
`wc -l < file` drops the name, and `typeset -i N=$(wc -l < file)` drops the blanks.

## Whitespace

### 15. No trailing blanks

```sh
grep -n -H "[[:blank:]]$"
```

**Rationale.** "Trailing blanks."

**False positives.** Here-document lines where trailing blanks are part of the data.

**Pattern issues.** This check runs on the file after comment stripping, which removes the blanks in front of a
trailing comment and everything after them. Trailing blanks on a line that ends with a comment are never reported.

## Notes on the script itself

These are not style rules. They matter if the script is reused or ported to a parser-based linter.

- It checks one file, given as `$1`, and `${ORIG_FILE}` is not quoted, so paths with blanks break it.
- `RESULT` is never initialised, so a `RESULT` variable already in the environment is printed as a finding.
- The temporary file comes from `cfmu_mktemp`, which is a site-specific helper, and nothing removes it with a `trap`
  if the script is interrupted.
- It exits 1 when anything matches, and the script's comment asks whether it should. Given the expected false
  positives, a non-zero exit is awkward in CI unless there is a way to suppress a finding.
- The output step `sed "s#${TMP}#${ORIG_FILE}#"` breaks if either path contains `#`.

---

# Second checker: undefined and unused variables

A second awk-based checker reads one ksh file and reports three things: variables that are used but never assigned,
variables that are assigned but never used, and assignments to ksh or environment-owned read-only variables. Its
header states its own limits. It parses lines with awk regular expressions and does no real ksh parsing, and it does
not check order, so a variable assigned after its first use is accepted. Comment stripping uses the same `sed` approach as
the first checker.

The rules below are the ones it encodes. They are grouped by theme like the first list. Rules 16 to 19 are the
assignment and use rules, and rules 20 to 22 are read-only and exemption rules.

## Assignment and use

### 16. Assign a variable before using it

```awk
END { for (val in var_used) if (!generic_var_assigned[val] && !var_assigned[val] && !ENVIRON[val] && !ksh_var_ro[val]) ... }
```

A variable counts as used when it appears as `$VAR`, `${VAR}`, or `${VAR#...}`, `${VAR%...}`, `${VAR:...}`, `${VAR/...}`
with a substitution. It counts as assigned when any assignment form in rule 18 appears anywhere in the file, or it is
in the environment at check time, or it is in the generic exemption list in rule 20.

**Rationale.** The script's header says the check "does not know whether the definition happens before the first usage",
so the rule is only that the variable is defined somewhere. The message for this check prints "seem to be used not defined".

**False positives.** The script's own message lists two: the variable is set in a file that is sourced, or in a caller that
exported it. Any variable that comes from the CFMU environment and is not in the exemption list is reported too.

### 17. Use every variable you assign

```awk
for (val in var_assigned) if (!var_used[val]) ...
```

**Rationale.** A variable that is assigned and never read is likely dead code. The script's comment notes it may be
exported for another script, so the report says "There can be false positive, so this shall be double checked".

**Pattern issues.** `export` names are not treated differently from other names. The script's own comment asks for
a separate check for exported variables and says `export A B C` can declare several names, which is not handled.

### 18. Use an assignment form the script recognises

The script records a variable as assigned for each of these forms:

| Form | Example | Notes |
|---|---|---|
| Start of line | `A=1` (leading blanks allowed) | |
| Export at start of line | `export A=1` | |
| Inline after a space, `;` or `(` | `A=1 B=2`, `{ A=toot; }` | The first occurrence on each line only. |
| For loop | `for X in ...` | |
| Read | `read X Y` | Only when `read` has no option argument. |
| Eval of a dbt query | `eval $(myquery.info.query X Y)` | `-prefix` is taken into account. |
| Eval of get_parameter_value | `eval $(get_parameter_value X Y)` | |
| Select | `select X in ...` | Also sets `REPLY`. |
| getopts | `getopts "a:" OPT` | Also sets `OPTARG` and `OPTIND`. |
| Array set | `set -A ARR` | Only `set -A` and `set -a` are matched in the code, not `typeset -A`. |
| Array element | `A[i]=1` | |

**Pattern issues.**
- **Only one inline assignment per match.** The inline pattern uses `match`, which finds one occurrence per line, so
  `A=1; B=2; C=3` only records one of `B` and `C`. The comment says it handles `A=AA B=XX`, which works because the
  first assignment is found by the start-of-line pattern.
- **`read` with an option argument is missed.** `read -p "Name: " NAME` does not match, because the `read` pattern expects a
  lowercase option followed by a name. `NAME` is then not recorded, and any use of it is reported as not defined.
- **`typeset -A` and `typeset -a` are not matched.** Only `set -A` and `set -a` are, although the comment lists `typeset`.
- **`$(...)` and `${...}` in the assignment are matched by the start-of-line pattern.** For example `X=$(cmd)` records `X`,
  which is correct, but a `=` inside a `[[ ... ]]` test with no spaces, such as `[[ a=b ]]`, is recorded as `a`.

### 19. Read a variable with `${VAR}` when it is followed by a subscript-like operator

The script counts as a use these forms: `$VAR` followed by a non-name character or the end of the line, `${VAR}`, and
`${VAR` followed by `#`, `%`, `:` or `/` and a closing `}`.

**Pattern issues.** These uses are missed, so the variable is reported as assigned and not used (rule 17) or never seen as used.
- `${#VAR}` (length). The `#` comes right after `{`, so the pattern does not match.
- `${VAR-default}`, `${VAR+x}`, `${VAR=x}`, `${VAR?msg}`, `${VAR,}`, `${VAR^^}`. Only `#`, `%`, `:` and `/` are listed.
- `${VAR}` with a `}` that is not on the same line as `${`.

I checked these on sample lines with GNU awk: `${#LEN_VAR}` and `${OPT-DEFAULT_V}` are not counted as uses, while `${A} == 3` is.

## Read-only and environment variables

### 20. Do not assign a variable that the environment already defines

Each of these is listed in the script and reported when it is assigned in a checked file:

- **ksh read-only**: `EGID`, `ENV`, `EUID`, `GID`, `HISTCMD`, `LINENO`, `PPID`, `RANDOM`, `TTYIDLE`, `UID`, `USERNAME`, and
  the `SUDO_COMMAND`, `SUDO_USER`, `SUDO_UID` and `SUDO_GID` variables set when a user logs on with sudo. The report says
  "default ksh var assigned, it is likely a bug". The rationale comment: assigning one either "fails loudly (read-only
  var)" in zsh or "fails silently and does nothing", as in `USERNAME=aa`.
- **Defined by `define_configuration`**: `PHYSICAL_SERVERS`, `SYSTEM_LOCATION`, `LOCAL_STATIONS`, `SYSTEM_TEMPLATE`,
  `OTHER_INSTANCE`, `CONFIGURATION_SYSTEM`, `CONFIGURATION_TYPE`, `APPLICATION`, `DB_FUNCTION`, `ENTERPRISE_ID`,
  `ENV_UPDATE_USER`, `ENV_UPDATE_USER_PASSWD`, `EXER_TITLE`, `REFERENCE_INSTANCE`, `PHYSICAL_HOSTS_ALL`, `PACKAGE_NAME`,
  `HOSTS_ALL` and `SYSTEM_PAIR`. These may be set only "in very specific circumstances like setting a profile in
  regression tests". The check is skipped when the checked file name matches the defining name (the script uses
  `FILE !~ ksh_var_ro[val]`), so a file named after `define_configuration` may assign them.

**Pattern issues.** The file-name test is a regular expression match on the defining name. `define_configuration` is
a substring match, so any file whose name contains it is exempt. `ENV` is also marked read-only with the value `ksh`, so
a file named `...ksh...` is not exempt.

### 21. Do not expect the environment or the CFMU setup to define these; the checker exempts them

The script exempts these from rule 16, so using them in a script does not need an assignment:

- **CFMU environment**: `APPLICATION_INSTANCE_KEY`, `CFMU_TEMP_DIR`, `CM_ROOT`, `CM_SYSTEM`, `PATCHES_DIR`, `PATH`, `PWD`,
  `TMP_ROOT`, `WORK_DIR`, `WORK_ROOT`, `DATA_FILES`, `SHARED_AREA`, `SVLOGS`.
- **CMA5 environment**: `CMA_WORKSPACE_ROOT`, `CMA_WORKSPACE_DATA_DIRECTORY`, `CMA_WORKSPACE`, `CMA_WORKSPACE_NM_REPOSITORY_DIRECTORY`.
- **Set by `define_configuration`**: the list in rule 20 (so using them is allowed, assigning them is not).
- **Coverage and workspace builds**: `GCOV_PREFIX` and `CLEARCASE_ROOT`.
- **Set by the shell or tools**: `SCRIPT` (used by `Log`), `DISPLAY`, `ENABLE_UPDATE_STATISTICS`, `TZ`, `PS1`, `PS2`,
  `IFS`, `SECONDS`, `funcfiletrace` (when `zmodload zsh/parameter` is present), `OPTARG` and `OPTIND`, `REPLY` and `PS3`.
- **awk**: `NF`. It looks like a shell variable in awk code but is not one.

**Pattern issues.**
- `CFMU_TEMP_DIR` is both in the generic list and marked used, so it is never reported.
- `PHYSICAL_SERVERS` and `PHYSICAL_HOSTS_ALL` are listed twice in the code. This is harmless.
- `PATH` and `PWD` are exempt from rule 16 but are not read-only. Assigning `PWD` by hand is not reported.

### 22. Keep the read-only list in alphabetical order

**Rationale.** The comment says "Keep these variables in alphabetical order". The `ksh_var_ro` list is grouped in several
blocks (ksh, define_configuration, SUDO), so only the first block is kept sorted. This is a convention, not a check.

## Known limitations and stale comments in the checker

- **The header comment is stale.** It says "only the first [variable] is taken into account" in an expression. The
  `${VAR}` and `$VAR` patterns loop with `while` and do count several per line. The inline assignment pattern is the one
  that counts only the first per line (rule 18).
- **`{ A=toot; }` is recorded.** The header says the check "does not yet verify in blocks like `{ A=toot; }`". The inline
  pattern does match a variable after a space or `;`, so that case works. Only the second and later assignments on one line are missed.
- **No argument check.** The script reads `$1` without checking that an argument was given. With no argument, `sed`
  and `awk` get an empty file name and fail.
- **Comment stripping.** The first `sed` removes `#` only when a space or tab comes before it, so `\t# comment` is removed only
  by the second `sed`, and a `#` inside a string after a space is cut. This is the same limitation as the first checker.
- **`\<` is a gawk extension.** The `read` pattern uses `\<`, which is a word boundary in gawk but not in POSIX awk.
  The script will not run the same way under `mawk` or BSD awk.
- **Awk's `match` does not reset `a`.** `a` is reused across calls. This is harmless here because each use reads only `a[0]`
  right after the call, but it would break if the code ever read a capture group.

---

# Third checker: return codes

This checker reads one ksh file, tracks curly-brace depth to find function bodies, and warns when a return code is
tested in a way that hides the real result. Its header says the checks are "not as robust as the other ones", so the
results need checking by hand.

## Return code checks

### 23. Do not test `$?` right after a `tee`

Test the return code of the command on the left of `|`, not of `tee`.

```awk
if (previous_line ~ "[|][[:space:]]*tee[[:space:]]") ...
```

**Rationale.** The return code after `cmd | tee file` is `tee`'s, which is almost always 0. The script's message says it is
"unlikely that it is what we want".

**Pattern issues.** Only the immediately previous non-blank line is checked. `cmd | tee f`, then `echo done`, then `$?`
is not reported.

### 24. Do not test `$?` after `typeset VAR=$(...)`

Assign first, then declare the type:

```ksh
my_number=$(returns_a_number)
typeset -i my_number
echo $?          # now the return code of returns_a_number
```

**Rationale.** `typeset -i my_number=$(returns_a_number)` returns the status of `typeset`, which is 0 even when the command
fails. The script shows a session where `returns_a_number` is not found (127) but the `typeset` form gives 0.

**Pattern issues.** The check uses the same one-line lookback as rule 23, so an intervening blank line or comment is
fine but any other line is not. The pattern `typeset.*=[$][(]` also matches `typeset -i X=$(...)` inside a
`[[ ]]` or after `;`, and does not match the backtick form `` typeset X=`cmd` ``.

### 25. Do not test `$?` after calling a function that uses `exit`

Use `return` in functions. When a function uses `exit`, the whole script exits, and the `$?` check never runs.

```awk
$0 ~ /exit / && func_name != "" { exit_in_function_line[func_name]=NR ":" $0; }
```

The script tracks the current function from a `function NAME` line and the curly-brace depth. When a `$?` line follows a
call to such a function, it reports both the `exit` line and the call.

**Pattern issues.**
- **Typo in the brace-depth check.** `func_nested_level` is set when a function starts, but the end test uses
  `function_nested_level`, which is never set, so it is 0. A function is only closed when the depth returns to 0. In a
  function that starts inside a block, the name is never cleared, so later `exit` lines in the main script are recorded
  as function exits. This is a real bug, and I did not run it.
- **Only `function NAME` is recognised.** `NAME()` and `NAME ()` definitions are not tracked, so an `exit` inside them is
  not reported. (Rule 33 reports the `NAME ()` form.)
- **`exit` must be followed by a space.** The pattern `/exit /` misses `exit` at the end of the line and `exit;`.
- **Braces in strings and awk code are counted.** A `{` inside `"..."` or an awk program changes the depth.
- **Only the last `exit` line for each function is stored.**
- **Name matching is by word boundary in the regex.** It is checked against the previous line only, so calls in
  `if NAME; then` on the line before `$?` are matched but calls two lines earlier are not.

# Extra style checks

The fourth checker's own header calls these checks "not as robust as the other ones".

## Variables and special parameters

### 26. Do not put braces around `$OPC_SERVICE_NAME`, `$OPC_USER`, `$MGMTSV`, `$OPC_NODES`, `$OPC_MSG_NODES`, `$OPC_MSG` or `$OPC_ALWAYS`

**Rationale.** The comment says these names are used "by the OML/OBM software as literals", so they must be declared as
`$OPC_XXX` and not as `${OPC_XXX}`, or that software will not pick them up. The warning text says this is about the two
names OPC_SERVICE_NAME and OPC_USER, but the code also protects the five others.

**How the check works.** It replaces each protected `$NAME` with `DOLLAR_NAME` before searching for `$[[:alpha:]]`, so
protected uses are not reported. It then restores only `OPC_SERVICE_NAME` and `OPC_USER`. The restore step runs the
other five substitutions again, which does nothing because the names were already replaced.

**Pattern issues.** The five extra names are hidden from the braces check in both directions, so `${MGMTSV}` is never
reported. Either the other names should be restored in the second `sed`, or their substitutions should be removed.

### 27. Do not use `${0}`, `${1}`, ..., `${?}`, `${@}`, `${*}`, `${#}`, `${$}`, `${!}` with braces unless the braces are needed

Write `$1`, not `${1}`. The braces are allowed only when a word is built from the parameter, e.g. `${1}_foo`.

```sh
grep -n -H -e "[$]{[0-9?@#*-$!]}[^[:alnum:]_]" -e "[$]{[0-9?@#*-$!]}$"
```

**Rationale.** The comment says "no curly bracket for $0 $1 .. $9, $? $@ $* except maybe when it is used to generate a
word".

**Pattern issues.** The character class `[0-9?@#*-$!]` contains `*-$`, a range from `*` to `$`. `$` (0x24) comes before
`*` (0x2A), so GNU grep stops with `Invalid range end` (exit 2). I ran the pattern on sample lines and grep failed
without matching anything. Because the result is captured with `$(...)`, the check is silently skipped, and the rule
never reports. The fix is to put `-` first or last in the class, e.g. `[0-9?@#*$!-]`.

### 28. Do not use `$*`; use `$@`

**Rationale.** "You should be using `\$@` instead of `\$*`", with a link to the Austin Group bug on the difference.
Unquoted `$*` and `$@` split differently, and a quoted `"$*"` joins the arguments into one word.

**False positives.** The rule says it can be broken "if you know why and document it".

### 29. Do not use `${NF}` as a shell variable, and do not use `$NF` in a script that has no awk

**Rationale.** `$NF` is an awk field, not a shell variable. The script writes it as `DOLLAR_NF` for the other checks.

**Pattern issues.** `${NF}` is matched in single quotes, so it works. `$NF>` is matched only when the file has no
`awk` word, so a `$NF` in a script that calls `awk` is never reported. That is the intent, but a script that names awk
only in a comment is also exempt.

### 30. Do not write `${VAR}=A` as an assignment

**Rationale.** `${VAR}=A` is not a valid shell line. The pattern excludes lines with `&&`, `||` or `]]`.

## Tests and conditionals

### 31. Do not test a non-empty or empty string without a `$` on the variable

```sh
grep -n -H "[[][[:space:]].*-[nz][[:space:]][[:space:]]*[[:alpha:]].*[]]"
```

**Rationale.** "Missing `$` in the variable name in test of empty or not empty strings". `[[ -n foo ]]` is almost always a
mistake for `[[ -n $foo ]]`.

**False positives.** A deliberate literal test, such as `[[ -z abc ]]`, is reported.

### 32. Use one `[[ ]]` with `&&` or `||` inside, not two tests joined by `&&` or `||`

Write `[[ -n $a && -n $b ]]` instead of `[[ -n $a ]] && [[ -n $b ]]`.

```sh
grep -n -H "[]][]][[:blank:]][[:blank:]]*&&[[:blank:]][[:blank:]]*[[][["
```

**Rationale.** "Usage of `[[ ]] && [[ ]]` is not needed, use `[[ && ]]` and if grouping is needed then use the `()`."

**Pattern issues.** Only exactly-adjacent `]] && [[` and `]] || [[` are found. `]] && ! [[` and `]]  &&  (` pass.

### 33. Declare a function with the `function` keyword

Write `function my_function`, not `my_function ()`.

```sh
grep -n -H "^[[:space:]]*[[:alpha:]][[:alnum:]_]*[[:space:]]*[(][)]"
```

**Rationale.** Readability. The message gives the two forms side by side.

**Pattern issues.** The name must start with a letter and contain only letters, digits and `_`. A name with `-` or `.`
(ksh allows `my-func ()`) is not found. A call such as `echo ()` on its own line is reported too, which is rare but wrong.

### 34. Do not test a variable that may be unset with `[[ ]]` without `$` after `&&` or `||`

```sh
grep -n -H "[[][[][^]]*&&[[:blank:]][[:blank:]]*[^$][[:alpha:]].*[]][]]"  | grep -v "&& [[:blank:]]*-" | grep -e if -e while
```

**Rationale.** In `if [[ $a ]] && [[ b ]]`, the second `b` should probably be a variable. The check skips the `&&`
followed by an option (`&& -n`, which is an operator on a file test) and needs `if` or `while` on the line.

**Pattern issues.**
- `[^$][[:alpha:]]` needs two characters, so a one-letter name (`&& x`) is not found.
- `grep -e if -e while` is a substring match, so any line that contains "if" anywhere is kept, e.g. `modifier`.
- A `-n` or `-z` test after `&&` is checked by a separate pattern, which has the same `if`/`while` restriction.

### 35. Use `!` instead of `.` in a path to separate subsystem and version

```sh
grep -n -H "/.*[.][$][(]cm_where"
```

**Rationale.** PATHs with a dot do not work on OPT/OPS, so `$(cm_where ...)` should use `!` even in non-OPS scripts, so
copy-paste does not produce a wrong path.

### 36. Do not write `if ${VAR};` without quotes (under test)

```sh
grep -n -H -e "[^[:alnum:]_]\(elif\|if\|while\)[[:space:]][[:space:]]*[$][[:alnum:]_{]" \
           -e "^\(elif\|if\|while\)[[:space:]][[:space:]]*[$][[:alnum:]_{]"
```

Write `if "${VAR}"; then`, or `if command "${VAR}"; then`. The script's comment says this pattern is "UNDER TESTING,
NOT APPROVED YET". The reason is `I2_093351`: an uninitialised `VAR` used as a command makes the test true.

**Pattern issues.** The `${CMD}` exception is hard-coded. `if $cmd arg; then` is also reported.

## Commands and redirections

### 37. Do not use `tee` followed by `2>&1`

Redirect stderr before `tee`, so the file holds it.

```sh
grep -n -H "tee.*2>&1"
```

**Rationale.** "Usually one wants to do it afterwards, so the file contains stderr." Reference: `SC_067980`.

**Pattern issues.** Any `2>&1` after a `tee` on the same line is flagged, including `tee` inside a string or a `2>&1` that
is part of another command.

### 38. Do not write `2>&1 >file` (stderr to stdout before stdout to file)

Write `>file 2>&1`.

```sh
grep -n -H "2[[:space:]]*>[[:space:]]*&1 [[:space:]]*1*>"
```

**Pattern issues.** The pattern needs exactly one space after `&1`. `2>&1>file` passes.

### 39. Do not redirect stderr of `Log` to stdout (`Log ... >&2`)

`Log` already writes to stderr.

```sh
grep -n -H "Log\>[^|]*>[[:space:]]*&2"
```

**Pattern issues.** `[^|]*` stops at a `|`, so `Log x | tee f >&2` passes. The `\>` requires the word `Log` to end.

### 40. Use `Log -i`, `-w`, `-s` or `-f` (not `-t` alone) on a message with a level

```sh
grep -n -H "Log .*\(INFO\|WARNING\|SEVERE\|ERROR\|FATAL\)" | grep -v "Log [[:space:]]*-[iwsf]" | grep -v "Log [[:space:]]*-t [[:space:]]*[[:digit:]]*[[:space:]]*-[iwsf]"
```

**Rationale.** The level is passed with a flag. The script's comment says "test of not using -i,-w,-s,-f options of Log".

**Pattern issues.** A level word anywhere on the line, including in a string, is reported. `Log -i` in a `case` or a
message such as `Log "ERROR count"` is treated the same.

### 41. Do not ask a yes/no question with `y/n`; use the `confirm` script

```sh
grep -n -H -i y/n
```

**Rationale.** "Test of not using script named `confirm` to ask question answered by y/n."

**Pattern issues.** `y/n` matches any text with those characters, such as a path `/usr/y/n` or `yes/no`-free strings
like `copy y/n`. `-i` also matches `Y/N`.

### 42. Use `cd "${OLDPWD}"` (not `cd -`)

**Rationale.** Since RHEL7 `cd -` prints the directory it goes to, which breaks scripts that use its output.

```sh
grep -n -H -e "\Wcd[[:space:]][[:space:]]*-"
```

**Pattern issues.** `cd -P -`, or `cd -` at the start of a line, is missed.

### 43. Quote the first argument of `tr`

Write `tr "a-z" "A-Z"`, not `tr a-z A-Z`.

```sh
grep -n -H -e "\Wtr[[:space:]][[:space:]]*\(-d[[:space:]]\|-s[[:space:]]\)*[[:space:]]*[^-\"'[:space:]]" | grep -v -e "-tr"
```

**Rationale.** The arguments can be expanded by the shell first. The script says `tr` can have one or two arguments, so
the check looks only at the first one, and skips `-d` and `-s`, which take one argument.

**Pattern issues.**
- `tr -c "..." ...` is not checked, because the `-` at the start of the argument is excluded.
- `tr -d x` with an unquoted set is reported, but `tr -cd x` is not, because `-c` is skipped.
- A quote preceded by a backslash is passed although the shell does expand it, as the script comment says.
- The `\W` before `tr` needs a non-word character, so `tr` at the very start of a line is not found.

### 44. Quote the `cfmu_ftps_list` mask and the `cfmu_ftps_get` mask

```sh
grep -n -H -e "cfmu_ftps_list[[:space:]][[:space:]]*[^[:space:]][^[:space:]]*[[:space:]][[:space:]]*[^\"']"
grep -n -H -e "cfmu_ftps_get ... [^\"']"
```

**Rationale.** A mask that is not quoted is resolved locally by the shell. Write `cfmu_ftps_list SERVICE "MASK"` or
`cfmu_ftps_get LOCAL_DIR SERVICE DECOMPRESS "MASK"`. The lines with `-sequence`, `-period`, `-free_text` or
`-source_key` are allowed to omit the mask.

**Pattern issues.** The check assumes the arguments are exactly as shown, so a call with an option before the service
name, or with a variable as the service, is matched wrongly. The script comment says it may be a false positive for
another argument order.

### 45. Do not use `bmw VAR | awk '{print $2}'`; use `bmw -V VAR`

```sh
grep -n -H -e "bmw[[:space:]].*[|][[:space:]]*awk[[:space:]].*print \$[2N]"
```

**Rationale.** `bmw -V` returns the value without parsing. The awk form depends on the output layout.

### 46. Do not use `cat file | grep|awk|sed|cut|sort`; pass the file to the command (under test)

```sh
grep -n -H -E '\<cat\>[^\|]*\|[^\|]*\<(grep|awk|sed|cut|sort)\>'
```

**Rationale.** The script comment says "Do not cat a file into a function that can open a file directly". The rule is
"UNDER TESTING, NOT APPROVED YET".

**Pattern issues.** `[^\|]*` is a bracket with `\` and `|`, so any `|` is excluded. `cat` in a string followed by a
pipe is reported.

### 47. Do not use `Log` with a trailing blank or quote

```sh
grep -n -H "Log[[:space:]].*[[:space:]][\"']$"
```

**Rationale.** "Test of having trailing blank(s) in the message output by Log." The trailing blank is inside the quotes,
so it is printed.

## Constructs and literals

### 48. Use `alias_get -q`, not `alias_get ... Value`

```sh
grep -n -H -e "alias_get.*Value"
```

**Rationale.** The comment says "use -q option of alias_get". The check only flags the word `Value` after `alias_get`
on the same line.

### 49. Do not use backticks

Use `$( )`. Backticks are hard to read and cannot be nested.

```sh
grep -n -H "\`"
```

### 50. Do not use the `.LATEST` alias; use `.LATEST_GOOD`

```sh
grep -n -H "[.]LATEST[^_]"
```

**Pattern issues.** `.LATEST` at the end of a line is not found, because `[^_]` needs a character.

### 51. Do not use tab characters

**Rationale.** A tab cannot be told from spaces in most editors. Exceptions are a subsequent program that needs a tab,
or input that contains one.

```sh
grep -n -H -e "$(echo ' ' | tr ' ' '\t')"
```

The pattern is built at run time. I checked that the expansion is a single tab, so the grep works.

### 52. Do not use `CFMU_OS`

**Rationale.** It "is likely to be obsolete" since the HP-UX to Linux migration.

# Known problems in the third and fourth checkers

- **Brace-depth typo** in the function-exit check (rule 25). `func_nested_level` and `function_nested_level` are different names.
- **Invalid grep range** in the special-parameter check (rule 27). `[0-9?@#*-$!]` fails with `Invalid range end`, and the failure
  is hidden by `$(...)`, so the check does nothing.
- **Redundant substitutions** in the OPC check (rule 26). The second `sed` re-applies five substitutions that do nothing.
- **Other variable names are not restored.** Rule 26 hides five names from the braces check without reporting them.
- **Previous-line lookback.** The `tee` and `typeset` checks (rules 23 and 24) use only the previous non-blank line.
- **Single-line matching.** The `[[ ]] && [[ ]]` checks (rules 32 and 34) only see one line, so a test split across lines is missed.
- **Comment-stripping** works as in the first checker: a `#` after a space starts a comment, even in a quoted string.
