"""HTTP client for the Baileys WhatsApp gateway bridge (gateway/whatsapp_bridge.js).

Talks to 127.0.0.1 only, with the internal token. Never exposed to the browser.
"""

import json
import urllib.error
import urllib.request

DEFAULT_BRIDGE_URL = "http://127.0.0.1:9090"


def _token() -> str:
    from config.settings import get_internal_token
    return get_internal_token()


def _request(path: str, method: str = "GET", payload=None, timeout=10) -> dict:
    url = DEFAULT_BRIDGE_URL + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + _token())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"error": "HTTP " + str(e.code)}
    except Exception as e:
        return {"error": str(e), "status": "bridge_unavailable"}


def status() -> dict:
    return _request("/status")


def start_qr() -> dict:
    return _request("/start-qr", method="POST")


def request_pairing(phone: str) -> dict:
    return _request("/request-pairing", method="POST", payload={"phone": phone})


def logout() -> dict:
    return _request("/logout", method="POST")


def send_message(to: str, text: str) -> dict:
    return _request("/send", method="POST", payload={"to": to, "text": text})
