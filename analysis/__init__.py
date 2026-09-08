"""Traditional (lexicon-based) sentiment & stance grading of representatives.

Reads the pulled data under DATA_DIR and grades each representative by:
  1. what they say  — general tone of their questions/speeches
  2. topic stance   — pro/con lexicon per policy category, on what they say
  3. activity       — how much they participate
  4. voting         — how they vote on divisions, mapped to topics

See analysis/topics.py for the editable category + pro/con word lists and
analysis/grade.py for the scorer/CLI.
"""
