# Phase 3b — Lighthouses + System Character

**Status:** Drafting (2026-05-02)
**Owner:** Jordan
**Depends on:**
- Phase 3a — [`docs/lore/setting.md`](../lore/setting.md) (canonical galaxy setting)
- Phase 0 — `System` model (per-Sector channel-system)
- Phase 1 — Build / parts / credits
- Phase 2a — Durable scheduler
- Phase 2b — Parameterized expedition engine
- Phase 2c — LLM narrative pipeline (used for system seed pass)

**Supersedes:** the Phase 3b placeholder section in [`2026-04-22-salvage-pulp-revamp.md`](2026-04-22-salvage-pulp-revamp.md). The original section becomes a stub that points here.

---

## Contents

1. [Frontmatter](#phase-3b--lighthouses--system-character)
2. [Goal & scope](#2-goal--scope)
3. [Player loops at a glance](#3-player-loops-at-a-glance)
4. [System character & generation](#4-system-character--generation)
5. [Citizenship & dock](#5-citizenship--dock)
6. [The Lighthouse object](#6-the-lighthouse-object)
7. [Wardenship claim](#7-wardenship-claim)
8. [Donation flow](#8-donation-flow)
9. [Upgrade catalog (stub for 3b)](#9-upgrade-catalog-stub-for-3b)
10. [Tribute](#10-tribute)
11. [Citizen buffs](#11-citizen-buffs)
12. [Beacon Flares (Slice X)](#12-beacon-flares-slice-x)
13. [System Pride](#13-system-pride)
14. [Inactivity lapse + Vacation verb](#14-inactivity-lapse--vacation-verb)
15. [Data model](#15-data-model)
16. [Commands & UI surface](#16-commands--ui-surface)
17. [Files likely touched](#17-files-likely-touched)
18. [Out of scope (deferred)](#18-out-of-scope-deferred)
19. [Verification](#19-verification)
20. [Open questions / soft commitments](#20-open-questions--soft-commitments)

---

## 2. Goal & scope

Phase 3b ships the gameplay-layer foundation that 3c, 3d, and 3e all build on. It replaces the abstract "system control" concept from the original roadmap with the canonical Lighthouse model from the setting doc, and gives both Wardens and non-Wardens daily verbs that matter.

**What ships in 3b:**

- Per-system rich character: star type, 3–7 planets with type tags, 0–3 named features, plus a one-time LLM narrative pass that generates flavor names and short prose at activation.
- Self-elected citizenship: `/dock <system>` makes a player a citizen of one system at a time, with a switching cooldown.
- Lighthouse object per system with a state machine (`active` / `contested` / `dormant`), slot count scaled by band (rim 3 / middle 5 / inner 7).
- Wardenship claim via a single Authority-vetted contract — a parameterized Phase-2b expedition whose difficulty scales with the target Lighthouse's tier. Per-player cooldown.
- Donation flow: Wardens post upgrade goals as line items (credits + parts); citizens contribute via a public goal embed; goal completion unlocks installation.
- Upgrade catalog stub: five categorical slots × two tiers = ten upgrades. Each upgrade has a Warden-side effect (flares / defense / tribute) and a citizen-side service buff (repair / training / expedition QoL).
- Tribute ledger: passive base scaled to upgrades + small cut of citizen activity. Spendable on Warden-called flares, vacation, panic-mode lapse defer; convertible to credits at unfavorable rate.
- Beacon Flares Slice X: timer-based public events with click-to-claim, tiered audience delay (citizen 0s / same-Sector neighbor 30–60s), two archetypes (Salvage Drift, Signal Pulse), Warden-called variant, System Pride scoreboard.
- Inactivity lapse: 14-day warning + 7-day grace + auto-abdication; tribute-deferral panic-mode at penalty rate; dedicated `/lighthouse vacation` verb at favorable rate.

**Out of scope** (deferred — see §18 for receivers): resource extraction and sub-claims (3c), home base UI consolidation (3d), weather events / channel events / named villains / villain takeovers / tier-III and exotic-slot upgrades / Poach + rare-prize + Bounty + Cult Whisper flare archetypes / universe-wide flare tier and cross-Sector stealing (3e), PvP Warden challenges and contested claim windows (Phase 4), alliance/guild Wardenship (Phase 4+).

---

## 3. Player loops at a glance

Three time horizons, each with its own audience.

**The claim arc (rare, weeks-scale).** A captain decides to pursue Wardenship. They browse unclaimed Lighthouses on `/lighthouse list`, pick one matching their tier, run the claim contract (a tier-scaled Phase-2b expedition), and on success become Warden of that system. Per-player cooldown caps attempt cadence. Most captains never claim; for those who do, the seat anchors their next phase of play.

**Warden daily (active stewardship).** The Warden's verbs are: post upgrade goals, watch donations land, install completed upgrades, call Beacon Flares with tribute to drive citizen engagement, declare vacations for planned absences, convert or hoard tribute. Tribute accrues passively plus a small percentage of citizen rewards in-system, so the Warden's income is partly entitlement (the seat) and partly merit (driving citizen activity). Re-investing tribute in flares creates a positive feedback loop: more flares → more citizen engagement → more activity-cut tribute → more flares.

**Citizen daily (passive engagement).** A docked captain's verbs are: contribute to whichever upgrade goal the Warden has posted (credits + parts from their own stockpile), race to claim Beacon Flares in their channel (0s priority — they get first crack), enjoy service buffs scaled to the Lighthouse's upgrade level (cheaper repairs, faster training, expedition QoL). Cross-system play within the Sector is supported but lower-priority: a fast clicker can snipe a same-guild neighbor system's flare, costing that system's Pride and giving the snipe-er a small reward and a story to tell. Citizens who don't want to climb to Wardenship still have a daily loop and a system to be loyal to.

No loop requires the others. A player who never docks still has the Phase 0–2 game; a citizen who never aspires to Warden still has flares and donation participation; a Warden whose system is quiet still earns the passive base. The loops *amplify* each other — they don't gate each other.

---

## 4. System character & generation

System character has four data layers, generated once at system activation and persisted thereafter.

### 4.1 Star

One per system. Attributes: `type` (single / binary / trinary), `color` (red / yellow / white / blue / exotic), `age` (young / mature / aging / dying). The star drives planet generation bias, weather affinity (3e), and narrative tone. Roughly 45 single-star combinations; binary/trinary multiply; ≈ 60 total combos for MVP.

### 4.2 Planets

3–7 per system. Each: `name`, `type` (rocky / gas / frozen / exotic / ocean / desert / barren), `size` (small / medium / large), `richness` (low / medium / high), and a one-line descriptor. Planet count and type distribution are biased by star type (e.g., red giants tend toward gas and barren rocky; blue stars produce more exotic-tagged planets; old stars yield more derelict-themed planet descriptors).

### 4.3 Features

0–3 per system. Named structures or zones with a type tag: `relic_field`, `hazard_zone`, `industrial_ruin`, `phenomenon`, or `derelict`. Each tag has 3–5 named templates ("the Eastern Belt of Veyra Hesper", "the Conducting Spire", "the Fog Atrium"). Features are the primary hook 3c expeditions and 3e events grab onto. A system with zero features is the bare minimum; three-feature systems are the rare ones.

### 4.4 Narrative

Flavor name (overlay on the channel name; the channel still has its own user-set name), 2–4 sentence prose paragraph, one signature detail. Generated by an LLM pass at activation that sees the structured star/planets/features data plus the setting voice prompt; output is stored verbatim.

### 4.5 Deterministic generation

Generation is keyed on a per-system seed (`system.config["generator_seed"]`, produced at first activation). Given the same seed, planet count / types / sizes / richness / feature placement are deterministic. Only the LLM narrative pass is non-deterministic; its output is stored once and never re-rolled. Determinism enables clean test fixtures and (future) regenerating flavor without losing structural identity.

### 4.6 Activation flow

1. Existing `/system enable` (Phase 0) creates the `System` row.
2. Phase 3b extends activation with: roll `generator_seed` → run the procgen pass → write `system_planets` and `system_features` rows → enqueue an LLM narrative job (Phase 2c pipeline).
3. System is immediately usable for in-channel commands; the LLM flavor lands seconds later. If the LLM job fails, a placeholder paragraph is stored and a retry is scheduled.

### 4.7 Storage shape

Two new tables (full schema in §15):

- `system_planets` — `(system_id, slot_index, name, planet_type, size, richness, descriptor)`
- `system_features` — `(system_id, slot_index, name, feature_type, descriptor)`

Plus extending `System`:

- `star_type`, `star_color`, `star_age` (new enum columns)
- `generator_seed` (stored as a key in the existing `config` JSONB)
- `flavor_text` (existing column, populated by the LLM pass)

---

## 5. Citizenship & dock

### 5.1 The dock verb

`/dock <system>` makes the running player a citizen of `<system>`. The system is referenced by name with autocomplete from systems the player can access. The command can be issued from any channel — docking is a player-level state, not channel-bound.

Each player has at most one active citizenship at a time. Switching from System A to System B requires a 24-hour cooldown since the last switch. The cooldown is on *switching*, not on the first dock — a brand-new player can dock immediately on first use.

An undocked player can still run every Phase 0–2 command; they simply don't receive citizen-tier benefits anywhere.

### 5.2 What citizenship grants

1. **Flare priority.** Citizens see Beacon Flares in their docked system with 0s delay. Same-Sector neighbors (citizens of other systems in the same Discord guild) see the flare 30–60s later.
2. **Service buffs.** Each upgrade category installed on the home Lighthouse adds one citizen-side service benefit (cheaper repairs / faster training / etc.; full mapping in §11). Effects compose multiplicatively. A bare Lighthouse provides a 1% baseline floor.
3. **Donation scoreboard credit + patronage multiplier.** Anyone can donate to any Lighthouse. Citizen donations to the home Lighthouse get a +5% effective contribution multiplier and count toward home System Pride and the public top-contributors scoreboard. Outsider donations land in the goal but don't generate home Pride and don't get the patronage multiplier.

### 5.3 Warden coupling

A Warden is automatically docked at their seat the moment they claim it. They cannot `/dock` elsewhere without first abdicating. This resolves the "where do my buffs come from" question cleanly: always the seat they hold.

A Warden holding multiple seats (the setting permits it) picks which one is their primary dock; non-primary seats still earn tribute but don't drive citizen-buff resolution for the Warden personally. Switching primary among held seats has no cooldown.

### 5.4 Forward-compat

Citizenship is stored as a `citizenships(player_id, system_id, docked_at, switched_at, ended_at)` row, not a column on `User`. Phase 4+ alliance Wardenship will let an alliance hold a system; alliance citizenship inherits via the alliance's member roster — same `citizenships` table, with `player_id` resolved through alliance membership.

### 5.5 What citizenship does NOT do

- Does not gate any Phase 0–2 command. Visitors run jobs, expeditions, and hangar ops in any system.
- Does not gate donation, flare participation, or expedition entry. The benefits are all *priority and bonuses*, never gates.

---

## 6. The Lighthouse object

### 6.1 One per system, created at activation

When `/system enable` runs (Phase 0), 3b extends the flow to also create a `Lighthouse` row tied to that system. The Lighthouse's `band` is rolled at creation with weighted distribution: ~70% rim, ~25% middle, ~5% inner. Band is permanent.

### 6.2 State machine

Two states used in 3b; one stubbed for 3e.

- `active` — the default and only state 3b transitions into. Anchors the system, accepts commands, can be claimed, can flare.
- `contested` — column exists; 3b never transitions into it. Phase 3e villain attacks set this state. Citizen buffs and flares pause while contested.
- `dormant` — reserved for future deep-rim systems that need an expedition to activate. Not used in MVP.

### 6.3 Ownership and lapse state

Orthogonal to the state machine:

- `warden_id` — nullable UUID. Null = unclaimed. Set when a claim contract resolves successfully; unset on abdication.
- `lapse_warning_at` — nullable timestamp. Set when the inactivity scheduler fires the warning at 14 days. Cleared by Warden activity.
- `vacation_until` — nullable timestamp. Set by `/lighthouse vacation start`; suppresses lapse during the window.

### 6.4 Slot allocation by band

The five upgrade categories (Q6) are gated by band so smaller Lighthouses still feel complete:

| Band | Slots | Categories available |
|---|---|---|
| Rim | 3 | Fog Clearance, Weather Damping, Defense |
| Middle | 5 | All five (Fog, Weather, Defense, Network, Wildcard) |
| Inner | 7 | All five + 2 extra Wildcard slots |

The rim's narrative justification: "the smaller Lighthouses retained only the survival spires intact through the millennia." Mechanical justification: rim Wardens can fully *complete* their Lighthouse and feel mastery; inner-band Wardens have more variety but more grind.

### 6.5 What other commands depend on Lighthouse state

- Citizenship buffs read from the Lighthouse's installed upgrades.
- Beacon Flares fire only on `active` Lighthouses (not contested or dormant).
- Donation goals are scoped per-Lighthouse.
- Tribute accrual computes against the Lighthouse's installed-upgrade level.

---

## 7. Wardenship claim

### 7.1 Discovery surface (MVP)

3b ships `/lighthouse list` — paginated list of unclaimed Lighthouses across systems the player can access (i.e., systems in any Sector the player is a member of). Each row shows: system name, band, star type, feature count, and the contract's estimated difficulty. When the Authority job board lands in Phase 3e, claim contracts surface there too; both entry points coexist.

### 7.2 Contract structure

A single Authority-vetted parameterized Phase-2b expedition. Contract template: `template_id = "claim_lighthouse"` with parameters `target_system_id`, `target_band`, `difficulty`. Phase 2b's engine handles execution; Phase 2c provides narrative. No new expedition infrastructure.

### 7.3 Difficulty formula (placeholder)

```
base = {rim: 10, middle: 25, inner: 50}[band]
difficulty = base
           + 5 * len(features)
           + 5  if star_type in {binary, trinary}
           + 10 if star_color == "exotic"
```

Computed once at contract creation; fixed for the run.

### 7.4 Resolution and outcomes

Standard Phase-2b stat resolver — player's build + assigned crew vs. difficulty.

- **Pass:** player becomes Warden (sets `warden_id`), auto-docks at the system, 7-day claim cooldown starts.
- **Fail:** player consumes the 7-day claim cooldown, takes no fleet/crew damage, receives a small consolation payout (5% of expected reward) "for the attempt" per Authority custom.

### 7.5 Per-player cooldown

7 days between any two claim attempts (pass or fail). Cooldown is on the *player*, not on the system. Multiple players can attempt the same Lighthouse on overlapping schedules without contention (no contested-window mechanic in 3b — that's Phase 4 PvP). Whoever passes first becomes Warden; subsequent attempts on a now-claimed Lighthouse are blocked at the precondition check.

### 7.6 Preconditions

`/lighthouse claim` precheck:

- Player has an active Build with all six slots filled (Phase 1 ship).
- Player has completed ≥ 3 expeditions of any kind (basic competence gate).
- Player is not currently in claim cooldown.
- Target Lighthouse is `active` (not contested) and unclaimed.
- Player is not already the Warden of the target system.

### 7.7 Auto-dock on win

If the player was docked elsewhere before the claim, the dock switches automatically on win — no 24-hour cooldown applied (the claim itself is the qualifying event). The previous citizenship row is closed; a new row opens at the won system.

### 7.8 Multi-system Wardenship

Permitted. A player can hold multiple seats simultaneously. Each seat runs its own tribute ledger contributions, donation goals, lapse timer, and vacation state. The player picks one as their primary dock; non-primary seats still earn tribute but don't drive the Warden's personal citizen-buff resolution. Switching primary among held seats has no cooldown.

---

## 8. Donation flow

### 8.1 Posting goals

`/lighthouse upgrade post <upgrade_id>` — the Warden picks an upgrade from the catalog (filtered to their Lighthouse's open slots and current per-slot progress). The system creates an `UpgradeGoal` row with required line items pulled from the catalog entry, and publishes a public goal embed to the system channel. The embed is the canonical donation surface.

Goal embed contents:

- Upgrade name, category, target slot, tier
- Required line items (e.g., 5,000 credits + 30 alloy parts)
- Progress bar per line item, top 3 contributors, time since posted
- Buttons: `Donate Credits`, `Donate Parts`, with quick-amount presets (1k / 5k / "match remaining") and a modal for custom amounts
- "Cancel goal" button visible only to the Warden

### 8.2 Concurrency

Up to 3 active goals per Lighthouse at a time, across slots. Limit prevents donor attention from fragmenting and keeps each goal visible in channel scrollback. Network upgrade tier raises the cap (Tier I: +1, Tier II: +2). The Warden chooses which slot to push next when slots are open.

### 8.3 Donating

A donation decrements the donor's stockpile and increments the goal's progress. Each donation writes a `donation_ledger` row.

Eligibility: anyone can donate to any goal — citizen or visitor, from any system they can see. **Citizens of the home system receive a +5% patronage multiplier** on effective contribution to their home Lighthouse's goals (e.g., 1,000 credits donated counts as 1,050 against the goal). Encourages docking and rewards loyalty without gating outsider participation.

### 8.4 System Pride from donations

(Full mechanics in §13.)

- Donation grants Pride to the **recipient** system, scaled to the contribution amount (~1 Pride per 100 credits + 1 Pride per part).
- Donor's home system Pride is unaffected by donations to *other* systems. Donor home Pride is driven by flare wins/losses (§12).

### 8.5 Goal completion

When all line items are filled, the goal becomes "ready to install." The Warden runs `/lighthouse upgrade install <slot>` to consume the goal's accumulated resources and apply the upgrade. The completion publishes a public message naming the top 3 contributors by amount.

### 8.6 Cancellation

The Warden can cancel an active goal via the "Cancel goal" button. Refunds 75% of donated credits/parts pro-rata to donors; 25% retained as Authority filing fee. Cancellation publishes a public message to the channel so citizens see what happened (and Wardens who reset capriciously pay the social cost).

---

## 9. Upgrade catalog (stub for 3b)

Five categories × two tiers = ten upgrades. Cost numbers are placeholders for final tuning during implementation. Each upgrade has a *Warden-side* (Lighthouse-level) effect and a *citizen-side* (service buff) effect.

| Slot | Tier | Name | Cost | Warden-side | Citizen-side |
|---|---|---|---|---|---|
| Fog Clearance | I | Local Fog Damper | 5,000c + 30 parts | +1 flare/day passive cadence floor; eligible for standard prize tier | +2% expedition success |
| Fog Clearance | II | Resonance Damper | 15,000c + 80 parts | +2 flare/day cadence; eligible for premium prize tier | +5% expedition success |
| Weather Damping | I | Storm Buffer | 5,000c + 30 parts | -10% Lighthouse damage during 3e events | -5% repair cost |
| Weather Damping | II | Atmospheric Stabilizer | 15,000c + 80 parts | -25% Lighthouse damage | -15% repair cost |
| Defense | I | Skirmish Array | 5,000c + 30 parts | +5% defense roll vs villain attacks (3e) | -3% ambush rate on expeditions |
| Defense | II | Bastion Plating | 15,000c + 80 parts | +15% defense roll | -10% ambush rate |
| Network | I | Beacon Resonator | 5,000c + 30 parts | +1 concurrent goal slot (4 total) | -10% expedition turnaround |
| Network | II | Phase Lock | 15,000c + 80 parts | +2 concurrent goal slots (5 total) AND +10% tribute passive multiplier | -20% expedition turnaround |
| Wildcard | I | Auxiliary Spire | 7,500c + 50 parts | Warden picks one at install: +tribute drip / +signal-pulse window / +1 concurrent goal | (none — Warden-only effect) |
| Wildcard | II | Master Spire | 25,000c + 120 parts | Warden picks one larger effect from a 5-option pool | (none — Warden-only effect) |

**Notes:**

- Network and Wildcard categories are middle/inner only (locked from §6 — rim band has 3 slots: Fog, Weather, Defense).
- Wildcard upgrades are Warden-flavor levers (no citizen side); Wardens optimize them around their playstyle. Standard 4 categories all have citizen-side effects, so citizens always benefit from upgrade investment in the survival categories.
- Tier-replacement: installing II swaps out I, doesn't co-exist. Removing an upgrade refunds 25% of the cost (consistent with the cancellation rate in §8). Removal cost prevents Wardens from constantly swapping.
- Tier III, exotic-slot upgrades, and category extensions land in Phase 3e along with the resource categories that fund them.

**Catalog file location:** `data/upgrades/catalog.yaml` — same pattern as the expedition templates from Phase 2b, so author-readable and dev-editable.

---

## 10. Tribute

The Warden's earn-side currency. Hybrid: passive base scaled to upgrades, plus a small cut of citizen activity in-system. Single ledger per Warden across all held seats.

### 10.1 Sources

**Passive drip.** Daily accrual computed from installed upgrades. Per-day formula (placeholder):

```
passive_per_day = sum over slots of (tier * band_multiplier)
band_multiplier = {rim: 50, middle: 75, inner: 100}
tier = 0 (empty), 1 (Tier I installed), 2 (Tier II installed)
```

Worked examples:

- Empty rim Lighthouse: 0/day
- Fully upgraded rim (3 slots × Tier II): 300/day
- Fully upgraded inner (7 × Tier II): 1,400/day

Roughly a 5× range from a maxed-rim to a maxed-inner — meaningful band differentiation without making rim Wardens feel pointless.

**Activity cut.** 3% of citizen credit-equivalent rewards earned in-system flow to the Warden's tribute ledger. Sources counted: expedition payouts, job payouts, flare wins. Donations are *not* counted (donations are citizen-driven and shouldn't double-tax the donor).

A moderately active rim system (≈5 citizens earning ~500 credits/day) yields ≈75 tribute/day from activity, ≈25% of the passive base for a fully-upgraded rim Lighthouse. A very active inner-band system can double its passive — making active stewardship matter without dwarfing the seat itself.

### 10.2 Multi-system Wardens

One ledger per Warden, combined across seats. Tribute earned from System A is freely spendable on System B. Simple, prevents accidental siloing.

### 10.3 Spending

| Verb | Cost (placeholder) | Cooldown |
|---|---|---|
| Salvage Drift flare (cheap) | 100 tribute | 4h |
| Signal Pulse flare (standard) | 250 tribute | 8h |
| Premium flare (large prize) | 500–1,000 tribute | 24h |
| Vacation declare | 10 tribute / day, max 14 days | n/a |
| Panic-mode lapse defer | 50 tribute / +1 day, max +7 days | n/a |
| Convert to credits (unfavorable) | 5 tribute → 1 credit, max 1,000 credits / day | n/a |

The conversion cap exists so tribute isn't an infinite credit pump. The unfavorable rate is on purpose: tribute primarily fuels Warden-flavor verbs, not personal income.

### 10.4 Display surfaces

- `/lighthouse status` — shows current balance, today's accrual breakdown (passive vs activity per seat), and a recent spending summary.
- `/lighthouse ledger` — paginated transaction history, last N entries.

---

## 11. Citizen buffs

Service buffs only (no raw power buffs). Each upgrade category in the standard four (Fog / Weather / Defense / Network) drives one citizen-facing service benefit. Wildcard category has no citizen-side; it's a Warden-flavor lever.

### 11.1 Mapping

| Category | Citizen benefit | Scales with |
|---|---|---|
| Fog Clearance | Expedition success modifier | Tier I: +2%, Tier II: +5% |
| Weather Damping | Repair cost modifier | Tier I: -5%, Tier II: -15% |
| Defense | Ambush/mugging rate during expeditions | Tier I: -3%, Tier II: -10% |
| Network | Expedition / job turnaround time | Tier I: -10%, Tier II: -20% |

Effects compose multiplicatively across categories.

### 11.2 Resolution scope: travel with the player

Citizen buffs are tied to the player's **docked home Lighthouse**, not to the system where the action takes place. A System A citizen running an expedition out of System B gets System A's home buffs. The fiction: your home Lighthouse is your support infrastructure — repair docks, trainers, navigation hints. It supports you wherever you fly.

*Why not localize to the action's system?* That would create dead zones: visit a foreign system → no buffs → punished for travel. Travel-with-them keeps citizens valuable everywhere they fly while still tying benefits to a home.

*Wardens.* Use the Lighthouse of their primary dock for citizen buffs. Non-primary seats they hold contribute to their tribute ledger but don't drive their own citizen-buff resolution.

### 11.3 Baseline floor

A docked player whose home Lighthouse has *no* upgrades still receives a 1% benefit on each of the four affected stats (success / repair / ambush / turnaround). The floor exists so docking always grants something. Undocked players receive 0 buff.

### 11.4 Visitor handling

| Acting player | Acting in | Buffs applied |
|---|---|---|
| Citizen of A | System A | A's Lighthouse (home benefit) |
| Citizen of A | System B | A's Lighthouse (travels with them) |
| Undocked player | Anywhere | None |
| Warden of A (primary) | Anywhere | A's Lighthouse |

### 11.5 Note on flare priority vs service buffs

These are scoped differently and worth distinguishing in the docs and code:

- **Flare priority** is tied to the *system firing the flare*. Citizens of that system get 0s; same-Sector neighbors are delayed 30–60s.
- **Service buffs** are tied to the *player's docked home*. They travel with the player.

The two scopes coexist cleanly: a System A citizen visiting System B sees System B flares with delay (flare priority is local) but still gets System A's repair discount on damage they take in System B (buffs travel).

---

## 12. Beacon Flares (Slice X)

Public timer-based events that fire in a system's channel. Citizens compete for them; same-Sector neighbors can snipe with delay. Two archetypes ship in 3b; three more deferred to 3e.

### 12.1 Audience tiers

3b has two visibility tiers — both within a single Sector. Cross-Sector "universe-wide" tier is deferred to 3e.

- **Citizens of the firing system**: 0s delay
- **Same-Sector neighbors** (citizens of other systems in the same Discord guild): roll(30, 60) seconds delay, randomized per spawn so outsiders can't perfectly precompute the window

### 12.2 Anatomy

A `flares` row carries:

- `system_id` — where it fires
- `archetype` — `salvage_drift` | `signal_pulse`
- `prize_tier` — `small` | `standard` | `premium`
- `prize_pool` — JSONB (credits, parts, contribution_credit, custom fields)
- `triggered_by` — null (passive) or Warden's `player_id` (called)
- `spawned_at` — when first visible to citizens
- `expires_at` — global window close
- `state` — `open` | `won` | `expired`
- `winners` — JSONB array (single entry for Salvage Drift, multi for Signal Pulse)

Clicks recorded in a separate `flare_clicks(flare_id, player_id, clicked_at)` table; the database's transaction order resolves races.

### 12.3 Lifecycle

1. Spawn (passive scheduler or Warden-called).
2. Citizens of the system see the flare embed at `spawned_at` (0s delay).
3. Same-Sector neighbors see it at `spawned_at + roll(30, 60)s`.
4. Players click; resolution depends on archetype.
5. At `expires_at`, unclaimed flares mark `expired`. The channel post is updated to show outcome.

### 12.4 Salvage Drift archetype

Single winner, speed-based. First valid click within the clicker's visibility window wins the entire prize pool. 5-minute outer window. Public announcement: "Captain Sixgun caught the drift in Veyra Hesper." Prize sample varies by tier (see §12.7).

### 12.5 Signal Pulse archetype

Multi-winner, coalesce-style. The first click triggers a 30-second coalesce window during which anyone whose visibility window has opened can join the catch. At window close, the prize pool splits among joiners. Sweet spot: 3–7 winners. 10-minute outer window for the trigger; if nobody clicks, the flare expires unfired. Prize pools larger than Salvage Drift, designed to split.

### 12.6 Spawn cadence

Flares fire **always**, including on bare unclaimed Lighthouses. Upgrades amplify cadence and prize tier; they do not gate the mechanic.

| State | Base interval (randomized) | Approx flares/day |
|---|---|---|
| Unclaimed Lighthouse | every 2–4 hours | 6–12 |
| Active, no Fog upgrade | every 90 min – 3 hrs | 8–16 |
| Fog Clearance Tier I | every 60–120 min | 12–24 |
| Fog Clearance Tier II | every 30–60 min | 24–48 |

Plus Warden-called flares stack on top of passive cadence on demand.

**Channel noise mitigation.**

- Wardens can configure cadence within their tier's bounds: `low / normal / high`. Default normal. Unclaimed Lighthouses default to normal at the bare-tier rate.
- **Auto-throttle on silent channels.** If the system channel has had no human messages in >12h, next-flare delay extends. After >24h silence, passive cadence pauses entirely until any human message in the channel re-activates it. Avoids spamming dead channels and self-recovers.
- Warden-called flares ignore auto-throttle (deliberate Warden action overrides silence).
- Maximum 1 active flare per system at a time. Warden-called flares queue if a passive one is active. Passive cadence is suppressed while a Warden-called flare is active or queued.

### 12.7 Prize tiers (placeholder values)

Prize pools scale by Lighthouse upgrade level and by `prize_tier`. Unclaimed Lighthouses fire often but with smaller prizes; upgraded Lighthouses fire more often *and* with bigger prizes — total daily yield from a system scales up roughly 10× from bare-rim to maxed-rim.

| State | Salvage Drift sample | Signal Pulse pool (split among 3–7) |
|---|---|---|
| Unclaimed / bare | 100–500c, OR 2–10 parts, OR 50–100 contribution credit | 300–900c or 6–20 parts |
| Active, no Fog | 150–600c, OR 3–12 parts | 450–1,200c or 9–25 parts |
| Fog Tier I | 200–800c, OR 5–15 parts | 600–1,800c or 12–35 parts |
| Fog Tier II (premium-eligible) | 300–1,200c, OR 8–25 parts | 900–2,800c or 18–60 parts |
| Warden-called premium | 500–2,000c (or equivalent) | 1,500–5,000c or scaled parts |

Final tuning during implementation.

### 12.8 Reward delivery

- `credits` → player wallet
- `parts` → player inventory
- `contribution_credit` → applies as a free donation to the *winner's home Warden's* active goal (no stockpile decrement). The reward gives the citizen an at-a-distance way to support home without spending personal resources.
- Other reward shapes for premium tier deferred to 3e.

### 12.9 Out-of-scope flare archetypes (deferred to 3e)

- Universe-wide flare tier (Authority frequency), cross-Sector stealing
- Rare-prize variants (universe-wide banner alerts)
- Poach Opportunity (skim Warden tribute) — design with the rest of the stealing surface
- Bounty Mark (accepts Phase-2b expedition contract) — needs villain catalog
- Cult Whisper (dossier leads tied to over-there minds) — needs cult catalog

---

## 13. System Pride

Per-system score visible in `/system info`. Drives social rivalry between systems and gives Wardens a public legibility for "is my system thriving."

### 13.1 Sources

(Placeholder weights; final tuning in spec.)

| Event | Pride change |
|---|---|
| Home citizen donates to home Lighthouse | +1 per 100 credits + 1 per part |
| Home citizen wins flare in home system | +5 |
| Outsider wins flare in this system | -3 to home, +2 to outsider's home |
| Upgrade goal completed (any) | +20 to recipient system |
| Auto-abdication (Warden lapsed past grace) | -50 to system |
| Goal cancelled by Warden | -10 |
| Vacation declared | no change (planning is rewarded by silence) |

### 13.2 Decay

1% of current Pride decays per day. Decay floor is 0 — Pride doesn't go negative. Old wins fade so a system has to keep earning.

### 13.3 Visibility

`/system info <system>` shows:

- Current Pride score
- Top 3 donor-contributors this week (citizens of the system)
- "Recent" panel: last 5 flare wins/losses with timestamps and (for losses) which other system's citizen took it
- Per-Sector neighbor scoreboard: "Stolen from / stolen by" counters per neighboring system this week

### 13.4 Why it matters in 3b

Pride is the social pressure layer. Citizens see when their home is being raided by a same-Sector neighbor; they react. Wardens see a public legibility of their performance — a high-Pride Warden is clearly thriving, a falling-Pride Warden is clearly slipping. The number itself doesn't mechanically gate anything in 3b — it's purely social information — but it's the surface that makes flare warfare *legible* and therefore fun.

### 13.5 Future hooks (informational only — not built in 3b)

- Pride thresholds may unlock cosmetic flair (system rename privileges, channel banners).
- Pride may modify villain attack frequency (3e — high-Pride systems attract more attention).
- Pride may modify alliance Warden eligibility (Phase 4+).

### 13.6 Storage

Stored as `lighthouses.pride_score` (int, default 0) — Pride is a property of the Lighthouse-system pair, and the Lighthouse already has a 1:1 relationship with System. Saves a join and a row per system.

---

## 14. Inactivity lapse + Vacation verb

The Warden's commitment mechanism. Two separate paths handle planned vs unplanned absence; both are publicly visible so citizens always know whether the seat is being stewarded.

### 14.1 Activity definition

Any of the following resets the Warden's lapse timer:

- Any `/lighthouse` or `/system` command issued by the Warden
- Calling a flare (`/lighthouse flare call`)
- Posting, installing, or cancelling an upgrade goal
- Running an expedition or job in any of the systems they hold

Casual play touches at least one of these per session, so engaged Wardens never approach lapse.

### 14.2 Lapse window — default path (no vacation declared)

1. **Day 0–13:** No effect. Activity resets the clock.
2. **Day 14:** Public warning post in the system channel ("Warden Sixgun has not been seen in 14 days. Lighthouse abdicates in 7 days unless a Warden activity is registered.") + DM to the Warden.
3. **Day 15–20:** Grace period. Any Warden activity (per the list above) clears the warning and resets the timer.
4. **Day 21:** Auto-abdication. `warden_id` cleared; Lighthouse becomes unclaimed; system Pride drops by 50; channel post announces the seat is open.

### 14.3 Panic-mode tribute defer

Available only after the warning has fired (day 14+). Warden can spend tribute at a penalty rate to extend the grace period day-by-day:

- 50 tribute → +1 day of grace
- Max +7 days of extension (so latest possible auto-abdication is day 28)
- Penalty rate is intentional: this is the "I forgot to plan" cost, not a vacation

### 14.4 Vacation verb (planned absence)

`/lighthouse vacation start <days>` — declares a planned absence up to 14 days. Pays tribute upfront at a *favorable* rate:

- 10 tribute per day
- Caps at 14 days per declaration
- Cannot re-declare without 14 days of normal activity in between (no infinite vacationing)

While vacation is active:

- Lapse timer pauses
- Warning post is suppressed
- `/system info` shows "Warden on declared vacation — returns YYYY-MM-DD"
- All other Warden mechanics continue (flares can fire passively, tribute accrues, donations come in, citizens still benefit)

`/lighthouse vacation end` — return early. No refund of pre-paid tribute (the planning had value); lapse timer resumes.

### 14.5 Why dual rates

The 10/day vacation rate vs. 50/day panic rate is the social contract: communicate with your citizens and pay 5× less. Wardens who plan are rewarded; Wardens who ghost pay the cost.

### 14.6 Abdication consequences

- `warden_id` cleared on the Lighthouse.
- All active upgrade goals cancelled with full refunds (no 25% penalty — Authority custom for involuntary abdication).
- Tribute ledger persists in the player's account (still spendable on remaining seats they hold, or convertible).
- System Pride drops 50.
- The previous Warden enters a 14-day cooldown before they can attempt to claim *any* Lighthouse (penalty for failing the post; doubled vs the per-player claim cooldown).

---

## 15. Data model

### 15.1 New tables

```
system_planets
├── system_id (FK → systems.channel_id, PK part)
├── slot_index (PK part)
├── name (str)
├── planet_type (enum)
├── size (enum)
├── richness (enum)
└── descriptor (str)

system_features
├── system_id (FK)
├── slot_index (PK part with system_id)
├── name (str)
├── feature_type (enum)
└── descriptor (str)

lighthouses
├── id (PK)
├── system_id (FK, unique)
├── band (enum: rim | middle | inner)
├── state (enum: active | contested | dormant)
├── warden_id (FK → users, nullable)
├── lapse_warning_at (timestamp, nullable)
├── vacation_until (timestamp, nullable)
├── pride_score (int, default 0)
└── created_at

lighthouse_upgrades
├── lighthouse_id (FK, PK part)
├── slot_category (enum, PK part — fog/weather/defense/network/wildcard)
├── slot_subindex (int, PK part — for inner-band's extra wildcards: 0/1/2)
├── installed_upgrade_id (str, nullable — refs catalog.yaml)
├── tier (int)
├── installed_at
└── wildcard_chosen_effect (str, nullable)

citizenships
├── id (PK)
├── player_id (FK → users)
├── system_id (FK → systems)
├── docked_at
├── switched_at (timestamp, last switch)
└── ended_at (nullable; closes the row when player switches)

upgrade_goals
├── id (PK)
├── lighthouse_id (FK)
├── slot_category (enum)
├── upgrade_id (str — refs catalog.yaml)
├── tier (int)
├── required_credits, required_parts (int)
├── progress_credits, progress_parts (int)
├── posted_at, completed_at, cancelled_at (timestamps)
└── status (enum: open | filled | installed | cancelled)

donation_ledger
├── id (PK)
├── player_id (FK)
├── goal_id (FK → upgrade_goals)
├── system_id (FK — denormalized for queries)
├── credits (int)
├── parts (int)
├── effective_credits (int — after patronage multiplier)
├── refunded (bool, default false)
└── donated_at

tribute_ledger
├── id (PK)
├── warden_id (FK)
├── source_system_id (FK, nullable for non-system sources)
├── source_type (enum: passive | activity_cut | flare_call_cost | vacation_cost | panic_defer_cost | conversion | adjustment)
├── amount (int — signed; positive = credit, negative = spend)
└── occurred_at

flares
├── id (PK)
├── system_id (FK)
├── archetype (enum: salvage_drift | signal_pulse)
├── prize_tier (enum: small | standard | premium)
├── prize_pool (JSONB)
├── triggered_by (FK → users, nullable; null = passive)
├── spawned_at, expires_at
├── state (enum: open | won | expired)
└── winners (JSONB array)

flare_clicks
├── flare_id (FK, PK part)
├── player_id (FK, PK part)
└── clicked_at (timestamp)

claim_attempts
├── id (PK)
├── player_id (FK)
├── target_system_id (FK)
├── difficulty (int)
├── started_at, resolved_at
├── outcome (enum: pass | fail)
└── expedition_id (FK → expeditions, the underlying Phase-2b run)
```

### 15.2 Schema extensions to existing tables

```
systems
├── star_type (enum) — NEW
├── star_color (enum) — NEW
├── star_age (enum) — NEW
└── config[generator_seed] (JSONB key) — NEW
```

### 15.3 Migrations

Single Alembic migration adds all of the above. Existing systems get a Lighthouse row and procgen pass via a backfill data migration (idempotent — running twice doesn't double-roll). Existing systems' band is rolled at backfill using the same weighted distribution. The backfill also enqueues the LLM narrative pass for each existing system; until the LLM job lands, `flavor_text` shows a placeholder paragraph.

---

## 16. Commands & UI surface

Per the codebase's preference for interactive views over atomic slash commands, most Warden verbs live as buttons inside a tabbed view rather than as separate slash commands.

### 16.1 Top-level slash commands

| Command | Audience | Purpose |
|---|---|---|
| `/dock <system>` | All | Set or switch citizenship |
| `/lighthouse [system]` | All | Open the main interactive Lighthouse view (defaults to current channel's system) |
| `/lighthouse list` | All | Paginated discovery view of unclaimed Lighthouses |
| `/lighthouse claim <system>` | Eligible players | Direct claim entry; equivalent to the "Claim" button in `/lighthouse list` |
| `/system info [system]` | All | System character, planets, features, Pride, top contributors |

Autocomplete on `<system>` arguments resolves systems the player can access (citizen of, Warden of, or member of the Sector).

### 16.2 `/lighthouse [system]` interactive view — tab structure

Single message with a `select` to switch tabs and per-tab buttons:

| Tab | Visible to | Contents |
|---|---|---|
| Status | All | Band, state, Warden name, slot occupancy, current Pride, Warden's vacation status; Warden button: `Abdicate seat` (confirmation modal) |
| Upgrades | All; Warden has extra buttons | Active goals (with progress + donate buttons for any user); empty/installed slots; Warden buttons: `Post goal`, `Install`, `Cancel goal` |
| Flares | All; Warden has extra buttons | Recent flares + outcomes; current active flare (if any) with click button; Warden buttons: `Call flare` (sub-modal: archetype, prize tier) |
| Tribute | Warden only | Current balance, today's accrual breakdown, recent transactions; buttons: `Convert to credits`, `View full ledger` |
| Vacation | Warden only | Vacation state, controls: `Declare vacation` (modal: days), `End vacation early` |

Voluntary abdication via the Status tab triggers the same consequences as auto-abdication (§14.6) — full goal refunds, Pride drop, the previous Warden's 14-day claim cooldown — but the Warden chooses the timing. Required when a Warden wants to dock at a different system without first lapsing.

Note on terminology: this spec uses shorthand like "/lighthouse upgrade post" or "/lighthouse vacation start" in body text to name verb actions clearly. Those are not separate slash commands — they're button actions inside the relevant tab of `/lighthouse [system]`. Only the five commands in §16.1 are real slash commands.

Persistent dispatch via `DynamicItem` so buttons survive bot restart (consistent with the Hangar pattern from PR #36).

### 16.3 `/lighthouse list` paginated view

Embed lists 5 unclaimed Lighthouses per page with band, star type, feature count, and contract difficulty estimate. Each row has a `Claim` button that opens a confirmation modal (crew/build choice) and runs the claim flow.

### 16.4 Public channel views (auto-posted, not user-invoked)

- **Goal embed** — posted when Warden creates an upgrade goal; updated as donations land. Donate buttons (citizen + visitor); cancel button visible only to Warden.
- **Flare embed** — posted when a flare spawns; click-to-claim button; updated to outcome when resolved/expired.
- **Lapse-warning post** — posted at day-14 of inactivity; updated/replaced by abdication post at day-21.
- **Vacation post** — posted when Warden declares vacation; pinned for the duration.

---

## 17. Files likely touched

### 17.1 Code

- `db/models.py` — new tables (lighthouses, upgrade_goals, donation_ledger, tribute_ledger, flares, flare_clicks, citizenships, system_planets, system_features, claim_attempts, lighthouse_upgrades), extended System
- `db/migrations/versions/2026_05_03_add_lighthouses.py` — single Alembic migration with backfill data migration for existing systems
- `engine/lighthouse_engine.py` — claim resolution, upgrade install, tribute accrual + spending, lapse state machine
- `engine/system_generator.py` — deterministic procgen, LLM seed pass dispatch
- `engine/flare_engine.py` — flare lifecycle, click resolution, archetype handlers, prize delivery
- `engine/expedition_template.py` — register `claim_lighthouse` template
- `engine/stat_resolver.py` — extend to apply citizen service buffs from Lighthouse upgrades
- `bot/cogs/lighthouse.py` — slash commands + main interactive view registration
- `bot/cogs/dock.py` — `/dock` command
- `bot/cogs/system.py` — extend `/system info`
- `bot/views/lighthouse_view.py` — tabbed interactive view + `DynamicItem` button definitions
- `bot/views/lighthouse_list_view.py` — paginated unclaimed list
- `bot/views/upgrade_goal_view.py` — public goal embed
- `bot/views/flare_view.py` — public flare embed
- `scheduler/jobs/flare_spawner.py` — passive flare spawning per system, with channel-silence auto-throttle
- `scheduler/jobs/lapse_check.py` — daily lapse warning + grace + auto-abdication
- `scheduler/jobs/tribute_drip.py` — daily passive tribute accrual
- `scheduler/jobs/pride_decay.py` — daily Pride 1% decay
- `bot/cogs/expeditions.py` — outcome handler for `claim_lighthouse` template (calls `lighthouse_engine.complete_claim`)

### 17.2 Data

- `data/upgrades/catalog.yaml` — 10-upgrade stub
- `data/expeditions/claim_lighthouse.yaml` — claim contract template (Phase 2b shape)
- `data/system/star_types.yaml` — star type combinations + planet/feature distribution biases
- `data/system/planet_types.yaml` — 7 planet types, descriptor templates
- `data/system/feature_types.yaml` — 5 feature types, named templates

### 17.3 Reuse pointers

- Phase 2a scheduler — all spawning, lapse, drip, decay jobs use the durable scheduler.
- Phase 2b expedition engine — claim contracts are parameterized expeditions, no new infrastructure.
- Phase 2c LLM pipeline — system narrative seed pass uses the existing author loop.
- `DynamicItem` pattern from Hangar (PR #36) — interactive view buttons survive bot restart.

---

## 18. Out of scope (deferred)

### Phase 3c (Resource Loop)
- Resource extraction loop, planet/feature exploitation gameplay
- Sub-claims on planets/features (time-limited exclusive ownership)

### Phase 3d (Home Base)
- `/base` unified hub view consolidating `/hangar`, `/fleet`, `/training`, `/research`, `/stations`, `/expedition`, `/lighthouse` into a single navigation surface

### Phase 3e (Events: Weather + Channel + Villains)
- Universe-wide flare tier (Authority frequency), cross-Sector stealing
- Rare-prize flare variants (universe-wide banner alerts)
- Poach Opportunity flare archetype
- Bounty Mark flare archetype (accepts Phase-2b expedition contract)
- Cult Whisper flare archetype (dossier leads tied to over-there minds)
- Tier III upgrades and exotic-slot upgrades
- Named villains and villain takeovers (transitions Lighthouse to `contested`)
- Weather events affecting yields, expedition odds, visibility
- Channel events (timed multi-player engagement)
- Authority job board UI consolidation (claims surface there in addition to `/lighthouse list`)

### Phase 4 (Combat depth + PvP)
- Contested claim windows (multi-player race for the seat)
- Warden-vs-Warden challenges
- Alliance/guild Wardenship; alliance citizenship rosters
- Pride threshold cosmetic unlocks (system rename privileges, channel banners)

---

## 19. Verification

Acceptance criteria for "3b is correctly implemented." Each is testable.

### 19.1 System character
- A new system created via `/system enable` has a deterministic star type, planet set, and feature set given its `generator_seed`. Re-running generation with the same seed produces identical structural output.
- An activated system gets an LLM-generated narrative paragraph stored in `flavor_text` within ~10s; LLM job failure stores a placeholder and retries.

### 19.2 Citizenship
- `/dock` sets citizenship; switching A→B is blocked by 24h cooldown since last switch.
- A citizen donating to home gets +5% patronage multiplier on effective contribution.
- A citizen sees flares with 0s delay; a same-Sector neighbor sees the same flare 30–60s later.

### 19.3 Claim
- `/lighthouse list` returns unclaimed Lighthouses sorted by accessibility.
- `/lighthouse claim <system>` runs as a Phase-2b expedition; success transitions `warden_id`, sets the new Warden's dock, starts a 7-day claim cooldown, and posts a public announcement.
- Failure consumes the cooldown, pays 5% consolation, applies no fleet damage.
- Per-player 7-day claim cooldown enforced across all attempts (pass or fail).

### 19.4 Donations and upgrades
- Posted upgrade goal renders a public embed with progress bars and donate buttons.
- Citizen donations grant Pride to the recipient system; outsider donations don't grant donor's home Pride.
- Goal completion installs the upgrade, applies the Warden-side and citizen-side effects, and posts top-3-contributors message.
- Cancellation refunds 75% pro-rata to donors.

### 19.5 Tribute
- Passive accrues per the formula in §10, computed from installed upgrades and band.
- Activity cut accrues at 3% of citizen credit-equivalent rewards in-system.
- Multi-system Wardens see one combined ledger.
- `/lighthouse status` displays correct breakdown.

### 19.6 Flares
- Bare unclaimed Lighthouse fires 6–12 passive flares/day (with channel-silence auto-throttle pausing after 24h silence).
- Fully-upgraded Fog Tier II Lighthouse fires 24–48 passive flares/day.
- Salvage Drift resolves to a single winner by first-click within visibility tier.
- Signal Pulse resolves to N joiners within 30s of the trigger click.
- Warden-called flare deducts tribute, fires immediately, queues if a passive is active.
- Channel-silence auto-throttle kicks in at >12h silence (extends interval) and pauses entirely at >24h.

### 19.7 Lapse and vacation
- 14-day inactivity triggers public warning + DM.
- 21-day inactivity auto-abdicates; refunds active goals; drops Pride by 50.
- Vacation defers warning at 10 tribute/day; cannot re-declare without 14d normal activity gap.
- Panic-mode tribute defer at 50/day max +7d, available only after warning.

### 19.8 Pride
- Citizen wins flare in home → +5; outsider wins flare in this system → -3 to home, +2 to outsider's home.
- Pride decays 1% daily; floor at 0.
- `/system info` displays current Pride, top contributors, and per-Sector neighbor scoreboard.

### 19.9 Service buffs
- A docked citizen acting in any system applies their home Lighthouse's buff modifiers (Fog → expedition success, Weather → repair cost, Defense → ambush rate, Network → turnaround).
- Bare Lighthouse provides 1% baseline floor; undocked players get 0 buff.

### 19.10 State machine
- Lighthouse `state` correctly transitions on activation; `contested` column is writable but never set in 3b's flows.

---

## 20. Open questions / soft commitments

All numerical values in this spec are placeholders for tuning during implementation. Specifically:

- Cadence intervals, flare prize amounts, tribute rates, upgrade costs, Pride source weights, and decay rates — all subject to playtest tuning.
- Star type taxonomy specifics (final combination count) — settle in implementation.
- Wildcard upgrade option pool (3 effects for Tier I, 5 for Tier II) — author the specific effects in implementation.
- LLM prompt for narrative seed pass — author alongside content during implementation; should match the encyclopedic-yet-grounded voice of `setting.md`.
- Exact wireframe of `/lighthouse [system]` interactive view tabs — refine in implementation.
- Whether `claim_attempts` table should also track per-system attempt history for analytics (likely yes; doesn't change schema).

### Soft commitments worth flagging

- The "5 categories" of upgrades is a setting commitment (§8 of `setting.md`). New categories require a setting amendment, not just a spec change.
- The 70/25/5 band distribution is tunable; the *existence* of three bands is a setting commitment.
- The "single contract → Warden" claim flow is a 3b-MVP commitment; Phase 4 PvP can layer contested windows on top without invalidating the single-contract path.
- Citizenship as a row (not a column on `User`) is locked for forward-compat with alliance Wardenship — do not refactor to a column even if alliance support slips past Phase 4.
