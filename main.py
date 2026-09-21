from __future__ import annotations
import sys
from collections import deque
from dataclasses import dataclass
from functools import partial
from ursina import (
    Button,
    Entity,
    Slider,
    Text,
    Ursina,
    Vec3,
    camera,
    color,
    destroy,
    mouse,
    time,
    window,
)
from ursina.shaders.unlit_shader import unlit_shader
import cube
import solver


BLANK = "-"  # a sticker you have not painted yet

STICKER_COLOUR = {
    cube.YELLOW: color.hex("#f5d130"),
    cube.WHITE: color.hex("#f4f4f4"),
    cube.GREEN: color.hex("#1aa64b"),
    cube.BLUE: color.hex("#1f5ed0"),
    cube.ORANGE: color.hex("#eb811b"),
    cube.RED: color.hex("#cd2233"),
    BLANK: color.hex("#c2c8d0"),
}
PAINT_ORDER = (cube.YELLOW, cube.WHITE, cube.GREEN, cube.BLUE, cube.ORANGE, cube.RED)

BODY_COLOUR = color.hex("#0e1013")
BACKGROUND = color.hex("#181c22")
PANEL_TEXT = color.hex("#d7dde5")
DIM_TEXT = color.hex("#8892a0")
ACCENT = color.hex("#f5d130")
BUTTON_COLOUR = color.hex("#252b34")
WARNING = color.hex("#ff9a8a")

COLOUR_NAMES = {
    cube.YELLOW: "yellow",
    cube.WHITE: "white",
    cube.GREEN: "green",
    cube.BLUE: "blue",
    cube.ORANGE: "orange",
    cube.RED: "red",
}

ORIENT_HINT = "Position your cube with white center on top and green center in front"
STEP_HINT = "Click N/B to see next/previous move"
PAINT_HINT = "Pick a colour, then click the stickers. Drag to turn the cube around."

SCRAMBLE_LENGTH = 20

STEP_MOVE_TIME = 0.22  # a move you asked for with N or B
AUTO_SPEED_MIN = 0.4  # moves per second
AUTO_SPEED_MAX = 8.0
AUTO_SPEED_DEFAULT = 1.6

DRAG_SENSITIVITY = 260  # degrees per screen unit of mouse travel
VIEW_SMOOTHING = 16  # higher follows the mouse more tightly, lower glides more
MAX_PITCH = 85  # stops the cube tumbling over the poles

@dataclass
class Step:
    """One queued turn, with enough context to narrate it."""

    move: str
    duration: float | None = None  # None means "use the auto play speed"
    index: int = 0
    total: int = 0

#ursina

SELF_CHECK = "--check" in sys.argv

if solver.prepare():
    print("solver: two phase, shortest solutions")
else:
    print("solver: NOT READY. Run 'python solver.py --build-tables' once (about half")
    print("        an hour) to generate the pruning tables it needs.")

app = Ursina(
    title="Rubik's Cube Solver",
    size=(1280, 720),
    borderless=False,
    vsync=not SELF_CHECK,  # the self check steps frames as fast as it can
    development_mode=False,
)
window.color = BACKGROUND
window.fps_counter.enabled = False
window.entity_counter.enabled = False
window.collider_counter.enabled = False

camera.position = (0, 0, -10)
camera.rotation = (0, 0, 0)


def to_render(vec):
    """Model space is right handed with +z towards the viewer, ursina's is not."""
    return (vec[0], vec[1], -vec[2])


def _calibrate_rotation():
    """Measure which way ursina rotates about each axis, instead of assuming."""
    measured = {}
    for axis, probe in (("x", (0, 1, 0)), ("y", (1, 0, 0)), ("z", (1, 0, 0))):
        pivot = Entity()
        child = Entity(parent=pivot, position=Vec3(*probe))
        setattr(pivot, "rotation_" + axis, 90)
        result = child.world_position
        measured[axis] = (probe, (round(result[0]), round(result[1]), round(result[2])))
        destroy(child)
        destroy(pivot)
    return measured


ROTATION_CALIBRATION = _calibrate_rotation()

