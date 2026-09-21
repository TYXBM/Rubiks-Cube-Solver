"""End to end checks for the app itself.

    python uicheck.py

Presses the buttons and keys, steps real frames, and then asserts the cube on
screen really is in the state it should be.  Everything goes in as a Panda3D
event, which is the route a real keyboard and mouse take:

    letters and digits   'raw-<key>'
    everything else      'buttonDown' with panda3d's own button name
    mouse                'buttonDown' with 'mouse1'

That matters.  An earlier version of these checks called the handlers directly
and passed happily while the enter key and the colour picker were both broken for
an actual user.  `app.input(key)` is no better: ursina drops anything in its
`keyboard_keys` string unless the event is flagged raw.
"""

import sys

sys.argv.append("--check")  # main.py reads this and turns vsync off for us

from ursina import Entity, Vec3, destroy, mouse  # noqa: E402

import cube  # noqa: E402
import solver  # noqa: E402
from main import (  # noqa: E402
    AUTO_SPEED_MAX,
    BLANK,
    ORIENT_HINT,
    SCRAMBLE_LENGTH,
    STEP_HINT,
    STICKER_COLOUR,
    WARNING,
    app,
    resting_view,
    rotation_for,
    sim,
    to_render,
)


# ursina looks these up on the __main__ module every frame, which is this file
# now rather than main.py
def update():
    sim.update()


def input(key):  # noqa: A001
    sim.input(key)


# --------------------------------------------------------------------------- #
# driving the app
# --------------------------------------------------------------------------- #

_RAW_KEYS = "1234567890qwertyuiopasdfghjklzxcvbnm"  # ursina's own keyboard_keys


def _drain(limit=8000, duration=0.005):
    frames = 0
    for step in sim.queue:
        step.duration = duration
    while (sim.queue or sim.current or sim.pending) and frames < limit:
        app.step()
        frames += 1
        for step in sim.queue:
            step.duration = duration
    assert not sim.queue and not sim.current, "the move queue never drained"
    return frames


def _press(button):
    """Press a key exactly as Panda3D reports it to ursina."""
    if len(button) == 1 and button in _RAW_KEYS:
        app.messenger.send(f"raw-{button}")
    else:
        app.messenger.send("buttonDown", [button])


def _click(entity):
    """Click an entity the way the mouse does, via ursina's own dispatch."""
    mouse.hovered_entity = entity
    app.messenger.send("buttonDown", ["mouse1"])
    app.messenger.send("buttonUp", ["mouse1"])
    mouse.hovered_entity = None


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #


def _check_turn_directions():
    for move in cube.MOVE_NAMES:
        face = move[0]
        times = {"": 1, "2": 2, "'": 3}[move[1:]]
        normal = cube.FACE_NORMAL[face]
        axis_index = next(i for i in range(3) if normal[i])
        anim_axis, angle = rotation_for(move)

        pivot = Entity()
        probes = {}
        for pos in cube.CUBIE_POSITIONS:
            if pos[axis_index] == normal[axis_index]:
                probes[pos] = Entity(parent=pivot, position=Vec3(*to_render(pos)))
        setattr(pivot, "rotation_" + anim_axis, angle)

        for pos, probe in probes.items():
            landed = pos
            for _ in range(times):
                landed = cube.ROT[face](landed)
            expected = Vec3(*to_render(landed))
            assert (probe.world_position - expected).length() < 1e-3, f"{move} spins the wrong way"
            destroy(probe)
        destroy(pivot)
    print(f"turn directions: all {len(cube.MOVE_NAMES)} moves animate the right way")


def _check_scene_is_clean():
    for pos, cubie in sim.cubies.items():
        expected = Vec3(*to_render(pos))
        assert (cubie.position - expected).length() < 1e-4, f"cubie {pos} drifted"
        assert cubie.parent == sim.root, f"cubie {pos} left the cube"
        assert max(abs(v) for v in cubie.rotation) < 1e-4, f"cubie {pos} is crooked"
    for index, sticker in enumerate(sim.stickers):
        assert sticker.color == STICKER_COLOUR[sim.displayed_colours()[index]], "wrong colour"


