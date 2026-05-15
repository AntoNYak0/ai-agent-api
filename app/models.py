from pydantic import BaseModel, Field

# Size limits — protect DeepSeek budget from oversized inputs
MAX_CODE = 50_000       # 50 KB
MAX_TEXT = 50_000       # 50 KB
MAX_CONTEXT = 10_000    # 10 KB
MAX_QUERY = 10_000      # 10 KB
MAX_DIFF = 50_000       # 50 KB
MAX_DATA = 50_000       # 50 KB
MAX_DESC = 5_000        # 5 KB
MAX_INSTRUCTIONS = 5_000
MAX_DETAILS = 10_000
MAX_SCHEMA = 10_000
MAX_CATEGORIES = 2_000
MAX_NAME = 1_000        # protocol/chain/asset names
MAX_LANG = 200          # language identifiers
MAX_FORMAT = 100        # format names
MAX_TIMEFRAME = 50      # e.g. "daily", "weekly"
MAX_RESULT = 100_000    # 100 KB — AI response

# ── AI service models ──────────────────────────────────────────

class AuditRequest(BaseModel):
    code: str = Field(max_length=MAX_CODE)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)


class RefactorRequest(BaseModel):
    code: str = Field(max_length=MAX_CODE)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)


class DocsRequest(BaseModel):
    code: str = Field(max_length=MAX_CODE)
    format: str = Field(default="markdown", max_length=MAX_FORMAT)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)


class DefiAnalyzeRequest(BaseModel):
    protocol: str = Field(max_length=MAX_NAME)
    chain: str = Field(default="Ethereum", max_length=MAX_LANG)
    details: str | None = Field(default=None, max_length=MAX_DETAILS)


class TradingSignalRequest(BaseModel):
    asset: str = Field(max_length=MAX_NAME)
    timeframe: str = Field(default="daily", max_length=MAX_TIMEFRAME)
    additional_info: str | None = Field(default=None, max_length=MAX_DETAILS)


class SolidityScanRequest(BaseModel):
    code: str = Field(max_length=MAX_CODE)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)


class NlToSqlRequest(BaseModel):
    query: str = Field(max_length=MAX_QUERY)


class SqlToNlRequest(BaseModel):
    sql: str = Field(max_length=MAX_QUERY)


class GitSummarizeRequest(BaseModel):
    diff: str = Field(max_length=MAX_DIFF)


# ── Micro-task models ──────────────────────────────────────────

class ValidateJsonRequest(BaseModel):
    data: str = Field(max_length=MAX_DATA)
    target_schema: str | None = Field(default=None, max_length=MAX_SCHEMA)


class ClassifyTextRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    categories: str | None = Field(default=None, max_length=MAX_CATEGORIES)


class ExtractDataRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)


class TranslateCodeRequest(BaseModel):
    code: str = Field(max_length=MAX_CODE)
    source_lang: str = Field(max_length=MAX_LANG)
    target_lang: str = Field(max_length=MAX_LANG)


class GenerateRegexRequest(BaseModel):
    description: str = Field(max_length=MAX_DESC)


class FormatDataRequest(BaseModel):
    data: str = Field(max_length=MAX_DATA)
    source_format: str = Field(max_length=MAX_FORMAT)
    target_format: str = Field(max_length=MAX_FORMAT)


class SummarizeRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    max_length: int = Field(default=100, ge=10, le=5000)


# ── Response ───────────────────────────────────────────────────

class ServiceResponse(BaseModel):
    result: str = Field(max_length=MAX_RESULT)
    payment_network: str
    payment_tx: str
