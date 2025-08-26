#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, time, json, requests, sys
from typing import Optional, List, Tuple
from datetime import datetime, timezone, timedelta

# ================== 环境变量 ==================
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
HOLDINGS_DB_ID = (os.getenv("HOLDINGS_DB_ID") or os.getenv("NOTION_DATABASE_ID") or "").strip()
TRADES_DB_ID = os.getenv("TRADES_DB_ID", "").strip()
DASHBOARD_DB_ID = os.getenv("DASHBOARD_DB_ID", "").strip()   # 可选：数据看板库ID（否则自动解析）

# ============== 字段名（按你库实际改） ==============
# 交易流水表
TRADE_CODE_PROP = "Code"
TRADE_NAME_PROP = "基金名称"           # title 或 rich_text
TRADE_RELATION_PROP = "Fund 持仓"          # Relation → 持仓表

# 持仓表
HOLDING_TITLE_PROP = "基金名称"           # Title
HOLDING_CODE_PROP = "Code"              # Rich text
HOLDING_DASHBOARD_REL_PROP = "数据看板"     # Relation → 数据看板库

# 行情字段（持仓表）
FIELD = {
    "title": HOLDING_TITLE_PROP,
    "code": HOLDING_CODE_PROP,
    "dwjz": "单位净值",
    "gsz": "估算净值",
    "gszzl": "估算涨跌幅",
    "gztime": "估值时间",
    "source": "来源",
    "updated":"更新于",
}
# 仓位计算字段（持仓表）
COST_FIELD = "持仓成本"    # Number / Formula / Rollup(number)
WEIGHT_FIELD = "仓位"        # Number（建议Notion设置为百分比显示）

# ================== Notion / API ==================
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fund.eastmoney.com",
    "Accept": "*/*",
    "Connection": "keep-alive",
}

FUNDGZ_HTTP = "http://fundgz.1234567.com.cn/js/{code}.js"
FUNDGZ_HTTPS = "https://fundgz.1234567.com.cn/js/{code}.js"
EM_F10_API   = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=1&startDate=&endDate="

# ================ 工具函数 ================
SG_TZ = timezone(timedelta(hours=8))  # Asia/Singapore

def today_iso_date() -> str:
    return datetime.now(SG_TZ).date().isoformat()

def zpad6(s: str) -> str:
    t = "".join(ch for ch in str(s or "").strip() if ch.isdigit())
    return t.zfill(6) if t else ""

def notion_request(method: str, path: str, payload=None):
    url = f"https://api.notion.com/v1{path}"
    r = requests.request(method, url, headers=NOTION_HEADERS,
                         data=json.dumps(payload) if payload is not None else None,
                         timeout=25)
    if not r.ok:
        raise RuntimeError(f"Notion {method} {path} failed: {r.status_code} {r.text}")
    return r.json()

def get_prop_text(prop) -> str:
    if not prop: return ""
    t = prop.get("type")
    if t == "rich_text":
        arr = prop.get("rich_text") or []
        return "".join([(x.get("plain_text") or "") for x in arr]).strip()
    if t == "title":
        arr = prop.get("title") or []
        return "".join([(x.get("plain_text") or "") for x in arr]).strip()
    if t == "number":
        v = prop.get("number"); return "" if v is None else str(v)
    return ""

def has_relation(prop) -> bool:
    if not prop: return False
    if prop.get("type") != "relation": return False
    arr = prop.get("relation") or []
    return len(arr) > 0

def normalize_num_str(s: str) -> str:
    return (s or "").replace("－","-").replace("%","").strip()

def to_float_safe(x):
    try:
        return float(normalize_num_str(str(x)))
    except Exception:
        return None

