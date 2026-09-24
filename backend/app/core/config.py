"""Load configuration independently of the process working directory."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = Field(default="sqlite:///data/studyflow.db", min_length=1)
    canvas_base_url: str = ""
    canvas_access_token: SecretStr = SecretStr("")
    canvas_timeout_seconds: float = Field(default=20, gt=0, le=120)
    canvas_max_pages: int = Field(default=100, ge=1, le=10000)
    canvas_max_download_bytes: int = Field(default=104857600, gt=0)
    storage_path: Path = Path("data/files")
    materials_root: Path = Path("materials")
    sync_semester_id: int | None = Field(default=None, gt=0)
    material_ignore_readings: bool = True
    # Literal, pipe-separated phrases; not user-supplied regular expressions.
    material_core_terms: str = 'lecture|lecture slides|slides|tutorial|workshop|lab|practical|seminar'
    material_reading_terms: str = ('reading|required reading|recommended reading|supplementary reading|'
                                 'supplementary material|article|research paper|paper|journal article|'
                                 'book chapter|reference|further reading|additional reading|optional reading')

    @field_validator('sync_semester_id', mode='before')
    @classmethod
    def empty_semester(cls, value):
        return None if value == '' else value
    document_chunk_size: int = Field(default=2000, ge=100, le=20000)
    document_chunk_overlap: int = Field(default=200, ge=0)

    llm_provider: str = ""
    llm_model: str = ""
    openai_api_key: SecretStr = SecretStr("")
    deepseek_api_key: SecretStr = SecretStr("")
    knowledge_output_language: str = Field(default="", max_length=80)
    llm_timeout_seconds: float = Field(default=60, gt=0, le=180)
    llm_max_output_tokens: int = Field(default=6000, ge=512, le=16000)
    llm_batch_characters: int = Field(default=12000, ge=1000, le=32000)
    llm_max_batches: int = Field(default=20, ge=1, le=100)
    llm_max_retries: int = Field(default=1, ge=0, le=2)

    @model_validator(mode="after")
    def validate_chunk_settings(self):
        if self.document_chunk_overlap >= self.document_chunk_size:
            raise ValueError("DOCUMENT_CHUNK_OVERLAP must be smaller than DOCUMENT_CHUNK_SIZE")
        return self

    @field_validator("materials_root", mode="before")
    @classmethod
    def default_materials_root(cls, value):
        return "materials" if value is None or str(value).strip() == "" else value
