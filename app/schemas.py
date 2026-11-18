from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

EvidenceType = Literal[
    "Biological",
    "Trace",
    "Digital",
    "Firearms",
    "Document",
    "Other",
]


class Credentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class SignupRequest(Credentials):
    full_name: str = Field(min_length=2, max_length=100)


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    evidence_ref: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._/-]+$")
    evidence_type: EvidenceType
    collection_conditions: Literal["controlled", "challenging", "unknown"]
    ppe_compliant: bool
    tool_condition: Literal["clean", "compromised", "unknown"]
    packaging_condition: Literal["intact", "compromised", "unknown"]
    storage_condition: Literal["controlled", "uncontrolled", "unknown"]
    separately_packaged: bool
    chain_of_custody_documented: bool

    @field_validator("evidence_ref")
    @classmethod
    def evidence_ref_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Evidence reference is required.")
        return value


class PredictionRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        strict=True,
        extra="forbid",
    )

    evidence_type: EvidenceType
    collection_conditions: Literal["controlled", "challenging", "unknown"]
    ppe_compliant: bool
    tool_condition: Literal["clean", "compromised", "unknown"]
    packaging_condition: Literal["intact", "compromised", "unknown"]
    storage_condition: Literal["controlled", "uncontrolled", "unknown"]
    separately_packaged: bool
    chain_of_custody_documented: bool


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr


class AssessmentResponse(BaseModel):
    id: int
    evidence_ref: str
    evidence_type: str
    collection_conditions: str
    ppe_compliant: bool
    tool_condition: str
    packaging_condition: str
    storage_condition: str
    separately_packaged: bool
    chain_of_custody_documented: bool
    risk_category: str
    risk_score: int
    risk_factors: list[str]
    recommendations: list[str]
    created_at: str


class PrimaryScreenResult(BaseModel):
    status: Literal["succeeded"]
    method: str
    risk_category: str
    risk_score: int
    risk_factors: list[str]
    recommendations: list[str]


class ExperimentalClassifierResult(BaseModel):
    prediction: str
    class_probabilities: dict[str, float]
    algorithm: str
    dataset_type: str
    disclaimer: str


class ExperimentalClassifierExecution(BaseModel):
    status: Literal["succeeded", "failed"]
    result: ExperimentalClassifierResult | None = None
    message: str | None = None


class AssessmentWorkflowResponse(BaseModel):
    assessment: AssessmentResponse
    primary_screen: PrimaryScreenResult
    experimental_classifier: ExperimentalClassifierExecution
