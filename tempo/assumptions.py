"""Every economic and modeling parameter Tempo uses, in one place.

Each parameter has a comment, a unit, and a label:
- SOURCED: from a public page (URL and the date it was checked; full list in docs/SOURCES.md).
- ASSUMPTION: our choice, stated plainly; change it here and everything downstream follows.

Money is integer cents everywhere outside the solver and charts. Rates are fractions (0.02 = 2%).
"""

from datetime import date
from statistics import NormalDist

# --- Calendar and day count -------------------------------------------------------------------

AS_OF = date(2026, 11, 10)  # date. ASSUMPTION: the dataset's "today"; fixed so the plan hash is reproducible.
HORIZON_DAYS = 91  # days (13 weeks). SOURCED: Ramp Treasury forecasts 13 weeks (docs/SOURCES.md).
DAYS_IN_YEAR = 365  # days. SOURCED: AFP quotes 2/10 net 30 as "about 37%" on a 365-day simple basis
#   (afponline.org, checked 2026-11-10). The U.S. Treasury prompt-payment calculator uses 360 (36.73%).
TREASURY_DAYS_IN_YEAR = 360  # days. SOURCED: fiscal.treasury.gov prompt payment calculator; tooltip only.

# Federal Reserve holidays (no ACH settlement). SOURCED: federalreserve.gov/aboutthefed/k8.htm,
# checked 2026-11-10. Weekends are also non-business days.
FED_HOLIDAYS: tuple[date, ...] = (
    date(2026, 11, 11),  # Veterans Day
    date(2026, 11, 26),  # Thanksgiving Day
    date(2026, 12, 25),  # Christmas Day
    date(2027, 1, 1),  # New Year's Day
    date(2027, 1, 18),  # Birthday of Martin Luther King, Jr.
    date(2027, 2, 15),  # Washington's Birthday
)

# --- Cash, card, and financing economics -----------------------------------------------------

YIELD_ON_CASH = 0.04  # per year. ASSUMPTION: idle cash above the operating target is swept to Ramp's
#   investment account (advertised "up to" a higher rate) as Target Balance automation does; Ramp Checking
#   itself pays less. We use 4%.
CARD_CASHBACK = 0.015  # fraction of the charge. ASSUMPTION: Ramp advertises "up to 1.5%" cashback.
CARD_STATEMENT_DAYS_AFTER_CLOSE = 10  # days. ASSUMPTION: monthly cycle closing on the last day of the
#   month, paid 10 days after close. Ramp's exact statement timing was not found.
CARD_SURCHARGE_CAP = 0.03  # fraction. SOURCED: Visa caps U.S. credit surcharges at 3% (Mastercard 4%).
CARD_SURCHARGE_SANITY_MAX = 0.04  # fraction. ASSUMPTION: anything above is treated as an extraction error.
FINANCE_FEE_PER_30_DAYS = 0.01  # fraction per 30 days. ASSUMPTION: a Flex-style fee for illustration only;
#   Ramp's Flex pricing is not public, so this is never presented as Ramp's price.
FINANCE_TERM_DAYS = 30  # days. ASSUMPTION: shortest Flex-style repayment term (30/60/90 offered).
FINANCE_ENABLED = (
    False  # bool. ASSUMPTION: off for the headline (council C2): the fee is assumed and Flex has
)
#   no public API. RESULTS.md reports a sensitivity run with it on.
FLEX_LIMIT_CENTS = 50_000_000  # cents ($500,000). ASSUMPTION: Flex-style line limit. Total financing
#   outstanding on any day (financed amounts not yet repaid) can never exceed it. With a fixed 30-day term this
#   is the sum financed with send dates inside any 30-day window (tempo/optimize/capacity.py).
FINANCE_LINE_LIMIT_CENTS = FLEX_LIMIT_CENTS  # kept as an alias for older call sites.
CARD_LIMIT_PER_CYCLE_CENTS = 50_000_000  # cents ($500,000). ASSUMPTION: card charges allowed per monthly
#   statement cycle (card credit sits outside the cash constraint, so it needs its own cap; council C2).

# --- Rails (Ramp Help Center; see docs/SOURCES.md) ---------------------------------------------

FUNDING_ACCOUNT = "ramp_checking"  # "ramp_checking" | "external_bank". ASSUMPTION: default funding source.
ACH_FEE_CENTS = 59  # cents per payment. SOURCED: Ramp Help Center, standard ACH fee from an external bank;
#   waived when paying from a Ramp Checking Account.
ACH_LEAD_BUSINESS_DAYS = 3  # business days. SOURCED: standard ACH arrives in 2 to 4 business days; we use 3.
ACH_LEAD_DISCOUNT_BUSINESS_DAYS = 4  # business days. ASSUMPTION: the 4-day upper bound for discount-window
#   payments, because a late arrival forfeits the discount (council C1, ramp-engineer).
ACH_LEAD_NEW_VENDOR_BUSINESS_DAYS = 5  # business days. SOURCED: new vendors can take up to 5.
RTP_FEE_CENTS = 0  # cents. SOURCED: RTP is free per Ramp's Help Center, only from Ramp Checking, 24/7.
RTP_VENDOR_SHARE = 0.70  # fraction of vendors whose bank receives RTP. ASSUMPTION.
RTP_ASSURED = (
    True  # bool. ASSUMPTION: paying from Ramp Checking, RTP-eligible vendors are paid by RTP. Ramp's
)
#   request enum has no RTP, so the payload preview also shows the ACH-safe fallback send date.

