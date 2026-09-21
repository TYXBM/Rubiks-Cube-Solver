from __future__ import annotations
import contextlib
import io
import os
import sys
import cube as _cube
from cube import MOVE_NAMES, SOLVED

class SolveError(Exception):
    """Raised when the cube cannot be solved, i.e. it is not a real cube state."""

_TABLE_FILES = (
    "conj_twist",
    "conj_ud_edges",
    "move_twist",
    "move_flip",
    "move_slice_sorted",
    "move_u_edges",
    "move_d_edges",
    "move_ud_edges",
    "move_corners",
    "phase1_prun",
    "phase2_prun",
    "phase2_cornsliceprun",
)

_twophase = None 
_twophase_failed = False

def table_folder():
    override = os.environ.get("RUBIKS_TABLE_FOLDER")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "rubiks-cube-solver", "twophase")

def tables_ready():
    folder = table_folder()
    return all(os.path.isfile(os.path.join(folder, name)) for name in _TABLE_FILES)

def _load_twophase(allow_build=False):
    """Import the two phase solver, or return None if its tables are missing."""
    global _twophase, _twophase_failed
    if _twophase is not None:
        return _twophase
    if _twophase_failed:
        return None
    if not allow_build and not tables_ready():
        _twophase_failed = True
        return None
    try:
        folder = table_folder()
        os.makedirs(folder, exist_ok=True)
        import twophase.defs as defs

        defs.FOLDER = folder

        building = not tables_ready()
        with contextlib.nullcontext() if building else contextlib.redirect_stdout(io.StringIO()):
            import twophase.solver as twophase_solver

        _twophase = twophase_solver
        return _twophase
    except Exception as exc:  
        print(f"two phase solver unavailable: {exc}")
        _twophase_failed = True
        return None

def prepare():
    """Load the tables up front, so the first solve is not the slow one."""
    return _load_twophase() is not None

def build_tables():
    """Generate the pruning tables.  Takes roughly half an hour, once ever."""
    folder = table_folder()
    print(f"building two phase tables in {folder}")
    print("this takes about half an hour, and only ever has to happen once")
    if _load_twophase(allow_build=True) is None:
        raise SolveError("table generation failed")
    solve(_cube.apply_move(SOLVED, "R"))  # forces the phase 2 tables too
    print("tables ready")

_SUFFIX_FROM_TWOPHASE = {"": "", "1": "", "2": "2", "3": "'"}


def _parse_twophase(raw):
    moves = []
    for token in raw.split():
        if token.startswith("("):  
            continue
        face, suffix = token[0], token[1:]
        if face not in _cube.FACES or suffix not in _SUFFIX_FROM_TWOPHASE:
            raise SolveError(f"could not read the solver's answer: {raw!r}")
        moves.append(face + _SUFFIX_FROM_TWOPHASE[suffix])
    return moves

def _brute_force(state, max_depth=4):
    """Provably shortest answer for cubes only a few moves from solved.

    The two phase algorithm has to route through its intermediate subgroup, so it
    answers a single R with eight moves.  A plain search is instant at this depth
    and gets those cases exactly right.
    """
    if state == SOLVED:
        return []

    def descend(current, depth, last_face, path):
        for move in MOVE_NAMES:
            if move[0] == last_face:
                continue
            nxt = _cube.apply_move(current, move)
            path.append(move)
            if nxt == SOLVED:
                return list(path)
            if depth > 1:
                found = descend(nxt, depth - 1, move[0], path)
                if found:
                    return found
            path.pop()
        return None

    for depth in range(1, max_depth + 1):
        found = descend(state, depth, "", [])
        if found:
            return found
    return None


def solve(state, max_length=20, timeout=3):
    """Solve `state` in about 20 moves, returning the move list.

    Raises SolveError if the cube is not one a real cube can be in, or if the
    pruning tables have not been built yet.
    """
    state = tuple(state)
    problem = _cube.validity_error(state)
    if problem:
        raise SolveError(problem)

    quick = _brute_force(state)
    if quick is not None:
        return quick

    module = _load_twophase()
    if module is None:
        raise SolveError("the two phase tables are not built (python solver.py --build-tables)")
    raw = module.solve(_cube.facelet_string(state), max_length=max_length, timeout=timeout)
    moves = _parse_twophase(raw)
    if _cube.apply_moves(state, moves) != SOLVED:
        raise SolveError(f"the two phase solver returned a wrong answer: {raw!r}")
    return moves

if __name__ == "__main__":
    if "--build-tables" in sys.argv:
        build_tables()
    else:
        print(f"tables folder: {table_folder()}")
        print(f"ready to solve: {tables_ready()}")
        print("run with --build-tables to generate them (about half an hour, once)")
