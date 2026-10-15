"""
generic_mode.py
Mode diagram umum: geometri draw.io dipertahankan, shape menjadi elemen model
Sparx EA, dan connector menghubungkan ID elemen hasil konversi.

Pemetaan default (dapat dipilih sebelum konversi):
  wadah (swimlane / kotak berisi shape lain) -> Boundary
  kotak biasa / bentuk catatan                -> Class (atau tipe pilihan pengguna)
  teks lepas                                 -> Note
  elips / lingkaran                           -> UseCase (tampil sebagai elips)
  belah ketupat                               -> Decision
  garis berpanah / tanpa panah                -> Dependency / Association
"""
import html
import json
import re

from drawio_to_sparx import (MARGIN, _raw_pages_drawio, _rect_dist, detect_format, f, parse_style)
from model_types import (EA_ELEMENT_TYPES, RELATION_TYPES, archimate, default_relation_type, infer_archimate)
from ea_catalogue import JS_CATALOGUE, normalise_catalogue

SNAP = 40
DEFAULT_ELEMENT_TYPES = {"container": "Boundary", "text": "Note", "note": "Class",
                         "box": "Class", "ellipse": "UseCase", "diamond": "Decision", "actor": "Actor", "activity": "Activity"}


def multiline(text):
    """Label HTML draw.io -> teks polos dengan baris baru dipertahankan."""
    t = html.unescape(text or "")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(div|p|li|h\d|tr)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in t.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()     # pertahankan 1 baris kosong pemisah


def _shape_kind(style):
    base, kv = parse_style(style)
    shape = kv.get("shape", "")
    key = base + " " + shape
    s = (style or "").lower()
    if base == "actor" or "actor" in shape or re.search(r"\bactor\b", kv.get("semantic", "")):
        return "actor"
    if "umlactivity" in shape.lower():
        return "activity"
    if base == "swimlane" or any(k in shape for k in ("swimlane", "pool", "lane")):
        return "container"
    if "edgelabel" in s:
        return "label"
    if base == "group":
        return "group"
    if base == "image" or shape == "image":
        return "image"
    if base in ("text", "label") or kv.get("text") == "1":
        return "text"
    if any(k in key for k in ("note", "annotation", "callout", "comment")):
        return "note"
    if any(k in key for k in ("rhombus", "decision", "diamond", "gateway")):
        return "diamond"
    if any(k in key for k in ("ellipse", "circle", "start_1", "start_2", "endstate",
                              "startstate", "bpmn.event")):
        return "ellipse"
    return "box"


