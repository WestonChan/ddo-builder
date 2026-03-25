"""DDO game database schema — DDL and seed data for SQLite."""

from __future__ import annotations

import sqlite3

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

SCHEMA_V1 = """
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
    category TEXT NOT NULL  CHECK (category IN ('ability', 'defensive', 'martial', 'magical', 'skill', 'other')) -- sd
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
    category TEXT NOT NULL  CHECK (category IN ('physical', 'elemental', 'alignment', 'energy', 'untyped')) -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_damage_types_name ON damage_types(name);

CREATE TABLE IF NOT EXISTS weapon_proficiencies (
    id       INTEGER PRIMARY KEY,                                -- sd
    name     TEXT NOT NULL,                                      -- sd
    category TEXT NOT NULL  CHECK (category IN ('simple', 'martial', 'exotic')) -- sd
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
    category   TEXT NOT NULL CHECK (category IN ('weapon', 'armor', 'accessory')) -- sd
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
    bab_progression        TEXT CHECK (bab_progression IN ('full', 'three_quarter', 'half')), -- sd
    skill_points_per_level INTEGER,                              -- sd
    fort_save_progression  TEXT CHECK (fort_save_progression IN ('good', 'poor')), -- sd
    ref_save_progression   TEXT CHECK (ref_save_progression  IN ('good', 'poor')), -- sd
    will_save_progression  TEXT CHECK (will_save_progression IN ('good', 'poor')), -- sd
    caster_type            TEXT CHECK (caster_type IN ('full', 'half', 'none')),   -- sd
    spell_tradition        TEXT CHECK (spell_tradition IN ('arcane', 'divine')),   -- sd
    alignment              TEXT,                                  -- sd: e.g., 'any', 'lawful good', 'any lawful'
    description            TEXT                                   -- sd
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_classes_name ON classes(name);

CREATE TABLE IF NOT EXISTS races (
    id           INTEGER PRIMARY KEY,                            -- sd
    name         TEXT NOT NULL,                                   -- sd
    race_type    TEXT CHECK (race_type IN ('free', 'premium', 'iconic')), -- sd/wt: from Races page
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
    source      TEXT NOT NULL CHECK (source IN ('innate', 'enhancement')), -- innate=at creation, enhancement=racial tree
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

CREATE TABLE IF NOT EXISTS class_bonus_feat_slots (           -- unpopulated (future: wt)
    class_id      INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level   INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 30),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    feat_category TEXT,
    PRIMARY KEY (class_id, class_level, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_class_bonus_feat_slots_level ON class_bonus_feat_slots(class_id, class_level);

CREATE TABLE IF NOT EXISTS class_spell_slots (               -- unpopulated (future: wt)
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 20),
    spell_level INTEGER NOT NULL CHECK (spell_level BETWEEN 1 AND 9),
    slots       INTEGER NOT NULL CHECK (slots >= 0),
    PRIMARY KEY (class_id, class_level, spell_level)
);

CREATE TABLE IF NOT EXISTS class_spells_known (               -- unpopulated (future: wt)
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
    rarity            TEXT CHECK (rarity IN ('Common', 'Uncommon', 'Rare', 'Epic')), -- bp: key 0x10000B5F enum
    slot_id           INTEGER REFERENCES equipment_slots(id),      -- c: joined from equipment_slot name
    equipment_slot    TEXT,                                         -- bp: key 0x10000A4B enum
    item_category     TEXT CHECK (item_category IN (                -- bp: key 0x10000A4C enum; wt: fallback
                          'Armor','Shield','Weapon','Jewelry','Clothing',
                          'Wondrous','Potion','Scroll','Wand',
                          'Component','Collectible','Consumable')),
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
    handedness     TEXT CHECK (handedness IN ('One-handed', 'Two-handed', 'Off-hand', 'Thrown')) -- wt: hand field
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
    proficiency_id       INTEGER REFERENCES weapon_proficiencies(id), -- c: joined from proficiency name
    wiki_url             TEXT                                    -- c: constructed from name
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feats_name ON feats(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feats_dat_id ON feats(dat_id) WHERE dat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_feats_proficiency ON feats(proficiency_id) WHERE proficiency_id IS NOT NULL;

-- Past-life subtype — only populated for past life feats
CREATE TABLE IF NOT EXISTS feat_past_life_stats (                -- wt: parsed from feat description/name
    feat_id        INTEGER PRIMARY KEY REFERENCES feats(id) ON DELETE CASCADE,
    past_life_type TEXT NOT NULL CHECK (past_life_type IN ('heroic', 'racial', 'iconic', 'epic', 'legendary')), -- wt
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

CREATE TABLE IF NOT EXISTS class_auto_feats (                   -- unpopulated (future: wt)
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 30),
    feat_id     INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (class_id, class_level, feat_id)
);
CREATE INDEX IF NOT EXISTS idx_class_auto_feats_feat ON class_auto_feats(feat_id);

CREATE TABLE IF NOT EXISTS race_auto_feats (                         -- sd: populated in insert_feats()
    race_id INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    feat_id INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (race_id, feat_id)
);
CREATE INDEX IF NOT EXISTS idx_race_auto_feats_feat ON race_auto_feats(feat_id);

-- Enhancement Trees --------------------------------------------------------
CREATE TABLE IF NOT EXISTS enhancement_trees (
    id        INTEGER PRIMARY KEY,                               -- c: autoincrement
    dat_id    TEXT,                                               -- ln: FID from fid_enhancement_lookup.json
    name      TEXT NOT NULL,                                      -- wt: wiki tree page title
    tree_type TEXT NOT NULL CHECK (tree_type IN ('class', 'racial', 'universal', 'reaper', 'destiny')), -- wt: from index category
    ap_pool   TEXT NOT NULL CHECK (ap_pool IN ('heroic', 'racial', 'reaper', 'legendary')), -- c: derived from tree_type
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
    tier                TEXT    NOT NULL CHECK (tier IN ('1', '2', '3', '4', '5')),
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
    tier        TEXT NOT NULL CHECK (tier IN ('core', '1', '2', '3', '4', '5', 'unknown')), -- wt: from section headers
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
    link_type      TEXT NOT NULL CHECK (link_type IN ('requires', 'grants', 'excludes')),
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
    save_type        TEXT CHECK (save_type IS NULL OR save_type IN ('Fortitude', 'Reflex', 'Will')), -- c: parsed from saving_throw
    save_effect      TEXT CHECK (save_effect IS NULL OR save_effect IN ('negates', 'half', 'partial', 'special')), -- c: parsed from saving_throw
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
    link_type      TEXT NOT NULL DEFAULT 'grants' CHECK (link_type IN ('grants', 'modifies')),
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
    data_source TEXT CHECK (data_source IN ('binary', 'wiki')),  -- provenance
    PRIMARY KEY (item_id, effect_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_item_effects_item ON item_effects(item_id);
CREATE INDEX IF NOT EXISTS idx_item_effects_effect ON item_effects(effect_id);

-- Bonus Definitions (normalized: one row per unique stat+bonus_type+value) --
CREATE TABLE IF NOT EXISTS bonuses (
    id            INTEGER PRIMARY KEY,                           -- c: autoincrement
    name          TEXT    NOT NULL,                               -- c: "{stat} +{value}" format
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
    data_source       TEXT CHECK (data_source IN ('binary', 'wiki')),
    resolution_method TEXT CHECK (resolution_method IN ('fid_lookup', 'type167_name', 'stat_def_ids', 'wiki_enchantment')),
    PRIMARY KEY (item_id, bonus_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_item_bonuses_item ON item_bonuses(item_id);
CREATE INDEX IF NOT EXISTS idx_item_bonuses_bonus ON item_bonuses(bonus_id);

-- M2M: augments <-> bonuses
CREATE TABLE IF NOT EXISTS augment_bonuses (
    augment_id        INTEGER NOT NULL REFERENCES augments(id) ON DELETE CASCADE,
    bonus_id          INTEGER NOT NULL REFERENCES bonuses(id),
    sort_order        INTEGER NOT NULL DEFAULT 0,
    data_source       TEXT CHECK (data_source IN ('binary', 'wiki')),
    resolution_method TEXT CHECK (resolution_method IN ('wiki_enchantment', 'binary_name', 'fid_lookup')),
    PRIMARY KEY (augment_id, bonus_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_augment_bonuses_augment ON augment_bonuses(augment_id);

-- M2M: enhancements <-> bonuses (with rank activation)
CREATE TABLE IF NOT EXISTS enhancement_bonuses (
    enhancement_id    INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    bonus_id          INTEGER NOT NULL REFERENCES bonuses(id),
    min_rank          INTEGER NOT NULL DEFAULT 1 CHECK (min_rank >= 1),
    data_source       TEXT CHECK (data_source IN ('binary', 'wiki')),
    resolution_method TEXT CHECK (resolution_method IN ('wiki_description', 'localization_orphan', 'binary_name')),
    PRIMARY KEY (enhancement_id, bonus_id, min_rank)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_bonuses_enh ON enhancement_bonuses(enhancement_id);

-- M2M: set_bonuses <-> bonuses (with piece count threshold)
CREATE TABLE IF NOT EXISTS set_bonus_bonuses (
    set_id            INTEGER NOT NULL REFERENCES set_bonuses(id) ON DELETE CASCADE,
    bonus_id          INTEGER NOT NULL REFERENCES bonuses(id),
    min_pieces        INTEGER NOT NULL CHECK (min_pieces >= 2),
    sort_order        INTEGER NOT NULL DEFAULT 0,
    data_source       TEXT CHECK (data_source IN ('binary', 'wiki')),
    resolution_method TEXT CHECK (resolution_method IN ('wiki_enchantment', 'binary_name')),
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

_SEED_SQL = """
-- Ability scores
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (1, 'Strength',     'ability'),
    (2, 'Dexterity',    'ability'),
    (3, 'Constitution', 'ability'),
    (4, 'Intelligence', 'ability'),
    (5, 'Wisdom',       'ability'),
    (6, 'Charisma',     'ability');

