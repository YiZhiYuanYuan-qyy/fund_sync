#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Notion Funds Pipeline

1) 交易流水 → 自动关联/创建持仓、补基金名称
2) 持仓行情更新（fundgz 优先，东财 F10 兜底）
3) 仓位写入（持仓成本 / 全部成本）
"""

import os
import re
import sys
import time
import json
from typing import Optional
from datetime import datetime, timezone, timedelta

import requests


# ================== 环境变量 ==================
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
HOLDINGS_DB_ID = (
    os.getenv("HOLDINGS_DB_ID")
    or os.getenv("NOTION_DATABASE_ID")
    or ""
).strip()
TRADES_DB_ID = os.getenv("TRADES_DB_ID", "").strip()


# ============== 字段名（按你的库实际改） ==============
# 交易流水表
TRADE_CODE_PROP = "Code"
TRADE_NAME_PROP = "基金名称"             # title 或 rich_text
TRADE_RELATION_PROP = "Fund 持仓"        # Relation → 持仓表
TRADE_HOLDING_DAYS_PROP = "持仓时间"     # Formula (number)
TRADE_ESTIMATED_FEE_PROP = "预估卖出费率" # Number
TRADE_QUANTITY_PROP = "持仓份额"         # Number
TRADE_ESTIMATED_NAV_PROP = "估算净值"    # Number (从持仓表获取)
TRADE_AMOUNT_PROP = "交易金额"           # Number
TRADE_HOLDING_PROFIT_PROP = "持有收益"   # Number

# 持仓表
HOLDING_TITLE_PROP = "基金名称"          # Title
HOLDING_CODE_PROP = "Code"              # Rich text

# 行情字段（持仓表）
FIELD = {
    "title": HOLDING_TITLE_PROP,
    "code": HOLDING_CODE_PROP,
    "dwjz": "单位净值",
    "gsz": "估算净值",
    "gszzl": "估算涨跌幅",
    "gztime": "估值时间",
    "source": "来源",
    "updated": "更新于",
}

# 仓位计算字段（持仓表）
COST_FIELD = "持仓成本"     # Number / Formula / Rollup(number)
WEIGHT_FIELD = "仓位"       # Number（建议 Notion 设置为百分比显示）

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
EM_F10_API = (
    "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}"
    "&pageIndex=1&pageSize=1&startDate=&endDate="
)

# ================ 工具函数 ================
SG_TZ = timezone(timedelta(hours=8))  # Asia/Singapore


def today_iso_date() -> str:
    return datetime.now(SG_TZ).date().isoformat()


def zpad6(s: str) -> str:
    t = "".join(ch for ch in str(s or "").strip() if ch.isdigit())
    return t.zfill(6) if t else ""


def notion_request(method: str, path: str, payload=None) -> dict:
    url = f"https://api.notion.com/v1{path}"
    data = json.dumps(payload) if payload is not None else None
    resp = requests.request(
        method, url, headers=NOTION_HEADERS, data=data, timeout=25
    )
    if not resp.ok:
        raise RuntimeError(
            f"Notion {method} {path} failed: "
            f"{resp.status_code} {resp.text}"
        )
    return resp.json()


def get_prop_text(prop: dict) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t == "rich_text":
        arr = prop.get("rich_text") or []
        return "".join((x.get("plain_text") or "") for x in arr).strip()
    if t == "title":
        arr = prop.get("title") or []
        return "".join((x.get("plain_text") or "") for x in arr).strip()
    if t == "number":
        v = prop.get("number")
        return "" if v is None else str(v)
    return ""


def has_relation(prop: dict) -> bool:
    if not prop or prop.get("type") != "relation":
        return False
    return bool(prop.get("relation") or [])


def normalize_num_str(s: str) -> str:
    return (s or "").replace("－", "-").replace("%", "").strip()


def to_float_safe(x) -> Optional[float]:
    try:
        return float(normalize_num_str(str(x)))
    except Exception:
        return None


def is_iso_like(s: str) -> bool:
    return bool(
        re.match(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$", s or "")
    )


def get_page_properties(page_id: str) -> dict:
    return notion_request("GET", f"/pages/{page_id}")


# ================ fundgz（名称/行情） ================
def http_get_utf8(url: str, timeout: float = 8.0) -> str:
    resp = requests.get(
        url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout
    )
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


def fetch_fund_name_from_fundgz(code6: str) -> Optional[str]:
    for base in (FUNDGZ_HTTP, FUNDGZ_HTTPS):
        try:
            raw = http_get_utf8(
                base.format(code=code6) + f"?rt={int(time.time())}"
            )
            m = re.search(r"\{.*\}", raw, flags=re.S)
            if not m:
                continue
            js = m.group(0)
            mm = re.search(r'"name"\s*:\s*"([^"]+)"', js)
            if mm:
                return mm.group(1).strip()
        except Exception:
            time.sleep(0.2)
            continue
    return None


def fetch_fundgz(code6: str, timeout: float = 8.0) -> dict:
    for base in (FUNDGZ_HTTP, FUNDGZ_HTTPS):
        try:
            raw = http_get_utf8(
                base.format(code=code6) + f"?rt={int(time.time())}", timeout
            )
            m = re.search(r"\{.*\}", raw, flags=re.S)
            if not m:
                continue
            js = m.group(0)

            def jget(k: str) -> str:
                mm = re.search(rf'"{k}"\s*:\s*"([^"]*)"', js)
                return mm.group(1) if mm else ""

            name = jget("name")
            dwjz = jget("dwjz")
            gsz = jget("gsz")
            gszzl = normalize_num_str(jget("gszzl"))
            gz = jget("gztime")
            if gz and not is_iso_like(gz):
                gz = ""
            return {
                "name": name,
                "dwjz": dwjz,
                "gsz": gsz,
                "gszzl": gszzl,
                "gztime": gz,
                "source": "天天基金",
            }
        except Exception:
            time.sleep(0.3)
            continue
    return {}


# ================ 东方财富 F10（兜底） ================
def fetch_em_last_nav_and_chg(code6: str, timeout: float = 8.0) -> dict:
    try:
        url = EM_F10_API.format(code=code6)
        resp = requests.get(url, headers=UA_HEADERS, timeout=timeout)
        resp.raise_for_status()
        js = resp.json()
        rows = (js.get("Data") or {}).get("LSJZList") or []
        if not rows:
            return {}
        row = rows[0]
        return {
            "dwjz": row.get("DWJZ"),
            "gszzl": row.get("JZZZL"),
            "gztime": row.get("FSRQ"),
            "source": "东方财富(历史净值)",
        }
    except Exception:
        return {}


# ================ 持仓 查找/创建/标题补全 ================
def find_holding_by_code(code6: str) -> Optional[str]:
    payload = {
        "filter": {
            "property": HOLDING_CODE_PROP,
            "rich_text": {"equals": code6},
        },
        "page_size": 1,
    }
    data = notion_request("POST", f"/databases/{HOLDINGS_DB_ID}/query", payload)
    res = data.get("results") or []
    return res[0]["id"] if res else None


def create_holding(code6: str, name: str) -> str:
    props = {
        HOLDING_TITLE_PROP: {"title": [{"text": {"content": name or code6}}]},
        HOLDING_CODE_PROP: {"rich_text": [{"text": {"content": code6}}]},
    }
    data = notion_request(
        "POST",
        "/pages",
        {"parent": {"database_id": HOLDINGS_DB_ID}, "properties": props},
    )
    return data["id"]


def get_holding_title(holding_page_id: str) -> str:
    props = get_page_properties(holding_page_id).get("properties") or {}
    return get_prop_text(props.get(HOLDING_TITLE_PROP)) or ""


def update_holding_title_if_needed(
    holding_page_id: str, code6: str, fetched_name: Optional[str] = None
) -> None:
    cur = get_holding_title(holding_page_id)
    need = (not cur) or cur.isdigit() or (cur == code6)
    if not need:
        return
    name = fetched_name or fetch_fund_name_from_fundgz(code6) or code6
    notion_request(
        "PATCH",
        f"/pages/{holding_page_id}",
        {"properties": {HOLDING_TITLE_PROP: {
            "title": [{"text": {"content": name}}]
        }}},
    )


# ================ 交易：Relation / 名称写入 ================
def set_trade_relation(trade_page_id: str, holding_page_id: str) -> None:
    notion_request(
        "PATCH",
        f"/pages/{trade_page_id}",
        {"properties": {TRADE_RELATION_PROP: {
            "relation": [{"id": holding_page_id}]
        }}},
    )


def set_trade_name(trade_page_id: str, name: str) -> None:
    if not name:
        return
    pg = get_page_properties(trade_page_id)
    p = (pg.get("properties") or {}).get(TRADE_NAME_PROP)
    if not p:
        return
    t = p.get("type")
    if t == "title":
        payload = {TRADE_NAME_PROP: {"title": [{"text": {"content": name}}]}}
    elif t == "rich_text":
        payload = {
            TRADE_NAME_PROP: {"rich_text": [{"text": {"content": name}}]}
        }
    else:
        return
    notion_request("PATCH", f"/pages/{trade_page_id}", {"properties": payload})



def calculate_sell_fee_rate(holding_days: float) -> float:
    """根据持仓时间计算卖出费率"""
    if holding_days < 0:
        return 0.0
    elif holding_days < 7:
        return 0.015  # 1.5%
    elif holding_days < 30:
        return 0.005  # 0.5%
    else:
        return 0.0    # 0%


def get_estimated_nav_from_holding(holding_page_id: str) -> float:
    """从持仓表获取估算净值"""
    try:
        props = get_page_properties(holding_page_id).get("properties") or {}
        # 优先使用估算净值，如果没有则使用单位净值
        estimated_nav = prop_number_value(props.get(FIELD["gsz"]))
        if estimated_nav is None:
            estimated_nav = prop_number_value(props.get(FIELD["dwjz"]))
        return estimated_nav or 0.0
    except Exception:
        return 0.0


def calculate_estimated_sell_fee(trade_page_id: str, holding_page_id: str) -> None:
    """计算预估卖出费率并更新到交易记录"""
    try:
        trade_props = get_page_properties(trade_page_id).get("properties") or {}
        
        # 获取持仓时间（Formula 字段）
        holding_days_prop = trade_props.get(TRADE_HOLDING_DAYS_PROP)
        if not holding_days_prop or holding_days_prop.get("type") != "formula":
            print(f"[WARN] 交易 {trade_page_id} 缺少持仓时间字段")
            return
            
        holding_days = prop_number_value(holding_days_prop)
        if holding_days is None:
            print(f"[WARN] 交易 {trade_page_id} 持仓时间计算失败")
            return
            
        # 获取持仓份额
        quantity_prop = trade_props.get(TRADE_QUANTITY_PROP)
        if not quantity_prop:
            print(f"[WARN] 交易 {trade_page_id} 缺少持仓份额字段")
            return
            
        quantity = prop_number_value(quantity_prop)
        if quantity is None or quantity <= 0:
            print(f"[WARN] 交易 {trade_page_id} 持仓份额无效: {quantity}")
            return
            
        # 获取估算净值
        estimated_nav = get_estimated_nav_from_holding(holding_page_id)
        if estimated_nav <= 0:
            print(f"[WARN] 持仓 {holding_page_id} 估算净值无效: {estimated_nav}")
            return
            
        # 计算卖出费率
        sell_fee_rate = calculate_sell_fee_rate(holding_days)
        
        # 计算预估卖出费率
        estimated_sell_fee = sell_fee_rate * quantity * estimated_nav
        
        # 更新交易记录
        notion_request(
            "PATCH",
            f"/pages/{trade_page_id}",
            {"properties": {TRADE_ESTIMATED_FEE_PROP: {"number": estimated_sell_fee}}}
        )
        
        print(f"[FEE] 交易 {trade_page_id} 预估卖出费率: {estimated_sell_fee:.2f} "
              f"(费率:{sell_fee_rate*100:.1f}%, 份额:{quantity}, 净值:{estimated_nav:.4f})")
              
    except Exception as exc:
        print(f"[ERR] 计算预估卖出费率失败 {trade_page_id}: {exc}")


def calculate_holding_profit(trade_page_id: str, holding_page_id: str) -> None:
    """计算持有收益并更新到交易记录"""
    try:
        trade_props = get_page_properties(trade_page_id).get("properties") or {}
        
        # 获取持仓份额
        quantity_prop = trade_props.get(TRADE_QUANTITY_PROP)
        if not quantity_prop:
            print(f"[WARN] 交易 {trade_page_id} 缺少持仓份额字段")
            return
            
        quantity = prop_number_value(quantity_prop)
        if quantity is None or quantity <= 0:
            print(f"[WARN] 交易 {trade_page_id} 持仓份额无效: {quantity}")
            return
            
        # 获取交易金额
        amount_prop = trade_props.get(TRADE_AMOUNT_PROP)
        if not amount_prop:
            print(f"[WARN] 交易 {trade_page_id} 缺少交易金额字段")
            return
            
        trade_amount = prop_number_value(amount_prop)
        if trade_amount is None:
            print(f"[WARN] 交易 {trade_page_id} 交易金额无效: {trade_amount}")
            return
            
        # 获取估算净值
        estimated_nav = get_estimated_nav_from_holding(holding_page_id)
        if estimated_nav <= 0:
            print(f"[WARN] 持仓 {holding_page_id} 估算净值无效: {estimated_nav}")
            return
            
        # 计算持有收益 = 持仓份额 × 估算净值 - 交易金额
        holding_profit = (quantity * estimated_nav) - trade_amount
        
        # 更新交易记录
        notion_request(
            "PATCH",
            f"/pages/{trade_page_id}",
            {"properties": {TRADE_HOLDING_PROFIT_PROP: {"number": holding_profit}}}
        )
        
        print(f"[PROFIT] 交易 {trade_page_id} 持有收益: {holding_profit:.2f} "
              f"(份额:{quantity}, 净值:{estimated_nav:.4f}, 金额:{trade_amount:.2f})")
              
    except Exception as exc:
        print(f"[ERR] 计算持有收益失败 {trade_page_id}: {exc}")


def update_all_trades_estimated_fees() -> None:
    """更新所有交易记录的预估卖出费率和持有收益"""
    cursor = None
    total = updated = failed = 0
    
    while True:
        payload = {"page_size": 50}
        if cursor:
            payload["start_cursor"] = cursor
            
        # 查找所有有持仓关联的交易记录
        flt = {
            "and": [
                {"property": TRADE_RELATION_PROP, "relation": {"is_not_empty": True}},
                {"property": TRADE_QUANTITY_PROP, "number": {"greater_than": 0}},
            ]
        }
        payload["filter"] = flt
        
        data = notion_request("POST", f"/databases/{TRADES_DB_ID}/query", payload)
        for pg in data.get("results") or []:
            total += 1
            trade_id = pg["id"]
            props = pg.get("properties") or {}
            
            # 获取持仓关联
            relation_prop = props.get(TRADE_RELATION_PROP)
            if not relation_prop or relation_prop.get("type") != "relation":
                continue
                
            relations = relation_prop.get("relation") or []
            if not relations:
                continue
                
            holding_id = relations[0]["id"]
            
            # 计算预估卖出费率和持有收益
            try:
                calculate_estimated_sell_fee(trade_id, holding_id)
                calculate_holding_profit(trade_id, holding_id)
                updated += 1
            except Exception as exc:
                print(f"[ERR] 更新交易数据失败 {trade_id}: {exc}")
                failed += 1
                
        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break
            
    print(f"TRADES UPDATE Done. total={total}, updated={updated}, failed={failed}")


# ================ 交易处理：建立/补齐关系与名称（支持--today-only） ================
def process_new_trades(today_only: bool = False) -> None:
    cursor = None
    processed = created = linked = named = 0

    while True:
        payload = {"page_size": 50}
        if cursor:
            payload["start_cursor"] = cursor

        flt = {
            "and": [
                {"property": TRADE_CODE_PROP, "rich_text": {"is_not_empty": True}},
                {"property": TRADE_RELATION_PROP, "relation": {"is_empty": True}},
            ]
        }
        if today_only:
            flt["and"].append({
                "timestamp": "created_time",
                "created_time": {"on_or_after": today_iso_date()},
            })
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
                fetched_name = (
                    get_holding_title(holding_id)
                    or fetch_fund_name_from_fundgz(code6)
                    or code6
                )
            set_trade_name(trade_id, fetched_name)
            named += 1
            
            # 计算预估卖出费率和持有收益
            calculate_estimated_sell_fee(trade_id, holding_id)
            calculate_holding_profit(trade_id, holding_id)

            print(
                f"[OK] trade {trade_id} -> holding {holding_id} "
                f"(code={code6}, name={fetched_name})"
            )

        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break

    print(
        "TRADES Done. processed={p}, created_holdings={c}, "
        "linked={l}, named={n}, fees_and_profits_calculated".format(
            p=processed, c=created, l=linked, n=named
        )
    )


# ================ 行情更新（持仓表） ================
def list_holdings_pages() -> list:
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


def update_holdings_market() -> None:
    pages = list_holdings_pages()
    total = ok = fail = 0
    for pg in pages:
        props = pg.get("properties") or {}
        code_raw = (
            get_prop_text(props.get(FIELD["code"]))
            or get_prop_text(props.get(FIELD["title"]))
        )
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
                    "source": em.get("source"),
                }
        if not (info.get("dwjz") or info.get("gszzl")):
            info = {"source": "失败"}

        name_existing = get_prop_text(props.get(FIELD["title"]))
        name = (info.get("name") or name_existing or code6).strip()
        try:
            notion_request(
                "PATCH",
                f"/pages/{pg['id']}",
                {"properties": build_market_props(code6, name, info)},
            )
            print(
                f"[MARKET] {code6} {name} ｜source={info.get('source')} "
                f"｜chg={info.get('gszzl')}"
            )
            ok += 1
        except Exception as exc:
            print(f"[ERR] MARKET {code6}: {exc}")
            fail += 1

    print(f"MARKET Done. updated={ok}, failed={fail}, total={total}")


# ================ 仓位计算（基于持仓成本） ================
def prop_number_value(prop: dict) -> Optional[float]:
    if not prop:
        return None
    t = prop.get("type")
    if t == "number":
        return prop.get("number")
    if t == "formula":
        f = prop.get("formula") or {}
        if f.get("type") == "number":
            return f.get("number")
    if t == "rollup":
        r = prop.get("rollup") or {}
        if r.get("type") == "number":
            return r.get("number")
    return None


def update_positions_by_cost() -> None:
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
            notion_request(
                "PATCH",
                f"/pages/{page_id}",
                {"properties": {WEIGHT_FIELD: {"number": position}}},
            )
            updated += 1
        except Exception as exc:
            print(f"[ERR] POSITION {page_id}: {exc}")
    print(f"[POSITION] updated={updated}/{len(costs)}")


# ================== main：link / market / position / all ==================
def main() -> None:
    if not NOTION_TOKEN:
        raise SystemExit("请设置 NOTION_TOKEN")
    if not HOLDINGS_DB_ID:
        raise SystemExit("请设置 HOLDINGS_DB_ID（或 NOTION_DATABASE_ID）")

    mode = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    today_only = ("--today-only" in sys.argv[2:]) or ("-t" in sys.argv[2:])

    if mode in ("link", "all"):
        if not TRADES_DB_ID:
            print("[WARN] 未设置 TRADES_DB_ID，跳过交易处理（link）")
        else:
            process_new_trades(today_only=today_only)
    if mode in ("market", "all"):
        update_holdings_market()
    if mode in ("position", "all"):
        update_positions_by_cost()
    # 所有模式都包含费率计算
    if TRADES_DB_ID:
        update_all_trades_estimated_fees()
    else:
        print("[WARN] 未设置 TRADES_DB_ID，跳过费率计算")


if __name__ == "__main__":
    main()
    