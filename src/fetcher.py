import requests
import time
import logging
import json
from typing import Optional, List, Dict
from src.compress import compress_run
from src.db import insert_run, init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_events(api_key: str, project_id: str, limit: int = 1000, offset: int = 0, retries: int = 3) -> List[Dict]:
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

    for attempt in range(1, retries + 1):
        try:
            logging.info(f"正在请求 offset={offset}, limit={limit} (尝试 {attempt}/{retries})")
            response = requests.get(url, headers=headers, params=params, timeout=60)
            response.encoding = 'utf-8'
            response.raise_for_status()
            data = response.json()
            results = data.get('results', [])
            logging.info(f"获取到 {len(results)} 条事件")
            return results
        except requests.exceptions.Timeout:
            logging.warning(f"请求超时 (尝试 {attempt}/{retries})")
            if attempt == retries:
                raise
            wait_time = 2 ** (attempt - 1)
            logging.info(f"等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)
        except requests.exceptions.RequestException as e:
            logging.warning(f"请求异常: {e} (尝试 {attempt}/{retries})")
            if attempt == retries:
                raise
            wait_time = 2 ** (attempt - 1)
            logging.info(f"等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

    return []

def extract_raw_run_data(event: Dict) -> Optional[Dict]:
    """
    从 PostHog 事件中提取原始运行数据。
    顶层字段从 properties 获取，run_history 和 private_contributions 从 properties.payload 获取。
    """
    properties = event.get('properties', {})
    if not properties:
        logging.warning("事件缺少 properties 字段")
        return None

    # 获取 payload
    payload = properties.get('payload')
    if payload is None:
        logging.warning("事件缺少 payload 字段")
        return None

    # 如果 payload 是字符串，尝试解析为 dict
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except:
            logging.warning("payload 字符串不是有效 JSON")
            return None

    if not isinstance(payload, dict):
        logging.warning(f"payload 不是 dict，类型: {type(payload)}")
        return None

    # 从 payload 中提取 run_history 和 private_contributions
    run_history = payload.get('run_history')
    if run_history is None:
        logging.warning("payload 中缺少 run_history")
        return None

    private_contributions = payload.get('private_contributions', {})
    if isinstance(private_contributions, str):
        try:
            private_contributions = json.loads(private_contributions)
        except:
            private_contributions = {}

    # 构建 raw_data，顶层字段从 properties 取，applicant_payload 包装 run_history
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
        'applicant_payload': {'run_history': run_history},
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
        try:
            events = fetch_events(api_key, project_id, limit=limit, offset=offset)
        except Exception as e:
            logging.error(f"获取事件失败: {e}")
            break

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