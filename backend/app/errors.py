from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Raised by services; rendered as {"error": {"code", "message"}}."""

    status_code = 400

    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFound(AppError):
    status_code = 404

    def __init__(self, message: str = "Resource not found"):
        super().__init__("not_found", message)


class Forbidden(AppError):
    status_code = 403

    def __init__(self, message: str = "You are not authorized to perform this action"):
        super().__init__("forbidden", message)


class Conflict(AppError):
    status_code = 409


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})
