"""DDO game database schema — DDL and seed data for SQLite."""

from __future__ import annotations

import sqlite3

from ddo_data.enums import (
    AbilityModSource, Alignment, ApPool, BabProgression, CasterType,
    DamageCategory, DataSource, EnhancementTier, EquipmentSlot, FeatTier,
    Handedness, ItemCategory, LinkType, PastLifeType, ProficiencyCategory,
    RaceType, Rarity, ResolutionMethod, SaveEffect, SaveProgression, SaveType,
    SlotCategory, SlotTier, SlotType, SpellSchool, SpellTradition,
    StatCategory, TreeType,
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
    WHERE source = 'innate';

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
    slot_type     TEXT NOT NULL DEFAULT 'class_bonus'
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
        (tree_type = 'class'     AND ap_pool = 'heroic'    AND class_id IS NOT NULL AND race_id IS NULL) OR
        (tree_type = 'racial'    AND ap_pool = 'racial'    AND race_id  IS NOT NULL AND class_id IS NULL) OR
        (tree_type = 'universal' AND ap_pool = 'heroic'    AND class_id IS NULL     AND race_id IS NULL) OR
        (tree_type = 'reaper'    AND ap_pool = 'reaper'    AND class_id IS NULL     AND race_id IS NULL) OR
        (tree_type = 'destiny'   AND ap_pool = 'legendary' AND class_id IS NULL     AND race_id IS NULL)
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
    prerequisite TEXT                                             -- wt: prereq field
);
CREATE INDEX IF NOT EXISTS idx_enhancements_tree ON enhancements(tree_id);
CREATE INDEX IF NOT EXISTS idx_enhancements_name ON enhancements(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_enhancements_unique ON enhancements(tree_id, name, tier, progression);

CREATE TABLE IF NOT EXISTS enhancement_ranks (
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    rank           INTEGER NOT NULL CHECK (rank >= 1),           -- c: sequential
    description    TEXT,                                          -- wt: description field (rank 1 only currently)
    PRIMARY KEY (enhancement_id, rank)
);

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
-- Ability scores
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (1, 'Strength',     '{StatCategory.ABILITY}'),
    (2, 'Dexterity',    '{StatCategory.ABILITY}'),
    (3, 'Constitution', '{StatCategory.ABILITY}'),
    (4, 'Intelligence', '{StatCategory.ABILITY}'),
    (5, 'Wisdom',       '{StatCategory.ABILITY}'),
    (6, 'Charisma',     '{StatCategory.ABILITY}');

-- Martial stats (melee/ranged offense, tactics)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (7,  'Melee Power',       '{StatCategory.MARTIAL}'),
    (8,  'Ranged Power',      '{StatCategory.MARTIAL}'),
    (9,  'Attack Bonus',      '{StatCategory.MARTIAL}'),
    (10, 'Damage Bonus',      '{StatCategory.MARTIAL}'),
    (11, 'Hit Points',        '{StatCategory.MARTIAL}'),
    (12, 'Sneak Attack Dice', '{StatCategory.MARTIAL}'),
    (36, 'Trip DC',           '{StatCategory.MARTIAL}'),
    (37, 'Sunder DC',         '{StatCategory.MARTIAL}'),
    (38, 'Stun DC',           '{StatCategory.MARTIAL}'),
    (39, 'Assassinate DC',    '{StatCategory.MARTIAL}'),
    (40, 'Helpless Damage',   '{StatCategory.MARTIAL}'),
    (63, 'Seeker',            '{StatCategory.MARTIAL}'),
    (64, 'Deadly',            '{StatCategory.MARTIAL}'),
    (65, 'Accuracy',          '{StatCategory.MARTIAL}'),
    (66, 'Deception',         '{StatCategory.MARTIAL}'),
    (67, 'Speed',             '{StatCategory.MARTIAL}'),
    (68, 'Doublestrike',      '{StatCategory.MARTIAL}'),
    (69, 'Doubleshot',        '{StatCategory.MARTIAL}'),
    (118, 'Combat Mastery',   '{StatCategory.MARTIAL}'),
    (119, 'Tendon Slice',     '{StatCategory.MARTIAL}'),
    (124, 'Nimble',           '{StatCategory.MARTIAL}'),
    (125, 'Alluring',         '{StatCategory.MARTIAL}');

-- Defensive stats (AC, saves, resistances, sheltering, absorption)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (13, 'Armor Class',                '{StatCategory.DEFENSIVE}'),
    (14, 'Physical Resistance Rating', '{StatCategory.DEFENSIVE}'),
    (15, 'Magical Resistance Rating',  '{StatCategory.DEFENSIVE}'),
    (16, 'Fortification',              '{StatCategory.DEFENSIVE}'),
    (17, 'Dodge',                      '{StatCategory.DEFENSIVE}'),
    (18, 'Fortitude Save',             '{StatCategory.DEFENSIVE}'),
    (19, 'Reflex Save',               '{StatCategory.DEFENSIVE}'),
    (20, 'Will Save',                  '{StatCategory.DEFENSIVE}'),
    (21, 'Spell Resistance',           '{StatCategory.DEFENSIVE}'),
    (62, 'Saving Throws vs Traps',     '{StatCategory.DEFENSIVE}'),
    (70, 'Physical Sheltering',        '{StatCategory.DEFENSIVE}'),
    (71, 'Magical Sheltering',         '{StatCategory.DEFENSIVE}'),
    (72, 'Concealment',                '{StatCategory.DEFENSIVE}'),
    (115, 'Natural Armor',             '{StatCategory.DEFENSIVE}'),
    (116, 'Protection',                '{StatCategory.DEFENSIVE}'),
    (117, 'Sheltering',                '{StatCategory.DEFENSIVE}'),
    (120, 'Resistance',                '{StatCategory.DEFENSIVE}'),
    (121, 'Enchantment Save',          '{StatCategory.DEFENSIVE}'),
    (122, 'Curse Save',                '{StatCategory.DEFENSIVE}'),
    (123, 'Poison Resistance',         '{StatCategory.DEFENSIVE}'),
    (128, 'Elemental Resistance',      '{StatCategory.DEFENSIVE}'),
    (76, 'Fire Resistance',            '{StatCategory.DEFENSIVE}'),
    (77, 'Cold Resistance',            '{StatCategory.DEFENSIVE}'),
    (78, 'Electric Resistance',        '{StatCategory.DEFENSIVE}'),
    (79, 'Acid Resistance',            '{StatCategory.DEFENSIVE}'),
    (80, 'Sonic Resistance',           '{StatCategory.DEFENSIVE}'),
    (81, 'Light Resistance',           '{StatCategory.DEFENSIVE}'),
    (82, 'Force Resistance',           '{StatCategory.DEFENSIVE}'),
    (83, 'Negative Resistance',        '{StatCategory.DEFENSIVE}'),
    (84, 'Fire Absorption',            '{StatCategory.DEFENSIVE}'),
    (85, 'Cold Absorption',            '{StatCategory.DEFENSIVE}'),
    (86, 'Electric Absorption',        '{StatCategory.DEFENSIVE}'),
    (87, 'Acid Absorption',            '{StatCategory.DEFENSIVE}'),
    (88, 'Sonic Absorption',           '{StatCategory.DEFENSIVE}'),
    (89, 'Light Absorption',           '{StatCategory.DEFENSIVE}'),
    (90, 'Force Absorption',           '{StatCategory.DEFENSIVE}'),
    (91, 'Negative Absorption',        '{StatCategory.DEFENSIVE}');

-- Magical stats (spell power, spell focus, spell penetration)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (22, 'Spell Points',              '{StatCategory.MAGICAL}'),
    (23, 'Spell Penetration',         '{StatCategory.MAGICAL}'),
    (24, 'Universal Spell Power',     '{StatCategory.MAGICAL}'),
    (25, 'Fire Spell Power',          '{StatCategory.MAGICAL}'),
    (26, 'Cold Spell Power',          '{StatCategory.MAGICAL}'),
    (27, 'Electric Spell Power',      '{StatCategory.MAGICAL}'),
    (28, 'Acid Spell Power',          '{StatCategory.MAGICAL}'),
    (29, 'Sonic Spell Power',         '{StatCategory.MAGICAL}'),
    (30, 'Light Spell Power',         '{StatCategory.MAGICAL}'),
    (31, 'Force Spell Power',         '{StatCategory.MAGICAL}'),
    (32, 'Negative Spell Power',      '{StatCategory.MAGICAL}'),
    (33, 'Positive Spell Power',      '{StatCategory.MAGICAL}'),
    (34, 'Repair Spell Power',        '{StatCategory.MAGICAL}'),
    (35, 'Alignment Spell Power',     '{StatCategory.MAGICAL}'),
    (92, 'Abjuration Spell Focus',    '{StatCategory.MAGICAL}'),
    (93, 'Conjuration Spell Focus',   '{StatCategory.MAGICAL}'),
    (94, 'Enchantment Spell Focus',   '{StatCategory.MAGICAL}'),
    (95, 'Evocation Spell Focus',     '{StatCategory.MAGICAL}'),
    (96, 'Illusion Spell Focus',      '{StatCategory.MAGICAL}'),
    (97, 'Necromancy Spell Focus',    '{StatCategory.MAGICAL}'),
    (98, 'Transmutation Spell Focus', '{StatCategory.MAGICAL}'),
    (99, 'Wizardry',                  '{StatCategory.MAGICAL}'),
    (100, 'Spell Focus Mastery',      '{StatCategory.MAGICAL}'),
    (126, 'Rune Arm Spell Focus',    '{StatCategory.MAGICAL}'),
    (101, 'Fire Spell Lore',          '{StatCategory.MAGICAL}'),
    (102, 'Cold Spell Lore',          '{StatCategory.MAGICAL}'),
    (103, 'Electric Spell Lore',      '{StatCategory.MAGICAL}'),
    (104, 'Acid Spell Lore',          '{StatCategory.MAGICAL}'),
    (105, 'Sonic Spell Lore',         '{StatCategory.MAGICAL}'),
    (106, 'Light Spell Lore',         '{StatCategory.MAGICAL}'),
    (107, 'Force Spell Lore',         '{StatCategory.MAGICAL}'),
    (108, 'Negative Spell Lore',      '{StatCategory.MAGICAL}'),
    (109, 'Positive Spell Lore',      '{StatCategory.MAGICAL}'),
    (110, 'Repair Spell Lore',        '{StatCategory.MAGICAL}'),
    (111, 'Universal Spell Lore',     '{StatCategory.MAGICAL}'),
    (112, 'Spell Lore',              '{StatCategory.MAGICAL}'),
    (113, 'Sacred Ground Lore',       '{StatCategory.MAGICAL}'),
    (114, 'Dark Restoration Lore',    '{StatCategory.MAGICAL}');

-- Skills
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (41, 'Balance',               '{StatCategory.SKILL}'),
    (42, 'Bluff',                 '{StatCategory.SKILL}'),
    (43, 'Concentration',         '{StatCategory.SKILL}'),
    (44, 'Diplomacy',             '{StatCategory.SKILL}'),
    (45, 'Disable Device',        '{StatCategory.SKILL}'),
    (46, 'Haggle',                '{StatCategory.SKILL}'),
    (47, 'Heal',                  '{StatCategory.SKILL}'),
    (48, 'Hide',                  '{StatCategory.SKILL}'),
    (49, 'Intimidate',            '{StatCategory.SKILL}'),
    (50, 'Jump',                  '{StatCategory.SKILL}'),
    (51, 'Listen',                '{StatCategory.SKILL}'),
    (52, 'Move Silently',         '{StatCategory.SKILL}'),
    (53, 'Open Lock',             '{StatCategory.SKILL}'),
    (54, 'Perform',               '{StatCategory.SKILL}'),
    (55, 'Repair',                '{StatCategory.SKILL}'),
    (56, 'Search',                '{StatCategory.SKILL}'),
    (57, 'Spellcraft',            '{StatCategory.SKILL}'),
    (58, 'Spot',                  '{StatCategory.SKILL}'),
    (59, 'Swim',                  '{StatCategory.SKILL}'),
    (60, 'Tumble',                '{StatCategory.SKILL}'),
    (61, 'Use Magic Device',      '{StatCategory.SKILL}');

-- Other stats (healing/repair amplification, misc)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (73, 'Healing Amplification', '{StatCategory.OTHER}'),
    (74, 'Repair Amplification',  '{StatCategory.OTHER}'),
    (75, 'Well Rounded',          '{StatCategory.OTHER}'),
    (127, 'Linguistics',          '{StatCategory.SKILL}'),
    (129, 'Positive Healing Amplification', '{StatCategory.OTHER}'),
    (130, 'Negative Healing Amplification', '{StatCategory.OTHER}'),
    (131, 'Maximum Spell Points',           '{StatCategory.MAGICAL}'),
    (132, 'Critical Damage Multiplier',     '{StatCategory.MARTIAL}'),
    (133, 'Critical Threat Range',          '{StatCategory.MARTIAL}'),
    (134, 'Melee and Ranged Power',         '{StatCategory.MARTIAL}'),
    (135, 'Physical and Magical Resistance Rating', '{StatCategory.DEFENSIVE}'),
    (136, 'Positive and Negative Spell Power',      '{StatCategory.MAGICAL}'),
    (137, 'Positive and Negative Healing Amplification', '{StatCategory.OTHER}'),
    (138, 'Doublestrike and Doubleshot',    '{StatCategory.MARTIAL}'),
    (140, 'Poison Spell Power',             '{StatCategory.MAGICAL}'),
    (142, 'Temporary Hit Points',           '{StatCategory.DEFENSIVE}'),
    (143, 'Bard Songs',                     '{StatCategory.OTHER}'),
    (144, 'Movement Speed',                 '{StatCategory.OTHER}'),
    (145, 'Maximum Hit Points',             '{StatCategory.DEFENSIVE}'),
    -- Absorption stats (from {{Absorption}} wiki template)
    (146, 'Fire Absorption',               '{StatCategory.DEFENSIVE}'),
    (147, 'Cold Absorption',               '{StatCategory.DEFENSIVE}'),
    (148, 'Electric Absorption',           '{StatCategory.DEFENSIVE}'),
    (149, 'Acid Absorption',               '{StatCategory.DEFENSIVE}'),
    (150, 'Sonic Absorption',              '{StatCategory.DEFENSIVE}'),
    (151, 'Light Absorption',              '{StatCategory.DEFENSIVE}'),
    (152, 'Negative Energy Absorption',    '{StatCategory.DEFENSIVE}'),
    (153, 'Law Absorption',                '{StatCategory.DEFENSIVE}'),
    (154, 'Chaos Absorption',              '{StatCategory.DEFENSIVE}'),
    (155, 'Good Absorption',               '{StatCategory.DEFENSIVE}'),
    (156, 'Evil Absorption',               '{StatCategory.DEFENSIVE}'),
    (157, 'Elemental Absorption',          '{StatCategory.DEFENSIVE}'),
    (158, 'Alignment Absorption',          '{StatCategory.DEFENSIVE}'),
    (159, 'Spell Absorption',              '{StatCategory.DEFENSIVE}'),
    (160, 'Curse Absorption',              '{StatCategory.DEFENSIVE}'),
    -- Save (from {{Save}} template)
    (161, 'Saving Throws',                 '{StatCategory.DEFENSIVE}'),
    -- Spell Focus (from {{Spell Focus}} template)
    (162, 'Universal Spell Focus',         '{StatCategory.MAGICAL}'),
    (163, 'Breath Weapon Spell Focus',     '{StatCategory.MAGICAL}'),
    -- Tactics (from {{Tactics}} template)
    (164, 'Shatter',                       '{StatCategory.MARTIAL}'),
    (165, 'Prudent',                        '{StatCategory.MARTIAL}'),
    (166, 'Astute',                         '{StatCategory.MARTIAL}'),
    -- Elemental resistance (from {{Elemental Resistance}} template)
    (167, 'Negative Energy Resistance',    '{StatCategory.DEFENSIVE}'),
    (168, 'Elemental Resistance',          '{StatCategory.DEFENSIVE}'),
    -- Save subtypes (from {{Save}} template)
    (169, 'Enchantment Save',              '{StatCategory.DEFENSIVE}'),
    (170, 'Illusion Save',                 '{StatCategory.DEFENSIVE}'),
    (171, 'Fear Save',                     '{StatCategory.DEFENSIVE}'),
    (172, 'Poison Save',                   '{StatCategory.DEFENSIVE}'),
    (173, 'Disease Save',                  '{StatCategory.DEFENSIVE}'),
    (174, 'Curse Save',                    '{StatCategory.DEFENSIVE}'),
    (175, 'Sleep Save',                    '{StatCategory.DEFENSIVE}'),
    (176, 'Trap Save',                     '{StatCategory.DEFENSIVE}'),
    (177, 'Spell Save',                    '{StatCategory.DEFENSIVE}'),
    -- Potency (acts as all element spell powers but different stacking than Universal SP)
    (178, 'Potency',                       '{StatCategory.MAGICAL}'),
    (179, 'Helpless Damage',               '{StatCategory.MARTIAL}'),
    (180, 'Imbue Dice',                    '{StatCategory.MARTIAL}'),
    (181, 'Fortification Bypass',          '{StatCategory.MARTIAL}'),
    (182, 'Attack Speed',                  '{StatCategory.MARTIAL}'),
    (183, 'Positive Spell Lore',           '{StatCategory.MAGICAL}'),
    (184, 'Negative Spell Lore',           '{StatCategory.MAGICAL}'),
    (185, 'Force Spell Lore',              '{StatCategory.MAGICAL}'),
    (186, 'Repair Spell Lore',             '{StatCategory.MAGICAL}'),
    -- Set bonus stats
    (187, 'Magical Resistance Rating Cap', '{StatCategory.DEFENSIVE}'),
    (188, 'Threat Generation',             '{StatCategory.MARTIAL}'),
    (189, 'Melee Threat Generation',       '{StatCategory.MARTIAL}'),
    (190, 'Threat Reduction',              '{StatCategory.MARTIAL}'),
    (191, 'Missile Deflection',            '{StatCategory.DEFENSIVE}'),
    (192, 'Offhand Strike Chance',         '{StatCategory.MARTIAL}'),
    (193, 'Strikethrough',                 '{StatCategory.MARTIAL}'),
    (194, 'Critical Multiplier',           '{StatCategory.MARTIAL}'),
    (195, 'Shield Armor Class',            '{StatCategory.DEFENSIVE}'),
    (196, 'Rune Arm DC',                   '{StatCategory.MAGICAL}'),
    (197, 'Assassinate DC',                '{StatCategory.MARTIAL}'),
    (198, 'Tactics',                        '{StatCategory.MARTIAL}'),
    (199, 'Dodge Cap',                     '{StatCategory.DEFENSIVE}'),
    (200, 'Critical Confirmation',         '{StatCategory.MARTIAL}'),
    (201, 'Spell Critical Damage',         '{StatCategory.MAGICAL}'),
    (202, 'Maximum Spell Points',          '{StatCategory.MAGICAL}'),
    (203, 'Armor Class Percentage',        '{StatCategory.DEFENSIVE}'),
    (204, 'Sneak Attack Damage',           '{StatCategory.MARTIAL}'),
    (205, 'Critical Damage',               '{StatCategory.MARTIAL}'),
    (206, 'Spell Point Cost Reduction',    '{StatCategory.MAGICAL}'),
    (207, 'Sneak Attack Hit',              '{StatCategory.MARTIAL}'),
    (208, 'Damage Bonus',                  '{StatCategory.MARTIAL}'),
    -- Missing stats found during enum migration
    (209, 'Spell DCs',                     '{StatCategory.MAGICAL}'),
    (210, 'Command',                       '{StatCategory.SKILL}'),
    (211, 'Persuasion',                    '{StatCategory.SKILL}'),
    (212, 'Universal Spell Critical Damage', '{StatCategory.MAGICAL}'),
    (213, 'Sneak Attack',                  '{StatCategory.MARTIAL}'),
    (214, 'Sneak Attack Bonus',            '{StatCategory.MARTIAL}'),
    (215, 'Poison Spell Power',            '{StatCategory.MAGICAL}'),
    (216, 'Poison Spell Lore',             '{StatCategory.MAGICAL}'),
    (217, 'Poison Absorption',             '{StatCategory.DEFENSIVE}'),
    (218, 'Chaos Spell Power',             '{StatCategory.MAGICAL}'),
    (219, 'Chaos Spell Lore',              '{StatCategory.MAGICAL}'),
    (220, 'Good Spell Power',              '{StatCategory.MAGICAL}'),
    (221, 'Good Spell Lore',               '{StatCategory.MAGICAL}'),
    (222, 'Evil Spell Power',              '{StatCategory.MAGICAL}'),
    (223, 'Evil Spell Lore',               '{StatCategory.MAGICAL}'),
    (224, 'Law Spell Power',               '{StatCategory.MAGICAL}'),
    (225, 'Law Spell Lore',                '{StatCategory.MAGICAL}'),
    (226, 'Melee and Ranged Threat Reduction', '{StatCategory.MARTIAL}'),
    (227, 'Ranged Threat Reduction',       '{StatCategory.MARTIAL}'),
    (228, 'Saves vs Evil',                 '{StatCategory.DEFENSIVE}'),
    (229, 'Attack and Damage vs Evil',     '{StatCategory.MARTIAL}'),
    (230, 'Damage vs Evil',                '{StatCategory.MARTIAL}');

-- Skills (key_ability_id references stats above)
INSERT OR IGNORE INTO skills (id, name, key_ability_id) VALUES
    (1,  'Balance',          2),   -- DEX
    (2,  'Bluff',            6),   -- CHA
    (3,  'Concentration',    3),   -- CON
    (4,  'Diplomacy',        6),   -- CHA
    (5,  'Disable Device',   4),   -- INT
    (6,  'Haggle',           6),   -- CHA
    (7,  'Heal',             5),   -- WIS
    (8,  'Hide',             2),   -- DEX
    (9,  'Intimidate',       6),   -- CHA
    (10, 'Jump',             1),   -- STR
    (11, 'Listen',           5),   -- WIS
    (12, 'Move Silently',    2),   -- DEX
    (13, 'Open Lock',        2),   -- DEX
    (14, 'Perform',          6),   -- CHA
    (15, 'Repair',           4),   -- INT
    (16, 'Search',           4),   -- INT
    (17, 'Spellcraft',       4),   -- INT
    (18, 'Spot',             5),   -- WIS
    (19, 'Swim',             1),   -- STR
    (20, 'Tumble',           2),   -- DEX
    (21, 'Use Magic Device', 6);   -- CHA

-- Classes
INSERT OR IGNORE INTO classes (id, name, hit_die, bab_progression, skill_points_per_level, fort_save_progression, ref_save_progression, will_save_progression, caster_type, spell_tradition, alignment, icon) VALUES
    (1,  'Barbarian',      12, '{BabProgression.FULL}',          4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY_NON_LAWFUL}', 'Barbarian.png'),
    (2,  'Bard',            8, '{BabProgression.THREE_QUARTER}',  6, '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Bard.png'),
    (3,  'Cleric',          8, '{BabProgression.THREE_QUARTER}',  2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.DIVINE}', '{Alignment.ANY}',            'Cleric.png'),
    (4,  'Fighter',        10, '{BabProgression.FULL}',           2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY}',            'Fighter.png'),
    (5,  'Paladin',        10, '{BabProgression.FULL}',           2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{CasterType.HALF}',  '{SpellTradition.DIVINE}', '{Alignment.LAWFUL_GOOD}',    'Paladin.png'),
    (6,  'Ranger',         10, '{BabProgression.FULL}',           6, '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{CasterType.HALF}',  '{SpellTradition.DIVINE}', '{Alignment.ANY}',            'Ranger.png'),
    (7,  'Rogue',           8, '{BabProgression.THREE_QUARTER}',  8, '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY}',            'Rogue.png'),
    (8,  'Sorcerer',        6, '{BabProgression.HALF}',           2, '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Sorcerer.png'),
    (9,  'Wizard',          6, '{BabProgression.HALF}',           2, '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Wizard.png'),
    (10, 'Monk',            8, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{SaveProgression.GOOD}', '{CasterType.NONE}',  NULL,     '{Alignment.ANY_LAWFUL}',     'Monk.png'),
    (11, 'Favored Soul',    8, '{BabProgression.THREE_QUARTER}',  2, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.DIVINE}', '{Alignment.ANY}',            'Favored Soul.png'),
    (12, 'Artificer',       8, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Artificer.png'),
    (13, 'Druid',           8, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.DIVINE}', '{Alignment.ANY_NEUTRAL}',    'Druid.png'),
    (14, 'Warlock',         6, '{BabProgression.THREE_QUARTER}',  2, '{SaveProgression.POOR}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Warlock.png'),
    (15, 'Alchemist',       6, '{BabProgression.THREE_QUARTER}',  4, '{SaveProgression.GOOD}', '{SaveProgression.POOR}', '{SaveProgression.GOOD}', '{CasterType.FULL}',  '{SpellTradition.ARCANE}', '{Alignment.ANY}',            'Alchemist.png');

-- Archetypes (modify a base class; inherit most stats from parent)
INSERT OR IGNORE INTO classes (id, name, parent_class_id, is_archetype) VALUES
    (16, 'Dragon Lord',        4,  1),   -- Fighter archetype
    (17, 'Dragon Disciple',    8,  1),   -- Sorcerer archetype
    (18, 'Arcane Trickster',   7,  1),   -- Rogue archetype
    (19, 'Wild Mage',          9,  1),   -- Wizard archetype
    (20, 'Stormsinger',        2,  1),   -- Bard archetype
    (21, 'Dark Apostate',      3,  1),   -- Cleric archetype
    (22, 'Blightcaster',      13,  1),   -- Druid archetype
    (23, 'Sacred Fist',        5,  1),   -- Paladin archetype
    (24, 'Dark Hunter',        6,  1),   -- Ranger archetype
    (25, 'Acolyte of the Skin',14, 1);   -- Warlock archetype

-- Races (standard + iconic)
INSERT OR IGNORE INTO races (id, name, race_type, icon) VALUES
    -- Free races (icons resolved at build time via MediaWiki allimages API)
    (1,  'Human',         '{RaceType.FREE}',    'Human_race_icon.png'),
    (2,  'Elf',           '{RaceType.FREE}',    'Elf_race_icon.png'),
    (3,  'Dwarf',         '{RaceType.FREE}',    'Dwarf_race_icon.png'),
    (4,  'Halfling',      '{RaceType.FREE}',    'Halfling_race_icon.png'),
    (5,  'Warforged',     '{RaceType.FREE}',    'Warforged_race_icon.png'),
    (6,  'Drow Elf',      '{RaceType.FREE}',    'Drow_race_icon.png'),
    (7,  'Half-Elf',      '{RaceType.FREE}',    'Half-Elf_race_icon.png'),
    (8,  'Half-Orc',      '{RaceType.FREE}',    'Half-Orc_race_icon.png'),
    (9,  'Gnome',         '{RaceType.FREE}',    'Gnome_race_icon.png'),
    (10, 'Dragonborn',    '{RaceType.FREE}',    'Dragonborn_race_icon.png'),
    (11, 'Tiefling',      '{RaceType.FREE}',    'Tiefling_race_icon.png'),
    (12, 'Wood Elf',      '{RaceType.FREE}',    'Wood_Elf_race_icon.jpg'),
    -- Premium races
    (13, 'Aasimar',       '{RaceType.PREMIUM}', 'Aasimar_race_icon.png'),
    (14, 'Tabaxi',        '{RaceType.PREMIUM}', 'Tabaxi_race_icon.png'),
    (15, 'Shifter',       '{RaceType.PREMIUM}', 'Shifter_race_icon.png'),
    (16, 'Eladrin',       '{RaceType.PREMIUM}', 'Eladrin_race_icon.png'),
    (17, 'Dhampir',       '{RaceType.PREMIUM}', 'Dhampir_race_icon.png'),
    -- Iconic races (start at class level, have a parent base race)
    (18, 'Bladeforged',          '{RaceType.ICONIC}', 'Bladeforged_race_icon.png'),
    (19, 'Purple Dragon Knight', '{RaceType.ICONIC}', 'Purple_Dragon_Knight_race_icon.png'),
    (20, 'Morninglord',          '{RaceType.ICONIC}', 'Morninglord_race_icon.png'),
    (21, 'Shadar-kai',           '{RaceType.ICONIC}', 'Shadar-Kai_race_icon.png'),
    (22, 'Deep Gnome',           '{RaceType.ICONIC}', 'Deep_Gnome_race_icon.png'),
    (23, 'Aasimar Scourge',      '{RaceType.ICONIC}', 'Aasimar_Scourge_race_icon.png'),
    (24, 'Razorclaw Shifter',    '{RaceType.ICONIC}', 'Razorclaw_Shifter_race_icon.png'),
    (25, 'Tiefling Scoundrel',   '{RaceType.ICONIC}', 'Tiefling_Scoundrel_race_icon.png'),
    (26, 'Tabaxi Trailblazer',   '{RaceType.ICONIC}', 'Tabaxi_Trailblazer_race_icon.png'),
    (27, 'Eladrin Chaosmancer',  '{RaceType.ICONIC}', 'Eladrin_Chaosmancer_race_icon.png'),
    (28, 'Dhampir Dark Bargainer','{RaceType.ICONIC}', NULL);

-- Bonus types (stacks_with_self=1 means same-type bonuses from different sources stack)
INSERT OR IGNORE INTO bonus_types (id, name, stacks_with_self) VALUES
    (1,  'Enhancement',   0),
    (2,  'Competence',    0),
    (3,  'Insight',       0),
    (4,  'Sacred',        0),
    (5,  'Profane',       0),
    (6,  'Luck',          0),
    (7,  'Morale',        0),
    (8,  'Alchemical',    0),
    (9,  'Dodge',         1),  -- dodge bonuses stack
    (10, 'Armor',         0),
    (11, 'Natural Armor', 0),
    (12, 'Deflection',    0),
    (13, 'Shield',        0),
    (14, 'Size',          0),
    (15, 'Racial',        0),
    (16, 'Resistance',    0),
    (17, 'Festive',       0),
    (18, 'Exceptional',   0),
    (19, 'Quality',       0),
    (20, 'Artifact',      0),
    (21, 'Inherent',      0),
    (22, 'Stacking',      1),  -- explicitly stacking bonuses
    (23, 'Rage',          0),
    (24, 'Primal',        0),
    (25, 'Determination', 0),
    (26, 'Implement',     0),
    (27, 'Music',         0),
    (28, 'Equipment',     0);

-- Damage types
INSERT OR IGNORE INTO damage_types (id, name, category) VALUES
    (1,  'Slashing',    '{DamageCategory.PHYSICAL}'),
    (2,  'Piercing',    '{DamageCategory.PHYSICAL}'),
    (3,  'Bludgeoning', '{DamageCategory.PHYSICAL}'),
    (4,  'Fire',        '{DamageCategory.ELEMENTAL}'),
    (5,  'Cold',        '{DamageCategory.ELEMENTAL}'),
    (6,  'Electric',    '{DamageCategory.ELEMENTAL}'),
    (7,  'Acid',        '{DamageCategory.ELEMENTAL}'),
    (8,  'Sonic',       '{DamageCategory.ELEMENTAL}'),
    (9,  'Good',        '{DamageCategory.ALIGNMENT}'),
    (10, 'Evil',        '{DamageCategory.ALIGNMENT}'),
    (11, 'Lawful',      '{DamageCategory.ALIGNMENT}'),
    (12, 'Chaotic',     '{DamageCategory.ALIGNMENT}'),
    (13, 'Negative',    '{DamageCategory.ENERGY}'),
    (14, 'Positive',    '{DamageCategory.ENERGY}'),
    (15, 'Force',       '{DamageCategory.ENERGY}'),
    (16, 'Light',       '{DamageCategory.ENERGY}'),
    (17, 'Poison',      '{DamageCategory.ENERGY}'),
    (18, 'Untyped',     '{DamageCategory.UNTYPED}');

-- Weapon proficiencies
INSERT OR IGNORE INTO weapon_proficiencies (id, name, category) VALUES
    (1, 'Simple',  '{ProficiencyCategory.SIMPLE}'),
    (2, 'Martial', '{ProficiencyCategory.MARTIAL}'),
    (3, 'Exotic',  '{ProficiencyCategory.EXOTIC}');

-- Equipment slots (binary codes 2–17 from EQUIPMENT_SLOTS enum; seed PKs are independent)
INSERT OR IGNORE INTO equipment_slots (id, name, sort_order, category) VALUES
    (1,  '{EquipmentSlot.MAIN_HAND}',  1,  '{SlotCategory.WEAPON}'),
    (2,  '{EquipmentSlot.OFF_HAND}',   2,  '{SlotCategory.WEAPON}'),
    (3,  '{EquipmentSlot.RANGED}',     3,  '{SlotCategory.WEAPON}'),
    (4,  '{EquipmentSlot.QUIVER}',     4,  '{SlotCategory.WEAPON}'),
    (5,  '{EquipmentSlot.HEAD}',       5,  '{SlotCategory.ARMOR}'),
    (6,  '{EquipmentSlot.NECK}',       6,  '{SlotCategory.ACCESSORY}'),
    (7,  '{EquipmentSlot.TRINKET}',    7,  '{SlotCategory.ACCESSORY}'),
    (8,  '{EquipmentSlot.BACK}',       8,  '{SlotCategory.ARMOR}'),
    (9,  '{EquipmentSlot.WRISTS}',     9,  '{SlotCategory.ARMOR}'),
    (10, '{EquipmentSlot.ARMS}',       10, '{SlotCategory.ARMOR}'),
    (11, '{EquipmentSlot.BODY}',       11, '{SlotCategory.ARMOR}'),
    (12, '{EquipmentSlot.WAIST}',      12, '{SlotCategory.ARMOR}'),
    (13, '{EquipmentSlot.FEET}',       13, '{SlotCategory.ARMOR}'),
    (14, '{EquipmentSlot.GOGGLES}',    14, '{SlotCategory.ACCESSORY}'),
    (15, '{EquipmentSlot.RING}',       15, '{SlotCategory.ACCESSORY}'),
    (16, '{EquipmentSlot.RUNEARM}',    16, '{SlotCategory.WEAPON}');

-- Spell schools
INSERT OR IGNORE INTO spell_schools (id, name) VALUES
    (1, '{SpellSchool.ABJURATION}'),
    (2, '{SpellSchool.CONJURATION}'),
    (3, '{SpellSchool.DIVINATION}'),
    (4, '{SpellSchool.ENCHANTMENT}'),
    (5, '{SpellSchool.EVOCATION}'),
    (6, '{SpellSchool.ILLUSION}'),
    (7, '{SpellSchool.NECROMANCY}'),
    (8, '{SpellSchool.TRANSMUTATION}'),
    (9, '{SpellSchool.UNIVERSAL}');

-- Class skills (sd: from DDO wiki class pages)
-- class_id: 1=Barbarian 2=Bard 3=Cleric 4=Fighter 5=Paladin 6=Ranger 7=Rogue
--           8=Sorcerer 9=Wizard 10=Monk 11=FvS 12=Artificer 13=Druid 14=Warlock 15=Alchemist
-- skill_id: 1=Balance 2=Bluff 3=Concentration 4=Diplomacy 5=DisableDevice 6=Haggle
--           7=Heal 8=Hide 9=Intimidate 10=Jump 11=Listen 12=MoveSilently 13=OpenLock
--           14=Perform 15=Repair 16=Search 17=Spellcraft 18=Spot 19=Swim 20=Tumble 21=UMD
INSERT OR IGNORE INTO class_skills (class_id, skill_id) VALUES
    -- Barbarian: Balance, Intimidate, Jump, Listen, Swim
    (1,1),(1,9),(1,10),(1,11),(1,19),
    -- Bard: Balance, Bluff, Concentration, Diplomacy, Haggle, Hide, Jump, Listen,
    --       Move Silently, Open Lock, Perform, Repair, Spellcraft, Swim, Tumble, UMD
    (2,1),(2,2),(2,3),(2,4),(2,6),(2,8),(2,10),(2,11),(2,12),(2,13),(2,14),(2,15),(2,17),(2,19),(2,20),(2,21),
    -- Cleric: Concentration, Diplomacy, Heal, Spellcraft
    (3,3),(3,4),(3,7),(3,17),
    -- Fighter: Balance, Intimidate, Jump, Repair, Swim
    (4,1),(4,9),(4,10),(4,15),(4,19),
    -- Paladin: Balance, Concentration, Diplomacy, Heal, Intimidate, Jump, Swim
    (5,1),(5,3),(5,4),(5,7),(5,9),(5,10),(5,19),
    -- Ranger: Balance, Concentration, Heal, Hide, Jump, Listen, Move Silently, Search, Spot, Swim
    (6,1),(6,3),(6,7),(6,8),(6,10),(6,11),(6,12),(6,16),(6,18),(6,19),
    -- Rogue: Balance, Bluff, Diplomacy, Disable Device, Haggle, Hide, Intimidate, Jump, Listen,
    --        Move Silently, Open Lock, Perform, Repair, Search, Spot, Swim, Tumble, UMD
    (7,1),(7,2),(7,4),(7,5),(7,6),(7,8),(7,9),(7,10),(7,11),(7,12),(7,13),(7,14),(7,15),(7,16),(7,18),(7,19),(7,20),(7,21),
    -- Sorcerer: Bluff, Concentration, Spellcraft
    (8,2),(8,3),(8,17),
    -- Wizard: Concentration, Repair, Spellcraft
    (9,3),(9,15),(9,17),
    -- Monk: Balance, Concentration, Diplomacy, Hide, Jump, Listen, Move Silently, Spot, Swim, Tumble
    (10,1),(10,3),(10,4),(10,8),(10,10),(10,11),(10,12),(10,18),(10,19),(10,20),
    -- Favored Soul: Concentration, Diplomacy, Heal, Jump, Spellcraft
    (11,3),(11,4),(11,7),(11,10),(11,17),
    -- Artificer: Balance, Concentration, Disable Device, Haggle, Open Lock, Repair, Search, Spellcraft, UMD
    (12,1),(12,3),(12,5),(12,6),(12,13),(12,15),(12,16),(12,17),(12,21),
    -- Druid: Balance, Concentration, Diplomacy, Heal, Hide, Listen, Spellcraft, Spot, Swim
    (13,1),(13,3),(13,4),(13,7),(13,8),(13,11),(13,17),(13,18),(13,19),
    -- Warlock: Bluff, Concentration, Intimidate, Spellcraft, UMD
    (14,2),(14,3),(14,9),(14,17),(14,21),
    -- Alchemist: Balance, Concentration, Disable Device, Heal, Repair, Search, Spellcraft, UMD
    (15,1),(15,3),(15,5),(15,7),(15,15),(15,16),(15,17),(15,21);

-- Race ability bonuses (sd: from DDO wiki race pages)
-- Standard races only (iconics inherit from base race + class)
-- stat_id: 1=STR 2=DEX 3=CON 4=INT 5=WIS 6=CHA
-- Innate racial ability modifiers (from ddowiki.com/page/Races stat range columns)
-- stat IDs: 1=STR, 2=DEX, 3=CON, 4=INT, 5=WIS, 6=CHA
INSERT OR IGNORE INTO race_ability_modifiers (race_id, stat_id, modifier, source) VALUES
    -- 1=Human: no innate mods
    -- 2=Elf: +2 DEX, -2 CON
    (2, 2, 2, '{AbilityModSource.INNATE}'), (2, 3, -2, '{AbilityModSource.INNATE}'),
    -- 3=Dwarf: +2 CON, -2 CHA
    (3, 3, 2, '{AbilityModSource.INNATE}'), (3, 6, -2, '{AbilityModSource.INNATE}'),
    -- 4=Halfling: +2 DEX, -2 STR
    (4, 2, 2, '{AbilityModSource.INNATE}'), (4, 1, -2, '{AbilityModSource.INNATE}'),
    -- 5=Warforged: +2 CON, -2 WIS, -2 CHA
    (5, 3, 2, '{AbilityModSource.INNATE}'), (5, 5, -2, '{AbilityModSource.INNATE}'), (5, 6, -2, '{AbilityModSource.INNATE}'),
    -- 6=Drow Elf: +2 DEX, +2 INT, +2 CHA, -2 CON
    (6, 2, 2, '{AbilityModSource.INNATE}'), (6, 4, 2, '{AbilityModSource.INNATE}'), (6, 6, 2, '{AbilityModSource.INNATE}'), (6, 3, -2, '{AbilityModSource.INNATE}'),
    -- 7=Half-Elf: no innate mods
    -- 8=Half-Orc: +2 STR, -2 INT, -2 CHA
    (8, 1, 2, '{AbilityModSource.INNATE}'), (8, 4, -2, '{AbilityModSource.INNATE}'), (8, 6, -2, '{AbilityModSource.INNATE}'),
    -- 9=Gnome: +2 INT, -2 STR
    (9, 4, 2, '{AbilityModSource.INNATE}'), (9, 1, -2, '{AbilityModSource.INNATE}'),
    -- 10=Dragonborn: +2 STR, +2 CHA, -2 DEX
    (10, 1, 2, '{AbilityModSource.INNATE}'), (10, 6, 2, '{AbilityModSource.INNATE}'), (10, 2, -2, '{AbilityModSource.INNATE}'),
    -- 11=Tiefling: +2 CHA
    (11, 6, 2, '{AbilityModSource.INNATE}'),
    -- 12=Wood Elf: +2 DEX, -2 INT
    (12, 2, 2, '{AbilityModSource.INNATE}'), (12, 4, -2, '{AbilityModSource.INNATE}'),
    -- 13=Aasimar: +2 WIS
    (13, 5, 2, '{AbilityModSource.INNATE}'),
    -- 14=Tabaxi: +2 DEX
    (14, 2, 2, '{AbilityModSource.INNATE}'),
    -- 15=Shifter: +2 DEX, -2 INT
    (15, 2, 2, '{AbilityModSource.INNATE}'), (15, 4, -2, '{AbilityModSource.INNATE}'),
    -- 16=Eladrin: +2 DEX
    (16, 2, 2, '{AbilityModSource.INNATE}'),
    -- 17=Dhampir: +2 STR
    (17, 1, 2, '{AbilityModSource.INNATE}'),
    -- 18=Bladeforged: +2 CON, -2 DEX, -2 WIS
    (18, 3, 2, '{AbilityModSource.INNATE}'), (18, 2, -2, '{AbilityModSource.INNATE}'), (18, 5, -2, '{AbilityModSource.INNATE}'),
    -- 19=Purple Dragon Knight: no innate mods
    -- 20=Morninglord: +2 INT, -2 CON
    (20, 4, 2, '{AbilityModSource.INNATE}'), (20, 3, -2, '{AbilityModSource.INNATE}'),
    -- 21=Shadar-kai: +2 DEX, -2 CHA
    (21, 2, 2, '{AbilityModSource.INNATE}'), (21, 6, -2, '{AbilityModSource.INNATE}'),
    -- 22=Deep Gnome: +2 INT, +2 WIS, -2 STR, -2 CHA
    (22, 4, 2, '{AbilityModSource.INNATE}'), (22, 5, 2, '{AbilityModSource.INNATE}'), (22, 1, -2, '{AbilityModSource.INNATE}'), (22, 6, -2, '{AbilityModSource.INNATE}'),
    -- 23=Aasimar Scourge: +2 WIS
    (23, 5, 2, '{AbilityModSource.INNATE}'),
    -- 24=Razorclaw Shifter: +2 STR, -2 INT
    (24, 1, 2, '{AbilityModSource.INNATE}'), (24, 4, -2, '{AbilityModSource.INNATE}'),
    -- 25=Tiefling Scoundrel: +2 CHA
    (25, 6, 2, '{AbilityModSource.INNATE}'),
    -- 26=Tabaxi Trailblazer: +2 DEX
    (26, 2, 2, '{AbilityModSource.INNATE}'),
    -- 27=Eladrin Chaosmancer: +2 CHA
    (27, 6, 2, '{AbilityModSource.INNATE}'),
    -- 28=Dhampir Dark Bargainer: +1 CHA, +1 INT
    (28, 6, 1, '{AbilityModSource.INNATE}'), (28, 4, 1, '{AbilityModSource.INNATE}');

-- Enhancement racial ability modifiers (from racial enhancement trees, ddowiki.com/page/Races)
-- Fixed bonuses from core abilities; choice-based from racial tree picks
-- is_choice=1 means player distributes choice_pool points among marked stats
INSERT OR IGNORE INTO race_ability_modifiers (race_id, stat_id, modifier, source, is_choice, choice_pool) VALUES
    -- 1=Human: choose +1 to any stat, +1 to a different stat (pool=1 each pick)
    (1, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (1, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    (1, 3, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (1, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    (1, 5, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (1, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    -- 2=Elf: +2 DEX
    (2, 2, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 3=Dwarf: +2 CON
    (3, 3, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 4=Halfling: +2 DEX
    (4, 2, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 5=Warforged: +2 CON
    (5, 3, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 6=Drow Elf: +2 total from DEX/INT/CHA
    (6, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (6, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (6, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 7=Half-Elf: as Elf or Human (choice)
    (7, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (7, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    (7, 3, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (7, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    (7, 5, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (7, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 8=Half-Orc: +2 STR
    (8, 1, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 9=Gnome: +2 INT
    (9, 4, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 10=Dragonborn: +2 total from STR/CHA
    (10, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (10, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 11=Tiefling: +2 CHA
    (11, 6, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 12=Wood Elf: (none parsed — wiki cell truncated)
    -- 13=Aasimar: +2 total from STR/WIS/CHA
    (13, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (13, 5, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (13, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 14=Tabaxi: +2 total from CHA/DEX
    (14, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (14, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 15=Shifter: +2 total from STR/DEX/CON/WIS
    (15, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (15, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    (15, 3, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (15, 5, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 16=Eladrin: +1 CHA (fixed) + +2 total from DEX/INT/CHA
    (16, 6, 1, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    (16, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (16, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 17=Dhampir: +2 total from STR/CON/CHA
    (17, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (17, 3, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (17, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 18=Bladeforged: +2 CON
    (18, 3, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 19=Purple Dragon Knight: choose +1 to any stat, +1 to different stat
    (19, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (19, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    (19, 3, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (19, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    (19, 5, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (19, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    -- 20=Morninglord: +2 INT
    (20, 4, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 21=Shadar-kai: +1 total from DEX/INT/CHA
    (21, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (21, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1), (21, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 1),
    -- 22=Deep Gnome: +2 total from WIS/INT
    (22, 5, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (22, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 23=Aasimar Scourge: +1 CON (fixed) + +2 total from STR/WIS/CHA
    (23, 3, 1, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    (23, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (23, 5, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (23, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 24=Razorclaw Shifter: +2 total from STR/DEX/CON
    (24, 1, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (24, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (24, 3, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 25=Tiefling Scoundrel: +2 CHA
    (25, 6, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 26=Tabaxi Trailblazer: +2 DEX
    (26, 2, 2, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    -- 27=Eladrin Chaosmancer: +1 CHA (fixed) + +2 total from DEX/INT/CHA
    (27, 6, 1, '{AbilityModSource.ENHANCEMENT}', 0, NULL),
    (27, 2, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (27, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2),
    -- 28=Dhampir Dark Bargainer: +2 total from CHA/CON/INT
    (28, 6, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (28, 3, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2), (28, 4, 0, '{AbilityModSource.ENHANCEMENT}', 1, 2);

-- Universal feat slot schedule (every character gets these, independent of class/race)
INSERT OR IGNORE INTO feat_slots (character_level, sort_order, slot_tier) VALUES
    -- Heroic standard feats
    (1,  0, 'heroic'), (3,  0, 'heroic'), (6,  0, 'heroic'), (9,  0, 'heroic'),
    (12, 0, 'heroic'), (15, 0, 'heroic'), (18, 0, 'heroic'),
    -- Epic standard feats
    (21, 0, 'epic'), (24, 0, 'epic'), (27, 0, 'epic'),
    -- Epic Destiny feats (separate pool)
    (22, 0, 'destiny'), (25, 0, 'destiny'), (28, 0, 'destiny'),
    -- Level 30: one epic feat + one legendary feat
    (30, 0, 'epic'), (30, 1, 'legendary');

-- Race bonus feat slots (races that grant extra feat choices)
INSERT OR IGNORE INTO race_bonus_feat_slots (race_id, character_level, slot_tier) VALUES
    (1,  1, 'heroic'),   -- Human: +1 standard feat at level 1
    (19, 1, 'heroic');   -- Purple Dragon Knight: same as Human
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_schema(conn: sqlite3.Connection) -> None:
    """Apply SCHEMA_V1 DDL and seed reference data to *conn*.

    Safe to call on an existing database — uses ``CREATE TABLE IF NOT EXISTS``
    and ``INSERT OR IGNORE`` throughout, so re-running is idempotent.
    """
    conn.executescript(SCHEMA_V1)
    conn.executescript(_SEED_SQL)
    conn.commit()