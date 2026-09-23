from pydantic import BaseModel, ConfigDict, PositiveInt, model_validator


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    semester_id: PositiveInt | None = None
    course_id: PositiveInt | None = None  # Local StudyFlow ID.
    module_id: PositiveInt | None = None  # Canvas IDs for bounded development runs.
    file_id: PositiveInt | None = None

    @model_validator(mode='after')
    def bounded_scope(self):
        if self.module_id is not None and self.course_id is None:
            raise ValueError('module_id requires course_id')
        if self.file_id is not None and self.module_id is None:
            raise ValueError('file_id requires module_id')
        return self
