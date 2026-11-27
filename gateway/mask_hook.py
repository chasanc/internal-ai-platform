"""LiteLLM pre-call hook: masks PII and financial identifiers in every request, whoever the caller is.

This is the second layer. Services such as support-triage still mask first, so raw text never leaves them; this hook
covers callers that do not (other languages, curl, a new tool). Masking is idempotent, so running twice is harmless.
Only user, assistant and tool messages are masked: the system prompt is ours. If masking fails the request is
rejected, never sent on unmasked.
"""
from litellm.integrations.custom_logger import CustomLogger

try:
    from .pii import mask  # in the repo, as gateway.mask_hook
except ImportError:
    from pii import mask  # in the gateway image, where LiteLLM loads this file as a top-level module

MASKED_ROLES = {"user", "assistant", "tool", "function"}


def mask_content(content):
    if isinstance(content, str):
        return mask(content)[0]
    if isinstance(content, list):  # OpenAI content parts: [{"type": "text", "text": "..."}]
        return [{**p, "text": mask(p["text"])[0]} if isinstance(p, dict) and isinstance(p.get("text"), str) else p for p in content]
    return content


class MaskGuard(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        messages = data.get("messages")
        if messages is None:
            return data
        try:
            data["messages"] = [
                {**m, "content": mask_content(m.get("content"))} if m.get("role") in MASKED_ROLES else m
                for m in messages
            ]
        except Exception as e:  # fail closed
            raise ValueError("request rejected: PII masking failed") from e
        return data


guard = MaskGuard()