def is_iso_like(s: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$", s or ""))

def get_page_properties(page_id: str) -> dict:
    return notion_request("GET", f"/pages/{page_id}")

# ================ fundgz（名称/行情） ================
def http_get_utf8(url: str, timeout: float = 8.0) -> str:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    r.raise_for_status()
    return r.content.decode("utf-8", errors="replace")

def fetch_fund_name_from_fundgz(code6: str) -> Optional[str]:
    for base in (FUNDGZ_HTTP, FUNDGZ_HTTPS):
        try:
            raw = http_get_utf8(base.format(code=code6) + f"?rt={int(time.time())}")
            m = re.search(r'\{.*\}', raw, flags=re.S)
            if not m: continue
            js = m.group(0)
            mm = re.search(r'"name"\s*:\s*"([^"]+)"', js)
            if mm: return mm.group(1).strip()
        except Exception:
            time.sleep(0.2); continue
    return None

def fetch_fundgz(code6: str, timeout: float = 8.0) -> dict:
    for base in (FUNDGZ_HTTP, FUNDGZ_HTTPS):
        try:
            raw = http_get_utf8(base.format(code=code6) + f"?rt={int(time.time())}", timeout=timeout)
            m = re.search(r"\{.*\}", raw, flags=re.S)
            if not m: continue
            js = m.group(0)
            def jget(k):
                mm = re.search(rf'"{k}"\s*:\s*"([^"]*)"', js)
                return mm.group(1) if mm else ""
            name  = jget("name")
            dwjz  = jget("dwjz")
            gsz   = jget("gsz")
            gszzl = normalize_num_str(jget("gszzl"))
            gz    = jget("gztime")
            if gz and not is_iso_like(gz): gz = ""
            return {"name": name, "dwjz": dwjz, "gsz": gsz, "gszzl": gszzl, "gztime": gz, "source": "天天基金"}
        except Exception:
            time.sleep(0.3); continue
    return {}

# ================ 东方财富 F10（兜底） ================
def fetch_em_last_nav_and_chg(code6: str, timeout: float = 8.0) -> dict:
    try:
        url = EM_F10_API.format(code=code6)
        r = requests.get(url, headers=UA_HEADERS, timeout=timeout)
        r.raise_for_status()
        js = r.json()
        rows = (js.get("Data") or {}).get("LSJZList") or []
        if not rows: return {}
        row = rows[0]
        return {
            "dwjz": row.get("DWJZ"),
            "gszzl": row.get("JZZZL"),
            "gztime": row.get("FSRQ"),
            "source": "东方财富(历史净值)"
        }
    except Exception:
        return {}

# ================ 持仓 查找/创建/标题补全 ================
def find_holding_by_code(code6: str) -> Optional[str]:
    payload = {"filter": {"property": HOLDING_CODE_PROP, "rich_text": {"equals": code6}}, "page_size": 1}
    data = notion_request("POST", f"/databases/{HOLDINGS_DB_ID}/query", payload)
    res = data.get("results") or []
    return res[0]["id"] if res else None

def create_holding(code6: str, name: str) -> str:
    props = {
        HOLDING_TITLE_PROP: {"title": [{"text": {"content": name or code6}}]},
        HOLDING_CODE_PROP:  {"rich_text": [{"text": {"content": code6}}]},
    }
    data = notion_request("POST", "/pages", {
        "parent": {"database_id": HOLDINGS_DB_ID},
        "properties": props
    })
    return data["id"]

def get_holding_title(holding_page_id: str) -> str:
    props = get_page_properties(holding_page_id).get("properties") or {}
    return get_prop_text(props.get(HOLDING_TITLE_PROP)) or ""

def update_holding_title_if_needed(holding_page_id: str, code6: str, fetched_name: Optional[str]=None):
    cur = get_holding_title(holding_page_id)
    need = (not cur) or (cur.isdigit()) or (cur == code6)
    if not need: return
    name = fetched_name or fetch_fund_name_from_fundgz(code6) or code6
    notion_request("PATCH", f"/pages/{holding_page_id}", {
        "properties": { HOLDING_TITLE_PROP: { "title": [{"text": {"content": name}}] } }
    })

# ================ 交易：Relation / 名称写入 ================
def set_trade_relation(trade_page_id: str, holding_page_id: str):
    notion_request("PATCH", f"/pages/{trade_page_id}", {
        "properties": { TRADE_RELATION_PROP: { "relation": [{"id": holding_page_id}] } }
    })

def set_trade_name(trade_page_id: str, name: str):
    if not name: return
    pg = get_page_properties(trade_page_id)
    p = (pg.get("properties") or {}).get(TRADE_NAME_PROP)
    if not p: return
    t = p.get("type")
    if t == "title":
        payload = { TRADE_NAME_PROP: { "title": [{"text": {"content": name}}] } }
    elif t == "rich_text":
        payload = { TRADE_NAME_PROP: { "rich_text": [{"text": {"content": name}}] } }
    else:
        return
    notion_request("PATCH", f"/pages/{trade_page_id}", { "properties": payload })

# ================ 数据看板 Relation（icon=💰） ================
_dashboard_db_id_cache = None
_moneybag_page_id_cache = None

def get_dashboard_db_id() -> Optional[str]:
    global _dashboard_db_id_cache
    if DASHBOARD_DB_ID: return DASHBOARD_DB_ID
    if _dashboard_db_id_cache: return _dashboard_db_id_cache
    db = notion_request("GET", f"/databases/{HOLDINGS_DB_ID}")
    p = (db.get("properties") or {}).get(HOLDING_DASHBOARD_REL_PROP)
    if p and p.get("type") == "relation":
        _dashboard_db_id_cache = (p.get("relation") or {}).get("database_id")
    return _dashboard_db_id_cache

def _scan_pick_moneybag(pages):
    for pg in pages:
        icon = pg.get("icon")
        if icon and icon.get("type") == "emoji" and icon.get("emoji") == "💰":
            return pg["id"]
    for pg in pages:
        props = pg.get("properties", {})
        title_prop = next((props[k] for k, v in props.items() if v.get("type") == "title"), None)
        name = get_prop_text(title_prop)
        if "💰" in name: return pg["id"]
    for pg in pages:
        props = pg.get("properties", {})
        title_prop = next((props[k] for k, v in props.items() if v.get("type") == "title"), None)
        name = get_prop_text(title_prop)
        if "数据看板" in name: return pg["id"]
    return None

def find_moneybag_page_id() -> Optional[str]:
    global _moneybag_page_id_cache
    if _moneybag_page_id_cache: return _moneybag_page_id_cache
    dbid = get_dashboard_db_id()
    if not dbid: return None
    cursor = None
    pages = []
    while True:
        payload = {"page_size": 100}
        if cursor: payload["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{dbid}/query", payload)
        pages.extend(data.get("results") or [])
        cursor = data.get("next_cursor")
        if not data.get("has_more"): break
    target = _scan_pick_moneybag(pages)
    if target: _moneybag_page_id_cache = target
    return _moneybag_page_id_cache

def ensure_holding_dashboard_relation(holding_page_id: str):
    target_id = find_moneybag_page_id()
    if not target_id: return
    pg = get_page_properties(holding_page_id)
    rel = (pg.get("properties") or {}).get(HOLDING_DASHBOARD_REL_PROP)
    current = []
    if rel and rel.get("type") == "relation":
        current = rel.get("relation") or []
        if any(x.get("id") == target_id for x in current):
            return
    new_list = current + [{"id": target_id}]
    notion_request("PATCH", f"/pages/{holding_page_id}", {
        "properties": { HOLDING_DASHBOARD_REL_PROP: { "relation": new_list } }
    })

def sweep_all_holdings_and_fix_dashboard():
    target_id = find_moneybag_page_id()
    if not target_id:
        print("[WARN] 未找到 icon=💰 的数据看板页面，跳过 sweep。"); return
    cursor = None; fixed = 0; total = 0
    while True:
        payload = {"page_size": 100}
        if cursor: payload["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{HOLDINGS_DB_ID}/query", payload)
        for pg in data.get("results") or []:
            total += 1
            rel = (pg.get("properties") or {}).get(HOLDING_DASHBOARD_REL_PROP)
            need = True
            if rel and rel.get("type") == "relation":
                if any(x.get("id") == target_id for x in (rel.get("relation") or [])):
                    need = False
            if need:
                ensure_holding_dashboard_relation(pg["id"]); fixed += 1
        cursor = data.get("next_cursor")
        if not data.get("has_more"): break
    print(f"[SWEEP] 数据看板 Relation 修复：fixed={fixed} / total={total}")

# ================ 交易处理：建立/补齐关系与名称（支持--today-only） ================
def process_new_trades(today_only: bool = False):
    cursor = None
    processed = created = linked = named = dashboard_linked = 0
    while True:
        payload = {"page_size": 50}
        if cursor:
            payload["start_cursor"] = cursor
        # 基础过滤：Code 非空 & Relation 为空
        flt = {
            "and": [
                {"property": TRADE_CODE_PROP, "rich_text": {"is_not_empty": True}},
                {"property": TRADE_RELATION_PROP, "relation": {"is_empty": True}}
            ]
        }
        if today_only:
            # 只处理“今天创建”的交易
            flt["and"].append({"timestamp": "created_time", "created_time": {"on_or_after": today_iso_date()}})
        payload["filter"] = flt

        data = notion_request("POST", f"/databases/{TRADES_DB_ID}/query", payload)
        for pg in data.get("results") or []:
            processed += 1
            props = pg.get("properties") or {}
            trade_id = pg["id"]
            code6 = zpad6(get_prop_text(props.get(TRADE_CODE_PROP)))
            if not code6:
                continue

            holding_id = find_holding_by_code(code6)
            fetched_name = None
            if not holding_id:
                fetched_name = fetch_fund_name_from_fundgz(code6) or code6
                holding_id = create_holding(code6, fetched_name)
                created += 1

            update_holding_title_if_needed(holding_id, code6, fetched_name)
            set_trade_relation(trade_id, holding_id)
            linked += 1

            if not fetched_name:
                fetched_name = get_holding_title(holding_id) or fetch_fund_name_from_fundgz(code6) or code6
            set_trade_name(trade_id, fetched_name)
            named += 1

            try:
                ensure_holding_dashboard_relation(holding_id)
                dashboard_linked += 1
            except Exception as e:
                print(f"[WARN] dashboard relation skip: {e}")

            print(f"[OK] trade {trade_id} -> holding {holding_id} (code={code6}, name={fetched_name})")

        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break

    print(f"TRADES Done. processed={processed}, created_holdings={created}, linked={linked}, named={named}, dashboard_linked={dashboard_linked}")

# ================ 行情更新（持仓表） ================
def list_holdings_pages():
    pages = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{HOLDINGS_DB_ID}/query", payload)
        pages.extend(data.get("results") or [])
        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break
    return pages

def build_market_props(code: str, name: str, info: dict) -> dict:
    now_iso = datetime.now(SG_TZ).isoformat()
    props = {
        FIELD["title"]: {"title": [{"text": {"content": name or code}}]},
        FIELD["code"]: {"rich_text": [{"text": {"content": code}}]},
        FIELD["dwjz"]: {"number": to_float_safe(info.get("dwjz"))},
        FIELD["gsz"]: {"number": to_float_safe(info.get("gsz"))},
        FIELD["gszzl"]: {"number": to_float_safe(info.get("gszzl"))},
        FIELD["source"]: {"select": {"name": info.get("source") or "失败"}},
        FIELD["updated"]: {"date": {"start": now_iso}},
    }
    gz = (info.get("gztime") or "").strip()
    if gz and is_iso_like(gz):
        props[FIELD["gztime"]] = {"date": {"start": gz}}
    return props

def update_holdings_market():
    pages = list_holdings_pages()
    total = ok = fail = 0
    for pg in pages:
        props = pg.get("properties") or {}
        code_raw = get_prop_text(props.get(FIELD["code"])) or get_prop_text(props.get(FIELD["title"]))
        code6 = zpad6(code_raw)
        if not code6:
            continue
        total += 1

        info = fetch_fundgz(code6)
        if not info or not info.get("gszzl"):
            em = fetch_em_last_nav_and_chg(code6)
            if em:
                info = {
                    "name": info.get("name") if info else "",
                    "dwjz": em.get("dwjz"),
                    "gsz": em.get("dwjz"),
                    "gszzl": em.get("gszzl"),
                    "gztime": em.get("gztime"),
                    "source": em.get("source")
                }
        if not (info.get("dwjz") or info.get("gszzl")):
            info = {"source": "失败"}

        name_existing = get_prop_text(props.get(FIELD["title"]))
        name = (info.get("name") or name_existing or code6).strip()
        try:
            notion_request("PATCH", f"/pages/{pg['id']}", {"properties": build_market_props(code6, name, info)})
            print(f"[MARKET] {code6} {name} ｜source={info.get('source')} ｜chg={info.get('gszzl')}")
            ok += 1
        except Exception as e:
            print(f"[ERR] MARKET {code6}: {e}")
            fail += 1
    print(f"MARKET Done. updated={ok}, failed={fail}, total={total}")


# ================ 仓位计算（基于持仓成本） ================
def prop_number_value(p: dict):
    if not p:
        return None
    t = p.get("type")
    if t == "number":
        return p.get("number")
    if t == "formula":
        f = p.get("formula") or {}
        if f.get("type") == "number":
            return f.get("number")
    if t == "rollup":
        r = p.get("rollup") or {}
        if r.get("type") == "number":
            return r.get("number")
    return None

def update_positions_by_cost():
    pages = list_holdings_pages()
    # 1) 计算总持仓成本
    costs = []
    for pg in pages:
        props = pg.get("properties") or {}
        c = prop_number_value(props.get(COST_FIELD))
        if c is not None:
            costs.append((pg["id"], float(c)))
    total_cost = sum(v for _, v in costs)
    print(f"[POSITION] total_cost={total_cost}")
    if total_cost <= 0:
        print("[POSITION] 总持仓成本<=0，跳过仓位写入。")
        return

    # 2) 写回仓位（0~1）
    updated = 0
    for page_id, c in costs:
        position = c / total_cost
        try:
            notion_request("PATCH", f"/pages/{page_id}", {
                "properties": {WEIGHT_FIELD: {"number": position}}
            })
            updated += 1
        except Exception as e:
            print(f"[ERR] POSITION {page_id}: {e}")
    print(f"[POSITION] updated={updated}/{len(costs)}")


# ================== main：link / market / position / all ==================
def main():
    if not NOTION_TOKEN:
        raise SystemExit("请设置 NOTION_TOKEN")
    if not HOLDINGS_DB_ID:
        raise SystemExit("请设置 HOLDINGS_DB_ID（或 NOTION_DATABASE_ID）")

    mode = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    today_only = ("--today-only" in sys.argv[2:] or "-t" in sys.argv[2:])

    if mode in ("link", "all"):
        if not TRADES_DB_ID:
            print("[WARN] 未设置 TRADES_DB_ID，跳过交易处理（link）")
        else:
            process_new_trades(today_only=today_only)
            sweep_all_holdings_and_fix_dashboard()   # 补齐数据看板 Relation
    if mode in ("market", "all"):
        update_holdings_market()
    if mode in ("position", "all"):
        update_positions_by_cost()


if __name__ == "__main__":
    main()