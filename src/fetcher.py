import requests
import time
import logging
import json
from typing import Optional, List, Dict
from src.compress import compress_run
from src.db import insert_run, init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_events(api_key: str, project_id: str, limit: int = 1000, offset: int = 0, retries: int = 3) -> List[Dict]:
    # ... 保持不变（略） ...

def extract_raw_run_data(event: Dict) -> Optional[Dict]:
    """
    模仿 extract_lightweight 的逻辑提取 run_history，
    同时提取 private_contributions。
    """
    properties = event.get('properties', {})
    if not properties:
        logging.warning("事件缺少 properties 字段")
        return None

    # ---- 提取 applicant_payload ----
    payload = None
    if 'payload' in properties:
        payload = properties['payload']
        if isinstance(payload, dict) and 'applicant_payload' in payload:
            payload = payload['applicant_payload']
    elif 'applicant_payload' in properties:
        payload = properties['applicant_payload']

    if not payload:
        logging.warning("未找到 applicant_payload")
        return None

    # 如果 payload 是字符串，解析为 JSON
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except:
            logging.warning("applicant_payload 不是有效 JSON")
            return None

    if not isinstance(payload, dict):
        logging.warning(f"applicant_payload 不是 dict，类型: {type(payload)}")
        return None

    # 从 payload 中获取 run_history
    run_history = payload.get('run_history')
    if run_history is None:
        # 如果 run_history 不存在，尝试将整个 payload 当作 run_history（兼容某些格式）
        run_history = payload

    # ---- 提取 private_contributions ----
    # 从 properties.payload 顶层获取（可能在 payload 中，也可能在 properties 中）
    private_contributions = {}
    # 尝试从 properties.payload 中获取
    if 'payload' in properties and isinstance(properties['payload'], dict):
        private_contributions = properties['payload'].get('private_contributions', {})
    # 如果没找到，再从 properties 顶层获取
    if not private_contributions and 'private_contributions' in properties:
        private_contributions = properties['private_contributions']

    if isinstance(private_contributions, str):
        try:
            private_contributions = json.loads(private_contributions)
        except:
            private_contributions = {}

    # ---- 顶层字段从 properties 读取 ----
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
        'applicant_payload': {'run_history': run_history},  # compress.py 期望 applicant_payload 包含 run_history
        'private_contributions': private_contributions
    }

    if raw_data['game_version'] is None:
        logging.warning("缺少 game_version，跳过")
        return None

    return raw_data

def fetch_new_runs(db_path: str, api_key: str, project_id: str, max_fetch: Optional[int] = None) -> int:
    conn = init_db(db_path)
    offset = 0
    total_fetched = 0
    new_count = 0
    printed_first = False

    while max_fetch is None or total_fetched < max_fetch:
        limit = 1000
        if max_fetch is not None:
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

            # 调试打印（第一条）
            if not printed_first:
                print("=" * 80)
                print("🔍 调试：打印第一条 raw_data 完整内容")
                try:
                    print(json.dumps(raw_data, indent=2, ensure_ascii=False, default=str))
                except Exception as e:
                    print(f"打印失败: {e}")
                    print(f"raw_data keys: {list(raw_data.keys())}")
                print("=" * 80)
                printed_first = True

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