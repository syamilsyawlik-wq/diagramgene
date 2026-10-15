"""
visio_reader.py
Membaca flowchart Visio .vsdx (Visio 2013+) jadi data halaman untuk drawio_to_sparx.
Format .vsd (Visio lama) tidak didukung; simpan dulu sebagai .vsdx di Visio.

Pemetaan shape (dari nama master Visio, NameU, selalu bahasa Inggris):
  Swimlane / Functional band          -> Lane
  CFF Container                       -> Pool (judul pool)
  Process / Subprocess / Predefined   -> Task
  Decision                            -> Exclusive Gateway
  Start/End / Terminator              -> Start / End Event
  Document / Multiple documents / Data-> Data Object
  Off-page / On-page reference        -> Intermediate Event (penghubung antar halaman)
  Dynamic connector / garis 1-D       -> Sequence Flow (arah dari panah)
Shape lain dilewati dan dilaporkan di "skipped", kecuali shape tanpa master yang
bertuliskan teks dan tersambung connector ke shape proses (dianggap Task).
"""
import io
import re
import zipfile
from posixpath import dirname, join, normpath

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

V = "{http://schemas.microsoft.com/office/visio/2012/main}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
PX_PER_INCH = 96
MAX_UNZIPPED = 200 * 1024 * 1024

KIND_RULES = [                      # (kind, kata kunci pada nama master/shape)
    ("pool", ("cff container", "cross-functional flowchart")),
    ("lane", ("swimlane", "functional band", "lane")),
    ("ignore", ("separator", "phase", "title")),
    ("gateway", ("decision",)),
    ("event", ("start/end", "terminator", "start", "end")),
    ("data", ("document", "data", "database", "stored data")),
    ("link", ("off-page reference", "on-page reference", "off page", "page reference")),
    ("task", ("process", "subprocess", "sub-process", "predefined", "manual operation",
              "preparation", "operation")),
    ("edge", ("dynamic connector", "connector", "line", "arrow")),
]


def _kind_from_name(name):
    n = re.sub(r"\.\d+$", "", (name or "").strip().lower())
    if not n:
        return None
    for kind, keys in KIND_RULES:
        if any(k == n or k in n for k in keys):
            return kind
    return None


def _text(el):
    if el is None:
        return ""
    t = el.find(V + "Text")
    if t is None:
        return ""
    return re.sub(r"\s+", " ", "".join(t.itertext())).strip()


class _Pkg:
    def __init__(self, data):
        self.zf = zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in self.zf.infolist()) > MAX_UNZIPPED:
            raise ValueError("File Visio terlalu besar setelah diekstrak.")
        self.names = set(self.zf.namelist())

    def xml(self, path):
        return ET.fromstring(self.zf.read(path)) if path in self.names else None

    def rels(self, part):
        rp = join(dirname(part), "_rels", part.rsplit("/", 1)[-1] + ".rels")
        root = self.xml(rp)
        if root is None:
            return {}
        return {r.get("Id"): normpath(join(dirname(part), r.get("Target")))
                for r in root.iter(PKG_REL + "Relationship")}


class _Masters:
    """Master shape: default cell, teks, dan nama untuk shape turunan."""

    def __init__(self, pkg):
        self.info = {}                         # master id -> (NameU, {shape id: el}, main el)
        part = "visio/masters/masters.xml"
        root, rels = pkg.xml(part), pkg.rels(part)
        if root is None:
            return
        for m in root.iter(V + "Master"):
            rel = m.find(V + "Rel")
            target = rels.get(rel.get(R_ID)) if rel is not None else None
            content = pkg.xml(target) if target else None
            shapes, main = {}, None
            if content is not None:
                top = content.find(V + "Shapes")
                for s in content.iter(V + "Shape"):
                    shapes[s.get("ID")] = s
                if top is not None and len(top):
                    main = top[0]
            self.info[m.get("ID")] = (m.get("NameU") or m.get("Name") or "", shapes, main)

    def name(self, mid):
        return self.info.get(mid, ("",))[0]

    def shape(self, mid, sid=None):
        if mid not in self.info:
            return None
        _, shapes, main = self.info[mid]
        return shapes.get(sid) if sid else main


