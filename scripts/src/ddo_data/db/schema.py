"""DDO game database schema — DDL and seed data for SQLite."""

from __future__ import annotations

import sqlite3

from ddo_data.enums import (
    S, AbilityModSource, AffixType, Alignment, ApPool, Archetype,
    BabProgression, BonusType, CasterType, Class, CraftingParam, CraftingSystem,
    DamageCategory, DamageType, DataSource, EnhancementTier, EquipmentSlot,
    FeatTier, Handedness, ItemCategory, LinkType, PastLifeType,
    ProficiencyCategory, Race, RaceType, Rarity, ResolutionMethod,
    SaveEffect, SaveProgression, SaveType, Skill, SlotCategory, SlotTier,
    SlotType, SpellSchool, SpellTradition, StatCategory, TreeType,
)


def _check(enum_cls: type) -> str:
    """Generate a SQL CHECK IN clause from an enum class."""
    values = ", ".join(f"'{m.value}'" for m in enum_cls)
    return f"IN ({values})"


def _check_subset(*members: str) -> str:
    """Generate a SQL CHECK IN clause from specific enum values."""
    values = ", ".join(f"'{m}'" for m in members)
    return f"IN ({values})"

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_EQUIP_CATEGORIES = _check_subset(
    ItemCategory.ARMOR, ItemCategory.SHIELD, ItemCategory.WEAPON,
    ItemCategory.JEWELRY, ItemCategory.CLOTHING,
)