def convert_generic_page(name, model):
    cells = {}
    for c in model.iter("mxCell"):
        if c.get("id"):
            cells[c.get("id")] = c
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
        absg[cid] = (0.0, 0.0, 0.0, 0.0)
        g = c.find("mxGeometry")
        px, py, _, _ = geom(c.get("parent"))
        if g is None or g.get("relative") == "1":
            r = (px, py, 0.0, 0.0)
        else:
            r = (px + f(g.get("x")), py + f(g.get("y")), f(g.get("width")), f(g.get("height")))
        absg[cid] = r
        return r

    kinds, labels, skipped = {}, {}, []
    for cid, c in cells.items():
        if c.get("vertex") != "1":
            continue
        k = _shape_kind(c.get("style"))
        if k == "label":
            labels[c.get("parent")] = multiline(c.get("value")).replace("\n", " ")
        elif k == "image":
            skipped.append({"master": "Gambar", "text": multiline(c.get("value"))[:80] or "(gambar)"})
        elif k != "group":
            kinds[cid] = k

    children = {}
    for cid, c in cells.items():
        children.setdefault(c.get("parent"), []).append(cid)

    # kotak yang punya anak / container=1 / melingkupi shape lain -> wadah
    for cid, k in list(kinds.items()):
        if k not in ("box", "note"):
            continue
        _, kv = parse_style(cells[cid].get("style"))
        x, y, w, h = geom(cid)
        inside = [o for o in kinds if o != cid and geom(o)[2] * geom(o)[3] * 2 < w * h and
                  x <= geom(o)[0] and y <= geom(o)[1] and
                  geom(o)[0] + geom(o)[2] <= x + w and geom(o)[1] + geom(o)[3] <= y + h]
        if kv.get("container") == "1" or any(x_ in kinds for x_ in children.get(cid, [])) or inside:
            kinds[cid] = "container"

    items = {}
    for cid, k in kinds.items():
        x, y, w, h = geom(cid)
        if w <= 0 or h <= 0:
            continue
        text = multiline(cells[cid].get("value"))
        if not text and k in ("text", "note"):
            continue
        items[cid] = {"key": cid, "kind": k, "text": text, "g": (x, y, w, h)}
    if not items:
        return {"name": name, "mode": "generic", "title": name, "items": [], "links": [],
                "skipped": skipped, "pool": {"name": name}, "nodes": [], "lanes": [], "flows": []}

    def to_item(cid):
        seen = set()
        while cid is not None and cid in cells and cid not in seen:
            if cid in items:
                return cid
            seen.add(cid)
            cid = cells[cid].get("parent")
        return None

    links, loose = [], 0
    for cid, c in cells.items():
        if c.get("edge") != "1":
            continue
        ends = {"source": to_item(c.get("source")), "target": to_item(c.get("target"))}
        g = c.find("mxGeometry")
        ox, oy, _, _ = geom(c.get("parent"))
        for end in ("source", "target"):
            if ends[end] or g is None:
                continue
            pt = g.find(f"mxPoint[@as='{end}Point']")
            if pt is None:
                continue
            p = (ox + f(pt.get("x")), oy + f(pt.get("y")))
            best = min(items, key=lambda k: (_rect_dist(p, items[k]["g"]),
                                             items[k]["g"][2] * items[k]["g"][3]))
            if _rect_dist(p, items[best]["g"]) <= SNAP:
                ends[end] = best
        src, tgt = ends["source"], ends["target"]
        if not src or not tgt:
            loose += 1
            continue
        _, kv = parse_style(c.get("style"))
        start_arrow = kv.get("startarrow", "none") not in ("none", "")
        end_arrow = kv.get("endarrow", "classic") not in ("none", "")
        if start_arrow and not end_arrow:
            src, tgt = tgt, src
        direction = "Bi-Directional" if start_arrow and end_arrow else "Source -> Destination" if start_arrow or end_arrow else "Unspecified"
        links.append({"key": cid, "src": src, "tgt": tgt, "directed": start_arrow or end_arrow,
                      "direction": direction,
                      "name": multiline(c.get("value")).replace("\n", " ") or labels.get(cid, "")})
    if loose:
        skipped.append({"master": "Garis tanpa ujung",
                        "text": f"{loose} garis tidak menempel ke shape mana pun"})

    # koordinat relatif ke pojok kiri atas semua shape
    x0 = min(it["g"][0] for it in items.values())
    y0 = min(it["g"][1] for it in items.values())
    out = []
    # wadah besar di belakang: urutkan dari yang terbesar
    order = sorted(items.values(), key=lambda it: -(it["g"][2] * it["g"][3]))
    for rank, it in enumerate(order):
        x, y, w, h = it["g"]
        l, t = round(x - x0 + MARGIN), round(y - y0 + MARGIN)
        out.append({"key": it["key"], "kind": it["kind"], "text": it["text"],
                    "source_style": cells[it["key"]].get("style", ""),
                    "context": [other["text"] for other in sorted(items.values(), key=lambda o: o["g"][2] * o["g"][3])
                                if other["kind"] == "container" and other["key"] != it["key"]
                                and other["g"][0] <= x and other["g"][1] <= y
                                and x + w <= other["g"][0] + other["g"][2]
                                and y + h <= other["g"][1] + other["g"][3]],
                    "l": l, "t": t, "r": l + round(w), "b": t + round(h),
                    "seq": (len(order) - rank) if it["kind"] == "container" else 1})

    return {"name": name, "mode": "generic", "title": name, "items": out, "links": links,
            "skipped": skipped,
            # kolom di bawah dipakai app untuk ringkasan
            "pool": {"name": name}, "nodes": [], "lanes": [], "flows": []}


