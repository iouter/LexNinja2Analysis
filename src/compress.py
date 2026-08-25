import copy
from src.utils import GAME_ITEMS, get_card, is_valid_acts, extract_lexninja2_version

class RunDataCompressor:
    VERSION_RULES = [
        (["3.0.0", "3.0.1", "3.0.2", "3.0.3", "3.0.4", "3.0.5", "3.0.6", "3.0.7", "3.0.8"], "0.107.1", True),
        (["3.0.4-beta"], "0.108.", False),
        (["3.0.5-beta", "3.0.6-beta"], "0.109.", False),
        (["3.0.7-beta"], "0.110.", False),
        (["3.0.8-beta"], "0.111.", False),
    ]

    def __init__(self, raw_data: dict):
        self.raw_data = raw_data
        if self._is_invalid():
            self.compressed_data = None
            return
        self.compressed_data = {}
        self._compress()

    @staticmethod
    def _deep_remove_key(data, target_key: str):
        if isinstance(data, dict):
            for key, value in list(data.items()):
                if key == target_key:
                    del data[key]
                else:
                    RunDataCompressor._deep_remove_key(value, target_key)
        elif isinstance(data, list):
            for item in data:
                RunDataCompressor._deep_remove_key(item, target_key)

    @staticmethod
    def _is_valid_lexninja2_version(version: str) -> bool:
        import re
        return bool(re.match(r'^(\d+)\.(\d+)\.(\d+)(?:-beta)?$', version))

    @staticmethod
    def _del_dict_keys(d: dict, keys: list[str]):
        for key in keys:
            if key in d:
                del d[key]

    def _is_version_match(self) -> bool:
        game_version = self.raw_data.get("game_version", "")
        lexninja2_version = extract_lexninja2_version(self._get_lexninja_context().get("version", ""))
        if not self._is_valid_lexninja2_version(lexninja2_version):
            return False
        for versions, target, exact_match in self.VERSION_RULES:
            if lexninja2_version in versions:
                if exact_match:
                    return game_version == target
                else:
                    return game_version.startswith(target)
        return True

    def _compress(self):
        run_history = self._get_run_history()
        self._copy_raw_field("game_version")
        self._extract_lexninja2_field("version", extract_lexninja2_version)
        self._extract_lexninja2_field("is_challenge_mode")
        self._copy_raw_field("run_game_mode")
        self._copy_raw_field("run_ascension")
        self._copy_raw_field("run_character_ids")
        self._copy_raw_field("run_player_count")
        self._copy_raw_field("run_floor_reached")
        self._copy_raw_field("run_reload_count")
        self._copy_raw_field("run_time_seconds")
        self.compressed_data["is_multiplayer"] = self.raw_data["run_player_count"] > 1
        self._copy_raw_field("is_abandoned")
        self._copy_raw_field("is_victory")
        self.compressed_data["modifiers"] = run_history["modifiers"]
        self.compressed_data["acts"] = [act["id"] for act in run_history["acts"]]

        players_raw = run_history["players"]
        players_by_id = {}
        for player in players_raw:
            if player["character_id"] != "CHARACTER.LEX_NINJA2_CHARACTER_LEX_NINJA2":
                continue
            processed_player = copy.copy(player)
            self._del_dict_keys(processed_player, ["discovered_cards", "discovered_enemies", "relic_grab_bag", "rng", "unlock_state"])
            players_by_id[player["net_id"]] = processed_player
        self.compressed_data["players"] = players_by_id

        history_batch = run_history["map_point_history"][0]
        processed_histories = []
        for history_node in history_batch:
            processed_node = copy.copy(history_node)
            stats_raw = processed_node["player_stats"]
            stats_by_id = {}
            for stat_entry in stats_raw:
                stat_player_id = stat_entry["player_id"]
                if stat_player_id not in players_by_id:
                    continue
                stats_by_id[stat_player_id] = stat_entry
            processed_node["player_stats"] = stats_by_id
            processed_histories.append(processed_node)
        self.compressed_data["map_point_history"] = processed_histories

        self._deep_remove_key(self.compressed_data, "save_dict_List[BaseLib.Abstracts.CardModifier+ModifierSave]")

    def _is_invalid(self) -> bool:
        # 先检查是否是 LexNinja2 数据，不是则直接视为无效
        private = self.raw_data.get("private_contributions", {})
        if "LexNinja2" not in private:
            return True

        # 正常检查
        return (
            self._get_lexninja_context()["is_dirty_data"]
            or self.raw_data["run_game_mode"] != "Standard"
            or not self._is_version_match()
        )

    def _copy_raw_field(self, key: str):
        self.compressed_data[key] = self.raw_data[key]

    def _get_lexninja_context(self) -> dict:
        return self.raw_data["private_contributions"]["LexNinja2"]["lex_ninja2_run_context"]

    def _extract_lexninja2_field(self, key: str, transform_func=None):
        value = self._get_lexninja_context()[key]
        if transform_func is not None:
            value = transform_func(value)
        self.compressed_data["lexninja2_" + key] = value

    def _get_run_history(self) -> dict:
        return self.raw_data["applicant_payload"]["run_history"]

def compress_run(raw_data: dict) -> dict | None:
    """包装器：捕获所有异常，失败则返回 None"""
    try:
        compressor = RunDataCompressor(raw_data)
        return compressor.compressed_data
    except Exception as e:
        # 记录日志（使用 logging 或 print）
        import logging
        logging.warning(f"压缩失败，跳过该条数据: {e}")
        return None