-- Martial stats (melee/ranged offense, tactics)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (7,  'Melee Power',       'martial'),
    (8,  'Ranged Power',      'martial'),
    (9,  'Attack Bonus',      'martial'),
    (10, 'Damage Bonus',      'martial'),
    (11, 'Hit Points',        'martial'),
    (12, 'Sneak Attack Dice', 'martial'),
    (36, 'Trip DC',           'martial'),
    (37, 'Sunder DC',         'martial'),
    (38, 'Stun DC',           'martial'),
    (39, 'Assassinate DC',    'martial'),
    (40, 'Helpless Damage',   'martial'),
    (63, 'Seeker',            'martial'),
    (64, 'Deadly',            'martial'),
    (65, 'Accuracy',          'martial'),
    (66, 'Deception',         'martial'),
    (67, 'Speed',             'martial'),
    (68, 'Doublestrike',      'martial'),
    (69, 'Doubleshot',        'martial'),
    (118, 'Combat Mastery',   'martial'),
    (119, 'Tendon Slice',     'martial'),
    (124, 'Nimble',           'martial'),
    (125, 'Alluring',         'martial');

-- Defensive stats (AC, saves, resistances, sheltering, absorption)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (13, 'Armor Class',                'defensive'),
    (14, 'Physical Resistance Rating', 'defensive'),
    (15, 'Magical Resistance Rating',  'defensive'),
    (16, 'Fortification',              'defensive'),
    (17, 'Dodge',                      'defensive'),
    (18, 'Fortitude Save',             'defensive'),
    (19, 'Reflex Save',               'defensive'),
    (20, 'Will Save',                  'defensive'),
    (21, 'Spell Resistance',           'defensive'),
    (62, 'Saving Throws vs Traps',     'defensive'),
    (70, 'Physical Sheltering',        'defensive'),
    (71, 'Magical Sheltering',         'defensive'),
    (72, 'Concealment',                'defensive'),
    (115, 'Natural Armor',             'defensive'),
    (116, 'Protection',                'defensive'),
    (117, 'Sheltering',                'defensive'),
    (120, 'Resistance',                'defensive'),
    (121, 'Enchantment Save',          'defensive'),
    (122, 'Curse Save',                'defensive'),
    (123, 'Poison Resistance',         'defensive'),
    (128, 'Elemental Resistance',      'defensive'),
    (76, 'Fire Resistance',            'defensive'),
    (77, 'Cold Resistance',            'defensive'),
    (78, 'Electric Resistance',        'defensive'),
    (79, 'Acid Resistance',            'defensive'),
    (80, 'Sonic Resistance',           'defensive'),
    (81, 'Light Resistance',           'defensive'),
    (82, 'Force Resistance',           'defensive'),
    (83, 'Negative Resistance',        'defensive'),
    (84, 'Fire Absorption',            'defensive'),
    (85, 'Cold Absorption',            'defensive'),
    (86, 'Electric Absorption',        'defensive'),
    (87, 'Acid Absorption',            'defensive'),
    (88, 'Sonic Absorption',           'defensive'),
    (89, 'Light Absorption',           'defensive'),
    (90, 'Force Absorption',           'defensive'),
    (91, 'Negative Absorption',        'defensive');

