# -*- coding: utf-8 -*-
"""模型调用：任何 OpenAI 兼容接口，支持多 provider 链（第一个通了就用它，失败自动降级）。
没配 key / 全部失败时自动进入演示模式（不联网、不编造）。"""
import json
import os

import requests

DEFAULT_NAMES = {
    "api.deepseek.com": "deepseek",
    "open.bigmodel.cn": "智谱",
}


def _norm_provider(raw, default=None):
    """把一条 provider 配置补全成内部结构；没有 key 的也保留，之后过滤掉。"""
    raw = dict(raw or {})
    model = (raw.get("model") or "").strip()
    name = (raw.get("name") or model or "model").strip()
    key_env = (raw.get("api_key_env") or "").strip()
    key = os.environ.get(key_env, "").strip() if key_env else ""
    price_in = float(raw.get("price_in", 0.0) or 0.0)
    price_out = float(raw.get("price_out", 0.0) or 0.0)
    return {
        "name": name,
        "base_url": (raw.get("base_url") or "").rstrip("/"),
        "model": model,
        "api_key_env": key_env,
        "key": key,
        "price_in": price_in,
        "price_out": price_out,
        "free": (price_in == 0.0 and price_out == 0.0),
        "temperature": raw.get("temperature"),
        "timeout": raw.get("timeout"),
    }


def build_providers(cfg):
    """兼容两种写法：providers: [...] 列表，或旧的单 provider 顶层字段 + fallbacks: [...]。"""
    cfg = cfg or {}
    items = []
    if isinstance(cfg.get("providers"), list) and cfg.get("providers"):
        items = [_norm_provider(p) for p in cfg["providers"]]
    else:
        items = [_norm_provider(cfg, default=True)]
        for extra in (cfg.get("fallbacks") or []):
            items.append(_norm_provider(extra))
    seen = set()
    out = []
    for it in items:
        sig = (it["base_url"], it["model"], it["api_key_env"])
        if sig in seen:
            continue
        seen.add(sig)
        out.append(it)
    return out


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.temperature = self.cfg.get("temperature", 0.3)
        self.timeout = self.cfg.get("timeout", 90)
        self.json_retry = int(self.cfg.get("json_retry", 1) or 0)
        self.providers = build_providers(self.cfg)
        self.calls = 0
        self.errors = []
        self.used = {}
        self.disabled = False
        self.last_error = ""
        # 兼容旧代码：llm.key 仍然存在（只读，用于 --no-llm 判断已改为 disable()）
        self.key = next((p["key"] for p in self.providers if p["key"]), "")

    # ---------- 状态 ----------
    def active_providers(self):
        if self.disabled:
            return []
        return [p for p in self.providers if p["key"]]

    def available(self):
        return bool(self.active_providers())

    def disable(self):
        self.disabled = True

    def model_name(self):
        acts = self.active_providers()
        return acts[0]["model"] if acts else ""

    def cost_cny(self):
        total = 0.0
        for st in self.used.values():
            total += st.get("cost", 0.0)
        return total

    def provider_label(self):
        """给页面用：实际调用的模型与次数，例：deepseek-flash ×11 / glm-4.5-flash ×6（免费）"""
        if not self.used:
            return ""
        parts = []
        for name, st in self.used.items():
            if not st.get("calls"):
                continue
            label = name if not st.get("free") else name + "（免费）"
            parts.append("%s ×%d" % (label, st.get("calls", 0)))
        return " + ".join(parts)

    def usage_summary(self):
        return {
            "providers": [
                {"name": n, "calls": s["calls"], "in": s["in"], "out": s["out"],
                 "cost": round(s["cost"], 6), "free": s["free"], "errors": s["errors"]}
                for n, s in self.used.items()
            ],
            "calls": self.calls,
            "cost": round(self.cost_cny(), 6),
            "errors": self.errors[:8],
        }

    # ---------- 调用 ----------
    def _call_one(self, p, messages, json_mode=True, max_tokens=800):
        url = p["base_url"] + "/chat/completions"
        payload = {
            "model": p["model"],
            "messages": messages,
            "temperature": p["temperature"] if p["temperature"] is not None else self.temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        last_err = ""
        for _ in range(self.json_retry + 1):
            try:
                r = requests.post(url, headers={
                    "Authorization": "Bearer " + p["key"],
                    "Content-Type": "application/json",
                }, json=payload, timeout=p["timeout"] or self.timeout)
                if r.status_code != 200:
                    last_err = "%s HTTP %s %s" % (p["name"], r.status_code, r.text[:160])
                    continue
                data = r.json()
                u = data.get("usage") or {}
                tin = int(u.get("prompt_tokens") or 0)
                tout = int(u.get("completion_tokens") or 0)
                st = self.used.setdefault(p["name"], {"calls": 0, "in": 0, "out": 0,
                                                      "cost": 0.0, "free": p["free"],
                                                      "errors": 0})
                st["calls"] += 1
                st["in"] += tin
                st["out"] += tout
                st["cost"] += (tin / 1e6) * p["price_in"] + (tout / 1e6) * p["price_out"]
                self.calls += 1
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            except Exception as exc:
                last_err = "%s %s: %s" % (p["name"], type(exc).__name__, str(exc)[:160])
        raise RuntimeError(last_err)

    def complete(self, messages, json_mode=True, max_tokens=800):
        """按 provider 链依次尝试；全失败才抛错（上层会降级成摘录模式）。"""
        acts = self.active_providers()
        if not acts:
            raise RuntimeError("no api key")
        errs = []
        for p in acts:
            try:
                return self._call_one(p, messages, json_mode=json_mode, max_tokens=max_tokens)
            except Exception as exc:
                msg = str(exc)[:200]
                errs.append(msg)
                st = self.used.setdefault(p["name"], {"calls": 0, "in": 0, "out": 0,
                                                      "cost": 0.0, "free": p["free"],
                                                      "errors": 0})
                st["errors"] += 1
                self.errors.append(msg)
                self.last_error = msg
                continue
        raise RuntimeError("; ".join(errs[-2:]) or "all providers failed")


def parse_json(text):
    """模型有时会把 JSON 包在 markdown 代码块里，先剥掉再解析。"""
    if not text:
        return None
    t = text.strip()
    fence = "\x60\x60\x60"
    if t.startswith(fence):
        t = t.split("\n", 1)[-1]
    if t.endswith(fence):
        t = t.rsplit(fence, 1)[0]
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