def _cells(el):
    return {c.get("N"): c.get("V") for c in el.findall(V + "Cell")} if el is not None else {}


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _collect_shapes(root, masters):
    shapes = {}                  # id -> info
    parent = {}

    def walk(container, par, inherit_master, ox, oy):
        if container is None:
            return
        for s in container.findall(V + "Shape"):
            sid = s.get("ID")
            mid = s.get("Master") or inherit_master
            mshape = masters.shape(s.get("Master")) if s.get("Master") else \
                masters.shape(inherit_master, s.get("MasterShape")) if s.get("MasterShape") else None
            cells = _cells(mshape)
            cells.update({k: v for k, v in _cells(s).items() if v is not None})
            w, h = _num(cells.get("Width")), _num(cells.get("Height"))
            left = ox + _num(cells.get("PinX")) - _num(cells.get("LocPinX"), w / 2)
            bottom = oy + _num(cells.get("PinY")) - _num(cells.get("LocPinY"), h / 2)
            one_d = "BeginX" in cells and "EndX" in cells
            text = _text(s) or _text(mshape)
            mname = masters.name(s.get("Master")) if s.get("Master") else ""
            info = {
                "id": sid, "master": mname, "shape_name": s.get("NameU") or s.get("Name") or "",
                "text": text, "one_d": one_d, "cells": cells, "ox": ox, "oy": oy,
                "g": (left, bottom, w, h), "children": [],
            }
            shapes[sid] = info
            parent[sid] = par
            if par:
                shapes[par]["children"].append(sid)
            walk(s.find(V + "Shapes"), sid, mid, left, bottom)

    walk(root.find(V + "Shapes"), None, None, 0.0, 0.0)
    return shapes, parent


def _read_page(name, root, masters, page_h):
    shapes, parent = _collect_shapes(root, masters)

    def to_px(g):                                   # inci, y ke atas -> px, y ke bawah
        left, bottom, w, h = g
        return (left * PX_PER_INCH, (page_h - bottom - h) * PX_PER_INCH, w * PX_PER_INCH, h * PX_PER_INCH)

    def full_text(sid):
        info = shapes.get(sid)
        if info is None:
            return ""
        parts = [info["text"]] if info["text"] else []
        for c in info["children"]:
            if not shapes[c]["one_d"]:
                parts.append(full_text(c))
        return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()

    kinds = {}
    for sid, info in shapes.items():
        kind = _kind_from_name(info["master"]) or _kind_from_name(info["shape_name"])
        if info["one_d"]:
            kind = "edge"
        elif kind == "edge":
            kind = None
        kinds[sid] = kind

    def top_node(sid):                  # naik ke leluhur terdekat yang shape proses
        while sid is not None and sid in shapes:
            if kinds.get(sid) in ("task", "gateway", "event", "data", "link"):
                return sid
            sid = parent.get(sid)
        return None

    # ---- connector: dari <Connects>, fallback posisi ujung garis
    glue = {}
    connects = root.find(V + "Connects")
    if connects is not None:
        for c in connects.findall(V + "Connect"):
            end = "begin" if (c.get("FromCell") or "").startswith("Begin") else "end"
            glue.setdefault(c.get("FromSheet"), {})[end] = c.get("ToSheet")

    flow_node_ids = {sid for sid, k in kinds.items() if k in ("task", "gateway", "event", "data", "link")
                     and top_node(parent.get(sid)) is None}
    pending_edges = []
    for sid, info in shapes.items():
        if kinds[sid] != "edge":
            continue
        cells = info["cells"]
        ends = {}
        for end, cx, cy in (("begin", "BeginX", "BeginY"), ("end", "EndX", "EndY")):
            target = glue.get(sid, {}).get(end)
            ends[end] = {"glued": target,
                         "pt": ((info["ox"] + _num(cells.get(cx))) * PX_PER_INCH,
                                (page_h - info["oy"] - _num(cells.get(cy))) * PX_PER_INCH)}
        begin_arrow = _num(cells.get("BeginArrow")) > 0
        end_arrow = _num(cells.get("EndArrow")) > 0
        if begin_arrow and not end_arrow:
            ends["begin"], ends["end"] = ends["end"], ends["begin"]
        pending_edges.append((ends, info["text"]))

    # shape tanpa master yang tersambung connector -> kandidat task
    promoted = set()

    def resolve(end):
        sid = end["glued"]
        if sid is not None and sid not in shapes:
            sid = None                       # glue ke shape yang tidak ada: pakai posisi ujung
        if sid is not None:
            node = top_node(sid)
            if node:
                return node
            root_id = sid
            while parent.get(root_id) in shapes:
                root_id = parent[root_id]
            if kinds.get(root_id) is None and full_text(root_id):
                promoted.add(root_id)
                return root_id
            return None
        x, y = end["pt"]                     # tidak di-glue: cari shape di titik ujung
        best, best_area = None, None
        for nid in flow_node_ids | promoted:
            gx, gy, gw, gh = to_px(shapes[nid]["g"])
            tol = 6
            if gx - tol <= x <= gx + gw + tol and gy - tol <= y <= gy + gh + tol:
                area = gw * gh
                if best_area is None or area < best_area:
                    best, best_area = nid, area
        return best

    flows = []
    for ends, label in pending_edges:
        src, tgt = resolve(ends["begin"]), resolve(ends["end"])
        if src and tgt and src != tgt:
            flows.append({"kind": "seq", "src": "v" + src, "tgt": "v" + tgt, "name": label})

    # ---- node, lane, pool
    nodes, lanes, pool_name, pool_g, skipped = {}, [], None, None, []
    for sid in list(flow_node_ids) + sorted(promoted):
        kind = kinds.get(sid) or "task"
        nodes["v" + sid] = {"kind": kind, "name": full_text(sid), "g": to_px(shapes[sid]["g"])}
    for sid, info in shapes.items():
        k = kinds[sid]
        if k == "lane":
            lanes.append(("v" + sid, full_text(sid) or info["shape_name"], to_px(info["g"])))
        elif k == "pool" and pool_g is None:
            pool_g, pool_name = to_px(info["g"]), full_text(sid)
        elif (k is None and parent.get(sid) is None and sid not in promoted and not info["one_d"]
              and full_text(sid)):
            skipped.append({"master": info["master"] or "(tanpa master)",
                            "text": full_text(sid)[:80]})

    lanes = [l for l in lanes if l[2][2] > 0 and l[2][3] > 0]
    return nodes, flows, lanes, pool_name, pool_g, skipped