def _check_keys_arrive():
    """Does a real key press actually reach the app?  This is not a given."""
    seen = []
    original = sim.input

    def spy(key):
        seen.append(key)
        original(key)

    sim.input = spy
    try:
        sim.on_reset()
        # letter keys still have to reach the app, but must no longer turn the cube
        for letter in ("u", "d", "f", "b", "r", "l"):
            _press(letter)
        assert "r" in seen, f"letter keys never arrive, app saw {seen}"
        assert not sim.queue and not sim.current, "a letter key still turns the cube"
        assert cube.is_solved(sim.state), "a letter key still turns the cube"

        seen.clear()
        sim.face_view = None
        _press("enter")
        assert "enter" in seen, f"the enter key never arrives, app saw {seen}"
        assert sim.face_view is not None, "enter arrived but did not square up a face"

        seen.clear()
        _press("arrow_right")
        assert "right arrow" in seen, f"arrow keys never arrive, app saw {seen}"
    finally:
        sim.input = original
    print("keyboard: enter and arrows work, letter keys no longer turn the cube")


def _check_face_view():
    sim.on_reset()
    sim.face_view = None
    sim.target_pitch, sim.target_yaw = resting_view()
    _press("arrow_up")  # arrows must do nothing until a face is squared up
    assert sim.face_view is None, "arrow keys worked without a face squared up"

    _press("enter")
    assert sim.face_view is not None, "enter did not square up a face"
    facing = sim.view_direction(sim.target_pitch, sim.target_yaw, cube.FACE_NORMAL[sim.face_view])
    assert facing[2] < -0.999, f"{sim.face_view} is not square to the camera: {facing}"

    seen = {sim.face_view}
    for key in ("arrow_right", "arrow_right", "arrow_up", "arrow_down", "arrow_left"):
        previous = sim.face_view
        _press(key)
        assert sim.face_view != previous, f"{key} did not turn to another face"
        facing = sim.view_direction(
            sim.target_pitch, sim.target_yaw, cube.FACE_NORMAL[sim.face_view]
        )
        assert facing[2] < -0.999, f"{sim.face_view} is not square to the camera"
        seen.add(sim.face_view)
    assert len(seen) >= 4, f"the arrows only reached {seen}"

    for _ in range(90):
        app.step()
    assert abs(sim.pitch - sim.target_pitch) < 1.0, "the view never settled where it was sent"
    print(f"face view: enter squares up a face, arrows walked to {len(seen)} faces")


def _check_stepping_keys():
    sim.on_scramble()
    scrambled = sim.state
    _click(sim.buttons[3])  # Solve (step by step)
    _drain()
    assert sim.mode == sim.STEP and sim.solution, "the step by step button did nothing"
    assert sim.bottom_text.text.startswith(STEP_HINT), sim.bottom_text.text

    first_three = sim.solution[:3]
    for expected in first_three:
        _press("n")
        assert sim.queue and sim.queue[-1].move == expected, "N did not play the next move"
        _drain(duration=0.01)
    assert sim.state == cube.apply_moves(scrambled, first_three)

    for _ in range(3):
        _press("b")
        _drain(duration=0.01)
    assert sim.cursor == 0 and sim.state == scrambled, "B did not step back cleanly"

    while sim.cursor < len(sim.solution):
        _press("n")
        _drain(duration=0.005)
    assert cube.is_solved(sim.state), "stepping through the whole solution did not solve it"
    _check_scene_is_clean()

    # with no solution loaded, B does nothing rather than turning a face
    sim.on_reset()
    _press("b")
    assert not sim.queue and cube.is_solved(sim.state), "B moved the cube with nothing to step"
    print("stepping: N and B walk the solution")