-- Magical stats (spell power, spell focus, spell penetration)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (22, 'Spell Points',              'magical'),
    (23, 'Spell Penetration',         'magical'),
    (24, 'Universal Spell Power',     'magical'),
    (25, 'Fire Spell Power',          'magical'),
    (26, 'Cold Spell Power',          'magical'),
    (27, 'Electric Spell Power',      'magical'),
    (28, 'Acid Spell Power',          'magical'),
    (29, 'Sonic Spell Power',         'magical'),
    (30, 'Light Spell Power',         'magical'),
    (31, 'Force Spell Power',         'magical'),
    (32, 'Negative Spell Power',      'magical'),
    (33, 'Positive Spell Power',      'magical'),
    (34, 'Repair Spell Power',        'magical'),
    (35, 'Alignment Spell Power',     'magical'),
    (92, 'Abjuration Spell Focus',    'magical'),
    (93, 'Conjuration Spell Focus',   'magical'),
    (94, 'Enchantment Spell Focus',   'magical'),
    (95, 'Evocation Spell Focus',     'magical'),
    (96, 'Illusion Spell Focus',      'magical'),
    (97, 'Necromancy Spell Focus',    'magical'),
    (98, 'Transmutation Spell Focus', 'magical'),
    (99, 'Wizardry',                  'magical'),
    (100, 'Spell Focus Mastery',      'magical'),
    (126, 'Rune Arm Spell Focus',    'magical'),
    (101, 'Fire Spell Lore',          'magical'),
    (102, 'Cold Spell Lore',          'magical'),
    (103, 'Electric Spell Lore',      'magical'),
    (104, 'Acid Spell Lore',          'magical'),
    (105, 'Sonic Spell Lore',         'magical'),
    (106, 'Light Spell Lore',         'magical'),
    (107, 'Force Spell Lore',         'magical'),
    (108, 'Negative Spell Lore',      'magical'),
    (109, 'Positive Spell Lore',      'magical'),
    (110, 'Repair Spell Lore',        'magical'),
    (111, 'Universal Spell Lore',     'magical'),
    (112, 'Spell Lore',              'magical'),
    (113, 'Sacred Ground Lore',       'magical'),
    (114, 'Dark Restoration Lore',    'magical');

