from pathlib import Path
import json
import re

BASE_DIR = Path(__file__).parent.parent
RESOURCE_DIR = BASE_DIR / "resources"

def get_resource_path(filename: str) -> Path:
    file_path = RESOURCE_DIR / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Resource file not found: {file_path}")
    return file_path

def read_resource_text(filename: str, encoding: str = "utf-8") -> str:
    return get_resource_path(filename).read_text(encoding=encoding)

def read_resource_json(filename: str, encoding: str = "utf-8") -> dict | list:
    with open(get_resource_path(filename), 'r', encoding=encoding) as f:
        return json.load(f)

GAME_ITEMS = read_resource_json("game_items.json")

def get_card(id: str, upgrades: int = 0, need_lexninja_card: bool = True) -> dict | None:
    cards: dict = GAME_ITEMS["cards"]
    if id.startswith("CARD."):
        id = id.replace("CARD.", "", 1)
    if upgrades != 0:
        id += "_upgrades_" + str(upgrades)
    result = cards.get(id)
    if result is None:
        return None
    if need_lexninja_card and result.get("mod") != "LexNinja2":
        return None
    return result

def is_valid_acts(acts: list[str]) -> bool:
    return (
        len(acts) == 3
        and acts[0] in ("ACT.OVERGROWTH", "ACT.UNDERDOCKS")
        and acts[1] == "ACT.HIVE"
        and acts[2] == "ACT.GLORY"
    )

def extract_lexninja2_version(version_str: str) -> str:
    base = version_str.split("+")[0]
    if '-beta-0' in base:
        return base.split('-beta')[0] + '-beta'
    return base