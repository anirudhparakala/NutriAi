from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal


class Ingredient(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    name: str                       # normalized common name (e.g., "chicken thigh")
    amount: float | None = Field(default=None, ge=0)  # grams (optional - only if user/vision stated exact amount)
    unit: Literal["g"] = "g"        # grams only (prompts enforce conversion via density)
    source: Literal["vision","user","default","search","estimation","web","portion-resolver"]  # provenance
    portion_label: str | None = None  # size/variant label when grams unknown (e.g., "medium", "large", "2 cups")
    notes: str | None = None        # e.g., "boneless, skinless"

    @model_validator(mode='after')
    def validate_amount_source_contract(self):
        """
        Enforce strict contract:
        - If amount is set, source must be 'user' or 'vision' or 'portion-resolver'
        - If amount is None, portion_label should be present (soft check)
        """
        # If amount is set, source must be user/vision/portion-resolver
        if self.amount is not None and self.amount > 0:
            if self.source not in ("user", "vision", "portion-resolver"):
                raise ValueError(
                    f"Ingredient '{self.name}': amount can only be set if source is 'user', 'vision', or 'portion-resolver'. "
                    f"Got source='{self.source}', amount={self.amount}. Set amount=None and use portion_label instead."
                )
        return self


class Assumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    key: str                        # e.g., "oil_type"
    value: str                      # e.g., "butter"
    confidence: float = Field(ge=0, le=1)  # 0.0–1.0


class Explanation(BaseModel):
    """Schema for explanation JSON responses."""
    model_config = ConfigDict(extra='forbid', strict=True)

    explanation: str = ""
    follow_up_question: str = ""


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    id: str                         # stable key, e.g., "oil_type"
    text: str
    options: list[str] | None = None
    default: str | None = None
    impact_score: float = Field(ge=0, le=1)  # 0–1 estimated effect on kcal accuracy
    follow_up_prompt: str | None = None  # Optional prompt shown when option needs specification


class VisionEstimate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    dish: str
    portion_guess_g: float = Field(ge=0)  # portion weight must be >= 0
    ingredients: list[Ingredient]
    critical_questions: list[ClarificationQuestion]
    raw_model: dict | None = None   # for debugging (full LLM JSON before parsing)


class RefinementUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    updated_ingredients: list[Ingredient]
    updated_assumptions: list[Assumption]
    raw_model: dict | None = None