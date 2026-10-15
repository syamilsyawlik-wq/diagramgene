"""
drawio_to_sparx.py
Konversi swimlane flowchart draw.io / Visio (.vsdx) -> script JScript Sparx EA
(diagram BPMN 2.0). Parser Visio ada di visio_reader.py.

Pakai:  python drawio_to_sparx.py input.(drawio|xml|vsdx) output.js [--horizontal | --keep-layout]
        default: auto-layout BPMN vertikal (lane = kolom, alur atas -> bawah)
                 -> setelah run di Sparx: klik kanan background diagram >
                    Set Diagram Flow Direction > Vertical
        --horizontal: lane = baris, alur kiri -> kanan
        --keep-layout: pakai koordinat asli draw.io
Lalu paste isi output.js ke script JScript baru di Sparx (Specialize > Scripting),
pilih package tujuan di Project Browser, dan jalankan.

Aturan konversi:
- swimlane teratas            -> Pool, swimlane di dalamnya -> Lane
- decision / rhombus          -> Exclusive Gateway
- terminator / dfd.start      -> Start Event (tanpa panah masuk) / End Event (tanpa panah keluar)
- document / parallelogram    -> Data Object
- kotak lain                  -> Task
- lane ditentukan dari POSISI tengah shape (bukan parent di draw.io),
  karena di draw.io shape sering "tumpah" ke lane sebelah.
- Data Object yang ada di tengah alur di-bypass: A -> D -> B  jadi  A -> B (sequence)
  plus data association A -> D (kalau A task) dan D -> B (kalau B task).
- Data Object yang tidak tersambung -> data association ke task terdekat.
- Panah tanpa source/target dicari ke shape terdekat dari ujung panahnya.
- Panah yang menunjuk ke dirinya sendiri dibuang.
"""
import base64, html, json, math, re, sys, urllib.parse, zlib
try:                                    # aman untuk file upload (XML bomb, entity)
    import defusedxml.ElementTree as ET
except ImportError:                     # fallback kalau defusedxml belum terpasang
    import xml.etree.ElementTree as ET

MARGIN = 20  # jarak pool dari pojok kiri atas diagram Sparx


MAX_INFLATED = 20 * 1024 * 1024        # batas hasil dekompresi per halaman


def load_pages(source):
    """source: path file atau bytes isi file draw.io."""
    if isinstance(source, (bytes, bytearray)):
        root = ET.fromstring(bytes(source))
    else:
        root = ET.parse(source).getroot()
    tag = root.tag.split("}")[-1]
    if tag == "mxGraphModel":                    # XML mentah tanpa <mxfile>
        return [("Page-1", root)]
    if tag not in ("mxfile", "diagram"):
        raise ValueError("File XML ini bukan diagram draw.io.")
    pages = []
    for d in ([root] if tag == "diagram" else root.iter("diagram")):
        model = d.find("mxGraphModel")
        if model is None and (d.text or "").strip():
            dec = zlib.decompressobj(-15)
            raw = dec.decompress(base64.b64decode(d.text), MAX_INFLATED).decode("utf-8")
            if dec.unconsumed_tail:
                raise ValueError("Halaman '%s' terlalu besar setelah dekompresi" % d.get("name"))
            model = ET.fromstring(urllib.parse.unquote(raw))
            if model.tag != "mxGraphModel":
                model = model.find(".//mxGraphModel")
        if model is not None:
            model.set('_diagramgene_page_id', d.get('id') or d.get('name') or 'Page')
            pages.append((d.get("name") or "Page", model))
    return pages


def clean(text):
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def f(v):
    return float(v) if v not in (None, "") else 0.0


def parse_style(style):
    """'rounded=1;shape=process' -> ('rounded', {'rounded': '1', 'shape': 'process'})."""
    parts = [p for p in (style or "").split(";") if p]
    base = parts[0].lower() if parts and "=" not in parts[0] else ""
    kv = {}
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k.strip().lower()] = v.strip().lower()
    return base, kv


def _has(text, *keys):
    return any(k in text for k in keys)


def classify(style):
    """Jenis shape draw.io dari style-nya.
    Hasil: swimlane | label | text | note | image | group | link | gateway | event |
           data | task"""
    base, kv = parse_style(style)
    shape = kv.get("shape", "")
    s = (style or "").lower()
    key = base + " " + shape

    if base == "swimlane" or _has(shape, "swimlane", "pool", "lane") or shape == "table":
        return "swimlane"
    if "edgelabel" in s:
        return "label"
    if base in ("text", "label") or kv.get("text") == "1":
        return "text"
    if base == "group":
        return "group"
    if base == "image" or shape == "image":
        return "image"
    if _has(key, "note", "annotation", "callout", "comment"):
        return "note"
    if _has(key, "off-page", "offpage", "on-page", "onpage", "page_reference", "link_event"):
        return "link"
    if _has(key, "rhombus", "decision", "gateway", "diamond"):
        return "gateway"
    if _has(key, "ellipse", "doubleellipse", "terminator", "start_1", "start_2", "dfd.start",
            "bpmn.event", "endstate", "startstate", "initial", "final", "event", "circle"):
        return "event"
    if _has(key, "document", "parallelogram", "cylinder", "datastore", "data_store", "database",
            "stored_data", "internal_storage", "tape_data", "flowchart.data", "bpmn.data",
            "dataobject", "data_object", "card"):
        return "data"
    return "task"


