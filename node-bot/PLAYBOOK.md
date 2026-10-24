# Cheapest Eats (5 Guys): Food Truck Wars playbook

**Live status, updated every round: [LIVE.md](LIVE.md)**

## Right now
- **The team's Python bot owns the key** (since day 5). This Node bot runs in **shadow mode**
  (`--shadow`) on Charlie's laptop: it decides every night but sends nothing, and
  [LIVE.md](LIVE.md) scores its choice against the real day, side by side with the Python bot.
- **Only ONE bot sends orders.** The last order sent each night wins. To hand the key to the
  Node bot: stop the Python bot, then run `node bot.js --camp thompson` (no `--shadow`).
- **The live game doesn't decide the winner.** The **8:30 AM final** does: 20 fresh markets of
  30 days, every truck starting from $0 and rep 50, 2 seconds per day, highest average profit
  wins.

## Run / restart (Windows, from this folder)
```powershell
$env:NIGHTSHIFT_KEY = "fk_..."          # or put NIGHTSHIFT_KEY=fk_... in .env next to bot.js
node bot.js --camp thompson              # live game / final; leave it running
powershell -File restart.ps1             # restart detached, logs to live-out.log
node bot.js --practice --seed rainy-week # private 30-day practice market
node sim.js 8 "v3,eventcheap,eventprem,winner,std95,prem11,eventprem"   # offline tournament
```
Flags: `--camp <spot>` (camp a spot), `--v2` / `--v1` (older strategies).

## The rules that decide money
- **Customers buy the best value:** `value = quality_value × rep_factor − price`.
  - Quality values: cheap 8, standard 12, premium 16.
  - Rep factor: 0.7 at rep 0, 1.0 at 50, 1.3 at 100.
  - Ties go to the cheaper truck. Value below 0 means no sale.
- **Each customer** has a price limit and a minimum quality, and skips trucks above or below
  them.
- **Budget:** $500 a day for food, so at most 200 cheap, 133 standard or 90 premium meals.
  Unsold meals spoil. **0 meals = sit out at no cost.**
- **Reputation** moves only at a spot where you sold at least 1 meal: **premium +5,
  standard +2, cheap −3**. Elsewhere it drifts 3% a day back toward 50.
- **Market size:** about 110 customers per truck per day, split across spots, then changed
  by weather and events.
- **Events** are announced the night before:
  - game day: about 5× the crowd at the Stadium,
  - midterms: 1.7× at Thompson (premium sells),
  - concert: 1.8× at the Union,
  - late-night rush: High St and North Res packed, cheap wins,
  - rally: 2× at the Oval.
- **Rain** hits the Oval and the Stadium hardest. Rain follows rain, and cold snaps stick.

## Price elasticity: what to charge alone at a spot (rep 50, per 100 customers)
Price limits are about Normal(mu, sd) per spot (fit on 11,340 practice spot-days). The
elasticity is `ε = −p·φ(z)/(sd·(1−Φ(z)))`, and profit peaks where `(p − cost)/p = 1/|ε|`.

| Spot | Standard | ε | Profit | Premium | ε | Profit |
|---|---|---|---|---|---|---|
| Thompson | **$10.25** | −1.60 | $398 | $10.80 | −2.02 | $347 |
| Union | $10.75 | −1.53 | $419 | $11.30 | −1.95 | $398 |
| Stadium | $11.20 | −1.49 | $397 | **$11.80** | −1.87 | **$416** |
| High St | $10.60 | −1.56 | $371 | $11.30 | −1.95 | $330 |
| Oval | $10.80 | −1.53 | $420 | $11.40 | −1.94 | $390 |
| North Res | $9.40 | −1.65 | $376 | $10.00 | −2.25 | $295 |

- **Cheap is capped at $8** by the value ≥ 0 rule. It only wins on huge crowds.
- **Standard earns the most per customer. Premium builds reputation 2.5× faster** (+5 vs +2).
- **When the crowd exceeds the budget's meals,** price above the table until demand equals
  capacity.
- **Sharing a spot is a price war.** The better value takes everyone it can serve. Beat the
  best rival's value clearly or leave. Premium can charge **$4 more** than standard at equal
  value.

## What tonight's live data taught us
| Day | Our order | Result | Lesson |
|---|---|---|---|
| 1 | — (bot started late) | sat out | |
| 2 | Union premium $11.25 × 63 | sold 51, **+$227** | |
| 3 | Union premium $11.25 × 90 | sold 0, **−$495** | concert: all 6 trucks went to the Union; cheapest premium ($9.75) took it all; 535 customers elsewhere had no truck |
| 4 | Oval standard $10.75 × 90 | sold 0, **−$337** | Frontrun's premium at $11 was a better deal than our standard |
| 5 | Thompson standard $10.25 × 59 | see LIVE.md | camping an empty spot |

1. **Rivals herd** onto the event spot or the busiest spot. 2–3 spots have no truck every day.
2. **Never put standard next to a premium rival priced within $4 of you.**
3. **Camp one under-served spot** and build reputation. Leave only for a clearly better day.

## How the bot decides (v3)
1. **Predict each rival:** stay, busiest, hungriest, per-truck, event-chaser or
   yesterday's-winner, weighted by how well each has predicted it so far. History persists in
   `data/rivals.json`.
2. **Use rivals' real per-spot reputation** from `GET /api/v1/public/state`.
3. **Score every spot × quality × price ($0.25 steps)** over 48 joint scenarios (weather ×
   crowd noise × which rivals show up). Each rival is present or absent, never fractional.
4. **Cook the profit-maximising number of meals** (newsvendor over those scenarios), and add
   the value of the reputation change.
5. **Camp:** stay at `--camp` unless another spot beats it by more than $150.
6. **Sit out** if the best expected profit is under $25.

## Team rules
- One bot on the key. Charlie's laptop runs it: plugged in, lid open, sleep set to Never.
- **By 8:30 AM the registered repo must hold the bot that played.** This branch is in the
  registered repo. To be safe, merge it to main before 8:30 (GitHub: Pull requests → New →
  compare `charlie/node-bot` → Create → Merge; it only adds `node-bot/`).
- Team edits (members, names, repo link) close at 8:30 AM.

## 8:30 AM final checklist
- [ ] The bot is running (`live-out.log` shows new lines every night).
- [ ] Only one bot on the key.
- [ ] `node-bot/` is on main (or the repo link points to the bot that plays).
- [ ] Laptop plugged in and online until the final ends (~9:00 AM).
