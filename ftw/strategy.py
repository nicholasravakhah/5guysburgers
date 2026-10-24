"""Decision making: scenario sampling + joint search over spot, quality, price, meals.

Brain.observe(state) ingests each day's results exactly once per (mode, market, day).
Brain.decide(state) returns a legal order within a deadline, falling back to a
simple heuristic if anything goes wrong.
"""
import hashlib
import math
import random
import time

from . import engine
from .model import CustomerModel, default_expected, event_key
from .opponents import Rival, day_context
from .rules import QI, REP_DELTA, Rules, rep_factor

DEFAULT_CFG = {
    "scenarios": 48,
    "deadline": 0.45,         # seconds of compute before using the best order found so far
    "rep_lambda": 1.0,        # $ per reputation point per remaining-day weight
    "rep_horizon": 10.0,      # days over which reputation pays back
    "rep_return": 0.5,        # baseline chance we return to a spot we sell at
    "near_tol_abs": 3.0,      # randomize among options within this many dollars...
    "near_tol_rel": 0.015,    # ...or this fraction of the best expected profit
    "price_step": 0.5,
    "min_price": 2.0,
    "max_price": 24.0,
    "price_offset": 0.0,      # added to grid prices (e.g. -0.01 gives $8.99-style prices)
    "avoid_spots": [],        # spots never considered
    "only_quality": None,     # e.g. "premium" to consider one tier only
    "fixed_price": None,      # e.g. 9.24: only this price; the optimizer still picks meals
    "live_overrides": {},     # manual settings applied in mode == "live" only
    "meals_mult": 1.0,        # scale the optimal meal count (e.g. 1.15 after repeated sellouts)
    "shared_meal_frac": 1.0,  # <1 cooks less than the optimum when rivals are expected (Arjun's idea; off)
}

STYLES = {
    "max": {},
    # camp a home spot and build reputation there (best on held-out local seeds)
    "camp": {"rep_return": 0.9, "rep_lambda": 2.0, "near_tol_abs": 0.5},
    # Cheapest Eats: low prices, odd cents; the optimizer still picks spot/quality/meals
    "cheap": {"max_price": 9.0, "price_offset": -0.01},
}


def _stable_seed(*parts):
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:16], 16)


