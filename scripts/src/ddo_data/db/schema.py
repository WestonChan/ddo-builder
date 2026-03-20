"""DDO game database schema — DDL and seed data for SQLite."""

from __future__ import annotations

import sqlite3

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

SCHEMA_V1 = """
PRAGMA foreign_keys = ON;

-- Game Mechanics Reference (must precede all FK dependents) ----------------
CREATE TABLE IF NOT EXISTS stats (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL  CHECK (category IN ('defensive', 'martial', 'magical', 'other'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stats_name ON stats(name);
CREATE INDEX IF NOT EXISTS idx_stats_category ON stats(category);

CREATE TABLE IF NOT EXISTS bonus_types (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    stacks_with_self INTEGER NOT NULL DEFAULT 0 CHECK (stacks_with_self IN (0, 1))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bonus_types_name ON bonus_types(name);

CREATE TABLE IF NOT EXISTS skills (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    key_ability_id INTEGER NOT NULL REFERENCES stats(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name ON skills(name);

CREATE TABLE IF NOT EXISTS damage_types (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL  CHECK (category IN ('physical', 'elemental', 'alignment', 'energy', 'untyped'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_damage_types_name ON damage_types(name);

CREATE TABLE IF NOT EXISTS weapon_proficiencies (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL  CHECK (category IN ('simple', 'martial', 'exotic'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weapon_proficiencies_name ON weapon_proficiencies(name);

CREATE TABLE IF NOT EXISTS weapon_types (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    proficiency_id INTEGER REFERENCES weapon_proficiencies(id),
    base_damage    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weapon_types_name ON weapon_types(name);
CREATE INDEX IF NOT EXISTS idx_weapon_types_proficiency ON weapon_types(proficiency_id) WHERE proficiency_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS equipment_slots (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    category   TEXT NOT NULL CHECK (category IN ('weapon', 'armor', 'accessory'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_equipment_slots_name ON equipment_slots(name);

CREATE TABLE IF NOT EXISTS spell_schools (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_spell_schools_name ON spell_schools(name);

-- Classes and Races --------------------------------------------------------
CREATE TABLE IF NOT EXISTS classes (
    id                     INTEGER PRIMARY KEY,
    name                   TEXT NOT NULL,
    hit_die                INTEGER,
    bab_progression        TEXT CHECK (bab_progression IN ('full', 'three_quarter', 'half')),
    skill_points_per_level INTEGER,
    fort_save_progression  TEXT CHECK (fort_save_progression IN ('good', 'poor')),
    ref_save_progression   TEXT CHECK (ref_save_progression  IN ('good', 'poor')),
    will_save_progression  TEXT CHECK (will_save_progression IN ('good', 'poor')),
    caster_type            TEXT CHECK (caster_type IN ('full', 'half', 'none')),
    spell_tradition        TEXT CHECK (spell_tradition IN ('arcane', 'divine')),
    description            TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_classes_name ON classes(name);

CREATE TABLE IF NOT EXISTS races (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_races_name ON races(name);

CREATE TABLE IF NOT EXISTS race_ability_bonuses (
    race_id  INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    stat_id  INTEGER NOT NULL REFERENCES stats(id),
    modifier INTEGER NOT NULL,
    PRIMARY KEY (race_id, stat_id)
);
CREATE INDEX IF NOT EXISTS idx_race_ability_bonuses_stat ON race_ability_bonuses(stat_id);

CREATE TABLE IF NOT EXISTS class_skills (
    class_id       INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    skill_id       INTEGER NOT NULL REFERENCES skills(id),
    is_class_skill INTEGER NOT NULL DEFAULT 1 CHECK (is_class_skill IN (0, 1)),
    PRIMARY KEY (class_id, skill_id)
);
CREATE INDEX IF NOT EXISTS idx_class_skills_skill ON class_skills(skill_id);

CREATE TABLE IF NOT EXISTS class_bonus_feat_slots (
    class_id      INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level   INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 30),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    feat_category TEXT,
    PRIMARY KEY (class_id, class_level, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_class_bonus_feat_slots_level ON class_bonus_feat_slots(class_id, class_level);

CREATE TABLE IF NOT EXISTS class_spell_slots (
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 20),
    spell_level INTEGER NOT NULL CHECK (spell_level BETWEEN 1 AND 9),
    slots       INTEGER NOT NULL CHECK (slots >= 0),
    PRIMARY KEY (class_id, class_level, spell_level)
);

CREATE TABLE IF NOT EXISTS class_spells_known (
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 20),
    spell_level INTEGER NOT NULL CHECK (spell_level BETWEEN 1 AND 9),
    known_count INTEGER NOT NULL CHECK (known_count >= 0),
    PRIMARY KEY (class_id, class_level, spell_level)
);

-- Item Materials -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS item_materials (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    dr_bypass TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_materials_name ON item_materials(name);

-- Augments -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS augments (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    slot_color TEXT NOT NULL CHECK (slot_color IN ('colorless', 'blue', 'yellow', 'red', 'green', 'orange', 'purple', 'white')),
    min_level  INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_augments_name ON augments(name);
CREATE INDEX IF NOT EXISTS idx_augments_slot_color ON augments(slot_color);

-- Items --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    dat_id            TEXT,
    rarity            TEXT CHECK (rarity IN ('Common', 'Uncommon', 'Rare', 'Epic')),
    slot_id           INTEGER REFERENCES equipment_slots(id),
    equipment_slot    TEXT,                                         -- display fallback
    item_category     TEXT CHECK (item_category IN (
                          'Armor','Shield','Weapon','Jewelry','Clothing',
                          'Wondrous','Potion','Scroll','Wand',
                          'Component','Collectible','Consumable')),
    level             INTEGER,
    durability        INTEGER,
    item_type         TEXT,
    minimum_level     INTEGER,
    enhancement_bonus INTEGER,
    hardness          INTEGER,
    weight            REAL,
    material_id       INTEGER REFERENCES item_materials(id),
    material          TEXT,                                         -- display fallback
    binding           TEXT,
    base_value        TEXT,
    description       TEXT,
    wiki_url          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_name ON items(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_dat_id ON items(dat_id) WHERE dat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_equipment_slot ON items(equipment_slot);
CREATE INDEX IF NOT EXISTS idx_items_slot_id ON items(slot_id) WHERE slot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_minimum_level ON items(minimum_level);
CREATE INDEX IF NOT EXISTS idx_items_rarity ON items(rarity) WHERE rarity IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_weapon_stats (
    item_id        INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    damage         TEXT,
    critical       TEXT,
    weapon_type_id INTEGER REFERENCES weapon_types(id),
    weapon_type    TEXT,                                         -- display fallback
    proficiency_id INTEGER REFERENCES weapon_proficiencies(id),
    proficiency    TEXT,                                         -- display fallback
    handedness     TEXT CHECK (handedness IN ('One-handed', 'Two-handed', 'Off-hand', 'Thrown'))
);
CREATE INDEX IF NOT EXISTS idx_item_weapon_stats_weapon_type ON item_weapon_stats(weapon_type_id) WHERE weapon_type_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_item_weapon_stats_proficiency ON item_weapon_stats(proficiency_id) WHERE proficiency_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_armor_stats (
    item_id       INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    armor_bonus   INTEGER,
    max_dex_bonus INTEGER
);

CREATE TABLE IF NOT EXISTS item_augment_slots (
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    slot_type  TEXT NOT NULL,
    augment_id INTEGER REFERENCES augments(id),
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
    id                   INTEGER PRIMARY KEY,
    dat_id               TEXT,
    name                 TEXT NOT NULL,
    icon                 TEXT,
    description          TEXT,
    prerequisite         TEXT,
    note                 TEXT,
    cooldown             TEXT,
    min_bab              INTEGER,
    damage_dice_notation TEXT,
    is_free              INTEGER NOT NULL DEFAULT 0 CHECK (is_free              IN (0, 1)),
    is_passive           INTEGER NOT NULL DEFAULT 0 CHECK (is_passive           IN (0, 1)),
    is_active            INTEGER NOT NULL DEFAULT 0 CHECK (is_active            IN (0, 1)),
    is_stance            INTEGER NOT NULL DEFAULT 0 CHECK (is_stance            IN (0, 1)),
    is_metamagic         INTEGER NOT NULL DEFAULT 0 CHECK (is_metamagic         IN (0, 1)),
    is_epic_destiny      INTEGER NOT NULL DEFAULT 0 CHECK (is_epic_destiny      IN (0, 1)),
    proficiency_id       INTEGER REFERENCES weapon_proficiencies(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feats_name ON feats(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feats_dat_id ON feats(dat_id) WHERE dat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_feats_proficiency ON feats(proficiency_id) WHERE proficiency_id IS NOT NULL;

-- Past-life subtype — only populated for past life feats
CREATE TABLE IF NOT EXISTS feat_past_life_stats (
    feat_id        INTEGER PRIMARY KEY REFERENCES feats(id) ON DELETE CASCADE,
    past_life_type TEXT NOT NULL CHECK (past_life_type IN ('heroic', 'racial', 'iconic', 'epic', 'legendary')),
    class_id       INTEGER REFERENCES classes(id),
    race_id        INTEGER REFERENCES races(id),
    max_stacks     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_feat_past_life_stats_class ON feat_past_life_stats(class_id) WHERE class_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_feat_past_life_stats_race  ON feat_past_life_stats(race_id)  WHERE race_id  IS NOT NULL;

CREATE TABLE IF NOT EXISTS feat_bonus_classes (
    feat_id  INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    PRIMARY KEY (feat_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_feat_bonus_classes_class ON feat_bonus_classes(class_id);

CREATE TABLE IF NOT EXISTS feat_prereq_feats (
    feat_id          INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    required_feat_id INTEGER NOT NULL REFERENCES feats(id),
    logic_group      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, required_feat_id, logic_group)
);
CREATE INDEX IF NOT EXISTS idx_feat_prereq_feats_required ON feat_prereq_feats(required_feat_id);

CREATE TABLE IF NOT EXISTS feat_prereq_stats (
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    stat_id     INTEGER NOT NULL REFERENCES stats(id),
    min_value   INTEGER NOT NULL CHECK (min_value > 0),
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, stat_id, logic_group)
);

CREATE TABLE IF NOT EXISTS feat_prereq_classes (
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    class_id    INTEGER NOT NULL REFERENCES classes(id),
    min_level   INTEGER NOT NULL CHECK (min_level >= 1),
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, class_id, logic_group)
);

CREATE TABLE IF NOT EXISTS feat_prereq_races (
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    race_id     INTEGER NOT NULL REFERENCES races(id),
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, race_id, logic_group)
);

CREATE TABLE IF NOT EXISTS feat_prereq_skills (
    feat_id     INTEGER NOT NULL REFERENCES feats(id) ON DELETE CASCADE,
    skill_id    INTEGER NOT NULL REFERENCES skills(id),
    min_rank    INTEGER NOT NULL CHECK (min_rank > 0),
    logic_group INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feat_id, skill_id, logic_group)
);

CREATE TABLE IF NOT EXISTS class_auto_feats (
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    class_level INTEGER NOT NULL CHECK (class_level BETWEEN 1 AND 30),
    feat_id     INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (class_id, class_level, feat_id)
);
CREATE INDEX IF NOT EXISTS idx_class_auto_feats_feat ON class_auto_feats(feat_id);

CREATE TABLE IF NOT EXISTS race_feats (
    race_id INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    feat_id INTEGER NOT NULL REFERENCES feats(id),
    PRIMARY KEY (race_id, feat_id)
);
CREATE INDEX IF NOT EXISTS idx_race_feats_feat ON race_feats(feat_id);

-- Enhancement Trees --------------------------------------------------------
CREATE TABLE IF NOT EXISTS enhancement_trees (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    tree_type TEXT NOT NULL CHECK (tree_type IN ('class', 'racial', 'universal', 'reaper', 'destiny')),
    ap_pool   TEXT NOT NULL CHECK (ap_pool IN ('heroic', 'racial', 'reaper', 'legendary')),
    class_id  INTEGER REFERENCES classes(id),
    race_id   INTEGER REFERENCES races(id),
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
    id          INTEGER PRIMARY KEY,
    tree_id     INTEGER NOT NULL REFERENCES enhancement_trees(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    icon        TEXT,
    max_ranks   INTEGER NOT NULL DEFAULT 1,
    ap_cost     INTEGER NOT NULL DEFAULT 1,
    progression INTEGER NOT NULL DEFAULT 0,
    tier        TEXT NOT NULL CHECK (tier IN ('core', '1', '2', '3', '4', '5', 'unknown')),
    level_req   TEXT,
    prerequisite TEXT
);
CREATE INDEX IF NOT EXISTS idx_enhancements_tree ON enhancements(tree_id);
CREATE INDEX IF NOT EXISTS idx_enhancements_name ON enhancements(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_enhancements_unique ON enhancements(tree_id, name, tier, progression);

CREATE TABLE IF NOT EXISTS enhancement_ranks (
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    rank           INTEGER NOT NULL CHECK (rank >= 1),
    description    TEXT,
    PRIMARY KEY (enhancement_id, rank)
);

CREATE TABLE IF NOT EXISTS enhancement_prereqs (
    enhancement_id          INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    required_enhancement_id INTEGER NOT NULL REFERENCES enhancements(id),
    PRIMARY KEY (enhancement_id, required_enhancement_id)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_prereqs_required ON enhancement_prereqs(required_enhancement_id);

CREATE TABLE IF NOT EXISTS enhancement_prereq_classes (
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    class_id       INTEGER NOT NULL REFERENCES classes(id),
    min_level      INTEGER NOT NULL CHECK (min_level >= 1),
    PRIMARY KEY (enhancement_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_prereq_classes_class ON enhancement_prereq_classes(class_id);

CREATE TABLE IF NOT EXISTS enhancement_prereq_races (
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    race_id        INTEGER NOT NULL REFERENCES races(id),
    PRIMARY KEY (enhancement_id, race_id)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_prereq_races_race ON enhancement_prereq_races(race_id);

CREATE TABLE IF NOT EXISTS enhancement_feat_links (
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    feat_id        INTEGER NOT NULL REFERENCES feats(id),
    link_type      TEXT NOT NULL CHECK (link_type IN ('requires', 'grants', 'excludes')),
    min_rank       INTEGER NOT NULL DEFAULT 1,  -- rank at which this link becomes active
    PRIMARY KEY (enhancement_id, feat_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_feat_links_feat ON enhancement_feat_links(feat_id);

-- enhancement_spell_links defined after Spells block (forward reference to spells)

-- Patrons ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patrons (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_patrons_name ON patrons(name);

-- Adventure Packs ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS adventure_packs (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    is_free_to_play INTEGER NOT NULL DEFAULT 0 CHECK (is_free_to_play IN (0, 1))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_adventure_packs_name ON adventure_packs(name);

-- Quests -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quests (
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
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    school_id        INTEGER REFERENCES spell_schools(id),
    spell_points     INTEGER,
    cooldown         TEXT,
    description      TEXT,
    components       TEXT,
    range            TEXT,
    target           TEXT,
    duration         TEXT,
    saving_throw     TEXT,
    spell_resistance TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_spells_name ON spells(name);
CREATE INDEX IF NOT EXISTS idx_spells_school ON spells(school_id) WHERE school_id IS NOT NULL;

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
CREATE TABLE IF NOT EXISTS enhancement_spell_links (
    enhancement_id INTEGER NOT NULL REFERENCES enhancements(id) ON DELETE CASCADE,
    spell_id       INTEGER NOT NULL REFERENCES spells(id),
    link_type      TEXT NOT NULL DEFAULT 'grants' CHECK (link_type IN ('grants', 'modifies')),
    min_rank       INTEGER NOT NULL DEFAULT 1,  -- rank at which this link becomes active
    PRIMARY KEY (enhancement_id, spell_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_enhancement_spell_links_spell ON enhancement_spell_links(spell_id);

-- Set Bonuses --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS set_bonuses (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_set_bonuses_name ON set_bonuses(name);

CREATE TABLE IF NOT EXISTS set_bonus_items (
    set_id  INTEGER NOT NULL REFERENCES set_bonuses(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (set_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_set_bonus_items_item ON set_bonus_items(item_id);

-- Effects (weapon/armor enchantments: Vorpal, Bane, Destruction, etc.) ------
CREATE TABLE IF NOT EXISTS effects (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    modifier    TEXT,
    description TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_effects_name_mod
    ON effects(name, COALESCE(modifier, ''));

CREATE TABLE IF NOT EXISTS item_effects (
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    effect_id  INTEGER NOT NULL REFERENCES effects(id),
    value      INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (item_id, effect_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_item_effects_item ON item_effects(item_id);
CREATE INDEX IF NOT EXISTS idx_item_effects_effect ON item_effects(effect_id);

-- Unified Bonuses ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS bonuses (
    id            INTEGER PRIMARY KEY,
    source_type   TEXT    NOT NULL CHECK (source_type IN ('item', 'feat', 'augment', 'enhancement', 'set_bonus')),
    source_id     INTEGER NOT NULL,
    min_rank      INTEGER CHECK (min_rank IS NULL OR min_rank >= 1),
    min_pieces    INTEGER CHECK (min_pieces IS NULL OR min_pieces >= 2),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    name          TEXT    NOT NULL,
    stat_id       INTEGER REFERENCES stats(id),
    bonus_type_id INTEGER REFERENCES bonus_types(id),
    value         INTEGER,
    CHECK (
        (source_type IN ('item', 'feat', 'augment') AND min_rank IS NULL AND min_pieces IS NULL) OR
        (source_type = 'enhancement'                AND min_rank IS NOT NULL AND min_pieces IS NULL) OR
        (source_type = 'set_bonus'                  AND min_pieces IS NOT NULL AND min_rank IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bonuses_unique ON bonuses(source_type, source_id, COALESCE(min_rank, 0), COALESCE(min_pieces, 0), sort_order);
CREATE INDEX IF NOT EXISTS idx_bonuses_source ON bonuses(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_bonuses_stat ON bonuses(stat_id) WHERE stat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bonuses_bonus_type ON bonuses(bonus_type_id) WHERE bonus_type_id IS NOT NULL;

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
    (1, 'Strength',     'other'),
    (2, 'Dexterity',    'other'),
    (3, 'Constitution', 'other'),
    (4, 'Intelligence', 'other'),
    (5, 'Wisdom',       'other'),
    (6, 'Charisma',     'other');

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

-- Other stats (ability scores, skills, healing/repair amplification)
INSERT OR IGNORE INTO stats (id, name, category) VALUES
    (41, 'Balance',               'other'),
    (42, 'Bluff',                 'other'),
    (43, 'Concentration',         'other'),
    (44, 'Diplomacy',             'other'),
    (45, 'Disable Device',        'other'),
    (46, 'Haggle',                'other'),
    (47, 'Heal',                  'other'),
    (48, 'Hide',                  'other'),
    (49, 'Intimidate',            'other'),
    (50, 'Jump',                  'other'),
    (51, 'Listen',                'other'),
    (52, 'Move Silently',         'other'),
    (53, 'Open Lock',             'other'),
    (54, 'Perform',               'other'),
    (55, 'Repair',                'other'),
    (56, 'Search',                'other'),
    (57, 'Spellcraft',            'other'),
    (58, 'Spot',                  'other'),
    (59, 'Swim',                  'other'),
    (60, 'Tumble',                'other'),
    (61, 'Use Magic Device',      'other'),
    (73, 'Healing Amplification', 'other'),
    (74, 'Repair Amplification',  'other'),
    (75, 'Well Rounded',          'other'),
    (127, 'Linguistics',          'other');

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
INSERT OR IGNORE INTO classes (id, name, hit_die, bab_progression, skill_points_per_level, fort_save_progression, ref_save_progression, will_save_progression, caster_type, spell_tradition) VALUES
    (1,  'Barbarian',      12, 'full',          4, 'good', 'poor', 'poor', 'none',  NULL),
    (2,  'Bard',            8, 'three_quarter',  6, 'poor', 'good', 'good', 'full',  'arcane'),
    (3,  'Cleric',          8, 'three_quarter',  2, 'good', 'poor', 'good', 'full',  'divine'),
    (4,  'Fighter',        10, 'full',           2, 'good', 'poor', 'poor', 'none',  NULL),
    (5,  'Paladin',        10, 'full',           2, 'good', 'poor', 'poor', 'half',  'divine'),
    (6,  'Ranger',          8, 'full',           6, 'good', 'good', 'poor', 'half',  'divine'),
    (7,  'Rogue',           6, 'three_quarter',  8, 'poor', 'good', 'poor', 'none',  NULL),
    (8,  'Sorcerer',        4, 'half',           2, 'poor', 'poor', 'good', 'full',  'arcane'),
    (9,  'Wizard',          4, 'half',           2, 'poor', 'poor', 'good', 'full',  'arcane'),
    (10, 'Monk',            8, 'three_quarter',  4, 'good', 'good', 'good', 'none',  NULL),
    (11, 'Favored Soul',    8, 'three_quarter',  2, 'good', 'poor', 'good', 'full',  'divine'),
    (12, 'Artificer',       6, 'three_quarter',  4, 'good', 'poor', 'good', 'full',  'arcane'),
    (13, 'Druid',           8, 'three_quarter',  4, 'good', 'poor', 'good', 'full',  'divine'),
    (14, 'Warlock',         6, 'three_quarter',  2, 'poor', 'poor', 'good', 'full',  'arcane'),
    (15, 'Alchemist',       8, 'three_quarter',  4, 'good', 'poor', 'good', 'full',  'arcane');

-- Races (standard + iconic)
INSERT OR IGNORE INTO races (id, name) VALUES
    (1,  'Human'),
    (2,  'Elf'),
    (3,  'Dwarf'),
    (4,  'Halfling'),
    (5,  'Warforged'),
    (6,  'Drow Elf'),
    (7,  'Half-Elf'),
    (8,  'Half-Orc'),
    (9,  'Gnome'),
    (10, 'Aasimar'),
    (11, 'Dragonborn'),
    (12, 'Tiefling'),
    (13, 'Wood Elf'),
    (14, 'Tabaxi'),
    (15, 'Shifter'),
    (16, 'Eladrin'),
    (17, 'Dhampir'),
    -- Iconic races
    (18, 'Bladeforged'),
    (19, 'Purple Dragon Knight'),
    (20, 'Morninglord'),
    (21, 'Shadar-kai'),
    (22, 'Deep Gnome'),
    (23, 'Aasimar Scourge'),
    (24, 'Razorclaw Shifter'),
    (25, 'Tiefling Scoundrel'),
    (26, 'Tabaxi Trailblazer'),
    (27, 'Eladrin Chaosmancer'),
    (28, 'Dhampir Dark Bargainer'),
    (29, 'Elven Arcane Archer');

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
    (22, 'Stacking',      1);  -- explicitly stacking bonuses

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