-- Skills
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (41, 'Balance',               'skill'),
    (42, 'Bluff',                 'skill'),
    (43, 'Concentration',         'skill'),
    (44, 'Diplomacy',             'skill'),
    (45, 'Disable Device',        'skill'),
    (46, 'Haggle',                'skill'),
    (47, 'Heal',                  'skill'),
    (48, 'Hide',                  'skill'),
    (49, 'Intimidate',            'skill'),
    (50, 'Jump',                  'skill'),
    (51, 'Listen',                'skill'),
    (52, 'Move Silently',         'skill'),
    (53, 'Open Lock',             'skill'),
    (54, 'Perform',               'skill'),
    (55, 'Repair',                'skill'),
    (56, 'Search',                'skill'),
    (57, 'Spellcraft',            'skill'),
    (58, 'Spot',                  'skill'),
    (59, 'Swim',                  'skill'),
    (60, 'Tumble',                'skill'),
    (61, 'Use Magic Device',      'skill');

-- Other stats (healing/repair amplification, misc)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (73, 'Healing Amplification', 'other'),
    (74, 'Repair Amplification',  'other'),
    (75, 'Well Rounded',          'other'),
    (127, 'Linguistics',          'skill'),
    (129, 'Positive Healing Amplification', 'other'),
    (130, 'Negative Healing Amplification', 'other'),
    (131, 'Maximum Spell Points',           'magical'),
    (132, 'Critical Damage Multiplier',     'martial'),
    (133, 'Critical Threat Range',          'martial'),
    (134, 'Melee and Ranged Power',         'martial'),
    (135, 'Physical and Magical Resistance Rating', 'defensive'),
    (136, 'Positive and Negative Spell Power',      'magical'),
    (137, 'Positive and Negative Healing Amplification', 'other'),
    (138, 'Doublestrike and Doubleshot',    'martial'),
    (140, 'Poison Spell Power',             'magical'),
    (142, 'Temporary Hit Points',           'defensive'),
    (143, 'Bard Songs',                     'other'),
    (144, 'Movement Speed',                 'other'),
    (145, 'Maximum Hit Points',             'defensive');

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
INSERT OR IGNORE INTO classes (id, name, hit_die, bab_progression, skill_points_per_level, fort_save_progression, ref_save_progression, will_save_progression, caster_type, spell_tradition, alignment) VALUES
    (1,  'Barbarian',      12, 'full',          4, 'good', 'poor', 'poor', 'none',  NULL,     'any non-lawful'),
    (2,  'Bard',            8, 'three_quarter',  6, 'poor', 'good', 'good', 'full',  'arcane', 'any'),
    (3,  'Cleric',          8, 'three_quarter',  2, 'good', 'poor', 'good', 'full',  'divine', 'any'),
    (4,  'Fighter',        10, 'full',           2, 'good', 'poor', 'poor', 'none',  NULL,     'any'),
    (5,  'Paladin',        10, 'full',           2, 'good', 'poor', 'poor', 'half',  'divine', 'lawful good'),
    (6,  'Ranger',         10, 'full',           6, 'good', 'good', 'poor', 'half',  'divine', 'any'),
    (7,  'Rogue',           8, 'three_quarter',  8, 'poor', 'good', 'poor', 'none',  NULL,     'any'),
    (8,  'Sorcerer',        6, 'half',           2, 'poor', 'poor', 'good', 'full',  'arcane', 'any'),
    (9,  'Wizard',          6, 'half',           2, 'poor', 'poor', 'good', 'full',  'arcane', 'any'),
    (10, 'Monk',            8, 'three_quarter',  4, 'good', 'good', 'good', 'none',  NULL,     'any lawful'),
    (11, 'Favored Soul',    8, 'three_quarter',  2, 'good', 'poor', 'good', 'full',  'divine', 'any'),
    (12, 'Artificer',       8, 'three_quarter',  4, 'good', 'poor', 'good', 'full',  'arcane', 'any'),
    (13, 'Druid',           8, 'three_quarter',  4, 'good', 'poor', 'good', 'full',  'divine', 'any neutral'),
    (14, 'Warlock',         6, 'three_quarter',  2, 'poor', 'poor', 'good', 'full',  'arcane', 'any'),
    (15, 'Alchemist',       6, 'three_quarter',  4, 'good', 'poor', 'good', 'full',  'arcane', 'any');

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
INSERT OR IGNORE INTO races (id, name, race_type) VALUES
    -- Free races
    (1,  'Human',         'free'),
    (2,  'Elf',           'free'),
    (3,  'Dwarf',         'free'),
    (4,  'Halfling',      'free'),
    (5,  'Warforged',     'free'),
    (6,  'Drow Elf',      'free'),
    (7,  'Half-Elf',      'free'),
    (8,  'Half-Orc',      'free'),
    (9,  'Gnome',         'free'),
    (10, 'Dragonborn',    'free'),
    (11, 'Tiefling',      'free'),
    (12, 'Wood Elf',      'free'),
    -- Premium races
    (13, 'Aasimar',       'premium'),
    (14, 'Tabaxi',        'premium'),
    (15, 'Shifter',       'premium'),
    (16, 'Eladrin',       'premium'),
    (17, 'Dhampir',       'premium'),
    -- Iconic races (start at class level, have a parent base race)
    (18, 'Bladeforged',          'iconic'),
    (19, 'Purple Dragon Knight', 'iconic'),
    (20, 'Morninglord',          'iconic'),
    (21, 'Shadar-kai',           'iconic'),
    (22, 'Deep Gnome',           'iconic'),
    (23, 'Aasimar Scourge',      'iconic'),
    (24, 'Razorclaw Shifter',    'iconic'),
    (25, 'Tiefling Scoundrel',   'iconic'),
    (26, 'Tabaxi Trailblazer',   'iconic'),
    (27, 'Eladrin Chaosmancer',  'iconic'),
    (28, 'Dhampir Dark Bargainer','iconic');

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
    (22, 'Stacking',      1),  -- explicitly stacking bonuses
    (23, 'Rage',          0),
    (24, 'Primal',        0),
    (25, 'Determination', 0),
    (26, 'Implement',     0),
    (27, 'Music',         0),
    (28, 'Equipment',     0);

