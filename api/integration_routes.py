"""Integration settings endpoints: Telegram and AI providers."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_ui_access
from config import settings as settings_store
from config import testing as testing_mod
from whatsapp import baileys_client

int_router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class ValueBody(BaseModel):
    value: str = ""


class TokenBody(BaseModel):
    token: str = ""


@int_router.get("/status")
def get_status(_: None = Depends(require_ui_access)):
    return {"providers": settings_store.status(), "whatsapp": baileys_client.status()}


# ---- Telegram ----
@int_router.post("/telegram/save")
def telegram_save(body: TokenBody, _: None = Depends(require_ui_access)):
    result = testing_mod.test_telegram_token(body.token)
    if not result.get("valid"):
        raise HTTPException(status_code=400, detail=result.get("error", "Token tidak valid."))
    settings_store.set("telegram_bot_token", body.token)
    return {"saved": True, "username": result.get("username"), "needs_restart": True}


@int_router.post("/telegram/test")
def telegram_test(body: TokenBody, _: None = Depends(require_ui_access)):
    return testing_mod.test_telegram_token(body.token)


@int_router.post("/telegram/delete")
def telegram_delete(_: None = Depends(require_ui_access)):
    settings_store.delete("telegram_bot_token")
    return {"deleted": True}


# ---- DeepSeek ----
@int_router.post("/deepseek/save")
def deepseek_save(body: ValueBody, _: None = Depends(require_ui_access)):
    settings_store.set("deepseek_api_key", body.value)
    return {"saved": True, "needs_restart": True}


@int_router.post("/deepseek/test")
def deepseek_test(body: ValueBody, _: None = Depends(require_ui_access)):
    return testing_mod.test_deepseek_key(body.value)


@int_router.post("/deepseek/delete")
def deepseek_delete(_: None = Depends(require_ui_access)):
    settings_store.delete("deepseek_api_key")
    return {"deleted": True}


# ---- OpenRouter ----
@int_router.post("/openrouter/save")
def openrouter_save(body: ValueBody, _: None = Depends(require_ui_access)):
    settings_store.set("openrouter_api_key", body.value)
    return {"saved": True, "needs_restart": True}


@int_router.post("/openrouter/test")
def openrouter_test(body: ValueBody, _: None = Depends(require_ui_access)):
    return testing_mod.test_openrouter_key(body.value)


@int_router.post("/openrouter/delete")
def openrouter_delete(_: None = Depends(require_ui_access)):
    settings_store.delete("openrouter_api_key")
    return {"deleted": True}


# ---- AI provider selection + OpenRouter models ----
class AIConfigBody(BaseModel):
    ai_provider: str = ""
    openrouter_chat_model: str = ""
    openrouter_vision_model: str = ""


@int_router.post("/ai/config")
def ai_config_save(body: AIConfigBody, _: None = Depends(require_ui_access)):
    provider = (body.ai_provider or "").strip().lower()
    if provider and provider not in ("deepseek", "openrouter"):
        raise HTTPException(status_code=400, detail="AI_PROVIDER harus 'deepseek' atau 'openrouter'.")
    settings_store.set_config("ai_provider", provider)
    settings_store.set_config("openrouter_chat_model", (body.openrouter_chat_model or "").strip())
    settings_store.set_config("openrouter_vision_model", (body.openrouter_vision_model or "").strip())
    return {"saved": True, "needs_restart": True}
