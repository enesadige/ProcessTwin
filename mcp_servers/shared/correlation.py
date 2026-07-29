import re

MAX_CORRELATION_ID_LENGTH = 128
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def is_valid_correlation_id(value: str) -> bool:
    return bool(
        value
        and len(value) <= MAX_CORRELATION_ID_LENGTH
        and CORRELATION_ID_PATTERN.fullmatch(value)
    )