def _rect_dist(pt, g):
    """Jarak titik ke tepi kotak (0 kalau di dalam)."""
    x, y, w, h = g
    dx = max(x - pt[0], 0, pt[0] - (x + w))
    dy = max(y - pt[1], 0, pt[1] - (y + h))
    return math.hypot(dx, dy)


def _nearest(pt, geoms, candidates):
    def c(k):
        x, y, w, h = geoms[k]
        return x + w / 2, y + h / 2
    return min(candidates, key=lambda k: math.dist(pt, c(k)), default=None)


def finalize_page(name, pool_name, pool_g, lanes, nodes, flows, skipped=None):
    """Langkah bersama untuk semua format input.
    pool_g / geometri: (x, y, w, h) absolut, sumbu y ke bawah.
    lanes: [(key, nama, g)]; nodes: {key: {"kind", "name", "g"}};
    flows: [{"kind": "seq", "src", "tgt", "name"}] (key sudah valid)."""
    geoms = {k: n["g"] for k, n in nodes.items()}
    flows = [fl for fl in flows if fl["src"] in nodes and fl["tgt"] in nodes and fl["src"] != fl["tgt"]]

    # ---- start / end events
    for k, n in nodes.items():
        if n["kind"] == "event":
            has_in = any(fl["tgt"] == k for fl in flows)
            has_out = any(fl["src"] == k for fl in flows)
            is_end = re.search(r"\b(finish|end|selesai|akhir|stop)\b", n["name"], re.I)
            is_start = re.search(r"\b(start|mulai|awal|begin)\b", n["name"], re.I)
            if has_in and not has_out:
                n["kind"] = "end"
            elif has_out and not has_in:
                n["kind"] = "start"
            elif has_in and has_out:                 # di tengah alur: intermediate event
                n["kind"] = "end" if is_end else "start" if is_start else "link"
            else:
                n["kind"] = "end" if is_end else "start"

    # ---- penghubung (off-page reference) di ujung alur -> start / end event
    for k, n in nodes.items():
        if n["kind"] == "link":
            has_in = any(fl["tgt"] == k for fl in flows)
            has_out = any(fl["src"] == k for fl in flows)
            if has_in and not has_out:
                n["kind"] = "end"
            elif has_out and not has_in:
                n["kind"] = "start"

    # ---- bypass data objects
    tasks = [k for k, n in nodes.items() if n["kind"] == "task"]
    for d in [k for k, n in nodes.items() if n["kind"] == "data"]:
        ins = [fl for fl in flows if fl["tgt"] == d]
        outs = [fl for fl in flows if fl["src"] == d]
        flows = [fl for fl in flows if d not in (fl["src"], fl["tgt"])]
        if not ins and not outs:
            x, y, w, h = geoms[d]
            t = _nearest((x + w / 2, y + h / 2), geoms, tasks)
            if t:
                flows.append({"kind": "data", "src": d, "tgt": t, "name": ""})
            continue
        for a in ins:
            if nodes[a["src"]]["kind"] == "task":
                flows.append({"kind": "data", "src": a["src"], "tgt": d, "name": ""})
        for b in outs:
            if nodes[b["tgt"]]["kind"] == "task":
                flows.append({"kind": "data", "src": d, "tgt": b["tgt"], "name": ""})
        for a in ins:
            for b in outs:
                if a["src"] != b["tgt"]:
                    flows.append({"kind": "seq", "src": a["src"], "tgt": b["tgt"],
                                  "name": a["name"] or b["name"]})

    # ---- dedupe
    seen, uniq = set(), []
    for fl in flows:
        key = (fl["kind"], fl["src"], fl["tgt"])
        if key not in seen:
            seen.add(key)
            uniq.append(fl)
    flows = uniq

    # ---- pool & lane default
    if pool_g is None:
        xs = [g[0] for g in geoms.values()] + [g[0] + g[2] for g in geoms.values()]
        ys = [g[1] for g in geoms.values()] + [g[1] + g[3] for g in geoms.values()]
        pool_g = (min(xs) - 40, min(ys) - 40, max(xs) - min(xs) + 80, max(ys) - min(ys) + 80)
    if not lanes:
        lanes = [("lane_0", pool_name, pool_g)]
    lanes = sorted(lanes, key=lambda l: (round(l[2][1]), round(l[2][0])))
    lane_g = {k: g for k, _, g in lanes}
    avg_w = sum(g[2] for g in lane_g.values()) / len(lane_g)
    avg_h = sum(g[3] for g in lane_g.values()) / len(lane_g)
    native = "vertical" if len(lanes) == 1 or avg_w <= avg_h else "horizontal"

    px, py = pool_g[0], pool_g[1]

    def rect(g):
        x, y, w, h = g
        l, t = round(x - px + MARGIN), round(y - py + MARGIN)
        return {"l": l, "t": t, "r": l + round(w), "b": t + round(h)}

    def lane_of(g):
        cx, cy = g[0] + g[2] / 2, g[1] + g[3] / 2
        inside = [k for k, lg in lane_g.items()
                  if lg[0] <= cx < lg[0] + lg[2] and lg[1] <= cy < lg[1] + lg[3]]
        if inside:
            return min(inside, key=lambda k: lane_g[k][2] * lane_g[k][3])
        return _nearest((cx, cy), lane_g, list(lane_g))

    out_nodes = []
    for k, n in nodes.items():
        out_nodes.append(dict(key=k, kind=n["kind"], name=n["name"], lane=lane_of(n["g"]), **rect(n["g"])))
    return {"name": name, "pool": dict(name=pool_name, **rect(pool_g)),
            "lanes": [dict(key=k, name=nm, **rect(g)) for k, nm, g in lanes],
            "nodes": out_nodes, "flows": flows, "native_orient": native,
            "skipped": skipped or []}