SCHEMA_V1 = f"""
PRAGMA foreign_keys = ON;

-- Data source key (used in column comments throughout):
--   sd = seed data (hardcoded in this file)
--   bp = binary property (dup-triple key from gamelogic.dat)
--   fl = FID lookup (precomputed JSON: fid_item_lookup.json, EFFECT_FID_LOOKUP)
--   ln = localization name (0x25 string table from English.dat)
--   lt = localization tooltip (0x25 tooltip sub-entry from English.dat)
--   wt = wiki template (parsed from ddowiki.com wikitext)
--   c  = computed (derived/joined at insert time)

-- Game Mechanics Reference (must precede all FK dependents) ----------------
CREATE TABLE IF NOT EXISTS stats (
    id       INTEGER PRIMARY KEY,                                -- sd
    name     TEXT NOT NULL,                                      -- sd
    category TEXT NOT NULL  CHECK (category {_check(StatCategory)}) -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stats_name ON stats(name);
CREATE INDEX IF NOT EXISTS idx_stats_category ON stats(category);

CREATE TABLE IF NOT EXISTS bonus_types (
    id               INTEGER PRIMARY KEY,                        -- sd
    name             TEXT NOT NULL,                               -- sd
    stacks_with_self INTEGER NOT NULL DEFAULT 0 CHECK (stacks_with_self IN (0, 1)) -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bonus_types_name ON bonus_types(name);

CREATE TABLE IF NOT EXISTS skills (
    id             INTEGER PRIMARY KEY,                          -- sd
    name           TEXT NOT NULL,                                 -- sd
    key_ability_id INTEGER NOT NULL REFERENCES stats(id)         -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name ON skills(name);

CREATE TABLE IF NOT EXISTS damage_types (
    id       INTEGER PRIMARY KEY,                                -- sd
    name     TEXT NOT NULL,                                      -- sd
    category TEXT NOT NULL  CHECK (category {_check(DamageCategory)}) -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_damage_types_name ON damage_types(name);

CREATE TABLE IF NOT EXISTS weapon_proficiencies (
    id       INTEGER PRIMARY KEY,                                -- sd
    name     TEXT NOT NULL,                                      -- sd
    category TEXT NOT NULL  CHECK (category {_check(ProficiencyCategory)}) -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weapon_proficiencies_name ON weapon_proficiencies(name);

CREATE TABLE IF NOT EXISTS weapon_types (
    id             INTEGER PRIMARY KEY,                          -- c: autoincrement
    name           TEXT NOT NULL,                                 -- wt: type field; fl: fallback
    proficiency_id INTEGER REFERENCES weapon_proficiencies(id),  -- c: joined from proficiency name
    base_damage    TEXT                                           -- unpopulated
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weapon_types_name ON weapon_types(name);
CREATE INDEX IF NOT EXISTS idx_weapon_types_proficiency ON weapon_types(proficiency_id) WHERE proficiency_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS equipment_slots (
    id         INTEGER PRIMARY KEY,                              -- sd
    name       TEXT NOT NULL,                                     -- sd
    sort_order INTEGER NOT NULL DEFAULT 0,                       -- sd
    category   TEXT NOT NULL CHECK (category {_check(SlotCategory)}) -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_equipment_slots_name ON equipment_slots(name);

CREATE TABLE IF NOT EXISTS spell_schools (
    id   INTEGER PRIMARY KEY,                                    -- sd
    name TEXT NOT NULL                                            -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_spell_schools_name ON spell_schools(name);

-- Classes and Races --------------------------------------------------------
CREATE TABLE IF NOT EXISTS classes (
    id                     INTEGER PRIMARY KEY,                  -- sd
    name                   TEXT NOT NULL,                         -- sd
    parent_class_id        INTEGER REFERENCES classes(id),       -- sd: NULL for base, set for archetypes
    is_archetype           INTEGER NOT NULL DEFAULT 0 CHECK (is_archetype IN (0, 1)), -- sd
    hit_die                INTEGER,                              -- sd
    bab_progression        TEXT CHECK (bab_progression {_check(BabProgression)}), -- sd
    skill_points_per_level INTEGER,                              -- sd
    fort_save_progression  TEXT CHECK (fort_save_progression {_check(SaveProgression)}), -- sd
    ref_save_progression   TEXT CHECK (ref_save_progression  {_check(SaveProgression)}), -- sd
    will_save_progression  TEXT CHECK (will_save_progression {_check(SaveProgression)}), -- sd
    caster_type            TEXT CHECK (caster_type {_check(CasterType)}),   -- sd
    spell_tradition        TEXT CHECK (spell_tradition {_check(SpellTradition)}),   -- sd
    alignment              TEXT,                                  -- sd: e.g., 'any', 'lawful good', 'any lawful'
    icon                   TEXT,                                  -- wt: wiki image filename
    description            TEXT                                   -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_classes_name ON classes(name);

CREATE TABLE IF NOT EXISTS races (
    id           INTEGER PRIMARY KEY,                            -- sd
    name         TEXT NOT NULL,                                   -- sd
    race_type    TEXT CHECK (race_type {_check(RaceType)}), -- sd/wt: from Races page
    parent_race  TEXT,                                            -- sd: base race for iconics (e.g., 'Elf' for Morninglord)
    alignment    TEXT,                                            -- sd: alignment restriction if any
    icon         TEXT,                                            -- wt: wiki image filename
    description  TEXT                                             -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_races_name ON races(name);

CREATE TABLE IF NOT EXISTS race_ability_modifiers (           -- sd/wt: from ddowiki.com/page/Races chart
    race_id     INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    stat_id     INTEGER NOT NULL REFERENCES stats(id),
    modifier    INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source {_check(AbilityModSource)}), -- innate=at creation, enhancement=racial tree
    is_choice   INTEGER NOT NULL DEFAULT 0 CHECK (is_choice IN (0, 1)),   -- 1=player picks from options
    choice_pool INTEGER,                                         -- total points to distribute (when is_choice=1)
    PRIMARY KEY (race_id, stat_id, source, is_choice)
);
CREATE INDEX IF NOT EXISTS idx_race_ability_modifiers_stat ON race_ability_modifiers(stat_id);

-- Legacy alias view for backwards compatibility
CREATE VIEW IF NOT EXISTS race_ability_bonuses AS
    SELECT race_id, stat_id, modifier
    FROM race_ability_modifiers
    WHERE source = '{AbilityModSource.INNATE}';

CREATE TABLE IF NOT EXISTS class_skills (                     -- sd: from DDO wiki class pages
    class_id       INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    skill_id       INTEGER NOT NULL REFERENCES skills(id),
    is_class_skill INTEGER NOT NULL DEFAULT 1 CHECK (is_class_skill IN (0, 1)),
    PRIMARY KEY (class_id, skill_id)
);
CREATE INDEX IF NOT EXISTS idx_class_skills_skill ON class_skills(skill_id);

CREATE TABLE IF NOT EXISTS class_bonus_feat_slots (           -- wt: from class progression parsing
    class_id      INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level   INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 30),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    slot_type     TEXT NOT NULL DEFAULT '{SlotType.CLASS_BONUS}'
                  CHECK (slot_type {_check(SlotType)}),
    slot_label    TEXT,                                          -- wt: raw wiki text (display fallback)
    PRIMARY KEY (class_id, class_level, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_class_bonus_feat_slots_level ON class_bonus_feat_slots(class_id, class_level);

CREATE TABLE IF NOT EXISTS feat_slots (                            -- sd: universal feat slot schedule
    character_level INTEGER NOT NULL CHECK (character_level BETWEEN 1 AND 30),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    slot_tier       TEXT NOT NULL CHECK (slot_tier {_check(SlotTier)}),
    PRIMARY KEY (character_level, sort_order)
);

CREATE TABLE IF NOT EXISTS class_spell_slots (               -- wt: from class progression parsing
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 20),
    spell_level INTEGER NOT NULL CHECK (spell_level BETWEEN 1 AND 9),
    slots       INTEGER NOT NULL CHECK (slots >= 0),
    PRIMARY KEY (class_id, class_level, spell_level)
);

CREATE TABLE IF NOT EXISTS class_spells_known (               -- wt: from class progression parsing
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 20),
    spell_level INTEGER NOT NULL CHECK (spell_level BETWEEN 1 AND 9),
    known_count INTEGER NOT NULL CHECK (known_count >= 0),
    PRIMARY KEY (class_id, class_level, spell_level)
);

-- Item Materials -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS item_materials (
    id        INTEGER PRIMARY KEY,                               -- c: autoincrement
    name      TEXT NOT NULL,                                      -- wt: material field; fl: fallback
    dr_bypass TEXT                                                -- unpopulated
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_materials_name ON item_materials(name);

-- Filigrees (sentient weapon / minor artifact augments) --------------------
CREATE TABLE IF NOT EXISTS filigrees (
    id             INTEGER PRIMARY KEY,                          -- c: autoincrement
    name           TEXT NOT NULL,                                 -- wt: filigree page title
    icon           TEXT,                                          -- wt: wiki image filename
    set_name       TEXT,                                         -- wt: set name field
    rare_bonus     TEXT,                                         -- wt: rare bonus text
    bonus          TEXT                                           -- wt: bonus text
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_filigrees_name ON filigrees(name);
CREATE INDEX IF NOT EXISTS idx_filigrees_set ON filigrees(set_name) WHERE set_name IS NOT NULL;

-- Augments -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS augments (
    id         INTEGER PRIMARY KEY,                              -- c: autoincrement
    dat_id     TEXT,                                             -- bp: 0x79 file ID (matched by name)
    name       TEXT NOT NULL,                                     -- wt: {{Item Augment|name=...}}
    icon       TEXT,                                              -- wt: wiki image filename
    slot_color TEXT NOT NULL,                                     -- wt: type field; lt: fallback from tooltip
    min_level  INTEGER                                           -- bp: key 0x10001C5D; wt: minimum level field
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_augments_name ON augments(name);
CREATE INDEX IF NOT EXISTS idx_augments_slot_color ON augments(slot_color);

-- Items --------------------------------------------------------------------
-- Source key: bp=binary property, fl=FID lookup, ln=localization name,
--             lt=localization tooltip, wt=wiki template, c=computed
CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY,                         -- c: autoincrement
    name              TEXT NOT NULL,                                -- ln: 0x25 string table
    dat_id            TEXT,                                        -- bp: 0x79 file ID
    rarity            TEXT CHECK (rarity {_check(Rarity)}), -- bp: key 0x10000B5F enum
    slot_id           INTEGER REFERENCES equipment_slots(id),      -- c: joined from equipment_slot name
    equipment_slot    TEXT,                                         -- bp: key 0x10000A4B enum
    item_category     TEXT CHECK (item_category {_EQUIP_CATEGORIES}), -- bp: key 0x10000A4C enum; wt: fallback
    level             INTEGER,                                     -- bp: key 0x10000A3C
    durability        INTEGER,                                     -- bp: key 0x10000A4D
    item_type         TEXT,                                        -- wt: {{Named item|TYPE}} positional arg
    minimum_level     INTEGER,                                     -- bp: key 0x10001C5D
    enhancement_bonus INTEGER,                                     -- wt: enchantmentbonus field
    hardness          INTEGER,                                     -- wt: hardness field
    weight            REAL,                                        -- wt: weight field
    material_id       INTEGER REFERENCES item_materials(id),       -- c: joined from material name
    material          TEXT,                                         -- wt: material field; fl: fallback
    binding           TEXT,                                        -- wt: bind field; fl: fallback
    base_value        TEXT,                                        -- wt: basevalue field; fl: fallback
    race_required     TEXT,                                        -- wt: race field (e.g., "Warforged")
    icon              TEXT,                                        -- wt: picdesc or pic field (wiki image filename)
    description       TEXT,                                        -- wt: description field
    tooltip           TEXT,                                        -- lt: 0x25 tooltip sub-entry
    enchant_name      TEXT,                                        -- ln: 0x25 enchant_name sub-entry
    enchant_suffix    TEXT,                                        -- ln: 0x25 enchant_suffix sub-entry
    effect_value      INTEGER,                                     -- bp: key 0x100012A2
    cooldown_seconds  REAL,                                        -- bp: key 0x10000B7A or 0x10001013 (float)
    internal_level    INTEGER,                                     -- bp: key 0x10000742 (float, unknown meaning)
    tier_multiplier   REAL,                                        -- bp: key 0x10000B60 (float)
    wiki_url          TEXT                                         -- c: constructed from name
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_name ON items(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_dat_id ON items(dat_id) WHERE dat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_equipment_slot ON items(equipment_slot);
CREATE INDEX IF NOT EXISTS idx_items_slot_id ON items(slot_id) WHERE slot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_minimum_level ON items(minimum_level);
CREATE INDEX IF NOT EXISTS idx_items_rarity ON items(rarity) WHERE rarity IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_weapon_stats (
    item_id        INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    damage         TEXT,                                         -- wt: damage field; fl: fallback
    critical       TEXT,                                         -- wt: crit field; fl: fallback
    damage_class   TEXT,                                         -- wt: class field; fl: fallback
    attack_mod     TEXT,                                         -- wt: attackmod field; fl: fallback
    damage_mod     TEXT,                                         -- wt: damagemod field; fl: fallback
    weapon_type_id INTEGER REFERENCES weapon_types(id),          -- c: joined from weapon_type name
    weapon_type    TEXT,                                         -- wt: type field; fl: fallback
    proficiency_id INTEGER REFERENCES weapon_proficiencies(id),  -- c: joined from proficiency name
    proficiency    TEXT,                                         -- wt: prof field; fl: fallback
    handedness     TEXT CHECK (handedness {_check(Handedness)}) -- wt: hand field
);
CREATE INDEX IF NOT EXISTS idx_item_weapon_stats_weapon_type ON item_weapon_stats(weapon_type_id) WHERE weapon_type_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_weapon_stats_proficiency ON item_weapon_stats(proficiency_id) WHERE proficiency_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_armor_stats (
    item_id       INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    armor_bonus   INTEGER,                                       -- wt: armorbonus field
    max_dex_bonus INTEGER                                        -- wt: maxdex field
);

CREATE TABLE IF NOT EXISTS item_augment_slots (
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    slot_type  TEXT NOT NULL,                                     -- wt: {{Augment|Color}} in enhancements field
    augment_id INTEGER REFERENCES augments(id),                   -- c: joined from augments (unpopulated)
    PRIMARY KEY (item_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_item_augment_slots_type ON item_augment_slots(slot_type);

CREATE TABLE IF NOT EXISTS item_class_min_levels (
    item_id   INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    class_id  INTEGER NOT NULL REFERENCES classes(id),
    min_level INTEGER NOT NULL CHECK (min_level >= 1),
    PRIMARY KEY (item_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_item_class_min_levels_class ON item_class_min_levels(class_id);

-- item_spell_links defined after Spells block (forward reference to spells)

CREATE TABLE IF NOT EXISTS item_upgrades (
    item_id      INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    base_item_id INTEGER NOT NULL REFERENCES items(id),
    upgrade_tier INTEGER NOT NULL CHECK (upgrade_tier >= 1),
    PRIMARY KEY (item_id, upgrade_tier)
);
CREATE INDEX IF NOT EXISTS idx_item_upgrades_base ON item_upgrades(base_item_id);

CREATE TABLE IF NOT EXISTS item_effect_refs (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    ref_id  TEXT NOT NULL,
    PRIMARY KEY (item_id, ref_id)
);

-- Feats --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feats (
    id                   INTEGER PRIMARY KEY,                    -- c: autoincrement
    dat_id               TEXT,                                   -- bp: 0x79 file ID
    name                 TEXT NOT NULL,                           -- wt: {{Feat|name=...}}
    icon                 TEXT,                                    -- wt: icon field
    description          TEXT,                                    -- wt: description; bp: fallback from localization
    tooltip              TEXT,                                    -- lt: 0x25 tooltip sub-entry
    prerequisite         TEXT,                                    -- wt: prerequisite field (free text)
    note                 TEXT,                                    -- wt: note field
    cooldown             TEXT,                                    -- wt: cooldown field (text)
    cooldown_seconds     REAL,                                   -- bp: key 0x10000B7A (float)
    duration_seconds     REAL,                                   -- bp: key 0x10000907 (float)
    min_bab              INTEGER,                                -- unpopulated
    damage_dice_notation TEXT,                                   -- bp: key 0x10001C2B decoded
    is_free              INTEGER NOT NULL DEFAULT 0 CHECK (is_free              IN (0, 1)), -- bp: key 0x100040FB; wt: fallback
    is_passive           INTEGER NOT NULL DEFAULT 0 CHECK (is_passive           IN (0, 1)), -- wt: passive=yes
    is_active            INTEGER NOT NULL DEFAULT 0 CHECK (is_active            IN (0, 1)), -- bp: active key set; wt: fallback
    is_stance            INTEGER NOT NULL DEFAULT 0 CHECK (is_stance            IN (0, 1)), -- bp: stance key set; wt: fallback
    is_metamagic         INTEGER NOT NULL DEFAULT 0 CHECK (is_metamagic         IN (0, 1)), -- wt: metamagic=yes
    is_epic_destiny      INTEGER NOT NULL DEFAULT 0 CHECK (is_epic_destiny      IN (0, 1)), -- wt: epic destiny=yes
    scales_with_difficulty INTEGER NOT NULL DEFAULT 0 CHECK (scales_with_difficulty IN (0, 1)), -- bp: tier key presence
    feat_tier            TEXT CHECK (feat_tier {_check(FeatTier)}),
                                                                    -- wt: choosability pool (NULL = not choosable)
    min_character_level  INTEGER CHECK (min_character_level BETWEEN 1 AND 30),
                                                                    -- wt: parsed from "Level N" prerequisite text
    proficiency_id       INTEGER REFERENCES weapon_proficiencies(id), -- c: joined from proficiency name
    wiki_url             TEXT                                    -- c: constructed from name
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feats_name ON feats(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feats_dat_id ON feats(dat_id) WHERE dat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_feats_proficiency ON feats(proficiency_id) WHERE proficiency_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_feats_tier ON feats(feat_tier) WHERE feat_tier IS NOT NULL;

-- Past-life subtype — only populated for past life feats
CREATE TABLE IF NOT EXISTS feat_past_life_stats (                -- wt: parsed from feat description/name
    feat_id        INTEGER PRIMARY KEY REFERENCES feats(id) ON DELETE CASCADE,
    past_life_type TEXT NOT NULL CHECK (past_life_type {_check(PastLifeType)}), -- wt
    class_id       INTEGER REFERENCES classes(id),               -- c: joined from class name
    race_id        INTEGER REFERENCES races(id),                 -- c: joined from race name
    max_stacks     INTEGER                                       -- wt
);
CREATE INDEX IF NOT EXISTS idx_feat_past_life_stats_class ON feat_past_life_stats(class_id) WHERE class_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_feat_past_life_stats_race  ON feat_past_life_stats(race_id)  WHERE race_id  IS NOT NULL;

CREATE TABLE IF NOT EXISTS feat_bonus_classes (                 -- wt: fighter=yes, barbarian=yes etc.
    feat_id  INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL REFERENCES classes(id),             -- c: joined from class name
    PRIMARY KEY (feat_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_feat_bonus_classes_class ON feat_bonus_classes(class_id);

CREATE TABLE IF NOT EXISTS feat_prereq_feats (                  -- wt: parsed from prerequisite text
    feat_id          INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    required_feat_id INTEGER NOT NULL REFERENCES feats(id),      -- c: joined by feat name
    logic_group      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, required_feat_id, logic_group)
);
CREATE INDEX IF NOT EXISTS idx_feat_prereq_feats_required ON feat_prereq_feats(required_feat_id);

CREATE TABLE IF NOT EXISTS feat_prereq_stats (                  -- wt: parsed "17 Strength" from prerequisite
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    stat_id     INTEGER NOT NULL REFERENCES stats(id),           -- c: joined by stat name
    min_value   INTEGER NOT NULL CHECK (min_value > 0),          -- wt: parsed int
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, stat_id, logic_group)
);

CREATE TABLE IF NOT EXISTS feat_prereq_classes (                -- wt: parsed "Warlock Level 15" from prerequisite
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    class_id    INTEGER NOT NULL REFERENCES classes(id),         -- c: joined by class name
    min_level   INTEGER NOT NULL CHECK (min_level >= 1),         -- wt: parsed int
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, class_id, logic_group)
);

CREATE TABLE IF NOT EXISTS feat_prereq_races (                  -- wt: parsed race name from prerequisite
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    race_id     INTEGER NOT NULL REFERENCES races(id),           -- c: joined by race name
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, race_id, logic_group)
);

CREATE TABLE IF NOT EXISTS feat_prereq_skills (                 -- wt: parsed "7 ranks of Balance" from prerequisite
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    skill_id    INTEGER NOT NULL REFERENCES skills(id),          -- c: joined by skill name
    min_rank    INTEGER NOT NULL CHECK (min_rank > 0),           -- wt: parsed int
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, skill_id, logic_group)
);

CREATE TABLE IF NOT EXISTS class_auto_feats (                   -- wt: from class progression parsing
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 30),
    feat_id     INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (class_id, class_level, feat_id)
);
CREATE INDEX IF NOT EXISTS idx_class_auto_feats_feat ON class_auto_feats(feat_id);

CREATE TABLE IF NOT EXISTS class_choice_feats (                    -- wt: from class progression parsing
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 30),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    feat_id     INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (class_id, class_level, sort_order, feat_id)
);
CREATE INDEX IF NOT EXISTS idx_class_choice_feats_feat ON class_choice_feats(feat_id);

CREATE TABLE IF NOT EXISTS race_auto_feats (                         -- sd: populated in insert_feats()
    race_id INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    feat_id INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (race_id, feat_id)
);
CREATE INDEX IF NOT EXISTS idx_race_auto_feats_feat ON race_auto_feats(feat_id);

CREATE TABLE IF NOT EXISTS race_bonus_feat_slots (                   -- sd
    race_id         INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    character_level INTEGER NOT NULL CHECK (character_level BETWEEN 1 AND 30),
    slot_tier       TEXT NOT NULL CHECK (slot_tier {_check_subset(SlotTier.HEROIC, SlotTier.EPIC, SlotTier.LEGENDARY)}),
    PRIMARY KEY (race_id, character_level)
);

-- Enhancement Trees --------------------------------------------------------
CREATE TABLE IF NOT EXISTS enhancement_trees (
    id        INTEGER PRIMARY KEY,                               -- c: autoincrement
    dat_id    TEXT,                                               -- ln: FID from fid_enhancement_lookup.json
    name      TEXT NOT NULL,                                      -- wt: wiki tree page title
    tree_type TEXT NOT NULL CHECK (tree_type {_check(TreeType)}), -- wt: from index category
    ap_pool   TEXT NOT NULL CHECK (ap_pool {_check(ApPool)}), -- c: derived from tree_type
    class_id  INTEGER REFERENCES classes(id),                    -- c: joined from class name
    race_id   INTEGER REFERENCES races(id),                      -- c: joined from race name
    CHECK (
        (tree_type = '{TreeType.CLASS}'     AND ap_pool = '{ApPool.HEROIC}'    AND class_id IS NOT NULL AND race_id IS NULL) OR
        (tree_type = '{TreeType.RACIAL}'    AND ap_pool = '{ApPool.RACIAL}'    AND race_id  IS NOT NULL AND class_id IS NULL) OR
        (tree_type = '{TreeType.UNIVERSAL}' AND ap_pool = '{ApPool.HEROIC}'    AND class_id IS NULL     AND race_id IS NULL) OR
        (tree_type = '{TreeType.REAPER}'    AND ap_pool = '{ApPool.REAPER}'    AND class_id IS NULL     AND race_id IS NULL) OR
        (tree_type = '{TreeType.DESTINY}'   AND ap_pool = '{ApPool.LEGENDARY}' AND class_id IS NULL     AND race_id IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_enhancement_trees_name ON enhancement_trees(name);
CREATE INDEX IF NOT EXISTS idx_enhancement_trees_class ON enhancement_trees(class_id) WHERE class_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_enhancement_trees_race ON enhancement_trees(race_id) WHERE race_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS enhancement_tree_ap_thresholds (
    tree_id             INTEGER NOT NULL REFERENCES enhancement_trees(id) ON DELETE CASCADE,
    tier                TEXT    NOT NULL CHECK (tier {_check_subset(EnhancementTier.T1, EnhancementTier.T2, EnhancementTier.T3, EnhancementTier.T4, EnhancementTier.T5)}),
    ap_required         INTEGER NOT NULL CHECK (ap_required >= 0),
    min_character_level INTEGER,
    PRIMARY KEY (tree_id, tier)
);

CREATE TABLE IF NOT EXISTS enhancements (
    id          INTEGER PRIMARY KEY,                             -- c: autoincrement
    tree_id     INTEGER NOT NULL REFERENCES enhancement_trees(id) ON DELETE CASCADE,
    dat_id      TEXT,                                            -- ln: FID from fid_enhancement_lookup.json
    name        TEXT NOT NULL,                                    -- wt: {{Enhancement table/item|name=...}}
    icon        TEXT,                                             -- wt: image field
    max_ranks   INTEGER NOT NULL DEFAULT 1,                      -- wt: ranks field
    ap_cost     INTEGER NOT NULL DEFAULT 1,                      -- wt: ap field
    progression INTEGER NOT NULL DEFAULT 0,                      -- wt: pg field
    tier        TEXT NOT NULL CHECK (tier {_check(EnhancementTier)}), -- wt: from section headers
    level_req   TEXT,                                            -- wt: level field
    prerequisite TEXT,                                            -- wt: prereq field
    description TEXT                                              -- wt: wiki description (contains [1/2/3] rank notation)
);
CREATE INDEX IF NOT EXISTS idx_enhancements_tree ON enhancements(tree_id);
CREATE INDEX IF NOT EXISTS idx_enhancements_name ON enhancements(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_enhancements_unique ON enhancements(tree_id, name, tier, progression);

CREATE TABLE IF NOT EXISTS enhancement_prereqs (                -- wt: parsed from prerequisite text
    enhancement_id          INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    required_enhancement_id INTEGER NOT NULL REFERENCES enhancements(id),
    PRIMARY KEY (enhancement_id, required_enhancement_id)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_prereqs_required ON enhancement_prereqs(required_enhancement_id);

CREATE TABLE IF NOT EXISTS enhancement_prereq_classes (         -- wt: parsed "Class Level N" from prereq
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    class_id       INTEGER NOT NULL REFERENCES classes(id),
    min_level      INTEGER NOT NULL CHECK (min_level >= 1),
    PRIMARY KEY (enhancement_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_prereq_classes_class ON enhancement_prereq_classes(class_id);

CREATE TABLE IF NOT EXISTS enhancement_prereq_races (           -- unpopulated (future: wt)
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    race_id        INTEGER NOT NULL REFERENCES races(id),
    PRIMARY KEY (enhancement_id, race_id)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_prereq_races_race ON enhancement_prereq_races(race_id);

CREATE TABLE IF NOT EXISTS enhancement_feat_links (             -- unpopulated (future: wt)
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    feat_id        INTEGER NOT NULL REFERENCES feats(id),
    link_type      TEXT NOT NULL CHECK (link_type {_check(LinkType)}),
    min_rank       INTEGER NOT NULL DEFAULT 1,                   -- rank at which this link becomes active
    PRIMARY KEY (enhancement_id, feat_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_feat_links_feat ON enhancement_feat_links(feat_id);

-- enhancement_spell_links defined after Spells block (forward reference to spells)

-- Patrons ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patrons (                             -- unpopulated (future: wt)
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_patrons_name ON patrons(name);

-- Adventure Packs ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS adventure_packs (                     -- unpopulated (future: wt)
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    is_free_to_play INTEGER NOT NULL DEFAULT 0 CHECK (is_free_to_play IN (0, 1))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_adventure_packs_name ON adventure_packs(name);

-- Quests -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quests (                              -- unpopulated (future: wt)
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    pack_id   INTEGER REFERENCES adventure_packs(id),
    patron_id INTEGER REFERENCES patrons(id),
    level     INTEGER,
    zone      TEXT,
    npc       TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_quests_name ON quests(name);
CREATE INDEX IF NOT EXISTS idx_quests_pack ON quests(pack_id) WHERE pack_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_quests_patron ON quests(patron_id) WHERE patron_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS quest_flagging (
    quest_id        INTEGER NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    prereq_quest_id INTEGER NOT NULL REFERENCES quests(id),
    PRIMARY KEY (quest_id, prereq_quest_id)
);

CREATE TABLE IF NOT EXISTS quest_loot (
    quest_id INTEGER NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    item_id  INTEGER NOT NULL REFERENCES items(id),
    PRIMARY KEY (quest_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_quest_loot_item ON quest_loot(item_id);

-- Crafting -----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS crafting_enchantments (                -- wt: from Cannith_Crafting wiki tables
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,                                 -- wt: shard/enchantment name (e.g., "Ability", "Fortification")
    bonus_type_id   INTEGER REFERENCES bonus_types(id),           -- c: Enhancement for normal, Insight for "Ins." variants
    stat_id         INTEGER REFERENCES stats(id),                 -- c: direct stat mapping, NULL if parameterized
    parameter_type  TEXT CHECK (parameter_type {_check(CraftingParam)} OR parameter_type IS NULL), -- wt
    is_scaling      INTEGER NOT NULL DEFAULT 1 CHECK (is_scaling IN (0, 1)), -- wt: 1=scales with ML, 0=fixed
    crafting_level  INTEGER                                       -- wt: base crafting level required
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_crafting_enchantments_name ON crafting_enchantments(name);

CREATE TABLE IF NOT EXISTS crafting_enchantment_values (          -- wt: from Cannith_Crafting/table_3b
    enchantment_id  INTEGER NOT NULL REFERENCES crafting_enchantments(id) ON DELETE CASCADE,
    minimum_level   INTEGER NOT NULL CHECK (minimum_level BETWEEN 1 AND 34),
    value           TEXT NOT NULL,                                 -- wt: numeric or dice notation (e.g., "3d6")
    PRIMARY KEY (enchantment_id, minimum_level)
);

CREATE TABLE IF NOT EXISTS crafting_enchantment_slots (           -- wt: from Cannith_Crafting/table_1b
    enchantment_id  INTEGER NOT NULL REFERENCES crafting_enchantments(id) ON DELETE CASCADE,
    slot_id         INTEGER NOT NULL REFERENCES equipment_slots(id),
    affix_type      TEXT NOT NULL CHECK (affix_type {_check(AffixType)}),
    PRIMARY KEY (enchantment_id, slot_id, affix_type)
);
CREATE INDEX IF NOT EXISTS idx_crafting_enchantment_slots_slot ON crafting_enchantment_slots(slot_id);

-- Named crafting systems (Green Steel, Thunder-Forged, etc.) ---------------

CREATE TABLE IF NOT EXISTS crafting_systems (                     -- sd/wt
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL                                             -- sd: "Green Steel", "Thunder-Forged", etc.
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_crafting_systems_name ON crafting_systems(name);

CREATE TABLE IF NOT EXISTS crafting_options (                     -- wt: from system wiki pages
    id          INTEGER PRIMARY KEY,
    system_id   INTEGER NOT NULL REFERENCES crafting_systems(id) ON DELETE CASCADE,
    tier        TEXT NOT NULL,                                     -- wt: "Tier 1", "Eldritch Rune", "Prefix", etc.
    name        TEXT NOT NULL,                                     -- wt: option name (e.g., "Air - Martial", "Lightning II")
    description TEXT                                               -- wt: full effect text from wiki
);
CREATE INDEX IF NOT EXISTS idx_crafting_options_system ON crafting_options(system_id);

CREATE TABLE IF NOT EXISTS crafting_option_bonuses (              -- wt: links options to unified bonuses table
    option_id     INTEGER NOT NULL REFERENCES crafting_options(id) ON DELETE CASCADE,
    bonus_id      INTEGER NOT NULL REFERENCES bonuses(id),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (option_id, bonus_id)
);
CREATE INDEX IF NOT EXISTS idx_crafting_option_bonuses_option ON crafting_option_bonuses(option_id);

CREATE TABLE IF NOT EXISTS crafting_system_items (                -- wt: links crafting systems to craftable items
    system_id     INTEGER NOT NULL REFERENCES crafting_systems(id) ON DELETE CASCADE,
    item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (system_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_crafting_system_items_item ON crafting_system_items(item_id);

CREATE TABLE IF NOT EXISTS crafting_ingredients (                 -- wt: materials/ingredients for crafting
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,                                   -- wt: "Shavarath Stone", "Dragon Scale", etc.
    wiki_url      TEXT                                             -- wt: wiki page URL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_crafting_ingredients_name ON crafting_ingredients(name);

CREATE TABLE IF NOT EXISTS crafting_recipes (                     -- wt: upgrade paths (input + materials -> output)
    id            INTEGER PRIMARY KEY,
    system_id     INTEGER NOT NULL REFERENCES crafting_systems(id) ON DELETE CASCADE,
    option_id     INTEGER REFERENCES crafting_options(id),         -- c: which option/tier this recipe produces
    name          TEXT,                                            -- wt: recipe name if any
    input_item_id INTEGER REFERENCES items(id),                   -- c: item being upgraded (NULL for base crafting)
    output_item_id INTEGER REFERENCES items(id),                  -- c: resulting item (NULL if same item upgraded in place)
    description   TEXT                                             -- wt: recipe description
);
CREATE INDEX IF NOT EXISTS idx_crafting_recipes_system ON crafting_recipes(system_id);
CREATE INDEX IF NOT EXISTS idx_crafting_recipes_input ON crafting_recipes(input_item_id) WHERE input_item_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_crafting_recipes_output ON crafting_recipes(output_item_id) WHERE output_item_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS crafting_recipe_ingredients (          -- wt: materials needed for a recipe
    recipe_id       INTEGER NOT NULL REFERENCES crafting_recipes(id) ON DELETE CASCADE,
    ingredient_id   INTEGER NOT NULL REFERENCES crafting_ingredients(id),
    quantity        INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (recipe_id, ingredient_id)
);
CREATE INDEX IF NOT EXISTS idx_crafting_recipe_ingredients_recipe ON crafting_recipe_ingredients(recipe_id);

-- Spells -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spells (
    id               INTEGER PRIMARY KEY,                        -- c: autoincrement
    name             TEXT NOT NULL,                               -- wt: {{Infobox-spell|name=...}}
    icon             TEXT,                                        -- wt: icon or image field
    school_id        INTEGER REFERENCES spell_schools(id),       -- bp: hash lookup on ref slot; wt: fallback
    spell_points     INTEGER,                                    -- bp: stat 553/554 in ref list/body; wt: cost field fallback
    cooldown         TEXT,                                        -- wt: cooldown field (text)
    cooldown_seconds REAL,                                       -- wt: parsed from cooldown text
    tick_count       INTEGER,                                    -- bp: stat 731 in spell body
    description      TEXT,                                        -- wt: description field
    components       TEXT,                                        -- wt: components field
    range            TEXT,                                        -- wt: range field
    target           TEXT,                                        -- wt: target field
    duration         TEXT,                                        -- wt: duration field
    saving_throw     TEXT,                                        -- wt: save field
    save_type        TEXT CHECK (save_type IS NULL OR save_type {_check(SaveType)}), -- c: parsed from saving_throw
    save_effect      TEXT CHECK (save_effect IS NULL OR save_effect {_check(SaveEffect)}), -- c: parsed from saving_throw
    spell_resistance TEXT                                         -- wt: sr field
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_spells_name ON spells(name);
CREATE INDEX IF NOT EXISTS idx_spells_school ON spells(school_id) WHERE school_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS spell_class_cooldowns (
    spell_id        INTEGER NOT NULL REFERENCES spells(id) ON DELETE CASCADE,
    class_id        INTEGER NOT NULL REFERENCES classes(id),
    cooldown_seconds REAL NOT NULL,
    PRIMARY KEY (spell_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_spell_class_cooldowns_spell ON spell_class_cooldowns(spell_id);

CREATE TABLE IF NOT EXISTS spell_class_levels (
    spell_id    INTEGER NOT NULL REFERENCES spells(id) ON DELETE CASCADE,
    class_id    INTEGER NOT NULL REFERENCES classes(id),
    spell_level INTEGER NOT NULL CHECK (spell_level BETWEEN 1 AND 9),
    PRIMARY KEY (spell_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_spell_class_levels_class ON spell_class_levels(class_id);

CREATE TABLE IF NOT EXISTS spell_metamagics (
    spell_id INTEGER NOT NULL REFERENCES spells(id) ON DELETE CASCADE,
    feat_id  INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (spell_id, feat_id)
);

CREATE TABLE IF NOT EXISTS spell_damage_types (
    spell_id       INTEGER NOT NULL REFERENCES spells(id) ON DELETE CASCADE,
    damage_type_id INTEGER NOT NULL REFERENCES damage_types(id),
    PRIMARY KEY (spell_id, damage_type_id)
);
CREATE INDEX IF NOT EXISTS idx_spell_damage_types_damage_type ON spell_damage_types(damage_type_id);

-- item_spell_links (defined here; items block has forward-reference comment)
CREATE TABLE IF NOT EXISTS item_spell_links (
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    spell_id INTEGER NOT NULL REFERENCES spells(id),
    charges  INTEGER,
    PRIMARY KEY (item_id, spell_id)
);
CREATE INDEX IF NOT EXISTS idx_item_spell_links_spell ON item_spell_links(spell_id);

-- enhancement_spell_links (defined here; enhancements block has forward-reference comment)
CREATE TABLE IF NOT EXISTS enhancement_spell_links (            -- unpopulated (future: wt)
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    spell_id       INTEGER NOT NULL REFERENCES spells(id),
    link_type      TEXT NOT NULL DEFAULT '{LinkType.GRANTS}' CHECK (link_type {_check_subset(LinkType.GRANTS, LinkType.MODIFIES)}),
    min_rank       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (enhancement_id, spell_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_spell_links_spell ON enhancement_spell_links(spell_id);

-- Set Bonuses --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS set_bonuses (
    id   INTEGER PRIMARY KEY,                                    -- c: autoincrement
    name TEXT NOT NULL                                            -- wt: {{Named item sets}} page
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_set_bonuses_name ON set_bonuses(name);

CREATE TABLE IF NOT EXISTS set_bonus_items (                    -- wt: {{Named item sets}} templates
    set_id  INTEGER NOT NULL REFERENCES set_bonuses(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (set_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_set_bonus_items_item ON set_bonus_items(item_id);

-- Effects (weapon/armor enchantments: Vorpal, Bane, Destruction, etc.) ------
CREATE TABLE IF NOT EXISTS effects (
    id          INTEGER PRIMARY KEY,                             -- c: autoincrement
    name        TEXT NOT NULL,                                    -- wt: parsed from enchantment text
    modifier    TEXT,                                             -- wt: modifier from effect template
    description TEXT                                              -- unpopulated
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_effects_name_mod
    ON effects(name, COALESCE(modifier, ''));

CREATE TABLE IF NOT EXISTS item_effects (                       -- wt: parsed from enchantment text via parse_effect_template
    item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    effect_id   INTEGER NOT NULL REFERENCES effects(id),         -- c: joined from effect name
    value       INTEGER,                                         -- wt: effect value (e.g., Bane damage)
    sort_order  INTEGER NOT NULL DEFAULT 0,                      -- c: enumeration order
    data_source TEXT CHECK (data_source {_check(DataSource)}),  -- provenance
    PRIMARY KEY (item_id, effect_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_item_effects_item ON item_effects(item_id);
CREATE INDEX IF NOT EXISTS idx_item_effects_effect ON item_effects(effect_id);

-- Bonus Definitions (normalized: one row per unique stat+bonus_type+value) --
CREATE TABLE IF NOT EXISTS bonuses (
    id            INTEGER PRIMARY KEY,                           -- c: autoincrement
    name          TEXT    NOT NULL,                               -- c: "{{stat}} +{{value}}" format
    description   TEXT,                                           -- ln: effect localization name; wt: enchantment text
    stat_id       INTEGER REFERENCES stats(id),                  -- c: joined from stat name (parsed from ln/wt)
    bonus_type_id INTEGER REFERENCES bonus_types(id),            -- c: joined from bonus_type name (parsed from ln/wt)
    value         INTEGER                                        -- ln: parsed from "+N" in effect name; wt: from template
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bonuses_unique
    ON bonuses(COALESCE(stat_id, -1), COALESCE(bonus_type_id, -1), COALESCE(value, -1), name);
CREATE INDEX IF NOT EXISTS idx_bonuses_stat ON bonuses(stat_id) WHERE stat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bonuses_bonus_type ON bonuses(bonus_type_id) WHERE bonus_type_id IS NOT NULL;

-- M2M: items <-> bonuses
-- resolution_method tracks how stat identity was determined:
--   fid_lookup: EFFECT_FID_LOOKUP table (FID->stat, most reliable)
--   type167_name: parsed from type-167 localization name ("+10 Seeker")
--   stat_def_ids: STAT_DEF_IDS content-based (unreliable fallback)
--   wiki_enchantment: parsed from wiki {{Stat}} or {{SpellPower}} templates
CREATE TABLE IF NOT EXISTS item_bonuses (
    item_id           INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    bonus_id          INTEGER NOT NULL REFERENCES bonuses(id),
    sort_order        INTEGER NOT NULL DEFAULT 0,
    data_source       TEXT CHECK (data_source {_check(DataSource)}),
    resolution_method TEXT CHECK (resolution_method {_check(ResolutionMethod)}),
    PRIMARY KEY (item_id, bonus_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_item_bonuses_item ON item_bonuses(item_id);
CREATE INDEX IF NOT EXISTS idx_item_bonuses_bonus ON item_bonuses(bonus_id);

-- M2M: augments <-> bonuses
CREATE TABLE IF NOT EXISTS augment_bonuses (
    augment_id        INTEGER NOT NULL REFERENCES augments(id) ON DELETE CASCADE,
    bonus_id          INTEGER NOT NULL REFERENCES bonuses(id),
    sort_order        INTEGER NOT NULL DEFAULT 0,
    data_source       TEXT CHECK (data_source {_check(DataSource)}),
    resolution_method TEXT CHECK (resolution_method {_check(ResolutionMethod)}),
    PRIMARY KEY (augment_id, bonus_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_augment_bonuses_augment ON augment_bonuses(augment_id);

-- M2M: enhancements <-> bonuses (with rank activation)
CREATE TABLE IF NOT EXISTS enhancement_bonuses (
    enhancement_id    INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    bonus_id          INTEGER NOT NULL REFERENCES bonuses(id),
    min_rank          INTEGER NOT NULL DEFAULT 1 CHECK (min_rank >= 1),
    data_source       TEXT CHECK (data_source {_check(DataSource)}),
    resolution_method TEXT CHECK (resolution_method {_check(ResolutionMethod)}),
    PRIMARY KEY (enhancement_id, bonus_id, min_rank)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_bonuses_enh ON enhancement_bonuses(enhancement_id);

-- M2M: set_bonuses <-> bonuses (with piece count threshold)
CREATE TABLE IF NOT EXISTS set_bonus_bonuses (
    set_id            INTEGER NOT NULL REFERENCES set_bonuses(id) ON DELETE CASCADE,
    bonus_id          INTEGER NOT NULL REFERENCES bonuses(id),
    min_pieces        INTEGER NOT NULL CHECK (min_pieces >= 2),
    sort_order        INTEGER NOT NULL DEFAULT 0,
    data_source       TEXT CHECK (data_source {_check(DataSource)}),
    resolution_method TEXT CHECK (resolution_method {_check(ResolutionMethod)}),
    PRIMARY KEY (set_id, bonus_id, min_pieces, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_set_bonus_bonuses_set ON set_bonus_bonuses(set_id);

-- Schema versioning --------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT OR IGNORE INTO schema_version (version) VALUES (1);
"""

