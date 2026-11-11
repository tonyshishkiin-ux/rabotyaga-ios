"""Benchmark the local llama.cpp runtime without exposing prompts or credentials.

The script talks only to the loopback llama.cpp endpoint recorded by Hermes. It
measures a small prompt plus cold/warm prompts near the Hermes system-context
size and writes aggregate timing data to an ignored artifact path.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


SERVER_CONFIG = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "hermes"
    / "runtimes"
    / "llamacpp"
    / "server.json"
)


def request_json(base_url: str, api_key: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    parsed_base = urllib.parse.urlparse(base_url)
    url = urllib.parse.urlunparse((parsed_base.scheme, parsed_base.netloc, path, "", "", ""))
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Refusing to benchmark a non-loopback inference endpoint")

    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if body is None else "POST")
    request.add_header("Authorization", f"Bearer {api_key}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    return round(statistics.median(values), 2) if values else None


def completion(base_url: str, api_key: str, model: str, prompt: str, *, cache_prompt: bool) -> dict[str, Any]:
    started = time.perf_counter()
    response = request_json(
        base_url,
        api_key,
        "/completion",
        {
            "model": model,
            "prompt": prompt,
            "n_predict": 64,
            "temperature": 0,
            "cache_prompt": cache_prompt,
            "stream": False,
        },
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    timings = response.get("timings") or {}
    return {
        "wall_ms": round(elapsed_ms, 2),
        "prompt_tokens": timings.get("prompt_n"),
        "prompt_ms": timings.get("prompt_ms"),
        "prompt_tps": timings.get("prompt_per_second"),
        "output_tokens": timings.get("predicted_n"),
        "generation_ms": timings.get("predicted_ms"),
        "generation_tps": timings.get("predicted_per_second"),
        "cached_tokens": response.get("tokens_cached"),
    }


def prompt_near_tokens(base_url: str, api_key: str, model: str, target: int) -> tuple[str, int]:
    unit = "Neutral context item for a local performance measurement. "
    low, high = 1, target
    best = unit
    best_count = 0
    while low <= high:
        count = (low + high) // 2
        candidate = unit * count
        tokenized = request_json(base_url, api_key, "/tokenize", {"model": model, "content": candidate})
        tokens = len(tokenized.get("tokens") or [])
        if abs(tokens - target) < abs(best_count - target) or best_count == 0:
            best, best_count = candidate, tokens
        if tokens < target:
            low = count + 1
        elif tokens > target:
            high = count - 1
        else:
            break
    return best, best_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--target-prompt-tokens", type=int, default=17_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(SERVER_CONFIG.read_text(encoding="utf-8"))
    base_url = str(config["base_url"])
    api_key = str(config["api_key"])
    props = request_json(base_url, api_key, "/props")
    models = request_json(base_url, api_key, "/v1/models")
    model = str(models["data"][0]["id"])
    long_base, token_count = prompt_near_tokens(base_url, api_key, model, args.target_prompt_tokens)

    small_rows: list[dict[str, Any]] = []
    cold_rows: list[dict[str, Any]] = []
    warm_rows: list[dict[str, Any]] = []
    for index in range(args.runs):
        print(f"qwen:small:{index + 1}", flush=True)
        small_rows.append(completion(base_url, api_key, model, "Reply with one short greeting.", cache_prompt=False))

        # A unique suffix prevents a prior run from becoming the cold sample.
        prompt = f"Measurement id: {uuid.uuid4()}\n{long_base}\nReply briefly."
        print(f"qwen:cold:{index + 1}", flush=True)
        cold_rows.append(completion(base_url, api_key, model, prompt, cache_prompt=True))
        print(f"qwen:warm:{index + 1}", flush=True)
        warm_rows.append(completion(base_url, api_key, model, prompt, cache_prompt=True))

    model_value = props.get("model_path") or props.get("model")
    if not model_value or str(model_value).lower() == "none":
        model_value = model
    model_path = Path(str(model_value))
    result = {
        "schema": 1,
        "created_at": time.time(),
        "runs": args.runs,
        "server": {
            "model_file": model_path.name,
            "total_slots": props.get("total_slots"),
            "default_generation_settings": props.get("default_generation_settings"),
        },
        "target_prompt_tokens": args.target_prompt_tokens,
        "tokenized_prompt_tokens": token_count,
        "small": {"rows": small_rows},
        "cold_context": {"rows": cold_rows},
        "warm_context": {"rows": warm_rows},
    }
    for key in ("small", "cold_context", "warm_context"):
        rows = result[key]["rows"]
        result[key]["median"] = {
            field: median(rows, field)
            for field in (
                "wall_ms",
                "prompt_tokens",
                "prompt_ms",
                "prompt_tps",
                "output_tokens",
                "generation_ms",
                "generation_tps",
                "cached_tokens",
            )
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