EDGE_SNAP = 40      # px: ujung garis dianggap menempel ke shape dalam jarak ini
FLOW_KINDS = ("task", "gateway", "event", "data", "link")


def convert_page(name, model):
    """Halaman draw.io -> data halaman."""
    cells = {}
    for c in model.iter("mxCell"):
        if c.get("id"):
            cells[c.get("id")] = c
    # <object>/<UserObject label="..."><mxCell .../></object>: id & label ada di pembungkus
    for obj in model.iter():
        if obj.tag in ("object", "UserObject") and obj.get("id"):
            inner = obj.find("mxCell")
            if inner is not None:
                inner.set("id", obj.get("id"))
                if not inner.get("value"):
                    inner.set("value", obj.get("label", ""))
                cells[obj.get("id")] = inner
    absg = {}

    def geom(cid):
        if cid in absg:
            return absg[cid]
        c = cells.get(cid)
        if c is None or c.get("vertex") != "1":
            absg[cid] = (0.0, 0.0, 0.0, 0.0)
            return absg[cid]
        absg[cid] = (0.0, 0.0, 0.0, 0.0)          # jaga-jaga parent melingkar
        g = c.find("mxGeometry")
        px, py, _, _ = geom(c.get("parent"))
        if g is None or g.get("relative") == "1":
            r = (px, py, 0.0, 0.0)
        else:
            r = (px + f(g.get("x")), py + f(g.get("y")), f(g.get("width")), f(g.get("height")))
        absg[cid] = r
        return r

    kinds = {cid: classify(c.get("style") or "") for cid, c in cells.items() if c.get("vertex") == "1"}
    children = {}
    for cid, c in cells.items():
        children.setdefault(c.get("parent"), []).append(cid)

    # kotak biasa yang jadi wadah shape lain (container=1 atau punya anak shape) -> lane
    for cid, k in list(kinds.items()):
        if k not in ("task", "data", "note"):
            continue
        _, kv = parse_style(cells[cid].get("style"))
        kids = [x for x in children.get(cid, []) if kinds.get(x) in FLOW_KINDS + ("swimlane",)]
        if kv.get("container") == "1" or kids:
            kinds[cid] = "swimlane"

    labels, skipped = {}, []
    for cid, k in kinds.items():
        c = cells[cid]
        if k == "label":
            labels[c.get("parent")] = clean(c.get("value"))
        elif k in ("text", "note", "image"):
            txt = clean(c.get("value"))
            if txt:
                jenis = {"text": "Teks lepas", "note": "Catatan", "image": "Gambar"}[k]
                skipped.append({"master": jenis, "text": txt[:80]})

    nodes = {cid: {"kind": k, "name": clean(cells[cid].get("value")), "g": geom(cid)}
             for cid, k in kinds.items() if k in FLOW_KINDS}
    swimlanes = [cid for cid, k in kinds.items() if k == "swimlane"]

    # tanpa swimlane: kotak besar yang melingkupi >= 2 shape juga dianggap lane
    if not swimlanes and len(nodes) >= 3:
        areas = sorted(n["g"][2] * n["g"][3] for n in nodes.values() if n["kind"] == "task")
        median = areas[len(areas) // 2] if areas else 0
        for cid, n in list(nodes.items()):
            x, y, w, h = n["g"]
            if n["kind"] != "task" or median == 0 or w * h < 4 * median:
                continue
            inside = [k for k, o in nodes.items() if k != cid and
                      x <= o["g"][0] and y <= o["g"][1] and
                      o["g"][0] + o["g"][2] <= x + w and o["g"][1] + o["g"][3] <= y + h]
            if len(inside) >= 2:
                swimlanes.append(cid)
        # kotak seukuran lane yang sudah ketemu (mis. lane yang isinya cuma 1 shape)
        for cid, n in list(nodes.items()):
            if cid in swimlanes or n["kind"] != "task":
                continue
            w, h = n["g"][2], n["g"][3]
            if any(abs(w - geom(l)[2]) <= 0.15 * geom(l)[2] and abs(h - geom(l)[3]) <= 0.15 * geom(l)[3]
                   for l in swimlanes):
                swimlanes.append(cid)
        for cid in swimlanes:
            nodes.pop(cid, None)
            kinds[cid] = "swimlane"

    # shape kosong yang tidak tersambung = dekorasi, abaikan
    connected = set()
    for c in cells.values():
        if c.get("edge") == "1":
            connected.update([c.get("source"), c.get("target")])
    for cid in [k for k, n in nodes.items()
                if not n["name"] and k not in connected and n["kind"] in ("task", "data")]:
        nodes.pop(cid)

    # pool = swimlane terluar yang berisi swimlane lain (lewat parent atau posisi)
    sl = set(swimlanes)

    def swim_parent(k):
        p = cells[k].get("parent")
        seen = set()
        while p is not None and p in cells and p not in seen:
            if p in sl:
                return p
            seen.add(p)
            p = cells[p].get("parent")
        return None

    def inside_other(k):
        x, y, w, h = geom(k)
        for o in swimlanes:
            ox_, oy_, ow, oh = geom(o)
            if o != k and ow * oh > w * h and ox_ <= x and oy_ <= y and \
                    x + w <= ox_ + ow and y + h <= oy_ + oh:
                return o
        return None

    def outer(k):
        return swim_parent(k) or inside_other(k)

    nested = [k for k in swimlanes if outer(k)]
    pools = [k for k in swimlanes if k not in nested and any(outer(n) == k for n in nested)]
    loose = [k for k in swimlanes if k not in nested and k not in pools]
    lanes = nested + loose

    def bbox(keys):
        gs = [geom(k) for k in keys]
        x0, y0 = min(g[0] for g in gs), min(g[1] for g in gs)
        x1, y1 = max(g[0] + g[2] for g in gs), max(g[1] + g[3] for g in gs)
        return (x0, y0, x1 - x0, y1 - y0)

    if len(pools) == 1:
        pool_name, pool_g = clean(cells[pools[0]].get("value")) or name, geom(pools[0])
    elif pools:
        pool_name, pool_g = name, bbox(pools)
    elif lanes:
        pool_name, pool_g = name, bbox(lanes)
    else:
        pool_name, pool_g = name, None            # tanpa lane: satu lane otomatis
    geoms = {k: n["g"] for k, n in nodes.items()}

    def to_node(cid):                             # naik ke leluhur yang berupa shape proses
        seen = set()
        while cid is not None and cid in cells and cid not in seen:
            if cid in nodes:
                return cid
            seen.add(cid)
            cid = cells[cid].get("parent")
        return None

    flows, loose_edges = [], 0
    for cid, c in cells.items():
        if c.get("edge") != "1":
            continue
        ends = {"source": to_node(c.get("source")), "target": to_node(c.get("target"))}
        g = c.find("mxGeometry")
        ox, oy, _, _ = geom(c.get("parent"))
        for end in ("source", "target"):
            if ends[end] is not None or g is None or not nodes:
                continue
            pt = g.find(f"mxPoint[@as='{end}Point']")
            if pt is None:
                continue
            p = (ox + f(pt.get("x")), oy + f(pt.get("y")))
            best = min(nodes, key=lambda k: _rect_dist(p, geoms[k]))
            if _rect_dist(p, geoms[best]) <= EDGE_SNAP:
                ends[end] = best
        src, tgt = ends["source"], ends["target"]
        if src is None or tgt is None:
            loose_edges += 1
            continue
        _, kv = parse_style(c.get("style"))
        start_arrow = kv.get("startarrow", "none") not in ("none", "")
        end_arrow = kv.get("endarrow", "classic") not in ("none", "")
        if start_arrow and not end_arrow:        # panah digambar terbalik
            src, tgt = tgt, src
        flows.append({"kind": "seq", "src": src, "tgt": tgt,
                      "name": clean(c.get("value")) or labels.get(cid, "")})
    if loose_edges:
        skipped.append({"master": "Garis tanpa ujung",
                        "text": f"{loose_edges} garis tidak menempel ke shape mana pun"})

    return finalize_page(name, pool_name, pool_g,
                         [(k, clean(cells[k].get("value")) or "Lane", geom(k)) for k in lanes],
                         nodes, flows, skipped)


# ---------------------------------------------------------------------------
# Auto-layout BPMN. vertical (default): lane = kolom, alur atas->bawah.
#                  horizontal: lane = baris, alur kiri->kanan.
# Kolom ditentukan dari urutan alur (longest path), bukan dari posisi draw.io.
POOL_HDR, LANE_HDR = 30, 30          # kolom label pool & label lane
COL_W, PAD_X = 190, 30          # horizontal
ROW_H, PAD_Y = 115, 20          # vertical
SIZE = {"task": (140, 64), "gateway": (50, 50), "start": (30, 30),
        "end": (30, 30), "data": (40, 50), "link": (30, 30)}


def auto_layout(page, orient="vertical"):
    nodes = {n["key"]: n for n in page["nodes"]}
    seq = [f for f in page["flows"] if f["kind"] == "seq"]
    succ = {k: [] for k in nodes}
    for f in seq:
        succ[f["src"]].append(f["tgt"])

    # ---- buang panah balik (loop) supaya grafnya DAG.
    # Utamakan panah yang di diagram asli memang mengarah ke belakang (berdasarkan posisi
    # sepanjang arah alur), baru sisanya diputus lewat DFS.
    cx = {k: (n["l"] + n["r"]) / 2 for k, n in nodes.items()}
    cy = {k: (n["t"] + n["b"]) / 2 for k, n in nodes.items()}
    if len(page["lanes"]) > 1:
        axis = cx if page.get("native_orient") == "horizontal" else cy
    else:
        spread_x = max(cx.values(), default=0) - min(cx.values(), default=0)
        spread_y = max(cy.values(), default=0) - min(cy.values(), default=0)
        axis = cx if spread_x > spread_y else cy

    edges = [(f["src"], f["tgt"]) for f in seq]

    def reaches(a, b, back):
        stack, seen = [a], {a}
        while stack:
            u = stack.pop()
            if u == b:
                return True
            for x, y in edges:
                if x == u and (x, y) not in back and y not in seen:
                    seen.add(y)
                    stack.append(y)
        return False

    back = set()
    for u, v in sorted(edges, key=lambda e: axis[e[1]] - axis[e[0]]):
        if axis[v] < axis[u] - 5 and reaches(v, u, back):
            back.add((u, v))

    succ = {k: [] for k in nodes}
    for u, v in edges:
        if (u, v) not in back:
            succ[u].append(v)
    state, forward = {}, {k: [] for k in nodes}

    def dfs(u):
        state[u] = 1
        for v in sorted(succ[u], key=lambda k: axis[k]):
            if state.get(v) == 1:
                continue                      # sisa siklus
            forward[u].append(v)
            if v not in state:
                dfs(v)
        state[u] = 2
    starts = [k for k, n in nodes.items() if n["kind"] == "start"] + sorted(nodes, key=lambda k: axis[k])
    for s0 in starts:
        if s0 not in state and nodes[s0]["kind"] != "data":
            dfs(s0)

    rank = {}

    def r(u):
        if u not in rank:
            preds = [a for a in forward if u in forward[a]]
            rank[u] = 0 if not preds else 1 + max(r(a) for a in preds)
        return rank[u]
    flow_nodes = [k for k, n in nodes.items() if n["kind"] != "data"]
    for k in flow_nodes:
        r(k)

    # data object ikut lane & kolom task yang terhubung
    assoc = {}
    for f in page["flows"]:
        if f["kind"] == "data":
            d, t = (f["src"], f["tgt"]) if nodes[f["src"]]["kind"] == "data" else (f["tgt"], f["src"])
            assoc.setdefault(d, []).append(t)
    for d, ts in assoc.items():
        nodes[d]["lane"] = nodes[ts[0]]["lane"]

    lane_keys = [l["key"] for l in page["lanes"]]
    has_data = {lk: any(nodes[d]["lane"] == lk for d in assoc) for lk in lane_keys}
    nranks = max(rank.values(), default=0) + 1
    vertical = (orient == "vertical")
    page["orient"] = orient

    # slot: elemen di lane & urutan yang sama diletakkan berdampingan, bukan bertumpuk
    slot, per_cell = {}, {}
    for k in flow_nodes:
        cell = (nodes[k]["lane"], rank[k])
        slot[k] = per_cell.get(cell, 0)
        per_cell[cell] = slot[k] + 1
    max_slots = {lk: max([c for (ln, _), c in per_cell.items() if ln == lk] or [1]) for lk in lane_keys}
    SLOT_W, SLOT_H = 170, 95
    offset, lane_pos = MARGIN, {}

    if vertical:
        # lane = kolom (kiri->kanan), alur = atas->bawah
        y0 = MARGIN + POOL_HDR + LANE_HDR + PAD_Y
        height = POOL_HDR + LANE_HDR + 2 * PAD_Y + nranks * ROW_H
        for l in page["lanes"]:
            w = 210 + (max_slots[l["key"]] - 1) * SLOT_W + (70 if has_data[l["key"]] else 0)
            l.update(l=offset, t=MARGIN + POOL_HDR, r=offset + w, b=MARGIN + height)
            lane_pos[l["key"]] = offset
            offset += w
        page["pool"].update(l=MARGIN, t=MARGIN, r=offset, b=MARGIN + height)
    else:
        # lane = baris (atas->bawah), alur = kiri->kanan
        x0 = MARGIN + POOL_HDR + LANE_HDR + PAD_X
        width = POOL_HDR + LANE_HDR + 2 * PAD_X + nranks * COL_W
        for l in page["lanes"]:
            h = 130 + (max_slots[l["key"]] - 1) * SLOT_H + (70 if has_data[l["key"]] else 0)
            l.update(l=MARGIN + POOL_HDR, t=offset, r=MARGIN + width, b=offset + h)
            lane_pos[l["key"]] = offset
            offset += h
        page["pool"].update(l=MARGIN, t=MARGIN, r=MARGIN + width, b=offset)

    def put(n, cx, cy):
        w, h = SIZE[n["kind"]]
        n.update(l=round(cx - w / 2), t=round(cy - h / 2), r=round(cx + w / 2), b=round(cy + h / 2))

    for k in flow_nodes:
        n = nodes[k]
        if vertical:
            put(n, lane_pos[n["lane"]] + 105 + slot[k] * SLOT_W, y0 + rank[k] * ROW_H + ROW_H / 2 - PAD_Y)
        else:
            put(n, x0 + rank[k] * COL_W + COL_W / 2 - PAD_X, lane_pos[n["lane"]] + 60 + slot[k] * SLOT_H)

    # data object: di sisi kanan (vertikal) / bawah (horizontal) lane, hindari saling tumpuk
    placed = {}

    def put_data(n, along):
        lane = n["lane"]
        taken = placed.setdefault(lane, [])
        while any(abs(along - t) < 60 for t in taken):
            along += 60
        taken.append(along)
        if vertical:
            side = lane_pos[lane] + 105 + max_slots[lane] * SLOT_W - SLOT_W + 130
            put(n, side, along)
        else:
            side = lane_pos[lane] + 60 + max_slots[lane] * SLOT_H - SLOT_H + 90
            put(n, along, side)

    for d, ts in assoc.items():
        if vertical:
            along = sum((nodes[t]["t"] + nodes[t]["b"]) / 2 for t in ts) / len(ts) + (35 if len(ts) == 1 else 0)
        else:
            along = sum((nodes[t]["l"] + nodes[t]["r"]) / 2 for t in ts) / len(ts) + (45 if len(ts) == 1 else 0)
        put_data(nodes[d], along)
    for d in [k for k, n in nodes.items() if n["kind"] == "data" and k not in assoc]:
        put_data(nodes[d], MARGIN + POOL_HDR + LANE_HDR + 40)
    return page


JSCRIPT = r"""// Generated by drawio_to_sparx.py  --  Bahasa: JScript
// Cara pakai: pilih package tujuan di Project Browser, lalu Run script ini.
// Tiap halaman draw.io dibuatkan sub-package + diagram BPMN sendiri.
// Layout vertikal: pool & lane otomatis diset VPartition (header di atas).
// Opsional: klik kanan background > Set Diagram Flow Direction > Vertical.

// Tipe dasar connector. Kalau di Sparx kamu Data Association muncul dengan
// tipe lain, gambar satu Data Association manual, cek Type-nya, lalu ganti di sini.
var SEQ_BASE    = "ControlFlow";
var SEQ_STEREO  = "BPMN2.0::SequenceFlow";
var DATA_BASE   = "Dependency";
var DATA_STEREO = "BPMN2.0::DataAssociation";
var LINK_STYLE  = "Mode=3;TREE=OS;";   // Orthogonal - Square. "Mode=3;TREE=OR;" = rounded

var ELEMENT_TYPE = {
    "task":    "BPMN2.0::Activity",
    "gateway": "BPMN2.0::Gateway",
    "start":   "BPMN2.0::StartEvent",
    "end":     "BPMN2.0::EndEvent",
    "data":    "BPMN2.0::DataObject",
    "link":    "BPMN2.0::IntermediateEvent"
};

var PAGES = __DATA__;

function log(msg) { Session.Output(msg); }

function mustUpdate(obj, what) {
    if (!obj.Update()) { throw new Error("Gagal membuat " + what + ": " + obj.GetLastError()); }
    return obj;
}

function place(dia, el, g, seq) {
    var pos = "l=" + g.l + ";r=" + g.r + ";t=" + g.t + ";b=" + g.b + ";";
    var o = dia.DiagramObjects.AddNew(pos, "");
    o.ElementID = el.ElementID;
    o.Sequence = seq;              // angka besar = di belakang (pool/lane)
    mustUpdate(o, "diagram object " + el.Name);
    return o;
}

function setVertical(o, name) {    // header pool/lane di atas, bukan di samping
    var st = String(o.Style || "");
    if (st.indexOf("VPartition") >= 0) { return; }
    if (st.length > 0 && st.charAt(st.length - 1) != ";") { st += ";"; }
    o.Style = st + "VPartition=1;";
    mustUpdate(o, "orientasi " + name);
}

function resetRect(o, g, name) {   // koordinat Sparx: y negatif ke bawah
    o.left = g.l; o.right = g.r; o.top = -g.t; o.bottom = -g.b;
    mustUpdate(o, "posisi " + name);
}

function buildPage(parentPkg, page) {
    log("== " + page.name + " : " + page.pool.name);
    var pkg = parentPkg.Packages.AddNew(page.pool.name, "");
    mustUpdate(pkg, "package");
    parentPkg.Packages.Refresh();

    var dia = pkg.Diagrams.AddNew(page.pool.name, "BPMN2.0::Business Process");
    mustUpdate(dia, "diagram BPMN: pastikan MDG BPMN 2.0 aktif");
    pkg.Diagrams.Refresh();

    var map = {};
    var pool = mustUpdate(pkg.Elements.AddNew(page.pool.name, "BPMN2.0::Pool"), "pool");
    var vert = (page.orient == "vertical");
    var partitions = [], placed = [];
    partitions.push([place(dia, pool, page.pool, 100), pool.Name]);

    for (var i = 0; i < page.lanes.length; i++) {
        var L = page.lanes[i];
        var lane = mustUpdate(pool.Elements.AddNew(L.name, "BPMN2.0::Lane"), "lane " + L.name);
        map[L.key] = lane;
        partitions.push([place(dia, lane, L, 50), L.name]);
    }
    pool.Elements.Refresh();

    for (var j = 0; j < page.nodes.length; j++) {
        var N = page.nodes[j];
        var owner = map[N.lane];
        var el = mustUpdate(owner.Elements.AddNew(N.name, ELEMENT_TYPE[N.kind]), N.kind + " " + N.name);
        map[N.key] = el;
        placed.push([place(dia, el, N, 1), N, N.name]);
        log("  + " + N.kind + " : " + N.name);
    }

    for (var k = 0; k < page.flows.length; k++) {
        var F = page.flows[k];
        var src = map[F.src], tgt = map[F.tgt];
        var isSeq = (F.kind == "seq");
        var c = src.Connectors.AddNew(F.name, isSeq ? SEQ_BASE : DATA_BASE);
        c.SupplierID = tgt.ElementID;
        mustUpdate(c, "connector " + src.Name + " -> " + tgt.Name);
        c.StereotypeEx = isSeq ? SEQ_STEREO : DATA_STEREO;
        mustUpdate(c, "stereotype connector");
        src.Connectors.Refresh();
        var link = dia.DiagramLinks.AddNew("", "");
        link.ConnectorID = c.ConnectorID;
        link.Style = LINK_STYLE;
        mustUpdate(link, "diagram link");
    }

    // Orientasi diubah paling akhir, lalu posisi semua node disetel ulang,
    // supaya Sparx tidak sempat menggeser/mengubah ukuran elemen (kasus Start).
    if (vert) {
        for (var a = 0; a < partitions.length; a++) { setVertical(partitions[a][0], partitions[a][1]); }
    }
    for (var b = 0; b < placed.length; b++) { resetRect(placed[b][0], placed[b][1], placed[b][2]); }

    dia.DiagramObjects.Refresh();
    dia.DiagramLinks.Refresh();
    mustUpdate(dia, "diagram");
    return dia;
}

function main() {
    Repository.EnsureOutputVisible("Script");
    Repository.ClearOutput("Script");
    var target = Repository.GetTreeSelectedPackage();
    if (target == null) { log("Pilih package tujuan di Project Browser dulu."); return; }
    var last = null;
    for (var p = 0; p < PAGES.length; p++) { last = buildPage(target, PAGES[p]); }
    Repository.RefreshModelView(target.PackageID);
    if (last != null) { Repository.OpenDiagram(last.DiagramID); }
    log("Selesai.");
}

main();
"""


VSD_HELP = ("File .vsd (Visio versi lama) tidak didukung. Buka di Microsoft Visio, pilih "
            "File > Save As > Visio Drawing (*.vsdx), lalu upload file .vsdx-nya.")


def _png_drawio(data):
    """Ambil XML draw.io yang tertanam di PNG (File > Export > PNG, 'Include a copy')."""
    import struct
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype in (b"tEXt", b"zTXt", b"iTXt") and b"\x00" in body:
            keyword, rest = body.split(b"\x00", 1)
            if keyword != b"mxfile":
                continue
            if ctype == b"zTXt":
                rest = zlib.decompress(rest[1:])
            elif ctype == b"iTXt":
                flag = rest[0]
                rest = rest[2:].split(b"\x00", 2)[-1]
                if flag:
                    rest = zlib.decompress(rest)
            return urllib.parse.unquote(rest.decode("utf-8", "replace")).encode("utf-8")
        if ctype == b"IEND":
            break
    raise ValueError("PNG ini tidak berisi data draw.io. Ekspor ulang dari draw.io dengan "
                     "opsi 'Include a copy of my diagram', atau upload file .drawio-nya.")


def _svg_drawio(data):
    """Ambil XML draw.io dari atribut content di SVG (File > Export > SVG, editable)."""
    root = ET.fromstring(bytes(data))
    content = root.get("content")
    if not content:
        raise ValueError("SVG ini tidak berisi data draw.io. Ekspor ulang dari draw.io dengan "
                         "opsi 'Include a copy of my diagram', atau upload file .drawio-nya.")
    return content.encode("utf-8")


def tidy_keep_layout(page):
    """Mode posisi asli: ukuran event/gateway/data diseragamkan (tetap di titik tengah
    aslinya), lalu shape digeser supaya tidak menabrak header pool & lane."""
    orient = page.get("native_orient", "vertical")
    page["orient"] = orient
    for n in page["nodes"]:
        if n["kind"] == "task":
            continue
        w, h = SIZE[n["kind"]]
        cx, cy = (n["l"] + n["r"]) / 2, (n["t"] + n["b"]) / 2
        n.update(l=round(cx - w / 2), t=round(cy - h / 2), r=round(cx + w / 2), b=round(cy + h / 2))

    pool, lanes = page["pool"], page["lanes"]
    lane_of = {l["key"]: l for l in lanes}
    horizontal = orient == "horizontal"
    a, b = ("l", "r") if horizontal else ("t", "b")      # sumbu tempat header berada

    # lane harus mulai setelah header pool
    need_lane = max([pool[a] + POOL_HDR - l[a] for l in lanes] + [0])
    if need_lane:
        for l in lanes:
            l[a] += need_lane
            l[b] += need_lane
        for n in page["nodes"]:
            n[a] += need_lane
            n[b] += need_lane
        pool[b] += need_lane
    # shape harus mulai setelah header lane
    need_node = max([lane_of[n["lane"]][a] + LANE_HDR + 10 - n[a] for n in page["nodes"]] + [0])
    if need_node:
        for n in page["nodes"]:
            n[a] += need_node
            n[b] += need_node
        for l in lanes:
            l[b] += need_node
        pool[b] += need_node
    # lane & pool cukup besar menampung semua shape
    for l in lanes:
        members = [n for n in page["nodes"] if n["lane"] == l["key"]]
        if members:
            l[b] = max(l[b], max(n[b] for n in members) + 20)
    end = max(l[b] for l in lanes)
    for l in lanes:
        l[b] = end
    pool[b] = max(pool[b], end)
    return page


def detect_format(data):
    head = bytes(data[:8])
    if head.startswith(b"\x89PNG"):
        return "png"
    if b"<svg" in bytes(data[:2048]).lower():
        return "svg"
    if head.startswith(b"PK\x03\x04"):
        return "vsdx"
    if head.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
        return "vsd"
    return "drawio"


def _raw_pages_drawio(source):
    """[(nama, mxGraphModel)] untuk file draw.io (.drawio/.xml/.svg/.png)."""
    data = source if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    fmt = detect_format(data)
    if fmt == "vsd":
        raise ValueError(VSD_HELP)
    if fmt == "vsdx":
        raise ValueError("Mode 'salin apa adanya' baru mendukung file draw.io (.drawio, .xml, "
                         ".svg, .png). Untuk file .vsdx, pakai mode alur proses (BPMN).")
    if fmt == "png":
        data = _png_drawio(bytes(data))
    elif fmt == "svg":
        data = _svg_drawio(bytes(data))
    return load_pages(data)


def _raw_pages(source):
    """[(nama, fungsi -> data halaman)] sesuai format file."""
    data = source if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    fmt = detect_format(data)
    if fmt == "vsd":
        raise ValueError(VSD_HELP)
    if fmt == "png":
        data, fmt = _png_drawio(bytes(data)), "drawio"
    elif fmt == "svg":
        data, fmt = _svg_drawio(bytes(data)), "drawio"
    if fmt == "vsdx":
        from visio_reader import load_vsdx
        return [(name, fn) for name, fn in load_vsdx(bytes(data))]
    return [(name, (lambda n=name, m=model: convert_page(n, m))) for name, model in load_pages(data)]


def convert(source, orient="vertical", keep_layout=False, page_names=None,
            repository_profile=None, snapshot=None, element_decisions=None, relationship_decisions=None,
            execution_mode="VALIDATE_ONLY", execute_approved=False):
    """Konversi file (draw.io / .vsdx) -> (teks JScript, data halaman, catatan).
    source: bytes atau path. page_names: subset nama halaman (None = semua)."""
    pages, notes = [], []
    for name, build in _raw_pages(source):
        if page_names is not None and name not in page_names:
            continue
        try:
            pg = build()
        except ValueError as exc:
            notes.append(f"{name}: {exc}")
            continue
        if not pg["nodes"]:
            notes.append(f"{name}: tidak ada shape proses yang dikenali, halaman dilewati.")
            continue
        if keep_layout:
            pg = tidy_keep_layout(pg)
        else:
            pg = auto_layout(pg, orient)
        pages.append(pg)
    if not pages:
        raise ValueError("Tidak ada halaman yang bisa dikonversi. " + " ".join(notes))
    from import_plan import read_source, apply_layout, build_plan, generate_jscript
    document = read_source(source, mode='bpmn')
    if page_names is not None:
        document['pages'] = [p for p in document['pages'] if p['name'] in page_names]
    apply_layout(document, orient, keep_layout)
    plan = build_plan(document, repository_profile, snapshot, element_decisions, relationship_decisions,
                      execution_mode, execute_approved)
    return generate_jscript(plan), pages, notes


def list_pages(source):
    """[(nama halaman, judul)] untuk ditampilkan ke pengguna."""
    out = []
    for name, build in _raw_pages(source):
        try:
            pg = build()
            title = pg["pool"]["name"] or name
            if not pg["nodes"]:
                title += " (tanpa shape proses)"
        except ValueError:
            title = name + " (tidak bisa dibaca)"
        out.append((name, title))
    return out


def to_jscript(pages):
    raise ValueError('Gunakan convert(source, repository_profile=..., snapshot=...) agar seluruh identitas dan relasi melalui preflight. Scene legacy tidak memuat source identity yang cukup.')


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = "--keep-layout" in sys.argv
    orient = "horizontal" if "--horizontal" in sys.argv else "vertical"
    src = args[0] if len(args) > 0 else "input.drawio.xml"
    out = args[1] if len(args) > 1 else "drawio_to_sparx_output.js"
    js, data, notes = convert(src, orient, keep)
    for n in notes:
        print("Catatan:", n)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(js)
    for pg in data:
        print(f"{pg['name']}: {pg['pool']['name']} | {len(pg['lanes'])} lane, "
              f"{len(pg['nodes'])} node, {len(pg['flows'])} connector")
    print("Output:", out)
