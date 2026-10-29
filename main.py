from __future__ import annotations
import sys
from collections import deque
from dataclasses import dataclass
from functools import partial
from panda3d.core import AntialiasAttrib, loadPrcFileData
from PIL import Image, ImageDraw
from ursina import (
    Button,
    Entity,
    Quad,
    Shader,
    Slider,
    Text,
    Texture,
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
    cube.YELLOW: color.hex("#f7cd2e"),
    cube.WHITE: color.hex("#f3f4f1"),
    cube.GREEN: color.hex("#16a352"),
    cube.BLUE: color.hex("#1f5fd4"),
    cube.ORANGE: color.hex("#f2771f"),
    cube.RED: color.hex("#d2263d"),
    BLANK: color.hex("#c4c9d1"),  # pale grey: reads as blank, never as white
}
PAINT_ORDER = (cube.WHITE, cube.YELLOW, cube.GREEN, cube.BLUE, cube.RED, cube.ORANGE)

BODY_COLOUR = color.hex("#111318")
BACKGROUND = color.hex("#0d1014")
CARD_COLOUR = color.hex("#171b22")
CARD_EDGE = color.hex("#262c36")
PILL_COLOUR = color.hex("#171b22")
PANEL_TEXT = color.hex("#e3e7ee")
DIM_TEXT = color.hex("#8a93a2")
LABEL_TEXT = color.hex("#5f6878")
ACCENT = color.hex("#f7cd2e")  # the big next-move letter
PRIMARY = color.hex("#3567e8")  # solve and apply buttons
SECONDARY = color.hex("#28355a")  # step by step: related to solving, quieter
BUTTON_COLOUR = color.hex("#262c37")
TRACK_COLOUR = color.hex("#2a303b")
WARNING = color.hex("#ff9a8a")

MOVE_FONT = "VeraMono.ttf"  # monospaced, so the move grid lines up in columns
MAX_GRID_MOVES = 24

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

# 4x multisampling smooths the jagged, flickering pixels along the cube's edges.
# Has to be configured before the window opens.
loadPrcFileData("", "framebuffer-multisample 1\nmultisamples 4")

app = Ursina(
    title="Rubik's Cube Solver",
    size=(1280, 720),
    borderless=False,
    vsync=not SELF_CHECK,  # the self check steps frames as fast as it can
    development_mode=False,
)
app.render.setAntialias(AntialiasAttrib.MMultisample)
window.color = BACKGROUND
window.fps_counter.enabled = False
window.entity_counter.enabled = False
window.collider_counter.enabled = False

CAMERA_DISTANCE = 14.5  # far enough that the cube sits between the two side panels
ZOOM_NEAREST, ZOOM_FARTHEST = 8.0, 24.0
camera.position = (0, 0, -CAMERA_DISTANCE)
camera.rotation = (0, 0, 0)


# Soft directional lighting.  The camera never moves, so a light fixed in world
# space behaves like a studio light: faces turned towards the upper left are
# brightest, faces turned away fall into shade, and the cube reads as a solid
# object instead of flat paper.  Colour still comes from Entity.color, so the
# model's sticker colours are untouched.
cube_shader = Shader(
    name="cube_shader",
    language=Shader.GLSL,
    vertex="""
#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec2 p3d_MultiTexCoord0;
in vec4 p3d_Color;
out vec2 uvs;
out vec3 world_normal;
out vec4 vertex_color;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uvs = p3d_MultiTexCoord0;
    world_normal = normalize(mat3(p3d_ModelMatrix) * p3d_Normal);
    vertex_color = p3d_Color;
}
""",
    fragment="""
#version 140
uniform sampler2D p3d_Texture0;
uniform vec4 p3d_ColorScale;
in vec2 uvs;
in vec3 world_normal;
in vec4 vertex_color;
out vec4 fragColor;
void main() {
    vec4 base = texture(p3d_Texture0, uvs) * p3d_ColorScale * vertex_color;
    if (base.a < 0.5) discard;  // rounded sticker corners
    vec3 n = normalize(world_normal);
    float key = max(dot(n, normalize(vec3(-0.30, 0.60, -0.74))), 0.0);
    float fill = max(dot(n, normalize(vec3(0.75, 0.0, -0.66))), 0.0);
    float shade = min(1.0, 0.62 + 0.38 * key + 0.20 * fill);
    fragColor = vec4(base.rgb * shade, 1.0);
}
""",
)


