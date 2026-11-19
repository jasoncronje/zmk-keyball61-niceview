"""TPU grip pad for the case bottom, glued on in place of the stick-on feet.

Run `uv run bottom_pad.py` to write out/{left,right}_bottom_pad.{step,stl,3mf}.

The pad is the flat of the case bottom: the case's floor outline, in past its rounded
bottom edge, pad_thick thick. It is open over the screw
counterbores (pad_screw_hole, so the case still comes apart) and the trackball hole.
Plugs stand up from it into the feet's recesses and locate it while the glue sets.

`_grooved` versions add a hex grid of one-layer grooves to the desk side, joined to a
groove round the edge and a ring round every hole, which bite
a little on matte wood and give dust somewhere to go, at the cost of some contact area.

It prints plugs up, the desk side on the bed: a textured plate gives the grip side its
texture. In the STEP it sits under the case, as it is glued on.
"""

import math

import shapely
import shapely.geometry as sg
from build123d import Circle, Cylinder, Face, Kind, Pos, Sketch, Vector, Wire, extrude, offset

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
    pad_groove_sliver,
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
    """A hex grid of pad_groove-wide grooves over the pad, all one connected net: a
    groove runs round the edge pad_groove_rim in, and a ring groove round every hole
    pad_groove_rim out from it, and the grid runs into both. Each hole keeps its solid
    band whole, even where its ring meets the edge groove. Solid slivers thinner than
    pad_groove_sliver, where a grid line meets a ring at a shallow angle, are grooved
    out. Drawn in shapely, whose offsets don't fail on this many pieces."""
    edge = _shapely(outline.faces()[0].outer_wire())
    bx0, by0, bx1, by1 = edge.bounds
    dx, dy = pad_groove_pitch, pad_groove_pitch * math.sqrt(3) / 2  # rows of flat-sided cells
    gap = (pad_groove_pitch - pad_groove) / math.sqrt(3)  # circumradius of a cell's solid hexagon
    cells = []
    for j in range(int((by1 - by0) / dy) + 3):
        y = by0 - dy + j * dy
        shift = dx / 2 if j % 2 else 0.0
        for i in range(int((bx1 - bx0) / dx) + 3):
            cells.append(sg.Polygon(_hex_points(gap, bx0 - dx + shift + i * dx, y)))
    grid = sg.box(bx0 - dx, by0 - dx, bx1 + dx, by1 + dx).difference(shapely.unary_union(cells))

    edge_out = edge.buffer(-pad_groove_rim, quad_segs=32)
    edge_in = edge.buffer(-pad_groove_rim - pad_groove, quad_segs=32)
    bands, rings_out = [], []
    for h in holes:
        c, r = h.center(), h.bounding_box().size.X / 2 + pad_groove_rim
        bands.append(sg.Point(c.X, c.Y).buffer(r, quad_segs=32))  # the hole and its solid band
        rings_out.append(sg.Point(c.X, c.Y).buffer(r + pad_groove, quad_segs=32))
    bands, rings_out = shapely.unary_union(bands), shapely.unary_union(rings_out)

    net = grid.intersection(edge_in).difference(rings_out)
    net = shapely.unary_union([net, edge_out.difference(edge_in), rings_out]).intersection(edge_out).difference(bands)
    # groove out the solid slivers: open the solid (shrink, then grow back) and take the rest
    solid = edge_out.difference(net).difference(bands)
    solid = solid.buffer(-pad_groove_sliver / 2, join_style="mitre").buffer(pad_groove_sliver / 2, join_style="mitre")
    net = edge_out.difference(bands).difference(solid)
    return Sketch() + [_face(g) for g in getattr(net, "geoms", [net]) if g.area > 2 * pad_groove**2]


def _shapely(wire) -> "sg.Polygon":
    return sg.Polygon([(p.X, p.Y) for p in wire.positions([i / 4000 for i in range(4000)])])


def _face(poly) -> Face:
    """A shapely polygon as a build123d face, facing up (outline anticlockwise)."""
    poly = sg.polygon.orient(poly, 1.0)
    ring = lambda r: Wire.make_polygon([Vector(x, y) for x, y in r.coords[:-1]], close=True)
    return Face(ring(poly.exterior), [ring(r) for r in poly.interiors])


def _hex_points(r: float, x: float, y: float) -> list:
    """A cell's hexagon, pointy end up (flat sides left and right), circumradius r."""
    return [(x + r * math.cos(math.radians(90 + 60 * k)), y + r * math.sin(math.radians(90 + 60 * k))) for k in range(6)]


PADS = {"left_bottom_pad": left, "right_bottom_pad": right}

if __name__ == "__main__":
    for name, layout in PADS.items():
        for suffix, grooved in (("", False), ("_grooved", True)):
            part = pad(layout, grooved)
            print(f"{name}{suffix}: volume {part.volume:.1f} mm^3, bbox {part.bounding_box().size}")
            export(part, name + suffix, flip=False, pose=Pos(0, 0, pad_thick))
