# ADR-001: Rig System, Part Economy, and Car Classes

**Date:** 2026-04-06
**Status:** In Discussion
**Area:** gameplay · economy · cards

---

## Context

Currently, the game has a working part card system (7 slots: engine, transmission, tires, chassis, brakes, suspension, turbo) with pack openings, an inventory, and basic racing. Parts are minted freely through pack openings, which means print numbers on individual parts would become meaningless at scale.

We need to decide:
- How players combine parts into a complete car ("rig")
- What makes rigs unique and collectible
- How to create a healthy part economy (sinks for excess parts)
- How car classes gate race types and give players reasons to maintain multiple builds

---

## Decision

### 1. The Rig Passport (Car Title)

When a player fully equips all 7 part slots and commits to a build, the game **mints a Car Title** — a permanent, globally-sequential collectible separate from the individual parts.

The Car Title records:
- **Global serial number** — #1, #2, etc. across all rigs ever built in the game. Low serial = early adopter prestige.
- **Build snapshot** — the 7 parts (name, rarity, serial if limited print) at time of build.
- **Pedigree bonus** — a stat multiplier derived from any limited print parts used (see §2).
- **Living ownership log** — every player who has owned this rig title, with timestamps.
- **Living part-swap log** — every part change made to the rig after initial build.
- **Race record** — wins, losses, events entered.

**Parts are not destroyed.** They remain in the player's inventory conceptually, but are "locked" to the rig while it is active. Disassembling a rig recovers all parts but marks the title as **Scrapped** — it retains its history but can no longer be raced.

This means:
- Parts are a liquid market (always tradeable and reusable).
- Rigs are the prestige collectible layer — traceable, historical, unique.
- Trading a rig transfers the title (and its full history) to the new owner.

---

### 2. Limited Print Parts and Pedigree Bonuses

Most parts are **open print** — unlimited copies can be minted through normal pack openings.

A small class of parts are **limited print** — a hard global cap is baked into the card (e.g. only 50 or 100 ever exist). These are:
- Drops from Legend Crates at very low probability
- Rewards for winning events and seasonal milestones
- Never available in Junkyard or Performance packs

#### Releases and Series

Limited print parts are **not a one-time launch event**. They are released in ongoing waves — each with a theme, its own set of parts, and its own print caps. This is the primary mechanism for keeping the economy fresh and giving long-term players something new to chase.

Each release is a named **Series** or **Collection**:

| Release type | Cadence | Example |
|---|---|---|
| **Seasonal Series** | Each season (e.g. quarterly) | *Summer Inferno Collection — 7 parts, 150 prints each* |
| **Event Drop** | Tied to a race event or tournament | *Championship Finals Drop — 25 prints, tournament winners get #001–#010* |
| **Collaboration / Theme** | Occasional, irregular | *Ghost Series — one ghost-rarity limited part per slot, 50 prints each* |
| **Anniversary** | Yearly | *Year One Pack — 1st anniversary re-release of original launch parts, very low print count* |

The key intent: **low serial numbers remain meaningful without being locked to a single historical moment.** A player who joins in Season 4 can still chase a #001/50 part — it just won't be from the same series as a launch-era collector's. Both are prestigious within their context.

Each series is permanently tagged on the part card and on any Car Title that uses it:

> *Built with: Voidhowl Supercharger #007/100 · Ghost Series*
> *Nexus Sequential #032/150 · Summer Inferno*
> *Pedigree Bonus: +4.2%*

#### Pedigree Bonus Calculation

The pedigree bonus on a Car Title is calculated from:
- How many limited print parts are in the build (more = higher bonus)
- The serial number of each (lower serial = bigger individual contribution)
- Optionally, whether parts share a series (set bonus — see below)

Limited print parts exist in a separate prestige economy from open print parts. A #001/50 engine is valuable to a very specific buyer, and that remains true for every series released — the market stays active rather than peaking at launch and dying.

#### Set Bonuses

When all 7 parts in a rig come from the **same named series**, the Car Title receives a set bonus on top of the standard pedigree bonus. This is the highest tier of build prestige and gives collectors a concrete reason to complete a full series rather than mixing parts across releases.

---

### 3. Part Sinks

To prevent inventory bloat and give players reasons to spend excess parts, three sink mechanics:

#### Salvage
Discard any part for a flat currency return. Commons return very little; higher rarities scale up but always at a loss relative to market value. This is the "tidy up" mechanic — always available, no friction. The rate is intentionally slightly wasteful to preserve part value.