def resting_view():
    """(pitch, yaw) for a three quarter view of the white, green and red faces."""
    _probe, moved_up = ROTATION_CALIBRATION["x"]
    _probe, moved_right = ROTATION_CALIBRATION["y"]
    pitch = 26 if moved_up[2] < 0 else -26  # bring the top face towards the camera
    yaw = 34 if moved_right[2] < 0 else -34  # and the right face round to it
    return pitch, yaw

def rotation_for(move):
    """(axis letter, signed degrees) that turns `move` the way the model does."""
    face = move[0]
    quarters = {"": 1, "2": 2, "'": 3}[move[1:]]
    axis_vec = to_render(cube.FACE_NORMAL[face])
    axis = "xyz"[next(i for i in range(3) if axis_vec[i])]

    probe, measured = ROTATION_CALIBRATION[axis]
    wanted = to_render(cube.ROT[face](to_render(probe)))
    sign = 1 if tuple(wanted) == tuple(measured) else -1
    if quarters == 2:
        return axis, 180.0
    return axis, sign * 90.0 * (1 if quarters == 1 else -1)

def invert_move(move):
    return cube.invert([move])[0]

def paint_button(button, colour):
    """Buttons cache tints from their starting colour, so set all three."""
    button.color = colour
    button.highlight_color = colour.tint(0.25)
    button.pressed_color = colour.tint(-0.2)

