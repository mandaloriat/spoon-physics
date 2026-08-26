# The teaching system — five subjects, two machines, one course

**Status:** proposal. Nothing is decided here and nothing is built by it: an ADR records a
decision taken, and this document exists to ask for one — the largest this repository has been
asked to make, which is why it is a proposal and not a commit.
**Occasion:** the founder wants the lab to teach the five subjects he knows best —
**aerodynamics**, **structural mechanics**, **control of systems**, **aeroelasticity**, and
**static & quasistatic electromagnetism** — as *one course*: real teaching, not a drawer of
abstract problems with nothing between them.
**Related:** [the exercise contract](../exercise-contract.md),
[ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt),
the two P45 specifications ([capacitive sensor](../exercises/capacitive-sensor.md),
[adaptive mirror](../exercises/adaptive-mirror.md)),
[mindlin-plate-and-modes](mindlin-plate-and-modes.md),
[instant-incidence](instant-incidence.md).

---

## 1. The wish, restated as commitments

"Real teaching, not abstract or disconnected problems" is a direction, not a test. Turned into
commitments a page can pass or fail:

1. **Every problem is about a machine that exists.** A wing section, a bridge, an
   electromagnet, a deformable mirror. Never "a beam", never "a circuit" — the lab already
   holds this line ([ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt))
   and the pivot extends it from each page to the whole.
2. **Every exercise's answer is somebody's input.** The number a student computes in one
   exercise is consumed by a later one, with its provenance attached. This is the connective
   tissue the current lab has in exactly one place — the mirror
   [depends on](../exercises/adaptive-mirror.md) the sensor — and the pivot generalises that
   one arrow into the organising rule (§4).