#### Fusion (Upgrade Ladder)
Combine **3 parts of the same slot + rarity** to receive **1 part of the same slot at the next rarity tier**. The output is a random roll within that tier — not guaranteed to be the part you want, just a better one.

```
3× Common [engine] → 1× Uncommon [engine] (random)
3× Uncommon [engine] → 1× Rare [engine] (random)
... and so on up to Legendary
```

This is the long grind mechanic. It gives players with large inventories a meaningful progression path and makes duplicates purposeful rather than dead weight.

#### Tuning
Sacrifice one part to permanently apply a stat modifier to a **different part of the same slot**. The donor part is consumed; the recipient gains a small permanent boost that is visible on its card and carries into any rig it's built into.

This lets players craft toward a specific ideal part from their pool of duplicates, and means even a common part can become interesting after heavy tuning. Tuned parts are visually distinguishable on the card (modifier deltas are already shown in `/inspect`).

---

### 4. Car Classes

Each completed rig is assigned a **class** based on the stat profile of its 7 parts combined. Class is not explicitly chosen — it emerges from the build.

Parts may have **class affinities** that nudge the calculation without hard-locking them. The player doesn't pick a class; they build toward one, and the Car Title tells them what they made.

#### Proposed Classes

| Class | Key Stat Profile | Notes |
|-------|-----------------|-------|
| `STREET` | No requirements | Open to any rig. Low stakes, low reward. Entry point. |
| `DRAG` | High power + acceleration. Handling below a ceiling. | Can't just stack everything — handling cap enforces specialisation. |
| `CIRCUIT` | Balanced handling, braking, and stability above minimums. | Rewards well-rounded builds. |
| `DRIFT` | Grip intentionally low, high torque, tuned suspension. | Counter-intuitive to build — rewarding to master. |
| `RALLY` | High durability + suspension + weather performance. | Unlocks fully once weather/condition stats are in the game. |
| `ELITE` | Meets a class requirement + minimum rig rarity tier. | Reserved for builds with genuine pedigree. May require limited print parts to qualify. |

#### Why Multiple Classes Matter

- A drag build is useless in a circuit race and vice versa — multiple rigs are genuinely necessary, not just optional.
- Limited print parts become class-specific in value (a #007/100 drift-tuned turbo is worthless to a drag racer but extremely desirable to the right buyer).
- Fusion has direction: players aren't upgrading randomly, they're chasing the stats for a target class.
- Higher-class races have higher entry costs and higher rewards, creating a natural progression ladder.

#### Open Question: Class Transparency During Assembly
Players should be able to see what class their build is trending toward before committing. A live preview during part selection ("Current build: trending DRAG — needs more braking for CIRCUIT eligibility") would make the system feel approachable rather than opaque. UX to be designed.

---

## Alternatives Considered

### A: Forge & Burn
Parts consumed on build. Rig rarity derived from parts used. Rejected because destroying parts reduces liquidity, discourages experimentation, and makes the early-game feel punishing. The Rig Passport achieves the same sense of commitment without the irreversibility.

### B: Chassis as Car Identity
The chassis card becomes the permanent rig serial. Other parts equip to it freely. Rejected as the primary model because it creates a single bottleneck (chassis rarity gates all rig creation) and doesn't cleanly separate parts from the rig's identity. Could be revisited as a flavour layer on top of the Passport system.

### D: Build Timer
Completing a rig takes hours or days. High rarity parts reduce build time. Not adopted now — the game needs to establish baseline engagement before adding time gates. **Flagged as a future consideration** once the rig system is established and the team can observe how quickly players are building.

---

## Consequences

**What this commits us to building (in rough priority order):**

1. Car Title data model — globally sequential serial, snapshot at mint, ownership log, part-swap log, race record
2. Rig assembly flow — UI/command to equip 7 slots and commit to a mint
3. Class calculation engine — stat-profile → class assignment
4. Race gating by class — races define which classes can enter
5. Salvage command — simplest sink, immediate value
6. Limited print part designation — flag on card data, series tag, print cap, pedigree bonus formula
7. Series/release infrastructure — tooling to define and publish a new named series of limited parts
8. Fusion command — 3-to-1 upgrade mechanic
9. Tuning command — part sacrifice → stat modifier on recipient

**What stays open:**
- Exact pedigree bonus formula and set bonus multiplier (needs playtesting)
- Class threshold values (needs balancing once more race data exists)
- Release cadence — how often a new series ships and who decides (game team decision, not a code question)
- Whether event drop serials are pre-assigned to winners or random within the winner pool
- Build timer (future)
- Public rig profile / ownership history display (future)
