"""Property key name mapping via wiki cross-reference and distribution analysis.

Cross-references wiki item data with decoded gamelogic entries to discover
what binary property keys (0x10XXXXXX) mean in human terms.

Entry format:
  0x79XXXXXX entries in client_gamelogic.dat use a "dup-triple" encoding:
  [preamble:2B] [key:u32][val:u32] [key:u32][key:u32][val:u32] ...
  These share a 24-bit namespace with 0x25XXXXXX localization strings.

Discovery methods:
  1. Wiki correlation: match entries to wiki items via the string table,
     then find property keys whose values match known wiki fields.
  2. Distribution analysis: classify keys by their value distributions
     across all entries (see DISCOVERED_KEYS constant).

Key finding: minimum_level is stored directly as key 0x10001C5D in
dup-triple items (confirmed via Black Opal Bracers ML=31 cross-check).
"""

from __future__ import annotations

import json
import logging
import struct
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .archive import DatArchive, FileEntry
from .btree import traverse_btree
from .extract import read_entry_data
from .probe import DecodedProperty
from .strings import load_string_table

logger = logging.getLogger(__name__)

# Wiki fields to correlate against property key values.
# Numeric fields: compared directly as int.
_NUMERIC_FIELDS = [
    "minimum_level",
    "enhancement_bonus",
    "durability",
    "hardness",
    "armor_bonus",
    "max_dex_bonus",
]

# String fields: property value is a 0x0AXXXXXX string ref, resolved via
# the string table and compared to the wiki field text.
_STRING_FIELDS = [
    "weapon_type",
    "proficiency",
    "material",
    "binding",
    "quest",
    "description",
    "set_name",
    "handedness",
]

_MAX_SAMPLE_VALUES = 5


# ---------------------------------------------------------------------------
# Statistically discovered key meanings (from distribution analysis)
# ---------------------------------------------------------------------------
# These were identified by analyzing value distributions across 76,000+
# named 0x79 entries.  Confidence level indicates how strongly the
# distribution matches the proposed meaning.
#
# NOTE: minimum_level is stored directly as key 0x10001C5D (confirmed via
# cross-check of Black Opal Bracers ML=31).  The earlier hypothesis that it
# was computed at runtime was incorrect.

