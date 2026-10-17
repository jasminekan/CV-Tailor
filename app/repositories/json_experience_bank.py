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
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            bank = ExperienceBank.model_validate(payload)
            # PUT may generate new IDs, but stored records must already have
            # them. Generating IDs on each GET would break saved CV references.
            records = [
                record
                for field in ("work_experience", "projects", "education", "certifications", "additional_evidence")
                for record in payload.get(field, [])
            ]
            for work in payload.get("work_experience", []):
                records.extend(work.get("achievements", []))
            for project in payload.get("projects", []):
                records.extend(project.get("evidence", []))
            if any("id" not in record for record in records):
                raise ValueError("Saved experience-bank records must include stable IDs.")
            return bank
        except FileNotFoundError:
            return ExperienceBank()
        except (OSError, ValueError) as error:
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
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ExperienceBankRepositoryError("The experience bank could not be saved.") from error
        return bank
