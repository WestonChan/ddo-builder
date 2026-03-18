# DDO Database Design Guidelines

Design decisions for `public/data/ddo.db` — the SQLite database powering the DDO Build Planner.

---

## Naming conventions

### Table names

Tables are grouped by prefix so related tables sort together:

| Prefix | Tables |
|--------|--------|
| `item_` | `item_weapon_stats`, `item_armor_stats`, `item_augment_slots`, `item_class_min_levels`, `item_spell_links`, `item_upgrades`, `item_effect_refs` |
| `feat_` | `feat_bonus_classes`, `feat_prereq_feats`, `feat_prereq_stats`, `feat_prereq_classes`, `feat_prereq_races`, `feat_prereq_skills` |
| `class_` | `class_skills`, `class_bonus_feat_slots`, `class_spell_slots`, `class_spells_known`, `class_auto_feats` |
| `race_` | `race_ability_bonuses`, `race_feats` |
| `enhancement_` | `enhancement_trees`, `enhancement_tree_ap_thresholds`, `enhancement_ranks`, `enhancement_prereqs`, `enhancement_prereq_classes`, `enhancement_prereq_races`, `enhancement_feat_links`, `enhancement_spell_links` |
| `spell_` | `spell_class_levels`, `spell_metamagics`, `spell_damage_types`, `spell_schools` |
| `set_bonus_` | `set_bonus_items` |
| `quest_` | `quest_flagging`, `quest_loot` |
| _(unified)_ | `bonuses` — all stat effect rows, all source types |

Junction tables use `{parent}_{child_concept}` naming:
- `quest_loot` (not `quest_item_links`)
- `item_spell_links`, `enhancement_feat_links` (use `_links` when the join table has extra columns)
- `set_bonus_items`, `quest_flagging` (short/idiomatic when no extra columns)

### Column names

- **Primary keys**: always `id` for standalone auto-increment PKs; subtype table PKs use the FK column name (e.g., `item_id` on `item_weapon_stats` since it is simultaneously a FK to `items`)
- **Foreign keys**: `{referenced_table_singular}_id` — use the core noun for long table names (e.g., `slot_id` not `equipment_slot_id`, `school_id` not `spell_school_id`)
- **Boolean flags**: `is_*` prefix (e.g., `is_passive`, `is_class_skill`, `is_free_to_play`)
- **Display order**: `sort_order` (not `order` — reserved word conflict risk)
- **Display fallback columns**: strip `_id` from the FK name (e.g., `slot_id` + `equipment_slot`, `proficiency_id` + `proficiency`, `material_id` + `material`)

### Index names

```
idx_{table}_{column}              -- single-column index
idx_{table}_{col1}_{col2}        -- composite index
```

Unique indexes always use `CREATE UNIQUE INDEX` (not inline `UNIQUE` constraint) so the name is explicit:

```sql
CREATE UNIQUE INDEX idx_items_name ON items(name);
```

---

## Schema readability

### Self-documenting FK names

All PKs are `id`. FK column names follow `{singular}_id`, using the core noun for long table names — `slot_id` on `items` unambiguously points to `equipment_slots.id`, `school_id` points to `spell_schools.id`. JOIN conditions are always `fk_col = parent.id`:

```sql
-- FK column name tells you which table; .id is always the PK
JOIN classes c ON ec.class_id = c.id
```

Never rename an FK to `parent_class_id` or `fk_class` — the `{singular}_id` form is the convention.

**Self-referential FKs**: when a table references itself, or when two FKs point to the same parent table, prefix with a role word to disambiguate:
- `feat_prereq_feats.required_feat_id` (distinguishes from the parent `feat_id`)
- `item_upgrades.base_item_id` (distinguishes from the upgraded `item_id`)
- `quest_flagging.prereq_quest_id` (distinguishes from the flagged `quest_id`)

**Semantic FKs**: when the generic `{singular}_id` name wouldn't convey the FK's purpose, use a descriptive name:
- `skills.key_ability_id` — references `stats(id)`, but named for its role (the governing ability score)

### DDL comments

Add `--` comments in DDL only where intent is non-obvious from the name alone:

- Display fallback TEXT columns: `equipment_slot TEXT    -- display fallback`
- Non-obvious CHECK constraints: `-- ensures tree_type/ap_pool/class_id are consistent`
- Forward-reference reminders: `-- item_spell_links defined after Spells block`
- Section headers use `-- Section Name ---` (trailing dashes to column boundary) for visual grouping in long DDL files

Do **not** comment self-evident columns (`name TEXT NOT NULL`, `sort_order INTEGER NOT NULL`).

---

## Display fallback pattern

Several columns appear in pairs: an FK for relational queries + a TEXT fallback for display when the FK is NULL or the join target hasn't been scraped yet.

