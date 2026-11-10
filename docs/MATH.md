# Tempo: the math

All money is in integer cents in storage and converted to dollars only inside the solver. All balances are end-of-day. Code references are to `tempo/`.

## 1. Discount economics (`economics.py`)

Terms $d/D$ net $N$: pay $(1-d)$ of the pre-tax subtotal within $D$ days, else the full amount at $N$ days.

Simple annualized return of taking the discount (365-day basis; AFP quotes "about 37%" for 2/10 net 30):

$$r = \frac{d}{1-d}\cdot\frac{365}{N-D}, \qquad r_{2/10\,n30} = \frac{0.02}{0.98}\cdot\frac{365}{20} = 37.24\%.$$

On the U.S. Treasury's 360-day basis the same term is 36.73%. The compounded effective rate $\left(\frac{1}{1-d}\right)^{365/(N-D)} - 1 = 44.6\%$ is shown as a tooltip only.

Break-even discount for paying $\Delta$ days early when cash costs $c$ per year:

$$d^* = 1 - \frac{1}{1 + c\,\Delta/365}, \qquad d^*(c = 8\%,\ \Delta = 30) = 0.6532\%,$$

slightly below the shortcut $c\Delta/365 = 0.6575\%$.

Because the discount applies to the subtotal only, explanations quote the return on the cash actually paid, $\frac{\text{discount\$}}{\text{cash paid}}\cdot\frac{365}{\text{days early}}$, which is below $r$ whenever tax or freight is present.

## 2. Payment options (`optimize/options.py`)

Bill $i$ has a small set of options $k$. Each has a send date (a business day, never before the as-of date), an arrival date, a cash-out day $t_{ik}$ and amount $c_{ik}$, and a value measured against the baseline "pay by bank to arrive on the due date" (cash-out day $t^0_i$, amount $A_i$):

$$v_{ik} = (A_i - c_{ik}) + \text{rewards}_{ik} + y\,c_{ik}\,\frac{t_{ik} - t^0_i}{365} - \text{rail fee}_{ik} - \text{penalty}_{ik},$$

with $y$ = `YIELD_ON_CASH`. Paying later than the baseline earns yield; paying earlier loses it. Options: `BANK_DUE`, `BANK_EARLY` (arrives by the discount deadline; ACH uses the 4-business-day upper bound), `CARD` (charged on the due date, cash leaves on the statement payment date), `CARD_EARLY`, `FINANCE_EARLY` (off by default), `LATE` (15 days late, plus the late fee and a relationship penalty that enters only the objective).

## 3. Forecast (`forecast/fit.py`, `forecast/simulate.py`)

**Fit.** For customer $i$, paid invoices give log days-to-pay $y_{ij}$; invoices still open at the as-of date give log elapsed days $\ell_{ik}$ and are right-censored. The per-customer maximum-likelihood estimate solves

$$(\hat\mu_i, \hat\sigma_i) = \arg\max_{\mu,\sigma}\ \sum_j \left[\log\varphi\!\left(\tfrac{y_{ij}-\mu}{\sigma}\right) - \log\sigma\right] + \sum_k \log\left(1 - \Phi\!\left(\tfrac{\ell_{ik}-\mu}{\sigma}\right)\right).$$

Ignoring the open invoices biases $\hat\mu_i$ low (slow invoices are exactly the ones still open); `tests/unit/test_forecast.py` shows the bias and its correction. Partial pooling with $n_i$ = paid + open invoices and $w_i = n_i/(n_i+\kappa)$:

$$\mu_i = w_i\hat\mu_i + (1-w_i)\mu_{\text{pool}},\qquad \sigma_i = w_i\hat\sigma_i + (1-w_i)\sigma_{\text{pool}},$$

where $\mu_{\text{pool}}$ is the mean of the $\hat\mu_i$ and $\sigma_{\text{pool}}^2 = \sum_i (n_i - 1)\hat\sigma_i^2 / \sum_i (n_i - 1)$ is the within-customer spread. Using the total spread would add between-customer differences.

**Simulation.** In scenario $s$ a common factor $Z_s \sim N(0,1)$ shifts every customer's log-mean:

$$\log D_{sj} = \mu_{c(j)} + \sigma_{\text{macro}} Z_s + \sigma_{c(j)}\varepsilon_{sj}.$$

