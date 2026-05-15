from pydantic import BaseModel


# ── AI service models ──────────────────────────────────────────

class AuditRequest(BaseModel):
    code: str
    context: str | None = None


class RefactorRequest(BaseModel):
    code: str
    instructions: str | None = None
    context: str | None = None


class DocsRequest(BaseModel):
    code: str
    format: str = "markdown"
    context: str | None = None


class DefiAnalyzeRequest(BaseModel):
    protocol: str
    chain: str = "Ethereum"
    details: str | None = None


class TradingSignalRequest(BaseModel):
    asset: str
    timeframe: str = "daily"
    additional_info: str | None = None


class SolidityScanRequest(BaseModel):
    code: str
    context: str | None = None


class NlToSqlRequest(BaseModel):
    query: str


class SqlToNlRequest(BaseModel):
    sql: str


class GitSummarizeRequest(BaseModel):
    diff: str


# ── Micro-task models ──────────────────────────────────────────

class ValidateJsonRequest(BaseModel):
    data: str
    target_schema: str | None = None


class ClassifyTextRequest(BaseModel):
    text: str
    categories: str | None = None


class ExtractDataRequest(BaseModel):
    text: str


class TranslateCodeRequest(BaseModel):
    code: str
    source_lang: str
    target_lang: str


class GenerateRegexRequest(BaseModel):
    description: str


class FormatDataRequest(BaseModel):
    data: str
    source_format: str
    target_format: str


class SummarizeRequest(BaseModel):
    text: str
    max_length: int = 100


# ── Response ───────────────────────────────────────────────────

class ServiceResponse(BaseModel):
    result: str
    payment_network: str
    payment_tx: str
