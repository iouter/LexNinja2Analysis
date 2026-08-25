import os
import sys
import logging
from src.db import init_db, get_all_compressed_runs, get_run_count
from src.fetcher import fetch_new_runs
from src.aggregation import aggregation
from src.generate_report import write_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    api_key = os.environ.get('POSTHOG_API_KEY')
    project_id = os.environ.get('POSTHOG_PROJECT_ID')
    if not api_key or not project_id:
        logging.error("缺少 POSTHOG_API_KEY 或 POSTHOG_PROJECT_ID 环境变量")
        sys.exit(1)

    db_path = os.environ.get('DB_PATH', 'data.db')
    logging.info(f"数据库路径: {db_path}")

    logging.info("开始拉取新对局...")
    # 不设上限，拉取所有新数据
    new_count = fetch_new_runs(db_path, api_key, project_id, max_fetch=None)
    logging.info(f"新增 {new_count} 条记录")

    conn = init_db(db_path)
    total = get_run_count(conn)
    logging.info(f"数据库中总记录数: {total}")

    if total == 0:
        logging.warning("没有数据，退出")
        conn.close()
        return

    compressed_list = get_all_compressed_runs(conn)
    logging.info(f"成功读取 {len(compressed_list)} 条压缩数据")

    logging.info("开始聚合...")
    agg_data = aggregation(compressed_list)
    logging.info(f"聚合得到 {len(agg_data)} 条汇总记录")

    logging.info("生成 HTML 报告...")
    write_report(agg_data, "report.html")
    logging.info("报告已保存为 report.html")

    conn.close()

if __name__ == "__main__":
    main()