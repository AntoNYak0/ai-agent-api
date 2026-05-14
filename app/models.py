from pydantic import BaseModel


class AuditRequest(BaseModel):
    code: str
    context: str | None = None


class AuditResponse(BaseModel):
    analysis: str
    payment_network: str
    payment_tx: str


class RefactorRequest(BaseModel):
    code: str
    instructions: str | None = None
    context: str | None = None


class RefactorResponse(BaseModel):
    refactored_code: str
    explanation: str
    payment_network: str
    payment_tx: str


class DocsRequest(BaseModel):
    code: str
    format: str = "markdown"
    context: str | None = None


class DocsResponse(BaseModel):
    documentation: str
    payment_network: str
    payment_tx: str
