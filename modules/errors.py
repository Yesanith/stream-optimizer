from __future__ import annotations


class OptimizerError(Exception):
    # message is shown to the user as is, detail keeps the raw cause for debugging
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
