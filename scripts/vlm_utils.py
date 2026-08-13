"""Shared helper for calling the local Ollama vision model, used by both
generate_explanations.py and backfill_crq_rubrics.py."""
import base64

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5vl:7b"


def _post_ollama(payload: dict, timeout: int) -> dict:
    resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} from Ollama: {resp.text[:300]}")
    return resp.json()


def vlm_image(prompt: str, image_path: str, temperature: float = 0, num_ctx: int = 8192, timeout: int = 300) -> str:
    """Send an image + prompt to the local vision model, return the text response."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
    data = _post_ollama({
        "model": MODEL,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }, timeout=timeout)
    return data["response"].strip()


def vlm_text(prompt: str, temperature: float = 0.2, num_ctx: int = 8192, timeout: int = 300) -> str:
    """Send a text-only prompt to the local model, return the text response."""
    data = _post_ollama({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }, timeout=timeout)
    return data["response"].strip()