```sql
slot_id        INTEGER REFERENCES equipment_slots(id),
equipment_slot TEXT,    -- display fallback

proficiency_id INTEGER REFERENCES weapon_proficiencies(id),
proficiency    TEXT,    -- display fallback
```

**Rule**: FK column is authoritative for querying; TEXT fallback is for UI display only. Never query on the TEXT fallback column if the FK exists.

**When to use the pattern**:
- When the referenced entity comes from a different data source and may not be populated yet
- When parsing fails to resolve a name to an ID, but you still want the raw value visible

---

## Index strategy

**Always index**:
- All FK columns used in JOINs — use partial indexes (`WHERE col IS NOT NULL`) for sparse FKs to avoid indexing NULLs
- `name` columns on entities that are looked up by name from scraper output (all reference tables + core entities)
- Composite `(parent_id, level)` or `(parent_id, child_id)` on tables queried by parent + a filter column

**Use partial indexes** for sparse FK columns to save space and keep index compact:

```sql
CREATE INDEX idx_items_rarity ON items(rarity) WHERE rarity IS NOT NULL;
CREATE INDEX idx_feats_proficiency ON feats(proficiency_id) WHERE proficiency_id IS NOT NULL;
```

**Skip indexes** on:
- Junction table FKs that are already part of the PRIMARY KEY (SQLite indexes PKs automatically)
- Columns only used in full-table scans (display fallback TEXT columns)
- Low-cardinality boolean flags used alone (`is_passive` etc.) — combine with another column if needed

**Composite index ordering**: put the high-selectivity column first, the range/filter column second:

```sql
CREATE INDEX idx_class_bonus_feat_slots_level ON class_bonus_feat_slots(class_id, class_level);
```

---

## Consolidating columns into their own tables

**Subtype tables for optional column groups**: when a column group only applies to a subset of rows, move it to a dedicated 1:0-or-1 table rather than leaving NULLs on the parent. Use LEFT JOIN to read; the absence of a row is semantically "not applicable."

```sql
-- Weapon-specific stats — only populated for weapon items
CREATE TABLE item_weapon_stats (
    item_id    INTEGER PRIMARY KEY REFERENCES items(id),
    damage     TEXT,
    critical   TEXT,
    handedness TEXT
);

-- Query: get item + weapon stats (NULL columns if non-weapon)
SELECT i.*, iws.damage, iws.handedness
FROM items i
LEFT JOIN item_weapon_stats iws ON iws.item_id = i.id;
```

This pattern applies wherever a table would have a cluster of columns that are always NULL together. Current examples: `item_weapon_stats`, `item_armor_stats`.

**Repeated multi-value attributes**: when an entity can have multiple values for the same attribute (e.g., an item with several augment slots, or an enhancement with multiple prerequisites), use a junction/child table rather than repeating columns or a comma-separated TEXT field.

```sql
-- Multiple augment slots per item — NOT a comma-separated "slots" column on items
CREATE TABLE item_augment_slots (
    item_id    INTEGER NOT NULL REFERENCES items(id),
    sort_order INTEGER NOT NULL,
    slot_type  TEXT NOT NULL,
    PRIMARY KEY (item_id, sort_order)
);
```

**Detecting subtype candidates — two signals to look for**:

1. **Boolean flag gating a nullable cluster**: if a boolean column (`is_past_life`, `is_special`, etc.) is the only reason a group of other columns are non-NULL, the flag and its cluster belong in a subtype table. The flag itself becomes redundant — the *presence of a row* is the flag. Current extraction: `feat_past_life_stats` (previously `is_past_life + past_life_type + past_life_class_id + past_life_race_id + past_life_max_stacks` on `feats`).

2. **Structurally identical tables with different semantic payloads**: `class_spell_slots` and `class_spells_known` share the same `(class_id, class_level, spell_level, count)` shape. The similarity is real but the concepts are distinct — slots are a spell-per-day resource, known counts gate spell selection. Keep these separate when the semantic distinction drives different query patterns. Only merge when tables are genuinely interchangeable.

**Per-level data belongs in child tables**: class spell slots, known spells, bonus feat slots, and auto-granted feats are all indexed by `(class_id, class_level)`. They live in `class_spell_slots`, `class_spells_known`, `class_bonus_feat_slots`, and `class_auto_feats` respectively — not as 20-column arrays on `classes`.

**Computed values**: do not store per-level BAB or save values — they are fully derivable from `bab_progression` (`full` = level, `three_quarter` = ⌊3L/4⌋, `half` = ⌊L/2⌋) and save progressions (`good` = ⌊L/2⌋+2, `poor` = ⌊L/3⌋). Store the progression type, derive the value at query time.

---

## Multi-rank enhancement bonuses

Enhancements are structurally identical to feats at query time — both resolve to `bonuses` rows with a `source_type` and `source_id`. The only difference is that enhancement bonuses carry a `min_rank` gate: a bonus is active when the character's rank in that enhancement meets or exceeds `min_rank`.

