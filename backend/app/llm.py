"""Language-model step: turn retrieved data + rule outcomes into a plain answer (Google Gemini)."""
import asyncio
import json
import logging

from google import genai
from google.genai import errors, types

from . import config
from .prompts import OUTPUT_SCHEMA, SYSTEM_PROMPT, TRANSCRIBE_SCHEMA, transcribe_prompt

log = logging.getLogger(__name__)

RETRYABLE_CODES = {429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


class _Retryable(Exception):
    pass


_client: genai.Client | None = None


def available() -> bool:
    return bool(config.GEMINI_API_KEY)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        # HttpOptions.timeout is in milliseconds.
        _client = genai.Client(api_key=config.GEMINI_API_KEY,
                               http_options=types.HttpOptions(timeout=int(config.LLM_TIMEOUT_S * 1000)))
    return _client


def _gen_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=OUTPUT_SCHEMA,
        thinking_config=types.ThinkingConfig(thinking_level=config.LLM_THINKING_LEVEL),
        max_output_tokens=config.LLM_MAX_TOKENS,
    )


def _transcribe_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=TRANSCRIBE_SCHEMA,
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
        max_output_tokens=2048,
    )


async def _call(model: str, contents, gen_config: types.GenerateContentConfig | None = None) -> dict:
    try:
        response = await asyncio.wait_for(
            _get_client().aio.models.generate_content(model=model, contents=contents,
                                                      config=gen_config or _gen_config()),
            timeout=config.LLM_TIMEOUT_S + 5,
        )
    except asyncio.TimeoutError:
        raise _Retryable(f"timed out after {config.LLM_TIMEOUT_S:.0f}s")
    except errors.APIError as e:
        if e.code in RETRYABLE_CODES:
            raise _Retryable("rate limit reached" if e.code == 429 else f"HTTP {e.code}")
        if e.code in (400, 401, 403) and "API key" in str(e):
            raise LLMError("language model rejected the API key")
        raise LLMError(f"language model error (HTTP {e.code})")
    except Exception as e:  # network errors surface as httpx exceptions
        raise _Retryable(f"could not reach the language model ({type(e).__name__})")

    if response.prompt_feedback and response.prompt_feedback.block_reason:
        raise LLMError("language model declined this request")
    finish = response.candidates[0].finish_reason if response.candidates else None
    if finish == types.FinishReason.MAX_TOKENS:
        raise LLMError("language model answer was cut off")
    if finish not in (None, types.FinishReason.STOP):
        raise LLMError(f"language model stopped early ({finish.name if finish else 'unknown'})")

    text = response.text
    if not text:
        raise LLMError("language model returned no text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON: %.200s", text)
        raise LLMError("language model returned an invalid answer")


async def generate(user_message: str) -> tuple[dict, str]:
    """Call Gemini and return (parsed JSON answer, model used). Raises LLMError on any failure.

    On a rate limit, timeout or server error the request is retried once on
    LLM_FALLBACK_MODEL (free-tier quotas are per model).
    """
    if not available():
        raise LLMError("language model not configured (GEMINI_API_KEY is not set)")
    last = ""
    for model in _models():
        try:
            return await _call(model, user_message), model
        except _Retryable as e:
            last = str(e)
            log.warning("LLM %s failed (%s)", model, last)
    raise LLMError(f"language model unavailable: {last}")


def _models() -> list[str]:
    models = [config.LLM_MODEL]
    if config.LLM_RETRIES and config.LLM_FALLBACK_MODEL and config.LLM_FALLBACK_MODEL != config.LLM_MODEL:
        models.append(config.LLM_FALLBACK_MODEL)
    return models


async def transcribe(wav: bytes, lang_hint: str | None = None) -> tuple[dict, str]:
    """Transcribe a short WAV clip of the farmer's question. Returns ({text, language}, model used)."""
    if not available():
        raise LLMError("voice input needs the language model (GEMINI_API_KEY is not set)")
    contents = [types.Part.from_bytes(data=wav, mime_type="audio/wav"), transcribe_prompt(lang_hint)]
    last = ""
    for model in _models():
        try:
            return await _call(model, contents, _transcribe_config()), model
        except _Retryable as e:
            last = str(e)
            log.warning("transcription with %s failed (%s)", model, last)
    raise LLMError(f"speech-to-text unavailable: {last}")
