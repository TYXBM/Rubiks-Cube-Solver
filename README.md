# Rubik's Cube Solver

A 3D 3×3×3 Rubik's Cube simulator written in Python. Scramble a cube, paint the
stickers to match a physical cube, then watch a short solution animate or step
through it one move at a time.

## Features

- 3D animated cube built with [Ursina](https://www.ursinaengine.org/)
- Legal 20-move scrambles
- Interactive sticker-colour entry with validation of physically impossible states
- Short solutions using Herbert Kociemba's two-phase algorithm
- Auto-play speed control and N/B step-through controls
- Face-centering camera controls with Enter and arrow keys
- Model, solver, and UI regression checks

The colour scheme is the standard western orientation: **white up, green front,
red right**.

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux with a graphics-capable desktop session

## Install

### Windows PowerShell

```powershell
# From this repository folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, use Command Prompt instead:

```bat
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
```

The project uses two pinned dependencies:

- `ursina==8.3.0` — 3D window, input, and UI
- `RubikTwoPhase==1.1.1` — short two-phase Rubik's Cube solutions

## Build solver tables

The two-phase solver uses precomputed pruning tables. Generate them once before
using the solver:

```powershell
python solver.py --build-tables
```

This can take several minutes to roughly half an hour depending on hardware. The
tables are saved outside the repository by default, at:

```text
%LOCALAPPDATA%\rubiks-cube-solver\twophase
```

They are not committed to GitHub.

## Run

```powershell
python main.py
```

| Control | Action |
| --- | --- |
| **Scramble** | Applies 20 legal random moves. |
| **Enter colours** | Blanks non-centre stickers so you can paint a physical cube's state. |
| **Solve (auto play)** | Animates the full short solution at the selected speed. |
| **Solve (step by step)** | Prepares a solution for manual navigation. |
| **N** | Play the next solution move. |
| **B** | Undo the previous solution move. |
| **Stop** | Stops after any currently animating move finishes. |
| **Reset** | Restores the solved cube. |
| Drag | Rotate the camera view. |
| Scroll | Zoom in or out. |
| **Enter** | Square the nearest face to the camera. |
| Arrow keys | Move between adjacent faces after centring one with Enter. |

For a physical cube, position it with the **white centre on top** and the
**green centre in front** before following the displayed moves.

## Entering a physical cube

Click **Enter colours**, choose a colour from the palette, and click the
stickers directly on the 3D cube. The six centre stickers remain fixed because
they define the colour scheme. Use drag, Enter, and arrow keys to reach every
face.

Before solving, the app rejects states a real cube cannot reach, including:

- missing or duplicated colours/pieces
- an individually twisted corner
- an odd number of flipped edges
- mismatched corner and edge permutation parity

## Testing

```powershell
python selftest.py 200
python uicheck.py
```

`selftest.py` validates cube moves, notation, valid states, facelet encoding, and
short solver output. `uicheck.py` drives the live UI to verify animation,
buttons, camera controls, sticker entry, and solve workflows.

## Project structure

```text
cube.py         Cube state, legal moves, facelet encoding, and validation
solver.py       Two-phase solver adapter and short direct-search optimisation
main.py         Ursina app, 3D rendering, animation, and user interaction
selftest.py     Model and solver checks
uicheck.py      End-to-end UI checks
requirements.txt Pinned Python dependencies
```

## Solver notes

For cubes within four moves of solved, the project uses a direct search to return
a provably shortest answer. Other positions use Kociemba's two-phase method and
normally solve in about 20 moves. The two-phase method produces very short
solutions, but is not guaranteed to be mathematically optimal for every cube.


