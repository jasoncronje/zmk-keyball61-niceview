"""TPU grip pad for the case bottom, glued on in place of the stick-on feet.

Run `uv run bottom_pad.py` to write out/{left,right}_bottom_pad.{step,stl,3mf}.

The pad is the flat of the case bottom: the case's floor outline, in past its rounded
bottom edge, pad_thick thick. It is open over the screw
counterbores (pad_screw_hole, so the case still comes apart) and the trackball hole.
Plugs stand up from it into the feet's recesses and locate it while the glue sets.

`_grooved` versions add a hex grid of one-layer grooves to the desk side, which bite
a little on matte wood and give dust somewhere to go, at the cost of some contact area.

It prints plugs up, the desk side on the bed: a textured plate gives the grip side its
texture. In the STEP it sits under the case, as it is glued on.
"""

import math

import shapely
import shapely.geometry as sg
from build123d import Circle, Cylinder, Face, Kind, Polygon, Pos, Rectangle, Sketch, Vector, Wire, extrude, offset

import layout_left as left
import layout_right as right
import touchid
from case import outlines
from params import (
    case_bottom_round,
    foot_dia,
    pad_edge_inset,
    pad_groove,
    pad_groove_depth,
    pad_groove_pitch,
    pad_groove_rim,
    pad_hole_clearance,
    pad_plug_clearance,
    pad_plug_height,
    pad_screw_hole,
    pad_thick,
    trackball_hole,
)
from switch_plate import export


def pad(layout, grooved: bool = False):
    _, outer, tray = outlines(layout)
    floor = outer + tray
    if layout.POD_CENTER:
        floor += touchid.floor_plan(layout)
    outline = offset(floor, -(case_bottom_round + pad_edge_inset), kind=Kind.ARC)
    screws = touchid.case_inserts(layout) + layout.SENSOR_SCREWS
    if layout.POD_CENTER:  # the Touch ID cap's two leg screws
        screws += [(at.position.X, at.position.Y) for at in touchid._leg_points(layout)]
    holes = [Pos(x, y) * Circle(pad_screw_hole / 2) for x, y in screws]
    if layout.TRACKBALL_HOLE:
        x, y = layout.TRACKBALL_HOLE
        holes.append(Pos(x, y) * Circle(trackball_hole / 2 + pad_hole_clearance))
    plan = outline - holes
    assert len(plan.faces()) == 1, f"pad outline split into {len(plan.faces())} faces"
    body = Pos(0, 0, -pad_thick) * extrude(plan, pad_thick)
    r = foot_dia / 2 - pad_plug_clearance
    body += [Pos(x, y, pad_plug_height / 2) * Cylinder(r, pad_plug_height) for x, y in layout.FEET]
    if grooved:
        body -= Pos(0, 0, -pad_thick) * extrude(grooves(outline, holes), pad_groove_depth)
    assert len(body.solids()) == 1, f"pad split into {len(body.solids())} solids"
    return body


def grooves(outline: Sketch, holes: list) -> Sketch:
    """A hex grid of pad_groove-wide grooves over the pad: a sheet the pad's size, less a
    hexagon per cell pad_groove narrower than the pitch. A solid band pad_groove_rim wide
    runs round the edge and every hole: the cells it reaches into are left whole and
    solid, so every groove is a complete cell edge, never a cut-off stub."""
    bb = outline.bounding_box()
    dx, dy = pad_groove_pitch, pad_groove_pitch * math.sqrt(3) / 2  # rows of flat-sided cells
    gap = (pad_groove_pitch - pad_groove) / math.sqrt(3)  # circumradius of a cell's solid hexagon
    tile = pad_groove_pitch / math.sqrt(3)  # ...and of the whole cell, out to the groove centres
    centres = []
    for j in range(int((bb.max.Y - bb.min.Y) / dy) + 3):
        y = bb.min.Y - dy + j * dy
        shift = dx / 2 if j % 2 else 0.0
        for i in range(int((bb.max.X - bb.min.X) / dx) + 3):
            centres.append((bb.min.X - dx + shift + i * dx, y))
    sheet = Pos(bb.center().X, bb.center().Y) * Rectangle(bb.size.X + 2 * dx, bb.size.Y + 2 * dx)
    net = (sheet - [Polygon(*_hex_points(gap, x, y), align=None) for x, y in centres]) & offset(outline, -pad_groove_rim, kind=Kind.ARC)

    # the solid band: every cell not wholly inside the rim or reaching a hole's zone, out
    # to the groove centres, merged and drawn back to the grooves' inner edges (shapely: OCC can't offset the merged hexagons inwards)
    zones = [sg.Point(h.center().X, h.center().Y).buffer(h.bounding_box().size.X / 2 + pad_groove_rim) for h in holes]
    wire = offset(outline, -pad_groove_rim, kind=Kind.ARC).faces()[0].outer_wire()
    inside = sg.Polygon([(p.X, p.Y) for p in wire.positions([i / 2000 for i in range(2000)])])
    tiles = [sg.Polygon(_hex_points(tile + 0.01, x, y)) for x, y in centres]  # overlapping a hair, so they merge without slivers
    island = shapely.unary_union([t for t in tiles if not inside.contains(t) or any(t.intersects(z) for z in zones)]).buffer(
        -pad_groove / 2 - 0.01, join_style="mitre")
    for poly in getattr(island, "geoms", [island]):
        net -= _face(poly)
    return Sketch() + [f for f in net.faces() if f.area > 2 * pad_groove**2]


def _hex_points(r: float, x: float, y: float) -> list:
    """A cell's hexagon, pointy end up (flat sides left and right), circumradius r."""
    return [(x + r * math.cos(math.radians(90 + 60 * k)), y + r * math.sin(math.radians(90 + 60 * k))) for k in range(6)]


def _face(poly) -> Face:
    """A shapely polygon as a build123d face."""
    wire = lambda ring: Wire.make_polygon([Vector(x, y) for x, y in ring.coords[:-1]], close=True)
    return Face(wire(poly.exterior), [wire(r) for r in poly.interiors])


PADS = {"left_bottom_pad": left, "right_bottom_pad": right}

if __name__ == "__main__":
    for name, layout in PADS.items():
        for suffix, grooved in (("", False), ("_grooved", True)):
            part = pad(layout, grooved)
            print(f"{name}{suffix}: volume {part.volume:.1f} mm^3, bbox {part.bounding_box().size}")
            export(part, name + suffix, flip=False, pose=Pos(0, 0, pad_thick))
