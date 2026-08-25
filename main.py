import os
import sys
from src.db import init_db, get_all_compressed_runs, get_run_count
from src.fetcher import fetch_new_runs
from src.aggregation import aggregation
from src.generate_report import write_report
from src.utils import GAME_ITEMS

def main():
    api_key = os.environ.get('POSTHOG_API_KEY')
    project_id = os.environ.get('POSTHOG_PROJECT_ID')
    if not api_key or not project_id:
        print("错误：缺少 POSTHOG_API_KEY 或 POSTHOG_PROJECT_ID 环境变量")
        sys.exit(1)

    db_path = os.environ.get('DB_PATH', 'data.db')
    conn = init_db(db_path)

    # 拉取新数据
    print("开始拉取新对局...")
    new_count = fetch_new_runs(db_path, api_key, project_id, max_fetch=5000)
    print(f"新增 {new_count} 条记录")

    # 读取全部压缩数据
    compressed_list = get_all_compressed_runs(conn)
    total = len(compressed_list)
    print(f"数据库中总记录数: {total}")

    if total == 0:
        print("没有数据，退出")
        conn.close()
        return

    # 聚合
    print("开始聚合...")
    agg_data = aggregation(compressed_list)
    print(f"聚合得到 {len(agg_data)} 条汇总记录")

    # 生成报告
    print("生成 HTML 报告...")
    write_report(agg_data, "report.html")
    print("报告已保存为 report.html")

    conn.close()

if __name__ == "__main__":
    main()