Equivalently, every delay is multiplied by $e^{\sigma_{\text{macro}} Z_s}$. Without it the independent draws average out and the fan, and the risk bound, are too narrow (`test_common_factor_widens_the_fan`). An invoice outstanding for $e$ days is drawn from the conditional law given $D > e$. With $x = (\ln e - \mu - \sigma_{\text{macro}}Z_s)/\sigma$ and $u \sim U(0,1)$:

$$\varepsilon = \bar\Phi^{-1}\!\big(u\,\bar\Phi(x)\big),$$

i.e. `norm.isf(u * norm.sf(x))`, which stays accurate deep in the tail. Each invoice independently fails to pay within the horizon with probability $p_{\text{no pay}}$.

## 4. The chance-constrained MILP (`optimize/milp.py`)

Let $B_0$ be starting cash, $I_{st}$ cumulative inflows in scenario $s$ through day $t$, $F_t$ cumulative fixed outflows, and $b$ the buffer. Define the headroom

$$R_{st} = B_0 + I_{st} - F_t - b.$$

Variables: $x_{ik}\in\{0,1\}$; $C_t$ = cumulative plan outflow through day $t$; $G_t \ge 0$ = cumulative backstop credit (nondecreasing); $z_s \in\{0,1\}$ = scenario $s$ protected.

$$
\begin{aligned}
\max\ & \textstyle\sum_{i,k} v_{ik}x_{ik} - \kappa_G\,G_T \\
\text{s.t. } & \textstyle\sum_k x_{ik} = 1 && \forall i\\
& C_t = C_{t^-} + \textstyle\sum_{(i,k):\,t_{ik}=t} c_{ik}x_{ik} && \forall t \in \mathcal{T}\\
& G_t \ge G_{t^-} \ge 0 && \forall t\in\mathcal{T}\\
& C_t - G_t \le R_{st} + M_{st}(1 - z_s) && \forall s, t\in\mathcal{T}\\
& \textstyle\sum_s z_s \ge N - K\\
& \textstyle\sum_{k \in \mathcal{K}_g} c_{k} x_{k} \le \text{cap}_g && \forall \text{ capacity groups } g
\end{aligned}
$$

Here $t^-$ is the previous check day. The capacity rows cap card charges per statement cycle and financed principal per 30-day window: card and Flex-style credit move cash later, so the chance constraint alone would allow unlimited credit. Only the inflows are random, every payment option is a fixed outflow, and $G$ does not depend on the scenario. This is the random right-hand-side setting of Luedtke, Ahmed & Nemhauser, so the reductions below are exact.

### 4.1 Check days

**Claim.** Let $\mathcal{T}$ = {day 0} ∪ {every option cash-out day} ∪ {every day on which $R_{st}$ decreases in some scenario}. Enforcing the constraint on $\mathcal{T}$ is equivalent to enforcing it on every day.

**Proof.** Take a day $t \notin \mathcal{T}$ with $t > 0$. No option pays on $t$, so $C_t = C_{t-1}$. $R$ does not decrease on $t$ in any scenario, so $R_{st} \ge R_{s,t-1}$. $G$ is nondecreasing, so $G_t \ge G_{t-1}$. Hence the slack $R_{st} - C_t + G_t \ge R_{s,t-1} - C_{t-1} + G_{t-1}$. By induction the slack on $t$ is at least the slack on the latest check day before it, so the minimum over all days is attained on $\mathcal{T}$. ∎

Weekly checkpoints are *not* exact: they miss the dip right after payroll.

### 4.2 Quantile cut

**Claim.** With at most $K$ unprotected scenarios, $C_t - G_t \le q_t$ is valid, where $q_t$ is the $(K+1)$-th smallest value of $\{R_{st}\}_s$.

**Proof.** At least $K+1$ scenarios have $R_{st} \le q_t$. If $C_t - G_t > q_t$, all of them violate their day-$t$ row. That needs $K+1$ unprotected scenarios, which contradicts $\sum_s z_s \ge N - K$. ∎

### 4.3 Row drop and the tightest big-M

Given the cut, a scenario with $R_{st} \ge q_t$ satisfies $C_t - G_t \le q_t \le R_{st}$ automatically, so its row is dropped. At most $K$ scenarios have $R_{st} < q_t$; for them

$$M_{st} = q_t - R_{st}$$

