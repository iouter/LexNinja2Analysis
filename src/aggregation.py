from src.utils import GAME_ITEMS, get_card, is_valid_acts
from typing import Any

def aggregation(compressed_data: list[dict]) -> list[dict]:
    aggregation_list = []
    for data in compressed_data:
        aggregation_data: dict[str, Any] = {}
        # ---- 基本信息 ----
        aggregation_data["game_version"] = data["game_version"]
        aggregation_data["lexninja2_version"] = data["lexninja2_version"]
        aggregation_data["lexninja2_is_challenge_mode"] = data["lexninja2_is_challenge_mode"]
        aggregation_data["run_ascension"] = data["run_ascension"]
        aggregation_data["run_player_count"] = data["run_player_count"]
        aggregation_data["run_lexninja_count"] = data["run_character_ids"].count("CHARACTER.LEX_NINJA2_CHARACTER_LEX_NINJA2")
        aggregation_data["run_floor_reached"] = data["run_floor_reached"]
        aggregation_data["run_reload_count"] = data["run_reload_count"]
        aggregation_data["run_time_seconds"] = data["run_time_seconds"]
        aggregation_data["is_multiplayer"] = data["is_multiplayer"]
        aggregation_data["is_victory"] = data["is_victory"]

        # ---- 模组判定 ----
        acts: list = data["acts"]
        modifiers: list = data["modifiers"]
        aggregation_data["is_possible_modded"] = is_valid_acts(acts) and len(modifiers) == 0

        # ---- 统计容器 ----
        stats: dict[str, set[str] | int] = {}
        deck_counts: list[int] = []
        max_hp_list: list[int] = []
        relics_counts: list[int] = []

        seq_stats: dict[str, list[int]] = {}
        player_upgrade_counters: dict[str, int] = {}
        player_remove_counters: dict[str, int] = {}

        players = data["players"]
        for net_id, player in players.items():
            deck = player["deck"]
            deck_counts.append(len(deck))
            for card in deck:
                card_id = card["id"]
                if get_card(card_id) is None:
                    continue
                key = card_id.replace("CARD.", "card.", 1) + ".deck"
                stats.setdefault(key, set()).add(net_id)
            max_hp_list.append(player["max_hp"])
            relics = player["relics"]
            relics_counts.append(len(relics))
            for relic in relics:
                relic_id = relic["id"]
                key = relic_id.replace("RELIC.", "relic.")
                stats.setdefault(key, set()).add(net_id)

        history = data["map_point_history"]
        for map_point in history:
            if "player_stats" not in map_point:
                continue
            for net_id, player_stat in map_point["player_stats"].items():
                if net_id not in player_upgrade_counters:
                    player_upgrade_counters[net_id] = 0
                if net_id not in player_remove_counters:
                    player_remove_counters[net_id] = 0

                if "card_choices" in player_stat:
                    for choice in player_stat["card_choices"]:
                        card_id = choice["card"]["id"]
                        if get_card(card_id) is None:
                            continue
                        base_key = card_id.replace("CARD.", "card.", 1)
                        appear_key = base_key + ".appear"
                        stats[appear_key] = stats.get(appear_key, 0) + 1
                        if choice["was_picked"]:
                            pick_key = base_key + ".pick"
                            stats[pick_key] = stats.get(pick_key, 0) + 1

                if "upgraded_cards" in player_stat:
                    for card_id in player_stat["upgraded_cards"]:
                        if get_card(card_id) is None:
                            continue
                        player_upgrade_counters[net_id] += 1
                        current_seq = player_upgrade_counters[net_id]
                        base_key = card_id.replace("CARD.", "card.", 1)
                        upgrade_key = base_key + ".upgrade"
                        stats[upgrade_key] = stats.get(upgrade_key, 0) + 1
                        seq_key = base_key + ".upgrade_seq"
                        seq_stats.setdefault(seq_key, []).append(current_seq)

                if "ancient_choice" in player_stat:
                    for option in player_stat["ancient_choice"]:
                        relic_key = option.get("TextKey")
                        if not relic_key:
                            continue
                        base_key = "relic." + relic_key
                        appear_key = base_key + ".appear"
                        stats[appear_key] = stats.get(appear_key, 0) + 1
                        if option.get("was_chosen", False):
                            pick_key = base_key + ".pick"
                            stats[pick_key] = stats.get(pick_key, 0) + 1

                if "relic_choices" in player_stat:
                    for option in player_stat["relic_choices"]:
                        choice_str = option.get("choice", "")
                        if not choice_str.startswith("RELIC."):
                            continue
                        relic_id = choice_str.replace("RELIC.", "")
                        base_key = "relic." + relic_id
                        appear_key = base_key + ".appear"
                        stats[appear_key] = stats.get(appear_key, 0) + 1
                        if option.get("was_picked", False):
                            pick_key = base_key + ".pick"
                            stats[pick_key] = stats.get(pick_key, 0) + 1

        final_stats: dict[str, int] = {}
        for key, value in stats.items():
            if isinstance(value, set):
                final_stats[key] = len(value)
            else:
                final_stats[key] = value

        cards_dict: dict[str, dict[str, Any]] = {}
        for key, value in final_stats.items():
            if key.startswith("card."):
                parts = key.split('.', 2)
                if len(parts) == 3:
                    card_id = parts[1]
                    stat_type = parts[2]
                    cards_dict.setdefault(card_id, {})[stat_type] = value
        for key, value in seq_stats.items():
            if key.startswith("card."):
                parts = key.split('.', 2)
                if len(parts) == 3:
                    card_id = parts[1]
                    stat_type = parts[2]
                    cards_dict.setdefault(card_id, {})[stat_type] = value

        relics_dict: dict[str, dict[str, Any]] = {}
        for key, value in final_stats.items():
            if key.startswith("relic."):
                suffix = key.replace("relic.", "")
                if '.' in suffix:
                    relic_id, stat_type = suffix.split('.', 1)
                else:
                    relic_id = suffix
                    stat_type = "deck"
                relics_dict.setdefault(relic_id, {})[stat_type] = value

        aggregation_data["cards"] = cards_dict
        aggregation_data["relics"] = relics_dict
        aggregation_data["deck_count"] = deck_counts
        aggregation_data["max_hp"] = max_hp_list
        aggregation_data["relics_count"] = relics_counts

        aggregation_list.append(aggregation_data)
    return aggregation_list