def load_vsdx(data):
    """[(nama halaman, fungsi -> data halaman)]."""
    from drawio_to_sparx import finalize_page       # hindari import melingkar
    pkg = _Pkg(data)
    masters = _Masters(pkg)
    part = "visio/pages/pages.xml"
    root, rels = pkg.xml(part), pkg.rels(part)
    if root is None:
        raise ValueError("Struktur .vsdx tidak dikenali (visio/pages/pages.xml tidak ada).")
    out = []
    for p in root.iter(V + "Page"):
        if p.get("Background") == "1":
            continue                                   # halaman background (kop, logo)
        name = (p.get("Name") or p.get("NameU") or "Page").strip()
        rel = p.find(V + "Rel")
        target = rels.get(rel.get(R_ID)) if rel is not None else None
        page_h = _num(_cells(p.find(V + "PageSheet")).get("PageHeight"), 8.5)

        def build(name=name, target=target, page_h=page_h):
            content = pkg.xml(target) if target else None
            if content is None:
                raise ValueError("isi halaman tidak ditemukan")
            nodes, flows, lanes, pool_name, pool_g, skipped = _read_page(name, content, masters, page_h)
            page = finalize_page(name, pool_name or name, pool_g, lanes,
                                 {k: dict(v) for k, v in nodes.items()}, flows, skipped)
            return page
        out.append((name, build))
    return out