**Cumulative values, not incremental**: store the total value active at each rank threshold, not the delta. An enhancement that gives +1/+2/+4 MRR at ranks 1/2/3 produces three rows:

```sql
-- enhancement_id=42, stat=MRR, bonus_type=Enhancement
(source_type='enhancement', source_id=42, stat_id=<mrr>, min_rank=1, value=1)
(source_type='enhancement', source_id=42, stat_id=<mrr>, min_rank=2, value=2)
(source_type='enhancement', source_id=42, stat_id=<mrr>, min_rank=3, value=4)
```

Query at character rank N: `WHERE min_rank <= N → MAX(value)`. Because values are cumulative, `MAX` always returns the highest threshold row that applies — no summing within a single enhancement source needed.

**Compound effects at a given rank**: when a rank grants both a numeric bonus and a qualitatively different effect, use multiple `bonuses` rows at the same `min_rank`, distinguished by `sort_order` and `stat_id`. Example — rank 3 gives +2 Evocation Spell Power AND grants a passive ability:

```
min_rank=1, stat=evo_sp, value=1, sort_order=0
min_rank=2, stat=evo_sp, value=2, sort_order=0   -- supersedes rank-1 row via MAX
min_rank=3, stat=some_passive_stat, value=1, sort_order=1  -- additional rank-3 effect
```

No new row needed for the evo bonus at rank 3 if its value is unchanged — the rank-2 row covers it (`min_rank=2 <= 3`).

**Feat and spell grants are also rank-gated**: `enhancement_feat_links.min_rank` and `enhancement_spell_links.min_rank` specify at which rank a feat or spell becomes active. Default is 1 (active from the first rank). A feat granted only at rank 3 has `min_rank=3`; the character builder ignores it unless the character has taken ≥3 ranks.

**Cross-source stacking after rank resolution**: once the planner has resolved each enhancement's effective bonuses (applying the `min_rank <= player_rank → MAX` reduction per stat), stacking across all sources follows the normal rule: `stacks_with_self=1` bonus types sum across all sources; `stacks_with_self=0` types take the highest single source value.

---

## Enums: reference tables vs. CHECK constraints

**Default: use a reference table** for any set of named values that is a domain concept (game terminology, categories, classifications). Reference tables are:
- Extensible without schema migration (just insert a new row)
- Queryable (JOIN to get the display name, description, sort order, etc.)
- Able to carry metadata (e.g., `bonus_types.stacks_with_self`, `equipment_slots.sort_order`, `stats.category`)

```sql
-- Prefer this:
CREATE TABLE augment_colors (
    color_id INTEGER PRIMARY KEY,
    name     TEXT NOT NULL   -- 'blue', 'yellow', 'red', ...
);

-- Over this:
slot_color TEXT CHECK (slot_color IN ('colorless', 'blue', 'yellow', ...))
```

**When CHECK constraints are appropriate** (narrow exceptions):
- Binary flags that map directly to `0`/`1`: `is_passive INTEGER CHECK (is_passive IN (0, 1))`
- Structural/schema discriminators that reflect the DDL itself and won't change: `bab_progression IN ('full', 'three_quarter', 'half')`, `logic_group` semantics
- Foreign-key–adjacent self-consistency checks on the same table: `enhancement_trees` consistency CHECK between `tree_type`, `ap_pool`, `class_id`, `race_id`

**Current schema reference tables** (already normalized):
`stats`, `bonus_types`, `skills`, `damage_types`, `weapon_proficiencies`, `weapon_types`, `equipment_slots`, `spell_schools`, `item_materials`, `classes`, `races`, `adventure_packs`, `patrons`

**Current CHECK enums** (candidates for future reference table migration):
- `augments.slot_color` → `augment_slot_colors`
- `items.rarity` → `item_rarities`
- `item_weapon_stats.handedness` → `item_handedness` or fold into `weapon_types`
- `items.item_category` → `item_categories`

These are left as CHECK constraints for now because the sets are stable and adding metadata columns is not yet needed. Convert when the planner needs to query against them (e.g., "show all augments for this slot color").

---

## DDL ordering rules

1. **Reference tables first** — `stats`, `bonus_types`, `skills`, `damage_types`, `weapon_proficiencies`, `spell_schools` have no FK dependencies; define them before anything that references them.
2. **Core entities before junction tables** — `classes`, `races`, `items`, `feats`, `enhancements`, `spells` before their junction tables.
3. **Forward references** — when a junction table has FKs to two entity blocks defined in different sections (e.g., `item_spell_links` needs both `items` and `spells`), define the junction table after the later entity block and leave a comment in the earlier block:
   ```sql
   -- item_spell_links defined after Spells block (forward reference to spells)
   ```
4. **`bonuses` last** — `bonuses` has no FKs to source entities (polymorphic), so it can be defined after all entity blocks. Any future views go after `bonuses`.
