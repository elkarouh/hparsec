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
