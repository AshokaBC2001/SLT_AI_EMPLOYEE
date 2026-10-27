"""Talks to the local model through llama.cpp's llama-server (OpenAI-style API).

This is the only file that knows how the model is reached. To use another
server or model later, change the settings in config.py (or the SLT_MODEL_URL
environment variable). Nothing is sent outside this computer.
"""
from __future__ import annotations

import time
from typing import Callable

import httpx

from . import config


class ModelUnavailable(Exception):
    """The model server is not running or did not answer."""


# Tests can replace the model with a function: fn(messages, json_mode) -> text
_backend: Callable[[list, bool], str] | None = None
_json_mode_supported = True
_health_cache: tuple[float, dict] = (0.0, {})


def set_backend(fn: Callable[[list, bool], str] | None) -> None:
    global _backend
    _backend = fn


def _prepare(messages: list[dict]) -> list[dict]:
    if not config.MERGE_SYSTEM_INTO_USER:
        return messages
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [dict(m) for m in messages if m["role"] != "system"]
    if system and rest and rest[0]["role"] == "user":
        rest[0]["content"] = system + "\n\n" + rest[0]["content"]
    elif system:
        rest.insert(0, {"role": "user", "content": system})
    return rest


def chat(messages: list[dict], json_mode: bool = True, max_tokens: int | None = None) -> str:
    """Send one chat request and return the model's text."""
    global _json_mode_supported
    if _backend is not None:
        return _backend(messages, json_mode)
    payload = {
        "model": config.MODEL_NAME,
        "messages": _prepare(messages),
        "temperature": config.MODEL_TEMPERATURE,
        "max_tokens": max_tokens or config.MODEL_MAX_TOKENS,
        "stream": False,
    }
    if json_mode and _json_mode_supported:
        payload["response_format"] = {"type": "json_object"}
    url = f"{config.MODEL_URL}/v1/chat/completions"
    try:
        r = httpx.post(url, json=payload, timeout=config.MODEL_TIMEOUT)
        if r.status_code == 400 and "response_format" in payload:
            # An older server may not accept response_format. Try once without it.
            _json_mode_supported = False
            payload.pop("response_format")
            r = httpx.post(url, json=payload, timeout=config.MODEL_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"] or ""
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise ModelUnavailable(f"The model server at {config.MODEL_URL} is not running.") from e
    except httpx.ReadTimeout as e:
        raise ModelUnavailable("The model took too long to answer.") from e
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        raise ModelUnavailable(f"The model server gave an error: {e}") from e


def health(force: bool = False) -> dict:
    """Is the model server up? Cached for 10 seconds."""
    global _health_cache
    if _backend is not None:
        return {"ok": True, "model": "test model", "detail": "Test model in use."}
    t, cached = _health_cache
    if not force and cached and time.time() - t < 10:
        return cached
    result = {"ok": False, "model": config.MODEL_NAME, "detail": ""}
    try:
        r = httpx.get(f"{config.MODEL_URL}/health", timeout=3)
        if r.status_code == 200:
            result["ok"] = True
            try:
                m = httpx.get(f"{config.MODEL_URL}/v1/models", timeout=3).json()
                ids = [x.get("id", "") for x in m.get("data", [])]
                if ids and ids[0]:
                    result["model"] = ids[0].split("/")[-1]
            except Exception:
                pass
            result["detail"] = "Model server is running."
        elif r.status_code == 503:
            result["detail"] = "Model server is starting (the model is still loading)."
        else:
            result["detail"] = f"Model server answered with code {r.status_code}."
    except httpx.HTTPError:
        result["detail"] = f"Model server is not running at {config.MODEL_URL}. Start it with ./start_model.sh"
    _health_cache = (time.time(), result)
    return result
