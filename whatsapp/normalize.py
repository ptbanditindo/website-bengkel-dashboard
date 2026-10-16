"""WhatsApp phone-number normalization."""


def normalize_wa_number(value) -> str:
    """Return a stable, comparable phone number (digits only).

    Converts an Indonesian leading 0 to 62. Returns empty string for empty or
    non-numeric input. Callers must pass the sender number from gateway metadata,
    never text typed by the customer.
    """
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        return "62" + digits[1:]
    return digits
