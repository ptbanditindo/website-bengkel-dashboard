"""WhatsApp gateway abstraction (no real provider connected yet)."""

from whatsapp.normalize import normalize_wa_number


class GatewayStatus:
    def __init__(self, connected=False, provider="mock", detail=""):
        self.connected = connected
        self.provider = provider
        self.detail = detail

    def as_dict(self) -> dict:
        return {"connected": self.connected, "provider": self.provider, "detail": self.detail}


class BaseGateway:
    def status(self) -> GatewayStatus:
        raise NotImplementedError

    def send_message(self, wa_number: str, text: str) -> bool:
        raise NotImplementedError

    def receive_event(self, payload: dict) -> dict | None:
        raise NotImplementedError


class MockGateway(BaseGateway):
    """Honest mock adapter: records outgoing messages, never reports connected."""

    def __init__(self):
        self.sent: list[dict] = []

    def status(self) -> GatewayStatus:
        return GatewayStatus(connected=False, provider="mock", detail="Gateway WhatsApp nyata belum dipasang.")

    def send_message(self, wa_number: str, text: str) -> bool:
        self.sent.append({"to": normalize_wa_number(wa_number), "text": text})
        return True

    def receive_event(self, payload: dict) -> dict | None:
        wa_number = normalize_wa_number(payload.get("from", ""))
        message_id = payload.get("message_id")
        text = (payload.get("text") or "").strip()
        if not wa_number or not text:
            return None
        return {"wa_number": wa_number, "message_id": message_id, "text": text}