-- Damage types
INSERT OR IGNORE INTO damage_types (id, name, category) VALUES
    (1,  'Slashing',    'physical'),
    (2,  'Piercing',    'physical'),
    (3,  'Bludgeoning', 'physical'),
    (4,  'Fire',        'elemental'),
    (5,  'Cold',        'elemental'),
    (6,  'Electric',    'elemental'),
    (7,  'Acid',        'elemental'),
    (8,  'Sonic',       'elemental'),
    (9,  'Good',        'alignment'),
    (10, 'Evil',        'alignment'),
    (11, 'Lawful',      'alignment'),
    (12, 'Chaotic',     'alignment'),
    (13, 'Negative',    'energy'),
    (14, 'Positive',    'energy'),
    (15, 'Force',       'energy'),
    (16, 'Light',       'energy'),
    (17, 'Poison',      'energy'),
    (18, 'Untyped',     'untyped');

-- Weapon proficiencies
INSERT OR IGNORE INTO weapon_proficiencies (id, name, category) VALUES
    (1, 'Simple',  'simple'),
    (2, 'Martial', 'martial'),
    (3, 'Exotic',  'exotic');

-- Equipment slots (binary codes 2–17 from EQUIPMENT_SLOTS enum; seed PKs are independent)
INSERT OR IGNORE INTO equipment_slots (id, name, sort_order, category) VALUES
    (1,  'Main Hand',  1,  'weapon'),
    (2,  'Off Hand',   2,  'weapon'),
    (3,  'Ranged',     3,  'weapon'),
    (4,  'Quiver',     4,  'weapon'),
    (5,  'Head',       5,  'armor'),
    (6,  'Neck',       6,  'accessory'),
    (7,  'Trinket',    7,  'accessory'),
    (8,  'Back',       8,  'armor'),
    (9,  'Wrists',     9,  'armor'),
    (10, 'Arms',       10, 'armor'),
    (11, 'Body',       11, 'armor'),
    (12, 'Waist',      12, 'armor'),
    (13, 'Feet',       13, 'armor'),
    (14, 'Goggles',    14, 'accessory'),
    (15, 'Ring',       15, 'accessory'),
    (16, 'Runearm',    16, 'weapon');