# --- Late payment -------------------------------------------------------------------------------

LATE_DAYS = 15  # days after the due date. ASSUMPTION: what "pay late" means in the option set.
LATE_RELATIONSHIP_PENALTY = 0.02  # fraction of the bill. ASSUMPTION: objective-only cost of paying late.
DEFAULT_LATE_FEE_BPS_PER_MONTH = 150  # basis points per month. ASSUMPTION: used when the invoice states none.
LATE_FEE_SANITY_MAX_BPS_PER_MONTH = 300  # basis points per month. ASSUMPTION: sanity bound (3%/month).

# --- Risk and solver -----------------------------------------------------------------------------

EPSILON = 0.05  # probability. ASSUMPTION (CFO setting): allowed chance of any end-of-day buffer breach
#   over the 13-week horizon.
CREDIT_COST = 0.50  # dollars per dollar drawn. ASSUMPTION: deliberately punitive emergency credit so the
#   backstop appears only when the chance constraint is otherwise infeasible.
N_OPT_SCENARIOS = 200  # scenarios in the optimizer (seed A). ASSUMPTION.
N_FAN_SCENARIOS = 1_000  # scenarios for the fan chart. ASSUMPTION.
N_CERT_SCENARIOS = 10_000  # fresh scenarios for certification (seed B). ASSUMPTION.
N_EVAL_SCENARIOS = 10_000  # fresh scenarios for reported numbers (seed C). ASSUMPTION.
K_LADDER = (10, 8, 6, 4, 3, 2, 1, 0)  # unprotected scenarios allowed, tried in order. ASSUMPTION: starts at
#   K = floor(EPSILON * N_OPT_SCENARIOS) = 10 and walks down to 0 (final fix pass; was 4..0, see DECISIONS.md).
FALLBACK_N = 1_000  # scenarios if K = 0 fails at N = 200. ASSUMPTION (council C1, quant).
FALLBACK_K = 5  # unprotected scenarios in the fallback. ASSUMPTION (council C1, quant).
WILSON_Z_REPORT = 1.645  # one-sided 95% normal quantile, for reported bounds.
CERT_ALPHA = 0.05  # the certification test's error rate (95% confidence); equals EPSILON only by coincidence.
CERT_STEPS = len(K_LADDER) + 1  # every plan the ladder can test: its rungs plus the N = 1,000 fallback.
WILSON_Z_CERTIFY = NormalDist().inv_cdf(
    1 - CERT_ALPHA / CERT_STEPS
)  # one-sided quantile at 0.05 / 9 = 2.539:
#   Bonferroni over every step the ladder can try.
SOLVER_TIME_LIMIT_S = 10.0  # seconds. ASSUMPTION: safety net; the reduced model solves well within it.
SOLVER_MIP_REL_GAP = 1e-4  # relative gap. ASSUMPTION.
CASH_VALUE_STEP_CENTS = 2_500_000  # $25,000 forward step for the marginal value of cash. ASSUMPTION.

# --- Forecast -----------------------------------------------------------------------------------

KAPPA = 5.0  # pseudo-observations. ASSUMPTION: pooling strength; a customer with 5 payments gets half
#   its own estimate and half the pool's.
SIGMA_MACRO = 0.15  # log-scale std of the common timing factor. ASSUMPTION: a scenario-wide shock that
#   speeds up or slows down every customer together (about +/-15% on every delay at one sigma).
P_NO_PAY = 0.02  # probability per invoice of no payment within the horizon. ASSUMPTION.

# --- Negotiation ---------------------------------------------------------------------------------

OFFER_DAYS = 10  # days after issue for the proposed early payment. ASSUMPTION.
OFFER_MARGIN = 0.0025  # fraction added to the break-even discount. ASSUMPTION.
OFFER_ROUNDING = 0.0025  # offers round up to the next 0.25%. ASSUMPTION.

# --- Extraction ----------------------------------------------------------------------------------

EOM_ROLL_AFTER_25TH = False  # bool. ASSUMPTION: some vendors roll invoices dated after the 25th to the
#   next month for EOM/prox terms; off by default.
MAX_NET_DAYS = 120  # days. ASSUMPTION: sanity bound for net terms.
MAX_DISCOUNT = 0.05  # fraction. ASSUMPTION: sanity bound for early-payment discounts.

# --- Reproducibility -----------------------------------------------------------------------------

SEED = 20261110  # the one seed. Scenario seeds below derive from it and are asserted distinct.
SEED_A = SEED  # optimizer scenarios
SEED_B = SEED + 1_000_003  # certification scenarios
SEED_C = SEED + 2_000_029  # reported scenarios (never used for any decision)
SEED_D = SEED + 3_000_017  # starting-cash calibration only
SEED_FAN = SEED + 4_000_037  # fan chart
