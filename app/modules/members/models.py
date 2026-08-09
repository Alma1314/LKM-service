import json
from pathlib import Path

from app.modules.members.schemas import Member, SubGroup

_CONFIG_PATH = Path(__file__).parent / "members.json"

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _raw = json.load(_f)

MEMBER_LISTS: dict[str, list[Member]] = {
    key: [Member(**m) for m in items]
    for key, items in _raw["memberLists"].items()
}

SUB_GROUP_MAPS: dict[str, dict[str, SubGroup]] = {
    map_key: {
        k: SubGroup(label=v["label"], desc=v.get("desc"), members=[Member(**m) for m in v["members"]])
        for k, v in map_data.items()
    }
    for map_key, map_data in _raw["subGroupMaps"].items()
}

ALL_TYPES = sorted([*MEMBER_LISTS.keys(), *SUB_GROUP_MAPS.keys()])
