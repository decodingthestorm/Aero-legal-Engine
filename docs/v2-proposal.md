# v2.0 High-Level Design — review

**Status: reviewed, partially adopted. Not a specification this codebase is being built
to.**

A "Legal Engine Platform v2.0 HLD" was proposed covering six DAG nodes: deontic
reasoning in Isabelle/HOL, constrained LLM extraction via vLLM/XGrammar, a
semantic-entropy hallucination gate, ZKP circuit compilation via CirC/cvc5,
schema-per-tenant Postgres with RFC 3161 timestamping, and a Stackelberg differential
game simulator.

Two nodes have been adopted and shipped (semantic entropy, v1.9.0; RFC 3161 timestamping,
v1.10.0). Two more are buildable here and remain open. Two cannot be built or verified in this environment. Six defects were
found that are wrong independent of tooling — two of them provably so, and one is a
cross-tenant data leak in the isolation model the spec chose *for* isolation.

This file summarizes rather than reproduces the original: the defect analysis is the
part worth versioning, and a verbatim copy of the source XML would rot without anyone
noticing. Read it as a record of what was assessed and why, not as a plan of record.

---

## Environment reality

Checked directly at review time, not assumed.

| Required by the spec | Status |
|---|---|
| Isabelle/HOL, cvc5, circom, ZoKrates, psql, pgbouncer | absent |
| vllm, xgrammar, torch, transformers, asyncpg/psycopg | absent |
| pyasn1 / pyasn1-modules | absent at review time; **added in v1.10.0** as the `tsp` extra, since it's pure Python with no native extensions |
| GPU | RTX 5070 Ti Laptop, 12 GB — but vLLM is Linux/WSL2 only, and torch's DLLs are blocked here by Windows Application Control |
| z3, numpy, scipy, cryptography, sqlalchemy | present |

---

## The six defects

### 1. The abstention gate could never fire — **fixed in v1.9.0**

The spec gated abstention on semantic entropy over `N=10` sampled generations, with a
threshold of **8.5**.

Entropy over a partition of `N` samples is bounded by `log(N)`, attained only when every
sample forms its own cluster. For `N=10` that ceiling is **log(10) = 2.3026 nats**
(3.3219 bits). The threshold sat roughly 3.7× above it. The gate could not fire under
any input, and its `ABS_01` abstention path was unreachable code.

The failure mode is silent: nothing raises, nothing logs, every input "passes," and the
gate still reads as a safety control in the design document. A gate that always passes
is worse than no gate, because it gets credited.

**Correction, shipped:** `uncertainty/semantic_entropy.py`. `SemanticEntropyGate`
validates its threshold against `max_entropy(n_samples)` at *construction* and refuses
to build an unfireable gate. The spec's own configuration now raises. Default is 1.0
nats, just under `log(3)`. See the README's "Semantic entropy abstention gate."

### 2. The mandated ZKP range check is exponential

`NODE_04` requires range checks of the form `f(e) = ∏(e−i) = 0 mod p`, a polynomial of
degree `2^N`:

| bit width | spec's constraints | bit-decomposition |
|---:|---:|---:|
| 8 | 256 | 9 |
| 32 | 4,294,967,296 | 33 |
| 64 | 1.8 × 10¹⁹ | 65 |

That product form appears in the literature to *motivate* bit-decomposition, not as an
implementation. It is mandated here as a `MUST`.

**Correction:** bit-decomposition (`N+1` constraints) or a lookup argument
(plookup/logUp). Not actionable here — no circom, ZoKrates, or cvc5.

### 3. `SET search_path` behind PgBouncer leaks across tenants

`NODE_05` mandates schema-per-tenant isolation, forbids row-level security, and
specifies session routing as `SET search_path TO 'tenant_<id>', public;` executed
"immediately upon connection acquisition," behind a PgBouncer pooler.

In transaction-pooling mode — the only mode PgBouncer is worth deploying for — server
connections are multiplexed among clients per transaction. A *session-level*
`SET search_path` persists on that server connection after the transaction ends and is
inherited by whichever client is assigned it next. Tenant B then executes against tenant
A's search path.

This is the most serious of the six: it is a cross-tenant data leak in the isolation
mechanism the spec selected *for* isolation, and because RLS is simultaneously forbidden,
the defence-in-depth that would have caught it is removed by the same document.

**Correction:** `SET LOCAL search_path` inside the transaction, or
`set_config('search_path', $1, true)`. Session-pooling mode also works but forfeits the
reason to run PgBouncer at all.

