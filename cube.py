from __future__ import annotations
import random
from itertools import product

# Colour scheme: white-up / yellow-down, with green front and red right.
# This is the standard western scheme: white opposite yellow, green opposite
# blue, and red opposite orange.

# colours and faces

YELLOW, WHITE, GREEN, BLUE, ORANGE, RED = "Y", "W", "G", "B", "O", "R"
COLOURS = (YELLOW, WHITE, GREEN, BLUE, ORANGE, RED)

FACES = ("U", "D", "F", "B", "R", "L")

FACE_NORMAL = {
    "U": (0, 1, 0),
    "D": (0, -1, 0),
    "F": (0, 0, 1),
    "B": (0, 0, -1),
    "R": (1, 0, 0),
    "L": (-1, 0, 0),
}
NORMAL_FACE = {v: k for k, v in FACE_NORMAL.items()}

FACE_COLOUR = {
    "U": WHITE,
    "D": YELLOW,
    "F": GREEN,
    "B": BLUE,
    "R": RED,
    "L": ORANGE,
}
COLOUR_FACE = {v: k for k, v in FACE_COLOUR.items()}

# A clockwise quarter turn of each face, as a map on vectors.  Clockwise means
# clockwise as seen from outside that face.  Sanity checks: U sends F -> L,
# R sends F -> U, F sends U -> R.
ROT = {
    "U": lambda v: (-v[2], v[1], v[0]),
    "D": lambda v: (v[2], v[1], -v[0]),
    "F": lambda v: (v[1], -v[0], v[2]),
    "B": lambda v: (-v[1], v[0], v[2]),
    "R": lambda v: (v[0], v[2], -v[1]),
    "L": lambda v: (v[0], -v[2], v[1]),
}


def _axis(vec):
    """Index of the single non-zero component of a face normal."""
    return next(i for i in range(3) if vec[i] != 0)

# cubies and facelets

_COORDS = (-1, 0, 1)

CUBIE_POSITIONS = tuple(
    p for p in product(_COORDS, repeat=3) if p != (0, 0, 0)
)
CORNER_POSITIONS = tuple(p for p in CUBIE_POSITIONS if sum(1 for c in p if c) == 3)
EDGE_POSITIONS = tuple(p for p in CUBIE_POSITIONS if sum(1 for c in p if c) == 2)
CENTRE_POSITIONS = tuple(p for p in CUBIE_POSITIONS if sum(1 for c in p if c) == 1)

def _dirs_at(pos):
    """Outward face directions of the cubie at `pos`."""
    dirs = []
    for i in range(3):
        if pos[i]:
            d = [0, 0, 0]
            d[i] = pos[i]
            dirs.append(tuple(d))
    return tuple(dirs)

DIRS_AT = {p: _dirs_at(p) for p in CUBIE_POSITIONS}

# Facelets, grouped face by face.  The order only has to be consistent.
FACELETS = []
for _f in FACES:
    _n = FACE_NORMAL[_f]
    _ax = _axis(_n)
    _others = [i for i in range(3) if i != _ax]
    for _a in _COORDS:
        for _b in _COORDS:
            _p = [0, 0, 0]
            _p[_ax] = _n[_ax]
            _p[_others[0]] = _a
            _p[_others[1]] = _b
            FACELETS.append((tuple(_p), _n))
FACELETS = tuple(FACELETS)
FACELET_INDEX = {fl: i for i, fl in enumerate(FACELETS)}
N_FACELETS = len(FACELETS)  # 54

SOLVED = tuple(FACE_COLOUR[NORMAL_FACE[d]] for (_p, d) in FACELETS)

# moves

def _rot(face, vec, times):
    for _ in range(times):
        vec = ROT[face](vec)
    return vec

def _face_perm(face, times):
    """Permutation `perm` with new_state[i] = old_state[perm[i]]."""
    normal = FACE_NORMAL[face]
    ax = _axis(normal)
    perm = list(range(N_FACELETS))
    for src, (pos, d) in enumerate(FACELETS):
        if pos[ax] == normal[ax]:  # cubie belongs to the turning slice
            dest = FACELET_INDEX[(_rot(face, pos, times), _rot(face, d, times))]
            perm[dest] = src
    return tuple(perm)

MOVE_PERM = {}
for _f in FACES:
    MOVE_PERM[_f] = _face_perm(_f, 1)
    MOVE_PERM[_f + "2"] = _face_perm(_f, 2)
    MOVE_PERM[_f + "'"] = _face_perm(_f, 3)

MOVE_NAMES = tuple(MOVE_PERM)

_QUARTERS = {"": 1, "2": 2, "'": 3}
_SUFFIX = {1: "", 2: "2", 3: "'"}

