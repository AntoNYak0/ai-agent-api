"""Micro-task prompts — high-frequency, low-cost agent pipeline services."""

VALIDATE_JSON_PROMPT = """\
Validate the provided JSON/YAML. Check: syntax, schema validity, type consistency.
Return the result as a single JSON object:
{
  "valid": true,
  "errors": [{"line": "line_or_path", "message": "what is wrong", "fix": "suggested correction"}],
  "warnings": [{"line": "line_or_path", "message": "potential issue"}]
}
If a target schema is provided, validate against it.
Output ONLY the JSON object. No additional text."""

CLASSIFY_TEXT_PROMPT = """\
Classify the provided text. Return the result as a single JSON object:
{
  "sentiment": "positive|negative|neutral",
  "category": "best_match_category",
  "confidence": 0.0-1.0,
  "keywords": ["key1", "key2"],
  "language": "detected_language"
}
Output ONLY the JSON object. No additional text."""

EXTRACT_DATA_PROMPT = """\
Extract structured data from the provided text. Return a single JSON object:
{
  "entities": [
    {"type": "name|email|phone|url|date|amount|address|id|company", "value": "extracted_value", "confidence": 0.0-1.0}
  ]
}
Output ONLY the JSON object. No additional text."""

TRANSLATE_CODE_PROMPT = """\
Translate the provided code from {source_lang} to {target_lang}.
Preserve exact logic and behavior. Use idiomatic patterns of the target language.
Return a single JSON object:
{
  "translated_code": "The translated code",
  "notes": ["Any potential behavioral differences or caveats"]
}
Output ONLY the JSON object. No additional text."""

GENERATE_REGEX_PROMPT = """\
Generate a regex pattern for the described matching task. Return a single JSON object:
{
  "pattern": "the_regex_pattern",
  "flags": "flags like g, i, m if needed",
  "test_cases": [{"input": "test_string", "matches": true, "captured": "captured_group_if_any"}],
  "explanation": "Brief explanation of how the pattern works"
}
Output ONLY the JSON object. No additional text."""

FORMAT_DATA_PROMPT = """\
Convert the provided data from {source_format} to {target_format}.
Preserve all data. Handle edge cases (nulls, nested structures, arrays).
Return a single JSON object:
{
  "converted": "The converted data as a string",
  "format": "{target_format}",
  "warnings": ["Any data loss or edge case notes"]
}
Output ONLY the JSON object. No additional text."""

SUMMARIZE_PROMPT = """\
Summarize the provided text in {max_length} words or less.
Preserve key facts, dates, names, and conclusions.
Return a single JSON object:
{
  "summary": "The summarized text",
  "word_count": number_of_words_in_summary,
  "key_points": ["Most important point 1", "point 2", "point 3"]
}
Output ONLY the JSON object. No additional text."""

# ── New prompts ────────────────────────────────────────────

NL_TO_SQL_PROMPT = """\
Convert the natural language description into a SQL query.
Infer the schema from the description. Return a single JSON object:
{
  "sql": "SELECT ... FROM ...",
  "explanation": "How the query works, what each clause does",
  "dialect": "standard|postgresql|mysql|sqlite|sqlserver",
  "assumed_schema": "CREATE TABLE statements for assumed schema"
}
Output ONLY the JSON object. No additional text."""

SQL_TO_NL_PROMPT = """\
Explain the provided SQL query in plain English. Return a single JSON object:
{
  "explanation": "What this query does in plain language",
  "tables_used": ["table1", "table2"],
  "operations": ["JOIN", "WHERE filter", "GROUP BY aggregation", "etc"],
  "complexity": "simple|moderate|complex"
}
Output ONLY the JSON object. No additional text."""

GIT_SUMMARIZE_PROMPT = """\
Summarize the provided git diff into a pull request description. Return a single JSON object:
{
  "title": "Concise PR title (under 70 chars)",
  "description": "PR description summarizing the changes and their purpose",
  "breaking_changes": ["Any breaking changes"],
  "files_summary": [
    {"file": "path/to/file", "what_changed": "brief description", "risk": "low|medium|high"}
  ]
}
Output ONLY the JSON object. No additional text."""

DEBUG_LOG_PROMPT = """\
Analyze the provided error log from a CI/CD pipeline or build failure.
Identify the root cause, suggest fixes, and provide code-level solutions.
Return a JSON object: {"error_type":"...", "root_cause":"...", "affected_files":[...], "fix":"...", "code_fix":"...", "prevention":"...", "confidence":"low|medium|high"}
Output ONLY the JSON object. No additional text."""
