# Game of Life

Conway's Game of Life on the badge, running a 42×45 board at 3 pixels per cell with a catalogue of nine starting patterns. It plays itself, notices when it has nothing left to show, and moves on to the next pattern — so it is happy running unattended on a lanyard all afternoon.

The rules are the whole simulation:

- a live cell with **2 or 3** live neighbours survives
- a live cell with any other neighbour count dies
- a dead cell with **exactly 3** live neighbours is born

## What you should see

- A dark purple board of square cells filling everything above the status strip.
- Cells appear in **conference orange** the generation they are born, then cool to **conference purple** once they have survived a step, then leave a dark ember for one generation on the way out. Anything growing therefore has an orange leading edge and a purple body, which is what makes a glider read as *moving* rather than blinking.
- A two-line status strip: pattern name and speed on top, generation / population and run state underneath.
- The 5 NeoPixels as a population meter — **orange when the population is growing, purple when it is shrinking**, and a slow purple breath once the board settles.

The board is a **torus**. The left edge neighbours the right and the top neighbours the bottom, so a glider that walks off one side comes back in on the other instead of dying in a corner. On a board this small that is the difference between the spaceship patterns running forever and running for eight seconds.

## Controls

- **SW1 (IO1)** — next pattern. `RANDOM SOUP` is a fresh roll every time you land on it.
- **SW2 (IO2)** — cycle speed (2 / 6 / 15 generations per second, then MAX). While paused, this advances exactly one generation.
- **SW3 (IO43)** — pause / resume.
- **SW1 + SW3** — exit to the Launcher menu.

## The pattern catalogue

| Pattern | What it is |
|---|---|
| `CCC` | Three block letters that immediately hollow out and collapse into debris. |
| `RANDOM SOUP` | 30% of cells alive at random. Burns down from ~565 cells to a few dozen. |
| `GLIDER GUN` | Gosper's glider gun — 36 cells wide, and the reason the board is not narrower. Fires gliders until its own wrapped output eventually destroys it. |
| `PULSAR` | Period-3 oscillator. Reaches its loop on generation 3 and beats there forever. |
| `R-PENTOMINO` | Five cells. Chaotic for hundreds of generations. |
| `ACORN` | Seven cells, and the longest runner in the catalogue. |
| `GLIDERS` | Four gliders crossing the torus at once. |
| `SPACESHIPS` | Three lightweight spaceships on a lap of the board. |
| `DIEHARD` | Seven cells that vanish completely on generation 130. The name is the spoiler. |

`SEED_HOLD` shows each freshly loaded pattern for 1.4 seconds before the first step. Block letters and the glider gun are recognisable for about a second and never again, so that pause is the only chance to see what the board started as.

## Settling and auto-advance

Most boards stop being interesting long before they stop changing. After each step the board is compared against the previous three generations, which catches **still lifes (period 1), blinkers (period 2) and the pulsar (period 3)** — where the overwhelming majority of small boards end up. The status line switches to `SETTLED` and the next pattern loads a couple of seconds later.

A period-3 board gets a longer hold (`OSC_HOLD`, 9 s) because that means the pulsar and it is worth watching. Period 2 is usually just leftover blinkers and gets the short hold.

Anything with a longer period — a glider circling the torus — is genuinely still moving, so it deliberately does not count as settled. Those get moved along by `PATTERN_TIMEOUT` (90 s) instead.

## Code design

- **One flat `bytearray`, not a list of rows.** Indexed `y * GRID_W + x`. Slicing a bytearray is a native memcpy and comparing two of them is a native compare, and both are used heavily — clearing the board, detecting an empty row, and cycle detection are all single native calls rather than interpreted loops.

- **Neighbour counting in two passes.** The naive version does eight lookups per cell. Instead, pass one fills `tri[y][x]` with the number of live cells in the three-wide window centred on each cell; pass two computes `tri[y-1][x] + tri[y][x] + tri[y+1][x] - cell`. Three lookups instead of eight, and the horizontal sums are shared between the three rows that need them.

- **Wrapping falls out of Python's negative indexing.** `tri[y - 1]` at `y == 0` is `tri[-1]`, the last row, which is exactly the torus neighbour. Only the `y + 1` edge needs an explicit check.

- **Pass two writes back into `grid` as it goes**, with no second buffer. That is safe precisely because `tri` was built from the old grid and nothing in pass two reads a neighbour's new state.

- **Empty rows are skipped by native compare.** `row == ZERO_ROW` costs one memcmp and skips 42 interpreted iterations. For the glider gun most of the board is empty most of the time, so this is most of the speed.

- **`ember_row` exists because the skip would otherwise be wrong.** A cell that died is drawn as an ember and must be cleared on the *next* step — which is exactly the step the all-dead-row skip wants to take. The flag forces one more pass over any row that still has an ember on it.

- **One bitmap pixel per cell, magnified by `displayio`.** The bitmap is 42×45, not 126×135, sitting in a `Group(scale=CELL)`. The scaling happens in native code, so a cell change costs exactly one bitmap write however large the cells are drawn. Changing `CELL` costs nothing at runtime.

- **Only changed cells are painted.** `drawn[]` tracks what is actually in the bitmap, so a settled board does almost no drawing work at all.

- **Labels are only assigned when the text changes.** Setting `Label.text` re-renders glyphs; at MAX speed the generation counter changes every frame and the pattern name never does.

- **`display.refresh()` is called only when something moved**, and the loop sleeps 5 ms when it did not, so a paused board is not spinning the CPU.

- **Debounce by timestamp, never `time.sleep()`.** Same approach as `samples/Doomish` — nothing in the loop is allowed to block.

## Configuration

Everything worth changing is in the `CONFIGURATION` block at the top: `ROTATION` (portrait or landscape — the board re-derives its size from `display.width`/`display.height`, so nothing else needs touching), `CELL`, `DENSITY`, the `SPEEDS` table, the auto-advance timings, and the colours.

`STRIP_H` is 24 for a reason: a `terminalio` label occupies a 12-pixel box including descender space, so two lines need 24 and anything less clips the lower one.

## Verified in the simulator

Developed against `sim/` — the rule engine was cross-checked cell-for-cell against a naive 8-neighbour reference implementation over 150 generations of random boards, including the painted colour of every cell. `DIEHARD` vanishing on generation 130 matches the textbook value, which is a good independent check that the neighbour arithmetic is right.

Not yet run on real hardware. The simulator says nothing useful about frame rate on the ESP32-S3 (see `sim/README.md`); if the badge turns out to be slower than hoped, raise `CELL` to 4 — that drops the board from 1890 cells to 1024 and costs nothing but chunkier pixels.
