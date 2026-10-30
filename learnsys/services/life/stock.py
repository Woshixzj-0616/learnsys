"""股票订阅：Tushare 免费档（日线），token 只存本地设置。

只用 `daily` 接口（非复权日线）；不做实时、不做 Level-2、不转发。
订阅的 `sources_json` 复用为股票代码列表。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import urllib.request

from learnsys import config

from .errors import LifeUnsupported

TUSHARE_API = "https://api.tushare.pro"
EASTMONEY_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"
FIELDS = ("ts_code,trade_date,close,pre_close,change,pct_chg,vol,amount")
MAX_CODES = 5
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
        })
    return quotes


def _secid(code: str) -> str:
    number, market = code.split(".", 1)
    return f"{'1' if market == 'SH' else '0'}.{number}"


def fetch_index_quotes(codes: list[str], day: str) -> list[dict]:
    """东方财富公开行情：一次请求拿多个指数，免 token、免积分。"""
    secids = [_secid(code) for code in codes]
    url = (f"{EASTMONEY_API}?secids={','.join(secids)}"
           "&fields=f2,f3,f4,f12,f14")
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
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
        })
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
        quotes += fetch_index_quotes(indices, day)
        sources.append("eastmoney")
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
            "source": "东方财富" if row["code"] in indices else "Tushare",
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