-- Spell schools
INSERT OR IGNORE INTO spell_schools (id, name) VALUES
    (1, 'Abjuration'),
    (2, 'Conjuration'),
    (3, 'Divination'),
    (4, 'Enchantment'),
    (5, 'Evocation'),
    (6, 'Illusion'),
    (7, 'Necromancy'),
    (8, 'Transmutation'),
    (9, 'Universal');

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
    (2, 2, 2, 'innate'), (2, 3, -2, 'innate'),
    -- 3=Dwarf: +2 CON, -2 CHA
    (3, 3, 2, 'innate'), (3, 6, -2, 'innate'),
    -- 4=Halfling: +2 DEX, -2 STR
    (4, 2, 2, 'innate'), (4, 1, -2, 'innate'),
    -- 5=Warforged: +2 CON, -2 WIS, -2 CHA
    (5, 3, 2, 'innate'), (5, 5, -2, 'innate'), (5, 6, -2, 'innate'),
    -- 6=Drow Elf: +2 DEX, +2 INT, +2 CHA, -2 CON
    (6, 2, 2, 'innate'), (6, 4, 2, 'innate'), (6, 6, 2, 'innate'), (6, 3, -2, 'innate'),
    -- 7=Half-Elf: no innate mods
    -- 8=Half-Orc: +2 STR, -2 INT, -2 CHA
    (8, 1, 2, 'innate'), (8, 4, -2, 'innate'), (8, 6, -2, 'innate'),
    -- 9=Gnome: +2 INT, -2 STR
    (9, 4, 2, 'innate'), (9, 1, -2, 'innate'),
    -- 10=Dragonborn: +2 STR, +2 CHA, -2 DEX
    (10, 1, 2, 'innate'), (10, 6, 2, 'innate'), (10, 2, -2, 'innate'),
    -- 11=Tiefling: +2 CHA
    (11, 6, 2, 'innate'),
    -- 12=Wood Elf: +2 DEX, -2 INT
    (12, 2, 2, 'innate'), (12, 4, -2, 'innate'),
    -- 13=Aasimar: +2 WIS
    (13, 5, 2, 'innate'),
    -- 14=Tabaxi: +2 DEX
    (14, 2, 2, 'innate'),
    -- 15=Shifter: +2 DEX, -2 INT
    (15, 2, 2, 'innate'), (15, 4, -2, 'innate'),
    -- 16=Eladrin: +2 DEX
    (16, 2, 2, 'innate'),
    -- 17=Dhampir: +2 STR
    (17, 1, 2, 'innate'),
    -- 18=Bladeforged: +2 CON, -2 DEX, -2 WIS
    (18, 3, 2, 'innate'), (18, 2, -2, 'innate'), (18, 5, -2, 'innate'),
    -- 19=Purple Dragon Knight: no innate mods
    -- 20=Morninglord: +2 INT, -2 CON
    (20, 4, 2, 'innate'), (20, 3, -2, 'innate'),
    -- 21=Shadar-kai: +2 DEX, -2 CHA
    (21, 2, 2, 'innate'), (21, 6, -2, 'innate'),
    -- 22=Deep Gnome: +2 INT, +2 WIS, -2 STR, -2 CHA
    (22, 4, 2, 'innate'), (22, 5, 2, 'innate'), (22, 1, -2, 'innate'), (22, 6, -2, 'innate'),
    -- 23=Aasimar Scourge: +2 WIS
    (23, 5, 2, 'innate'),
    -- 24=Razorclaw Shifter: +2 STR, -2 INT
    (24, 1, 2, 'innate'), (24, 4, -2, 'innate'),
    -- 25=Tiefling Scoundrel: +2 CHA
    (25, 6, 2, 'innate'),
    -- 26=Tabaxi Trailblazer: +2 DEX
    (26, 2, 2, 'innate'),
    -- 27=Eladrin Chaosmancer: +2 CHA
    (27, 6, 2, 'innate'),
    -- 28=Dhampir Dark Bargainer: +1 CHA, +1 INT
    (28, 6, 1, 'innate'), (28, 4, 1, 'innate');

