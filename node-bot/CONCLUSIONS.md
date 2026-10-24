# Node bot vs Python bot: conclusions after live day 6

Written for the team **and for Nick's Claude**. Everything here can be checked against the
files in this folder and the live API. The Node bot runs in **shadow mode** (decides every
night, sends nothing), and the Python bot owns the key.

## Verdict so far (honest)
| | Python bot (actual) | Node bot (shadow, replayed on the real day) |
|---|---|---|
| Day 5 | North Res premium $9.25 × 66 → **+$182.75** | Thompson standard $10.25 × 59 → est. **+$383.50** |
| Day 6 (game day, rain) | North Res standard $9.05 × 90 → **+$223.60** | Union standard $11.25 × 105 → est. **−$393.75** |
| **Total** | **+$406.35** | **−$10.25** |

- **The Node bot picks better spots.** On day 5 it chose an empty spot with 106 customers and
  would have made about 2× the Python bot.
- **It has one repeated pricing mistake that erases the gain:** standard at $10.75–11.25 next to
  a premium rival sells 0. That happened on day 4 (Oval vs Frontrun premium $11) and day 6
  (Union vs IBE premium $9.50).
  - Value math: 16 − 9.50 = 6.5 beats 12 − 11.25 = 0.75, so every customer goes to the premium.
- **With that one rule fixed, the Node bot's day 6 would have stayed at Thompson** (71
  customers, no truck, about +$200). The 2-day total would then be roughly +$580 vs +$406.
  The fix is identified and **not applied yet**.

## Where the Node bot is stronger (verifiable)
1. **The customer model is validated live.** It predicted the Python bot's actual sales at
   63 vs 59 (day 5) and **62 vs 62** (day 6), using only that day's real crowd and rival
   offers. Fit on **11,340 practice spot-days** (`fit.js` → `model.js`, Normal price limits
   per spot, accepted-quality shares, weather multipliers).
2. **Rivals are present-or-absent, never fractional.** Each candidate order is scored over 48
   joint scenarios (weather × crowd noise × which rivals show up). A fractional rival hides a
   herd. That's how day 3 went: all 6 trucks at the Union concert, 0 sold.
3. **Rivals' real per-spot reputation.** It reads `GET /api/v1/public/state` (the TV feed, no
   key needed), which has every truck's reputation at every spot. The Python bot doesn't read
   it (no `public/state` in `ftw/`). Wagyu is at rep 65 on High St, which is worth $1.44 a meal
   in customer value.
4. **Rival behaviour learning.** Each rival gets weighted hypotheses (stay, busiest, hungriest,
   per-truck, event-chaser, yesterday's winner), scored on its own history and kept across
   markets (`data/rivals.json`). That matters in the final's 20 markets.
5. **Offline tournament.** Against a field mimicking tonight's rivals (`sim.js`), v3 averaged
   **$13,274/market** vs v2 $10,610 and every rival archetype.

## Where the Python bot is right
- **Cheap prices with no rival around work.** North Res standard $9.05 sold 62/90 on game day.
- **Staying at a spot we have rep in.** North Res is now rep 57 for us.

## What the whole night's data says (both bots should follow it)
1. **The winning offer when sharing a spot is premium at about $9–10.** IBE does it every day
   and leads ($1,275+). Standard only sells where no premium truck parks.
2. **Free spots every day.** Thompson has been empty 4 days in a row; High St (178 customers)
   was empty on day 6.
3. **Rivals herd** onto events and the busiest spot. Never chase the event.
4. **Rivals' reputation moats:** Wagyu High St 65, Frontrun Oval 60, IBE Union 60. Ours:
   North Res 57, Union 55.
5. **Price alone with elasticity:** profit peaks where (p − cost)/p = 1/|ε|. Thompson standard
   $10.25 / premium $10.80; North Res standard $9.40 / premium $10.00. Full table in
   [PLAYBOOK.md](PLAYBOOK.md).

## For Nick's Claude: how to check all of this
```bash
git fetch origin charlie/node-bot
git show origin/charlie/node-bot:node-bot/CONCLUSIONS.md   # this file
git show origin/charlie/node-bot:node-bot/strategy.js      # v3 decision logic
git show origin/charlie/node-bot:node-bot/model.js         # fitted customer model
git show origin/charlie/node-bot:node-bot/bot.js           # addPublicReps(), --shadow, --camp
```
Suggested prompt for Nick's Claude:
> Read node-bot/CONCLUSIONS.md, PLAYBOOK.md, strategy.js and model.js on the charlie/node-bot
> branch. Compare them with our ftw/ bot on four points: (1) does ftw/ read per-spot rival
> reputation from /api/v1/public/state, (2) are rivals present-or-absent in our scenarios or
> fractional, (3) do we ever sell standard near a likely premium rival, (4) our customer-model
> accuracy against live days. Port whatever is better and tell me which bot should play the
> 8:30 AM final.

## Before 8:30 AM
- Only **one** bot sends orders on the key.
- The bot that plays must be in this repo (this branch only adds `node-bot/`).
- The laptop running it stays plugged in and online until the final ends.