def _supersampled(size, draw, scale=4):
    """Draw at `scale` times the size and shrink, for smooth anti-aliased edges."""
    big = Image.new("RGBA", (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    draw(ImageDraw.Draw(big), scale)
    return big.resize(size, Image.LANCZOS)


# rounded square sticker: white inside, transparent corners, tinted by .color
STICKER_TEXTURE = Texture(
    _supersampled(
        (128, 128),
        lambda d, s: d.rounded_rectangle(
            (0, 0, 128 * s - 1, 128 * s - 1), radius=26 * s, fill=(255, 255, 255, 255)
        ),
    )
)


def _backdrop_texture():
    """A soft radial glow behind the cube, fading to the window colour."""
    w, h = 320, 180
    image = Image.new("RGB", (w, h))
    pixels = image.load()
    centre = (0x1f, 0x26, 0x31)
    edge = (0x0d, 0x10, 0x14)
    for y in range(h):
        for x in range(w):
            dx, dy = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
            t = min(1.0, (dx * dx * 0.55 + dy * dy) ** 0.5)
            t = t * t * (3 - 2 * t)
            pixels[x, y] = tuple(round(c + (e - c) * t) for c, e in zip(centre, edge))
    return Texture(image)


# Parented to the camera and placed well behind the cube, so it fills the view
# at any zoom level.  The camera's horizontal field of view is 40 degrees.
_BACKDROP_DEPTH = 80
_backdrop_width = 2 * _BACKDROP_DEPTH * 0.364 * 1.15  # tan(20 degrees), plus margin
Entity(
    parent=camera,
    model="quad",
    texture=_backdrop_texture(),
    shader=unlit_shader,
    z=_BACKDROP_DEPTH,
    scale=(_backdrop_width, _backdrop_width / window.aspect_ratio),
)


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
                shader=cube_shader,
                position=Vec3(*to_render(pos)),
                scale=0.97,
            )
            self.cubies[pos] = cubie
            for direction in cube.DIRS_AT[pos]:
                # nearly flat: a thicker box shows its textured sides as thin
                # coloured lines along every sticker edge
                scale = [0.86, 0.86, 0.86]
                scale[next(i for i in range(3) if direction[i])] = 0.002
                sticker = Entity(
                    parent=cubie,
                    model="cube",
                    shader=cube_shader,
                    texture=STICKER_TEXTURE,
                    color=color.black,
                    position=Vec3(*to_render(direction)) * 0.5,
                    scale=Vec3(*scale),
                )
                index = cube.FACELET_INDEX[(pos, direction)]
                self.stickers[index] = sticker
                self.sticker_index[sticker] = index

    # -- interface layout ---------------------------------------------------- #
    #
    # Three columns: a control card on the left, the cube in the middle, and a
    # moves card on the right that only appears when there is something to show.
    # camera.ui spans x = -0.889 .. 0.889 and y = -0.5 .. 0.5 at 16:9.

    LEFT_X, RIGHT_X = -0.70, 0.70  # card centres
    CARD_WIDTH = 0.34
    CONTENT_WIDTH = 0.30
    BUTTON_HEIGHT = 0.054

    @staticmethod
    def _card(x, top=0.475, bottom=-0.475, width=CARD_WIDTH):
        """A rounded panel with a one pixel border, drawn behind everything else."""
        height = top - bottom
        y = (top + bottom) / 2
        pieces = []
        for grow, colour, depth in ((0.003, CARD_EDGE, 0.31), (0.0, CARD_COLOUR, 0.30)):
            w, h = width + grow, height + grow
            pieces.append(
                Entity(
                    parent=camera.ui,
                    model=Quad(radius=0.03, aspect=w / h),
                    color=colour,
                    position=(x, y, depth),
                    scale=(w, h),
                )
            )
        return pieces

    @staticmethod
    def _label(text, x, y, colour=LABEL_TEXT, scale=0.58, origin=(-0.5, 0.5), **kwargs):
        return Text(
            text,
            parent=camera.ui,
            position=(x, y),
            origin=origin,
            color=colour,
            scale=scale,
            **kwargs,
        )

    def _button(self, label, action, y, x=LEFT_X, width=CONTENT_WIDTH, colour=BUTTON_COLOUR):
        return Button(
            text=label,
            parent=camera.ui,
            position=(x, y),
            scale=(width, self.BUTTON_HEIGHT),
            color=colour,
            text_color=PANEL_TEXT,
            text_size=0.78,
            radius=0.28,
            on_click=action,
        )

    def _build_ui(self):
        left = self.LEFT_X
        content_left = left - self.CONTENT_WIDTH / 2
        content_right = left + self.CONTENT_WIDTH / 2
        half = (self.CONTENT_WIDTH - 0.01) / 2  # two buttons side by side

        self.left_card = self._card(left, bottom=-0.325)  # hugs its contents
        self.title = Text(
            "RUBIK'S CUBE SOLVER",
            parent=camera.ui,
            position=(content_left, 0.448),
            origin=(-0.5, 0.5),
            color=PANEL_TEXT,
            scale=1.1,
        )
        self.title_rule = Entity(
            parent=camera.ui,
            model=Quad(radius=0.5, aspect=10),
            color=PRIMARY,
            position=(content_left + 0.025, 0.401),
            scale=(0.05, 0.005),
        )

        cube_label = self._label("CUBE", content_left, 0.372)
        solve_label = self._label("SOLVE", content_left, 0.218)
        speed_label = self._label("Speed", content_left, 0.128, colour=DIM_TEXT, scale=0.64)
        self.speed_value = self._label(
            "", content_right, 0.128, colour=PANEL_TEXT, scale=0.64, origin=(0.5, 0.5)
        )

        self.buttons = [
            self._button("Scramble", self.on_scramble, 0.328),
            self._button("Enter colours", self.on_enter_colours, 0.266),
            self._button("Solve (auto play)", self.on_solve_auto, 0.172, colour=PRIMARY),
            self._button("Solve (step by step)", self.on_solve_step, 0.042, colour=SECONDARY),
            self._button(
                "Stop", self.on_stop, -0.020, x=content_left + half / 2, width=half
            ),
            self._button(
                "Reset", self.on_reset, -0.020, x=content_right - half / 2, width=half
            ),
        ]

        self.speed_slider = Slider(
            min=AUTO_SPEED_MIN,
            max=AUTO_SPEED_MAX,
            default=AUTO_SPEED_DEFAULT,
            dynamic=True,
            position=(content_left + 0.004, 0.094),
            scale=(self.CONTENT_WIDTH - 0.008) / 0.525,
            bar_color=TRACK_COLOUR,
            on_value_changed=self.refresh_text,
        )
        self.speed_slider.knob.text_entity.enabled = False  # shown in speed_value
        paint_button(self.speed_slider.knob, PANEL_TEXT)

        self.controls_rule = Entity(
            parent=camera.ui,
            model="quad",
            color=CARD_EDGE,
            position=(left, -0.074, 0.2),
            scale=(self.CONTENT_WIDTH, 0.0015),
        )
        controls_label = self._label("CONTROLS", content_left, -0.098)
        self.help_texts = [
            Text(
                body,
                parent=camera.ui,
                position=(content_left, y),
                origin=(-0.5, 0.5),
                color=DIM_TEXT,
                scale=0.66,
            )
            for body, y in (
                ("DRAG to rotate", -0.138),
                ("SCROLL to zoom in and out", -0.188),
                (
                    "ENTER KEY squares up to the\n"
                    "nearest face, then use the\n"
                    "ARROW KEYS to switch faces",
                    -0.238,
                ),
            )
        ]

        # status lines above and below the cube, each on its own rounded pill
        self.top_text = Text(
            "", parent=camera.ui, position=(0, 0.448), origin=(0, 0), color=PANEL_TEXT, scale=0.8
        )
        self.bottom_text = Text(
            "", parent=camera.ui, position=(0, -0.448), origin=(0, 0), color=PANEL_TEXT, scale=0.8
        )

        self._build_moves_panel()

        self.main_ui = [
            cube_label,
            solve_label,
            speed_label,
            self.speed_value,
            self.speed_slider,
            self.controls_rule,
            controls_label,
            *self.help_texts,
            *self.buttons,
        ]

    def _build_moves_panel(self):
        right = self.RIGHT_X
        content_left = right - self.CONTENT_WIDTH / 2
        self.moves_left = content_left

        self.right_card = []
        self.right_card_bottom = None
        self.next_label = self._label("", content_left, 0.448)
        self.move_text = Text(
            "",
            parent=camera.ui,
            position=(content_left, 0.428),
            origin=(-0.5, 0.5),
            color=ACCENT,
            scale=3.4,
        )
        self.progress_text = self._label("", content_left, 0.300, colour=DIM_TEXT, scale=0.66)
        self.progress_track = Entity(
            parent=camera.ui,
            model="quad",
            color=TRACK_COLOUR,
            position=(right, 0.262, 0.02),
            scale=(self.CONTENT_WIDTH, 0.008),
        )
        self.progress_fill = Entity(
            parent=camera.ui,
            model="quad",
            origin_x=-0.5,
            color=PRIMARY,
            position=(content_left, 0.262, 0.01),
            scale=(0.0001, 0.008),
        )
        self.upcoming_label = self._label("UPCOMING", content_left, 0.222)
        self.next_text = Text(
            "",
            parent=camera.ui,
            position=(content_left, 0.188),
            origin=(-0.5, 0.5),
            color=PANEL_TEXT,
            scale=0.9,
            line_height=1.5,
            font=MOVE_FONT,
        )
        self.right_panel = [
            self.next_label,
            self.move_text,
            self.progress_text,
            self.progress_track,
            self.progress_fill,
            self.upcoming_label,
            self.next_text,
        ]

    def _build_paint_ui(self):
        """The colour picker, in the left card where the buttons normally are.

        Top level entities like every other control here, rather than children
        of one container, so each can be shown and hidden on its own.
        """
        left = self.LEFT_X
        content_left = left - self.CONTENT_WIDTH / 2
        content_right = left + self.CONTENT_WIDTH / 2
        half = (self.CONTENT_WIDTH - 0.01) / 2
        self.paint_ui = []
        self.swatches = {}

        heading = self._label("PAINT YOUR CUBE", content_left, 0.372)
        instructions = self._label(
            "Pick a colour, then click the\n"
            "stickers on the cube. Drag,\n"
            "Enter and the arrow keys turn\n"
            "it to reach the other faces.",
            content_left,
            0.338,
            colour=DIM_TEXT,
            scale=0.64,
        )
        self.paint_ui += [heading, instructions]

        self.paint_highlight = Entity(
            parent=camera.ui,
            model=Quad(radius=0.24, aspect=0.093 / 0.079),
            color=PRIMARY,
            scale=(0.093, 0.079),
            z=0.01,
        )
        self.paint_ui.append(self.paint_highlight)

        for i, colour in enumerate(PAINT_ORDER):
            x = left + ((i % 3) - 1) * 0.1
            y = 0.205 - (i // 3) * 0.088
            swatch = Button(
                parent=camera.ui,
                scale=(0.08, 0.066),
                position=(x, y),
                radius=0.22,
                on_click=partial(self.choose_colour, colour),
            )
            paint_button(swatch, STICKER_COLOUR[colour])
            self.swatches[colour] = swatch
            self.paint_ui.append(swatch)

        self.paint_selected = self._label("", content_left, 0.064, colour=PANEL_TEXT, scale=0.66)
        self.paint_ui.append(self.paint_selected)

        self.apply_button = self._button("Apply", self.apply_colours, 0.002, colour=PRIMARY)
        clear_button = self._button(
            "Clear all", self.clear_colours, -0.060, x=content_left + half / 2, width=half
        )
        cancel_button = self._button(
            "Cancel", self.cancel_colours, -0.060, x=content_right - half / 2, width=half
        )
        note = self._label(
            "The six centres are fixed:\nwhite on top, green in front.",
            content_left,
            -0.112,
            colour=DIM_TEXT,
            scale=0.64,
        )
        self.paint_ui += [self.apply_button, clear_button, cancel_button, note]

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

    def _set_pill(self, text_entity, value):
        """Show `value` on a rounded dark pill, or hide both if it is empty."""
        if getattr(text_entity, "_pill_text", None) == value:
            return
        text_entity._pill_text = value
        text_entity.text = value
        if text_entity.background_entity:
            destroy(text_entity.background_entity)
            text_entity.background_entity = None
        if value:
            text_entity.create_background(
                padding=(Text.size * 2.4, Text.size * 1.3), radius=0.5, color=PILL_COLOUR
            )

    def refresh_text(self):
        self.speed_value.text = f"{self.speed_slider.value:.1f} moves/s"
        if self.editing:
            self._set_pill(self.top_text, PAINT_HINT)
            self._set_pill(self.bottom_text, self.bottom_message)
            self._show_moves_panel(False)
            return
        self._set_pill(self.top_text, self.top_message)
        self._set_pill(self.bottom_text, self.bottom_message)
        self._update_moves_panel(self._waiting_step())

    @staticmethod
    def _in_rows(moves, per_row=5):
        rows = [moves[i : i + per_row] for i in range(0, len(moves), per_row)]
        return "\n".join("  ".join(f"{m:<2}" for m in row) for row in rows)

    GRID_ROW_HEIGHT = 0.034  # one line of the move grid, in camera.ui units

    def _show_moves_panel(self, visible):
        for entity in self.right_panel + self.right_card:
            entity.enabled = visible

    def _fit_moves_card(self, grid_top, rows):
        """Size the right card to its contents rather than the full height."""
        bottom = round(min(grid_top - rows * self.GRID_ROW_HEIGHT - 0.035, 0.30), 3)
        if bottom == self.right_card_bottom:
            return
        for entity in self.right_card:
            destroy(entity)
        self.right_card = self._card(self.RIGHT_X, bottom=bottom)
        self.right_card_bottom = bottom

    def _upcoming_after(self, step):
        """The moves still to come after the one shown in large type."""
        if self.mode == self.STEP and self.solution:
            busy = self.current is not None or bool(self.queue)
            return self.solution[self.cursor if busy else self.cursor + 1 :]
        queued = [s.move for s in self.queue]
        return queued if self.current else queued[1:]

    def _update_moves_panel(self, step):
        stepping_done = step is None and self.mode == self.STEP and bool(self.solution)

        if step is not None or stepping_done:
            self._show_moves_panel(True)
            total = (step.total if step else 0) or len(self.solution or [])
            if step is not None:
                self.next_label.text = "NOW PLAYING" if self.mode == self.AUTO else "NEXT MOVE"
                self.move_text.text = step.move
                index = step.index or 1
                self.progress_text.text = f"Move {index} of {total}" if total else ""
                done = (index - 1) / total if total else 0.0
                upcoming = self._upcoming_after(step)
            else:
                self.next_label.text = "SOLVED"
                self.move_text.text = "Done"
                self.progress_text.text = f"All {total} moves played"
                done = 1.0
                upcoming = []
            self.progress_text.y = 0.300
            self.progress_track.enabled = self.progress_fill.enabled = bool(total)
            self.progress_fill.scale_x = max(0.0001, self.CONTENT_WIDTH * done)
            self.upcoming_label.enabled = bool(upcoming)
            self.next_text.y = 0.188
            shown = upcoming[:MAX_GRID_MOVES]
            self.next_text.text = self._in_rows(shown)
            rows = -(-len(shown) // 5)
            self._fit_moves_card(0.188 if rows else 0.262, rows)
            return

        if self.scramble_sequence:
            self._show_moves_panel(True)
            self.next_label.text = "SCRAMBLE"
            self.move_text.enabled = False
            self.progress_text.text = (
                "Apply these moves to a solved\ncube to match the one on screen."
            )
            self.progress_text.y = 0.414
            self.progress_track.enabled = self.progress_fill.enabled = False
            self.upcoming_label.enabled = False
            self.next_text.y = 0.350
            self.next_text.text = self._in_rows(self.scramble_sequence)
            self._fit_moves_card(0.350, -(-len(self.scramble_sequence) // 5))
            return

        self._show_moves_panel(False)

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
        self.paint_selected.text = f"Selected: {COLOUR_NAMES[colour].capitalize()}"

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
            camera.z = min(-ZOOM_NEAREST, camera.z + 0.5)
        elif key == "scroll down":
            camera.z = max(-ZOOM_FARTHEST, camera.z - 0.5)
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