is the smallest valid big-M. When $z_s = 0$ the row reads $C_t - G_t \le q_t$, already implied by the cut, and any smaller $M$ would cut off feasible plans. Scenarios that appear in no row are protected for free, so their $z_s$ is fixed to 1 and dropped. The cardinality row becomes $\sum_{s\in\mathcal{S}'} z_s \ge |\mathcal{S}'| - K$.

Rows fall from $N\cdot|\mathcal{T}|$ to at most $K\cdot|\mathcal{T}|$, plus one cut per check day. Measured numbers are in `docs/RESULTS.md`. Tests: brute force on tiny instances, and reduced = full model on random instances (`tests/unit/test_milp.py`).

### 4.4 Never trust $z$

HiGHS accepts integers within a tolerance, so a large $M$ times a $z$ of $10^{-7}$ can leak cash that isn't there. After every solve Tempo recomputes every scenario's balances from the chosen payments in integer cents and counts breaches directly (`Plan.breaches`). Those recounts never exceed $K$ (`test_recounted_breaches_never_exceed_k`).

## 5. Out-of-sample certification (`optimize/certify.py`, `optimize/stats.py`)

Sample-average approximation is optimistic: protecting all but $K$ of $N$ sampled scenarios does not bound the breach rate on new scenarios at $K/N$. Seeds: **A** builds the optimizer's $N = 200$ scenarios, **B** (10,000) certifies, **C** (10,000) is used only for reported numbers, and **D** only for the starting-cash calibration.

One-sided Wilson upper bound for $x$ breaches in $n$ scenarios:

$$U = \frac{\hat p + \frac{z^2}{2n} + z\sqrt{\frac{\hat p(1-\hat p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}},\qquad \hat p = x/n.$$

At $z = 1.645$ and $n = 10{,}000$: 464 breaches give $U = 4.9985\%$ (passes 5%); 465 give $5.0088\%$.

The ladder tries $K = 4, 3, 2, 1, 0$ at $N = 200$, then $K = 5$ at $N = 1{,}000$, and stops at the first plan whose seed-B bound is at most $\varepsilon$. Because up to six plans are tested, the seed-B test uses a Bonferroni-adjusted $z = \Phi^{-1}(1 - 0.05/6) = 2.394$. If nothing passes, the plan with the lowest seed-B bound ships and the miss is shown. Seed C is reported with $z = 1.645$ as it comes out.

Certification covers sampling error, not model error: B and C come from the fitted forecast. RESULTS.md therefore also evaluates every policy on seed C drawn with the generator's *true* per-customer laws (this does not test the common factor or the no-pay rate, which stay at their assumed values), and again with the common factor doubled ($\sigma_{\text{macro}} = 0.30$). Seed C's point estimate can exceed seed B's bound: B's bound covers B's rate, and C is an independent draw.

## 6. Marginal value of cash (`optimize/cash_value.py`)

A MILP has no meaningful duals. Fixing the binaries and reading LP duals gives zero on every buffer row, because the protected rows are slack at the integer optimum. Tempo uses a forward difference at the certified $K$ and $N$:

$$\lambda = \frac{\text{obj}(B_0 + \$25{,}000) - \text{obj}(B_0)}{\$25{,}000},\qquad c = y + \lambda\cdot\frac{365}{\text{horizon days}}.$$

A downward step can force the backstop credit on and inflate $\lambda$, so the step goes up. If either solve draws credit, the number is labeled "credit-bound".

## 7. Explanations: the binding reason (`optimize/explain.py`)

For a bill paid on its due date although it has a discount option:

1. **Economics first.** If the best discount option is worth no more than the chosen option after yield, the reason is economic.
2. **Otherwise, recount.** Switch only this bill to its discount option, keep everything else (including credit) fixed, and recount breaches on the optimizer's scenarios. If they exceed $K$, cash binds, and the reason names the first day with a new breach (often payroll). If they don't, the solve stopped within its optimality gap.

The order matters. A tight plan sits at exactly $K$ breaches, so the recount alone would blame cash for nearly every skipped discount.

## 8. Negotiation pricing (`agent/negotiation.py`)

For a vendor without discount terms, the proposed pay date is $P = $ issue $+ 10$ days and $\Delta = T - P$. The offer is

$$d_{\text{offer}} = \lceil d^*(c,\Delta) + 0.25\% \rceil_{0.25\%}.$$

It is verified exactly by adding a hypothetical discount option at $d_{\text{offer}}$ to that bill and re-solving at the base plan's $K$ and $N$. Only offers that Tempo would actually take are ranked, by the value they add.