def _raw_generic_pages(source):
    data = source if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    if detect_format(data) == "vsdx":
        from visio_reader import load_vsdx_generic
        return load_vsdx_generic(bytes(data))
    return _raw_pages_drawio(data)


def list_generic_pages(source):
    """Daftar halaman tanpa menerapkan heuristik proses BPMN."""
    return [(name, name) for name, _ in _raw_generic_pages(source)]


def load_generic_pages(source, page_names=None, default_type=None, element_types=None,
                       profile="uml", relation_types=None, catalogue=None):
    """Data halaman dengan tipe EA eksplisit; override: {halaman: {ID: tipe}}."""
    if profile not in ("uml", "archimate"):
        raise ValueError(f"Profil pemodelan tidak didukung: {profile}")
    default_type = default_type or ("Class" if profile == "uml" else archimate("ApplicationComponent"))
    if default_type not in EA_ELEMENT_TYPES:
        raise ValueError(f"Tipe elemen Sparx tidak didukung: {default_type}")
    element_types = element_types or {}
    relation_types = relation_types or {}
    catalogue = normalise_catalogue(catalogue)
    pages, notes = [], []
    for name, model in _raw_generic_pages(source):
        if page_names is not None and name not in page_names:
            continue
        pg = convert_generic_page(name, model)
        if not pg["items"]:
            notes.append(f"{name}: halaman kosong, dilewati.")
            continue
        overrides = element_types.get(name, {})
        for it in pg["items"]:
            default = default_type if it["kind"] in ("box", "note") else DEFAULT_ELEMENT_TYPES[it["kind"]]
            basis = "default" if it["kind"] in ("box", "note") else "jenis bentuk"
            if profile == "archimate" and it["kind"] not in ("container", "text"):
                default, basis = infer_archimate(it, default_type)
                if it["kind"] == "actor":
                    default, basis = archimate("BusinessActor"), "jenis bentuk"
                elif it["kind"] == "activity":
                    default, basis = archimate("BusinessProcess"), "jenis bentuk"
            it["ea_type"] = overrides.get(it["key"], default)
            it["mapping_basis"] = "pilihan pengguna" if it["key"] in overrides else basis
            if it["ea_type"] not in EA_ELEMENT_TYPES:
                raise ValueError(f"{name}: tipe elemen Sparx tidak didukung: {it['ea_type']}")
            it["catalogue_guid"] = catalogue["bindings"].get(name, {}).get(it["key"], "") if catalogue else ""
        by_key = {it["key"]: it for it in pg["items"]}
        for link in pg["links"]:
            src_type, tgt_type = by_key[link["src"]]["ea_type"], by_key[link["tgt"]]["ea_type"]
            default_relation = default_relation_type(src_type, tgt_type, link["directed"], profile)
            link["relation_type"] = relation_types.get(name, {}).get(link["key"], default_relation)
            if link["relation_type"] not in RELATION_TYPES:
                raise ValueError(f"{name}: tipe relasi tidak didukung: {link['relation_type']}")
            link["ea_type"], link["stereotype"] = RELATION_TYPES[link["relation_type"]]
        pg["profile"] = profile
        pages.append(pg)
    if not pages:
        raise ValueError("Tidak ada halaman yang bisa dikonversi. " + " ".join(notes))
    return pages, notes


