# phonecode.ady -- Adascript version of the Phone Code benchmark
# ============================================================
#
# Solves the "Phone Code" challenge from:
#   Prechelt, Lutz. "An Empirical Comparison of Seven Programming Languages."
#   IEEE Computer, Vol. 33, No. 10, October 2000, pp. 23-29.
#
# Transpile to Python:  python3 TO_PYTHON/py2py.py BENCHMARK/phonecode.ady
# Transpile to Nim:     python3 TO_NIM/py2nim.py BENCHMARK/phonecode.ady

from enum import Enum
import sys
import os

# ---------------------------------------------------------------------------
# Character-to-digit mapping
# ---------------------------------------------------------------------------
class Digit_T(Enum):
    D0 = 0
    D1 = 1
    D2 = 2
    D3 = 3
    D4 = 4
    D5 = 5
    D6 = 6
    D7 = 7
    D8 = 8
    D9 = 9
type Result_T = list[list[str]]

def _build_char_to_digit() -> dict[str, Digit_T]:
    mapping: dict[str, Digit_T] = {}

    def m(chars: str, digit: Digit_T):
        for c in chars:
            mapping[c.lower()] = digit
            mapping[c.upper()] = digit

    m("e", 0)
    m("jnq", 1)
    m("rwx", 2)
    m("dsy", 3)
    m("ft", 4)
    m("am", 5)
    m("civ", 6)
    m("bku", 7)
    m("lop", 8)
    m("ghz", 9)

    for d in "0123456789":
        mapping[d] = Digit_T(ord(d) - ord('0'))

    return mapping

CHAR_TO_DIGIT: dict[str, Digit_T] = _build_char_to_digit()

# ---------------------------------------------------------------------------
# Trie
# ---------------------------------------------------------------------------

class TrieNode:
    children: dict[Digit_T, TrieNode]
    words: list[str]

    def __init__(self):
        self.words = []

    def add_word(self, word: str, digits: list[Digit_T]) -> None:
        node: TrieNode = self
        for digit in digits:
            if node.children[digit] is None:
                node.children[digit] = TrieNode()
            node = node.children[digit]
        return node.words.append(word)

    def find_exact_word(self, digits: list[Digit_T]) -> str | None:
        node: TrieNode = self
        for digit in digits:
            if node.children[digit] is None:
                return None
            node = node.children[digit]
        if node.words:
            return node.words[0]
        return None

    def words_at(self, digits: list[Digit_T]) -> list[str]:
        node: TrieNode = self
        for digit in digits:
            if node.children[digit] is None:
                return []
            node = node.children[digit]
        return node.words

    def load_dictionary(self, filename: str, verbose: bool) -> None:
        word_count: int = 0

        def word_to_digits(word: str) -> list[Digit_T]:
            result: list[Digit_T] = []
            for c in word.lower():
                if c not in CHAR_TO_DIGIT:
                    return []
                result.append(CHAR_TO_DIGIT[c])
            return result

        with open(filename, "r") as f:
            for line in f:
                word: str = line.strip()
                if not word:
                    continue
                digits: list[Digit_T] = word_to_digits(word)
                if digits and len(digits) == len(word):
                    self.add_word(word, digits)
                    word_count += 1

        if verbose:
            print(f"Loaded {word_count} words from {filename}")

    def find_encodings(self, digits: list[Digit_T], pos: int, current: list[str], results: list[list[str]]) -> None:
        if pos == len(digits):
            results.append(list(current))
            return

        # Option 1: use the bare digit at this position
        self.find_encodings(digits, pos + 1, current + [str(digits[pos])], results)

        # Option 2: match one or more words starting at pos
        node: TrieNode = self
        for i in range(pos, len(digits)):
            digit: Digit_T = digits[i]
            if node.children[digit] is None:
                break
            node = node.children[digit]
            for word in node.words:
                self.find_encodings(digits, i + 1, current + [word], results)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_number(num: str) -> list[Digit_T]:
    return [CHAR_TO_DIGIT[c] for c in num if c in CHAR_TO_DIGIT]

def format_solution(original_num: str, solution: list[str]) -> str:
    return f"{original_num}: {' '.join(solution)}"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: phonecode <dictionary_file> <phone_numbers_file>")
        print("Example: phonecode words.txt phones.txt")
        sys.exit(1)

    dict_file: str = sys.argv[1]
    phone_file: str = sys.argv[2]

    if not os.path.exists(dict_file):
        print(f"Error: Dictionary file not found: {dict_file}")
        sys.exit(1)
    if not os.path.exists(phone_file):
        print(f"Error: Phone numbers file not found: {phone_file}")
        sys.exit(1)

    trie: TrieNode = TrieNode()
    trie.load_dictionary(dict_file, True)

    # Quick sanity-check
    test_digits: list[Digit_T] = [Digit_T(3), Digit_T(5)]
    exact_match: str | None = trie.find_exact_word(test_digits)
    if exact_match is not None:
        print(f"Exact match for digits 3,5: {exact_match}")
    else:
        print("No exact match for digits 3,5")

    words_at_35: list[str] = trie.words_at(test_digits)
    print(f"Words at [3,5]: {words_at_35}")

    # Process phone numbers
    with open(phone_file, "r") as f:
        all_lines: list[str] = f.readlines()

    for line in all_lines:
        original: str = line.strip()
        if not original:
            continue
        digits: list[Digit_T] = clean_number(original)
        if not digits:
            continue
        results: list[list[str]] = []
        trie.find_encodings(digits, 0, [], results)
        for sol in results:
            print(format_solution(original, sol))

if __name__ == "__main__":
    main()
