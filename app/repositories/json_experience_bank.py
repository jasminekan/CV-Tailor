import json
import os
from pathlib import Path

from app.models import ExperienceBank


class ExperienceBankRepositoryError(Exception):
    """Raised when the local experience-bank store cannot be read or written."""


class JsonExperienceBankRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ExperienceBank:
        if not self.path.exists():
            return ExperienceBank()
        try:
            return ExperienceBank.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ExperienceBankRepositoryError("The experience bank could not be loaded.") from error

    def save(self, bank: ExperienceBank) -> ExperienceBank:
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                bank.model_dump_json(indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise ExperienceBankRepositoryError("The experience bank could not be saved.") from error
        return bank