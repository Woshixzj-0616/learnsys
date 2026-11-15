"""股票订阅：Tushare 免费档（日线），token 只存本地设置。

只用 `daily` 接口（非复权日线）；不做实时、不做 Level-2、不转发。
订阅的 `sources_json` 复用为股票代码列表。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import time
import urllib.request

from learnsys import config, diagnostics

from .errors import LifeUnsupported

TUSHARE_API = "https://api.tushare.pro"
EASTMONEY_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"
SINA_API = "https://hq.sinajs.cn/list="
FIELDS = ("ts_code,trade_date,close,pre_close,change,pct_chg,vol,amount")
MAX_CODES = 5
HTTP_ATTEMPTS = 2          # 东财瞬时断连很常见，请求内先重试一次
HTTP_RETRY_SLEEP = 0.3     # 秒
SOURCE_LABELS = {"eastmoney": "东方财富", "sina": "新浪财经", "tushare": "Tushare"}
PROMPT_VERSION = "life-stock-v1"
# 指数走东方财富公开行情（免费档的 index_daily 要 2000 积分）；个股走 Tushare daily。
INDEX_CODES = {"000001.SH", "399001.SZ", "399006.SZ",
               "000300.SH", "000905.SH", "399005.SZ"}


def _is_index(code: str) -> bool:
    return code in INDEX_CODES


def configured_token() -> str:
    """环境变量优先，其次 设置.json 里的 `life.tushare_token`。"""
    env = str(os.environ.get("TUSHARE_TOKEN") or "").strip()
    if env:
        return env
    raw = config.load_settings()
    life = raw.get("life") if isinstance(raw.get("life"), dict) else {}
    return str(life.get("tushare_token") or "").strip()


def mask_token(token: str) -> str:
    token = str(token or "")
    return ("••••" + token[-4:]) if token else ""


def save_token(token: str) -> None:
    """原子写设置文件；空串 = 清除。"""
    token = str(token or "").strip()
    data = config.load_settings()
    if not isinstance(data, dict):
        data = {}
    life = data.get("life") if isinstance(data.get("life"), dict) else {}
    if token:
        life["tushare_token"] = token
    else:
        life.pop("tushare_token", None)
    data["life"] = life
    target = pathlib.Path(config.SETTINGS_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, target)


def normalize_codes(raw) -> list[str]:
    """6 位数字补交易所后缀：6→SH，0/3→SZ，4/8→BJ；去重、最多 5 个。"""
    codes: list[str] = []
    for item in raw or []:
        text = str(item or "").strip().upper()
        if not text:
            continue
        if "." not in text and text.isdigit() and len(text) == 6:
            if text.startswith("6"):
                text += ".SH"
            elif text.startswith(("0", "3")):
                text += ".SZ"
            elif text.startswith(("4", "8")):
                text += ".BJ"
        if "." not in text or len(text.split(".")[0]) != 6:
            continue
        if text not in codes:
            codes.append(text)
        if len(codes) >= MAX_CODES:
            break
    return codes


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _request(payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        TUSHARE_API, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8") or "{}")
    if int(data.get("code") or 0) != 0:
        raise LifeUnsupported(
            f"Tushare：{data.get('msg') or '返回错误，检查 token 与权限'}")
    return data.get("data") or {}


def fetch_quotes(codes: list[str], token: str, day: str) -> list[dict]:
    """取每只股票最近一个交易日的日线；停牌/代码错会缺行。"""
    end = str(day or dt.date.today().isoformat()).replace("-", "")[:8]
    try:
        start = (dt.datetime.strptime(end, "%Y%m%d").date()
                 - dt.timedelta(days=14)).strftime("%Y%m%d")
    except ValueError:
        start = end
    quotes: list[dict] = []
    for code in codes:
        data = _request({
            "api_name": "daily", "token": token,
            "params": {"ts_code": code, "start_date": start, "end_date": end},
            "fields": FIELDS,
        })
        fields = data.get("fields") or []
        rows = data.get("items") or []
        if not rows:
            continue
        row = dict(zip(fields, rows[-1]))
        for candidate in rows:
            item = dict(zip(fields, candidate))
            if str(item.get("trade_date") or "") > str(row.get("trade_date") or ""):
                row = item
        quotes.append({
            "code": str(row.get("ts_code") or code),
            "trade_date": str(row.get("trade_date") or ""),
            "close": _num(row.get("close")),
            "pre_close": _num(row.get("pre_close")),
            "change": _num(row.get("change")),
            "pct_chg": _num(row.get("pct_chg")),
            "vol": _num(row.get("vol")),
            "amount": _num(row.get("amount")),
            "source": "tushare",
        })
    return quotes


def _secid(code: str) -> str:
    number, market = code.split(".", 1)
    return f"{'1' if market == 'SH' else '0'}.{number}"


def _fetch_eastmoney_indices(codes: list[str], day: str) -> list[dict]:
    secids = [_secid(code) for code in codes]
    url = (f"{EASTMONEY_API}?secids={','.join(secids)}"
           "&fields=f2,f3,f4,f12,f14")
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    last_exc: Exception | None = None
    for attempt in range(HTTP_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8") or "{}")
            rows = (data.get("data") or {}).get("diff") or []
            if isinstance(rows, dict):
                rows = [rows]
            quotes: list[dict] = []
            for code, row in zip(codes, rows):
                price = _num(row.get("f2")) / 100
                if price <= 0:
                    continue
                quotes.append({
                    "code": code,
                    "name": str(row.get("f14") or ""),
                    "trade_date": str(day),
                    "close": price,
                    "change": _num(row.get("f4")) / 100,
                    "pct_chg": _num(row.get("f3")) / 100,
                    "source": "eastmoney",
                })
            return quotes
        except Exception as exc:  # noqa: BLE001 —— 瞬时断连才重试，最后一轮抛给上层
            last_exc = exc
            if attempt + 1 < HTTP_ATTEMPTS:
                time.sleep(HTTP_RETRY_SLEEP)
    raise last_exc or RuntimeError("东方财富指数行情失败")


def _sina_symbol(code: str) -> str:
    number, market = code.split(".", 1)
    return f"{market.lower()}{number}"


def _fetch_sina_indices(codes: list[str], day: str) -> list[dict]:
    """新浪公开行情备用源；返回 GBK 文本，需要带 Referer。"""
    url = SINA_API + ",".join(_sina_symbol(code) for code in codes)
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.sina.com.cn",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read().decode("gbk", errors="replace")
    quotes: list[dict] = []
    for code in codes:
        match = re.search(rf'hq_str_{_sina_symbol(code)}="([^"]*)"', text)
        if not match:
            continue
        parts = match.group(1).split(",")
        if len(parts) < 32:
            continue
        price = _num(parts[3])
        pre_close = _num(parts[2])
        if price <= 0:
            continue
        change = price - pre_close if pre_close > 0 else 0.0
        pct_chg = (change / pre_close * 100) if pre_close > 0 else 0.0
        quotes.append({
            "code": code,
            "name": str(parts[0] or ""),
            "trade_date": str(parts[30] or day),
            "close": price,
            "change": change,
            "pct_chg": pct_chg,
            "source": "sina",
        })
    return quotes


def fetch_index_quotes(codes: list[str], day: str) -> list[dict]:
    """指数行情：东方财富优先（重试一次），失败或不全时切新浪。"""
    try:
        quotes = _fetch_eastmoney_indices(codes, day)
        if len(quotes) >= len(codes):
            return quotes
        if quotes:
            diagnostics.log_swallow(
                "指数行情：东方财富返回不完整，改用新浪",
                RuntimeError(f"请求 {len(codes)} 个指数，只返回 {len(quotes)} 个"))
    except Exception as exc:  # noqa: BLE001 —— 备用源就是为这里兜底
        diagnostics.log_swallow("指数行情：东方财富不可用，改用新浪", exc)
    quotes = _fetch_sina_indices(codes, day)
    if not quotes:
        raise LifeUnsupported("指数行情暂时取不到（东方财富与新浪都失败）")
    return quotes


def card_content(conn, sub: dict, day: str) -> dict:
    """生成股票卡片内容；失败抛中文 `LifeUnsupported`。"""
    codes = normalize_codes(sub.get("sources") or [])
    if not codes:
        raise LifeUnsupported("股票订阅要先填股票/指数代码（如 000001.SH）")
    indices = [code for code in codes if _is_index(code)]
    stocks = [code for code in codes if not _is_index(code)]
    quotes: list[dict] = []
    sources: list[str] = []
    if indices:
        index_quotes = fetch_index_quotes(indices, day)
        quotes += index_quotes
        sources.append(index_quotes[0].get("source", "eastmoney")
                       if index_quotes else "eastmoney")
    if stocks:
        token = configured_token()
        if not token:
            raise LifeUnsupported(
                "个股需要 Tushare token：到 tushare.pro 注册免费档后，在生活订阅页填入 token")
        quotes += fetch_quotes(stocks, token, day)
        sources.append("tushare")
    if not quotes:
        summary = "最近 14 天没有交易数据（可能停牌或代码不对）"
        items: list[dict] = []
    else:
        labels = [f"{(row.get('name') or row['code'])} "
                  f"{row['close']:.2f}（{row['pct_chg']:+.2f}%）"
                  for row in quotes]
        summary = "；".join(labels)[:200]
        items = [{
            "title": label,
            "summary": f"代码 {row['code']} · 交易日 {row['trade_date']}",
            "source": SOURCE_LABELS.get(
                row.get("source") or ("eastmoney" if row["code"] in indices
                                      else "tushare"),
                "Tushare"),
        } for label, row in zip(labels, quotes)]
    return {
        "kind": "stock",
        "topic": str(sub.get("topic") or ""),
        "summary": summary,
        "items": items,
        "source": "+".join(sources),
        "prompt_version": PROMPT_VERSION,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
