"""Self checks for the cube model and the solver.

Run with:  python selftest.py            (quick, a few hundred cubes)
           python selftest.py 5000       (thorough)

No graphics needed, so this also works over a plain terminal.
"""

import random
import sys
import time

import cube as c
import solver


def check_geometry():
    assert c.FACE_COLOUR == {
        "U": c.WHITE,
        "D": c.YELLOW,
        "F": c.GREEN,
        "B": c.BLUE,
        "R": c.RED,
        "L": c.ORANGE,
    }, "the cube must be white-up / green-front / red-right"
    assert c.COLOUR_FACE[c.WHITE] == "U"
    assert c.COLOUR_FACE[c.GREEN] == "F"
    assert c.N_FACELETS == 54
    assert c.is_valid(c.SOLVED), c.validity_error(c.SOLVED)

    for move in c.MOVE_NAMES:
        assert c.apply_moves(c.SOLVED, [move] * 4) == c.SOLVED, f"{move} x4 is not identity"

    # a quarter turn and its inverse cancel, doubles behave like two quarters
    for face in c.FACES:
        assert c.apply_moves(c.SOLVED, [face, face + "'"]) == c.SOLVED
        assert c.apply_moves(c.SOLVED, [face, face]) == c.apply_move(c.SOLVED, face + "2")

    # the "sexy move" is famously of order 6
    sexy = c.parse("R U R' U'")
    assert c.apply_moves(c.SOLVED, sexy * 6) == c.SOLVED, "R U R' U' should have order 6"
    assert c.apply_moves(c.SOLVED, sexy) != c.SOLVED

    # a superflip-ish spot check: 6 sune repetitions restore the cube
    sune = c.parse("R U R' U R U2 R'")
    assert c.apply_moves(c.SOLVED, sune * 6) == c.SOLVED, "sune should have order 6"

    # documented turn directions
    assert c.colour_at(c.apply_move(c.SOLVED, "U"), (0, 1, 1), (0, 0, 1)) == c.FACE_COLOUR["R"], \
        "U must carry the right face colour round to the front"
    assert c.colour_at(c.apply_move(c.SOLVED, "R"), (1, 1, 0), (0, 1, 0)) == c.FACE_COLOUR["F"], \
        "R must carry the front face colour up"

    # notation helpers
    assert c.invert(c.parse("R U2 F'")) == c.parse("F U2 R'")
    assert c.invert(c.invert(c.parse("R U2 F'"))) == c.parse("R U2 F'")
    print("geometry, moves and notation: ok")


def check_states(count, rng):
    for i in range(count):
        state = c.random_state(rng)
        err = c.validity_error(state)
        assert err is None, f"generated state {i} is not solvable: {err}"
        assert c.build_state(*c.decode(state)) == state, "decode/build round trip failed"

    for i in range(count):
        state = c.apply_moves(c.SOLVED, c.random_moves(40, rng))
        assert c.validity_error(state) is None

    # states a real cube cannot reach must be rejected.
    # swapping two whole edge pieces is a single transposition, so it is impossible
    swapped = list(c.SOLVED)
    for d_a, d_b in zip(c.EDGE_DIRS[(0, 1, 1)], c.EDGE_DIRS[(1, 1, 0)]):
        a = c.FACELET_INDEX[((0, 1, 1), d_a)]
        b = c.FACELET_INDEX[((1, 1, 0), d_b)]
        swapped[a], swapped[b] = swapped[b], swapped[a]
    assert not c.is_valid(tuple(swapped)), "swapping two edges should be invalid"

    twisted = list(c.SOLVED)
    corner = (1, 1, 1)
    d0, d1, d2 = c.CORNER_DIRS[corner]
    i0, i1, i2 = (c.FACELET_INDEX[(corner, d)] for d in (d0, d1, d2))
    twisted[i0], twisted[i1], twisted[i2] = twisted[i2], twisted[i0], twisted[i1]
    assert not c.is_valid(tuple(twisted)), "a single twisted corner should be invalid"
    print(f"random states ({count} generated + {count} scrambled): ok")


def check_net():
    """The unfolded net must cover all 54 stickers exactly once."""
    seen = set()
    for face in c.NET_STRING_ORDER:
        for row in range(3):
            for col in range(3):
                pos, direction = c.net_facelet(face, row, col)
                assert direction == c.FACE_NORMAL[face], f"{face} {row},{col} faces the wrong way"
                index = c.FACELET_INDEX[(pos, direction)]
                assert index not in seen, f"{face} {row},{col} is a duplicate"
                seen.add(index)
    assert len(seen) == c.N_FACELETS

    # centres sit in the middle of each block
    for face in c.NET_STRING_ORDER:
        pos, _d = c.net_facelet(face, 1, 1)
        assert sum(1 for v in pos if v) == 1, f"{face} centre is not a centre"

    expected = "".join(letter * 9 for letter in c.NET_STRING_ORDER)
    assert c.facelet_string(c.SOLVED) == expected, "solved cube does not read as solved"

    # Turning one face moves the 12 stickers it shares with its four neighbours
    # into a different face, and leaves its own nine reading the same letter.
    for move in c.MOVE_NAMES:
        turned = c.facelet_string(c.apply_move(c.SOLVED, move))
        changed = sum(1 for a, b in zip(turned, expected) if a != b)
        assert changed == 12, f"{move} changed {changed} facelet letters, expected 12"
    print("unfolded net: covers 54 stickers once each, reads correctly")


def check_solver(count, rng):
    if not solver.tables_ready():
        print("solver: tables not built, skipped (python solver.py --build-tables)")
        return
    assert solver.prepare(), "the tables are there but would not load"

    lengths, times = [], []
    for _ in range(count):
        state = c.apply_moves(c.SOLVED, c.random_moves(25, rng))
        start = time.perf_counter()
        moves = solver.solve(state)
        times.append(time.perf_counter() - start)
        assert c.apply_moves(state, moves) == c.SOLVED, "the solution does not solve the cube"
        lengths.append(len(moves))
    assert max(lengths) <= 22, f"expected short solutions, got up to {max(lengths)}"

    # a cube a few moves from solved must come back with exactly those moves,
    # which two phase on its own does not manage
    assert solver.solve(c.apply_move(c.SOLVED, "R")) == ["R'"]
    assert solver.solve(c.apply_moves(c.SOLVED, ["R", "U"])) == ["U'", "R'"]
    assert solver.solve(c.SOLVED) == [], "a solved cube needs no moves"

    # and an impossible cube is refused rather than searched for ever
    swapped = list(c.SOLVED)
    for d_a, d_b in zip(c.EDGE_DIRS[(0, 1, 1)], c.EDGE_DIRS[(1, 1, 0)]):
        a = c.FACELET_INDEX[((0, 1, 1), d_a)]
        b = c.FACELET_INDEX[((1, 1, 0), d_b)]
        swapped[a], swapped[b] = swapped[b], swapped[a]
    try:
        solver.solve(tuple(swapped))
        raise AssertionError("an impossible cube should not have been solved")
    except solver.SolveError:
        pass

    print(
        f"solver ({count} cubes): all solved. "
        f"moves avg {sum(lengths) / len(lengths):.1f}, max {max(lengths)}; "
        f"time avg {sum(times) / len(times):.2f}s, max {max(times):.2f}s"
    )


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rng = random.Random(12345)
    check_geometry()
    check_net()
    check_states(min(count, 500), rng)
    check_solver(min(count, 30), rng)
    print("all checks passed")


if __name__ == "__main__":
    main()