class Simulator:
    IDLE, AUTO, STEP = "idle", "auto", "step"

    def __init__(self):
        self.state = cube.SOLVED
        self.queue: deque[Step] = deque()
        self.pending = None  # action waiting for the turn in flight to finish

        self.solution = None  # flat list of moves for self.solution_state
        self.solution_state = None
        self.cursor = 0  # how many solution moves have been played
        self.mode = self.IDLE

        self.current = None  # Step being animated
        self.active_duration = STEP_MOVE_TIME
        self.pivot = None
        self.pivot_axis = ""
        self.pivot_angle = 0.0
        self.elapsed = 0.0

        self.dragging = False
        self.drag_moved = False
        self.pressed_on = None
        self.face_view = None  # the face being looked at straight on, if any

        self.editing = False
        self.paint_state = list(cube.SOLVED)
        self.paint_colour = cube.YELLOW

        self.top_message = ""
        self.bottom_message = ""
        self.scramble_sequence = []

        self._build_cube()
        self._build_ui()
        self._build_paint_ui()
        self.repaint()
        self.refresh_text()

    def _build_cube(self):
        """Camera rig: pitch holds yaw holds the cube, which gives a turntable.

        Nesting them this way means a horizontal drag always spins the cube about
        its own vertical axis and a vertical drag always tips it towards or away
        from you, whatever angle it is already at.
        """
        pitch, yaw = resting_view()
        self.pitch_pivot = Entity(rotation_x=pitch)
        self.yaw_pivot = Entity(parent=self.pitch_pivot, rotation_y=yaw)
        self.root = Entity(parent=self.yaw_pivot)
        self.pitch, self.yaw = float(pitch), float(yaw)
        self.target_pitch, self.target_yaw = float(pitch), float(yaw)

        # an invisible copy of the rig, for working out angles without moving the
        # real one: whatever ursina's rotation conventions are, this obeys them
        self.probe_pitch = Entity()
        self.probe_yaw = Entity(parent=self.probe_pitch)
        self.probe_point = Entity(parent=self.probe_yaw)

        self.cubies = {}
        self.stickers = [None] * cube.N_FACELETS
        self.sticker_index = {}  # entity -> facelet index, for painting

        for pos in cube.CUBIE_POSITIONS:
            cubie = Entity(
                parent=self.root,
                model="cube",
                color=BODY_COLOUR,
                shader=unlit_shader,
                position=Vec3(*to_render(pos)),
                scale=0.96,
            )
            self.cubies[pos] = cubie
            for direction in cube.DIRS_AT[pos]:
                scale = [0.84, 0.84, 0.84]
                scale[next(i for i in range(3) if direction[i])] = 0.06
                sticker = Entity(
                    parent=cubie,
                    model="cube",
                    shader=unlit_shader,
                    color=color.black,
                    position=Vec3(*to_render(direction)) * 0.5,
                    scale=Vec3(*scale),
                )
                index = cube.FACELET_INDEX[(pos, direction)]
                self.stickers[index] = sticker
                self.sticker_index[sticker] = index

    def _build_ui(self):
        self.title = Text(
            "RUBIK'S CUBE SOLVER",
            parent=camera.ui,
            position=(-0.86, 0.46),
            origin=(-0.5, 0.5),
            color=PANEL_TEXT,
            scale=1.4,
        )

        def add_button(label, action, y):
            return Button(
                text=label,
                parent=camera.ui,
                position=(-0.74, y),
                scale=(0.26, 0.06),
                color=BUTTON_COLOUR,
                text_size=0.8,
                radius=0.25,
                on_click=action,
            )

        self.buttons = [
            add_button("Scramble", self.on_scramble, 0.37),
            add_button("Enter colours", self.on_enter_colours, 0.295),
            add_button("Solve (auto play)", self.on_solve_auto, 0.22),
            add_button("Solve (step by step)", self.on_solve_step, 0.06),
            add_button("Stop", self.on_stop, -0.015),
            add_button("Reset", self.on_reset, -0.09),
        ]

        self.speed_label = Text(
            "auto play speed, moves per second",
            parent=camera.ui,
            position=(-0.86, 0.172),
            origin=(-0.5, 0.5),
            color=DIM_TEXT,
            scale=0.62,
        )
        self.speed_slider = Slider(
            min=AUTO_SPEED_MIN,
            max=AUTO_SPEED_MAX,
            default=AUTO_SPEED_DEFAULT,
            dynamic=True,
            position=(-0.855, 0.135),
            scale=0.62,
            on_value_changed=self.refresh_text,
        )

        self.help_texts = [
            Text(
                body,
                parent=camera.ui,
                position=(-0.86, y),
                origin=(-0.5, 0.5),
                color=DIM_TEXT,
                scale=0.7,
            )
            for body, y in (
                ("DRAG to rotate", -0.17),
                ("SCROLL to zoom in and out", -0.235),
                (
                    "ENTER KEY squares up to the\n"
                    "nearest face, then use the\n"
                    "ARROW KEYS to switch faces",
                    -0.30,
                ),
            )
        ]

        self.move_text = Text(
            "", parent=camera.ui, position=(0, 0.46), origin=(0, 0.5), color=ACCENT, scale=2.2
        )
        self.top_text = Text(
            "", parent=camera.ui, position=(0, 0.39), origin=(0, 0.5), color=PANEL_TEXT, scale=0.85
        )
        self.bottom_text = Text(
            "", parent=camera.ui, position=(0, -0.42), origin=(0, 0.5), color=PANEL_TEXT, scale=0.85
        )
        self.next_text = Text(
            "",
            parent=camera.ui,
            position=(0.44, 0.33),
            origin=(-0.5, 0.5),
            color=PANEL_TEXT,
            scale=0.72,
            line_height=1.3,
        )

        self.main_ui = [
            self.speed_label,
            self.speed_slider,
            self.next_text,
            *self.help_texts,
            *self.buttons,
        ]

    def _build_paint_ui(self):
        """The colour picker, in the left column where the buttons normally are.

        Top level entities like every other button here, rather than children of
        one container: ursina hides a disabled entity's whole subtree, but these
        are simple enough that there is nothing to gain from nesting them.
        """
        self.paint_ui = []
        self.swatches = {}

        heading = Text(
            "PAINT YOUR CUBE",
            parent=camera.ui,
            position=(-0.86, 0.37),
            origin=(-0.5, 0.5),
            color=PANEL_TEXT,
            scale=0.95,
        )
        instructions = Text(
            "click a colour, then click the\nstickers on the cube itself\n"
            "drag, enter and the arrow keys\nturn it around",
            parent=camera.ui,
            position=(-0.86, 0.33),
            origin=(-0.5, 0.5),
            color=DIM_TEXT,
            scale=0.65,
        )
        self.paint_ui += [heading, instructions]

        self.paint_highlight = Entity(
            parent=camera.ui, model="quad", color=PANEL_TEXT, scale=(0.085, 0.072), z=0.01
        )
        self.paint_ui.append(self.paint_highlight)

        for i, colour in enumerate(PAINT_ORDER):
            x = -0.83 + (i % 3) * 0.085
            y = 0.17 - (i // 3) * 0.075
            swatch = Button(
                parent=camera.ui,
                model="quad",
                scale=(0.075, 0.062),
                position=(x, y),
                on_click=partial(self.choose_colour, colour),
            )
            paint_button(swatch, STICKER_COLOUR[colour])
            self.swatches[colour] = swatch
            self.paint_ui.append(swatch)

        def add_button(label, action, y):
            button = Button(
                text=label,
                parent=camera.ui,
                position=(-0.74, y),
                scale=(0.26, 0.06),
                color=BUTTON_COLOUR,
                text_size=0.8,
                radius=0.25,
                on_click=action,
            )
            self.paint_ui.append(button)
            return button

        self.apply_button = add_button("Apply", self.apply_colours, -0.01)
        add_button("Clear all", self.clear_colours, -0.085)
        add_button("Cancel", self.cancel_colours, -0.16)

        for entity in self.paint_ui:
            entity.enabled = False

    def show_paint_ui(self, visible):
        for entity in self.main_ui:
            entity.enabled = not visible
        for entity in self.paint_ui:
            entity.enabled = visible


    def displayed_colours(self):
        return self.paint_state if self.editing else self.state

    def repaint(self):
        """The model is the single source of truth for what is on screen."""
        colours = self.displayed_colours()
        for pos, cubie in self.cubies.items():
            cubie.parent = self.root
            cubie.position = Vec3(*to_render(pos))
            cubie.rotation = (0, 0, 0)
        for index, sticker in enumerate(self.stickers):
            sticker.color = STICKER_COLOUR[colours[index]]

    def _waiting_step(self):
        """The move that will happen next, if it is already decided."""
        if self.current:
            return self.current
        if self.queue:
            return self.queue[0]
        if self.mode == self.STEP and self.solution and self.cursor < len(self.solution):
            return Step(
                self.solution[self.cursor],
                index=self.cursor + 1,
                total=len(self.solution),
            )
        return None

    def refresh_text(self):
        if self.editing:
            self.move_text.text = ""
            self.top_text.text = PAINT_HINT
            self.bottom_text.text = self.bottom_message
            return

        step = self._waiting_step()
        self.move_text.text = step.move if step else ""
        self.top_text.text = self.top_message

        parts = [self.bottom_message] if self.bottom_message else []
        if step and step.total:
            parts.append(f"move {step.index} of {step.total}")
        if self.mode == self.AUTO and (self.queue or self.current):
            parts.append(f"{self.speed_slider.value:.1f} moves/sec")
        self.bottom_text.text = "     ".join(parts)

        self.next_text.text = self._next_lines()

    @staticmethod
    def _in_rows(moves, per_row=8):
        rows = [moves[i : i + per_row] for i in range(0, len(moves), per_row)]
        return "\n".join("  ".join(f"{m:<2}" for m in row) for row in rows)

    def _next_lines(self):
        if self.mode == self.STEP and self.solution:
            upcoming = self.solution[self.cursor :][:32]
        else:
            upcoming = [step.move for step in list(self.queue)[:32]]
            if self.current:
                upcoming.insert(0, self.current.move)
        if upcoming:
            return "NEXT MOVES\n\n" + self._in_rows(upcoming)
        if self.scramble_sequence:
            return (
                "SCRAMBLE\nturn a real cube with this to\nmatch the one on screen:\n\n"
                + self._in_rows(self.scramble_sequence)
            )
        return ""

    # cube painting 

    def on_enter_colours(self):
        self.cancel_now()
        self.editing = True
        self.face_view = None
        self.scramble_sequence = []
        self.forget_solution()
        self.clear_colours()
        self.show_paint_ui(True)
        for sticker in self.stickers:
            sticker.collider = "box"  # only clickable while painting

    def clear_colours(self):
        """Blank cube: every sticker empty except the six fixed centres."""
        self.paint_state = [BLANK] * cube.N_FACELETS
        for face in cube.FACES:
            pos, direction = cube.net_facelet(face, 1, 1)
            self.paint_state[cube.FACELET_INDEX[(pos, direction)]] = cube.FACE_COLOUR[face]
        self.choose_colour(self.paint_colour)
        self.repaint()
        self.report_blanks()

    def choose_colour(self, colour):
        self.paint_colour = colour
        swatch = self.swatches[colour]
        self.paint_highlight.position = (swatch.x, swatch.y, 0.01)

    def paint_sticker(self, index):
        if self.paint_state[index] == self.paint_colour:
            return
        self.paint_state[index] = self.paint_colour
        self.stickers[index].color = STICKER_COLOUR[self.paint_colour]
        self.report_blanks()

    def report_blanks(self):
        blanks = self.paint_state.count(BLANK)
        self.bottom_message = (
            f"{blanks} stickers still to paint" if blanks else "All painted. Press Apply."
        )
        self.bottom_text.color = PANEL_TEXT
        self.refresh_text()

    def apply_colours(self):
        blanks = self.paint_state.count(BLANK)
        if blanks:
            self.bottom_message = f"Paint the last {blanks} stickers first."
            self.bottom_text.color = WARNING
            self.refresh_text()
            return
        state = tuple(self.paint_state)
        problem = cube.validity_error(state)
        if problem:
            self.bottom_message = f"No real cube can look like that: {problem}"
            self.bottom_text.color = WARNING
            self.refresh_text()
            return

        self.close_paint_ui()
        self.state = state
        self.top_message = ORIENT_HINT
        self.bottom_message = ""
        self.ensure_solution()
        self.repaint()
        self.refresh_text()

    def cancel_colours(self):
        self.close_paint_ui()
        self.bottom_message = ""
        self.repaint()
        self.refresh_text()

    def close_paint_ui(self):
        self.editing = False
        self.bottom_text.color = PANEL_TEXT
        self.show_paint_ui(False)
        for sticker in self.stickers:
            sticker.collider = None

    #animation 

    def auto_duration(self):
        return 1.0 / max(0.05, self.speed_slider.value)

    def start(self, step):
        self.current = step
        self.active_duration = step.duration or self.auto_duration()
        self.elapsed = 0.0
        self.pivot = Entity(parent=self.root)
        self.pivot_axis, self.pivot_angle = rotation_for(step.move)

        normal = cube.FACE_NORMAL[step.move[0]]
        axis = next(i for i in range(3) if normal[i])
        for pos, cubie in self.cubies.items():
            if pos[axis] == normal[axis]:
                cubie.parent = self.pivot

    def finish(self):
        """Commit the turn: the cube snaps back to exact model positions."""
        self.state = cube.apply_move(self.state, self.current.move)
        for cubie in list(self.pivot.children):
            cubie.parent = self.root
        destroy(self.pivot)
        self.pivot = None
        self.current = None
        self.repaint()

    def when_settled(self, action):
        """Run `action` once the turn in flight ends, without cutting it short."""
        self.queue.clear()
        if self.current:
            self.pending = action
        else:
            self.pending = None
            action()

    def cancel_now(self):
        """Hard stop, for actions that replace the cube anyway."""
        self.queue.clear()
        self.pending = None
        if self.current:
            self.finish()

    def forget_solution(self):
        self.solution = None
        self.solution_state = None
        self.cursor = 0
        self.mode = self.IDLE

    #solving 
    def ensure_solution(self):
        if self.solution is not None and self.solution_state == self.state:
            return True
        try:
            self.solution = solver.solve(self.state)
            self.solution_state = self.state
            return True
        except solver.SolveError as exc:
            self.solution = None
            self.solution_state = None
            self.bottom_message = f"Cannot solve this cube: {exc}"
            return False

    #buttons

    def on_scramble(self):
        self.cancel_now()
        moves = cube.random_moves(SCRAMBLE_LENGTH)
        while cube.is_solved(cube.apply_moves(cube.SOLVED, moves)):
            moves = cube.random_moves(SCRAMBLE_LENGTH)

        self.state = cube.apply_moves(cube.SOLVED, moves)
        self.scramble_sequence = moves
        self.forget_solution()
        self.top_message = ORIENT_HINT
        self.bottom_message = ""
        self.ensure_solution()
        print("Scramble:", " ".join(moves))
        self.repaint()
        self.refresh_text()

    def on_solve_auto(self):
        self.when_settled(self._start_auto)

    def _start_auto(self):
        if not self._prepare_solution():
            return
        self.mode = self.AUTO
        total = len(self.solution)
        for index, move in enumerate(self.solution, start=1):
            self.queue.append(Step(move, None, index=index, total=total))
        self.cursor = total  # auto play consumes the whole solution
        self.bottom_message = f"Auto play: {total} moves."
        self.refresh_text()

    def on_solve_step(self):
        self.when_settled(self._start_stepping)

    def _start_stepping(self):
        if not self._prepare_solution():
            return
        self.mode = self.STEP
        self.top_message = ORIENT_HINT
        self.bottom_message = STEP_HINT
        self.refresh_text()

    def _prepare_solution(self):
        """Shared by both solve buttons.  False if there is nothing to solve."""
        if cube.is_solved(self.state):
            self.bottom_message = "Already solved. Try scrambling first."
            self.refresh_text()
            return False
        self.forget_solution()
        if not self.ensure_solution():
            self.refresh_text()
            return False
        self.scramble_sequence = []
        return True

    def step_forward(self):
        if self.mode != self.STEP or not self.solution:
            self.when_settled(self._start_stepping)
            return
        if self.cursor >= len(self.solution):
            self.bottom_message = "That is the whole solution."
            self.refresh_text()
            return
        move = self.solution[self.cursor]
        self.cursor += 1
        self.queue.append(Step(move, STEP_MOVE_TIME, index=self.cursor, total=len(self.solution)))
        self.bottom_message = STEP_HINT
        self.refresh_text()

    def step_back(self):
        if self.mode != self.STEP or not self.solution:
            self.bottom_message = "Nothing to undo yet."
            self.refresh_text()
            return
        if self.cursor <= 0:
            self.bottom_message = "Back at the start of the solution."
            self.refresh_text()
            return
        self.cursor -= 1
        self.queue.append(
            Step(
                invert_move(self.solution[self.cursor]),
                STEP_MOVE_TIME,
                index=self.cursor,
                total=len(self.solution),
            )
        )
        self.bottom_message = STEP_HINT
        self.refresh_text()

    def on_stop(self):
        """Stop playing, but never cut the turn in flight short."""
        if self.queue or self.current:
            self.bottom_message = "Stopped."
        self.when_settled(self._after_stop)
        self.refresh_text()

    def _after_stop(self):
        if self.mode == self.STEP and self.solution:
            self.refresh_text()
            return
        self.forget_solution()
        if cube.is_solved(self.state):
            self.bottom_message = "Solved."
        elif self.ensure_solution():
            self.bottom_message = f"Stopped. {len(self.solution)} moves left."
        self.refresh_text()

    def on_reset(self):
        self.cancel_now()
        if self.editing:
            self.close_paint_ui()
        self.state = cube.SOLVED
        self.forget_solution()
        self.scramble_sequence = []
        self.top_message = ""
        self.bottom_message = ""
        self.repaint()
        self.refresh_text()

    #looking at the cube
    def view_direction(self, pitch, yaw, model_dir):
        """Where a model direction ends up on screen at the given angles.

        Measured with the spare rig rather than worked out on paper, so it cannot
        disagree with what the real rig does.  -z points at the camera.
        """
        self.probe_pitch.rotation_x = pitch
        self.probe_yaw.rotation_y = yaw
        self.probe_point.position = Vec3(*to_render(model_dir))
        return self.probe_point.world_position

    def nearest_face(self):
        """The face closest to facing the camera right now."""
        return min(
            cube.FACES,
            key=lambda f: self.view_direction(
                self.target_pitch, self.target_yaw, cube.FACE_NORMAL[f]
            )[2],
        )

    def face_towards(self, screen_dir):
        """The face currently pointing in a given screen direction."""
        return max(
            cube.FACES,
            key=lambda f: sum(
                a * b
                for a, b in zip(
                    self.view_direction(
                        self.target_pitch, self.target_yaw, cube.FACE_NORMAL[f]
                    ),
                    screen_dir,
                )
            ),
        )

    def look_at_face(self, face):
        """Turn the cube so `face` points straight at the camera, the short way."""
        normal = cube.FACE_NORMAL[face]
        best, best_cost = None, None
        for pitch in (-90.0, 0.0, 90.0):
            for quarter in range(4):
                yaw = 90.0 * quarter
                if self.view_direction(pitch, yaw, normal)[2] > -0.999:
                    continue
                # take whichever equivalent angle is the shortest trip from here
                pitch_to = pitch + 360 * round((self.target_pitch - pitch) / 360)
                yaw_to = yaw + 360 * round((self.target_yaw - yaw) / 360)
                cost = abs(pitch_to - self.target_pitch) + abs(yaw_to - self.target_yaw)
                if best_cost is None or cost < best_cost:
                    best, best_cost = (pitch_to, yaw_to), cost
        if best is None:  # cannot happen for a face normal, but do not hang on it
            return
        self.target_pitch, self.target_yaw = best
        self.face_view = face

        colour = COLOUR_NAMES[cube.FACE_COLOUR[face]]
        self.bottom_message = f"Looking at the {colour} face. Arrow keys turn to the next one."
        self.refresh_text()

    ARROW_DIRECTIONS = {
        "up arrow": (0, 1, 0),
        "arrow_up": (0, 1, 0),
        "down arrow": (0, -1, 0),
        "arrow_down": (0, -1, 0),
        "left arrow": (-1, 0, 0),
        "arrow_left": (-1, 0, 0),
        "right arrow": (1, 0, 0),
        "arrow_right": (1, 0, 0),
    }
    ENTER_KEYS = ("enter", "return")

    def turn_to_neighbour(self, key):
        """Arrow keys walk from the face you are looking at to the next one."""
        if not self.face_view:
            return False
        self.look_at_face(self.face_towards(self.ARROW_DIRECTIONS[key]))
        return True

    def _orbit(self):
        if self.dragging:
            if mouse.velocity[0] or mouse.velocity[1]:
                self.drag_moved = True
                self.face_view = None  # dragging means free look again
            self.target_yaw -= mouse.velocity[0] * DRAG_SENSITIVITY
            self.target_pitch = max(
                -MAX_PITCH,
                min(MAX_PITCH, self.target_pitch + mouse.velocity[1] * DRAG_SENSITIVITY),
            )
        blend = min(1.0, VIEW_SMOOTHING * time.dt)
        self.yaw += (self.target_yaw - self.yaw) * blend
        self.pitch += (self.target_pitch - self.pitch) * blend
        self.yaw_pivot.rotation_y = self.yaw
        self.pitch_pivot.rotation_x = self.pitch

    def update(self):
        self._orbit()
        if self.editing:
            return

        if self.pending and not self.current:
            action, self.pending = self.pending, None
            action()

        if self.current:
            self.elapsed += time.dt
            fraction = min(1.0, self.elapsed / self.active_duration)
            eased = fraction * fraction * (3 - 2 * fraction)
            setattr(self.pivot, "rotation_" + self.pivot_axis, self.pivot_angle * eased)
            if fraction >= 1.0:
                self.finish()
                self._after_move()
        elif self.queue:
            self.start(self.queue.popleft())
            self.refresh_text()

    def _after_move(self):
        if self.queue or self.pending:
            self.refresh_text()
            return
        if cube.is_solved(self.state):
            if self.mode == self.STEP and self.solution:
                self.bottom_message = "Solved. B steps back through it."
            else:
                self.bottom_message = "Solved."
                self.forget_solution()
        self.refresh_text()

    #input 
    def input(self, key):
        if key == "left mouse down":
            self.on_press()
        elif key == "left mouse up":
            self.on_release()
        elif key == "scroll up":
            camera.z = min(-5.0, camera.z + 0.5)
        elif key == "scroll down":
            camera.z = max(-17.0, camera.z - 0.5)
        elif key in self.ENTER_KEYS:
            self.look_at_face(self.nearest_face())
        elif key in self.ARROW_DIRECTIONS:
            self.turn_to_neighbour(key)
        elif self.editing:
            return  # painting: nothing else to do with the keyboard
        elif key == "n":
            self.step_forward()
        elif key == "b":
            self.step_back()

    def on_press(self):
        hit = mouse.hovered_entity
        self.pressed_on = hit
        self.drag_moved = False
        if isinstance(hit, Button):
            self.dragging = False  # let the button have the click
        elif self.editing:
            self.dragging = True  # painting still needs to turn the cube
        else:
            self.dragging = hit is None

    def on_release(self):
        was_pressed, self.pressed_on = self.pressed_on, None
        self.dragging = False
        if self.editing and not self.drag_moved and was_pressed in self.sticker_index:
            self.paint_sticker(self.sticker_index[was_pressed])


sim = Simulator()


def update():
    sim.update()

def input(key):  
    sim.input(key)

if __name__ == "__main__":
    app.run()
