"""1:1 cutting template for an adhesive silicone sheet on the case bottom.

    uv run silicone_template.py   ->  out/silicone_template.pdf (one Letter page per half)

The printed TPU pads (bottom_pad.py) turned out slippery; a 1 mm adhesive silicone
sheet grips far better. This is the same plan as the pad: the case floor in past its
rounded bottom edge, open over the screw counterbores and the trackball hole. Every
hole has a cross at its centre and its punch size beside it.

Drawn seen from below, as you look at the upturned case: lay it on the sheet's grippy
face. On the backing paper the shape is the mirror image. Print at 100% and check the
50 mm bar.
"""

from bottom_pad import PADS, plan
from foam_template import PT, wire_points, write_pdf
from switch_plate import OUT

PAGE = (215.9, 279.4)  # Letter, portrait, mm


def page(layout, title: str) -> str:
    outline, holes, centres = plan(layout)
    flat = outline - holes
    bb = flat.bounding_box()
    # mirror (seen from below) and centre on the page, a little low to leave room for the notes
    cx, cy = (bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2
    ox, oy = PAGE[0] / 2, PAGE[1] / 2 - 8

    def at(x, y):
        return (ox - (x - cx)) * PT, (oy + (y - cy)) * PT

    ops = ["0 0 0 RG 0.6 w"]
    for face in flat.faces():
        for wire in [face.outer_wire(), *face.inner_wires()]:
            pts = [at(x, y) for x, y in wire_points(wire, step=0.2)]
            ops.append(" ".join(f"{x:.2f} {y:.2f} {'m' if i == 0 else 'l'}" for i, (x, y) in enumerate(pts)) + " h S")
    ops.append("0.3 w")
    for x, y, d in centres:
        px, py = at(x, y)
        c = 1.2 * PT
        ops.append(f"{px - c:.2f} {py:.2f} m {px + c:.2f} {py:.2f} l {px:.2f} {py - c:.2f} m {px:.2f} {py + c:.2f} l S")
        ops.append(f"BT /F1 6 Tf {px + (d / 2 + 1) * PT:.2f} {py - 1 * PT:.2f} Td ({d:g}) Tj ET")
    # 50 mm check bar
    x0, y0 = 20, 14
    ops.append(f"1.2 w {x0 * PT:.2f} {y0 * PT:.2f} m {(x0 + 50) * PT:.2f} {y0 * PT:.2f} l S")
    for x in (x0, x0 + 50):
        ops.append(f"{x * PT:.2f} {(y0 - 2) * PT:.2f} m {x * PT:.2f} {(y0 + 2) * PT:.2f} l S")
    ops.append(f"BT /F1 9 Tf {(x0 + 54) * PT:.2f} {(y0 - 1) * PT:.2f} Td (50 mm) Tj ET")
    w, h = bb.max.X - bb.min.X, bb.max.Y - bb.min.Y
    lines = [
        (title, 14),
        (f"Print at 100% (Actual size). The bar must measure 50 mm. Shape {w:.1f} x {h:.1f} mm.", 8),
        ("Seen from below, as on the upturned case: lay it on the grippy face. The backing paper is the mirror.", 8),
        ("Numbers are hole sizes in mm: punch 4.5 (3/16 in works) at each cross; cut the 12.5 trackball hole.", 8),
    ]
    y = PAGE[1] - 12
    for text, size in lines:
        ops.append(f"BT /F1 {size} Tf {12 * PT:.2f} {y * PT:.2f} Td ({text}) Tj ET")
        y -= size * 0.6
    return "\n".join(ops)


def main() -> None:
    streams = []
    for name, layout in PADS.items():
        half = name.split("_")[0].upper()
        streams.append(page(layout, f"Keyball61 {half} - silicone sheet for the case bottom"))
    path = OUT / "silicone_template.pdf"
    write_pdf(path, streams, PAGE)
    print("->", path)


if __name__ == "__main__":
    main()