Related: the spec's dynamic `ALTER USER ... CONNECTION LIMIT` load-shedding is a catalog
DDL change triggered by a 150 ms RTT sample, and does not affect already-established
pooled connections.

### 4. `ABS_02` halts on the normal case

The trigger fires when the preference relation `⪰` "yields equal optimality over
conflicting norm worlds."

Åqvist's System E mandates *totalness* of `⪰`, so ties are ubiquitous and `Opt(φ)` is
almost always a multi-world set. As written, the gate fires during ordinary operation.

**Correction:** trigger on `Opt(φ)` containing worlds that *disagree on ψ* — i.e. neither
`O(ψ|φ)` nor `O(¬ψ|φ)` holds. That is the actual normative dilemma.

### 5. `NODE_06` contradicts itself

It mandates "linear-quadratic semiconcave problem structure" **and** a "unique viscosity
solution" computed by implicit finite differences.

If the problem is genuinely LQ, the HJB equation collapses to Riccati ODEs with a smooth
closed-form solution and no viscosity machinery is needed. Viscosity solutions exist
precisely for when the value function *isn't* smooth — non-LQ dynamics, state
constraints, degenerate diffusion. With the jump term and general `b`, `σ`, `γ` the spec
also specifies, it isn't LQ.

Separately, "reduce bilevel optimization to a single stochastic control problem via exact
first-order potential game conditions" is asserted, not established. Stackelberg games do
not generically admit a potential-game reduction.

### 6. It forbids the isolation model this repo already proves

`NODE_05` calls shared-table `tenant_id` columns "strictly forbidden." This codebase uses
exactly that — `StatuteRecord`'s composite `(id, tenant_id)` primary key — and
`tests/integration/test_multi_tenant_isolation.py` verifies it end to end.

Schema-per-tenant is a legitimate alternative, but it is not free: migrations fan out
across N schemas, the catalog bloats at high tenant counts, and it collides with the
pooler the same document mandates (see defect 3). Declaring a working, tested design
forbidden without addressing any of that is not an upgrade.

---

## Node disposition

| Node | Disposition |
|---|---|
| `NODE_03` Semantic entropy gate | **Shipped v1.9.0**, with defect 1 corrected |
| `NODE_05` RFC 3161 timestamping | **Shipped v1.10.0.** `core/timestamper.py`. Anchors the WAL's head hash rather than stamping each entry — the chain already commits backwards, so one token attests the whole log. Verifies status, nonce, imprint, and hash algorithm; deliberately does *not* verify the TSA signature, since `cryptography` exposes no CMS verification API and hand-rolling it would be worse than deferring to `openssl ts -verify`. |
| `NODE_01` Deontic reasoning | **Open, buildable in reduced form.** Isabelle isn't available, but `Opt(φ)` and `O(ψ|φ)` over a *finite* world set with an explicit betterness relation is decidable and directly implementable, checkable against Chisholm's Paradox and gentle murder. Would also fix defect 4. Must be labelled finite-model evaluation, not HOL theorem proving. |
| `NODE_06` Stackelberg simulator | **Open, buildable in reduced form.** Drop the jump term and the potential-game reduction; a 1-D finite-difference HJB validated against the closed-form LQ Riccati solution is real work with numpy/scipy. Resolves defect 5 by construction. |
| `NODE_02` vLLM / XGrammar extraction | **Not buildable.** vLLM has no native Windows support; torch's DLLs are blocked here; 12 GB VRAM won't serve batch `N=256` for a legal-grade model. |
| `NODE_04` ZKP compilation | **Not buildable.** No circom, ZoKrates, or cvc5; Groth16/PLONK also needs a trusted setup. |
| `NODE_05` schema-per-tenant migration | **Not adopted.** See defects 3 and 6. |

---

## Notes on the rest

- **The determinism mandate and `NODE_03` are in tension.** `NODE_02` requires 100%
  token-for-token reproducibility while `NODE_03` requires `N=10` stochastic generations
  at `T=0.8`. Both can hold only if `NODE_03` uses fixed distinct seeds, which the spec
  never states and the test suite never pins.
- **`t_mask ≤ 0.65 µs` and flat latency to `N=256`** are roughly the published XGrammar
  figures. Reasonable as targets; unverifiable here.
- **The Isabelle/HOL direction is real work** (Benzmüller et al.'s LogiKEy embedding
  exists), but it is higher-order logic — undecidable, with no termination guarantee from
  `sledgehammer`. That is a different kind of claim from the EPR fragment's decidability
  guarantee that `formal_logic/` has held since Phase 1, and shouldn't be presented as
  strengthening it.
