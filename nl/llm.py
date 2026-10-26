# -*- coding: utf-8 -*-
"""模型调用：任何 OpenAI 兼容接口。没配 key 时自动进入演示模式（不联网、不编造）。"""
import json
import os
import re

import requests


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg
        self.key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "").strip()
        self.usage_in = 0
        self.usage_out = 0
        self.calls = 0
        self.errors = []

    def available(self):
        return bool(self.key)

    def cost_cny(self):
        return ((self.usage_in / 1e6) * self.cfg.get("price_in", 1.0)
                + (self.usage_out / 1e6) * self.cfg.get("price_out", 4.0))

    def complete(self, messages, json_mode=True, max_tokens=800):
        if not self.available():
            raise RuntimeError("no api key")
        url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        payload = {
            "model": self.cfg["model"],
            "messages": messages,
            "temperature": self.cfg.get("temperature", 0.3),
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        last_err = ""
        for _ in range(self.cfg.get("json_retry", 1) + 1):
            try:
                r = requests.post(url, headers={
                    "Authorization": "Bearer " + self.key,
                    "Content-Type": "application/json",
                }, json=payload, timeout=self.cfg.get("timeout", 90))
                if r.status_code != 200:
                    last_err = "HTTP %s %s" % (r.status_code, r.text[:200])
                    continue
                data = r.json()
                self.calls += 1
                u = data.get("usage") or {}
                self.usage_in += int(u.get("prompt_tokens") or 0)
                self.usage_out += int(u.get("completion_tokens") or 0)
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            except Exception as exc:
                last_err = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        self.errors.append(last_err)
        raise RuntimeError(last_err)


def parse_json(text):
    """模型有时会把 JSON 包在 markdown 代码块里，先剥掉再解析。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("\x60\x60\x60"):
        t = t.split("\n", 1)[-1]
    if t.endswith("\x60\x60\x60"):
        t = t.rsplit("\x60\x60\x60", 1)[0]
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except Exception:
            return None
    return None
