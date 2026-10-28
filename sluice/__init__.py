"""Sluice — a token-saving context-compression proxy between your prompts and the AI.

Three layers:
  * compressors/ : shrink tool output (shell, files, logs) by format/command;
  * store        : always keeps the ORIGINAL and returns a handle for byte-exact recall;
  * middleware   : compresses tool_result in an Anthropic-style Messages payload and
                   de-duplicates outputs repeated across turns.

Goal: spend the fewest input tokens per task without losing recoverable information.
"""

__version__ = "0.1.0"