def apply_move(state, move):
    perm = MOVE_PERM[move]
    return tuple([state[i] for i in perm])

def apply_moves(state, moves):
    for move in moves:
        state = tuple([state[i] for i in MOVE_PERM[move]])
    return state

def parse(moves):
    """'R U2 F' -> ['R', 'U2', 'F'].  Lists pass straight through."""
    if isinstance(moves, str):
        return moves.split()
    return list(moves)

def invert(moves):
    out = []
    for move in reversed(moves):
        out.append(move[0] + _SUFFIX[4 - _QUARTERS[move[1:]]])
    return out

def colour_at(state, pos, direction):
    return state[FACELET_INDEX[(pos, direction)]]

# the unfolded net

NET_STRING_ORDER = ("U", "R", "F", "D", "L", "B")
NET_BLOCKS = {  # (column, row) of each face on the net, measured in faces
    "U": (1, 0),
    "L": (0, 1),
    "F": (1, 1),
    "R": (2, 1),
    "B": (3, 1),
    "D": (1, 2),
}


def net_facelet(face, row, col):
    """Which sticker sits at `row`, `col` of `face` on the unfolded net."""
    if face == "U":
        pos = (col - 1, 1, row - 1)
    elif face == "D":
        pos = (col - 1, -1, 1 - row)
    elif face == "F":
        pos = (col - 1, 1 - row, 1)
    elif face == "B":
        pos = (1 - col, 1 - row, -1)
    elif face == "R":
        pos = (1, 1 - row, 1 - col)
    elif face == "L":
        pos = (-1, 1 - row, col - 1)
    else:
        raise ValueError(f"no such face: {face}")
    return pos, FACE_NORMAL[face]

def facelet_string(state):
    """The 54 character URFDLB string used by standard cube solvers."""
    letters = []
    for face in NET_STRING_ORDER:
        for row in range(3):
            for col in range(3):
                pos, direction = net_facelet(face, row, col)
                letters.append(COLOUR_FACE[state[FACELET_INDEX[(pos, direction)]]])
    return "".join(letters)


def is_solved(state):
    return tuple(state) == SOLVED

# cubie level view: needed to build random states that are actually solvable

def _det(a, b, c):
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )

def _corner_dirs(pos):
    """The three directions of a corner slot, y first, in right handed order.

    Using the same handedness for every corner is what makes "total twist is a
    multiple of 3" a genuine invariant of the cube.
    """
    dirs = DIRS_AT[pos]
    vertical = next(d for d in dirs if d[1])
    a, b = [d for d in dirs if not d[1]]
    if _det(vertical, a, b) < 0:
        a, b = b, a
    return (vertical, a, b)

def _edge_dirs(pos):
    """Both directions of an edge slot, reference direction first.

    Reference direction is the U/D one for the top and bottom layers and the
    F/B one for the middle layer, the standard convention under which "total
    number of flipped edges is even" is invariant.
    """
    dirs = DIRS_AT[pos]
    ref = next((d for d in dirs if d[1]), None)
    if ref is None:
        ref = next(d for d in dirs if d[2])
    other = next(d for d in dirs if d != ref)
    return (ref, other)

CORNER_SLOTS = CORNER_POSITIONS
EDGE_SLOTS = EDGE_POSITIONS
CORNER_DIRS = {p: _corner_dirs(p) for p in CORNER_SLOTS}
EDGE_DIRS = {p: _edge_dirs(p) for p in EDGE_SLOTS}
# Colours of each piece, listed in the direction order of its home slot.
CORNER_PIECE = {p: tuple(FACE_COLOUR[NORMAL_FACE[d]] for d in CORNER_DIRS[p]) for p in CORNER_SLOTS}
EDGE_PIECE = {p: tuple(FACE_COLOUR[NORMAL_FACE[d]] for d in EDGE_DIRS[p]) for p in EDGE_SLOTS}
_CORNER_BY_COLOURS = {frozenset(v): i for i, (_k, v) in enumerate(CORNER_PIECE.items())}
_EDGE_BY_COLOURS = {frozenset(v): i for i, (_k, v) in enumerate(EDGE_PIECE.items())}