class Brain:
    def __init__(self, cfg=None, model=None, memory=None, seed=0):
        self.cfg = dict(DEFAULT_CFG)
        self.cfg.update(cfg or {})
        self.model = model or CustomerModel()
        self.seed = seed
        self.rng = random.Random(seed)
        self.rivals = {}
        if memory:
            for d in memory.get("rivals", []):
                try:
                    r = Rival.from_json(d)
                    self.rivals[r.tid] = r
                except Exception:
                    pass
        self.market_key = None
        self.forecasts = {}       # day -> forecast seen the night before
        self.last_days = {}       # day -> last_day result
        self.processed = set()    # days already ingested in this market
        self.my_id = None
        self.last_debug = {}

    # ------------------------------------------------------------ memory
    def memory(self):
        return {"version": 1, "rivals": [r.to_json() for r in self.rivals.values()]}

    def _ensure_market(self, state):
        key = (state.get("mode"), state.get("market"))
        if key != self.market_key:
            if self.market_key is not None:
                for r in self.rivals.values():
                    r.new_market()
            self.market_key = key
            self.forecasts, self.last_days, self.processed = {}, {}, set()

    # ------------------------------------------------------------ observation
    def observe(self, state):
        """Ingest a state. Safe to call on every state; each day is processed once."""
        if not isinstance(state, dict):
            return
        self._ensure_market(state)
        you = state.get("you") if isinstance(state.get("you"), dict) else {}
        self.my_id = you.get("id") or self.my_id
        rules = Rules(state.get("rules"))
        fc = state.get("forecast")
        if isinstance(fc, dict) and isinstance(fc.get("day"), int):
            self.forecasts[fc["day"]] = fc
        ld = state.get("last_day")
        day = ld.get("day") if isinstance(ld, dict) else None
        trucks = state.get("trucks") if isinstance(state.get("trucks"), list) else []
        for t in trucks:
            if not isinstance(t, dict) or not t.get("id") or t.get("id") == self.my_id:
                continue
            r = self.rivals.get(t["id"])
            if r is None:
                r = self.rivals[t["id"]] = Rival(t["id"], t.get("truck_name", ""))
            if isinstance(t.get("reputation"), dict):
                r.rep = {s: _f(v, 50.0) for s, v in t["reputation"].items()}
        if not isinstance(day, int) or day in self.processed:
            return
        self.processed.add(day)
        self.last_days[day] = ld
        ctx = day_context(self.forecasts.get(day), self.last_days.get(day - 1), rules.spots)
        played = {}
        spots = ld.get("spots") if isinstance(ld.get("spots"), dict) else {}
        for s, v in spots.items():
            for t in (v.get("trucks") or []) if isinstance(v, dict) else []:
                if isinstance(t, dict) and t.get("id"):
                    played[t["id"]] = dict(t, spot=s)
        for tid, r in self.rivals.items():
            o = played.get(tid)
            r.observe(rules.spots, ctx, o, market=state.get("market"), day=day)
            if not any(isinstance(t, dict) and t.get("id") == tid and isinstance(t.get("reputation"), dict)
                       for t in trucks):
                _track_rep(r, o, rules.spots)

    # ------------------------------------------------------------ decision
    def decide(self, state, deadline=None):
        t0 = time.perf_counter()
        budget = self.cfg["deadline"] if deadline is None else deadline
        rules = Rules(state.get("rules") if isinstance(state, dict) else None)
        try:
            self.observe(state)
            order, debug = self._optimize(state, rules, t0 + budget)
        except Exception as e:  # never fail to produce an order
            order, debug = self._fallback(state, rules), {"error": repr(e)}
        order = rules.validate(order)
        debug["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self.last_debug = debug
        return order

    def _fallback(self, state, rules):
        fc = (state or {}).get("forecast") or {}
        exp_c = fc.get("expected_customers") if isinstance(fc.get("expected_customers"), dict) else None
        trucks = (state or {}).get("trucks") or []
        if not exp_c:
            exp_c = default_expected(len(trucks))
        crowd_trucks = {}
        for tid, r in self.rivals.items():
            if r.last_spot and r.p_active() > 0.5:
                crowd_trucks[r.last_spot] = crowd_trucks.get(r.last_spot, 0) + 1
        spot = max(rules.spots, key=lambda s: _f(exp_c.get(s), 0) / (1 + crowd_trucks.get(s, 0)))
        share = _f(exp_c.get(spot), 60) / (1 + crowd_trucks.get(spot, 0))
        meals = int(min(rules.max_meals("standard"), max(20, 0.75 * share)))
        return {"spot": spot, "price": 10.0, "quality": "standard", "meals": meals}

    def _rival_list(self, state):
        out = []
        for tid, r in self.rivals.items():
            if tid == self.my_id:
                continue
            out.append(r)
        return out

    def _scenarios(self, state, rules, K, deadline):
        fc = state.get("forecast") if isinstance(state.get("forecast"), dict) else {}
        exp_c = fc.get("expected_customers") if isinstance(fc.get("expected_customers"), dict) else {}
        trucks = state.get("trucks") if isinstance(state.get("trucks"), list) else []
        if not exp_c:
            exp_c = default_expected(len(trucks))
        events = [e for e in (fc.get("events") or []) if isinstance(e, dict)]
        rng = random.Random(_stable_seed(self.seed, state.get("mode"), state.get("market"),
                                         state.get("order_for_day")))
        ctx = day_context(fc, state.get("last_day"), rules.spots)
        rivals = self._rival_list(state)
        rival_pred = [(r, r.p_active(), r.spot_dist(rules.spots, ctx)) for r in rivals]
        profiles = {s: self.model.profile(s, events) for s in rules.spots}
        maxm = {q: rules.max_meals(q) for q in rules.qualities}
        scen = []
        for k in range(K):
            if k >= 8 and time.perf_counter() > deadline:
                break
            w = self.model.sample_weather(fc, rng)
            at = {s: [] for s in rules.spots}
            for r, pa, sd in rival_pred:
                if rng.random() >= pa:
                    continue
                spot = _sample(sd, rng)
                q, p, m = r.sample_order(spot, rng, maxm)
                at[spot].append(engine.Truck(r.tid, q, p, r.rep.get(spot, 50.0), m, rules.values))
            per_spot = {}
            for s in rules.spots:
                n = self.model.crowd(s, _f(exp_c.get(s), 0.0), w, fc, rng)
                med, sig, mix = profiles[s]
                lim, mq = self.model.customers(n, med, sig, mix, rng)
                per_spot[s] = engine.SpotScenario(lim, mq, at[s])
            scen.append(per_spot)
        return scen, rival_pred

    def _optimize(self, state, rules, deadline):
        cfg = self.cfg
        if state.get("mode") == "live" and cfg.get("live_overrides"):
            # manual live-game settings (spot/quality/price locks) never reach the final or practice
            cfg = dict(cfg, **cfg["live_overrides"])
        you = state.get("you") if isinstance(state.get("you"), dict) else {}
        my_rep = you.get("reputation") if isinstance(you.get("reputation"), dict) else {}
        day = state.get("order_for_day") or ((state.get("day") or 0) + 1)
        days = state.get("days") or 30
        remaining = max(0, int(days) - int(day))   # days after this one
        scen, rival_pred = self._scenarios(state, rules, cfg["scenarios"], deadline)
        if not scen:
            return self._fallback(state, rules), {"why": "no scenarios"}
        best_by_combo = {}
        evals = 0
        exp_rivals = {}
        for _r, pa, sd in rival_pred:
            for s_, p_ in sd.items():
                exp_rivals[s_] = exp_rivals.get(s_, 0.0) + pa * p_

        def evaluate(spot, q, price):
            nonlocal evals
            rep = _f(my_rep.get(spot), 50.0)
            value = rules.values[q] * rep_factor(rep) - price
            cap = rules.max_meals(q)
            qi = QI[q]
            ds = [sc[spot].demand(qi, price, value, cap) for sc in scen]
            evals += 1
            n, prof, sold = engine.best_quantity(ds, price, rules.costs[q], cap)
            if n > 0 and cfg.get("meals_mult", 1.0) != 1.0:
                n = max(0, min(cap, int(round(n * cfg["meals_mult"]))))
                sold = sum(min(n, d) for d in ds) / len(ds)
                prof = price * sold - rules.costs[q] * n
            if n > 0 and cfg["shared_meal_frac"] < 1.0 and exp_rivals.get(spot, 0.0) >= 0.5:
                n = int(n * cfg["shared_meal_frac"])
                sold = sum(min(n, d) for d in ds) / len(ds)
                prof = price * sold - rules.costs[q] * n
            bonus = 0.0
            if n > 0 and remaining > 0 and cfg["rep_lambda"]:
                new_rep = max(0.0, min(100.0, rep + REP_DELTA[q]))
                p_sell = sum(1 for d in ds if d > 0) / len(ds)
                weight = min(remaining, cfg["rep_horizon"]) / cfg["rep_horizon"]
                bonus = cfg["rep_lambda"] * (new_rep - rep) * weight * cfg["rep_return"] * p_sell * \
                    rules.values[q] / 12.0
            total = prof + bonus
            key = (spot, q)
            cur = best_by_combo.get(key)
            if cur is None or total > cur[0]:
                best_by_combo[key] = (total, {"spot": spot, "quality": q, "price": round(price, 2), "meals": n},
                                      prof, sold)
            return total

        # coarse pass
        avoid = set(cfg.get("avoid_spots") or [])
        if avoid >= set(rules.spots):
            avoid = set()
        quals = [cfg["only_quality"]] if cfg.get("only_quality") in rules.qualities else rules.qualities
        combos = [(s, q) for s in rules.spots if s not in avoid for q in quals]
        thresholds = self._threshold_prices(scen, rules, my_rep)
        for s, q in combos:
            if time.perf_counter() > deadline:
                break
            ceil_p = rules.values[q] * rep_factor(_f(my_rep.get(s), 50.0)) - 0.01
            hi = min(ceil_p, cfg["max_price"], rules.price_max)
            lo = max(cfg["min_price"], rules.costs[q] + 0.25, rules.price_min)
            p = lo
            prices = []
            while p <= hi + 1e-9:
                po = round(p + cfg["price_offset"], 2)
                if lo <= po <= hi:
                    prices.append(po)
                p += cfg["price_step"]
            prices.extend(tp for tp in thresholds.get((s, q), []) if lo <= tp <= hi)
            if cfg.get("fixed_price"):
                prices = [round(float(cfg["fixed_price"]), 2)]
            for p in sorted(set(prices)):
                evaluate(s, q, p)
        # refine around the best few combos
        ranked = sorted(best_by_combo.items(), key=lambda kv: -kv[1][0])
        for (s, q), (tot, order, _, _) in ([] if cfg.get("fixed_price") else ranked[:5]):
            if time.perf_counter() > deadline:
                break
            ceil_p = rules.values[q] * rep_factor(_f(my_rep.get(s), 50.0)) - 0.01
            base = order["price"]
            for dp in (-0.4, -0.3, -0.2, -0.1, -0.05, 0.05, 0.1, 0.2, 0.3, 0.4):
                p = round(base + dp, 2)
                if rules.price_min <= p <= min(ceil_p, rules.price_max, cfg["max_price"]):
                    evaluate(s, q, p)
        if not best_by_combo:
            return self._fallback(state, rules), {"why": "deadline before any evaluation"}
        ranked = sorted(best_by_combo.values(), key=lambda v: -v[0])
        best_total = ranked[0][0]
        if best_total <= 0:
            # nothing profitable in expectation: cook nothing (legal, no cost)
            o = dict(ranked[0][1])
            o["meals"] = 0
            return o, {"why": "no profitable option", "best": round(best_total, 2), "evals": evals}
        tol = max(cfg["near_tol_abs"], cfg["near_tol_rel"] * best_total)
        near = [v for v in ranked if v[0] >= best_total - tol]
        if len(near) > 1:
            ws = [math.exp((v[0] - best_total) / (tol / 2.0)) for v in near]
            pick = near[_sample_idx(ws, self.rng)]
        else:
            pick = ranked[0]
        debug = {"evals": evals, "scenarios": len(scen), "exp_total": round(pick[0], 2),
                 "exp_profit": round(pick[2], 2), "exp_sold": round(pick[3], 1), "near": len(near),
                 "top": [(v[1]["spot"], v[1]["quality"], v[1]["price"], v[1]["meals"], round(v[0], 1))
                         for v in ranked[:5]],
                 "rivals": [(r.name or r.tid, round(pa, 2), max(sd, key=sd.get)) for r, pa, sd in rival_pred]}
        return dict(pick[1]), debug

    def _threshold_prices(self, scen, rules, my_rep):
        """Prices that just beat a likely rival's value at a spot (one cent better)."""
        counts = {}
        for sc in scen:
            for s, ss in sc.items():
                for t in ss.rivals:
                    k = (s, round(t.value, 3))
                    counts[k] = counts.get(k, 0) + 1
        out = {}
        for (s, v), c in counts.items():
            if c < max(2, len(scen) // 10):
                continue
            for q in rules.qualities:
                a = rules.values[q] * rep_factor(_f(my_rep.get(s), 50.0))
                p = math.floor((a - v - 0.01) * 100) / 100.0
                out.setdefault((s, q), []).append(p)
        return out


def _track_rep(r, order, spots):
    """Update a rival's reputation estimate when the state does not expose it."""
    for s in spots:
        cur = r.rep.get(s, 50.0)
        if order and order.get("spot") == s:
            if (order.get("sold") or 0) > 0 and order.get("quality") in REP_DELTA:
                cur = max(0.0, min(100.0, cur + REP_DELTA[order["quality"]]))
        else:
            cur = cur + 0.03 * (50.0 - cur)
        r.rep[s] = cur


def _f(x, default):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _sample(dist, rng):
    r = rng.random()
    acc = 0.0
    last = None
    for k, p in dist.items():
        acc += p
        last = k
        if r <= acc:
            return k
    return last


def _sample_idx(ws, rng):
    r = rng.random() * sum(ws)
    acc = 0.0
    for i, w in enumerate(ws):
        acc += w
        if r <= acc:
            return i
    return len(ws) - 1


__all__ = ["Brain", "DEFAULT_CFG", "event_key"]
