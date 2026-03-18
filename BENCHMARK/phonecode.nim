# phonecode.hpy -- HPython version of the Phone Code benchmark
# ============================================================
#
# Solves the "Phone Code" challenge from:
#   Prechelt, Lutz. "An Empirical Comparison of Seven Programming Languages."
#   IEEE Computer, Vol. 33, No. 10, October 2000, pp. 23-29.
#
# Transpile to Python:  python3 TO_PYTHON/py2py.py BENCHMARK/phonecode.hpy
# Transpile to Nim:     python3 TO_NIM/py2nim.py BENCHMARK/phonecode.hpy

import options, strformat, strutils, sugar, tables
import os

# ---------------------------------------------------------------------------
# Character-to-digit mapping
# ---------------------------------------------------------------------------
type Digit_T = enum D0, D1, D2, D3, D4, D5, D6, D7, D8, D9
type Result_T = seq[seq[string]]

proc build_char_to_digit(): Table[char, Digit_T] =
    var mapping: Table[char, Digit_T] = initTable[char, Digit_T]()

    proc m(chars: string, digit: Digit_T) =
        for c in chars:
            mapping[c.toLowerAscii()] = digit
            mapping[c.toUpperAscii()] = digit

    m("e", Digit_T(0))
    m("jnq", Digit_T(1))
    m("rwx", Digit_T(2))
    m("dsy", Digit_T(3))
    m("ft", Digit_T(4))
    m("am", Digit_T(5))
    m("civ", Digit_T(6))
    m("bku", Digit_T(7))
    m("lop", Digit_T(8))
    m("ghz", Digit_T(9))

    for d in "0123456789":
        mapping[d] = Digit_T(ord(d) - ord('0'))

    return mapping

var CHAR_TO_DIGIT: Table[char, Digit_T] = build_char_to_digit()

# ---------------------------------------------------------------------------
# Trie
# ---------------------------------------------------------------------------

type TrieNode = ref object of RootObj
    children: array[Digit_T, TrieNode]
    words: seq[string]

method add_word(self: TrieNode, word: string, digits: seq[Digit_T]): void {.base.}
method find_exact_word(self: TrieNode, digits: seq[Digit_T]): Option[string] {.base.}
method words_at(self: TrieNode, digits: seq[Digit_T]): seq[string] {.base.}
method load_dictionary(self: TrieNode, filename: string, verbose: bool): void {.base.}
method find_encodings(self: TrieNode, digits: seq[Digit_T], pos: int, current: seq[string], results: var seq[seq[string]]): void {.base.}
proc initTrieNode(self: TrieNode, filename: string = "", verbose: bool = false) =
    if filename.len > 0:
        self.load_dictionary(filename, true)

proc newTrieNode*(filename: string = "", verbose: bool = false): TrieNode =
    new(result)
    initTrieNode(result, filename, verbose)
method add_word(self: TrieNode, word: string, digits: seq[Digit_T]): void {.base.} =
    var node: TrieNode = self
    for digit in digits:
        if node.children[digit] == nil:
            node.children[digit] = newTrieNode()
        node = node.children[digit]
    node.words.add(word)

method find_exact_word(self: TrieNode, digits: seq[Digit_T]): Option[string] {.base.} =
    var node: TrieNode = self
    for digit in digits:
        if node.children[digit] == nil:
            return none(string)
        node = node.children[digit]
    if len(node.words) > 0:
        return some(node.words[0])
    return none(string)

method words_at(self: TrieNode, digits: seq[Digit_T]): seq[string] {.base.} =
    var node: TrieNode = self
    for digit in digits:
        if node.children[digit] == nil:
            return @[]
        node = node.children[digit]
    return node.words

method load_dictionary(self: TrieNode, filename: string, verbose: bool): void {.base.} =
    var word_count: int = 0

    proc word_to_digits(word: string): seq[Digit_T] =
        var result: seq[Digit_T] = @[]
        for c in word.toLowerAscii():
            if c notin CHAR_TO_DIGIT:
                return @[]
            result.add(CHAR_TO_DIGIT[c])
        return result

    block:
        let f = open(filename, fmRead)
        defer: f.close()
        for line in f.lines:
            let word: string = line.strip()
            if word.len == 0:
                continue
            let digits: seq[Digit_T] = word_to_digits(word)
            if len(digits) > 0 and len(digits) == len(word):
                self.add_word(word, digits)
                word_count += 1

    if verbose:
        echo(fmt"Loaded {word_count} words from {filename}")

method find_encodings(self: TrieNode, digits: seq[Digit_T], pos: int, current: seq[string], results: var seq[seq[string]]): void {.base.} =
    if pos == len(digits):
        results.add(current)
        return
        # use the bare digit at this position
    self.find_encodings(digits, pos + 1, current & @[$digits[pos]], results)

    var node: TrieNode = self
    for i in pos ..< len(digits):
        let digit: Digit_T = digits[i]
        if node.children[digit] == nil:
            break
        node = node.children[digit]
        for word in node.words:
            self.find_encodings(digits, i + 1, current & @[word], results)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

proc clean_number(num: string): seq[Digit_T] =
    return collect(for c in num: (if c in CHAR_TO_DIGIT: CHAR_TO_DIGIT[c]))

proc format_solution(original_num: string, solution: seq[string]): string =
    return fmt"{original_num}: {solution.join($' ')}"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

proc main() =
    if (paramCount() + 1) < 3:
        echo("Usage: phonecode <dictionary_file> <phone_numbers_file>")
        echo("Example: phonecode words.txt phones.txt")
        quit(1)

    let dict_file: string = paramStr(1)
    let phone_file: string = paramStr(2)

    if not fileExists(dict_file):
        echo(fmt"Error: Dictionary file not found: {dict_file}")
        quit(1)
    if not fileExists(phone_file):
        echo(fmt"Error: Phone numbers file not found: {phone_file}")
        quit(1)

    var trie: TrieNode = newTrieNode(dict_file, true)

    # Quick sanity-check
    let test_digits: seq[Digit_T] = @[Digit_T(3), Digit_T(5)]
    let exact_match: Option[string] = trie.find_exact_word(test_digits)
    if exact_match.isSome:
        echo(fmt"Exact match for digits 3,5: {exact_match}")
    else:
        echo("No exact match for digits 3,5")

    let words_at_35: seq[string] = trie.words_at(test_digits)
    echo(fmt"Words at [3,5]: {words_at_35}")

    # Process phone numbers
    block:
        let f = open(phone_file, fmRead)
        defer: f.close()
        var all_lines: seq[string] = f.readAll().splitLines()

        for line in all_lines:
            let original: string = line.strip()
            if original.len == 0:
                continue
            let digits: seq[Digit_T] = clean_number(original)
            if digits.len == 0:
                continue
            var results: seq[seq[string]] = @[]
            trie.find_encodings(digits, 0, @[], results)
            for sol in results:
                echo(format_solution(original, sol))

when isMainModule:
    main()
