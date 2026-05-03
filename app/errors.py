from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class InvalidRequestError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_request", message, 400)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__("unauthorized", message, 401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__("forbidden", message, 403)


class NotFoundError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("not_found", message, 404)


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("conflict", message, 409)


class DependencyUnavailableError(AppError):
    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(code, message, status_code)
