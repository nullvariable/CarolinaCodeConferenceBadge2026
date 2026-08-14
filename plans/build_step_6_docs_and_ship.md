# Build step 6: docs and ship

**Deliverable:** the work is documented to the repo's standard, committed, and
pushed to Doug's fork.

**Depends on:** steps 1-4. Step 5 optional. **Blocks:** nothing.

Read `plans/build_overview.md` first.

## Git state

`origin` is `nullvariable/CarolinaCodeConferenceBadge2026` (Doug's fork).
`upstream` is `circuitboardmedics/CarolinaCodeConferenceBadge2026`.
`main` tracks `origin/main`.

**Never push to `upstream`.** It is push-capable in git config but it is not
ours. `HANDOFF.md:60` is explicit about this.

Confirm before the first push that `.env`, `relay/relay.env`, `settings.toml`,
and `sim/.venv/` are all ignored. The Ollama key is a bare 57-character value in
`.env` at the repo root with no variable name. `.gitignore` covers it via
`*.env`, but verify with `git check-ignore -v .env` rather than trusting it.

## `samples/Doomish/README.md`

Match the house format exactly. Every existing sample README has:

1. `# Title`
2. One-paragraph pitch
3. `## Configuration` when there are editable constants (there are: `BADGE_ID`,
   `RELAY_HOST`, `VIEW_MODE`, `ROTATION`, the map)
4. `## What you should see` -- bulleted, describes the visual result
5. `## Controls` -- markdown table with `SW1 (IO1)` style rows
6. `## Code design` -- bulleted, each bullet a **bolded technique name** followed
   by the rationale

For `## Code design`, the bullets worth writing:

* **Two loops at different speeds** -- why the split exists and what it
  demonstrates
* **OODA structure** -- the four functions map to `plans/gameplay.md`
* **Directives bias, they do not command** -- the weighting model, and why
  reflexes are never gated behind the network
* **Fire-and-forget UDP broadcast** -- why not HTTP (`adafruit_requests` blocks
  for ~1 s and would freeze the render loop), and why broadcast solves discovery
* **Graceful degradation** -- no wifi, no relay, no API key all still play
* **Precomputed trig tables** -- no `math.sin` in the render loop
* **The `VIEW_MODE` escape hatch** -- one constant swaps 3D for top-down

This README is likely to be read by people at the conference. It should be
honest about what the badge is doing rather than overselling it.

**State how much of it was AI-written.** That is the point Doug is making all
week, and a sample app that quietly hides its provenance undercuts the talk.

## Root `README.md`

Add one line to the tree at `README.md:68-77`, alphabetical, description column
aligned with the existing entries. That plus the folder is all the Launcher
needs; nothing else registers a sample.

## `relay/README.md`

Already written and already carries the measured benchmark table. Update it if
step 5 shipped: add the `--dashboard` flag, the port, and a line in the config
table.

## Commits

Group into reviewable commits rather than one dump:

1. `relay: UDP relay, fake badge, Pi setup docs`
2. `relay: fix empty-content failure, add directive normalisation` -- the
   `num_predict` and enum findings both belong in the message body, they are the
   non-obvious part
3. `sim: run badge samples on the desktop`
4. `samples/Doomish: raycaster with two-loop AI`
5. `relay: dashboard` (if built)
6. `docs: build plans` -- the `plans/` folder

Real messages. The `num_predict` one in particular should say what was wrong and
how it presented, because the symptom (empty string, no error) is not something
anyone would guess from the code.

## Before pushing

* `git status` clean except intended files
* `python3 -c "import ast; ast.parse(open('samples/Doomish/code.py').read())"`
  passes. There is no linter for CircuitPython here, so a syntax check is the
  floor.
* The sample runs in the simulator from a clean shell
* No absolute paths, no `192.168.1.54`, no SSID, and no key anywhere in tracked
  files. Grep for all four.
* `relay/relay.py` still runs with `--mock` and no key present

## Verification

1. `git log --oneline` reads as a story someone else could follow.
2. `git push origin main` succeeds.
3. Clone the fork fresh to a temp dir. `sim/run.py Doomish` works after only
   creating the venv and installing the three pip packages. If it does not, the
   README is missing a step.
4. `git remote -v` still shows `upstream` untouched, and `git log upstream/main`
   is unchanged.
