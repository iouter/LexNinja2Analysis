import json
from typing import Any, Dict, List
from src.utils import GAME_ITEMS, read_resource_text

def build_localization():
    cards = GAME_ITEMS.get("cards", {})
    relics = GAME_ITEMS.get("relics", {})
    card_names = {cid: info.get("name", cid) for cid, info in cards.items()}
    relic_names = {rid: info.get("name", rid) for rid, info in relics.items()}
    return card_names, relic_names

def generate_html(aggregation_data: List[Dict], card_names: Dict[str, str], relic_names: Dict[str, str]) -> str:
    template = read_resource_text("report_template.html")
    data_json = json.dumps(aggregation_data, ensure_ascii=False)
    card_names_json = json.dumps(card_names, ensure_ascii=False)
    relic_names_json = json.dumps(relic_names, ensure_ascii=False)
    html = template.replace("REPLACE_DATA_JSON", data_json)
    html = html.replace("REPLACE_CARD_NAMES_JSON", card_names_json)
    html = html.replace("REPLACE_RELIC_NAMES_JSON", relic_names_json)
    return html

def write_report(aggregation_data: List[Dict], output_file: str, card_names: Dict[str, str] = None, relic_names: Dict[str, str] = None) -> None:
    if card_names is None or relic_names is None:
        card_names, relic_names = build_localization()
    html = generate_html(aggregation_data, card_names, relic_names)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)