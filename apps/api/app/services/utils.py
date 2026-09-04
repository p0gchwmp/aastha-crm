import re


def normalize_mobile(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) > 10 and digits.endswith(digits[-10:]):
        digits = digits[-10:]
    return digits
