# Ideas

Dump thoughts here. Tag each idea with a **Status** and **Area** so we can triage later.

**Status tags:** `raw` · `exploring` · `planned` · `rejected`
**Area tags:** `gameplay` · `economy` · `cards` · `social` · `tech` · `ux`

---

## Shipped

> Features that are live in the codebase.

| Feature | Area | Notes |
|---|---|---|
| Rig system — Car Title mint | gameplay · cards | Fill 7 slots → `/build mint` issues a globally-sequential Car Title with snapshot, pedigree_bonus field, race_record, part_swap_log, ownership_log. See [ADR-001](adr/001-rig-system-and-part-economy.md) |
| Car class & body gating | gameplay | Class assigned at mint from stat profile. Non-Street races require a minted title with matching class/body. `/build preview` shows projected class before committing. |
| Multi-build support | gameplay | Players own multiple builds. `/build new` (500 Creds), `/build list`, `/build set-default`. `/race` and all garage commands take an optional `build` autocomplete param. |
| Part wear & wreck system | gameplay | Parts degrade each race; worn-out parts are destroyed. Wrecks can destroy parts mid-race. Both clear from the correct build regardless of which build was raced. |
| Rig provenance — data layer | cards | `race_record` (wins/losses) written after every race. `part_swap_log` written by `/equip` and `/autoequip` whenever a minted rig's slot changes. `ownership_log` schema exists; populated once trading lands. |

---

## Planned / Committed

> Ideas that have been decided and will be built.

| # | Idea | Area | Notes |
|---|---|---|---|---|
| — | `/rig history` command | ux | Show a rig's full provenance: race record (W/L), part swap history, mint date, and owner chain once trading exists. All data is already being written — just needs the read command. |
| — | Trade system | economy · social | Player-to-player rig or part transfers. Transferring a rig passes the Car Title with its full history to the new owner and appends an entry to `ownership_log`. Unlocks the owner chain in `/rig history`. |
| — | Salvage command | economy | Discard any part for a flat Creds return. Commons return very little; scales with rarity but always at a loss vs. market. The "tidy up" sink. See ADR-001 §3. |
| — | Fusion command | economy · cards | Combine 3 parts of the same slot + rarity → 1 part of same slot at next rarity tier (random roll). Gives duplicates a purpose and creates a long grind path. See ADR-001 §3. |
| — | Tuning command | economy · cards | Sacrifice one part to permanently apply a stat modifier to another part of the same slot. Donor consumed; recipient gains a visible delta in `/inspect`. See ADR-001 §3. |

---

## Backlog

| # | Idea | Area | Status | Notes |
|---|---|---|---|---|
| 1 | Limited print parts | cards | `planned` | Hard global print cap per card. Series/release tagging on both part and any Car Title built with it. Pedigree bonus formula needs playtesting to set values. See ADR-001 §2. |
| 2 | Series / release infrastructure | economy · tech | `planned` | Tooling to define and publish a named series of limited parts with its own theme, parts, and print caps. Ongoing cadence keeps economy fresh. |
| 3 | Set bonus | gameplay · cards | `exploring` | When all 7 rig parts share the same named series, Car Title receives a set bonus on top of standard pedigree bonus. Highest prestige tier. |
| 4 | Class threshold calibration | gameplay | `planned` | Current thresholds are scaffolded but need balancing once real race data accumulates. Street is open; all other classes need calibrated stat minimums. |
| 5 | Public rig profile (`/rig peek`) | ux · social | `raw` | Let any player view another's minted rig: wins, swap history, previous owners (once trading exists). Complements `/rig history` for the owner. |
| 6 | Build timer | gameplay | `raw` | Completing a rig takes hours/days; higher-rarity parts reduce build time. Flagged in ADR-001 as future — only makes sense once baseline engagement is established. |
| 7 | Car care system | gameplay | `raw` | Lack of maintenance or certain pre-race prep gives stat buffs/debuffs. E.g. skipping care between races accumulates a debuff; spending Creds or using a care item before a race buffs performance. Interacts with wear system. Not accepted — needs more design before committing. |
| 8 | Mechanic System | gameplay | `raw` | Players do their building through mechanics that they can acquire through a number of means. Different mechanics have different bonuses, can build faster, are more likely to get a high pedigree, etc. Players can buy more Mechanic slots to do multiple builds simultaneously. Depends on build timer |
| 9 | Race board | gameplay | `raw` | a rotating bulletin board of races (even tournaments) with various conditions, entry requirements, rewards. This is incredibly important bc it can make server members compete over rewards without betting. When a rare event pops up with a reward everyone wants, it creates competition |
| 10 | Story rewrite | gameplay | `raw` | Instead of being a driver, the player is managing some sort of racing team in a fictional world we create. They hire drivers through various means with differing skillsets to enter races for the team or club. There can be other roles to hire as well, and as the club gains notoriety it attracts more 'prestigious' staff. Paying staff can be another currency sink. this can be expanded in a number of ways. Since we are simulating races rather than letting the player drive this makes sense and can be expanded upon |

---

## In Discussion

| # | Idea | Area | Status | Notes |
|---|---|---|---|---|
| — | Rig system, part economy, car classes | gameplay · economy · cards | `exploring` | Core system is shipped. See [ADR-001](adr/001-rig-system-and-part-economy.md) and the Shipped section above for what's live vs pending. |

---

## Rejected / Parked

| Idea | Reason |
|------|--------|
| Part Versioning (standalone) | Absorbed into ADR-001 — limited print parts with pedigree bonuses cover this. |
| Forge & Burn | Destroying parts on build reduces liquidity and punishes experimentation. Rig Passport achieves the same commitment without irreversibility. See ADR-001. |
| Chassis as Car Identity | Creates a single bottleneck (chassis rarity gates all rigs) and doesn't cleanly separate parts from rig identity. Could revisit as a flavour layer on top of the Passport system. See ADR-001. |
