import logging
import sys


def error_message_detail(error: Exception, error_detail: sys) -> str:
    """
    Extracts detailed error information including file name, line number, and the error message.

    :param error: The exception that occurred.
    :param error_detail: The sys module to access traceback details.
    :return: A formatted error message string.
    """
    _, _, exc_tb = error_detail.exc_info()

    if exc_tb is None:
        # Raised outside an `except` block, so there is no traceback to read
        error_message = f"Error: {str(error)}"
    else:
        file_name = exc_tb.tb_frame.f_code.co_filename
        line_number = exc_tb.tb_lineno
        error_message = (
            f"Error occurred in python script: [{file_name}] "
            f"at line number [{line_number}]: {str(error)}"
        )

    logging.error(error_message)
    return error_message


class CafeException(Exception):
    """
    Custom exception for the cafe voice agent. Wraps any error with file and line details.

    Usage:
        try:
            ...
        except Exception as e:
            raise CafeException(e, sys) from e
    """

    def __init__(self, error_message: Exception | str, error_detail: sys):
        super().__init__(error_message)
        self.error_message = error_message_detail(error_message, error_detail)

    def __str__(self) -> str:
        return self.error_message
