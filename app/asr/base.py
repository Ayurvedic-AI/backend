from dataclasses import dataclass


class BackendError(Exception):
    pass


@dataclass
class Transcript:
    text: str
    model_name: str
    language: str | None = None  # detected language when the caller passed "auto"
    english: str | None = None   # set when the backend translates speech directly