def _check_colour_input():
    sim.on_reset()
    _click(sim.buttons[1])  # Enter colours
    assert sim.editing, "the Enter colours button did nothing"
    assert not sim.buttons[0].enabled and sim.apply_button.enabled, "the panels did not swap"
    assert not sim.help_texts[0].enabled, "the mouse hints stayed up over the palette"
    assert sim.paint_state.count(BLANK) == 48, "the cube should start blank apart from centres"
    assert all(s.collider for s in sim.stickers), "stickers are not clickable while painting"
    for index, sticker in enumerate(sim.stickers):
        assert sticker.color == STICKER_COLOUR[sim.paint_state[index]], "blank cube not drawn"

    # paint the whole cube by clicking every sticker, as a person would
    target = cube.apply_moves(cube.SOLVED, cube.random_moves(14))
    for index, sticker in enumerate(sim.stickers):
        if sim.paint_state[index] == target[index]:
            continue
        _click(sim.swatches[target[index]])
        assert sim.paint_colour == target[index], "clicking a colour did not select it"
        _click(sticker)
        assert sim.paint_state[index] == target[index], "clicking a sticker did not paint it"
    assert sim.paint_state.count(BLANK) == 0

    # an impossible cube must be refused, and say why
    spare = cube.FACELET_INDEX[((0, 1, 1), (0, 1, 0))]
    kept = sim.paint_state[spare]
    _click(sim.swatches[cube.RED if kept != cube.RED else cube.BLUE])
    _click(sim.stickers[spare])
    _click(sim.apply_button)
    assert sim.editing, "an impossible cube was accepted"
    assert sim.bottom_text.text and sim.bottom_text.color == WARNING, "no complaint shown"

    # put it back and apply for real
    _click(sim.swatches[kept])
    _click(sim.stickers[spare])
    _click(sim.apply_button)
    assert not sim.editing, "a real cube was refused"
    assert sim.state == target, "the cube did not take the colours painted on it"
    assert sim.buttons[0].enabled and not sim.apply_button.enabled, "panels did not swap back"
    assert not any(s.collider for s in sim.stickers), "stickers left clickable"
    assert sim.top_text.text == ORIENT_HINT
    assert sim.solution is not None, "no solution worked out for the painted cube"
    _check_scene_is_clean()

    # and it really solves
    _click(sim.buttons[2])  # Solve (auto play)
    _drain()
    assert cube.is_solved(sim.state), "the painted cube did not solve"
    print("colour input: blank cube painted by clicking, refused when impossible, then solved")


def _check_texts():
    sim.on_scramble()
    assert sim.top_text.text == ORIENT_HINT, "scramble should show the orientation hint"
    assert sim.bottom_text.text == "", "scramble should leave the bottom line empty"
    sim.on_reset()
    assert sim.top_text.text == "" and sim.bottom_text.text == "", "reset should clear both lines"

    hints = [t.text for t in sim.help_texts]
    assert hints[0] == "DRAG to rotate"
    assert hints[1] == "SCROLL to zoom in and out"
    assert hints[2].startswith("ENTER KEY") and "ARROW KEYS" in hints[2]
    gaps = [sim.help_texts[i].y - sim.help_texts[i + 1].y for i in range(len(sim.help_texts) - 1)]
    assert all(gap > 0.04 for gap in gaps), f"the three hints are not spaced apart: {gaps}"
    print("on screen text: hints and blanks as asked")


def main():
    print("solver tables ready:", solver.tables_ready())
    _check_turn_directions()
    _check_keys_arrive()

    sim.on_scramble()
    assert len(sim.scramble_sequence) == SCRAMBLE_LENGTH, "scramble is not 20 moves"
    assert cube.apply_moves(cube.SOLVED, sim.scramble_sequence) == sim.state
    assert sim.solution is not None, "scramble worked out no solution"
    assert len(sim.solution) <= 22, f"solution is {len(sim.solution)} moves"
    print(f"solution length: {len(sim.solution)} moves")

    sim.speed_slider.value = AUTO_SPEED_MAX
    _click(sim.buttons[2])  # Solve (auto play)
    assert sim.mode == sim.AUTO and sim.queue, "the auto play button did nothing"
    queued = len(sim.queue)
    frames = _drain()
    assert cube.is_solved(sim.state), "the animated cube did not end up solved"
    _check_scene_is_clean()
    print(f"auto play: {queued} moves animated in {frames} frames, cube solved")

    # stop must let the current turn finish rather than snapping it
    sim.on_scramble()
    _click(sim.buttons[2])
    for step in sim.queue:
        step.duration = 1.0
    for _ in range(10):
        app.step()
        if sim.current is not None and sim.elapsed < 0.4:
            break
    assert sim.current is not None, "expected a turn to be in flight"
    mid_move = sim.current.move
    before_stop = sim.state
    _click(sim.buttons[4])  # Stop
    assert sim.current is not None and sim.current.move == mid_move, "stop cut the turn short"
    assert not sim.queue, "stop left queued moves"
    _drain()
    assert sim.state == cube.apply_move(before_stop, mid_move), (
        "the turn in flight was thrown away instead of being finished"
    )
    print("stop: let the turn in flight finish, then held")

    _check_stepping_keys()
    _check_texts()
    _check_face_view()
    _check_colour_input()

    sim.on_reset()
    app.step()
    assert cube.is_solved(sim.state)
    _check_scene_is_clean()
    print("all app checks passed")


if __name__ == "__main__":
    main()