DISCOVERED_KEYS: dict[int, dict[str, str]] = {
    0x1000361A: {
        "name": "level",
        "confidence": "high",
        "evidence": "4715 entries, range 1-30, smooth tapering distribution. "
                    "Likely quest/encounter level, not item ML.",
    },
    0x10000E29: {
        "name": "rarity",
        "confidence": "high",
        "evidence": "6401 entries, values 2-5. Matches DDO rarity tiers: "
                    "2=Common, 3=Uncommon, 4=Rare, 5=Epic.",
    },
    0x10003D24: {
        "name": "durability",
        "confidence": "medium",
        "evidence": "3898 entries, range 1-169. 169 is standard heavy armor "
                    "durability; other peaks match DDO item types.",
    },
    0x10001BA1: {
        "name": "equipment_slot",
        "confidence": "medium",
        "evidence": "8345 entries, range 2-17. Values: 6(3139), 16(1954), "
                    "2(926), 8(702). Consistent with equipment slot codes.",
    },
    0x10001C59: {
        "name": "item_category",
        "confidence": "medium",
        "evidence": "13217 entries, range 1-12. Dominated by 12(6637) and "
                    "3(4367). Likely item type/category enum.",
    },
    0x100012A2: {
        "name": "effect_value",
        "confidence": "medium",
        "evidence": "4988 entries, range 1-100. Top: 33(1155), 100(1131). "
                    "Numeric magnitude of effect/enchantment.",
    },
    0x10000919: {
        "name": "effect_ref",
        "confidence": "high",
        "evidence": "16,168 total B-tree entries (236 wiki-named items), values "
                    "are 0x70XXXXXX file IDs pointing to type-2 effect definition "
                    "entries. Primary effect_ref slot used by BOP Bracers and "
                    "similar complex items.",
    },
    0x10001C5D: {
        "name": "minimum_level",
        "confidence": "high",
        "evidence": "Confirmed for Black Opal Bracers (ML=31, value=31) and "
                    "cross-checked against dat-identified items. Stored as a "
                    "plain u32 in dup-triple items (not computed at runtime).",
    },
    0x10001390: {
        "name": "effect_ref_2",
        "confidence": "high",
        "evidence": "185 named items, all values are 0x70XXXXXX effect IDs. "
                    "Second-most common effect_ref slot; often paired with "
                    "0x10000919 in the same item (125 items have both).",
    },
    0x100012AC: {
        "name": "effect_ref_3",
        "confidence": "medium",
        "evidence": "49 named items, all 0x70XXXXXX values. Third effect_ref "
                    "slot; frequently appears without the primary slots.",
    },
    0x100012BC: {
        "name": "effect_ref_4",
        "confidence": "medium",
        "evidence": "14 named items, all 0x70XXXXXX values. Fourth effect_ref "
                    "slot; sometimes paired with 0x100012AC.",
    },
    0x10006392: {
        "name": "effect_ref_compound",
        "confidence": "medium",
        "evidence": "Appears as first dup-triple key in rc=19 compound entries "
                    "(37,971 entries). Value is always a 0x70XXXXXX effect FID "
                    "whose low 3 bytes mirror the parent item FID. These entries "
                    "also carry refs[1..2]=0x47XXXXXX spell templates in header.",
    },
    0x10000882: {
        "name": "unknown_compound_0882",
        "confidence": "low",
        "evidence": "Most common first dup-triple key in rc=19 compound entries "
                    "(31,556 of 37,971). Purpose unknown; may be a template or "
                    "class reference for compound game objects.",
    },
    0x100008AC: {
        "name": "is_unique_or_deconstructable",
        "confidence": "low",
        "evidence": "Binary flag: 146/148 named items have val=0, 2 items "
                    "('Incredible Potential Ring Deconstruction') have val=1. "
                    "Likely a boolean flag for deconstruction eligibility or "
                    "unique-drop status.",
    },
    0x10001C5B: {
        "name": "item_subtype",
        "confidence": "low",
        "evidence": "Small enum: values 1-6 (plus rare 16, 20) in 132 named items. "
                    "Adjacent to confirmed item fields 0x10001C5D (min_level). "
                    "val=1: Blue Augment Slots, colorless diamonds, rubies (70 items); "
                    "val=2: Red Slot, abilities, quests (23 items); "
                    "val=3: Small crystals, Purple Slot (13 items); "
                    "val=20: Topaz/Legendary items at ML=55 (3 items). "
                    "Does NOT cleanly encode augment color — too mixed across item "
                    "types. May be 'item_system_category' (1=standard, 2=special, ...).",
    },
    0x10001C5F: {
        "name": "stat_def_id_item",
        "confidence": "low",
        "evidence": "Medium integers (range 369-1574) in 147 named items. Adjacent "
                    "to minimum_level (0x10001C5D) in key space. Values overlap "
                    "with stat_def_ids seen in effect entries (376=Haggle, etc.), "
                    "suggesting this encodes the primary stat_def_id for the item "
                    "as a whole rather than for individual effect sub-entries.",
    },
    0x10001C58: {
        "name": "item_schema_ref",
        "confidence": "low",
        "evidence": "146 named items, all values are 0x10XXXXXX property key IDs "
                    "(e.g. 0x10000914, 0x1000090B). Adjacent to 0x10001C5F and "
                    "0x10001C5D in the item property cluster. Functions as a "
                    "'linked schema' or 'bonus type template' pointer.",
    },
    # --- Effect ref slots 5-10 (all confirmed 0x70XXXXXX values) ---
    0x100011CB: {
        "name": "effect_ref_5",
        "confidence": "medium",
        "evidence": "Values are 0x70XXXXXX effect FIDs. Appears on compound ability "
                    "entries alongside 0x1000085B, 0x100023E6, 0x1000149C. Example "
                    "items: Knock, Soulweaver/Splendid Cacophony: Constitution (Rare).",
    },
    0x1000085B: {
        "name": "effect_ref_6",
        "confidence": "medium",
        "evidence": "Values are 0x70XXXXXX effect FIDs. Co-occurs with 0x100011CB on "
                    "the same items (Knock, Bolt[E], augment crystal entries).",
    },
    0x100023E6: {
        "name": "effect_ref_7",
        "confidence": "medium",
        "evidence": "Values are 0x70XXXXXX effect FIDs. Co-occurs with 0x100011CB and "
                    "0x1000085B on the same compound ability items.",
    },
    0x1000149C: {
        "name": "effect_ref_8",
        "confidence": "medium",
        "evidence": "Values are 0x70XXXXXX effect FIDs; some items carry 2 values for "
                    "this key. Co-occurs with 0x100011CB group on same items.",
    },
    0x100012F0: {
        "name": "effect_ref_9",
        "confidence": "medium",
        "evidence": "4 named items, all 0x70XXXXXX values. Rare slot; observed on "
                    "Bloody Bjorn[mn], Essence of the Stonemeld Plate[v], Construct "
                    "Bane, Judgment.",
    },
    0x100012E8: {
        "name": "effect_ref_10",
        "confidence": "medium",
        "evidence": "3 named items, all unique 0x70XXXXXX values. Rare slot; observed "
                    "on Essence of the Stonemeld Plate[v], Construct Bane, Judgment.",
    },
    # --- 0x10001C5X item property cluster completions ---
    0x10001C5E: {
        "name": "unknown_cluster_1C5E",
        "confidence": "low",
        "evidence": "139 named items, all values are 0x10XXXXXX property key IDs. "
                    "Adjacent to confirmed item fields (0x10001C5D minimum_level, "
                    "0x10001C58 item_schema_ref). Most common value: 0x10000909 (68x). "
                    "Co-occurs with entire 0x10001C58-0x10001C60 cluster at ~99%. "
                    "Likely another schema/template pointer in the item property block.",
    },
    0x10001C60: {
        "name": "unknown_cluster_1C60",
        "confidence": "low",
        "evidence": "140 named items. Values are packed 4-byte structures; most common "
                    "0x1C590600 (118x) and 0x1C590700 (17x). Bytes[2..3] in LE "
                    "(0x1C59) match the low 16 bits of the item_category key "
                    "(0x10001C59), suggesting a packed key reference. Co-occurs with "
                    "full cluster at ~99%.",
    },
    # --- Schema constant nodes ---
    0x10000909: {
        "name": "unknown_constant_0909",
        "confidence": "low",
        "evidence": "139 named items, ALL share the same value: 0x09190100 "
                    "(152,633,600). Also the most common ref-target of 0x10001C5E "
                    "(68 items). Items span NPCs, ammo, feats (cat=-1 70x, cat=12 68x). "
                    "Behaves as a schema-type identifier node — a fixed 'type tag' "
                    "shared by a broad class of entries.",
    },
    0x10001347: {
        "name": "unknown_constant_1347",
        "confidence": "low",
        "evidence": "97 named items, ALL share the same value: 0x39611300 "
                    "(962,663,168). Same 97 items as 0x10001348. Likely a CRC or "
                    "format-version constant embedded in a specific entry schema.",
    },
    0x10001348: {
        "name": "unknown_constant_1348",
        "confidence": "low",
        "evidence": "97 named items (same set as 0x10001347), ALL share the same "
                    "value: 0xAB82A800 (2,877,466,624). Always paired with "
                    "0x10001347. Likely the second word of a 64-bit format constant.",
    },
    # --- Enum/flag keys ---
    0x10000E39: {
        "name": "unknown_item_class_E39",
        "confidence": "low",
        "evidence": "145 named items; 3 values: 0 (138x), 1 (5x), 8 (2x). Val=0 items "
                    "span all categories. Val=1 items (Cleric Trainer, Scale: Sonic "
                    "Spell Crit Damage, Legendary Toughness) all have cat=-1 (no "
                    "item_category). Val=8 items (Epic Locus of Vol, Incredible "
                    "Potential Ring Deconstruction) also cat=-1. Non-zero values may "
                    "flag items as trainer/unique-object class.",
    },
    0x10000B32: {
        "name": "unknown_item_flags_B32",
        "confidence": "low",
        "evidence": "118 named items; 4 values: 0 (114x), 18 (2x, Shield spell), "
                    "22 (1x, Zarigan's Arcane Enlightenment: Spell Points (Rare)), "
                    "32 (1x, Incredible Potential Ring Deconstruction). Mostly 0 "
                    "with rare non-zero values on specific named items.",
    },
    0x100008B4: {
        "name": "unknown_rank_8B4",
        "confidence": "low",
        "evidence": "118 named items; small integers max=45. Val=1 (65x) is dominant. "
                    "Many values appear exactly 3x (e.g. 3, 5, 6, 10, 11, 12, 15, "
                    "19, 24), consistent with DDO enhancements having 3 tiers. Higher "
                    "values on named items like Dance of the Wind: Tumble (Rare) "
                    "(val=41), Epic Skill Focus: Perform (val=39). Possibly "
                    "enhancement tier rank or sort order.",
    },
    0x10004281: {
        "name": "unknown_pool_flag_4281",
        "confidence": "low",
        "evidence": "87 named items; 2 values: 4 (74x), 0 (13x). Val=4 items are "
                    "dominated by item_category=12 (60/74). Val=0 items are mostly "
                    "item_category=2 (8/13). May be a flag distinguishing standard "
                    "item pool (val=4) from ability/feat entries (val=0).",
    },
    0x100023F5: {
        "name": "unknown_signed_modifier_23F5",
        "confidence": "low",
        "evidence": "82 named items; signed integer values ranging from -10 to +34. "
                    "Negative values: -10 (12x, e.g. Armor, Lava Caves: Time is "
                    "Money), -5 (9x, e.g. Sapphire of Vertigo +2). Positive: +3, "
                    "+22, +24, +27, +34 (3x each). May encode a difficulty class "
                    "modifier, save penalty, or effect parameter.",
    },
    # --- Cross-item group / template reference keys ---
    0x10000A48: {
        "name": "unknown_group_ref_A48",
        "confidence": "low",
        "evidence": "155 named items; 8 distinct large values in namespace 0x00. "
                    "Most common: 0x0008AB00 (105x, e.g. Epic Locus of Vol: Blue "
                    "Augment Slot). Low byte varies 0/1 within a group. Co-occurs "
                    "with 0x10000DE2 on same items (same category/ML distribution). "
                    "May encode a loot group or content-pack identifier.",
    },
    0x10000DE2: {
        "name": "unknown_template_ref_DE2",
        "confidence": "low",
        "evidence": "151 named items; 5 distinct values. Dominant: 0x000A4A00 (113x). "
                    "Low byte varies 0/1. Identical item_category and ML distribution "
                    "to 0x10000A48 — likely always paired. May be a secondary template "
                    "or variant ID alongside 0x10000A48.",
    },
    0x10002DD9: {
        "name": "unknown_flag_or_float_2DD9",
        "confidence": "low",
        "evidence": "145 named items; binary: val=0 (144x) or val=0x40000000 (1x). "
                    "0x40000000 is IEEE 754 float 2.0; appears only on 'Scale: Sonic "
                    "Spell Crit Damage'. May encode a scaling multiplier stored as "
                    "float32, normally 0.",
    },
    0x10000901: {
        "name": "unknown_override_ref_0901",
        "confidence": "low",
        "evidence": "140 named items; val=0 (111x), otherwise 0x10XXXXXX property "
                    "key IDs (e.g. 0x10000D6F on 'Attack'). When non-zero, points to "
                    "an alternate property key — possibly an override or parent-class "
                    "property reference.",
    },
    0x10000B2E: {
        "name": "unknown_content_ref_B2E",
        "confidence": "low",
        "evidence": "138 named items; 17 distinct values; ALL have item_category=-1 "
                    "(feats/abilities/NPCs). Most common: 0x00086700 (54x, e.g. "
                    "Craftable (+6)). Values are diverse and do not clearly encode "
                    "a small enum.",
    },
    0x10000002: {
        "name": "unknown_format_sig_0002",
        "confidence": "low",
        "evidence": "127 named items; 14 distinct large values; ALL item_category=-1. "
                    "Values: 0x05001C00 (48x, Corrosive Arrows/Ammo), 0x54001800 "
                    "(38x, Orcish Strength I/Ammo), 0x90000000 (16x, Extra One "
                    "Power). Very low key ID (0x10000002) suggests a fundamental "
                    "schema marker. Values may be packed type/version signatures.",
    },
    # --- Constant-value keys (schema type tags) ---
    0x1000048E: {
        "name": "unknown_constant_pair_048E",
        "confidence": "low",
        "evidence": "127 named items; 2 distinct values: 0x3D632E00 (91x) and "
                    "0x60951300 (36x). Adjacent to 0x1000048D which is single-valued "
                    "0xA4487500. Together likely form a 64-bit schema constant pair.",
    },
    0x1000048D: {
        "name": "unknown_constant_048D",
        "confidence": "low",
        "evidence": "125 named items; ALL share value 0xA4487500 (2,756,211,968). "
                    "Same magic constant appears in 0x10005175 and 0x100018AA. "
                    "Likely a CRC-32 or schema-type tag constant.",
    },
    0x100018AA: {
        "name": "unknown_constant_18AA",
        "confidence": "low",
        "evidence": "103 named items; 96x share 0xA4487500 (same magic constant as "
                    "0x1000048D, 0x10005175). All item_category=-1. 5 items have "
                    "0x00451D01 (NPCs: Longtalon[mn], The Bloody End).",
    },
    0x10005175: {
        "name": "unknown_constant_5175",
        "confidence": "low",
        "evidence": "82 named items; ALL share value 0xA4487500 — same magic constant "
                    "as 0x1000048D and 0x100018AA. All item_category=-1.",
    },
    # --- Simple flag keys ---
    0x10000917: {
        "name": "unknown_flag_0917",
        "confidence": "low",
        "evidence": "99 named items; val=0 (98x), val=2 (1x, 'Bottled Rainstorm'). "
                    "Essentially always 0 with a single rare non-zero value.",
    },
    0x10002877: {
        "name": "unknown_flag_2877",
        "confidence": "low",
        "evidence": "83 named items; val=0 (82x), val=0x00800000 (1x, 'Green Fire'). "
                    "Essentially always 0 with a single non-zero value.",
    },
    # --- Feat/ability-specific keys ---
    0x1000088E: {
        "name": "item_type_bitmask",
        "confidence": "medium",
        "evidence": "4,934 items cross-referenced; 92% accuracy vs wiki item_type. "
                    "Bitmask: 0x04=Weapon, 0x10=Clothing, 0x40=Armor, 0x80=Jewelry, "
                    "0x01000000=Shield. On feat entries (item_category=-1) encodes "
                    "something else — does NOT map to feat boolean flags.",
    },
    0x10006F7F: {
        "name": "binding_type_ref",
        "confidence": "medium",
        "evidence": "707 items cross-referenced; 100% accuracy vs wiki binding field. "
                    "Packed reference: 0x00091701='from chest; otherwise' (57x), "
                    "0x00048D01/0x0008FC01/0x000B6A01=unbound. Low byte always 0x01 "
                    "(version flag).",
    },
    0x10002899: {
        "name": "unknown_template_ref_2899",
        "confidence": "low",
        "evidence": "86 named items; 6 distinct values; item_category=12 dominant "
                    "(44/86). Values: 0x0008B401 (37x), 0x0008B400 (31x), "
                    "0x0008FC01 (7x). Low byte 0/1 variant pattern — similar to "
                    "0x10006F7F.",
    },
    0x10001399: {
        "name": "damage_dice_notation",
        "confidence": "medium",
        "evidence": "83 named items; ALL item_category=-1. Values encode ASCII dice "
                    "notation as a packed 4-byte little-endian u32: byte[0]=bonus, "
                    "bytes[1..3]='XdY' ASCII. Examples: 0x32643205=[bonus=5,'2d2'] "
                    "→ 2d2+5; 0x34643103=[bonus=3,'1d4'] → 1d4+3. byte[2] is always "
                    "0x64 ('d'). Encodes damage dice for weapon/proc effects.",
    },
    0x10001585: {
        "name": "unknown_rank_1585",
        "confidence": "low",
        "evidence": "78 named items; small integers max=46; 36 distinct values; ALL "
                    "item_category=-1. val=1 is most common (16x). May be an "
                    "enhancement tier or sort-order rank similar to 0x100008B4.",
    },
    # --- Float-valued property keys ---
    0x10000E7C: {
        "name": "unknown_float_one_E7C",
        "confidence": "low",
        "evidence": "78 named items; ALL share value 0x3F800000, which is IEEE 754 "
                    "float 1.0. ALL item_category=-1. Likely a float32 property "
                    "storing a multiplicative scale factor, always 1.0 here.",
    },
    0x10002BCE: {
        "name": "unknown_float_modifier_2BCE",
        "confidence": "low",
        "evidence": "78 named items; val=0 (74x), otherwise IEEE 754 floats: "
                    "0x3DCCCCCD≈0.1 (2x, Echo of Ravenkind, Volley the Arbalest), "
                    "0x3C23D70A≈0.01 (1x, Card Trade 08_09), 0x3E19999A≈0.15 "
                    "(1x, Witch Doctor Glik[E]). Float32 modifier, normally 0.",
    },
    # --- Secondary feat/ability group refs ---
    0x1000283C: {
        "name": "unknown_group2_ref_283C",
        "confidence": "low",
        "evidence": "78 named items; 6 distinct values; ALL item_category=-1. "
                    "Most common: 0x00189800 (35x, Dread Pirate Apothecary[m]), "
                    "0x00189801 (33x, Craftable (+6)). Low byte 0/1 variant pattern.",
    },
    0x10002840: {
        "name": "unknown_group2_ref_2840",
        "confidence": "low",
        "evidence": "78 named items; 5 distinct values; ALL item_category=-1. "
                    "Most common: 0x002D1F00 (56x). Co-occurs with 0x1000283C, "
                    "0x10002BCE, 0x10000E7C on same entry set.",
    },
    # --- 78-item linked property chain (feat/ability entries) ---
    0x10001071: {
        "name": "unknown_chain_head_1071",
        "confidence": "low",
        "evidence": "77 named items; ALL share value 0x1000A084 (a key ID pointer). "
                    "Entry in the 78-item linked property chain — acts as a pointer "
                    "to the chain's data node (0x1000A084). See 0x10001072 for the "
                    "full chain description.",
    },
    0x10001072: {
        "name": "unknown_chain_count_1072",
        "confidence": "low",
        "evidence": "78 named items; ALL val=1. Entry in the 78-item property chain "
                    "(items like Wildhunter: Attack and Damage, Item Restoration). "
                    "Chain structure: 0x10001071→0x1000A084 (data ptr), "
                    "0x10001072=1 (count), 0x10001073=18 (type), "
                    "0x10001076→0x10730300→0x10731000 (value chain). "
                    "Likely feat/enhancement slot definitions.",
    },
    0x10001073: {
        "name": "unknown_chain_type_1073",
        "confidence": "low",
        "evidence": "78 named items; val=18 (77x), val=15 (1x). Part of the 78-item "
                    "linked property chain; likely a type or slot-kind identifier.",
    },
    0x10001076: {
        "name": "unknown_chain_start_1076",
        "confidence": "low",
        "evidence": "78 named items; ALL val=0x10730300 (key ID pointer). Head of the "
                    "value sub-chain in the 78-item property chain. Points to the "
                    "0x10730300→0x10731000 chain node.",
    },
    0x1000A084: {
        "name": "unknown_chain_node_A084",
        "confidence": "low",
        "evidence": "78 named items; 6 distinct item-reference values (low byte=0x01). "
                    "Most common: 0x003D2501 (48x, Angelic Wings entries). Target of "
                    "the 0x10001071 pointer in the 78-item property chain. Stores "
                    "the actual data ref for the chain entry.",
    },
    0x10710000: {
        "name": "unknown_chain_ptr_7100",
        "confidence": "low",
        "evidence": "77 named items; ALL val=0x10711000 (key ID pointer). Part of the "
                    "0x107XXXXX linked chain sub-structure. Keys in the 0x107XXXXX "
                    "range appear to form a linked list where each key's value is the "
                    "next key in the chain.",
    },
    0x10730300: {
        "name": "unknown_chain_next_7303",
        "confidence": "low",
        "evidence": "78 named items; ALL val=0x10731000 (key ID pointer). Chain node "
                    "in the 0x107XXXXX linked structure; always points to 0x10731000.",
    },
    0x10731000: {
        "name": "unknown_chain_value_7310",
        "confidence": "low",
        "evidence": "78 named items; val=0x00121000 (77x), val=0x000F1000 (1x, "
                    "Insightful Magical Sheltering +). Terminal value node in the "
                    "0x107XXXXX chain. Value 0x00121000 encodes 0x12=18 (matching "
                    "0x10001073 type=18) and 0x1000 = a block marker.",
    },
    0x10760000: {
        "name": "unknown_chain_terminal_7600",
        "confidence": "low",
        "evidence": "78 named items; ALL val=0x03001000. Terminal node in the "
                    "0x107XXXXX chain. Constant across all entries.",
    },
    # --- Missing 0x107XXXXX chain node ---
    0x10711000: {
        "name": "unknown_chain_value_7110",
        "confidence": "low",
        "evidence": "77 named items; ALL val=0xA0841000. Terminal value node in the "
                    "0x10710000→0x10711000 sub-chain. 0xA0841000 may encode a ref "
                    "to 0x1000A084 (the chain_node_A084 key, low bytes=0xA084).",
    },
    # --- Additional constant-value keys (adjacent to known constant cluster) ---
    0x10001349: {
        "name": "unknown_constant_1349",
        "confidence": "low",
        "evidence": "97 named items; ALL val=0x78F2A800. Third member of the "
                    "0x10001347/48/49 triple — all three appear on the same 97 items "
                    "and hold a single constant value each. Likely schema tags.",
    },
    0x10003102: {
        "name": "unknown_constant_3102",
        "confidence": "low",
        "evidence": "Appears on same category of items as other constant-value keys; "
                    "always a single repeated value. Likely a schema or type tag.",
    },
    0x10003972: {
        "name": "unknown_constant_3972",
        "confidence": "low",
        "evidence": "One of four keys (0x1000048D, 0x10005175, 0x100018AA, 0x10003972) "
                    "that all carry the magic constant 0xA4487500, believed to be a "
                    "schema-type tag. Always the same value across all items.",
    },
    0x10001A51: {
        "name": "unknown_constant_1A51",
        "confidence": "low",
        "evidence": "Single constant value across all occurrences. Likely a schema "
                    "tag or type marker.",
    },
    # --- Additional effect_ref slots (0x70XXXXXX values) ---
    0x10001B8D: {
        "name": "effect_ref_shared_1B8D",
        "confidence": "medium",
        "evidence": "73 named items; ALL share the SAME FID 0x700027E1. Unlike other "
                    "effect_ref_* keys which vary per item, this slot always points to "
                    "the same effect entry — possibly a global damage/defence baseline "
                    "or shared procedural effect.",
    },
    0x10001BC4: {
        "name": "effect_ref_11_BC4",
        "confidence": "medium",
        "evidence": "All values are 0x70XXXXXX FIDs (effect entry file IDs). Part of "
                    "the sequential 0x10001BC4/BC6/BC7 triple of effect_ref slots. "
                    "Co-occur on the same items as other effect_ref keys.",
    },
    0x10001BC6: {
        "name": "effect_ref_12_BC6",
        "confidence": "medium",
        "evidence": "All values are 0x70XXXXXX FIDs (effect entry file IDs). Part of "
                    "the sequential 0x10001BC4/BC6/BC7 triple of effect_ref slots.",
    },
    0x10001BC7: {
        "name": "effect_ref_13_BC7",
        "confidence": "medium",
        "evidence": "All values are 0x70XXXXXX FIDs (effect entry file IDs). Part of "
                    "the sequential 0x10001BC4/BC6/BC7 triple of effect_ref slots.",
    },
    # --- Float-valued property keys (IEEE 754 float32 stored in u32 slots) ---
    0x10000B60: {
        "name": "tier_multiplier",
        "confidence": "high",
        "evidence": "IEEE 754 float32; values 0.0, 1.0, 2.0, 3.0, 4.0, -1.0. "
                    "Confirmed as effect scaling tier multiplier. Used in items.py "
                    "as _KEY_TIER_MULTIPLIER, stored in items.tier_multiplier column.",
    },
    0x10000B5C: {
        "name": "sign_multiplier",
        "confidence": "high",
        "evidence": "IEEE 754 float32; values +1.0 (buff) or -1.0 (debuff). "
                    "Confirmed as buff/debuff sign multiplier. Used in items.py "
                    "as _KEY_SIGN_MULTIPLIER for is_debuff extraction.",
    },
    0x100007F8: {
        "name": "unknown_float_coeff_7F8",
        "confidence": "low",
        "evidence": "IEEE 754 float32; predominantly 1.0 (0x3F800000). Part of the "
                    "0x100007E2/F0/F5/F8 float coefficient group; likely a multiplier "
                    "or weight used in effect/stat calculations.",
    },
    0x100007F0: {
        "name": "unknown_float_coeff_7F0",
        "confidence": "low",
        "evidence": "IEEE 754 float32; predominantly 1.0 (0x3F800000). Part of the "
                    "0x100007E2/F0/F5/F8 float coefficient group.",
    },
    0x100007F5: {
        "name": "unknown_float_coeff_7F5",
        "confidence": "low",
        "evidence": "IEEE 754 float32; predominantly 1.0 (0x3F800000). Part of the "
                    "0x100007E2/F0/F5/F8 float coefficient group.",
    },
    0x100007E2: {
        "name": "unknown_float_coeff_7E2",
        "confidence": "low",
        "evidence": "IEEE 754 float32; predominantly 1.0 (0x3F800000). Part of the "
                    "0x100007E2/F0/F5/F8 float coefficient group.",
    },
    0x100008FC: {
        "name": "unknown_float_approx8_8FC",
        "confidence": "low",
        "evidence": "IEEE 754 float32; values cluster around 8.0–8.2. Possible item "
                    "weight (DDO items have weights like 8 lb) or a scaling parameter.",
    },
    0x10000742: {
        "name": "unknown_float_level_742",
        "confidence": "low",
        "evidence": "IEEE 754 float32; values range 6.0–32.0. Range matches DDO "
                    "minimum level range; may be a float representation of a level "
                    "requirement or caster level.",
    },
    # --- 0x10BB linked chain pair ---
    0x10BB0000: {
        "name": "unknown_chain_ptr_BB00",
        "confidence": "low",
        "evidence": "Always val=0x10BB1000 (key ID). Head of the 0x10BB0000→0x10BB1000 "
                    "pointer sub-chain, analogous to 0x10710000→0x10711000.",
    },
    0x10BB1000: {
        "name": "unknown_chain_value_BB10",
        "confidence": "low",
        "evidence": "Terminal value node for the 0x10BB0000→0x10BB1000 chain. "
                    "Value is a data reference or constant.",
    },
    0x100010BB: {
        "name": "unknown_chain_node_10BB",
        "confidence": "low",
        "evidence": "Parallel key to the 0x10BB chain; appears on the same items. "
                    "Likely the 0x10XX-namespace equivalent of the 0x10BB chain head.",
    },
    # --- 0x10000ABC/D/E ability flags cluster ---
    0x10000ABC: {
        "name": "weapon_class_bitmask",
        "confidence": "medium",
        "evidence": "4,635 items cross-referenced; 93% accuracy vs wiki proficiency. "
                    "Power-of-2 bitmask: 0x1000=Martial (685x), 0x2000=Martial (639x), "
                    "0x200=Simple (24x), 0x400000=Tower Shield (47x), 0x800=Magical "
                    "Training (20x). Part of ABC/ABD/ABE cluster.",
    },
    0x10000ABD: {
        "name": "unknown_ability_id_ABD",
        "confidence": "low",
        "evidence": "Part of the 0x10000ABC/ABD/ABE cluster; small integer, max=126. "
                    "Likely an ability or feat index within a category.",
    },
    0x10000ABE: {
        "name": "unknown_ability_bits_ABE",
        "confidence": "low",
        "evidence": "Part of the 0x10000ABC/ABD/ABE cluster. Value distribution "
                    "similar to ABC; may be a second flags/bits field for the ability.",
    },
    # --- Triple small-int parameter group (0x539/53B/53D) ---
    0x10000539: {
        "name": "unknown_seq6_param_A_539",
        "confidence": "low",
        "evidence": "Small integer; 70 named items. Part of the 6-member adjacent "
                    "sequence 539/53A/53B/53C/53D/53E. 58 items carry all 6; 12 items "
                    "carry only the odd sub-set (539/53B/53D). The 6 values together "
                    "encode a multi-part parameter (index, rank, or effect components). "
                    "Sample 'Fire Giant Exterminator IV': [34, 21, 10, 6, 10, 7].",
    },
    0x1000053B: {
        "name": "unknown_seq6_param_C_53B",
        "confidence": "low",
        "evidence": "Small integer; 70 named items. Third of the 6-member "
                    "539/53A/53B/53C/53D/53E sequence.",
    },
    0x1000053D: {
        "name": "unknown_seq6_param_E_53D",
        "confidence": "low",
        "evidence": "Small integer; 70 named items. Fifth of the 6-member "
                    "539/53A/53B/53C/53D/53E sequence.",
    },
    # --- Remaining individual keys ---
    0x100007EB: {
        "name": "unknown_flag_enum_7EB",
        "confidence": "low",
        "evidence": "Small enum with ~6 distinct values. Distribution and category "
                    "correlation not yet fully characterised.",
    },
    0x10000E87: {
        "name": "unknown_content_ref_E87",
        "confidence": "low",
        "evidence": "Values include 0x10XXXXXX property refs and small integers. "
                    "Possible content pack or expansion reference.",
    },
    0x100015C3: {
        "name": "unknown_flag_15C3",
        "confidence": "low",
        "evidence": "Binary or small-enum flag; appears on a subset of items.",
    },
    0x1000224E: {
        "name": "unknown_count_224E",
        "confidence": "low",
        "evidence": "Small integer; distribution suggests a count or index field.",
    },
    # --- 6-member 53X sequence: even sub-set ---
    0x1000053A: {
        "name": "unknown_seq6_param_B_53A",
        "confidence": "low",
        "evidence": "Small integer; 61 named items. Second of the 6-member "
                    "539/53A/53B/53C/53D/53E sequence. Part of the even sub-set "
                    "(53A/53C/53E), present on 58 of the 70 sequence items.",
    },
    0x1000053C: {
        "name": "unknown_seq6_param_D_53C",
        "confidence": "low",
        "evidence": "Small integer; 61 named items. Fourth of the 6-member "
                    "539/53A/53B/53C/53D/53E sequence.",
    },
    0x1000053E: {
        "name": "unknown_seq6_param_F_53E",
        "confidence": "low",
        "evidence": "Small integer; 61 named items. Sixth (final) member of the "
                    "539/53A/53B/53C/53D/53E sequence.",
    },
    # --- E87/E8F/E90 triple (adjacent small-int parameters) ---
    0x10000E8F: {
        "name": "unknown_triple_param_D_E8F",
        "confidence": "low",
        "evidence": "Small integer, max=36; 67 named items. Part of the E87/E8F/E90 "
                    "triple — 64/67 items have both E8F and E90. Similar value range "
                    "to the 539/53B/53D triple. Three adjacent keys likely encode "
                    "a 3-part parameter (index, rank, or effect component).",
    },
    0x10000E90: {
        "name": "unknown_triple_param_E_E90",
        "confidence": "low",
        "evidence": "Small integer, max=25; 67 named items. Part of the E87/E8F/E90 "
                    "triple. Adjacent to E8F with 64/67 items in common.",
    },
    # --- All-zero constants (schema tag placeholders) ---
    0x10001954: {
        "name": "unknown_zero_constant_1954",
        "confidence": "low",
        "evidence": "66 named items; ALL val=0. Likely a schema tag or reserved slot "
                    "that is always zero in the current data set.",
    },
    0x10001A46: {
        "name": "unknown_zero_constant_1A46",
        "confidence": "low",
        "evidence": "63 named items; ALL val=0. Schema tag or always-zero reserved field.",
    },
    0x10000B1D: {
        "name": "unknown_zero_constant_B1D",
        "confidence": "low",
        "evidence": "62 named items; ALL val=0. Schema tag or always-zero reserved field.",
    },
    0x100017A0: {
        "name": "unknown_zero_constant_17A0",
        "confidence": "low",
        "evidence": "62 named items; ALL val=0. Schema tag or always-zero reserved field.",
    },
    # --- Additional float-valued keys ---
    0x1000073D: {
        "name": "unknown_float_sparse_73D",
        "confidence": "low",
        "evidence": "IEEE 754 float32; mostly 0.0 (52/66), sparse non-zero floats: "
                    "4.0, 18.0, 22.0, 27.0, 32.0. Non-zero values span DDO level "
                    "range, suggesting an optional float level/dim parameter.",
    },
    0x10006CDA: {
        "name": "unknown_float_coeff_6CDA",
        "confidence": "low",
        "evidence": "IEEE 754 float32; mostly 0.0 (53/64), sparse values: 1.0 (7x), "
                    "0.5 (3x), 0.05 (1x). Likely a multiplier or fractional coefficient.",
    },
    0x10000B7A: {
        "name": "cooldown_seconds",
        "confidence": "high",
        "evidence": "IEEE 754 float32; mostly 15.0 (60/63), occasionally 1.0. "
                    "Confirmed as cooldown in seconds. Used in items.py as "
                    "_KEY_COOLDOWN and feats.py for cooldown_seconds extraction.",
    },
    0x100007BC: {
        "name": "unknown_float_coeff_7BC",
        "confidence": "low",
        "evidence": "IEEE 754 float32; mostly 1.0 (61/63). Adjacent to the "
                    "7E2/7F0/7F5/7F8 float coefficient group; likely another "
                    "multiplier in that cluster.",
    },
    0x1000131A: {
        "name": "unknown_float_range_A_131A",
        "confidence": "low",
        "evidence": "IEEE 754 float32; 40 distinct values, range 4.0–32.0. Adjacent "
                    "to 0x1000131B; together the pair may encode a min/max range or "
                    "two independent float dimensions.",
    },
    0x1000131B: {
        "name": "unknown_float_range_B_131B",
        "confidence": "low",
        "evidence": "IEEE 754 float32; 40 distinct values, range 4.0–32.0. Adjacent "
                    "to 0x1000131A; the pair likely encodes two related float bounds.",
    },
    0x10001A6B: {
        "name": "unknown_float_dim_1A6B",
        "confidence": "low",
        "evidence": "IEEE 754 float32; 33 distinct values, range 1.0–19.0. Diverse "
                    "per-item values suggest a scaling dimension or attribute.",
    },
    0x10005176: {
        "name": "unknown_float_approx8_5176",
        "confidence": "low",
        "evidence": "IEEE 754 float32; values cluster tightly around 8.0–8.2 "
                    "(e.g. 8.02, 8.18, 8.23). Similar to 0x100008FC. Adjacent to "
                    "0x10005175 (schema tag) and 0x10005177; the triple 5175/5176/5177 "
                    "may encode a schema tag + two float parameters.",
    },
    0x10005177: {
        "name": "unknown_float_tiny_5177",
        "confidence": "low",
        "evidence": "Values: mostly 0x3D632E00 (~0.0555, 57/62), rarely 0xA3XXXXXX "
                    "or 0x70XXXXXX. The 0.0555 constant may be a fixed precision or "
                    "weight factor. Part of the 5175/5176/5177 triple.",
    },
    # --- Slot reference key ---
    0x10000B22: {
        "name": "unknown_slot_ref_B22",
        "confidence": "low",
        "evidence": "Values are 0x10XXXXXX property key IDs (not file IDs). Most "
                    "common: 0x1000085B (effect_ref_6, 35/61 items), then 0x100033C1 "
                    "(14x), 0x10003D73 (4x). This key points to another key — "
                    "possibly identifying which effect_ref slot holds the primary "
                    "effect, or linking to a companion definition key.",
    },
    # --- Sparse optional effect_ref slots ---
    0x1000726E: {
        "name": "effect_ref_14_726E",
        "confidence": "medium",
        "evidence": "62 items; mostly val=0, but 7 items carry 0x70XXXXXX effect FIDs "
                    "(Fragment of Extraplanar Shadow, Legendary Thrummingspark Cord, "
                    "etc.). Sparse optional effect_ref slot, pattern matches other "
                    "effect_ref_N keys.",
    },
    0x10005405: {
        "name": "effect_ref_15_5405",
        "confidence": "medium",
        "evidence": "66 items; mostly val=0, one item (Diamond of Constitution +1) "
                    "carries 0x70014B84. Very sparse optional effect_ref slot.",
    },
    # --- Additional small-int / enum keys ---
    0x100008A3: {
        "name": "unknown_small_int_8A3",
        "confidence": "low",
        "evidence": "Small integer, max=35; 67 named items, mostly 0 (55/67). Diverse "
                    "non-zero values (10, 12, 19, 20, 35) with no clear pattern. "
                    "Similar distribution to 0x10000854.",
    },
    0x100030F5: {
        "name": "unknown_flag_30F5",
        "confidence": "low",
        "evidence": "3 distinct values: 0 (49x), 32 (16x), 8 (1x). The 32 vs 0 "
                    "split (16 items) may be a bitfield flag (bit 5 set).",
    },
    0x100007E5: {
        "name": "unknown_flag_7E5",
        "confidence": "low",
        "evidence": "Near-binary: 0 (65/66) vs 8 (1x). Single outlier on 'Apply "
                    "Minimum Level 25'. Adjacent to the 7E2/7F0/7F5/7F8 float group; "
                    "may be a boolean flag in that cluster.",
    },
    0x10000854: {
        "name": "unknown_small_int_854",
        "confidence": "low",
        "evidence": "Small integer, max=~37; 62 named items. Diverse non-zero values "
                    "(2, 10, 15, 17, 20, ...). Similar to 0x100008A3; possibly both "
                    "encode a class or sub-type index.",
    },
    # --- Constant ---
    0x10002842: {
        "name": "unknown_constant_2842",
        "confidence": "low",
        "evidence": "66 named items; ALL val=0x00284300. Bytes: 0x00, 0x43=67, "
                    "0x28=40, 0x00. The 0x43 (67) byte may encode a count or schema "
                    "type. Another instance of the magic-constant pattern.",
    },
    # --- Zero / preamble key ---
    0x10000000: {
        "name": "unknown_preamble_ref_0000",
        "confidence": "low",
        "evidence": "61 named items; 9 distinct values including packed byte patterns "
                    "(0x001B3B00, 0x00011100, 0x0019FC00) and occasional 0x10XXXXXX "
                    "refs. Key ID 0x10000000 is suspiciously low — values may be "
                    "from the 2-byte preamble region of the dup-triple stream rather "
                    "than a true property key.",
    },
    # --- Tier-3 keys (60–63 occurrences) ---
    # Companion to 0x10003972 (0xA4487500 schema tag)
    0x10003973: {
        "name": "unknown_constant_3973",
        "confidence": "low",
        "evidence": "63 named items; ALL val=0xE399D700 — single constant adjacent "
                    "to 0x10003972 (the 0xA4487500 schema tag). Part of the same "
                    "schema-tag cluster.",
    },
    # Adjacent to float_level_742
    0x10000747: {
        "name": "grip_type",
        "confidence": "medium",
        "evidence": "4,864 items cross-referenced; 91% accuracy vs wiki attack_mod. "
                    "Values 2-7 encode handedness/grip: 2=light one-hand (STR), "
                    "3=standard one-hand, 4=two-hand, 5=ranged. Partitions weapons "
                    "by grip category; wiki attack_mod is derived from grip.",
    },
    # Adjacent pair 1919/191A
    0x10001919: {
        "name": "unknown_ref_or_zero_1919",
        "confidence": "low",
        "evidence": "62 items; 2 vals: 0 (40x) or 0x100013E6 (22x, a 0x10XXXXXX ref). "
                    "Binary: either absent (0) or points to a specific key/entry ref. "
                    "Adjacent to 0x1000191A.",
    },
    0x1000191A: {
        "name": "unknown_small_int_191A",
        "confidence": "low",
        "evidence": "62 items; 2 vals: 0 (40x) or 20 (22x). Adjacent to 0x10001919 "
                    "— the 22 items with 191A=20 are the same items where 1919 holds "
                    "a 0x10XXXXXX ref. Possibly a paired count or mode flag.",
    },
    # Pair 1D94/1D95
    0x10001D94: {
        "name": "unknown_constant_1D94",
        "confidence": "low",
        "evidence": "61 items; mostly val=0x670E8400 (59x), one outlier "
                    "0x0BD51500. Large constant value; purpose unclear. Adjacent to "
                    "0x10001D95.",
    },
    0x10001D95: {
        "name": "unknown_float_sparse_1D95",
        "confidence": "low",
        "evidence": "IEEE 754 float32; 62 items; mostly 0.0 (48x), sparse non-zero: "
                    "30.0 (12x), 15.0 (1x), 35.0 (1x). Adjacent to 0x10001D94. "
                    "Optional float parameter.",
    },
    # Low key 0x1000000F (preamble-region artifact)
    0x1000000F: {
        "name": "unknown_preamble_ref_000F",
        "confidence": "low",
        "evidence": "62 items; ALL val=0x3D632E00 (~0.0555). Same constant value "
                    "as 0x10005177. Key ID 0x0F is suspiciously low (like 0x10000000) "
                    "— may be a preamble region artifact rather than a true property.",
    },
    # Adjacent to B22 (slot_ref)
    0x10000B24: {
        "name": "unknown_float_coeff_B24",
        "confidence": "low",
        "evidence": "IEEE 754 float32; 61 items; mostly 0.0 (48x), sparse fractional "
                    "values: 1.0 (8x), 0.25 (3x), ~0.2/0.29 (2x). Adjacent to "
                    "0x10000B22 (slot_ref). Likely a fractional coefficient or weight.",
    },
    # Additional zero constants
    0x10000C3E: {
        "name": "unknown_zero_constant_C3E",
        "confidence": "low",
        "evidence": "61 items; ALL val=0. Schema tag or always-zero reserved slot.",
    },
    0x10001B0A: {
        "name": "unknown_zero_constant_1B0A",
        "confidence": "low",
        "evidence": "60 items; ALL val=0. Schema tag or always-zero reserved slot.",
    },
    # 1A4A/4B/4C triple (all 60 items perfectly co-occur)
    0x10001A4A: {
        "name": "unknown_ref_slot_A_1A4A",
        "confidence": "low",
        "evidence": "60 items; mostly 0 (54x), else 0x10XXXXXX refs (effect_ref_13_BC7, "
                    "0x100019F5, 0x10001C36). Part of the 1A4A/1A4B/1A4C triple "
                    "(all 60 items perfectly co-occur). May be an optional slot ref.",
    },
    0x10001A4B: {
        "name": "unknown_ref_slot_B_1A4B",
        "confidence": "low",
        "evidence": "60 items; mostly 0 (42x), else 0x10XXXXXX refs. Part of the "
                    "1A4A/1A4B/1A4C triple. Second optional slot ref.",
    },
    0x10001A4C: {
        "name": "unknown_param_C_1A4C",
        "confidence": "low",
        "evidence": "60 items; mostly 0 (42x), else small ints 2/3/4 or packed "
                    "bytes (0x00140004). Part of the 1A4A/1A4B/1A4C triple. "
                    "May be a count or mode field paired with the two slot refs.",
    },
    # Other 60-count keys
    0x100029A9: {
        "name": "unknown_packed_id_29A9",
        "confidence": "low",
        "evidence": "61 items; 5 vals of packed 3-byte data (0x0026AD00, 0x006CCF00, "
                    "etc.); last byte 0x00 or 0x01. Likely a packed ID or reference "
                    "with a variant flag in the low byte.",
    },
    0x1000080F: {
        "name": "unknown_packed_data_80F",
        "confidence": "low",
        "evidence": "61 items; 29 distinct large values with byte patterns like "
                    "0x3144310B. Values are not valid floats or known refs — likely "
                    "packed multi-byte fields (e.g. version or UUID fragment).",
    },
    0x10001AED: {
        "name": "unknown_ref_or_zero_1AED",
        "confidence": "low",
        "evidence": "60 items; 3 vals: 0 (39x), 0x100013E5 (11x), 0x10001787 (10x). "
                    "Binary-like: either 0 or one of two 0x10XXXXXX entry refs. "
                    "Similar pattern to 0x10001919.",
    },
    0x10002368: {
        "name": "unknown_float_sparse_2368",
        "confidence": "low",
        "evidence": "60 items; mostly 0 (58x), one item has 60.0 (0x42700000). "
                    "Very sparse optional float.",
    },
    # --- Tier-4 keys (55–59 occurrences) ---
    # Adjacent pair of sparse effect_ref slots
    0x10003EF4: {
        "name": "effect_ref_16_3EF4",
        "confidence": "medium",
        "evidence": "59 items; mostly 0 (52x), else 0x70XXXXXX effect FIDs. Adjacent "
                    "to 0x10003EF5 with exactly parallel values (FIDs differ by 1). "
                    "Sparse optional effect_ref slot pair.",
    },
    0x10003EF5: {
        "name": "effect_ref_17_3EF5",
        "confidence": "medium",
        "evidence": "59 items; mostly 0 (52x), else 0x70XXXXXX effect FIDs. Adjacent "
                    "to 0x10003EF4 with exactly parallel values (FIDs differ by 1). "
                    "Sparse optional effect_ref slot pair.",
    },
    # New 0x107XXXXX chain link
    0x10720001: {
        "name": "unknown_chain_ptr_7200",
        "confidence": "low",
        "evidence": "59 items; ALL val=0x10721000 (key ID). Head of the "
                    "0x10720001→0x10721000 pointer sub-chain, same pattern as "
                    "0x10710000→0x10711000 and 0x10BB0000→0x10BB1000.",
    },
    0x10721000: {
        "name": "unknown_chain_value_7210",
        "confidence": "low",
        "evidence": "59 items; ALL val=0x00011000. Terminal value in the "
                    "0x10720001→0x10721000 chain. Constant 0x00011000.",
    },
    # Near-binary flags and zero constants
    0x10001167: {
        "name": "unknown_flag_1167",
        "confidence": "low",
        "evidence": "59 items; near-binary: 0 (57x) vs 1 (2x). A boolean flag.",
    },
    0x100008BB: {
        "name": "unknown_zero_constant_8BB",
        "confidence": "low",
        "evidence": "59 items; ALL val=0. Adjacent to 0x100008B9/8BA/8BB cluster. "
                    "Schema tag or always-zero slot.",
    },
    0x100008BA: {
        "name": "unknown_zero_constant_8BA",
        "confidence": "low",
        "evidence": "58 items; ALL val=0. Adjacent to 0x100008B9/8BA/8BB cluster.",
    },
    0x10002232: {
        "name": "unknown_zero_constant_2232",
        "confidence": "low",
        "evidence": "56 items; ALL val=0. Schema tag or always-zero reserved slot.",
    },
    0x100028EA: {
        "name": "unknown_zero_constant_28EA",
        "confidence": "low",
        "evidence": "56 items; ALL val=0. Schema tag or always-zero reserved slot.",
    },
    # Small-int / enum keys
    0x100008B9: {
        "name": "unknown_small_int_8B9",
        "confidence": "low",
        "evidence": "59 items; small integer, diverse values 0–20. Adjacent to "
                    "0x100008BA/8BB (zero constants). May be an index for the group.",
    },
    0x100007B8: {
        "name": "unknown_flag_enum_7B8",
        "confidence": "low",
        "evidence": "56 items; 5 distinct values: 0 (51x), 5 (2x), 4 (1x), 45 (1x), "
                    "100 (1x). Mostly-zero enum or flag.",
    },
    0x10000CF8: {
        "name": "unknown_binary_CF8",
        "confidence": "low",
        "evidence": "55 items; binary 2 (34x) or 1 (21x) — no zeros. Unusual "
                    "two-state field where both states are non-zero.",
    },
    0x10002E22: {
        "name": "unknown_flags_2E22",
        "confidence": "low",
        "evidence": "56 items; mostly 0 (54x), outliers 1024 (0x400) and 32784 "
                    "(0x8010=bits 15+4). Likely a bitfield.",
    },
    # Float keys
    0x10001A50: {
        "name": "unknown_float_approx8_1A50",
        "confidence": "low",
        "evidence": "IEEE 754 float32; 56 items; values cluster around 8.0 "
                    "(e.g. 0x4100CDA5 ≈ 8.05). Another instance of the ~8.0 float "
                    "cluster (like 0x100008FC and 0x10005176).",
    },
    0x10002F9E: {
        "name": "unknown_float_constant_1_2F9E",
        "confidence": "low",
        "evidence": "56 items; ALL val=0x3F800000 (1.0 as IEEE 754 float32). "
                    "A float-1.0 constant key, similar to the 7E2/7F0/7F5/7F8 group.",
    },
    # Special constant: all 0xFFFFFFFF
    0x100026AC: {
        "name": "unknown_all_ff_26AC",
        "confidence": "low",
        "evidence": "56 items; ALL val=0xFFFFFFFF. As a signed int this is -1; as a "
                    "u32 it is the maximum. May be a sentinel 'null/unset' value "
                    "for a reference field, or a bitfield with all bits set.",
    },
    # 12A3/A4/A6 cluster (adjacent to effect_ref_3/4 keys 0x100012AC/BC)
    0x100012A3: {
        "name": "unknown_packed_ref_12A3",
        "confidence": "low",
        "evidence": "56 items; large diverse packed values (0x12AC3101, 0x12BC3101, "
                    "0x32643103). Adjacent to effect_ref keys 0x100012AC and "
                    "0x100012BC. High bytes (0x12AC, 0x12BC) match those key low-bytes, "
                    "suggesting packed key-ID references.",
    },
    0x100012A4: {
        "name": "unknown_packed_ref_12A4",
        "confidence": "low",
        "evidence": "56 items; large packed values (0x12DC0200, 0x12C00200). "
                    "Adjacent to 0x100012A3; part of the 12A3/A4/A6 cluster. "
                    "Similar packed-ref pattern.",
    },
    0x100012A6: {
        "name": "unknown_small_int_12A6",
        "confidence": "low",
        "evidence": "56 items; small integer max=28, values 1–28. Adjacent to "
                    "0x100012A3/A4; likely a count or slot index in the cluster.",
    },
    # --- Tier-5 keys (53–60 occurrences) ---
    # 60-count tier
    0x10001CDE: {
        "name": "unknown_float_sparse_1CDE",
        "confidence": "low",
        "evidence": "60 items; mostly 0 (54x), 6 items have float 1.0 "
                    "(0x3F800000). Sparse optional float parameter.",
    },
    0x1000121B: {
        "name": "unknown_packed_id_121B",
        "confidence": "low",
        "evidence": "60 items; mostly val=0x0037A801 (55x), occasional variants. "
                    "Adjacent to the 12A3/A4/A6 cluster. Packed byte pattern "
                    "(bytes 0x00, 0x37, 0xA8, 0x01).",
    },
    0x100072C2: {
        "name": "unknown_flag_72C2",
        "confidence": "low",
        "evidence": "60 items; near-zero: 0 (59x) vs 15 (1x). Boolean or tiny enum.",
    },
    0x100019C2: {
        "name": "unknown_zero_constant_19C2",
        "confidence": "low",
        "evidence": "60 items; ALL val=0. Schema tag or always-zero reserved slot.",
    },
    # 59-count tier
    0x10002843: {
        "name": "unknown_packed_id_2843",
        "confidence": "low",
        "evidence": "59 items; packed 3-byte values (0x00073D00, 0x00020F00, "
                    "0x0007F000). Adjacent to 0x10002842 (constant 0x00284300) and "
                    "0x10002840. The packed bytes may encode a category ID.",
    },
    0x10001A53: {
        "name": "unknown_binary_1A53",
        "confidence": "low",
        "evidence": "59 items; binary: 0 (41x) vs 2 (18x). A two-state flag.",
    },
    0x10001A54: {
        "name": "unknown_zero_constant_1A54",
        "confidence": "low",
        "evidence": "59 items; ALL val=0. Adjacent to 0x10001A53; schema tag.",
    },
    0x100020C4: {
        "name": "effect_ref_18_20C4",
        "confidence": "medium",
        "evidence": "59 items; 0 (25x) else 0x70XXXXXX effect FIDs — ~34 items "
                    "carry FIDs (0x70001C80, 0x70000724, etc.). Active optional "
                    "effect_ref slot.",
    },
    0x10009F95: {
        "name": "unknown_zero_constant_9F95",
        "confidence": "low",
        "evidence": "59 items; ALL val=0. Adjacent to 0x10009F97; schema tag.",
    },
    0x10009F97: {
        "name": "unknown_zero_constant_9F97",
        "confidence": "low",
        "evidence": "59 items; ALL val=0. Adjacent to 0x10009F95; schema tag.",
    },
    # 56-54 count tier
    0x10000E54: {
        "name": "unknown_float_constant_1_E54",
        "confidence": "low",
        "evidence": "56 items; mostly float 1.0 (55/56); one item ~1.35. Another "
                    "float-1.0 constant key (like 0x100007BC, 0x10002F9E).",
    },
    0x100007B6: {
        "name": "unknown_float_constant_1_7B6",
        "confidence": "low",
        "evidence": "54 items; ALL val=0x3F800000 (float 1.0). Part of the float "
                    "coefficient cluster near 0x100007BC.",
    },
    0x100037A8: {
        "name": "unknown_packed_id_37A8",
        "confidence": "low",
        "evidence": "54 items; packed values (0x0072C200 = 42x, 0x000A1D00 = 10x). "
                    "Note: 0x0072C200 contains bytes 72C2 00, matching key "
                    "0x100072C2 low bytes — another packed-ID cross-ref pattern.",
    },
    0x10003CEE: {
        "name": "unknown_flags_3CEE",
        "confidence": "low",
        "evidence": "54 items; medium integer: 0 (12x), 32768 (0x8000, 11x), "
                    "16 (10x), plus other values. Bitfield pattern (bit 15 or bit 4).",
    },
    # 53-count tier (Schema tag cluster — all appear on 'Sheet Music' items)
    0x100027A7: {
        "name": "unknown_zero_constant_27A7",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100027XX zero-constant "
                    "cluster appearing on Sheet Music sub-schema items.",
    },
    0x100027AA: {
        "name": "unknown_zero_constant_27AA",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100027XX zero-constant cluster.",
    },
    0x100027AB: {
        "name": "unknown_zero_constant_27AB",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100027XX zero-constant cluster.",
    },
    0x100027B1: {
        "name": "unknown_zero_constant_27B1",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100027XX zero-constant cluster.",
    },
    0x100027B4: {
        "name": "unknown_zero_constant_27B4",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100027XX zero-constant cluster.",
    },
    0x100020F9: {
        "name": "unknown_zero_constant_20F9",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100020XX zero-constant cluster.",
    },
    0x100020FA: {
        "name": "unknown_zero_constant_20FA",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100020XX zero-constant cluster.",
    },
    0x100020FD: {
        "name": "unknown_zero_constant_20FD",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100020XX zero-constant cluster.",
    },
    0x100020FE: {
        "name": "unknown_zero_constant_20FE",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100020XX zero-constant cluster.",
    },
    0x10003460: {
        "name": "unknown_zero_constant_3460",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x10003463: {
        "name": "unknown_zero_constant_3463",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x10001804: {
        "name": "unknown_zero_constant_1804",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x100024AA: {
        "name": "unknown_constant_24AA",
        "confidence": "low",
        "evidence": "53 items; ALL val=0x0024AB00. Packed constant; low bytes "
                    "0x24AB match the adjacent key ID + 1. Another instance of "
                    "the packed-next-key-ID pattern.",
    },
    0x10000804: {
        "name": "unknown_packed_data_804",
        "confidence": "low",
        "evidence": "53 items; large diverse packed values (0x31643804, 0x31643704, "
                    "0x31643104). Byte [3]=0x31, [2]=0x64, bytes [1:0] vary. "
                    "Similar structure to 0x1000080F.",
    },
    0x10003157: {
        "name": "unknown_float_sparse_3157",
        "confidence": "low",
        "evidence": "53 items; mostly 0 (51x), 2 items have float 1.0. Sparse "
                    "optional float.",
    },
    0x10001809: {
        "name": "unknown_ref_or_zero_1809",
        "confidence": "low",
        "evidence": "53 items; mostly 0 (47x), two items carry 0x70XXXXXX effect "
                    "FIDs. Very sparse optional effect ref or zero slot.",
    },
    # --- Tier-5 continued (53–52 occurrences) ---
    # Sheet Music cluster zero constants
    0x100027B5: {
        "name": "unknown_zero_constant_27B5",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x100020FF: {
        "name": "unknown_zero_constant_20FF",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Member of the 0x100020XX zero-constant cluster.",
    },
    0x10003466: {
        "name": "unknown_zero_constant_3466",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x10003467: {
        "name": "unknown_zero_constant_3467",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x100027BB: {
        "name": "unknown_zero_constant_27BB",
        "confidence": "low",
        "evidence": "53 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x100035ED: {
        "name": "unknown_zero_constant_35ED",
        "confidence": "low",
        "evidence": "52 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    0x10003BE6: {
        "name": "unknown_zero_constant_3BE6",
        "confidence": "low",
        "evidence": "52 items; ALL val=0. Sheet Music sub-schema zero-constant cluster.",
    },
    # Sub-schema constant (value=1, not 0)
    0x10004B8B: {
        "name": "unknown_constant_1_4B8B",
        "confidence": "low",
        "evidence": "53 items; ALL val=1. Sheet Music sub-schema; unusual in being "
                    "always-1 rather than always-0.",
    },
    # Adjacent pair 1D46/1D47 (small-int + ref)
    0x10001D46: {
        "name": "unknown_small_int_1D46",
        "confidence": "low",
        "evidence": "53 items; mostly 0 (48x), else 28 (3x) or 38 (1x). Adjacent "
                    "to 0x10001D47 which carries the corresponding 0x10XXXXXX refs.",
    },
    0x10001D47: {
        "name": "unknown_key_ref_1D47",
        "confidence": "low",
        "evidence": "53 items; mostly 0 (48x), else 0x10XXXXXX refs (0x100098CF "
                    "3x, 0x100098CD 1x). Adjacent to 0x10001D46 (small-int index). "
                    "The non-zero items in D46/D47 co-occur (same 4 items).",
    },
    # Float pair: constant 0.5 and 0.75
    0x10000868: {
        "name": "unknown_float_half_868",
        "confidence": "low",
        "evidence": "53 items; ALL val=0x3F000000 (0.5 as IEEE 754 float32). "
                    "Adjacent to 0x10000869 (0.75). Constant fractional pair — "
                    "possibly probability weights or damage fractions.",
    },
    0x10000869: {
        "name": "unknown_float_threequarters_869",
        "confidence": "low",
        "evidence": "53 items; ALL val=0x3F400000 (0.75 as IEEE 754 float32). "
                    "Adjacent to 0x10000868 (0.5). Constant fractional pair.",
    },
    # Near-constant shared effect_ref (most items point to same FID)
    0x10002C92: {
        "name": "effect_ref_shared_2C92",
        "confidence": "medium",
        "evidence": "53 items; mostly the same FID 0x700007D2 (43/53). Like "
                    "0x10001B8D, this slot is near-constant across items — a "
                    "globally shared effect entry rather than per-item. Occasional "
                    "variant FIDs (0x70000FB2, 0x70002796).",
    },
    # Packed constant keys
    0x10003CEA: {
        "name": "unknown_packed_id_3CEA",
        "confidence": "low",
        "evidence": "53 items; mostly val=0x000C3E01 (52x). Bytes 0xC3E match "
                    "key 0x10000C3E (zero_constant_C3E) — another packed-key-ID "
                    "cross-reference pattern.",
    },
    0x1000573A: {
        "name": "unknown_constant_573A",
        "confidence": "low",
        "evidence": "53 items; val=0x00A1B101 (35x) or 0x00A1B100 (18x). "
                    "Packed constant differing only in low bit.",
    },
    # Binary non-zero enum
    0x10005795: {
        "name": "unknown_binary_nonzero_5795",
        "confidence": "low",
        "evidence": "52 items; binary 8 (45x) vs 32 (7x) — no zeros. Both values "
                    "are non-zero, similar to 0x10000CF8 (binary 2/1 pattern).",
    },
    # --- Tier-6 keys (50–52 occurrences) ---
    # All-constant / float-1.0 keys
    0x1000204B: {
        "name": "unknown_float_constant_1_204B",
        "confidence": "low",
        "evidence": "52 items; ALL val=0x3F800000 (float 1.0). Another float-1.0 "
                    "constant (like 0x10002F9E, 0x100007B6).",
    },
    0x10001D5A: {
        "name": "unknown_float_constant_1_1D5A",
        "confidence": "low",
        "evidence": "52 items; ALL val=0x3F800000 (float 1.0). Sheet Music sub-schema.",
    },
    # Packed constant IDs
    0x10001D51: {
        "name": "unknown_constant_1D51",
        "confidence": "low",
        "evidence": "52 items; ALL val=0x00228A00. Adjacent to 0x10001D50 cluster. "
                    "Packed constant.",
    },
    0x10001819: {
        "name": "unknown_packed_id_1819",
        "confidence": "low",
        "evidence": "52 items; val=0x00228B01 (39x) or 0x00228B00 (9x) or "
                    "0x003BE900 (3x). Packed constant with low-bit variant.",
    },
    0x10003F36: {
        "name": "unknown_packed_id_3F36",
        "confidence": "low",
        "evidence": "52 items; val=0x003F3700 (36x) or 0x00885500 (16x). Packed "
                    "constant; two variants, possibly two schema families.",
    },
    0x10003F38: {
        "name": "unknown_constant_3F38",
        "confidence": "low",
        "evidence": "52 items; ALL val=0x001DA800. Adjacent to 0x10003F36. Packed constant.",
    },
    0x10001822: {
        "name": "unknown_packed_id_1822",
        "confidence": "low",
        "evidence": "51 items; val=0x001D5B00 (34x) or 0x001D5C00 (16x). Bytes "
                    "0x1D5B/1D5C match nearby key IDs (0x10001D5B/5C). Packed ID.",
    },
    0x100010BC: {
        "name": "unknown_constant_10BC",
        "confidence": "low",
        "evidence": "51 items; ALL val=0x00031401. Adjacent to 0x100010BB "
                    "(chain_node_10BB). Constant companion value.",
    },
    # Zero constants
    0x10001D58: {
        "name": "unknown_zero_constant_1D58",
        "confidence": "low",
        "evidence": "52 items; ALL val=0. Sheet Music sub-schema; adjacent to "
                    "0x10001D5A (float-1.0) and 0x10001D59.",
    },
    0x10001D59: {
        "name": "unknown_zero_constant_1D59",
        "confidence": "low",
        "evidence": "52 items; ALL val=0. Sheet Music sub-schema.",
    },
    0x10002889: {
        "name": "unknown_zero_constant_2889",
        "confidence": "low",
        "evidence": "52 items; ALL val=0. Sheet Music sub-schema zero-constant.",
    },
    0x10003BE5: {
        "name": "unknown_zero_constant_3BE5",
        "confidence": "low",
        "evidence": "51 items; ALL val=0. Adjacent to 0x10003BE4/BE6.",
    },
    0x100027BC: {
        "name": "unknown_zero_constant_27BC",
        "confidence": "low",
        "evidence": "51 items; ALL val=0. Member of the 0x100027XX zero-constant cluster.",
    },
    0x100027BE: {
        "name": "unknown_zero_constant_27BE",
        "confidence": "low",
        "evidence": "51 items; ALL val=0. Member of the 0x100027XX zero-constant cluster.",
    },
    0x100027BF: {
        "name": "unknown_zero_constant_27BF",
        "confidence": "low",
        "evidence": "51 items; ALL val=0. Member of the 0x100027XX zero-constant cluster.",
    },
    0x10002015: {
        "name": "unknown_zero_constant_2015",
        "confidence": "low",
        "evidence": "50 items; ALL val=0.",
    },
    0x1000278F: {
        "name": "unknown_zero_constant_278F",
        "confidence": "low",
        "evidence": "50 items; ALL val=0. Member of the 0x100027XX cluster.",
    },
    # Near-binary flags
    0x10002DC3: {
        "name": "unknown_flag_2DC3",
        "confidence": "low",
        "evidence": "52 items; near-binary: 0 (50x) vs 1 (2x). Boolean flag.",
    },
    0x10002B06: {
        "name": "unknown_flag_2B06",
        "confidence": "low",
        "evidence": "51 items; near-binary: 0 (50x) vs 2 (1x). Rarely-set flag.",
    },
    # Small-enum keys
    0x10005794: {
        "name": "unknown_flag_enum_5794",
        "confidence": "low",
        "evidence": "52 items; 3 vals: 8 (50x), 40 (1x), 0 (1x). Adjacent to "
                    "0x10005795 (binary 8/32). Mostly-8 enum.",
    },
    0x10002D42: {
        "name": "unknown_small_int_2D42",
        "confidence": "low",
        "evidence": "52 items; mostly 0 (45x), else 20/12/22. Small index or mode.",
    },
    0x10003BE4: {
        "name": "unknown_small_int_3BE4",
        "confidence": "low",
        "evidence": "51 items; mostly 0 (46x), else 5 (4x) or 50 (1x). Adjacent "
                    "to 0x10003BE5/BE6 (zero constants).",
    },
    0x100007FD: {
        "name": "unknown_binary_nonzero_7FD",
        "confidence": "low",
        "evidence": "51 items; binary 2 (45x) vs 3 (6x) — no zeros. Adjacent to "
                    "the 7E2/7F0/7F5/7F8/7BC float cluster.",
    },
    # Float 0.25 constant — completes the 867/868/869 = 0.25/0.5/0.75 triplet
    0x10000867: {
        "name": "unknown_float_quarter_867",
        "confidence": "low",
        "evidence": "51 items; ALL val=0x3E800000 (0.25 as IEEE 754 float32). "
                    "Adjacent to 0x10000868 (0.5) and 0x10000869 (0.75). Together "
                    "the 867/868/869 triple forms a 0.25/0.5/0.75 constant "
                    "fractional progression (probability thresholds or damage fractions).",
    },
    # New 0x10BC chain link
    0x10BC0110: {
        "name": "unknown_chain_ptr_BC01",
        "confidence": "low",
        "evidence": "51 items; ALL val=0x10BC1000 (key ID). Head of the "
                    "0x10BC0110→0x10BC1000 pointer sub-chain. Same pattern as "
                    "0x10BB0000→0x10BB1000 and 0x10720001→0x10721000.",
    },
    0x10BC1000: {
        "name": "unknown_chain_value_BC10",
        "confidence": "low",
        "evidence": "51 items; ALL val=0x14011000. Terminal value in the "
                    "0x10BC0110→0x10BC1000 chain.",
    },
    # 4-member optional key-ref cluster (2252–2255)
    0x10002252: {
        "name": "unknown_ref_slot_A_2252",
        "confidence": "low",
        "evidence": "50 items; mostly 0 (47x), else 0x10XXXXXX refs. Part of the "
                    "2252/53/54/55 4-member cluster — same 3 items have non-zero "
                    "values across all four slots. Optional key-ref quadruple.",
    },
    0x10002253: {
        "name": "unknown_ref_slot_B_2253",
        "confidence": "low",
        "evidence": "50 items; mostly 0 (47x), else 0x10XXXXXX refs. Part of the "
                    "2252/53/54/55 optional key-ref quadruple.",
    },
    0x10002254: {
        "name": "unknown_ref_slot_C_2254",
        "confidence": "low",
        "evidence": "50 items; mostly 0 (47x), else 0x10XXXXXX refs. Part of the "
                    "2252/53/54/55 optional key-ref quadruple.",
    },
    0x10002255: {
        "name": "unknown_ref_slot_D_2255",
        "confidence": "low",
        "evidence": "50 items; mostly 0 (47x), else 0x10XXXXXX refs. Part of the "
                    "2252/53/54/55 optional key-ref quadruple.",
    },
    # --- Tier-6 continued: remaining 50-count keys ---
    # 0x100020XX zero-constant cluster (Raging Torrent sub-schema)
    0x1000201A: {"name": "unknown_zero_constant_201A", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x1000201C: {"name": "unknown_zero_constant_201C", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x1000201F: {"name": "unknown_zero_constant_201F", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x10002020: {"name": "unknown_zero_constant_2020", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x10002021: {"name": "unknown_zero_constant_2021", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x10002022: {"name": "unknown_zero_constant_2022", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x10002027: {"name": "unknown_zero_constant_2027", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x10002028: {"name": "unknown_zero_constant_2028", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x1000202A: {"name": "unknown_zero_constant_202A", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    0x1000202C: {"name": "unknown_zero_constant_202C", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100020XX sub-schema zero-constant."},
    # 0x100027XX additional zero constants
    0x10002795: {"name": "unknown_zero_constant_2795", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100027XX sub-schema zero-constant."},
    0x1000279D: {"name": "unknown_zero_constant_279D", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100027XX sub-schema zero-constant."},
    0x1000279E: {"name": "unknown_zero_constant_279E", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100027XX sub-schema zero-constant."},
    0x100027A0: {"name": "unknown_zero_constant_27A0", "confidence": "low",
                 "evidence": "50 items; ALL val=0. 0x100027XX sub-schema zero-constant."},
    # Packed constant IDs
    0x10001AE5: {
        "name": "unknown_packed_id_1AE5",
        "confidence": "low",
        "evidence": "50 items; val=0x00201E00 (45x) or 0x00201E01 (5x). Packed "
                    "constant with low-bit variant; low bytes 0x201E adjacent to "
                    "the 0x100020XX cluster.",
    },
    0x100030E1: {
        "name": "unknown_packed_id_30E1",
        "confidence": "low",
        "evidence": "50 items; val=0x002AE900 (43x) or 0x002AE901 (7x). Packed "
                    "constant with low-bit variant.",
    },
    0x1000354D: {
        "name": "unknown_ref_or_zero_354D",
        "confidence": "low",
        "evidence": "50 items; mostly 0 (46x), one 0x70XXXXXX FID. Very sparse "
                    "optional effect_ref slot.",
    },
    0x100019B8: {
        "name": "unknown_constant_19B8",
        "confidence": "low",
        "evidence": "50 items; ALL val=0x001E3200. Packed constant; bytes 0x1E32 "
                    "adjacent to the 0x10001E2X key cluster.",
    },
    # 0x10001E2X sub-schema: mostly-zero with sparse float-1.0 (Commendations schema)
    0x10001E2C: {"name": "unknown_float_sparse_1_1E2C", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E2D: {"name": "unknown_float_sparse_1_1E2D", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E2E: {"name": "unknown_float_sparse_1_1E2E", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E2F: {"name": "unknown_float_sparse_1_1E2F", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E30: {"name": "unknown_float_sparse_1_1E30", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E36: {"name": "unknown_float_sparse_1_1E36", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E37: {"name": "unknown_float_sparse_1_1E37", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E38: {"name": "unknown_float_sparse_1_1E38", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    0x10001E39: {"name": "unknown_float_sparse_1_1E39", "confidence": "low",
                 "evidence": "50 items; mostly 0 (49x), one float 1.0. Commendations sub-schema."},
    # Near-zero flags
    0x10002B05: {"name": "unknown_zero_constant_2B05", "confidence": "low",
                 "evidence": "50 items; ALL val=0."},
    0x10003B6F: {"name": "unknown_zero_constant_3B6F", "confidence": "low",
                 "evidence": "50 items; ALL val=0."},
    0x1000373B: {"name": "unknown_zero_constant_373B", "confidence": "low",
                 "evidence": "50 items; ALL val=0."},
    # --- Tier-7: non-trivial 40-49 count keys ---
    # Sparse effect_ref
    0x10005403: {
        "name": "effect_ref_19_5403",
        "confidence": "medium",
        "evidence": "44 items; mostly 0 (40x), sparse 0x70XXXXXX FIDs. Adjacent "
                    "to 0x10005405 (effect_ref_15). Sparse optional effect_ref slot.",
    },
    # Float-1.0 constant
    0x10001036: {
        "name": "unknown_float_constant_1_1036",
        "confidence": "low",
        "evidence": "44 items; ALL val=0x3F800000 (float 1.0). Another float-1.0 "
                    "constant in the large coefficient cluster.",
    },
    # Packed constant in the 28XX family (adjacent to 2840/2841/2842/2843)
    0x10002841: {
        "name": "unknown_packed_id_2841",
        "confidence": "low",
        "evidence": "49 items; val=0x00284200 (48x) or 0x00279000 (1x). Adjacent "
                    "to 0x10002842 (constant 0x00284300). Another packed ID in "
                    "the 2840/41/42/43 adjacent cluster.",
    },
    # All-val-2 constant
    0x10002361: {
        "name": "unknown_constant_2_2361",
        "confidence": "low",
        "evidence": "47 items; ALL val=2. Unusual constant-2 field.",
    },
    # Packed constant
    0x10002D1F: {
        "name": "unknown_constant_2D1F",
        "confidence": "low",
        "evidence": "45 items; ALL val=0x000E8701. Packed constant.",
    },
    # Small enum (all-nonzero, similar to CF8 and 7FD patterns)
    0x10000E2A: {
        "name": "unknown_enum_E2A",
        "confidence": "low",
        "evidence": "46 items; 3 vals: 2 (25x), 4 (19x), 3 (2x) — no zeros. "
                    "All-nonzero small enum similar to 0x10000CF8.",
    },
    # Near-constant 2 (mostly 2, one 1)
    0x10001898: {
        "name": "unknown_flag_near2_1898",
        "confidence": "low",
        "evidence": "47 items; val=2 (46x) or 1 (1x). Near-constant; both values "
                    "non-zero. Similar to 0x10000CF8 pattern.",
    },
    # Small int enums
    0x10002125: {
        "name": "unknown_small_enum_2125",
        "confidence": "low",
        "evidence": "47 items; vals 1 (34x), 2 (7x), 3 (2x), 4 (2x), 5 (2x). "
                    "Small consecutive enum starting at 1.",
    },
    0x1000277E: {
        "name": "unknown_small_enum_277E",
        "confidence": "low",
        "evidence": "44 items; vals 1 (16x), 5 (14x), 2 (7x), 3 (4x), 4 (3x). "
                    "Small enum, values 1–5. No zeros.",
    },
    0x10000E84: {
        "name": "unknown_small_int_E84",
        "confidence": "low",
        "evidence": "46 items; diverse small ints; adjacent to E87 "
                    "(unknown_content_ref_E87).",
    },
    # Sparse small-int keys
    0x10002432: {
        "name": "unknown_flag_near0_2432",
        "confidence": "low",
        "evidence": "49 items; mostly 0 (48x), one item=1. Rarely-set flag.",
    },
    0x100034B7: {
        "name": "unknown_flag_near0_34B7",
        "confidence": "low",
        "evidence": "43 items; mostly 0 (41x), 2 items=8.",
    },
    0x10009F19: {
        "name": "unknown_flag_near0_9F19",
        "confidence": "low",
        "evidence": "45 items; mostly 0 (43x), sparse small ints.",
    },
    0x1000283F: {
        "name": "unknown_packed_id_283F",
        "confidence": "low",
        "evidence": "47 items; val=0x0007EB00 (45x), two variants. Adjacent to "
                    "0x10002840/41/42/43 cluster. Packed ID.",
    },
    0x100007DC: {
        "name": "unknown_flag_near0_7DC",
        "confidence": "low",
        "evidence": "47 items; mostly 0 (44x), sparse small ints. Adjacent to "
                    "the 7E2/7F0/7F5/7F8/7BC/7B8/7FD float cluster.",
    },
    0x100008AB: {
        "name": "unknown_flag_near0_8AB",
        "confidence": "low",
        "evidence": "40 items; mostly 0 (39x), one item=3.",
    },
    # --- Tier-7 continued: remaining 37-50 count keys ---
    # Zero constants
    0x10003DAD: {"name": "unknown_zero_constant_3DAD", "confidence": "low",
                 "evidence": "50 items; ALL val=0."},
    0x100012DC: {"name": "unknown_constant_1_12DC", "confidence": "low",
                 "evidence": "49 items; ALL val=1. Adjacent to 0x100012DB; always-1 constant."},
    0x10002CC1: {"name": "unknown_zero_constant_2CC1", "confidence": "low",
                 "evidence": "49 items; ALL val=0."},
    0x1000254C: {"name": "unknown_zero_constant_254C", "confidence": "low",
                 "evidence": "49 items; ALL val=0."},
    0x10000A70: {"name": "unknown_zero_constant_A70", "confidence": "low",
                 "evidence": "49 items; ALL val=0."},
    0x10002275: {"name": "unknown_zero_constant_2275", "confidence": "low",
                 "evidence": "49 items; ALL val=0."},
    0x10002279: {"name": "unknown_zero_constant_2279", "confidence": "low",
                 "evidence": "49 items; ALL val=0."},
    0x1000227C: {"name": "unknown_zero_constant_227C", "confidence": "low",
                 "evidence": "49 items; ALL val=0."},
    0x1000227F: {"name": "unknown_zero_constant_227F", "confidence": "low",
                 "evidence": "49 items; ALL val=0."},
    0x10000CF6: {"name": "unknown_zero_constant_CF6", "confidence": "low",
                 "evidence": "48 items; ALL val=0."},
    0x10003B25: {"name": "unknown_zero_constant_3B25", "confidence": "low",
                 "evidence": "48 items; ALL val=0."},
    0x100011A5: {"name": "unknown_zero_constant_11A5", "confidence": "low",
                 "evidence": "46 items; ALL val=0."},
    0x1000519C: {"name": "unknown_zero_constant_519C", "confidence": "low",
                 "evidence": "45 items; ALL val=0."},
    0x10002888: {"name": "unknown_zero_constant_2888", "confidence": "low",
                 "evidence": "41 items; ALL val=0."},
    # Packed constants
    0x10002D44: {
        "name": "unknown_packed_id_2D44",
        "confidence": "low",
        "evidence": "50 items; val=0x0030FF01 (33x) or 0x002B0701 (16x). Two "
                    "packed-ID variants; low-bit 0x01 on most items.",
    },
    0x100012DB: {
        "name": "unknown_packed_ref_12DB",
        "confidence": "low",
        "evidence": "49 items; ALL val=0x12A30200. Bytes 0x12A3 match key "
                    "0x100012A3 (unknown_packed_ref_12A3). Part of the 12A3/A4/A6/DB/DC "
                    "augment slot metadata cluster. Adjacent to 12DC (always-1 count).",
    },
    0x10001B3B: {
        "name": "unknown_packed_id_1B3B",
        "confidence": "low",
        "evidence": "39 items; val=0x0018AA01 (20x), 0x0018AA00 (6x), 0x00011100 "
                    "(4x). Bytes 0x18AA match key 0x100018AA (one of the 0xA4487500 "
                    "magic-constant keys). Packed cross-ref.",
    },
    0x1000062E: {
        "name": "unknown_packed_id_62E",
        "confidence": "low",
        "evidence": "37 items; val=0x00029100 (28x) or 0x00029101 (2x). Packed "
                    "constant with low-bit variant.",
    },
    # Chain node 0x1036XXXX (like 0x10730300 / 0x10761000)
    0x10361000: {
        "name": "unknown_chain_value_3610",
        "confidence": "low",
        "evidence": "44 items; ALL val=0x00001000 (4096). Key in the 0x103XXXXX "
                    "range, following the same terminal-chain pattern as "
                    "0x10730300/10731000/10760000. Constant terminal value.",
    },
    # Key-selector (value is a known property key ID)
    0x10000914: {
        "name": "unknown_key_selector_914",
        "confidence": "low",
        "evidence": "46 items; values are known property key IDs: 0x10001C60 "
                    "(unknown_cluster_1C60, 26x) and 0x10000B32 (unknown_item_flags_B32, "
                    "20x). This key points to another property key, likely selecting "
                    "which field stores the primary value (similar to 0x10000B22).",
    },
    0x10000D88: {
        "name": "unknown_key_ref_D88",
        "confidence": "low",
        "evidence": "45 items; mostly 0x10000907 (35x, another unknown key), "
                    "occasionally 0 or other 0x10XXXXXX refs. Another key-selector "
                    "in a D88→907 chain.",
    },
    0x10000907: {
        "name": "unknown_key_ref_907",
        "confidence": "low",
        "evidence": "40 items; values are 0x10XXXXXX key refs (0x10004C39, "
                    "0x10000D85) and one float-like outlier. Pointed to by "
                    "0x10000D88 (key_ref_D88). Part of a key-ref chain.",
    },
    # Active effect_ref slots (diverse 0x70XXXXXX values)
    0x10003969: {
        "name": "effect_ref_20_3969",
        "confidence": "medium",
        "evidence": "38 items; diverse 0x70XXXXXX effect FIDs (0x700092F8 9x, "
                    "0x7001DD31 4x, etc.). Active optional effect_ref slot with "
                    "item-specific FIDs.",
    },
    0x10002CB1: {
        "name": "effect_ref_21_2CB1",
        "confidence": "medium",
        "evidence": "39 items; mostly 0 (33x), sparse 0x70XXXXXX FIDs. Adjacent "
                    "to 0x10002CB2. Sparse optional effect_ref slot.",
    },
    # Float key
    0x100024ED: {
        "name": "unknown_float_variable_24ED",
        "confidence": "low",
        "evidence": "48 items; float32: 1.0 (34x), 0.0 (7x), 1.5 (4x). Variable "
                    "coefficient — unlike the all-1.0 constant keys, this varies.",
    },
    # Bitfield key (high-bit set values)
    0x10000569: {
        "name": "unknown_bitfield_569",
        "confidence": "low",
        "evidence": "47 items; values: 0x80000000 (35x), 0xC0000100 (6x), "
                    "0xC0008000 (2x). All have bits 31/30 set (signed negative "
                    "range). Likely a bitfield or packed flags register.",
    },
    # Small enum keys
    0x10000839: {
        "name": "unknown_small_enum_839",
        "confidence": "low",
        "evidence": "49 items; 6 distinct values: 14 (20x), 18 (14x), 15 (10x), "
                    "and others. All non-zero. Adjacent to 0x10000854/8A3/8B9.",
    },
    0x1000083B: {
        "name": "unknown_packed_id_83B",
        "confidence": "low",
        "evidence": "49 items; packed values 0x23F50B00 (29x), 0x23F50C00 (16x), "
                    "0x23F50D00 (3x). Bytes 0x23F5 match key 0x100023F5 "
                    "(unknown_signed_modifier_23F5). Packed key-ID cross-ref.",
    },
    0x10000855: {
        "name": "unknown_small_enum_855",
        "confidence": "low",
        "evidence": "42 items; 8 distinct values: 2/3/6/others. Adjacent to "
                    "0x10000854 (small_int_854). Possibly a sub-type or flag.",
    },
    0x10003957: {
        "name": "unknown_small_enum_3957",
        "confidence": "low",
        "evidence": "37 items; 5 vals: 1 (17x), 3 (12x), 2 (5x), others. "
                    "Adjacent to 0x10003972 (0xA4487500 constant) cluster.",
    },
    # --- Tier-8: remaining 28-37 count keys ---
    # Effect_ref slots (diverse 0x70XXXXXX)
    0x1000395B: {
        "name": "effect_ref_22_395B",
        "confidence": "medium",
        "evidence": "37 items; diverse 0x70XXXXXX effect FIDs (0x70008EE2 9x, "
                    "0x7001CA59 2x, 0x7001CA58 2x, etc.). Active optional "
                    "effect_ref slot with item-specific FIDs.",
    },
    0x10001AE9: {
        "name": "effect_ref_23_1AE9",
        "confidence": "medium",
        "evidence": "35 items; diverse 0x70XXXXXX effect FIDs (0x7000351C 10x, "
                    "0x7000355B 8x, 0x7000459C 7x, etc.). e.g. 'Memory of "
                    "Animated Objects', 'Brute Fighting'. Active effect_ref slot.",
    },
    0x10001899: {
        "name": "effect_ref_24_1899",
        "confidence": "medium",
        "evidence": "29 items; mostly 0 (22x), sparse 0x70XXXXXX FIDs "
                    "(0x70003F0A 2x, 0x70004052 2x, etc.). e.g. 'Corrosive "
                    "Arrows', 'Ammo'. Sparse optional effect_ref slot.",
    },
    0x10001824: {
        "name": "effect_ref_25_1824",
        "confidence": "medium",
        "evidence": "29 items (per frequency scan); diverse 0x70XXXXXX FIDs "
                    "in the 0x70007XXX range. e.g. 'Favored Soul', 'Raging "
                    "Torrent[mn]'. Optional effect_ref slot.",
    },
    # Zero constants
    0x10002EC0: {
        "name": "unknown_zero_constant_2EC0",
        "confidence": "low",
        "evidence": "36 items; ALL val=0. Co-occurs with 0x10002EC1 on runearm "
                    "items: 'Runearm Knife Blast', 'Opportunist'. Likely a "
                    "schema placeholder in the runearm property cluster.",
    },
    0x1000478D: {
        "name": "unknown_zero_constant_478D",
        "confidence": "low",
        "evidence": "32 items; ALL val=0. Co-occurs with 0x10002EC0/EC1 on "
                    "runearm items. Schema-type placeholder.",
    },
    # Sparse/small enums
    0x10002EC1: {
        "name": "unknown_sparse_enum_2EC1",
        "confidence": "low",
        "evidence": "36 items; 35 zero, 1 val=2 ('Firebrand Sergeant[E]'). "
                    "Co-occurs with 0x10002EC0 on runearm items. Near-zero "
                    "enum, possibly a sub-mode flag.",
    },
    # Integer constants
    0x10000B5B: {
        "name": "unknown_constant_0B5B",
        "confidence": "low",
        "evidence": "36 items; ALL val=0x000E7C01 (949249). Constant across "
                    "all items; e.g. 'Corrosive Arrows', 'Ammo'. Likely a "
                    "packed FID or table offset shared by ranged-ammo items.",
    },
    0x10000026: {
        "name": "unknown_constant_1_26",
        "confidence": "low",
        "evidence": "29 items; ALL val=1. Co-occurs on quest/ability items "
                    "including long quest-description entries and 'Fire 3d6'. "
                    "Constant boolean-like flag.",
    },
    0x100023BD: {
        "name": "unknown_sentinel_FF_23BD",
        "confidence": "low",
        "evidence": "29 items; ALL val=0xFFFFFFFF (4294967295). Constant "
                    "sentinel/null marker. e.g. 'Bolt[E]', 'Dolnozz[mn]'. "
                    "May indicate 'not set' or '-1' for a signed field.",
    },
    # 0x0D88XXXX packed values (runearm-specific resource refs)
    0x1000117C: {
        "name": "unknown_0D88_packed_117C",
        "confidence": "low",
        "evidence": "35 items; values in 0x0D88XXXX range: 0x0D880400 (20x), "
                    "0x0D880200 (10x), 0x0D880500 (5x). Namespace 0x0D is "
                    "unusual (not item/effect/key). Exclusively on runearm items "
                    "('Runearm Knife Blast', 'Opportunist'). Likely a packed "
                    "resource ID for a runearm-specific sub-archive.",
    },
    # Small enum / small integer keys
    0x10000A1D: {
        "name": "weapon_type_id",
        "confidence": "medium",
        "evidence": "4,092 items cross-referenced; 91% accuracy vs wiki attack_mod. "
                    "Enum 1-16 partitioning weapons by type: val=1 is largest group "
                    "(STR weapons like longswords, 1,707x), val=4 maps to finesse "
                    "weapons (STR,DEX, 132x). Wiki attack_mod is derived from weapon "
                    "type, explaining the correlation.",
    },
    0x1000139B: {
        "name": "unknown_small_int_139B",
        "confidence": "low",
        "evidence": "31 items; 9 distinct vals: 5 (9x), 10 (8x), 20 (6x), "
                    "1 (3x), 8 (1x), up to 21. e.g. 'Solid Fog', 'Lava "
                    "Caves: Time is Money'. Scaling values — possibly a "
                    "caster level, duration multiplier, or tier parameter.",
    },
    0x10003968: {
        "name": "unknown_small_enum_3968",
        "confidence": "low",
        "evidence": "28 items; 3 distinct vals: 1 (23x), 2 (4x), 7 (1x). "
                    "e.g. 'Orcish Greatclub Attack I', 'Wooden Tower Shield[E]'. "
                    "Adjacent to 0x10003969 (effect_ref_20). Likely a sub-type "
                    "selector or tier index.",
    },
    0x10000545: {
        "name": "unknown_quantity_545",
        "confidence": "low",
        "evidence": "29 items; vals 100 (15x), 1 (10x), 500 (2x), 99 (1x), "
                    "10000 (1x). Appears on quest-entry items and effect items "
                    "like 'Fire 3d6'. The 100/1/500/99 range suggests a "
                    "percentage or quantity field.",
    },
    # Float values near ~8.0 (0x41XXXXXX float32)
    0x1000000E: {
        "name": "unknown_float8_0E",
        "confidence": "low",
        "evidence": "32 items; float32 values consistently ~8.0–8.2 "
                    "(0x41009B01=8.038, 0x41002BD1=8.011, 0x4100014=8.000). "
                    "e.g. 'Memory of Animated Objects'. Also 2 zero values. "
                    "May be a base stat value or version coefficient.",
    },
    0x10001D36: {
        "name": "unknown_float8_1D36",
        "confidence": "low",
        "evidence": "29 items; float32 ~8.0–8.2 (0x4100487D=8.018 12x, "
                    "0x410375B9=8.216 3x, etc.), plus 7 zeros. e.g. 'Lute of "
                    "the Summer Knight', 'Lava Caves: Time is Money'. Parallel "
                    "to 0x1000000E — same narrow float range.",
    },
    # Sparse integer (mixed zeros + sparse values)
    0x10000B4E: {
        "name": "unknown_sparse_int_B4E",
        "confidence": "low",
        "evidence": "31 items; mostly 0 (19x), then val=2 (9x), 256 (2x), "
                    "0x00800000 (1x). e.g. 'Opportunist', 'Epic Ring of Unknown "
                    "Origins'. The 0x00800000 outlier and 256-step increments "
                    "suggest a bitfield or shift-encoded integer.",
    },
    # Packed/structured values (XXYYZZ00 / XXYYZZ01 byte pattern)
    0x10001B38: {
        "name": "unknown_packed_1B38",
        "confidence": "low",
        "evidence": "31 items; values with pattern 0xXXYY00: 0x001B3900 (11x), "
                    "0x00056600 (10x), 0x00034B00 (5x), 0x006F7D00 (4x). Low "
                    "byte is always 0x00 or 0x01. Appears on quest/ability items. "
                    "Likely a packed FID or index reference.",
    },
    0x10001620: {
        "name": "unknown_packed_1620",
        "confidence": "low",
        "evidence": "30 items; values 0x00000800 (16x), 0x0007FD00 (8x), "
                    "0x001B4400 (6x). Low byte varies 0x00. Appears on augment "
                    "crystal items ('Durable Small Augment Crystal'). Likely a "
                    "packed resource ID in the augment system.",
    },
    0x1000111D: {
        "name": "unknown_packed_111D",
        "confidence": "low",
        "evidence": "30 items; near-constant: 0x000A4901 (25x), 0x0008AC00 "
                    "(4x), 0x000A4801 (1x). Items include 'Opportunity Attack "
                    "Observer', 'MOTU Bundle'. Same XXYY00/XXYY01 byte pattern "
                    "as 0x10001B38/1620/1654.",
    },
    0x10001654: {
        "name": "unknown_packed_1654",
        "confidence": "low",
        "evidence": "32 items; near-constant: 0x000A4B00 (31x), 0x000A4B01 "
                    "(1x). e.g. 'Runearm Knife Blast', 'Opportunist'. A single "
                    "packed value shared by nearly all items, low-byte variant "
                    "0x00/0x01.",
    },
    0x10003F37: {
        "name": "unknown_packed_3F37",
        "confidence": "low",
        "evidence": "17 items (probe); near-constant: 0x003F3800 (15x), "
                    "0x00304B00 (2x). e.g. 'The Fated One[mn]', 'Random Loot "
                    "Deconstruct'. Same XXYY00 byte pattern as the packed "
                    "FID cluster.",
    },
    0x10006736: {
        "name": "unknown_packed_6736",
        "confidence": "low",
        "evidence": "28 items; near-constant: 0x000B4E00 (22x), 0x000B4E01 "
                    "(6x). e.g. 'Attack', 'Dissolve'. Same low-byte 0x00/0x01 "
                    "variant pattern as 0x10001654/111D/1620.",
    },
    0x10001D16: {
        "name": "unknown_packed_1D16",
        "confidence": "low",
        "evidence": "29 items; values 0x002CC100 (11x), 0x00267300 (8x), "
                    "0x00254C00 (4x), etc. Low byte alternates 0x00/0x01. "
                    "e.g. 'Bolt[E]', 'Dolnozz[mn]'. Packed FID or index "
                    "reference in the 0x0026/002C range.",
    },
    0x10002364: {
        "name": "unknown_packed_2364",
        "confidence": "low",
        "evidence": "28 items; values 0x00354D00 (18x), 0x000E1A00 (4x), "
                    "0x000E1A01 (3x), etc. Same XXYY00/XXYY01 pattern. "
                    "e.g. 'Bolt[E]', 'Dolnozz[mn]'. Packed sub-archive ref.",
    },
    # 1DCA/1DCB/1DCC triplet (co-occur on 'Bolt[E]', 'Dolnozz[mn]', sheet music)
    0x10001DCA: {
        "name": "unknown_sparse_key_ref_1DCA",
        "confidence": "low",
        "evidence": "29 items; mostly 0 (15x), sparse 0x10XXXXXX key refs "
                    "(0x10001F65, 0x10001F98, 0x10001F72, 0x10002E2D). "
                    "Forms a triplet with 0x10001DCB/DCC. The non-zero values "
                    "are other property key IDs — a key-selector sub-field.",
    },
    0x10001DCB: {
        "name": "unknown_sparse_float_1DCB",
        "confidence": "low",
        "evidence": "29 items; mostly 0 (15x), sparse floats: 30.0 (3x), "
                    "6.0 (2x), 10.0 (2x), 2.5 (1x). Co-occurs with 0x10001DCA "
                    "and 0x10001DCC. Float parameter in the triplet group, "
                    "possibly a duration or magnitude.",
    },
    0x10001DCC: {
        "name": "unknown_sparse_float_1DCC",
        "confidence": "low",
        "evidence": "29 items; mostly 0 (19x), sparse floats: 1.0 (7x), "
                    "0.25 (2x), 45.0 (1x). Co-occurs with 0x10001DCA/DCB. "
                    "Second float parameter in the triplet; the 1.0/0.25 "
                    "range suggests a multiplier or fraction.",
    },
    # Chain node (0x1036XXXX family)
    0x10360700: {
        "name": "unknown_chain_node_3607",
        "confidence": "low",
        "evidence": "30 items (per frequency scan); in the 0x1036XXXX namespace "
                    "alongside 0x10361000 (chain_value_3610). Like other "
                    "0x1073XXXX/10BC1000 chain nodes — one of a series of "
                    "terminal-value keys in a linked-list schema structure.",
    },
    # --- Tier-9: multi-occurrence (array-element) keys ---
    # These keys appear MULTIPLE TIMES within a single item entry with
    # different values each time, forming a flat-serialized repeated
    # sub-record (list of N elements, each writing all fields in sequence).
    # Cluster A: 4 specific items (Bloody Bjorn[mn], Essence of the
    # Stonemeld Plate[v], Construct Bane, Judgment) — each item has
    # 20-180 repeats per key. Likely encodes enhancement sub-effect tables
    # or random-loot generation parameter lists.
    0x100013D5: {
        "name": "unknown_array_elem_type_13D5",
        "confidence": "low",
        "evidence": "291 raw occurrences across 4 unique items; max 98x in one "
                    "item. Vals: 30 (64x), 6 (61x), 7 (61x). Small enum per "
                    "list element — likely a type or category selector for each "
                    "sub-record in the repeated-element cluster.",
    },
    0x100012F2: {
        "name": "unknown_array_elem_index_12F2",
        "confidence": "low",
        "evidence": "278 raw occurrences across 4 unique items; max 94x in one "
                    "item. Vals: 1 (193x), 4 (64x), 3 (21x). Small int per "
                    "list element — index or rank within the sub-record list.",
    },
    0x100012E3: {
        "name": "unknown_array_elem_flag_12E3",
        "confidence": "low",
        "evidence": "246 raw occurrences across 4 unique items; max 180x in one "
                    "item. Vals: 1 (228x), 4 (18x). Near-binary flag per list "
                    "element. Same 4-item cluster as 0x100013D5/12F2.",
    },
    0x100012EB: {
        "name": "unknown_array_effect_ref_12EB",
        "confidence": "low",
        "evidence": "111 raw occurrences across 4 unique items; max 45x in one "
                    "item. Diverse 0x70XXXXXX effect FIDs per list element "
                    "(0x7000005E 10x, 0x70000618 6x, etc.). Effect ref slot "
                    "within the repeated sub-record structure.",
    },
    0x10000E43: {
        "name": "unknown_array_effect_ref_0E43",
        "confidence": "low",
        "evidence": "65 raw occurrences across 4 unique items; max 21x in one "
                    "item. 3 distinct 0x70XXXXXX FIDs each appearing exactly "
                    "21 times (0x70000071, 0x7000000B, 0x7000006D). Effect ref "
                    "cycling through 3 fixed values per list element.",
    },
    0x10003EA6: {
        "name": "unknown_array_effect_ref_3EA6",
        "confidence": "low",
        "evidence": "64 raw occurrences across 4 unique items; max 20x in one "
                    "item. 3 distinct 0x7000B7XX FIDs each x20 "
                    "(0x7000B733, 0x7000B735, 0x7000B736). Paired with "
                    "0x10003E98 — both cycle through a fixed set of FIDs.",
    },
    0x100014CC: {
        "name": "unknown_array_elem_param_14CC",
        "confidence": "low",
        "evidence": "61 raw occurrences across 4 unique items; max 20x in one "
                    "item. Vals: 9 (20x), 2 (20x), 1 (20x) — evenly "
                    "distributed small ints. Scalar parameter per list element "
                    "in the Bloody Bjorn / Stonemeld cluster.",
    },
    0x10003E98: {
        "name": "unknown_array_effect_ref_3E98",
        "confidence": "low",
        "evidence": "60 raw occurrences across 3 unique items; max 20x in one "
                    "item. 3 distinct 0x7000B7XX FIDs each x20 "
                    "(0x7000B762, 0x7000B6DD, 0x7000B78E). Parallel to "
                    "0x10003EA6 — second effect-ref slot in the array element.",
    },
    # Cluster B: broader set of items, smaller repetition
    0x10001C5C: {
        "name": "unknown_array_near_constant_1C5C",
        "confidence": "low",
        "evidence": "115 raw occurrences across 10 unique items; max 16x in one "
                    "item. Near-constant val=0x3FC (1020) x114, one outlier "
                    "val=810. Items: 'Ki Explosion', 'Tome of Universal "
                    "Enhancement +1 (Sharn)', 'Offensive Otyugh'. Likely a "
                    "capacity or limit parameter repeated for each list element.",
    },
    0x100012C0: {
        "name": "unknown_array_elem_flag_12C0",
        "confidence": "low",
        "evidence": "78 raw occurrences across 14 unique items; max 9x in one "
                    "item. Vals: 1 (43x), 5 (13x), 4 (13x). Items: 'Radiant "
                    "Prisms', 'Horn of Thunder', 'Vulnerable'. Smaller cluster "
                    "with a wider item set — per-element flag or sub-type.",
    },
    0x10000A96: {
        "name": "unknown_array_effect_ref_0A96",
        "confidence": "low",
        "evidence": "37 raw occurrences across 2 unique items; max 34x in "
                    "'Judgment'. Diverse 0x70XXXXXX FIDs — each unique, "
                    "suggesting a list of 34 distinct enhancement effects. "
                    "Effect-ref array for an ability/enhancement definition.",
    },
    0x10001529: {
        "name": "unknown_array_elem_index_1529",
        "confidence": "low",
        "evidence": "30 raw occurrences across 3 unique items; max 20x in one "
                    "item. Vals: 1 (12x), 2 (4x), 3 (4x). Items: 'Essence of "
                    "the Stonemeld Plate[v]', 'Construct Bane'. Small ascending "
                    "index per list element.",
    },
    # --- Tier-10: unique-item counts 24-28 ---
    # Fated One / Random Loot cluster (zero constants)
    0x10001D57: {
        "name": "unknown_zero_constant_1D57",
        "confidence": "low",
        "evidence": "28 items; ALL val=0. Co-occurs with 0x10001D5B/2BCF on "
                    "'The Fated One[mn]', 'Random Loot Deconstruct'. Schema "
                    "placeholder in the Random Loot cluster.",
    },
    0x10001D5B: {
        "name": "unknown_zero_constant_1D5B",
        "confidence": "low",
        "evidence": "27 items; ALL val=0. Same Fated One/Random Loot cluster "
                    "as 0x10001D57. Adjacent hex — likely sequential schema "
                    "fields in a loot-generation sub-record.",
    },
    0x10002BCF: {
        "name": "unknown_zero_constant_2BCF",
        "confidence": "low",
        "evidence": "27 items; ALL val=0. Same Fated One/Random Loot cluster "
                    "as 0x10001D57/1D5B. Schema placeholder.",
    },
    # Small enums
    0x10003967: {
        "name": "unknown_small_enum_3967",
        "confidence": "low",
        "evidence": "28 items; 3 vals: 1 (14x), 2 (12x), 3 (2x). Adjacent "
                    "to 0x10003968 (same tier). Items: 'Horn: Sacred DCs', "
                    "'Defender\\'s Masque'. Likely a sequential sub-type or "
                    "rank field.",
    },
    0x10001806: {
        "name": "unknown_near_constant_1806",
        "confidence": "low",
        "evidence": "27 items; near-constant: 1 (26x), 4 (1x). Items: "
                    "'Raging Torrent[mn]', 'Favored Soul'. Raging Torrent "
                    "cluster key — almost always val=1, boolean-like flag.",
    },
    0x10003774: {
        "name": "unknown_packed_3774",
        "confidence": "low",
        "evidence": "27 items; packed_XX00 pattern: 0x00288801 (10x), "
                    "0x005E2C00 (10x), 0x001D5701 (5x). Low byte alternates "
                    "0/1. Items: 'Wand and Scroll Mastery', 'The Fated One'. "
                    "Packed FID or sub-archive index.",
    },
    # Schema tag (0xA4487500 sentinel)
    0x10001A56: {
        "name": "unknown_schema_tag_1A56",
        "confidence": "low",
        "evidence": "26 items; ALL val=0xA4487500 (same magic constant seen "
                    "on 0x10003972/2A10/2B25/2B41). Items: 'Bolt[E]', "
                    "'Dolnozz[mn]'. Schema-type identifier tag in the "
                    "Bolt/enchanted-item cluster.",
    },
    # Bolt / Dolnozz cluster (packed refs + misc)
    0x10001DA8: {
        "name": "unknown_constant_1DA8",
        "confidence": "low",
        "evidence": "27 items; ALL val=0x001DA900 (constant). Items: 'Bolt[E]', "
                    "'Dolnozz[mn]'. Value encodes bytes 0x1DA9 — the key's "
                    "own low-16 +1. Packed self-referential constant, possibly "
                    "a schema node pointer.",
    },
    0x10001D92: {
        "name": "unknown_packed_1D92",
        "confidence": "low",
        "evidence": "27 items; packed_XX00: 0x00191900 (16x), 0x00424A01 (7x), "
                    "0x001A4600 (2x). Low byte 0/1 variant. Items: 'Bolt[E]', "
                    "'Minimum Level 24'. Packed FID in the Bolt cluster.",
    },
    0x10002DE1: {
        "name": "unknown_packed_2DE1",
        "confidence": "low",
        "evidence": "26 items; packed_XX00: 0x001E3601 (17x), 0x00C81901 (5x). "
                    "Items: 'Bolt[E]', 'Minimum Level 24'. Packed FID in the "
                    "same cluster as 0x10001D92/1DA8.",
    },
    0x1000472D: {
        "name": "unknown_sparse_int_472D",
        "confidence": "low",
        "evidence": "26 items; mostly 25 (16x), 0 (10x). Items: 'Bolt[E]', "
                    "'Dolnozz[mn]'. Co-occurs with 0x10001A56 (schema_tag). "
                    "Likely a version number or level threshold in the "
                    "enchanted-item schema.",
    },
    # Runearm cluster packed refs
    0x10005029: {
        "name": "unknown_packed_5029",
        "confidence": "low",
        "evidence": "27 items; near-constant packed_XX00: 0x00090100 (23x), "
                    "0x00090101 (4x). Items: 'Runearm Knife Blast', "
                    "'Opportunist'. Same runearm cluster as 0x1000117C/1654.",
    },
    0x100012A9: {
        "name": "unknown_packed_12A9",
        "confidence": "low",
        "evidence": "26 items; packed_XX00: 0x00479500 (17x), 0x00048E01 (3x). "
                    "Items: 'Runearm Knife Blast', 'Epic Locus of Vol'. "
                    "Packed FID in the runearm sub-archive ref cluster.",
    },
    # Key-ref extensions of the 1DCA/1DCB/1DCC triplet
    0x10001DC6: {
        "name": "unknown_sparse_key_ref_1DC6",
        "confidence": "low",
        "evidence": "26 items; sparse key_ref: 0 (17x), 0x10001DCE (7x), "
                    "0x10001DCF (1x), 0x100098D9 (1x). Items: 'Dolnozz[mn]', "
                    "'Winston[n]'. Part of the 1DCA–1DCF property cluster — "
                    "key-selector pointing to 0x10001DCE/DCF.",
    },
    0x10001DC7: {
        "name": "unknown_sparse_key_ref_1DC7",
        "confidence": "low",
        "evidence": "26 items; sparse key_ref: 0x10001DCF (14x), 0 (11x), "
                    "0x10001DCE (1x). Items: 'Dolnozz[mn]', 'Winston[n]'. "
                    "Sibling of 0x10001DC6 — second key-selector in the "
                    "1DCA–1DCF cluster, preferring 0x10001DCF.",
    },
    # Misc patterns
    0x10000F29: {
        "name": "unknown_sparse_key_ref_0F29",
        "confidence": "low",
        "evidence": "27 items; sparse key_ref: 0 (20x), 0x10000AF7 (7x). "
                    "Items: 'Opportunist', 'Armor'. Sparse key-selector — "
                    "occasionally points to 0x10000AF7 (another unknown key).",
    },
    0x10000B6A: {
        "name": "unknown_sparse_misc_B6A",
        "confidence": "low",
        "evidence": "27 items; mostly 0 (24x), then isolated large values "
                    "with unusual namespaces: 0x14000000 (1x), 0x0C800008 (1x). "
                    "Items: 'Opportunist'. Namespace diversity suggests "
                    "a rarely-used optional pointer field.",
    },
    0x10000B6C: {
        "name": "unknown_sparse_small_int_B6C",
        "confidence": "low",
        "evidence": "27 items; almost zero: 0 (26x), 16 (1x). Items: "
                    "'Opportunist'. Co-occurs with 0x10000B6A. Sparse flag "
                    "or sub-type field, effectively always zero.",
    },
    0x1000138D: {
        "name": "unknown_sparse_mixed_138D",
        "confidence": "low",
        "evidence": "27 items; mixed: 0 (9x), 50 (4x), 5 (2x), 0xFFFFFFFF (2x). "
                    "Items: 'Memory of Animated Objects', 'Lute of the Summer "
                    "Knight'. The 0xFFFFFFFF sentinel alongside small ints "
                    "suggests a nullable numeric field.",
    },
    0x10000D85: {
        "name": "unknown_version_data_D85",
        "confidence": "low",
        "evidence": "16 items (probe); values with unusual byte patterns: "
                    "0x27312D02 (10x), 0x010A3801 (2x), etc. Pointed to by "
                    "key-ref chain (0x10000D88→0x10000907→here). Possibly "
                    "a packed version string or schema descriptor.",
    },
    # Sparse float (values near -0.0 or 2.0)
    0x10000566: {
        "name": "unknown_sparse_float2_566",
        "confidence": "low",
        "evidence": "26 items; mostly 0x80000000 (-0.0 float, 15x), then "
                    "float32 values ~2.0 (0x40002000=2.000, 0x40008000=2.004, "
                    "0x40000800=2.000). Items: 'Lute of the Summer Knight', "
                    "'Demo Character Necklace'. Sparse float near 2.0.",
    },
    # More packed FID refs
    0x1000288E: {
        "name": "unknown_packed_288E",
        "confidence": "low",
        "evidence": "26 items; near-constant packed_XX00: 0x00540400 (15x), "
                    "0x00540401 (11x). Items: 'Warchanter Things', 'Durable "
                    "Tiny Augment Crystal of Diplomacy'. Same low-byte 0/1 "
                    "packed FID pattern.",
    },
    0x10001AE6: {
        "name": "unknown_packed_1AE6",
        "confidence": "low",
        "evidence": "25 items; packed_XX00: 0x00201F01 (10x), 0x00201F00 (8x), "
                    "0x00085C01 (7x). Items: 'Minimum Level 24', 'Sheet Music "
                    "of the Fey'. Low-byte alternates 0/1. Packed FID.",
    },
    0x100019FC: {
        "name": "unknown_packed_19FC",
        "confidence": "low",
        "evidence": "12 items (probe); packed_XX00: 0x00020F01 (10x), "
                    "0x00056901 (1x). Items: 'Lava Caves: Time is Money', "
                    "'Bard Warchanter II'. Low-byte 0/1 packed FID.",
    },
    # Medium integer
    0x1000055C: {
        "name": "unknown_medium_int_55C",
        "confidence": "low",
        "evidence": "25 items; vals: 1 (9x), 10 (6x), 0 (6x), 600 (2x). "
                    "Items: quest-text entries, 'Memory of Animated Objects'. "
                    "The 1/10/600 range may represent charges, duration, or "
                    "cooldown in some unit.",
    },
    # Ammo / Terror Arrows cluster
    0x1000083A: {
        "name": "unknown_small_enum_83A",
        "confidence": "low",
        "evidence": "25 items; 3 vals: 3 (14x), 2 (10x), 1 (1x). Items: "
                    "'Ammo', 'Terror Arrows: Phantasmal Killer'. Adjacent to "
                    "0x10000839 (small_enum_839). Likely ammo sub-type or "
                    "damage-type category.",
    },
    0x100020E0: {
        "name": "unknown_sparse_enum_20E0",
        "confidence": "low",
        "evidence": "24 items; mostly 0 (14x), then 1 (9x), 2 (1x). Items: "
                    "'Ammo', 'Terror Arrows: Phantasmal Killer'. Sparse enum "
                    "in the ammo cluster — likely a conditional flag.",
    },
    0x100008E5: {
        "name": "unknown_small_enum_8E5",
        "confidence": "low",
        "evidence": "24 items; 4 vals: 4 (10x), 6 (9x), 5 (4x), 1 (1x). "
                    "Items: 'Ammo', 'Terror Arrows'. Range 1-6 suggests a "
                    "damage die type (d4=4, d6=6, d8=8 pattern) or ammo "
                    "property category.",
    },
    0x10005404: {
        "name": "unknown_sparse_effect_ref_5404",
        "confidence": "low",
        "evidence": "24 items; mostly 0 (23x), one 0x70XXXXXX ref "
                    "(0x70011A76). Items: 'Ammo', 'Terror Arrows'. Optional "
                    "effect_ref slot in the ammo cluster — almost always unset.",
    },
    # Small enum (broader items)
    0x10005E2A: {
        "name": "unknown_small_enum_5E2A",
        "confidence": "low",
        "evidence": "24 items; 3 vals: 1 (20x), 2 (2x), 3 (2x). Items: "
                    "'Vestments of Ravenloft', 'Arcane Sanctum'. Small "
                    "ascending enum — likely a set tier or spell level index.",
    },
    # --- Tier-11: unique-item counts 19-24 ---
    # Vestments of Ravenloft / Arcane Sanctum cluster
    0x10005E2B: {
        "name": "unknown_small_enum_5E2B",
        "confidence": "low",
        "evidence": "24 items; 2 vals: 1 (18x), 3 (6x). Adjacent to "
                    "0x10005E2A (same cluster). Items: 'Vestments of "
                    "Ravenloft', 'Arcane Sanctum'. Likely a second sub-type "
                    "selector paired with 5E2A.",
    },
    # Runearm cluster: zero constants
    0x10004253: {
        "name": "unknown_zero_constant_4253",
        "confidence": "low",
        "evidence": "23 items; ALL val=0. Items: 'Runearm Knife Blast', "
                    "'Opportunist'. Adjacent to 0x10004252 — both zero "
                    "constants in the runearm sub-schema.",
    },
    0x10004252: {
        "name": "unknown_zero_constant_4252",
        "confidence": "low",
        "evidence": "22 items; ALL val=0. Items: 'Runearm Knife Blast', "
                    "'Red Slot - Diamond of Constitution +1'. Runearm "
                    "cluster schema placeholder.",
    },
    # Runearm cluster: packed refs
    0x10004C27: {
        "name": "unknown_packed_4C27",
        "confidence": "low",
        "evidence": "21 items; packed values: 0x1C5B3001 (18x), 0x0B323001 "
                    "(2x), 0x0B323601 (1x). Non-standard low-byte patterns "
                    "(not 0x00/0x01). Items: 'Runearm Knife Blast', 'Red Slot "
                    "- Diamond of Constitution +1'. Packed ref in the "
                    "runearm/augment cluster.",
    },
    # Packed-ASCII constant (0x4C3AXXXX looks like 'L:' in big-endian)
    0x10004C39: {
        "name": "unknown_packed_ascii_4C39",
        "confidence": "low",
        "evidence": "23 items; dominant val=0x4C3A3001 (19x); variants "
                    "0x4C3A3601 (1x), 0x4C3A3301 (1x). Big-endian bytes "
                    "spell 'L:0\\x01', 'L:6\\x01', 'L:3\\x01' — possible "
                    "packed version or schema label. Items: 'Runearm Knife "
                    "Blast', 'Opportunist'. Runearm cluster.",
    },
    # Float constant
    0x10004E98: {
        "name": "unknown_float_constant_4E98",
        "confidence": "low",
        "evidence": "23 items; ALL val=0x3D632E00 (float32=0.05546). Items: "
                    "'Signet Trader', 'Sapphire of Vertigo +2'. Co-occurs "
                    "with 0x10003D26 (zero_constant). Unusual float constant "
                    "— possibly a probability or resist fraction.",
    },
    0x10003D26: {
        "name": "unknown_zero_constant_3D26",
        "confidence": "low",
        "evidence": "23 items; ALL val=0. Co-occurs with 0x10004E98 on "
                    "'Signet Trader', 'Sapphire of Vertigo +2'. Schema "
                    "placeholder paired with the float constant.",
    },
    0x10003948: {
        "name": "unknown_near_constant_3948",
        "confidence": "low",
        "evidence": "21 items; near-constant: 1 (20x), 50 (1x). Items: "
                    "'Signet Trader', 'Sapphire of Vertigo +2'. Same cluster "
                    "as 0x10003D26/4E98. Effectively always val=1.",
    },
    # Packed FID refs (various clusters)
    0x10000A4A: {
        "name": "unknown_packed_0A4A",
        "confidence": "low",
        "evidence": "23 items; packed_XX00: 0x00222E00 (9x), 0x00134701 (4x), "
                    "0x00091700 (4x), 0x00165401 (4x). Low byte 0/1 variant. "
                    "Items: 'Opportunity Attack Observer', 'MOTU Bundle'. "
                    "Sibling to 0x10000A49.",
    },
    0x10000A49: {
        "name": "unknown_packed_0A49",
        "confidence": "low",
        "evidence": "21 items; packed_XX00: 0x00091701 (7x), 0x002E2201 (7x), "
                    "0x00091700 (2x). Low byte 0/1 variant. Items: 'Epic Ring "
                    "of Unknown Origins', 'Armor'. Adjacent to 0x10000A4A "
                    "with overlapping value ranges.",
    },
    0x10003F35: {
        "name": "unknown_packed_3F35",
        "confidence": "low",
        "evidence": "22 items; packed_XX00: 0x003F3600 (10x), 0x002BCF00 "
                    "(6x), 0x0011AD00 (5x). Items: 'Dolnozz[mn]', "
                    "'Winston[n]'. Dolnozz/enchanted-item cluster.",
    },
    0x1000288F: {
        "name": "unknown_packed_288F",
        "confidence": "low",
        "evidence": "22 items; near-constant: 0x00029100 (14x), 0x00029101 "
                    "(8x). Items: 'Warchanter Things', 'Durable Tiny Augment "
                    "Crystal'. Co-occurs with 0x10002891 — paired packed FIDs "
                    "in the Warchanter sub-schema.",
    },
    0x10002891: {
        "name": "unknown_packed_2891",
        "confidence": "low",
        "evidence": "22 items; near-constant: 0x0009A200 (15x), 0x0009A201 "
                    "(7x). Items: 'Warchanter Things', 'Durable Tiny Augment "
                    "Crystal'. Sibling of 0x1000288F in the Warchanter cluster.",
    },
    0x10007311: {
        "name": "unknown_constant_7311",
        "confidence": "low",
        "evidence": "21 items; ALL val=0x001C5D01 (constant). Items: 'Swim "
                    "like a Fish', 'Universal Spell Power'. Specific packed "
                    "constant — possibly a shared resource ID for spell power "
                    "or swim-speed items.",
    },
    # Effect_ref slots
    0x100011AF: {
        "name": "effect_ref_26_11AF",
        "confidence": "medium",
        "evidence": "13 items (probe); diverse 0x70XXXXXX FIDs — each "
                    "item has a distinct effect ref. Items: 'Lute of the "
                    "Summer Knight', 'Demo Character Necklace - ML25'. "
                    "Optional effect_ref slot.",
    },
    0x10004C4E: {
        "name": "effect_ref_27_4C4E",
        "confidence": "medium",
        "evidence": "22 items; diverse 0x70XXXXXX FIDs — 0x700007D2 (7x, "
                    "the common shared effect), 0x7001C941 (2x), etc. Items: "
                    "'Ammo', 'Terror Arrows: Phantasmal Killer'. Effect_ref "
                    "slot in the ammo cluster.",
    },
    0x100006E1: {
        "name": "effect_ref_28_06E1",
        "confidence": "medium",
        "evidence": "21 items; diverse 0x70XXXXXX FIDs — 0x7000006E (12x), "
                    "0x7000000E (3x), 0x7001B1A3 (3x), 0x7000006D (2x). "
                    "Items: 'Warchanter Things', 'Durable Tiny Augment Crystal'. "
                    "Effect_ref slot in the Warchanter cluster.",
    },
    # Sparse / mixed value keys
    0x10001DCD: {
        "name": "unknown_sparse_float_1DCD",
        "confidence": "low",
        "evidence": "19 items; mostly 0 (11x), then float 1.0 (4x), 0.2 (4x). "
                    "Items: 'Sheet Music of the Fey', 'Backstab'. Fourth member "
                    "of the 1DCA/1DCB/1DCC triplet group — sibling sparse float.",
    },
    0x100020B0: {
        "name": "unknown_sparse_nullable_20B0",
        "confidence": "low",
        "evidence": "22 items; 0xFFFFFFFF (8x), 5 (5x), 2 (2x), 100 (1x). "
                    "Mix of 0xFFFFFFFF sentinel and small ints. Items: 'Solid "
                    "Fog', 'Lute of the Summer Knight'. Nullable integer — "
                    "the 0xFF sentinel likely means 'not set'.",
    },
    0x10006CCD: {
        "name": "unknown_sparse_float_6CCD",
        "confidence": "low",
        "evidence": "21 items; mostly 0 (18x), sparse floats: 0.52 (1x), "
                    "0.32 (1x), 0.4 (1x). Items: 'Vestments of Ravenloft', "
                    "'Topaz of Cold Resistance 25'. Paired with 0x10006CCE "
                    "— both have identical value distributions.",
    },
    0x10006CCE: {
        "name": "unknown_sparse_float_6CCE",
        "confidence": "low",
        "evidence": "21 items; mostly 0 (18x), sparse floats: 0.52 (1x), "
                    "0.32 (1x), 0.4 (1x). Items: 'Vestments of Ravenloft', "
                    "'Topaz of Cold Resistance 25'. Identical distribution to "
                    "0x10006CCD — likely a paired property (min/max or two "
                    "channels of the same float field).",
    },
    # Float ~8.0 cluster (third member)
    0x1000242D: {
        "name": "unknown_float8_242D",
        "confidence": "low",
        "evidence": "20 items; float32 values consistently ~8.0–8.2 "
                    "(0x4101FCBF=8.124, 0x4102F885=8.186, 0x41009997=8.037). "
                    "Third member of the ~8.0 float cluster alongside "
                    "0x1000000E and 0x10001D36.",
    },
    # Sheet Music cluster: additional zero constants
    0x10002248: {
        "name": "unknown_zero_constant_2248",
        "confidence": "low",
        "evidence": "19 items; ALL val=0. Items: 'Sheet Music of the Fey - "
                    "Lets Drink to It [E]', 'Backstab'. Sheet Music "
                    "sub-schema zero placeholder.",
    },
    0x10002549: {
        "name": "unknown_zero_constant_2549",
        "confidence": "low",
        "evidence": "19 items; ALL val=0. Sheet Music cluster. Adjacent in "
                    "hex to 0x10002248/2A71 — sequential schema fields all "
                    "unused (zero) on these items.",
    },
    0x10002A71: {
        "name": "unknown_zero_constant_2A71",
        "confidence": "low",
        "evidence": "19 items; ALL val=0. Sheet Music cluster. One of several "
                    "zero-constant slots in the Sheet Music sub-schema "
                    "(alongside 0x10002248/2549/223D/28F4).",
    },
    0x1000223D: {
        "name": "unknown_zero_constant_223D",
        "confidence": "low",
        "evidence": "19 items; ALL val=0. Sheet Music cluster. Co-occurs with "
                    "0x10002248, 0x10002549, 0x10002A71, 0x100028F4 — all "
                    "zero-constant placeholders on sheet music items.",
    },
    0x100028F4: {
        "name": "unknown_zero_constant_28F4",
        "confidence": "low",
        "evidence": "19 items; ALL val=0. Sheet Music cluster. Fifth member "
                    "of the Sheet Music zero-constant group. The sub-schema "
                    "defines many unused optional fields for this item type.",
    },
    # --- Tier-12: count=19 Sheet Music sub-schema zero constants ---
    # All appear on the same 19 sheet music items, ALL val=0.
    # The Sheet Music sub-schema defines a large number of optional
    # property slots that are simply unused (zero-filled) for these items.
    0x10002A72: {"name": "unknown_zero_constant_2A72", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002001: {"name": "unknown_zero_constant_2001", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002A73: {"name": "unknown_zero_constant_2A73", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x1000223F: {"name": "unknown_zero_constant_223F", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10003368: {"name": "unknown_zero_constant_3368", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002002: {"name": "unknown_zero_constant_2002", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002A74: {"name": "unknown_zero_constant_2A74", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x100020C1: {"name": "unknown_zero_constant_20C1", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002240: {"name": "unknown_zero_constant_2240", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x100020C2: {"name": "unknown_zero_constant_20C2", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002A76: {"name": "unknown_zero_constant_2A76", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002005: {"name": "unknown_zero_constant_2005", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002A77: {"name": "unknown_zero_constant_2A77", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002A78: {"name": "unknown_zero_constant_2A78", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002A7A: {"name": "unknown_zero_constant_2A7A", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x100028FD: {"name": "unknown_zero_constant_28FD", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002A7B: {"name": "unknown_zero_constant_2A7B", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x100028FE: {"name": "unknown_zero_constant_28FE", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x1000200B: {"name": "unknown_zero_constant_200B", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x100020CB: {"name": "unknown_zero_constant_20CB", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10002900: {"name": "unknown_zero_constant_2900", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x1000200D: {"name": "unknown_zero_constant_200D", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10000A6D: {"name": "unknown_zero_constant_0A6D", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x10000A6E: {"name": "unknown_zero_constant_0A6E", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    0x1000254A: {"name": "unknown_zero_constant_254A", "confidence": "low",
                 "evidence": "19 items; ALL val=0. Sheet Music sub-schema zero placeholder."},
    # Two Sheet Music keys with non-zero values
    0x1000194F: {
        "name": "unknown_sparse_int_194F",
        "confidence": "low",
        "evidence": "19 items; mostly 0 (16x), then val=97 (2x), val=42 (1x). "
                    "Items: 'Sheet Music of the Fey', 'Backstab'. One of the "
                    "rare non-zero Sheet Music properties — possibly a "
                    "note range or musical parameter.",
    },
    0x10001950: {
        "name": "unknown_small_int_1950",
        "confidence": "low",
        "evidence": "19 items; vals: 8 (13x), 4 (3x), 2 (1x). Items: 'Sheet "
                    "Music of the Fey', 'Backstab'. Adjacent to 0x1000194F. "
                    "Small integer — could be a staff count, beat count, or "
                    "musical structure parameter.",
    },
    # --- Tier-13: final remaining non-trivial keys at count=19 ---
    # Float constant triplet (07CC / 07CD / 07CE)
    # All appear on 'Terror Arrows: Phantasmal Killer', 'Exceptional Resistance +1'.
    0x100007CC: {
        "name": "unknown_float_constant_1_07CC",
        "confidence": "low",
        "evidence": "19 items; ALL val=0x3F800000 (float32=1.0). Forms a "
                    "triplet with 0x100007CD/CE. Items: 'Terror Arrows: "
                    "Phantasmal Killer', 'Exceptional Resistance +1'. All three "
                    "keys encode float ~1.0.",
    },
    0x100007CD: {
        "name": "unknown_sparse_float_07CD",
        "confidence": "low",
        "evidence": "19 items; near-constant float: 1.0 (16x), 1.25 (2x), "
                    "0.0 (1x). Middle member of the 07CC/CD/CE triplet. "
                    "Usually 1.0 but occasionally 1.25 — possibly a "
                    "scaling factor that can be boosted.",
    },
    0x100007CE: {
        "name": "unknown_float_constant_1_07CE",
        "confidence": "low",
        "evidence": "19 items; ALL val=0x3F800000 (float32=1.0). Third "
                    "member of the 07CC/CD/CE triplet. Same items as 07CC/CD.",
    },
    # Near-zero key
    0x10000934: {
        "name": "unknown_near_zero_934",
        "confidence": "low",
        "evidence": "19 items; almost zero: 0 (18x), 1 (1x). Items: 'Terror "
                    "Arrows: Phantasmal Killer', 'Exceptional Resistance'. "
                    "Sparse boolean-like flag in the arrow/resistance cluster.",
    },
    # Small enum with 7 distinct values
    0x1000191E: {
        "name": "unknown_small_enum_191E",
        "confidence": "low",
        "evidence": "19 items; 7 distinct vals: 6 (6x), 5 (4x), 2 (3x), "
                    "7 (2x), plus others. Items: 'Warchanter Things', "
                    "'Duergar Laborer[E]'. Broader enum range than most — "
                    "possibly an enhancement tier or category type.",
    },
    # Constant-1 key (Epic Transmutation items)
    0x1000A1B1: {
        "name": "unknown_constant_1_A1B1",
        "confidence": "low",
        "evidence": "19 items; ALL val=1. Items: 'Epic Transmutation: "
                    "Luminous Truth', 'Epic Transmutation: Diabolist\\'s "
                    "Docent'. Constant boolean-like field for epic "
                    "transmutation items.",
    },
    # Special: appears on non-wiki entries only
    0x10004C3A: {
        "name": "unknown_non_wiki_common_4C3A",
        "confidence": "low",
        "evidence": "2262 dup-triple occurrences in ALL 0x79 entries but "
                    "ZERO in wiki-matched named items. This key is very "
                    "common on generic/unnamed game objects not covered by "
                    "the wiki dataset. Pattern type: large_values per "
                    "frequency scan.",
    },
    # Augment sapphire cluster constant
    0x10003949: {
        "name": "unknown_constant_3949",
        "confidence": "low",
        "evidence": "19 items; ALL val=0x00396A01 (constant). Items: "
                    "'Sapphire of Vertigo +2', 'Sapphire of Dodge +1%', "
                    "'Sapphire of Shatter +4'. A fixed packed value shared "
                    "by augment sapphire items — likely a sub-archive "
                    "resource ID for the sapphire item type.",
    },
    # Investigation coverage note: keys below unique-item count ~19 are not
    # catalogued here. The remaining ~560+ unknowns are overwhelmingly:
    # (a) zero-constant schema placeholders for specific item sub-types,
    # (b) very low-frequency keys appearing on <15 named wiki items,
    # (c) keys that use non-dup-triple encoding (e.g. 0x100013E6, 0x1010003C).
}


# ---------------------------------------------------------------------------
# Effect entry lookup tables
# ---------------------------------------------------------------------------

# Maps stat_def_id values (u16 at bytes [16..17] of 0x70XXXXXX effect entries)
# to stat names that match the `stats` table seed values in db/schema.py.
# Expand via investigation: ddo-data dat-dump --id 0x70XXXXXX on known items.
STAT_DEF_IDS: dict[int, str] = {
    376:  "Haggle",
    450:  "Magical Resistance Rating",
    1572: "Saving Throws vs Traps",
    1692: "Well Rounded",       # confirmed via dat-effect-map (6 confirmations, 0 conflicts)
    1941: "Spell Points",
    # Candidates (1 confirmation, 0 conflicts each):
    1269: "Spell Focus Mastery",
    1362: "Charisma",
    1524: "Constitution",
    1730: "Strength",
    1827: "Dodge",
}

# Maps raw bonus_type codes (u16 at bytes [13..14] of 0x70XXXXXX effect entries)
# to bonus type names matching the `bonus_types` table seed values in db/schema.py.
BONUS_TYPE_CODES: dict[int, str] = {
    0x0100: "Enhancement",  # only observed value so far
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NamedEntry:
    """A gamelogic entry matched to its wiki item data."""

    file_id: int
    name: str
    wiki_fields: dict[str, int | float | str]
    properties: list[DecodedProperty]


@dataclass
class KeyMapping:
    """A discovered mapping from property key to human-readable name."""

    key: int
    """Property key, e.g. 0x10000042."""

    name: str
    """Human-readable field name, e.g. 'minimum_level'."""

    confidence: float
    """Fraction of matched entries where the value agreed."""

    match_count: int
    """Number of entries that contributed to this mapping."""

    sample_values: list[int] = field(default_factory=list)
    """A few example values observed for this key."""


@dataclass
class NameMapResult:
    """Results of the property name mapping process."""

    matched_entries: int = 0
    """Wiki items successfully matched to gamelogic entries."""

    unmatched_wiki: int = 0
    """Wiki items not found in the string table / gamelogic."""

    mappings: list[KeyMapping] = field(default_factory=list)
    """Discovered key-to-name mappings, sorted by confidence."""

    unmapped_keys: list[int] = field(default_factory=list)
    """High-frequency keys with no wiki field match."""


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    """Normalize an item name for fuzzy matching."""
    return name.strip().replace("_", " ").lower()


# ---------------------------------------------------------------------------
# Dup-triple decoder for 0x79XXXXXX entries
# ---------------------------------------------------------------------------


def decode_dup_triple(data: bytes) -> list[DecodedProperty]:
    """Decode property key-value pairs from a dup-triple format entry.

    The 0x79XXXXXX entries in client_gamelogic.dat use a 2-byte-aligned
    format that starts with a 2-byte preamble (the schema type's low
    bytes, e.g. 0x1000 -> bytes 00 10), followed by property records:

        [preamble:2B] [key2:u32][key2:u32][val2:u32] [key2:u32][key2:u32][val2:u32] ...

    Most records duplicate the key: [key][key][value] (12 bytes, "dup-triple").
    Some records appear as lone pairs: [key][value] (8 bytes, no key repeat).
    Zero u32s act as section breaks within the stream.

    This scanner finds dup-triples at 2-byte alignment throughout the
    entry, plus lone key-value pairs not captured by the dup pass.
    """
    props: list[DecodedProperty] = []
    seen_keys: set[int] = set()
    n = len(data)

    # Pass 1: scan for dup-triples at 2-byte alignment
    # The preamble is 2 bytes, so all u32s in the property stream are
    # at even offsets (2, 6, 10, 14, ...). Step by 2 to match.
    i = 0
    while i + 12 <= n:
        k1 = struct.unpack_from("<I", data, i)[0]
        k2 = struct.unpack_from("<I", data, i + 4)[0]
        if k1 == k2 and (k1 >> 24) == 0x10:
            val = struct.unpack_from("<I", data, i + 8)[0]
            if k1 not in seen_keys:
                props.append(DecodedProperty(key=k1, value=val))
                seen_keys.add(k1)
            i += 12
        else:
            i += 2

    # Pass 2: lone key-value pairs (first record in each section)
    i = 0
    while i + 8 <= n:
        k = struct.unpack_from("<I", data, i)[0]
        if (k >> 24) == 0x10 and k not in seen_keys:
            val = struct.unpack_from("<I", data, i + 4)[0]
            # Skip if next u32 equals k (dup-triple, handled above)
            if val != k:
                props.append(DecodedProperty(key=k, value=val))
                seen_keys.add(k)
        i += 2

    return props


# ---------------------------------------------------------------------------
# Step 1: Match wiki items to gamelogic entries
# ---------------------------------------------------------------------------


def match_wiki_to_entries(
    wiki_items: list[dict],
    string_table: dict[int, str],
    archive: DatArchive,
    entries: dict[int, FileEntry],
) -> tuple[list[NamedEntry], int]:
    """Match wiki items to gamelogic entries via deterministic ID mapping.

    The Turbine engine uses a shared 24-bit namespace across archives.
    Item definitions live in the 0x79XXXXXX range of client_gamelogic.dat,
    with corresponding localization strings at 0x25XXXXXX in the English
    archive (same lower 3 bytes).

    These 0x79 entries use a "dup-triple" property encoding (not type-2),
    which decode_dup_triple handles.

    Returns (matched_entries, unmatched_wiki_count).
    """
    # Build reverse lookups
    wiki_by_name: dict[str, dict] = {}
    for item in wiki_items:
        name = item.get("name")
        if name:
            wiki_by_name[_normalize_name(name)] = item

    # Build string table lookup by lower 3 bytes (shared namespace)
    lower_to_name: dict[int, str] = {}
    for file_id, text in string_table.items():
        lower = file_id & 0x00FFFFFF
        norm = _normalize_name(text)
        # Only store if it matches a wiki item (avoids noise)
        if norm in wiki_by_name:
            lower_to_name[lower] = norm

    matched: list[NamedEntry] = []

    for file_id, entry in entries.items():
        # Only process 0x79XXXXXX entries (item definitions)
        if (file_id >> 24) & 0xFF != 0x79:
            continue

        # Check deterministic ID mapping: same lower 3 bytes in English
        lower = file_id & 0x00FFFFFF
        matched_name = lower_to_name.get(lower)
        if matched_name is None:
            continue

        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            continue

        if len(data) < 12:
            continue

        # Decode properties from dup-triple format
        properties = decode_dup_triple(data)
        if not properties:
            continue

        wiki_item = wiki_by_name[matched_name]
        named = NamedEntry(
            file_id=file_id,
            name=wiki_item.get("name", matched_name),
            wiki_fields={
                k: v for k, v in wiki_item.items()
                if v is not None and k != "name"
            },
            properties=properties,
        )
        matched.append(named)

    unmatched = len(wiki_by_name) - len({e.name.strip().lower() for e in matched})
    return matched, unmatched


# ---------------------------------------------------------------------------
# Step 2: Correlate property keys to field names
# ---------------------------------------------------------------------------


def correlate_keys(
    named_entries: list[NamedEntry],
    string_table: dict[int, str] | None = None,
    *,
    min_confidence: float = 0.8,
    min_matches: int = 5,
) -> list[KeyMapping]:
    """Find property keys that consistently match wiki field values.

    For numeric wiki fields, checks if a property key's scalar value equals
    the expected wiki value. For string fields, resolves 0x0AXXXXXX property
    values via the string table and compares to wiki text.

    Returns mappings sorted by confidence (descending).
    """
    mappings: list[KeyMapping] = []
    claimed_keys: set[int] = set()

    # --- Numeric fields ---
    for field_name in _NUMERIC_FIELDS:
        # For each property key, collect (actual_value, expected_value) pairs
        candidates: dict[int, list[tuple[int, int]]] = defaultdict(list)

        for entry in named_entries:
            expected = entry.wiki_fields.get(field_name)
            if expected is None or not isinstance(expected, (int, float)):
                continue
            expected_int = int(expected)

            for prop in entry.properties:
                if prop.is_array:
                    continue
                candidates[prop.key].append((prop.value, expected_int))

        # Score each candidate
        best_key = None
        best_confidence = 0.0
        best_count = 0
        best_values: list[int] = []

        for key, pairs in candidates.items():
            if key in claimed_keys:
                continue
            matches = sum(1 for actual, exp in pairs if actual == exp)
            total = len(pairs)
            if matches < min_matches:
                continue
            confidence = matches / total
            if confidence >= min_confidence and confidence > best_confidence:
                best_key = key
                best_confidence = confidence
                best_count = matches
                best_values = sorted({exp for actual, exp in pairs if actual == exp})[:_MAX_SAMPLE_VALUES]

        if best_key is not None:
            mappings.append(KeyMapping(
                key=best_key,
                name=field_name,
                confidence=best_confidence,
                match_count=best_count,
                sample_values=best_values[:_MAX_SAMPLE_VALUES],
            ))
            claimed_keys.add(best_key)

    # --- String fields ---
    if string_table:
        for field_name in _STRING_FIELDS:
            str_candidates: dict[int, list[tuple[str, str]]] = defaultdict(list)

            for entry in named_entries:
                expected_text = entry.wiki_fields.get(field_name)
                if not expected_text or not isinstance(expected_text, str):
                    continue
                norm_expected = _normalize_name(expected_text)

                for prop in entry.properties:
                    if prop.is_array:
                        continue
                    # Check if value looks like a string ref.
                    # 0x79 entries reference the localization archive
                    # directly via 0x25XXXXXX file IDs.
                    if isinstance(prop.value, int):
                        high = (prop.value >> 24) & 0xFF
                        if high in (0x25, 0x0A):
                            resolved = string_table.get(prop.value)
                            if resolved:
                                str_candidates[prop.key].append((
                                    _normalize_name(resolved),
                                    norm_expected,
                                ))

            best_key = None
            best_confidence = 0.0
            best_count = 0

            for key, pairs in str_candidates.items():
                if key in claimed_keys:
                    continue
                matches = sum(1 for actual, exp in pairs if actual == exp)
                total = len(pairs)
                if matches < min_matches:
                    continue
                confidence = matches / total
                if confidence >= min_confidence and confidence > best_confidence:
                    best_key = key
                    best_confidence = confidence
                    best_count = matches

            if best_key is not None:
                mappings.append(KeyMapping(
                    key=best_key,
                    name=field_name,
                    confidence=best_confidence,
                    match_count=best_count,
                    sample_values=[],
                ))
                claimed_keys.add(best_key)

    mappings.sort(key=lambda m: (-m.confidence, -m.match_count))
    return mappings


# ---------------------------------------------------------------------------
# Step 3: Orchestration
# ---------------------------------------------------------------------------


def build_name_map(
    ddo_path: Path,
    wiki_items_path: Path,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> NameMapResult:
    """Run the full name mapping pipeline.

    Args:
        ddo_path: DDO installation directory containing .dat files.
        wiki_items_path: Path to items.json from wiki scraper.
        on_progress: Optional callback for status messages.

    Returns:
        NameMapResult with discovered mappings.
    """
    result = NameMapResult()

    # Load wiki items
    with open(wiki_items_path) as f:
        wiki_items = json.load(f)
    if on_progress:
        on_progress(f"Loaded {len(wiki_items)} wiki items")

    # Load string table from English archive
    english_path = ddo_path / "client_local_English.dat"
    if not english_path.exists():
        logger.error("English archive not found: %s", english_path)
        return result

    if on_progress:
        on_progress("Loading string table from client_local_English.dat...")
    english_archive = DatArchive(english_path)
    english_archive.read_header()
    string_table = load_string_table(english_archive)
    if on_progress:
        on_progress(f"  {len(string_table):,} strings loaded")

    # Scan gamelogic entries
    gamelogic_path = ddo_path / "client_gamelogic.dat"
    if not gamelogic_path.exists():
        logger.error("Gamelogic archive not found: %s", gamelogic_path)
        return result

    if on_progress:
        on_progress("Scanning gamelogic entries...")
    gamelogic_archive = DatArchive(gamelogic_path)
    gamelogic_archive.read_header()
    entries = traverse_btree(gamelogic_archive)
    if on_progress:
        on_progress(f"  {len(entries):,} entries scanned")

    # Match wiki items to gamelogic entries
    if on_progress:
        on_progress("Matching wiki items to gamelogic entries...")
    matched, unmatched = match_wiki_to_entries(
        wiki_items, string_table, gamelogic_archive, entries,
    )
    result.matched_entries = len(matched)
    result.unmatched_wiki = unmatched
    if on_progress:
        on_progress(f"  {len(matched)} matched, {unmatched} unmatched")

    if not matched:
        return result

    # Correlate property keys
    if on_progress:
        on_progress("Correlating property keys...")
    result.mappings = correlate_keys(matched, string_table)
    if on_progress:
        on_progress(f"  {len(result.mappings)} mappings discovered")

    # Collect unmapped high-frequency keys
    mapped_keys = {m.key for m in result.mappings}
    key_freq: dict[int, int] = defaultdict(int)
    for entry in matched:
        for prop in entry.properties:
            if not prop.is_array and prop.key not in mapped_keys:
                key_freq[prop.key] += 1
    result.unmapped_keys = sorted(
        key_freq, key=lambda k: -key_freq[k],
    )[:20]

    return result


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_name_map(result: NameMapResult) -> str:
    """Format name map results as human-readable text."""
    lines: list[str] = []
    lines.append(f"Matched entries: {result.matched_entries}")
    lines.append(f"Unmatched wiki items: {result.unmatched_wiki}")
    lines.append("")

    if result.mappings:
        lines.append(f"Discovered mappings ({len(result.mappings)}):")
        lines.append("-" * 60)
        for m in result.mappings:
            vals = ", ".join(str(v) for v in m.sample_values) if m.sample_values else "-"
            lines.append(
                f"  0x{m.key:08X}  {m.name:<25s} "
                f"conf={m.confidence:.0%}  n={m.match_count}  "
                f"samples=[{vals}]"
            )
    else:
        lines.append("No mappings discovered.")

    if result.unmapped_keys:
        lines.append("")
        lines.append(f"Top unmapped keys ({len(result.unmapped_keys)}):")
        for key in result.unmapped_keys[:10]:
            lines.append(f"  0x{key:08X}")

    return "\n".join(lines)


def format_name_map_json(result: NameMapResult) -> dict:
    """Format name map results as a JSON-serializable dict."""
    return {
        "summary": {
            "matched_entries": result.matched_entries,
            "unmatched_wiki": result.unmatched_wiki,
            "mappings_found": len(result.mappings),
        },
        "mappings": [
            {
                "key": f"0x{m.key:08X}",
                "key_int": m.key,
                "name": m.name,
                "confidence": round(m.confidence, 4),
                "match_count": m.match_count,
                "sample_values": m.sample_values,
            }
            for m in result.mappings
        ],
        "unmapped_keys": [f"0x{k:08X}" for k in result.unmapped_keys],
    }
