"""Exact-semantics demand evaluation for one spot.

Customers arrive in order; each buys one meal from the best-value truck that is
in stock, affordable (price <= limit), good enough (quality >= minimum) and
offers value >= 0. Ties go to the cheaper price.

Key facts used for speed:
  * Our sales with n meals are min(n, D), where D is our sales with maximum stock:
    until we sell out the world is identical whatever n is.
  * Trucks ranked above us (better value) are unaffected by us, so the customers
    they leave over ("free" customers) depend only on how many rivals rank above us.
So for each scenario and rank j we precompute free customers' limits sorted by
minimum-quality class, and D(quality, price) is a few binary searches.
"""
from bisect import bisect_left

from .rules import QI, rep_factor


class Truck:
    __slots__ = ("tid", "qi", "price", "value", "stock")

    def __init__(self, tid, quality, price, rep, stock, values):
        self.tid = tid
        self.qi = QI[quality]
        self.price = float(price)
        self.value = values[quality] * rep_factor(rep) - self.price
        self.stock = int(stock)


def rank_key(value, price):
    # higher value first, then cheaper price first
    return (-round(value, 9), round(price, 9))


def simulate_spot(limits, minq, trucks, rng=None):
    """Full sequential simulation. Returns {tid: sold}. Used by the local market
    simulator and tests; trucks with identical (value, price) are randomized."""
    live = [t for t in trucks if t.value >= 0 and t.stock > 0]
    if rng is not None:
        rng.shuffle(live)
    live.sort(key=lambda t: rank_key(t.value, t.price))  # stable: random among exact ties
    stock = [t.stock for t in live]
    sold = [0] * len(live)
    prices = [t.price for t in live]
    qis = [t.qi for t in live]
    for L, mq in zip(limits, minq):
        for i in range(len(live)):
            if stock[i] > 0 and prices[i] <= L and qis[i] >= mq:
                stock[i] -= 1
                sold[i] += 1
                break
    out = {t.tid: 0 for t in trucks}
    for t, s in zip(live, sold):
        out[t.tid] = s
    return out


class SpotScenario:
    """One sampled day at one spot: customers in arrival order plus rival trucks."""
    __slots__ = ("rivals", "_free", "limits", "minq")

    def __init__(self, limits, minq, rivals):
        self.limits = limits
        self.minq = minq
        self.rivals = sorted([t for t in rivals if t.value >= 0 and t.stock > 0],
                             key=lambda t: rank_key(t.value, t.price))
        self._free = {}

    def free_sorted(self, j):
        """Sorted limits of customers not captured by the top-j rivals, by min-quality class."""
        f = self._free.get(j)
        if f is not None:
            return f
        top = self.rivals[:j]
        stock = [t.stock for t in top]
        prices = [t.price for t in top]
        qis = [t.qi for t in top]
        buckets = ([], [], [])
        for L, mq in zip(self.limits, self.minq):
            taken = False
            for i in range(j):
                if stock[i] > 0 and prices[i] <= L and qis[i] >= mq:
                    stock[i] -= 1
                    taken = True
                    break
            if not taken:
                buckets[mq].append(L)
        for b in buckets:
            b.sort()
        self._free[j] = buckets
        return buckets

    def demand(self, qi, price, value, cap):
        """Our sales with `cap` meals at (quality index, price, value)."""
        if value < 0:
            return 0
        key = rank_key(value, price)
        j = 0
        for t in self.rivals:
            if rank_key(t.value, t.price) <= key:  # exact tie counts against us
                j += 1
            else:
                break
        buckets = self.free_sorted(j)
        d = 0
        for c in range(qi + 1):
            b = buckets[c]
            d += len(b) - bisect_left(b, price)
        return d if d < cap else cap


def best_quantity(demands, price, cost, cap):
    """Given sampled demands D_k (already capped), pick n maximizing
    price * E[min(n, D)] - cost * n. Returns (n, expected_profit, expected_sold).
    The objective is concave piecewise-linear in n, so the optimum is at a sample."""
    K = len(demands)
    if K == 0 or price <= cost:
        return 0, 0.0, 0.0
    ds = sorted(demands)
    best = (0, 0.0, 0.0)
    below = 0.0  # sum of samples strictly below the current n
    i = 0
    while i < K:
        n = ds[i]
        exp_sold = (below + (K - i) * n) / K
        profit = price * exp_sold - cost * n
        if n <= cap and profit > best[1]:
            best = (n, profit, exp_sold)
        while i < K and ds[i] == n:
            below += n
            i += 1
    return best
