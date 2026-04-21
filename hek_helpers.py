#!/usr/bin/env python3
"""Shared helper functions for compound statement translators.

Used by both TO_PYTHON/hek_py3_parser.py and TO_NIM/hek_nim_parser.py.
"""

from hek_tokenize import RichNL

###############################################################################
# Indentation
###############################################################################

INDENT_STR = "    "


def _ind(level):
    """Return indentation string for the given nesting level."""
    return INDENT_STR * level


###############################################################################
# RichNL helpers
###############################################################################

def _richnl_lines(richnl_node):
    """Extract trivia lines from a RichNL or NL wrapper node.

    Returns a list of strings, or None if the node is not a RichNL.
    """
    rn = RichNL.extract_from(richnl_node)
    return rn.to_lines() if rn is not None else None


def _block_inline_header_comment(block_node):
    """Return the inline comment string on the compound header, or ''."""
    if not block_node or not block_node.nodes:
        return ''
    rn = RichNL.extract_from(block_node.nodes[0])
    return rn.inline_comment() if rn is not None else ''


###############################################################################
# Block statement helpers
###############################################################################

def _block_last_stmt(block_node):
    """Return the last stmt_line node in a block, or None.

    Walks the block's Several_Times children to find the last statement,
    skipping NL/trivia nodes.
    """
    last_stmt = None
    if not block_node or not hasattr(block_node, 'nodes'):
        return None
    for node in block_node.nodes:
        if type(node).__name__ == "Several_Times":
            for seq in node.nodes:
                if type(seq).__name__ == "Sequence_Parser" and hasattr(seq, "nodes"):
                    for child in seq.nodes:
                        if child is None:
                            continue
                        if type(child).__name__ != "Several_Times":
                            last_stmt = child
    return last_stmt
