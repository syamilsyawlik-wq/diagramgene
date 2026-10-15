"""Preview kasar layout hasil konversi (bukan render Sparx)."""
import io
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

FILL = {"task": "#FFF6D5", "gateway": "#D6EBB0", "data": "#E3F1EE",
        "start": "#DCE6F7", "end": "#DCE6F7", "link": "#EDE3F5"}


def _center(n):
    return (n["l"] + n["r"]) / 2, (n["t"] + n["b"]) / 2


def render_generic(page, dpi=90):
    items = page["items"]
    x1 = max(i["r"] for i in items) + 20
    y1 = max(i["b"] for i in items) + 20
    fig, ax = plt.subplots(figsize=(max(x1 / 110, 4), max(y1 / 110, 3)))
    by_key = {i["key"]: i for i in items}
    for it in sorted(items, key=lambda i: -i["seq"]):
        w, h = it["r"] - it["l"], it["b"] - it["t"]
        cx, cy = it["l"] + w / 2, it["t"] + h / 2
        if it["kind"] == "ellipse":
            ax.add_patch(patches.Ellipse((cx, cy), w, h, fc="#FFFFFF", ec="#333", lw=0.8))
        elif it["kind"] == "diamond":
            ax.add_patch(patches.Polygon([(cx, it["t"]), (it["r"], cy), (cx, it["b"]), (it["l"], cy)],
                                         fc="#FFFFFF", ec="#333", lw=0.8))
        elif it["kind"] == "container":
            ax.add_patch(patches.Rectangle((it["l"], it["t"]), w, h, fill=False, ec="#333", lw=1))
        elif it["kind"] != "text":
            ax.add_patch(patches.Rectangle((it["l"], it["t"]), w, h, fc="#FFFBEA", ec="#333", lw=0.7))
        lines = it["text"].split("\n")
        if it["kind"] == "container":
            ax.text(cx, it["t"] + 14, lines[0][:60], fontsize=6, ha="center", va="center", weight="bold")
        else:
            ax.text(cx if it["kind"] in ("ellipse", "diamond") else it["l"] + 4,
                    cy if it["kind"] in ("ellipse", "diamond") else it["t"] + 4,
                    "\n".join(textwrap.shorten(ln, 40) for ln in lines[:14]), fontsize=5,
                    ha="center" if it["kind"] in ("ellipse", "diamond") else "left",
                    va="center" if it["kind"] in ("ellipse", "diamond") else "top")
    for ln in page["links"]:
        a, b = by_key[ln["src"]], by_key[ln["tgt"]]
        ax.annotate("", xy=((b["l"] + b["r"]) / 2, (b["t"] + b["b"]) / 2),
                    xytext=((a["l"] + a["r"]) / 2, (a["t"] + a["b"]) / 2),
                    arrowprops=dict(arrowstyle="->" if ln["directed"] else "-", lw=0.6, color="#4A5578"))
    ax.set_xlim(0, x1)
    ax.set_ylim(y1, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_preview(page, dpi=90):
    if page.get("mode") == "generic":
        return render_generic(page, dpi)
    pool = page["pool"]
    w, h = pool["r"] - pool["l"], pool["b"] - pool["t"]
    fig, ax = plt.subplots(figsize=(max(w / 110, 4), max(h / 110, 3)))
    vertical = page.get("orient") == "vertical"

    ax.add_patch(patches.Rectangle((pool["l"], pool["t"]), w, h, fill=False, lw=1.2))
    ax.text(pool["l"] + 6, pool["t"] + 16 if vertical else pool["t"] + h / 2,
            pool["name"], fontsize=7, weight="bold",
            rotation=0 if vertical else 90, va="center")
    for lane in page["lanes"]:
        lw, lh = lane["r"] - lane["l"], lane["b"] - lane["t"]
        ax.add_patch(patches.Rectangle((lane["l"], lane["t"]), lw, lh, fill=False, lw=0.8))
        if vertical:
            ax.text(lane["l"] + lw / 2, lane["t"] + 16, textwrap.shorten(lane["name"], 32),
                    fontsize=6, ha="center", va="center")
        else:
            ax.text(lane["l"] + 14, lane["t"] + lh / 2, textwrap.shorten(lane["name"], 32),
                    fontsize=6, rotation=90, ha="center", va="center")

    nodes = {n["key"]: n for n in page["nodes"]}
    for f in page["flows"]:
        a, b = nodes[f["src"]], nodes[f["tgt"]]
        ax.annotate("", xy=_center(b), xytext=_center(a),
                    arrowprops=dict(arrowstyle="->", lw=0.6, color="#4A5578",
                                    ls="--" if f["kind"] == "data" else "-"))
    for n in page["nodes"]:
        nw, nh = n["r"] - n["l"], n["b"] - n["t"]
        if n["kind"] == "gateway":
            cx, cy = _center(n)
            shape = patches.Polygon([(cx, n["t"]), (n["r"], cy), (cx, n["b"]), (n["l"], cy)],
                                    fc=FILL["gateway"], ec="#333", lw=0.7)
        elif n["kind"] in ("start", "end", "link"):
            shape = patches.Circle(_center(n), nw / 2, fc=FILL[n["kind"]], ec="#333",
                                   lw=1.6 if n["kind"] == "end" else 0.7)
        else:
            shape = patches.FancyBboxPatch((n["l"], n["t"]), nw, nh,
                                           boxstyle="round,pad=0,rounding_size=6",
                                           fc=FILL[n["kind"]], ec="#333", lw=0.7)
        ax.add_patch(shape)
        label = "\n".join(textwrap.wrap(n["name"], 24))
        if n["kind"] == "task":
            ax.text(*_center(n), label, fontsize=5, ha="center", va="center")
        else:
            ax.text(_center(n)[0], n["b"] + 4, label, fontsize=5, ha="center", va="top")

    ax.set_xlim(pool["l"] - 10, pool["r"] + 60)
    ax.set_ylim(pool["b"] + 30, pool["t"] - 10)
    ax.set_aspect("equal")
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()