def _generic_model(root, masters, page_h):
    """Adapter Visio -> mxGraphModel, preserving generic shapes and connectors.

    Cached numeric geometry and glue references are used. Rotation, custom shape
    geometry, and Visio formula evaluation are not reproduced by this adapter.
    """
    from xml.etree.ElementTree import Element, SubElement
    shapes, parents = _collect_shapes(root, masters)
    model = Element("mxGraphModel")
    target = SubElement(model, "root")
    SubElement(target, "mxCell", id="0")
    SubElement(target, "mxCell", id="1", parent="0")

    def source_name(info):
        return (info["master"] + " " + info["shape_name"]).lower()

    def is_container(info):
        name = source_name(info)
        return any(s in name for s in ("container", "swimlane", "functional band", "lane"))

    # Visio master symbols often contain decorative child shapes. Model those as
    # one symbol, rather than importing each internal line or label as an entity.
    atomic = {sid for sid, info in shapes.items() if info["children"] and info["master"] and not is_container(info)}

    def atomic_ancestor(sid):
        current = parents.get(sid)
        while current is not None:
            if current in atomic:
                return current
            current = parents.get(current)
        return None

    def symbol_text(sid):
        info = shapes[sid]
        parts = [info["text"]] if info["text"] else []
        if sid in atomic:
            pending = list(info["children"])
            while pending:
                child = shapes[pending.pop(0)]
                if child["one_d"]:
                    continue
                if child["text"] and child["text"] not in parts:
                    parts.append(child["text"])
                pending.extend(child["children"])
        return "\n".join(parts)

    retained = set()
    for sid, info in shapes.items():
        if info["one_d"] or atomic_ancestor(sid):
            continue
        x, bottom, w, h = info["g"]
        if w <= 0 or h <= 0:
            continue
        name = source_name(info)
        if is_container(info) or (info["children"] and sid not in atomic):
            style = "swimlane;"
        elif any(k in name for k in ("annotation", "callout", "note")):
            style = "shape=note;"
        elif any(k in name for k in ("text", "title", "label")):
            style = "text;"
        elif any(k in name for k in ("decision", "diamond")):
            style = "rhombus;"
        elif any(k in name for k in ("ellipse", "circle", "terminator")):
            style = "ellipse;"
        else:
            style = "rounded=0;"
        style += "semantic=" + re.sub(r"[^a-z0-9_ .-]", "", name) + ";"
        cell = SubElement(target, "mxCell", id="v" + sid, parent="1", vertex="1",
                          value=symbol_text(sid), style=style)
        SubElement(cell, "mxGeometry", x=str(x * PX_PER_INCH),
                   y=str((page_h - bottom - h) * PX_PER_INCH),
                   width=str(w * PX_PER_INCH), height=str(h * PX_PER_INCH), **{"as": "geometry"})
        retained.add(sid)

    glue = {}
    for connection in root.iter(V + "Connect"):
        cell = connection.get("FromCell", "")
        if cell.startswith(("Begin", "End")):
            end = "source" if cell.startswith("Begin") else "target"
            glue.setdefault(connection.get("FromSheet"), {})[end] = connection.get("ToSheet")

    def endpoint(sid):
        atom = atomic_ancestor(sid)
        if atom:
            sid = atom
        while sid is not None:
            if sid in retained:
                return "v" + sid
            sid = parents.get(sid)
        return None

    for sid, info in shapes.items():
        if not info["one_d"] or atomic_ancestor(sid):
            continue
        cells = info["cells"]
        attrs = {end: endpoint(glue.get(sid, {}).get(end)) for end in ("source", "target")}
        attrs = {k: v for k, v in attrs.items() if v is not None}
        style = ("startArrow=" + ("classic" if _num(cells.get("BeginArrow")) > 0 else "none") +
                 ";endArrow=" + ("classic" if _num(cells.get("EndArrow")) > 0 else "none") + ";")
        cell = SubElement(target, "mxCell", id="v" + sid, parent="1", edge="1",
                          value=info["text"], style=style, **attrs)
        geo = SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        for end, cx, cy in (("sourcePoint", "BeginX", "BeginY"), ("targetPoint", "EndX", "EndY")):
            SubElement(geo, "mxPoint", x=str((info["ox"] + _num(cells.get(cx))) * PX_PER_INCH),
                       y=str((page_h - info["oy"] - _num(cells.get(cy))) * PX_PER_INCH), **{"as": end})
    return model


def load_vsdx_generic(data):
    """Halaman Visio non-background sebagai masukan mode entitas umum."""
    pkg = _Pkg(data)
    masters = _Masters(pkg)
    part = "visio/pages/pages.xml"
    root, rels = pkg.xml(part), pkg.rels(part)
    if root is None:
        raise ValueError("Struktur .vsdx tidak dikenali (visio/pages/pages.xml tidak ada).")
    out = []
    for page in root.iter(V + "Page"):
        if page.get("Background") == "1":
            continue
        name = (page.get("Name") or page.get("NameU") or "Page").strip()
        rel = page.find(V + "Rel")
        content = pkg.xml(rels.get(rel.get(R_ID))) if rel is not None and rel.get(R_ID) in rels else None
        if content is None:
            raise ValueError(f"{name}: isi halaman Visio tidak ditemukan.")
        page_h = _num(_cells(page.find(V + "PageSheet")).get("PageHeight"), 8.5)
        out.append((name, _generic_model(content, masters, page_h)))
    return out
