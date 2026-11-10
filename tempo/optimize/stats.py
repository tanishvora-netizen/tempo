"""Statistics for certification and reporting."""

import math


def wilson_upper(breaches: int, n: int, z: float) -> float:
    """One-sided Wilson score upper bound on a binomial rate.

        p = breaches / n
        U = (p + z^2/(2n) + z * sqrt(p(1-p)/n + z^2/(4n^2))) / (1 + z^2/n)

    With z = 1.645 (one-sided 95%) and n = 10,000: 464 breaches give U = 4.9985% (passes 5%), 465 give 5.0088%.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    p = breaches / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (centre + margin) / (1 + z2 / n)