-- Enhancement racial ability modifiers (from racial enhancement trees, ddowiki.com/page/Races)
-- Fixed bonuses from core abilities; choice-based from racial tree picks
-- is_choice=1 means player distributes choice_pool points among marked stats
INSERT OR IGNORE INTO race_ability_modifiers (race_id, stat_id, modifier, source, is_choice, choice_pool) VALUES
    -- 1=Human: choose +1 to any stat, +1 to a different stat (pool=1 each pick)
    (1, 1, 0, 'enhancement', 1, 1), (1, 2, 0, 'enhancement', 1, 1),
    (1, 3, 0, 'enhancement', 1, 1), (1, 4, 0, 'enhancement', 1, 1),
    (1, 5, 0, 'enhancement', 1, 1), (1, 6, 0, 'enhancement', 1, 1),
    -- 2=Elf: +2 DEX
    (2, 2, 2, 'enhancement', 0, NULL),
    -- 3=Dwarf: +2 CON
    (3, 3, 2, 'enhancement', 0, NULL),
    -- 4=Halfling: +2 DEX
    (4, 2, 2, 'enhancement', 0, NULL),
    -- 5=Warforged: +2 CON
    (5, 3, 2, 'enhancement', 0, NULL),
    -- 6=Drow Elf: +2 total from DEX/INT/CHA
    (6, 2, 0, 'enhancement', 1, 2), (6, 4, 0, 'enhancement', 1, 2), (6, 6, 0, 'enhancement', 1, 2),
    -- 7=Half-Elf: as Elf or Human (choice)
    (7, 1, 0, 'enhancement', 1, 2), (7, 2, 0, 'enhancement', 1, 2),
    (7, 3, 0, 'enhancement', 1, 2), (7, 4, 0, 'enhancement', 1, 2),
    (7, 5, 0, 'enhancement', 1, 2), (7, 6, 0, 'enhancement', 1, 2),
    -- 8=Half-Orc: +2 STR
    (8, 1, 2, 'enhancement', 0, NULL),
    -- 9=Gnome: +2 INT
    (9, 4, 2, 'enhancement', 0, NULL),
    -- 10=Dragonborn: +2 total from STR/CHA
    (10, 1, 0, 'enhancement', 1, 2), (10, 6, 0, 'enhancement', 1, 2),
    -- 11=Tiefling: +2 CHA
    (11, 6, 2, 'enhancement', 0, NULL),
    -- 12=Wood Elf: (none parsed — wiki cell truncated)
    -- 13=Aasimar: +2 total from STR/WIS/CHA
    (13, 1, 0, 'enhancement', 1, 2), (13, 5, 0, 'enhancement', 1, 2), (13, 6, 0, 'enhancement', 1, 2),
    -- 14=Tabaxi: +2 total from CHA/DEX
    (14, 6, 0, 'enhancement', 1, 2), (14, 2, 0, 'enhancement', 1, 2),
    -- 15=Shifter: +2 total from STR/DEX/CON/WIS
    (15, 1, 0, 'enhancement', 1, 2), (15, 2, 0, 'enhancement', 1, 2),
    (15, 3, 0, 'enhancement', 1, 2), (15, 5, 0, 'enhancement', 1, 2),
    -- 16=Eladrin: +1 CHA (fixed) + +2 total from DEX/INT/CHA
    (16, 6, 1, 'enhancement', 0, NULL),
    (16, 2, 0, 'enhancement', 1, 2), (16, 4, 0, 'enhancement', 1, 2),
    -- 17=Dhampir: +2 total from STR/CON/CHA
    (17, 1, 0, 'enhancement', 1, 2), (17, 3, 0, 'enhancement', 1, 2), (17, 6, 0, 'enhancement', 1, 2),
    -- 18=Bladeforged: +2 CON
    (18, 3, 2, 'enhancement', 0, NULL),
    -- 19=Purple Dragon Knight: choose +1 to any stat, +1 to different stat
    (19, 1, 0, 'enhancement', 1, 1), (19, 2, 0, 'enhancement', 1, 1),
    (19, 3, 0, 'enhancement', 1, 1), (19, 4, 0, 'enhancement', 1, 1),
    (19, 5, 0, 'enhancement', 1, 1), (19, 6, 0, 'enhancement', 1, 1),
    -- 20=Morninglord: +2 INT
    (20, 4, 2, 'enhancement', 0, NULL),
    -- 21=Shadar-kai: +1 total from DEX/INT/CHA
    (21, 2, 0, 'enhancement', 1, 1), (21, 4, 0, 'enhancement', 1, 1), (21, 6, 0, 'enhancement', 1, 1),
    -- 22=Deep Gnome: +2 total from WIS/INT
    (22, 5, 0, 'enhancement', 1, 2), (22, 4, 0, 'enhancement', 1, 2),
    -- 23=Aasimar Scourge: +1 CON (fixed) + +2 total from STR/WIS/CHA
    (23, 3, 1, 'enhancement', 0, NULL),
    (23, 1, 0, 'enhancement', 1, 2), (23, 5, 0, 'enhancement', 1, 2), (23, 6, 0, 'enhancement', 1, 2),
    -- 24=Razorclaw Shifter: +2 total from STR/DEX/CON
    (24, 1, 0, 'enhancement', 1, 2), (24, 2, 0, 'enhancement', 1, 2), (24, 3, 0, 'enhancement', 1, 2),
    -- 25=Tiefling Scoundrel: +2 CHA
    (25, 6, 2, 'enhancement', 0, NULL),
    -- 26=Tabaxi Trailblazer: +2 DEX
    (26, 2, 2, 'enhancement', 0, NULL),
    -- 27=Eladrin Chaosmancer: +1 CHA (fixed) + +2 total from DEX/INT/CHA
    (27, 6, 1, 'enhancement', 0, NULL),
    (27, 2, 0, 'enhancement', 1, 2), (27, 4, 0, 'enhancement', 1, 2),
    -- 28=Dhampir Dark Bargainer: +2 total from CHA/CON/INT
    (28, 6, 0, 'enhancement', 1, 2), (28, 3, 0, 'enhancement', 1, 2), (28, 4, 0, 'enhancement', 1, 2);
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
