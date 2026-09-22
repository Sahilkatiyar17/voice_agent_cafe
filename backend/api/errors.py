"""
Shared error handling for tool-backed endpoints.

A tool raises plain ValueError for expected, "the caller did something the business rules
don't allow" situations (sold out, wrong pincode, past date, ...) - those become a clean
400 with the tool's own message. Anything else is unexpected and becomes a CafeException,
logged with file/line, and a 500.
"""

import sys
from functools import wraps

from fastapi import HTTPException

from exception import CafeException


def handle_tool_errors(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except HTTPException:
            raise
        except Exception as e:
            raise CafeException(e, sys) from e

    return wrapper
