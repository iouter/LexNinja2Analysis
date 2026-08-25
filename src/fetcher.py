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

def extract_raw_run_data(event: Dict, debug: bool = False) -> Optional[Dict]:
    """
    从 PostHog 事件中提取原始运行数据。
    优先从 properties.payload 中读取所有字段，若不存在则从 properties 顶层读取。
    """
    properties = event.get('properties', {})
    if not properties:
        logging.warning("事件缺少 properties 字段")
        return None

    # ---- 获取 payload ----
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

    # ---- 调试输出 ----
    if debug:
        logging.info("=" * 70)
        logging.info("🔍 调试模式：打印 payload 的键和部分内容")
        logging.info(f"payload keys: {list(payload.keys())}")
        try:
            payload_str = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            if len(payload_str) > 3000:
                logging.info(f"payload (截断):\n{payload_str[:3000]}...")
            else:
                logging.info(f"payload:\n{payload_str}")
        except:
            pass
        logging.info("=" * 70)

    # ---- 从 payload 中提取字段，若缺失则从 properties 顶层补充 ----
    raw_data = {
        'game_version': payload.get('game_version') or properties.get('game_version'),
        'run_game_mode': payload.get('run_game_mode') or properties.get('run_game_mode'),
        'run_ascension': payload.get('run_ascension') or properties.get('run_ascension'),
        'run_character_ids': payload.get('run_character_ids') or properties.get('run_character_ids'),
        'run_player_count': payload.get('run_player_count') or properties.get('run_player_count'),
        'run_floor_reached': payload.get('run_floor_reached') or properties.get('run_floor_reached'),
        'run_reload_count': payload.get('run_reload_count') or properties.get('run_reload_count'),
        'run_time_seconds': payload.get('run_time_seconds') or properties.get('run_time_seconds'),
        'is_abandoned': payload.get('is_abandoned', False) or properties.get('is_abandoned', False),
        'is_victory': payload.get('is_victory', False) or properties.get('is_victory', False),
        'applicant_payload': payload.get('applicant_payload'),
        'private_contributions': payload.get('private_contributions', {})
    }

    # ---- 处理 applicant_payload 可能为字符串的情况 ----
    if isinstance(raw_data['applicant_payload'], str):
        try:
            raw_data['applicant_payload'] = json.loads(raw_data['applicant_payload'])
        except:
            logging.warning("applicant_payload 字符串解析失败，将保持原样")
            # 保留原字符串，后续 compress 可能会失败，但由 compress 自身处理

    # ---- 处理 private_contributions 可能为字符串的情况 ----
    if isinstance(raw_data['private_contributions'], str):
        try:
            raw_data['private_contributions'] = json.loads(raw_data['private_contributions'])
        except:
            logging.warning("private_contributions 字符串解析失败，将设为空字典")
            raw_data['private_contributions'] = {}

    # ---- 检查必要字段 ----
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
    debug_printed = False

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

            # 只在第一页的第一条事件打印调试信息
            if offset == 0 and not debug_printed:
                raw_data = extract_raw_run_data(ev, debug=True)
                debug_printed = True
                if raw_data is None:
                    logging.warning("调试数据提取失败，跳过")
                    continue
            else:
                raw_data = extract_raw_run_data(ev, debug=False)

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