3. **Nothing is gated.** A prediction gates nothing and is never marked
   ([ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt));
   a guided path can always be skipped
   ([ADR-021](../architecture-decisions.md#adr-021--an-exercise-page-opens-with-a-lesson-and-the-lesson-can-be-skipped)).
   The course keeps both: every station is enterable cold, with stated defaults where an
   upstream number would have been. Doing the course in order makes it *personal*, never
   merely *possible*.
4. **Two model levels where one would lie.** Ideal flow before viscous
   ([ADR-014](../architecture-decisions.md#adr-014--the-airfoil-exercise-ships-ideal-flow-with-a-kutta-condition-first)),
   quasi-steady before unsteady, linear before saturated — and the page says which level it is
   on and what that level cannot show.
5. **Every number is checkable.** The exercise contract's verification and validity sections
   ([§3, §4](../exercise-contract.md#3-verification-is-a-number)) are not relaxed for the new
   subjects; §5 names a verification anchor for every station before it is built.

The first four are pedagogy; the fifth is the lab's identity. None of them is new — the pivot
is the moment they stop applying to pages one at a time and start applying to the whole.

## 2. What the lab is today, and where it stops

Today the lab is **a set of challenges** — the words of
[ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt)
— and each challenge is good in exactly the way the contract demands: a target, metrics,
verification, a stated domain of validity, a predict-try-improve-compare loop. What the sum of
them is *not* is a course. The airfoil teaches nothing the bridge uses; the bridge teaches
nothing the magnet uses; a student who finishes all three has done three good exercises and
learned no arc. The one arc that exists — sensor feeds mirror — lives in two specifications
nobody can run yet.

The pivot changes the unit of design from the exercise to the **subject**, and the unit of
meaning from the subject to the **machine**: the reason to learn five subjects is that no
machine worth building respects the boundary between them.

## 3. Five subjects, two machines, one course

The five subjects are not five parallel shelves. Three of them are disciplines; the other two
are *meetings* of disciplines, which is why they are taught after — and why they are the
payoff:

| What meets | Subjects | Its name | Where it lands |
|---|---|---|---|
| a wing bends and twists under the very lift it creates | aerodynamics + structures | **static aeroelasticity** | divergence, control reversal |
| …and the flow is fast enough that the motion matters | + unsteady aerodynamics | **flutter** | the typical section |
| …and a controller closes the loop on it | + control | **aeroservoelasticity** | capstone I |
| a mirror holds a commanded shape by force alone, through no contact | structures + control + electromagnetism | **servoelasticity** | capstone II — [the adaptive mirror](../exercises/adaptive-mirror.md) |

So the course converges on **two machines**:

- **The wing** — designed in aerodynamics, stiffened in structures, then asked the
  aeroelastic questions: when does your wing diverge, when does it flutter, and can a
  controller buy the margin back?
- **The mirror** — the P45 deformable mirror already specified in this repository: a floating
  shell, capacitive sensors, voice-coil actuators, a two-level control loop. Structures gives
  its modes, electromagnetism its senses and muscles, control its behaviour.

Aeroelasticity (subject 4) has no station that is not a confluence — that is the honest
statement of what aeroelasticity *is*, and it is the strongest possible answer to
"disconnected problems": two of the five subjects cannot even be stated without the others.

## 4. The rule that connects — the number travels

The mechanism is small and it already half-exists. The run table
([ADR-015](../architecture-decisions.md#adr-015--the-run-table-lives-in-the-browser-and-fenix-spoon-owns-the-record))
keeps attempts per exercise, in the browser, with every input and every residual in the row.
The pivot adds one verb and one noun:

- **Pin.** A kept attempt can be pinned as *the* result of its station — "my wing", "my
  spar", "my sensor". Pinning is exporting the station's few named numbers (three to five,
  never the whole row) together with their provenance: solver id, inputs, residuals, the date.
- **The workbook.** Pinned results live in one site-scoped store beside the per-exercise run
  tables — same `localStorage`, same honesty about clearing the browser, same file export as
  the answer for anyone who wants to keep a course. A downstream station reads the workbook,
  shows *where each imported number came from*, and offers its stated default when the
  workbook has nothing — commitment 3.

What this buys is the sentence a teacher wants to say and the lab currently cannot: **"the
wing you are about to flutter is the wing you designed on Monday."** The lift-curve slope and
aerodynamic centre in the flutter exercise are not a textbook's — they are the ones the
student's own panel-method sweep produced, residuals attached, and the student watched them
get made.

Two rules keep it honest:

- **Provenance is shown, not implied.** A consuming page states what it imported and from
  which pinned attempt; a default is labelled as a default. A stale pin (the profile edited
  after pinning) is visible in its provenance, and the fix offered is *re-run and re-pin*,
  never a silent recompute.
- **Numbers travel; prose does not.** What crosses pages is data with units and provenance.
  Each page still explains itself — the overlap rule of
  [ADR-021](../architecture-decisions.md#adr-021--an-exercise-page-opens-with-a-lesson-and-the-lesson-can-be-skipped)
  applies between stations exactly as it does between chapters and sections.

This is shared state across pages, which is the thing
[ADR-009](../architecture-decisions.md#adr-009--no-front-end-framework-and-no-bundler) said to
watch for. §9 prices it.

## 5. The map

Station states: **built** (page live), **specified** (a `docs/exercises/*.md` exists),
**named** (a contract row and nothing else), **unwritten**. Every unbuilt station is listed
with the verification anchor it would have to keep — commitment 5 — and stations marked *elective*
are on the map but on no machine's critical path.

### 5.1 Aerodynamics

The one subject with its spine already built, guided path included.

| Station | The student… | State | Exports (pins) | Anchor |
|---|---|---|---|---|
| **A1 — the wing section** | shapes a profile and hits a lift target within a moment budget | **built** — [airfoil.md](../exercises/airfoil.md) | *a₀* (lift-curve slope), *x*<sub>ac</sub>, *C*<sub>m,ac</sub>, and the profile itself — all already computed by the sweep ([ADR-014](../architecture-decisions.md#adr-014--the-airfoil-exercise-ships-ideal-flow-with-a-kutta-condition-first)) | as today |
| **A2 — the section at altitude** *(elective)* | meets viscosity: drag, stall, Reynolds | model level 2, specified in [airfoil.md](../exercises/airfoil.md), unbuilt | *C*<sub>l,max</sub>, drag polar | correlation, stated as the weaker claim it is |

A1 needs nothing new except its export block. The
[instant-incidence proposal](instant-incidence.md) becomes more valuable inside a course —
a slider a lesson can lean on — and is otherwise untouched.

### 5.2 Structural mechanics

| Station | The student… | State | Exports (pins) | Anchor |
|---|---|---|---|---|
| **S1 — the bridge** | draws a truss and finds out which member gives way, and that it buckles before it yields | **built** — [truss.md](../exercises/truss.md) | none consumed downstream — S1 is the entry, and its stiffness matrices are the *method* S3 reuses | machine-precision equilibrium, as today |
| **S2 — the bracket** *(elective)* | removes mass from a continuum part while stress stays admissible | **named** — [contract §7 row 2](../exercise-contract.md#7-the-exercises); upstream elasticity solvers exist | mass, safety factor | *K*<sub>t</sub> tables, beam theory, mesh convergence |
| **S3 — the wing box** | sizes a two-spar box: bending and torsional stiffness, and where the shear centre actually is | **unwritten** | *EI*, *GJ*, *x*<sub>ea</sub> → the springs *k*<sub>h</sub>, *k*<sub>θ</sub> of the typical section | thin-walled closed forms (Bredt–Batho), energy consistency |
| **S4 — where it resonates** | asks the structure its frequencies and shapes | blocked on the modal solve — [mindlin-plate-and-modes](mindlin-plate-and-modes.md), ask A | *ω*<sub>h</sub>, *ω*<sub>θ</sub> for the wing; the mode table for the mirror | exact beam/plate modes; for the mirror, the published 50-mode table |

S3 is deliberately small — closed-form physics, a lab solver of the modest kind
[ADR-014](../architecture-decisions.md#adr-014--the-airfoil-exercise-ships-ideal-flow-with-a-kutta-condition-first)
established — because it is one of the two inputs the whole aeroelastic subject stands on.
The shear centre is the point of it: the distance between *x*<sub>ea</sub> and A1's
*x*<sub>ac</sub> **is** the aeroelastic coupling, and a student who has pinned both has
computed the coupling before being told its name.

### 5.3 Control of systems

The subject the lab has none of — and the one whose verification story is the *easiest* to
keep, because low-order LTI systems have exact answers: matrix-exponential discretisation to
machine precision, closed forms for overshoot and settling, stability boundaries by Routh.

| Station | The student… | State | Exports (pins) | Anchor |
|---|---|---|---|---|
| **C1 — hold the gap** | positions one floating control unit of the mirror — a mass with a force actuator and a capacitive reading — against a step command | **unwritten** | the tuned gains, bandwidth, phase margin | exact LTI closed forms; the damping stability boundary the [mirror spec](../exercises/adaptive-mirror.md) already names |
| **C2 — the derivative is a rumour** | meets the reason D-gain fails on a real sensor: noise, and the 40 kHz first-order filter P45 actually runs | **unwritten** (possibly C1's second act rather than its own page) | the filter choice | exact frequency response of the filtered loop |

C1 is a double integrator under PD control — the single most teachable plant there is — and
it is **not abstract**, because it is one control unit of the mirror, with defaults drawn from
the P45 archive exactly as the mirror specification draws them. Its sensor is E2's export;
its actuator constant is E3's; until those exist, the defaults are labelled P45 catalogue
values. It would be the lab's first transient exercise actually built — the first producer
for `series1d`, and the first page where protocol 1.7's "an artifact knows which instant it
holds" stops being unused ([ADR-007](../architecture-decisions.md#adr-007--the-dependency-is-pinned-to-a-commit-in-four-places-checked-by-a-script)).

### 5.4 Aeroelasticity

Every station a confluence; every import a pin from subjects 1–3.

| Station | The student… | State | Consumes | Exports (pins) | Anchor |
|---|---|---|---|---|---|
| **AE1 — divergence** | finds the speed at which their wing twists itself apart | **unwritten** | *a₀*, *x*<sub>ac</sub> (A1); *GJ* → *k*<sub>θ</sub>, *x*<sub>ea</sub> (S3) | *q*<sub>D</sub> | the closed form *q*<sub>D</sub> = *k*<sub>θ</sub>/(*e c*² *a₀*), exactly |
| **AE2 — flutter of the typical section** | finds the speed at which bending and torsion trade energy through the air until the air wins | **unwritten** | everything AE1 did, plus masses and *ω*<sub>h</sub>, *ω*<sub>θ</sub> | *V*<sub>f</sub>, the flutter frequency | quasi-steady limits; AE1's divergence recovered as the zero-frequency root; a published textbook section reproduced to its printed digits |
| **AE3 — control reversal** *(elective)* | discovers the speed above which the aileron works backwards | **unwritten**; wants a flapped profile in the panel method | flap effectiveness (A1 extension) | *q*<sub>R</sub> | closed form, like AE1 |

The typical-section flutter solver is a small dense complex eigenproblem — NumPy-sized, a lab
solver by the standing rule, **not** the upstream modal ask (that ask is for meshed
structures; S4 and the mirror need it, AE2 does not). Two model levels, per commitment 4:
quasi-steady aerodynamics first, Theodorsen second, and the page says what quasi-steady
cannot show. The flutter boundary is a curve over speed — the study object upstream is
building ([#48](https://github.com/mandaloriat/fenix-spoon/issues/48)) is its natural shape,
and `series1d` its natural wire format.

### 5.5 Electromagnetism, static and quasistatic

The subject whose stations are how a machine **senses** and **acts** — which is what connects
it to the other four, and what the current magnetics page (correctly, per
[ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt))
never managed to say in an outcome a student can picture.

| Station | The student… | State | Exports (pins) | Anchor |
|---|---|---|---|---|
| **EM1 — the electromagnet** | makes a magnet pull a plate on a power budget | replacement already specified by the editorial review [ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt) records: non-linear B–H, Maxwell-stress force verified a second way | the force, the ampere-turns, the dissipated power | the acceptance criteria that review set; the verified machinery of [ADR-018](../architecture-decisions.md#adr-018--the-magnetics-exercise-gets-its-own-solver-and-its-challenge-is-not-a-gap-force) underneath |
| **EM2 — the capacitive sensor** | calibrates the mirror's position sensor: sensitivity, linearity, tilt cross-talk | **specified** — [capacitive-sensor.md](../exercises/capacitive-sensor.md); blocked on `axisymmetric2d` ([#100](https://github.com/mandaloriat/fenix-spoon/issues/100)) | *C*₀, d*C*/d*z*, the calibration curve → C1 and the mirror | as its §-by-§ spec already states |
| **EM3 — the voice coil** | designs the mirror's contactless muscle: force per ampere, then what eddy currents do to it | **unwritten**; the static half wants the same axisymmetric kind as EM2, the quasistatic half is the hardest new physics on this map | *k*<sub>f</sub> (N/A), *R*, *L*, the eddy-current lag/damping → C1 and the mirror | force by B·l·i against force by virtual work, two routes; an exact conducting-slab frequency response for the eddy half |

EM3's quasistatic half is where the course touches the founder's own thesis ground — magnetic
couplings in the servoelastic analysis — and it is marked as the hardest deliberately: the
static force constant ships first, alone, and is already enough for C1 and the capstone.

**The current solenoid page** stays exactly what ADR-022 made it: the advanced lab, at its
URL, for readers who already know flux. EM1 is its student-facing face, not its replacement.

**The heat sink** — the one built thing on no subject's list — stops being an orphan by the
connection that was always there: EM1's power budget is a heat budget in disguise. The
winding's I²R must leave through a surface, and [heat-sink.md](../exercises/heat-sink.md) is
the exercise about exactly that. It joins the map as EM1's elective annex ("why the power
budget exists"), keeps its page, its verified solver and its contract row, and is not
promoted into a sixth subject.

### 5.6 The two capstones

| Capstone | Machine | Confluence | State |
|---|---|---|---|
| **The aeroservoelastic wing** | your wing, your box, your controller: move the flutter boundary with a control law on the flap | A1 + S3/S4 + AE2 + C1 | **unwritten**, to be specified in the mirror spec's mould |
| **The adaptive mirror** | the P45 mirror reaching a commanded shape without ringing its own modes | S4 + C1/C2 + EM2 + EM3 | **specified** — [adaptive-mirror.md](../exercises/adaptive-mirror.md); blocked on the plate element and the modal solve ([mindlin-plate-and-modes](mindlin-plate-and-modes.md)) |

Both are transient, both consume half the workbook, and each is the *examination* of its half
of the course in the only honest sense: not a quiz, but the machine finally asked to work.

## 6. What happens to what exists

The pivot modifies the structure; it discards nothing that is built and rewrites nothing that
is specified.

| Today | Under the pivot |
|---|---|
| Homepage: three challenge cards + an advanced shelf ([ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt)) | **a map of five subjects**, each showing its stations in order with honest states (built / specified / planned). Cards stay cards inside a subject; the shelf keeps holding the solenoid |
| [The exercise contract](../exercise-contract.md), nine sections, bench order, predict loop | **unchanged and binding on every station.** The pivot is a layer above the exercise, not a change to it |
| Contract [§7 registry](../exercise-contract.md#7-the-exercises) | stays the registry of pages and page numbers; gains two columns — *exports* and *consumes*. The map (this document's §5, promoted to `docs/curriculum.md` on adoption) owns order and grouping; §7 keeps owning identity |
| Airfoil, bridge pages | become A1 and S1 with an export block each; content otherwise untouched |
| Solenoid page | stays the advanced lab; EM1 (the electromagnet) becomes the subject's front door when built |
| Heat sink | EM1's elective annex (§5.5); page, solver, row all keep |
| Room-modes row | leaves the map (no subject claims it); keeps its registry row, honestly marked |
| Sensor & mirror specifications | become EM2 and capstone II verbatim — they were written as course material before the course existed |
| Guided paths ([ADR-021](../architecture-decisions.md#adr-021--an-exercise-page-opens-with-a-lesson-and-the-lesson-can-be-skipped)) | from "one exercise has one" to **the norm for every station** — a course is exactly the case the guided path was built for |
| Run table ([ADR-015](../architecture-decisions.md#adr-015--the-run-table-lives-in-the-browser-and-fenix-spoon-owns-the-record)) | grows *pin* and the workbook (§4); everything else as is |
| [mindlin-plate-and-modes](mindlin-plate-and-modes.md), [#100](https://github.com/mandaloriat/fenix-spoon/issues/100) | unchanged in content, **raised in priority**: between them they gate S4, EM2, EM3 and both capstones |
| Bilingual seam ([ADR-020](../architecture-decisions.md#adr-020--the-site-is-bilingual-the-repository-is-not)), quotas ([ADR-010](../architecture-decisions.md#adr-010--public-demo-limits-and-what-they-do-not-cover)), no accounts, the name ([ADR-016](../architecture-decisions.md#adr-016--the-product-is-called-spoon-physics)), the solver rule, the pin | untouched |

## 7. The order of work

The spine is built in the order that proves the pivot's one new claim — *the number travels* —
as early as possible, and the site is honest at every intermediate state, exactly as the
README already is about unbuilt rows.

- **Phase 0 — structure, no new physics.** Promote §5 to `docs/curriculum.md`; regroup the
  homepage by subject (touches the e2e assertions that count cards); add export/consume
  blocks to the four existing exercise documents; build the workbook's smallest honest
  version — pin, import with provenance, defaults. Everything in this phase is prose,
  front-end and tests.
- **Phase 1 — the proof arrow.** S3 (the wing box) and AE1 (divergence): two small lab
  solvers with exact closed-form verification, and the first number that actually travels —
  A1's pinned *a₀* and *x*<sub>ac</sub> meeting S3's pinned *k*<sub>θ</sub> and
  *x*<sub>ea</sub> in AE1's import panel. If the workbook mechanism is wrong, this is where
  it is cheapest to find out.
- **Phase 2 — time enters.** C1 (hold the gap) with a lab LTI solver: the first transient
  exercise, the first `series1d` producer, exact discrete-time verification. EM1 can proceed
  in parallel under the acceptance criteria ADR-022 recorded — it shares no machinery with
  the spine.
- **Phase 3 — the payoff.** AE2 (flutter), consuming everything Phase 1 pinned plus S4's
  frequencies where available and quasi-steady estimates where not, labelled as such.
- **Phase 4 — the capstones**, gated on the upstream asks already written: the modal solve
  and the plate element for the mirror, `axisymmetric2d` for EM2/EM3, and a new
  specification for the aeroservoelastic wing written in the mirror spec's mould.

EM advances on its own upstream-gated clock rather than in a phase: each of EM1–EM3 slots in
the moment its gate opens, and nothing on the spine waits for it (C1 runs on labelled P45
defaults until EM2/EM3 replace them).

## 8. What does not change

The exercise contract and its nine sections; the bench
([ADR-017](../architecture-decisions.md#adr-017--an-experiment-page-is-a-bench-not-a-document));
the predict-try-improve-compare loop; no framework and no bundler
([ADR-009](../architecture-decisions.md#adr-009--no-front-end-framework-and-no-bundler)) —
the workbook is one module of functions over `localStorage`, and §9 names the risk; the
public-demo limits; the bilingual seam — every new station is written in `content.json` and
translated, at the stated ~600-keys-and-growing cost; Fenix Spoon as a pinned dependency; and
the rule that the lab writes a solver only when physics a metric needs is missing — every new
solver in §5 passes the same test the first three did.

## 9. Costs, stated plainly

- **A map claims an order, and an order must be defended.** Today any card can be first.
  Under the pivot the site says "this before that", and although defaults keep every gate
  open (commitment 3), the claim itself is editorial work that will sometimes be wrong and
  need moving — the §7 registry's history already shows how often a table's rows shift.
- **The workbook is state shared across pages.** This is the exact hazard
  [ADR-009](../architecture-decisions.md#adr-009--no-front-end-framework-and-no-bundler)
  set a tripwire for. Scope it hard: read at load, written on pin, no live sync between open
  tabs, provenance mandatory — and if it ever wants reactivity, that is the day ADR-009's
  threshold is genuinely crossed and should be *decided*, not drifted past.
- **Two capstones of specification debt, and a long horizon of "specified, not built".**
  The map will show grey stations for a long time. The repository has always preferred an
  honest gap to a pretended page; a course multiplies the number of places that honesty is
  on display.
- **The prose bill doubles and doubles again.** Guided paths for every station, in two
  languages, with the chapter/section overlap kept from drifting by editorial work no script
  can do ([ADR-021](../architecture-decisions.md#adr-021--an-exercise-page-opens-with-a-lesson-and-the-lesson-can-be-skipped)'s
  stated cost, now multiplied by the map).
- **Pins go stale.** A profile edited after pinning makes AE1's imports a lie unless
  provenance is loud. The rule in §4 (show provenance, offer re-run, never recompute
  silently) is the mitigation, and it is a rule about UI discipline, which is the kind that
  erodes.
- **The five-subject claim demotes real work.** Room modes leaves the map, and the heat sink
  — a verified solver and the most interesting physics argument in the repository — becomes
  an annex. Both keep their pages and their rows; neither keeps its billing.

## 10. The decision being asked

Adopt the pivot, adjust it, or refuse it — but as a decision, recorded in an ADR that
supersedes the relevant halves of
[ADR-022](../architecture-decisions.md#adr-022--the-lab-is-a-set-of-challenges-and-the-explanation-comes-after-the-attempt)
(the homepage's shape) while keeping its loop. If adopted, Phase 0 is the first commit:
`docs/curriculum.md`, the homepage map, the export blocks, the workbook — no new physics
until the structure that connects the old physics exists.