def convert_generic(source, page_names=None, default_type=None, element_types=None,
                    profile="uml", relation_types=None, catalogue=None):
    """(JScript, halaman, catatan); perubahan tipe mempertahankan ID dan relasi."""
    catalogue = normalise_catalogue(catalogue)
    pages, notes = load_generic_pages(source, page_names, default_type, element_types, profile, relation_types, catalogue)
    script = JSCRIPT_GENERIC.replace("__CATALOGUE_RUNTIME__", JS_CATALOGUE)
    script = script.replace("__CATALOGUE__", json.dumps(catalogue, ensure_ascii=True))
    return script.replace("__DATA__", json.dumps(pages, indent=1, ensure_ascii=True)), pages, notes


JSCRIPT_GENERIC = r"""// Generated by generic_mode.py  --  Bahasa: JScript
// Mode: elemen model (non-BPMN). Posisi relatif, ukuran, teks, dan relasi dari draw.io.
// Cara pakai: pilih package tujuan di Project Browser, lalu Run script ini.

var LINK_STYLE      = "Mode=3;TREE=OS;";

var PAGES = __DATA__;
var CATALOGUE = __CATALOGUE__;
__CATALOGUE_RUNTIME__

function log(msg) { Session.Output(msg); }

function mustUpdate(obj, what) {
    if (!obj.Update()) { throw new Error("Gagal membuat " + what + ": " + obj.GetLastError()); }
    return obj;
}

function firstLine(text) {
    var s = String(text || "");
    var i = s.indexOf("\n");
    s = (i >= 0) ? s.substring(0, i) : s;
    return s.length > 60 ? s.substring(0, 57) + "..." : s;
}

function buildPage(parentPkg, page) {
    log("== " + page.name);
    var pkg = parentPkg.Packages.AddNew(page.title, "");
    mustUpdate(pkg, "package");
    parentPkg.Packages.Refresh();

    var dia = pkg.Diagrams.AddNew(page.title, "Custom");
    if (!dia.Update()) {
        dia = pkg.Diagrams.AddNew(page.title, "Logical");
        mustUpdate(dia, "diagram");
    }
    pkg.Diagrams.Refresh();

    var map = {}, placedElements = {}, placedLinks = {};
    for (var i = 0; i < page.items.length; i++) {
        var it = page.items[i];
        var type = it.ea_type;
        var resolved = resolveElement(pkg, page, it);
        var el = resolved.element, name = el.Name;
        if (resolved.created && (type == "Note" || it.text.indexOf("\n") >= 0)) {
            el.Notes = String(it.text).replace(/\n/g, "\r\n");
            mustUpdate(el, "teks " + name);
        }
        map[it.key] = el;
        if (placedElements[el.ElementID]) {
            log("  = referensi visual digabung untuk " + name);
            continue;
        }
        placedElements[el.ElementID] = true;

        var pos = "l=" + it.l + ";r=" + it.r + ";t=" + it.t + ";b=" + it.b + ";";
        var o = dia.DiagramObjects.AddNew(pos, "");
        o.ElementID = el.ElementID;
        o.Sequence = it.seq;
        mustUpdate(o, "posisi " + name);
        log("  + " + type + " : " + name);
    }
    pkg.Elements.Refresh();

    for (var k = 0; k < page.links.length; k++) {
        var L = page.links[k];
        var src = map[L.src], tgt = map[L.tgt];
        var c = resolveConnector(src, tgt, L);
        if (placedLinks[c.ConnectorID]) { continue; }
        placedLinks[c.ConnectorID] = true;
        var link = dia.DiagramLinks.AddNew("", "");
        link.ConnectorID = c.ConnectorID;
        link.Style = LINK_STYLE;
        mustUpdate(link, "diagram link");
    }

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
    preflightCatalogue();
    var last = null;
    for (var p = 0; p < PAGES.length; p++) { last = buildPage(target, PAGES[p]); }
    Repository.RefreshModelView(target.PackageID);
    if (last != null) { Repository.OpenDiagram(last.DiagramID); }
    log("Selesai.");
}

main();
"""
