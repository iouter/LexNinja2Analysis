import requests
import time
import logging
from typing import Optional, List, Dict
from src.compress import compress_run
from src.db import insert_run, init_db

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
    logging.info(f"正在请求 offset={offset}, limit={limit}")
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.encoding = 'utf-8'
    response.raise_for_status()
    data = response.json()
    results = data.get('results', [])
    logging.info(f"获取到 {len(results)} 条事件")
    return results

def extract_raw_run_data(event: Dict) -> Optional[Dict]:
    """从 PostHog 事件中提取原始运行数据，适应多种嵌套结构。"""
    properties = event.get('properties', {})
    if not properties:
        logging.warning("事件缺少 properties 字段")
        return None

    # 尝试提取 applicant_payload
    applicant_payload = None
    if 'payload' in properties and isinstance(properties['payload'], dict):
        payload = properties['payload']
        if 'applicant_payload' in payload:
            applicant_payload = payload['applicant_payload']
    if applicant_payload is None and 'applicant_payload' in properties:
        applicant_payload = properties['applicant_payload']
    if isinstance(applicant_payload, str):
        try:
            import json
            applicant_payload = json.loads(applicant_payload)
        except:
            logging.warning("applicant_payload 不是有效 JSON")
            applicant_payload = None
    if applicant_payload is None:
        logging.warning("未找到 applicant_payload")
        return None

    # 提取 private_contributions
    private_contributions = properties.get('private_contributions', {})
    if not private_contributions:
        logging.warning("事件缺少 private_contributions 字段，使用空字典")

    raw_data = {
        'game_version': properties.get('game_version'),
        'run_game_mode': properties.get('run_game_mode'),
        'run_ascension': properties.get('run_ascension'),
        'run_character_ids': properties.get('run_character_ids'),
        'run_player_count': properties.get('run_player_count'),
        'run_floor_reached': properties.get('run_floor_reached'),
        'run_reload_count': properties.get('run_reload_count'),
        'run_time_seconds': properties.get('run_time_seconds'),
        'is_abandoned': properties.get('is_abandoned', False),
        'is_victory': properties.get('is_victory', False),
        'applicant_payload': applicant_payload,
        'private_contributions': private_contributions
    }

    if raw_data['game_version'] is None:
        logging.warning("缺少 game_version，跳过")
        return None

    return raw_data

def fetch_new_runs(db_path: str, api_key: str, project_id: str, max_fetch: int = 5000) -> int:
    conn = init_db(db_path)
    offset = 0
    total_fetched = 0
    new_count = 0
    inserted_this_page = 0

    while total_fetched < max_fetch:
        limit = min(1000, max_fetch - total_fetched)
        events = fetch_events(api_key, project_id, limit=limit, offset=offset)
        if not events:
            logging.info("API 返回空列表，停止拉取")
            break

        inserted_this_page = 0
        for ev in events:
            event_id = ev.get('id')
            if not event_id:
                logging.warning("事件缺少 id，跳过")
                continue

            raw_data = extract_raw_run_data(ev)
            if raw_data is None:
                logging.debug("数据提取失败，跳过")
                continue

            compressed = compress_run(raw_data)
            if compressed is None:
                # compress_run 内部已打印日志，这里不再重复
                continue

            inserted = insert_run(conn, event_id, compressed)
            if inserted:
                new_count += 1
                inserted_this_page += 1

        total_fetched += len(events)
        offset += len(events)

        logging.info(f"本页处理: 事件 {len(events)}，新增 {inserted_this_page}，累计新增 {new_count}")

        if inserted_this_page == 0 and offset > 0:
            logging.info("本页无新数据，已追平历史记录，停止拉取")
            break

        if len(events) < 1000:
            logging.info("已到达最后一页")
            break

        time.sleep(0.5)

    conn.close()
    return new_count