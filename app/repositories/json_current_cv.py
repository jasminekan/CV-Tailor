import os
from pathlib import Path

from app.models import CurrentCV


class CurrentCVRepositoryError(Exception):
    """Raised when the local Current CV store cannot be read or written."""


class JsonCurrentCVRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> CurrentCV:
        try:
            return CurrentCV.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return CurrentCV()
        except (OSError, ValueError) as error:
            raise CurrentCVRepositoryError("The Current CV could not be loaded.") from error

    def save(self, current_cv: CurrentCV) -> CurrentCV:
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(current_cv.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary_path, self.path)
        except OSError as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                # A cleanup failure must not hide the original save failure.
                pass
            raise CurrentCVRepositoryError("The Current CV could not be saved.") from error
        return current_cv