# ---------------------------------------------------------------------------
# Seed data (inserted after DDL; uses INSERT OR IGNORE for idempotency)
# ---------------------------------------------------------------------------

_SEED_SQL = f"""
-- stats: generated from S enum in _seed_from_enums()

-- skills: generated from Skill enum in _seed_from_enums()

-- Classes
INSERT OR IGNORE INTO classes (id, name, hit_die, bab_progression, skill_points_per_level, fort_save_progression, ref_save_progression, will_save_progression, caster_type, spell_tradition, alignment, icon) VALUES
    (1,  '{Class.BARBARIAN}',   12, '{BabProgression.FULL}',          4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY_NON_LAWFUL}', 'Barbarian.png'),
    (2,  '{Class.BARD}',         8, '{BabProgression.THREE_QUARTER}',  6, '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Bard.png'),
    (3,  '{Class.CLERIC}',       8, '{BabProgression.THREE_QUARTER}',  2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.DIVINE}', '{Alignment.ANY}',            'Cleric.png'),
    (4,  '{Class.FIGHTER}',     10, '{BabProgression.FULL}',           2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY}',            'Fighter.png'),
    (5,  '{Class.PALADIN}',     10, '{BabProgression.FULL}',           2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{CasterType.HALF}',  '{SpellTradition.DIVINE}', '{Alignment.LAWFUL_GOOD}',    'Paladin.png'),
    (6,  '{Class.RANGER}',      10, '{BabProgression.FULL}',           6, '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{CasterType.HALF}',  '{SpellTradition.DIVINE}', '{Alignment.ANY}',            'Ranger.png'),
    (7,  '{Class.ROGUE}',        8, '{BabProgression.THREE_QUARTER}',  8, '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY}',            'Rogue.png'),
    (8,  '{Class.SORCERER}',     6, '{BabProgression.HALF}',           2, '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Sorcerer.png'),
    (9,  '{Class.WIZARD}',       6, '{BabProgression.HALF}',           2, '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Wizard.png'),
    (10, '{Class.MONK}',         8, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY_LAWFUL}',     'Monk.png'),
    (11, '{Class.FAVORED_SOUL}', 8, '{BabProgression.THREE_QUARTER}',  2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.DIVINE}', '{Alignment.ANY}',            'Favored Soul.png'),
    (12, '{Class.ARTIFICER}',    8, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Artificer.png'),
    (13, '{Class.DRUID}',        8, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.DIVINE}', '{Alignment.ANY_NEUTRAL}',    'Druid.png'),
    (14, '{Class.WARLOCK}',      6, '{BabProgression.THREE_QUARTER}',  2, '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Warlock.png'),
    (15, '{Class.ALCHEMIST}',    6, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Alchemist.png');

-- Archetypes (modify a base class; inherit most stats from parent)
INSERT OR IGNORE INTO classes (id, name, parent_class_id, is_archetype) VALUES
    (16, '{Archetype.DRAGON_LORD}',          4,  1),   -- Fighter archetype
    (17, '{Archetype.DRAGON_DISCIPLE}',      8,  1),   -- Sorcerer archetype
    (18, '{Archetype.ARCANE_TRICKSTER}',     7,  1),   -- Rogue archetype
    (19, '{Archetype.WILD_MAGE}',            9,  1),   -- Wizard archetype
    (20, '{Archetype.STORMSINGER}',          2,  1),   -- Bard archetype
    (21, '{Archetype.DARK_APOSTATE}',        3,  1),   -- Cleric archetype
    (22, '{Archetype.BLIGHTCASTER}',        13,  1),   -- Druid archetype
    (23, '{Archetype.SACRED_FIST}',          5,  1),   -- Paladin archetype
    (24, '{Archetype.DARK_HUNTER}',          6,  1),   -- Ranger archetype
    (25, '{Archetype.ACOLYTE_OF_THE_SKIN}', 14,  1);   -- Warlock archetype

-- Races (standard + iconic)
INSERT OR IGNORE INTO races (id, name, race_type, icon) VALUES
    -- Free races (icons resolved at build time via MediaWiki allimages API)
    (1,  '{Race.HUMAN}',      '{RaceType.FREE}',    'Human_race_icon.png'),
    (2,  '{Race.ELF}',        '{RaceType.FREE}',    'Elf_race_icon.png'),
    (3,  '{Race.DWARF}',      '{RaceType.FREE}',    'Dwarf_race_icon.png'),
    (4,  '{Race.HALFLING}',   '{RaceType.FREE}',    'Halfling_race_icon.png'),
    (5,  '{Race.WARFORGED}',  '{RaceType.FREE}',    'Warforged_race_icon.png'),
    (6,  '{Race.DROW_ELF}',   '{RaceType.FREE}',    'Drow_race_icon.png'),
    (7,  '{Race.HALF_ELF}',   '{RaceType.FREE}',    'Half-Elf_race_icon.png'),
    (8,  '{Race.HALF_ORC}',   '{RaceType.FREE}',    'Half-Orc_race_icon.png'),
    (9,  '{Race.GNOME}',      '{RaceType.FREE}',    'Gnome_race_icon.png'),
    (10, '{Race.DRAGONBORN}', '{RaceType.FREE}',    'Dragonborn_race_icon.png'),
    (11, '{Race.TIEFLING}',   '{RaceType.FREE}',    'Tiefling_race_icon.png'),
    (12, '{Race.WOOD_ELF}',   '{RaceType.FREE}',    'Wood_Elf_race_icon.jpg'),
    -- Premium races
    (13, '{Race.AASIMAR}',    '{RaceType.PREMIUM}', 'Aasimar_race_icon.png'),
    (14, '{Race.TABAXI}',     '{RaceType.PREMIUM}', 'Tabaxi_race_icon.png'),
    (15, '{Race.SHIFTER}',    '{RaceType.PREMIUM}', 'Shifter_race_icon.png'),
    (16, '{Race.ELADRIN}',    '{RaceType.PREMIUM}', 'Eladrin_race_icon.png'),
    (17, '{Race.DHAMPIR}',    '{RaceType.PREMIUM}', 'Dhampir_race_icon.png'),
    -- Iconic races (start at class level, have a parent base race)
    (18, '{Race.BLADEFORGED}',           '{RaceType.ICONIC}', 'Bladeforged_race_icon.png'),
    (19, '{Race.PURPLE_DRAGON_KNIGHT}',  '{RaceType.ICONIC}', 'Purple_Dragon_Knight_race_icon.png'),
    (20, '{Race.MORNINGLORD}',           '{RaceType.ICONIC}', 'Morninglord_race_icon.png'),
    (21, '{Race.SHADAR_KAI}',            '{RaceType.ICONIC}', 'Shadar-Kai_race_icon.png'),
    (22, '{Race.DEEP_GNOME}',            '{RaceType.ICONIC}', 'Deep_Gnome_race_icon.png'),
    (23, '{Race.AASIMAR_SCOURGE}',       '{RaceType.ICONIC}', 'Aasimar_Scourge_race_icon.png'),
    (24, '{Race.RAZORCLAW_SHIFTER}',     '{RaceType.ICONIC}', 'Razorclaw_Shifter_race_icon.png'),
    (25, '{Race.TIEFLING_SCOUNDREL}',    '{RaceType.ICONIC}', 'Tiefling_Scoundrel_race_icon.png'),
    (26, '{Race.TABAXI_TRAILBLAZER}',    '{RaceType.ICONIC}', 'Tabaxi_Trailblazer_race_icon.png'),
    (27, '{Race.ELADRIN_CHAOSMANCER}',   '{RaceType.ICONIC}', 'Eladrin_Chaosmancer_race_icon.png'),
    (28, '{Race.DHAMPIR_DARK_BARGAINER}','{RaceType.ICONIC}', NULL);

-- bonus_types: generated from BonusType enum in _seed_from_enums()

-- damage_types: generated from DamageType enum in _seed_from_enums()

-- Weapon proficiencies: generated from ProficiencyCategory enum in _seed_from_enums()

-- equipment_slots: generated from EquipmentSlot enum in _seed_from_enums()

-- Spell schools: generated from SpellSchool enum in _seed_from_enums()

-- Class skills (sd: from DDO wiki class pages)
INSERT OR IGNORE INTO class_skills (class_id, skill_id) VALUES
    -- Barbarian: Balance, Intimidate, Jump, Listen, Swim
    ({Class.BARBARIAN.id},{Skill.BALANCE.id}),({Class.BARBARIAN.id},{Skill.INTIMIDATE_SKILL.id}),({Class.BARBARIAN.id},{Skill.JUMP.id}),({Class.BARBARIAN.id},{Skill.LISTEN.id}),({Class.BARBARIAN.id},{Skill.SWIM.id}),
    -- Bard: Balance, Bluff, Concentration, Diplomacy, Haggle, Hide, Jump, Listen,
    --       Move Silently, Open Lock, Perform, Repair, Spellcraft, Swim, Tumble, UMD
    ({Class.BARD.id},{Skill.BALANCE.id}),({Class.BARD.id},{Skill.BLUFF.id}),({Class.BARD.id},{Skill.CONCENTRATION.id}),({Class.BARD.id},{Skill.DIPLOMACY.id}),({Class.BARD.id},{Skill.HAGGLE.id}),({Class.BARD.id},{Skill.HIDE_SKILL.id}),({Class.BARD.id},{Skill.JUMP.id}),({Class.BARD.id},{Skill.LISTEN.id}),({Class.BARD.id},{Skill.MOVE_SILENTLY.id}),({Class.BARD.id},{Skill.OPEN_LOCK.id}),({Class.BARD.id},{Skill.PERFORM_SKILL.id}),({Class.BARD.id},{Skill.REPAIR_SKILL.id}),({Class.BARD.id},{Skill.SPELLCRAFT.id}),({Class.BARD.id},{Skill.SWIM.id}),({Class.BARD.id},{Skill.TUMBLE.id}),({Class.BARD.id},{Skill.USE_MAGIC_DEVICE.id}),
    -- Cleric: Concentration, Diplomacy, Heal, Spellcraft
    ({Class.CLERIC.id},{Skill.CONCENTRATION.id}),({Class.CLERIC.id},{Skill.DIPLOMACY.id}),({Class.CLERIC.id},{Skill.HEAL_SKILL.id}),({Class.CLERIC.id},{Skill.SPELLCRAFT.id}),
    -- Fighter: Balance, Intimidate, Jump, Repair, Swim
    ({Class.FIGHTER.id},{Skill.BALANCE.id}),({Class.FIGHTER.id},{Skill.INTIMIDATE_SKILL.id}),({Class.FIGHTER.id},{Skill.JUMP.id}),({Class.FIGHTER.id},{Skill.REPAIR_SKILL.id}),({Class.FIGHTER.id},{Skill.SWIM.id}),
    -- Paladin: Balance, Concentration, Diplomacy, Heal, Intimidate, Jump, Swim
    ({Class.PALADIN.id},{Skill.BALANCE.id}),({Class.PALADIN.id},{Skill.CONCENTRATION.id}),({Class.PALADIN.id},{Skill.DIPLOMACY.id}),({Class.PALADIN.id},{Skill.HEAL_SKILL.id}),({Class.PALADIN.id},{Skill.INTIMIDATE_SKILL.id}),({Class.PALADIN.id},{Skill.JUMP.id}),({Class.PALADIN.id},{Skill.SWIM.id}),
    -- Ranger: Balance, Concentration, Heal, Hide, Jump, Listen, Move Silently, Search, Spot, Swim
    ({Class.RANGER.id},{Skill.BALANCE.id}),({Class.RANGER.id},{Skill.CONCENTRATION.id}),({Class.RANGER.id},{Skill.HEAL_SKILL.id}),({Class.RANGER.id},{Skill.HIDE_SKILL.id}),({Class.RANGER.id},{Skill.JUMP.id}),({Class.RANGER.id},{Skill.LISTEN.id}),({Class.RANGER.id},{Skill.MOVE_SILENTLY.id}),({Class.RANGER.id},{Skill.SEARCH_SKILL.id}),({Class.RANGER.id},{Skill.SPOT_SKILL.id}),({Class.RANGER.id},{Skill.SWIM.id}),
    -- Rogue: Balance, Bluff, Diplomacy, Disable Device, Haggle, Hide, Intimidate, Jump, Listen,
    --        Move Silently, Open Lock, Perform, Repair, Search, Spot, Swim, Tumble, UMD
    ({Class.ROGUE.id},{Skill.BALANCE.id}),({Class.ROGUE.id},{Skill.BLUFF.id}),({Class.ROGUE.id},{Skill.DIPLOMACY.id}),({Class.ROGUE.id},{Skill.DISABLE_DEVICE.id}),({Class.ROGUE.id},{Skill.HAGGLE.id}),({Class.ROGUE.id},{Skill.HIDE_SKILL.id}),({Class.ROGUE.id},{Skill.INTIMIDATE_SKILL.id}),({Class.ROGUE.id},{Skill.JUMP.id}),({Class.ROGUE.id},{Skill.LISTEN.id}),({Class.ROGUE.id},{Skill.MOVE_SILENTLY.id}),({Class.ROGUE.id},{Skill.OPEN_LOCK.id}),({Class.ROGUE.id},{Skill.PERFORM_SKILL.id}),({Class.ROGUE.id},{Skill.REPAIR_SKILL.id}),({Class.ROGUE.id},{Skill.SEARCH_SKILL.id}),({Class.ROGUE.id},{Skill.SPOT_SKILL.id}),({Class.ROGUE.id},{Skill.SWIM.id}),({Class.ROGUE.id},{Skill.TUMBLE.id}),({Class.ROGUE.id},{Skill.USE_MAGIC_DEVICE.id}),
    -- Sorcerer: Bluff, Concentration, Spellcraft
    ({Class.SORCERER.id},{Skill.BLUFF.id}),({Class.SORCERER.id},{Skill.CONCENTRATION.id}),({Class.SORCERER.id},{Skill.SPELLCRAFT.id}),
    -- Wizard: Concentration, Repair, Spellcraft
    ({Class.WIZARD.id},{Skill.CONCENTRATION.id}),({Class.WIZARD.id},{Skill.REPAIR_SKILL.id}),({Class.WIZARD.id},{Skill.SPELLCRAFT.id}),
    -- Monk: Balance, Concentration, Diplomacy, Hide, Jump, Listen, Move Silently, Spot, Swim, Tumble
    ({Class.MONK.id},{Skill.BALANCE.id}),({Class.MONK.id},{Skill.CONCENTRATION.id}),({Class.MONK.id},{Skill.DIPLOMACY.id}),({Class.MONK.id},{Skill.HIDE_SKILL.id}),({Class.MONK.id},{Skill.JUMP.id}),({Class.MONK.id},{Skill.LISTEN.id}),({Class.MONK.id},{Skill.MOVE_SILENTLY.id}),({Class.MONK.id},{Skill.SPOT_SKILL.id}),({Class.MONK.id},{Skill.SWIM.id}),({Class.MONK.id},{Skill.TUMBLE.id}),
    -- Favored Soul: Concentration, Diplomacy, Heal, Jump, Spellcraft
    ({Class.FAVORED_SOUL.id},{Skill.CONCENTRATION.id}),({Class.FAVORED_SOUL.id},{Skill.DIPLOMACY.id}),({Class.FAVORED_SOUL.id},{Skill.HEAL_SKILL.id}),({Class.FAVORED_SOUL.id},{Skill.JUMP.id}),({Class.FAVORED_SOUL.id},{Skill.SPELLCRAFT.id}),
    -- Artificer: Balance, Concentration, Disable Device, Haggle, Open Lock, Repair, Search, Spellcraft, UMD
    ({Class.ARTIFICER.id},{Skill.BALANCE.id}),({Class.ARTIFICER.id},{Skill.CONCENTRATION.id}),({Class.ARTIFICER.id},{Skill.DISABLE_DEVICE.id}),({Class.ARTIFICER.id},{Skill.HAGGLE.id}),({Class.ARTIFICER.id},{Skill.OPEN_LOCK.id}),({Class.ARTIFICER.id},{Skill.REPAIR_SKILL.id}),({Class.ARTIFICER.id},{Skill.SEARCH_SKILL.id}),({Class.ARTIFICER.id},{Skill.SPELLCRAFT.id}),({Class.ARTIFICER.id},{Skill.USE_MAGIC_DEVICE.id}),
    -- Druid: Balance, Concentration, Diplomacy, Heal, Hide, Listen, Spellcraft, Spot, Swim
    ({Class.DRUID.id},{Skill.BALANCE.id}),({Class.DRUID.id},{Skill.CONCENTRATION.id}),({Class.DRUID.id},{Skill.DIPLOMACY.id}),({Class.DRUID.id},{Skill.HEAL_SKILL.id}),({Class.DRUID.id},{Skill.HIDE_SKILL.id}),({Class.DRUID.id},{Skill.LISTEN.id}),({Class.DRUID.id},{Skill.SPELLCRAFT.id}),({Class.DRUID.id},{Skill.SPOT_SKILL.id}),({Class.DRUID.id},{Skill.SWIM.id}),
    -- Warlock: Bluff, Concentration, Intimidate, Spellcraft, UMD
    ({Class.WARLOCK.id},{Skill.BLUFF.id}),({Class.WARLOCK.id},{Skill.CONCENTRATION.id}),({Class.WARLOCK.id},{Skill.INTIMIDATE_SKILL.id}),({Class.WARLOCK.id},{Skill.SPELLCRAFT.id}),({Class.WARLOCK.id},{Skill.USE_MAGIC_DEVICE.id}),
    -- Alchemist: Balance, Concentration, Disable Device, Heal, Repair, Search, Spellcraft, UMD
    ({Class.ALCHEMIST.id},{Skill.BALANCE.id}),({Class.ALCHEMIST.id},{Skill.CONCENTRATION.id}),({Class.ALCHEMIST.id},{Skill.DISABLE_DEVICE.id}),({Class.ALCHEMIST.id},{Skill.HEAL_SKILL.id}),({Class.ALCHEMIST.id},{Skill.REPAIR_SKILL.id}),({Class.ALCHEMIST.id},{Skill.SEARCH_SKILL.id}),({Class.ALCHEMIST.id},{Skill.SPELLCRAFT.id}),({Class.ALCHEMIST.id},{Skill.USE_MAGIC_DEVICE.id});

-- Race ability bonuses (sd: from DDO wiki race pages)
-- Standard races only (iconics inherit from base race + class)
-- Innate racial ability modifiers (from ddowiki.com/page/Races stat range columns)
INSERT OR IGNORE INTO race_ability_modifiers (race_id, stat_id, modifier, source) VALUES
    -- 1=Human: no innate mods
    -- 2=Elf: +2 DEX, -2 CON
    ({Race.ELF.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'), ({Race.ELF.id}, {S.CONSTITUTION.id}, -2, '{AbilityModSource.INNATE}'),
    -- 3=Dwarf: +2 CON, -2 CHA
    ({Race.DWARF.id}, {S.CONSTITUTION.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DWARF.id}, {S.CHARISMA.id}, -2, '{AbilityModSource.INNATE}'),
    -- 4=Halfling: +2 DEX, -2 STR
    ({Race.HALFLING.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'), ({Race.HALFLING.id}, {S.STRENGTH.id}, -2, '{AbilityModSource.INNATE}'),
    -- 5=Warforged: +2 CON, -2 WIS, -2 CHA
    ({Race.WARFORGED.id}, {S.CONSTITUTION.id}, 2, '{AbilityModSource.INNATE}'), ({Race.WARFORGED.id}, {S.WISDOM.id}, -2, '{AbilityModSource.INNATE}'), ({Race.WARFORGED.id}, {S.CHARISMA.id}, -2, '{AbilityModSource.INNATE}'),
    -- 6=Drow Elf: +2 DEX, +2 INT, +2 CHA, -2 CON
    ({Race.DROW_ELF.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DROW_ELF.id}, {S.INTELLIGENCE.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DROW_ELF.id}, {S.CHARISMA.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DROW_ELF.id}, {S.CONSTITUTION.id}, -2, '{AbilityModSource.INNATE}'),
    -- 7=Half-Elf: no innate mods
    -- 8=Half-Orc: +2 STR, -2 INT, -2 CHA
    ({Race.HALF_ORC.id}, {S.STRENGTH.id}, 2, '{AbilityModSource.INNATE}'), ({Race.HALF_ORC.id}, {S.INTELLIGENCE.id}, -2, '{AbilityModSource.INNATE}'), ({Race.HALF_ORC.id}, {S.CHARISMA.id}, -2, '{AbilityModSource.INNATE}'),
    -- 9=Gnome: +2 INT, -2 STR
    ({Race.GNOME.id}, {S.INTELLIGENCE.id}, 2, '{AbilityModSource.INNATE}'), ({Race.GNOME.id}, {S.STRENGTH.id}, -2, '{AbilityModSource.INNATE}'),
    -- 10=Dragonborn: +2 STR, +2 CHA, -2 DEX
    ({Race.DRAGONBORN.id}, {S.STRENGTH.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DRAGONBORN.id}, {S.CHARISMA.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DRAGONBORN.id}, {S.DEXTERITY.id}, -2, '{AbilityModSource.INNATE}'),
    -- 11=Tiefling: +2 CHA
    ({Race.TIEFLING.id}, {S.CHARISMA.id}, 2, '{AbilityModSource.INNATE}'),
    -- 12=Wood Elf: +2 DEX, -2 INT
    ({Race.WOOD_ELF.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'), ({Race.WOOD_ELF.id}, {S.INTELLIGENCE.id}, -2, '{AbilityModSource.INNATE}'),
    -- 13=Aasimar: +2 WIS
    ({Race.AASIMAR.id}, {S.WISDOM.id}, 2, '{AbilityModSource.INNATE}'),
    -- 14=Tabaxi: +2 DEX
    ({Race.TABAXI.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'),
    -- 15=Shifter: +2 DEX, -2 INT
    ({Race.SHIFTER.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'), ({Race.SHIFTER.id}, {S.INTELLIGENCE.id}, -2, '{AbilityModSource.INNATE}'),
    -- 16=Eladrin: +2 DEX
    ({Race.ELADRIN.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'),
    -- 17=Dhampir: +2 STR
    ({Race.DHAMPIR.id}, {S.STRENGTH.id}, 2, '{AbilityModSource.INNATE}'),
    -- 18=Bladeforged: +2 CON, -2 DEX, -2 WIS
    ({Race.BLADEFORGED.id}, {S.CONSTITUTION.id}, 2, '{AbilityModSource.INNATE}'), ({Race.BLADEFORGED.id}, {S.DEXTERITY.id}, -2, '{AbilityModSource.INNATE}'), ({Race.BLADEFORGED.id}, {S.WISDOM.id}, -2, '{AbilityModSource.INNATE}'),
    -- 19=Purple Dragon Knight: no innate mods
    -- 20=Morninglord: +2 INT, -2 CON
    ({Race.MORNINGLORD.id}, {S.INTELLIGENCE.id}, 2, '{AbilityModSource.INNATE}'), ({Race.MORNINGLORD.id}, {S.CONSTITUTION.id}, -2, '{AbilityModSource.INNATE}'),
    -- 21=Shadar-kai: +2 DEX, -2 CHA
    ({Race.SHADAR_KAI.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'), ({Race.SHADAR_KAI.id}, {S.CHARISMA.id}, -2, '{AbilityModSource.INNATE}'),
    -- 22=Deep Gnome: +2 INT, +2 WIS, -2 STR, -2 CHA
    ({Race.DEEP_GNOME.id}, {S.INTELLIGENCE.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DEEP_GNOME.id}, {S.WISDOM.id}, 2, '{AbilityModSource.INNATE}'), ({Race.DEEP_GNOME.id}, {S.STRENGTH.id}, -2, '{AbilityModSource.INNATE}'), ({Race.DEEP_GNOME.id}, {S.CHARISMA.id}, -2, '{AbilityModSource.INNATE}'),
    -- 23=Aasimar Scourge: +2 WIS
    ({Race.AASIMAR_SCOURGE.id}, {S.WISDOM.id}, 2, '{AbilityModSource.INNATE}'),
    -- 24=Razorclaw Shifter: +2 STR, -2 INT
    ({Race.RAZORCLAW_SHIFTER.id}, {S.STRENGTH.id}, 2, '{AbilityModSource.INNATE}'), ({Race.RAZORCLAW_SHIFTER.id}, {S.INTELLIGENCE.id}, -2, '{AbilityModSource.INNATE}'),
    -- 25=Tiefling Scoundrel: +2 CHA
    ({Race.TIEFLING_SCOUNDREL.id}, {S.CHARISMA.id}, 2, '{AbilityModSource.INNATE}'),
    -- 26=Tabaxi Trailblazer: +2 DEX
    ({Race.TABAXI_TRAILBLAZER.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.INNATE}'),
    -- 27=Eladrin Chaosmancer: +2 CHA
    ({Race.ELADRIN_CHAOSMANCER.id}, {S.CHARISMA.id}, 2, '{AbilityModSource.INNATE}'),
    -- 28=Dhampir Dark Bargainer: +1 CHA, +1 INT
    ({Race.DHAMPIR_DARK_BARGAINER.id}, {S.CHARISMA.id}, 1, '{AbilityModSource.INNATE}'), ({Race.DHAMPIR_DARK_BARGAINER.id}, {S.INTELLIGENCE.id}, 1, '{AbilityModSource.INNATE}');

-- Enhancement racial ability modifiers (from racial enhancement trees, ddowiki.com/page/Races)
-- Fixed bonuses from core abilities; choice-based from racial tree picks
-- is_choice=1 means player distributes choice_pool points among marked stats
INSERT OR IGNORE INTO race_ability_modifiers (race_id, stat_id, modifier, source, is_choice, choice_pool) VALUES
    -- 1=Human: choose +1 to any stat, +1 to a different stat (pool=1 each pick)
    ({Race.HUMAN.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.HUMAN.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    ({Race.HUMAN.id}, {S.CONSTITUTION.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.HUMAN.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    ({Race.HUMAN.id}, {S.WISDOM.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.HUMAN.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    -- 2=Elf: +2 DEX
    ({Race.ELF.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 3=Dwarf: +2 CON
    ({Race.DWARF.id}, {S.CONSTITUTION.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 4=Halfling: +2 DEX
    ({Race.HALFLING.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 5=Warforged: +2 CON
    ({Race.WARFORGED.id}, {S.CONSTITUTION.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 6=Drow Elf: +2 total from DEX/INT/CHA
    ({Race.DROW_ELF.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DROW_ELF.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DROW_ELF.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 7=Half-Elf: as Elf or Human (choice)
    ({Race.HALF_ELF.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.HALF_ELF.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    ({Race.HALF_ELF.id}, {S.CONSTITUTION.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.HALF_ELF.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    ({Race.HALF_ELF.id}, {S.WISDOM.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.HALF_ELF.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 8=Half-Orc: +2 STR
    ({Race.HALF_ORC.id}, {S.STRENGTH.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 9=Gnome: +2 INT
    ({Race.GNOME.id}, {S.INTELLIGENCE.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 10=Dragonborn: +2 total from STR/CHA
    ({Race.DRAGONBORN.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DRAGONBORN.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 11=Tiefling: +2 CHA
    ({Race.TIEFLING.id}, {S.CHARISMA.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 12=Wood Elf: (none parsed — wiki cell truncated)
    -- 13=Aasimar: +2 total from STR/WIS/CHA
    ({Race.AASIMAR.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.AASIMAR.id}, {S.WISDOM.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.AASIMAR.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 14=Tabaxi: +2 total from CHA/DEX
    ({Race.TABAXI.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.TABAXI.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 15=Shifter: +2 total from STR/DEX/CON/WIS
    ({Race.SHIFTER.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.SHIFTER.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    ({Race.SHIFTER.id}, {S.CONSTITUTION.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.SHIFTER.id}, {S.WISDOM.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 16=Eladrin: +1 CHA (fixed) + +2 total from DEX/INT/CHA
    ({Race.ELADRIN.id}, {S.CHARISMA.id}, 1, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    ({Race.ELADRIN.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.ELADRIN.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 17=Dhampir: +2 total from STR/CON/CHA
    ({Race.DHAMPIR.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DHAMPIR.id}, {S.CONSTITUTION.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DHAMPIR.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 18=Bladeforged: +2 CON
    ({Race.BLADEFORGED.id}, {S.CONSTITUTION.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 19=Purple Dragon Knight: choose +1 to any stat, +1 to different stat
    ({Race.PURPLE_DRAGON_KNIGHT.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.PURPLE_DRAGON_KNIGHT.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    ({Race.PURPLE_DRAGON_KNIGHT.id}, {S.CONSTITUTION.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.PURPLE_DRAGON_KNIGHT.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    ({Race.PURPLE_DRAGON_KNIGHT.id}, {S.WISDOM.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.PURPLE_DRAGON_KNIGHT.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    -- 20=Morninglord: +2 INT
    ({Race.MORNINGLORD.id}, {S.INTELLIGENCE.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 21=Shadar-kai: +1 total from DEX/INT/CHA
    ({Race.SHADAR_KAI.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.SHADAR_KAI.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), ({Race.SHADAR_KAI.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    -- 22=Deep Gnome: +2 total from WIS/INT
    ({Race.DEEP_GNOME.id}, {S.WISDOM.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DEEP_GNOME.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 23=Aasimar Scourge: +1 CON (fixed) + +2 total from STR/WIS/CHA
    ({Race.AASIMAR_SCOURGE.id}, {S.CONSTITUTION.id}, 1, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    ({Race.AASIMAR_SCOURGE.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.AASIMAR_SCOURGE.id}, {S.WISDOM.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.AASIMAR_SCOURGE.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 24=Razorclaw Shifter: +2 total from STR/DEX/CON
    ({Race.RAZORCLAW_SHIFTER.id}, {S.STRENGTH.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.RAZORCLAW_SHIFTER.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.RAZORCLAW_SHIFTER.id}, {S.CONSTITUTION.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 25=Tiefling Scoundrel: +2 CHA
    ({Race.TIEFLING_SCOUNDREL.id}, {S.CHARISMA.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 26=Tabaxi Trailblazer: +2 DEX
    ({Race.TABAXI_TRAILBLAZER.id}, {S.DEXTERITY.id}, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 27=Eladrin Chaosmancer: +1 CHA (fixed) + +2 total from DEX/INT/CHA
    ({Race.ELADRIN_CHAOSMANCER.id}, {S.CHARISMA.id}, 1, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    ({Race.ELADRIN_CHAOSMANCER.id}, {S.DEXTERITY.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.ELADRIN_CHAOSMANCER.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 28=Dhampir Dark Bargainer: +2 total from CHA/CON/INT
    ({Race.DHAMPIR_DARK_BARGAINER.id}, {S.CHARISMA.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DHAMPIR_DARK_BARGAINER.id}, {S.CONSTITUTION.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), ({Race.DHAMPIR_DARK_BARGAINER.id}, {S.INTELLIGENCE.id}, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2);

-- Universal feat slot schedule (every character gets these, independent of class/race)
INSERT OR IGNORE INTO feat_slots (character_level, sort_order, slot_tier) VALUES
    -- Heroic standard feats
    (1,  0, '{SlotTier.HEROIC}'), (3,  0, '{SlotTier.HEROIC}'), (6,  0, '{SlotTier.HEROIC}'), (9,  0, '{SlotTier.HEROIC}'),
    (12, 0, '{SlotTier.HEROIC}'), (15, 0, '{SlotTier.HEROIC}'), (18, 0, '{SlotTier.HEROIC}'),
    -- Epic standard feats
    (21, 0, '{SlotTier.EPIC}'), (24, 0, '{SlotTier.EPIC}'), (27, 0, '{SlotTier.EPIC}'),
    -- Epic Destiny feats (separate pool)
    (22, 0, '{SlotTier.DESTINY}'), (25, 0, '{SlotTier.DESTINY}'), (28, 0, '{SlotTier.DESTINY}'),
    -- Level 30: one epic feat + one legendary feat
    (30, 0, '{SlotTier.EPIC}'), (30, 1, '{SlotTier.LEGENDARY}');

-- Race bonus feat slots (races that grant extra feat choices)
INSERT OR IGNORE INTO race_bonus_feat_slots (race_id, character_level, slot_tier) VALUES
    ({Race.HUMAN.id},  1, '{SlotTier.HEROIC}'),   -- Human: +1 standard feat at level 1
    ({Race.PURPLE_DRAGON_KNIGHT.id}, 1, '{SlotTier.HEROIC}');   -- Purple Dragon Knight: same as Human
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _seed_from_enums(conn: sqlite3.Connection) -> None:
    """Generate and insert seed data from enum definitions.

    Tables whose rows are 1:1 with enum members are generated here
    rather than hardcoded in SQL. This ensures the DB stays in sync
    with the enum definitions automatically.
    """
    # stats: id, name, category from S enum
    for m in S:
        conn.execute(
            "INSERT OR IGNORE INTO stats (id, name, category) VALUES (?, ?, ?)",
            (m.id, str(m), str(m.category)),
        )

    # skills: id, name, key_ability_id from Skill enum
    for m in Skill:
        conn.execute(
            "INSERT OR IGNORE INTO skills (id, name, key_ability_id) VALUES (?, ?, ?)",
            (m.id, str(m), m.key_ability_id),
        )

    # bonus_types: id, name, stacks_with_self from BonusType enum
    for m in BonusType:
        conn.execute(
            "INSERT OR IGNORE INTO bonus_types (id, name, stacks_with_self) VALUES (?, ?, ?)",
            (m.id, str(m), 1 if m.stacks_with_self else 0),
        )

    # damage_types: id, name, category from DamageType enum
    for m in DamageType:
        conn.execute(
            "INSERT OR IGNORE INTO damage_types (id, name, category) VALUES (?, ?, ?)",
            (m.id, str(m), str(m.category)),
        )

    # equipment_slots: id, name, sort_order, category from EquipmentSlot enum
    for m in EquipmentSlot:
        conn.execute(
            "INSERT OR IGNORE INTO equipment_slots (id, name, sort_order, category) VALUES (?, ?, ?, ?)",
            (m.id, str(m), m.sort_order, str(m.category)),
        )

    # spell_schools: id (auto), name from SpellSchool
    for i, member in enumerate(SpellSchool, 1):
        conn.execute(
            "INSERT OR IGNORE INTO spell_schools (id, name) VALUES (?, ?)",
            (i, str(member)),
        )

    # weapon_proficiencies: id (auto), name + category from ProficiencyCategory
    for i, member in enumerate(ProficiencyCategory, 1):
        conn.execute(
            "INSERT OR IGNORE INTO weapon_proficiencies (id, name, category) VALUES (?, ?, ?)",
            (i, member.value.title(), str(member)),
        )

    # crafting_systems: id, name from CraftingSystem enum
    for m in CraftingSystem:
        conn.execute(
            "INSERT OR IGNORE INTO crafting_systems (id, name) VALUES (?, ?)",
            (m.id, str(m)),
        )


def create_schema(conn: sqlite3.Connection) -> None:
    """Apply SCHEMA_V1 DDL and seed reference data to *conn*.

    Safe to call on an existing database — uses ``CREATE TABLE IF NOT EXISTS``
    and ``INSERT OR IGNORE`` throughout, so re-running is idempotent.
    """
    conn.executescript(SCHEMA_V1)
    _seed_from_enums(conn)  # must run before _SEED_SQL (classes/races FK stats/skills)
    conn.executescript(_SEED_SQL)
    conn.commit()