def build_state(corner_perm, corner_twist, edge_perm, edge_flip):
    """Assemble a facelet state from a cubie level description.

    corner_perm[i] is the index of the piece sitting in slot i, and so on.
    """
    state = list(SOLVED)
    for slot_i, slot in enumerate(CORNER_SLOTS):
        dirs = CORNER_DIRS[slot]
        cols = CORNER_PIECE[CORNER_SLOTS[corner_perm[slot_i]]]
        twist = corner_twist[slot_i]
        for j, d in enumerate(dirs):
            state[FACELET_INDEX[(slot, d)]] = cols[(j - twist) % 3]
    for slot_i, slot in enumerate(EDGE_SLOTS):
        dirs = EDGE_DIRS[slot]
        cols = EDGE_PIECE[EDGE_SLOTS[edge_perm[slot_i]]]
        flip = edge_flip[slot_i]
        for j, d in enumerate(dirs):
            state[FACELET_INDEX[(slot, d)]] = cols[(j + flip) % 2]
    return tuple(state)

def decode(state):
    """Inverse of build_state.  Raises ValueError if the stickers make no sense."""
    corner_perm, corner_twist, edge_perm, edge_flip = [], [], [], []
    for slot in CORNER_SLOTS:
        dirs = CORNER_DIRS[slot]
        found = [state[FACELET_INDEX[(slot, d)]] for d in dirs]
        key = frozenset(found)
        if len(key) != 3 or key not in _CORNER_BY_COLOURS:
            raise ValueError(f"no such corner piece: {found}")
        piece = _CORNER_BY_COLOURS[key]
        cols = CORNER_PIECE[CORNER_SLOTS[piece]]
        twist = next(t for t in range(3) if all(found[j] == cols[(j - t) % 3] for j in range(3)))
        corner_perm.append(piece)
        corner_twist.append(twist)
    for slot in EDGE_SLOTS:
        dirs = EDGE_DIRS[slot]
        found = [state[FACELET_INDEX[(slot, d)]] for d in dirs]
        key = frozenset(found)
        if len(key) != 2 or key not in _EDGE_BY_COLOURS:
            raise ValueError(f"no such edge piece: {found}")
        piece = _EDGE_BY_COLOURS[key]
        cols = EDGE_PIECE[EDGE_SLOTS[piece]]
        flip = 0 if found[0] == cols[0] else 1
        edge_perm.append(piece)
        edge_flip.append(flip)
    return corner_perm, corner_twist, edge_perm, edge_flip

def _parity(perm):
    seen = [False] * len(perm)
    parity = 0
    for i in range(len(perm)):
        if seen[i]:
            continue
        j, length = i, 0
        while not seen[j]:
            seen[j] = True
            j = perm[j]
            length += 1
        parity ^= (length - 1) & 1
    return parity

def validity_error(state):
    """None if `state` is a state a real cube can actually be in, else why not."""
    state = tuple(state)
    if len(state) != N_FACELETS:
        return "wrong number of facelets"
    for colour in COLOURS:
        if state.count(colour) != 9:
            return f"colour {colour} appears {state.count(colour)} times, expected 9"
    for pos in CENTRE_POSITIONS:
        d = DIRS_AT[pos][0]
        if state[FACELET_INDEX[(pos, d)]] != FACE_COLOUR[NORMAL_FACE[d]]:
            return "centres do not match the colour scheme"
    try:
        cp, co, ep, eo = decode(state)
    except ValueError as exc:
        return str(exc)
    if sorted(cp) != list(range(8)):
        return "a corner piece appears twice"
    if sorted(ep) != list(range(12)):
        return "an edge piece appears twice"
    if sum(co) % 3:
        return "a corner is twisted (total twist is not a multiple of 3)"
    if sum(eo) % 2:
        return "an edge is flipped (odd number of flipped edges)"
    if _parity(cp) != _parity(ep):
        return "two pieces are swapped (corner and edge permutation parity differ)"
    return None

def is_valid(state):
    return validity_error(state) is None

def random_state(rng=None):
    """A uniformly random, guaranteed solvable cube state.

    Pieces are placed at random, then the three physical constraints of a real
    cube are enforced: matching permutation parity, total corner twist a
    multiple of three, an even number of flipped edges.
    """
    rng = rng or random
    corner_perm = rng.sample(range(8), 8)
    edge_perm = rng.sample(range(12), 12)
    if _parity(corner_perm) != _parity(edge_perm):
        edge_perm[0], edge_perm[1] = edge_perm[1], edge_perm[0]
    corner_twist = [rng.randrange(3) for _ in range(7)]
    corner_twist.append(-sum(corner_twist) % 3)
    edge_flip = [rng.randrange(2) for _ in range(11)]
    edge_flip.append(sum(edge_flip) % 2)
    return build_state(corner_perm, corner_twist, edge_perm, edge_flip)

def random_moves(count=25, rng=None):
    """A random move sequence, no two consecutive turns on the same face."""
    rng = rng or random
    moves, previous = [], None
    while len(moves) < count:
        move = rng.choice(MOVE_NAMES)
        if move[0] == previous:
            continue
        moves.append(move)
        previous = move[0]
    return moves
