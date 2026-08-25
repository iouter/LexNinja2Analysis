import requests
import time
import logging
import json
from typing import Optional, List, Dict
from src.compress import compress_run
from src.db import insert_run, init_db

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

def extract_raw_run_data(event: Dict, debug: bool = False) -> Optional[Dict]:
    """从 PostHog 事件中提取原始运行数据，适应多种嵌套结构。"""
    properties = event.get('properties', {})
    if not properties:
        logging.warning("事件缺少 properties 字段")
        return None

    # 🔍 调试信息：打印第一条事件的完整结构
    if debug:
        logging.info("=" * 70)
        logging.info("🔍 调试模式：打印第一条事件的 properties 完整内容")
        logging.info("=" * 70)
        # 打印 properties 的 JSON 格式（缩进便于阅读）
        try:
            properties_str = json.dumps(properties, indent=2, ensure_ascii=False, default=str)
            logging.info(f"properties:\n{properties_str}")
        except Exception as e:
            logging.warning(f"无法序列化 properties: {e}")
            logging.info(f"properties keys: {list(properties.keys())}")

        # 特别检查 payload 字段
        if 'payload' in properties:
            payload = properties['payload']
            logging.info(f"payload 类型: {type(payload)}")
            if isinstance(payload, dict):
                logging.info(f"payload keys: {list(payload.keys())}")
                # 如果 payload 是字典，打印其内容
                try:
                    payload_str = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
                    logging.info(f"payload 内容:\n{payload_str}")
                except:
                    pass
            elif isinstance(payload, str):
                logging.info(f"payload 是字符串，长度: {len(payload)}")
                if len(payload) < 2000:
                    logging.info(f"payload 内容: {payload}")
                else:
                    logging.info(f"payload 前500字符: {payload[:500]}...")

        # 特别检查 applicant_payload 字段（可能存在）
        if 'applicant_payload' in properties:
            ap = properties['applicant_payload']
            logging.info(f"applicant_payload 类型: {type(ap)}")
            if isinstance(ap, dict):
                logging.info(f"applicant_payload keys: {list(ap.keys())}")
            elif isinstance(ap, str):
                logging.info(f"applicant_payload 是字符串，长度: {len(ap)}")
                if len(ap) < 2000:
                    logging.info(f"applicant_payload 内容: {ap}")
                else:
                    logging.info(f"applicant_payload 前500字符: {ap[:500]}...")

        # 特别检查 private_contributions 字段
        if 'private_contributions' in properties:
            pc = properties['private_contributions']
            logging.info(f"private_contributions 类型: {type(pc)}")
            if isinstance(pc, dict):
                logging.info(f"private_contributions keys: {list(pc.keys())}")
                try:
                    pc_str = json.dumps(pc, indent=2, ensure_ascii=False, default=str)
                    logging.info(f"private_contributions 内容:\n{pc_str}")
                except:
                    pass
        else:
            logging.warning("properties 中没有 private_contributions 字段")
            logging.info("尝试查找其他可能包含运行数据的字段...")
            # 打印所有可能是数据容器的字段
            for key in properties.keys():
                if 'payload' in key.lower() or 'run' in key.lower() or 'history' in key.lower():
                    logging.info(f"可能相关的字段: {key}, 类型: {type(properties[key])}")

        logging.info("=" * 70)

    # --- 原有的提取逻辑 ---
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
    debug_printed = False

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
                logging.debug("数据提取失败，跳过")
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