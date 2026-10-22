"""Validation-case contract shared by feedback workflows."""
from pydantic import BaseModel, Field, model_validator


class CorrectionCase(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    input_payload: dict | list | str
    expected_output: str | None = Field(default=None,min_length=1,max_length=50000)
    expected_error: str | None = Field(default=None,min_length=1,max_length=500)

    @model_validator(mode='after')
    def one_expectation(self):
        if (self.expected_output is None)==(self.expected_error is None):
            raise ValueError('Provide exactly one expected_output or expected_error.')
        if self.expected_error is not None and not self.expected_error.strip():
            raise ValueError('Expected validation message must not be blank.')
        return self

