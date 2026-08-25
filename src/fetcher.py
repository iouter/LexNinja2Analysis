import requests
import time
import logging
from typing import Optional, List, Dict
from src.compress import compress_run
from src.db import insert_run, init_db

def fetch_events(api_key: str, project_id: str, limit: int = 1000, offset: int = 0) -> List[Dict]:
    url = f"https://us.posthog.com/api/projects/{project_id}/events/"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Accept-Charset": "utf-8",
    }
    params = {
        "event": "run_history.completed",
        "limit": limit,
        "offset": offset
    }
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.encoding = 'utf-8'
    response.raise_for_status()
    data = response.json()
    return data.get('results', [])

def extract_raw_run_data(event: Dict) -> Optional[Dict]:
    """提取 RunDataCompressor 所需的原始数据结构"""
    properties = event.get('properties', {})
    if 'payload' in properties and isinstance(properties['payload'], dict):
        payload = properties['payload']
        if 'applicant_payload' in payload:
            properties['applicant_payload'] = payload['applicant_payload']
    required = ('game_version', 'run_history', 'private_contributions')
    if not all(k in properties for k in required):
        return None
    return properties

def fetch_new_runs(db_path: str, api_key: str, project_id: str, max_fetch: int = 5000) -> int:
    """
    使用 offset 翻页拉取所有新对局，直到遇到已存在的 event_id 或达到最大拉取数。
    返回新插入的条数。
    """
    conn = init_db(db_path)
    offset = 0
    total_fetched = 0
    new_count = 0
    inserted_this_page = 0

    while total_fetched < max_fetch:
        limit = min(1000, max_fetch - total_fetched)
        events = fetch_events(api_key, project_id, limit=limit, offset=offset)
        if not events:
            break

        inserted_this_page = 0
        for ev in events:
            event_id = ev.get('id')
            raw_data = extract_raw_run_data(ev)
            if raw_data is None:
                continue
            compressed = compress_run(raw_data)
            if compressed is None:
                continue
            inserted = insert_run(conn, event_id, compressed)
            if inserted:
                new_count += 1
                inserted_this_page += 1

        total_fetched += len(events)
        offset += len(events)

        # 如果本页没有新增记录，说明已经拉取到历史数据（之前已经存过的），停止翻页
        if inserted_this_page == 0 and offset > 0:
            logging.info("本页无新数据，已追平历史记录，停止拉取")
            break

        if len(events) < 1000:
            break
        time.sleep(0.5)

    conn.close()
    return new_count