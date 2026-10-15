"""
trm_mode.py
Mode "Portofolio aplikasi (CSV) -> TRM": membaca CSV portofolio aplikasi dan menghasilkan
script JScript yang membangun package TRM (Technology Reference Model) di Sparx EA:

  <root>
    Applications      : 1 Component <<Application>> per baris CSV, kolom -> tagged value
    ODA Mapping       : 1 package + diagram per ODA Domain (Boundary <<ODA Domain>>),
                        semua ODA Component referensi + aplikasi yang memetakannya
                        (relasi Realisation), tag Jumlah/Daftar/Breakdown/Redundant
    Technology Stack  : kategori > teknologi (Package <<subkategori>>), relasi Dependency
                        dari aplikasi, tag Jumlah/Breakdown/Daftar, diagram berisi Model View
    + halaman indeks berisi NavigationCell ke tiap diagram

Aturan diturunkan dari model TRM yang sudah ada (dump package Sparx), dengan satu perbaikan:
query Model View memfilter berdasarkan GUID package teknologi, bukan nama, sehingga teknologi
bernama sama di kategori berbeda (mis. Grafana) tidak lagi menghasilkan baris ganda.
"""
import csv
import io
import json
import os
import re
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ODA_REFERENCE = json.load(open(os.path.join(HERE, "oda_reference.json"), encoding="utf-8"))

# kolom teknologi tanpa pola "Kategori - Subkategori" (kategori = subkategori = nama kolom)
SINGLE_TECH_COLUMNS = ["Operating System", "Jenis Akses", "Service Device", "Tipe Hosting",
                       "Public Cloud Provider"]
COL_NAME, COL_DESC = "Nama Aplikasi", "Deskripsi"
COL_DOMAIN, COL_COMP = "ODA Domain", "ODA Component"
COL_KRIT, COL_STATUS = "Kritikalitas", "Status"
EMPTY_VALUES = {"", "-", "–", "n/a", "na", "null", "none"}
SPLIT_RE = re.compile(r"\s*,\s*|\s+\+\s+")      # "PHP, Flutter" / "Prometheus + Grafana"

PKG_NOTES = {
    "root": "Model TRM hasil generate dari CSV portofolio aplikasi. Applications = semua aplikasi + "
            "detail di Tagged Values (termasuk 'Tech Stack (Ringkasan)' & 'Status' untuk dipakai sebagai "
            "kolom Model View). Technology Stack = elemen teknologi per kategori, tiap item ada Tagged "
            "Value 'Jumlah Aplikasi Terdampak' & 'Breakdown Kritikalitas' untuk risk/impact analysis. "
            "ODA Mapping = 1 diagram per ODA Domain untuk analisis redundansi. Cek tab Script Output "
            "setelah generate untuk daftar redundansi & teknologi paling banyak dipakai.",
    "apps": "Semua elemen Aplikasi. Buka Properties tiap aplikasi (double-click) > tab Tagged Values "
            "untuk detail lengkap (OpCo, ODA, status, kritikalitas, seluruh tech stack, pain point, "
            "rekomendasi TIME Gartner, dsb).",
    "oda": "ANALISIS REDUNDANSI. 1 package + 1 diagram per ODA Domain, isinya semua ODA Component di "
           "domain itu + aplikasi yang memetakannya. Kalau 1 ODA Component dipetakan >= 2 aplikasi -> "
           "kandidat redundan, ditandai Tagged Value 'Redundant = YA' di elemen component-nya.",
    "tech": "Technology Stack > <Kategori> > <Nama Teknologi>. Tiap item teknologi dibuat sebagai PACKAGE "
            "dengan stereotype subkategori. Tagged Value 'Jumlah Aplikasi Terdampak', 'Breakdown "
            "Kritikalitas', 'Daftar Aplikasi' ada di tiap item. Diagram tiap kategori berisi Model View "
            "daftar aplikasi pengguna teknologi tersebut.",
}


# --------------------------------------------------------------------------- CSV
def _val(v):
    """Nilai kosong / '-' dianggap tidak ada (dipakai untuk kolom teknologi & kunci)."""
    v = (v or "").strip()
    return "" if v.lower() in EMPTY_VALUES else v


def _raw(v):
    """Nilai apa adanya; hanya string kosong yang dianggap tidak ada (kolom non-teknologi)."""
    return (v or "").strip()


def read_csv(data):
    if isinstance(data, (bytes, bytearray)):
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = bytes(data).decode(enc)
                break
            except UnicodeDecodeError:
                continue
    else:
        text = data
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("File CSV kosong.")
    header = [h.strip().lstrip("\ufeff") for h in rows[0]]
    if COL_NAME not in header:
        raise ValueError(f"Kolom '{COL_NAME}' tidak ditemukan. Kolom yang ada: " + ", ".join(header[:12]) + " ...")
    records = []
    for r in rows[1:]:
        rec = OrderedDict()
        for i, h in enumerate(header):
            if h:
                rec[h] = r[i] if i < len(r) else ""
        if _val(rec.get(COL_NAME)):
            records.append(rec)
    if not records:
        raise ValueError("Tidak ada baris aplikasi (kolom Nama Aplikasi kosong semua).")
    return header, records, delim


def tech_columns(header):
    cols = []
    for h in header:
        if " - " in h:
            cat, sub = h.split(" - ", 1)
            cols.append((h, cat.strip(), sub.strip()))
        elif h in SINGLE_TECH_COLUMNS:
            cols.append((h, h, h))
    return cols


def _breakdown(apps):
    """'Top Critical: 12, Supporting: 11, (kosong): 2' -- urutan sesuai kemunculan pertama."""
    counts = OrderedDict()
    for a in apps:
        k = a["krit"] or "(kosong)"
        counts[k] = counts.get(k, 0) + 1
    order = [k for k in counts if k != "(kosong)"] + (["(kosong)"] if "(kosong)" in counts else [])
    return ", ".join(f"{k}: {counts[k]}" for k in order)


def _natkey(name):
    m = re.match(r"\s*([A-Za-z]+)(\d+)", name)
    return (m.group(1).upper(), int(m.group(2)), name) if m else (name.upper(), 0, name)


# --------------------------------------------------------------------------- model
def build_model(data, root_name="TRM - Technology Reference Model"):
    header, records, delim = read_csv(data)
    tcols = tech_columns(header)
    warnings = []

    # ---- aplikasi
    apps, seen = [], {}
    source_names = {_val(r.get(COL_NAME)) for r in records}
    used_names = set()
    for i, r in enumerate(records):
        name = _val(r.get(COL_NAME))
        if name in seen:
            seen[name] += 1
            while f"{name} #{seen[name]}" in source_names or f"{name} #{seen[name]}" in used_names:
                seen[name] += 1
            warnings.append(f"Nama aplikasi ganda: '{name}' (baris {i + 2}), diberi akhiran #{seen[name]}.")
            name = f"{name} #{seen[name]}"
        else:
            seen[name] = 1
        used_names.add(name)
        tech_set = {h for h, _, _ in tcols}
        tags = []
        for h in header:
            if h in (COL_NAME, COL_DESC):
                continue
            v = _val(r.get(h)) if h in tech_set else _raw(r.get(h))
            if v:
                tags.append((h, v))
        ring = ", ".join(_val(r.get(h)) for h, _, _ in tcols if _val(r.get(h)))
        if ring:
            tags.append(("Tech Stack (Ringkasan)", ring))
        apps.append({"key": f"a{i}", "name": name, "notes": _val(r.get(COL_DESC)), "tags": tags,
                     "krit": _val(r.get(COL_KRIT)), "row": r})

    # ---- ODA: referensi + yang muncul di CSV
    domains = OrderedDict()
    for d in ODA_REFERENCE:
        domains[d["name"]] = {"name": d["name"], "notes": d["notes"],
                              "components": OrderedDict((c["name"], {"name": c["name"], "notes": c["notes"],
                                                                     "apps": []}) for c in d["components"])}

    def find_domain(text):
        if not text:
            return None
        for n in domains:
            if n.lower() == text.lower():
                return n
        m = re.match(r"\s*([A-Za-z])\s*\.", text)
        if m:
            for n in domains:
                if n[:2].upper() == m.group(1).upper() + ".":
                    return n
        domains[text] = {"name": text, "notes": "", "components": OrderedDict()}
        warnings.append(f"ODA Domain baru (tidak ada di referensi): '{text}'.")
        return text

    def find_comp(dom, text):
        comps = domains[dom]["components"]
        for n in comps:
            if n.lower() == text.lower():
                return n
        m = re.match(r"\s*([A-Za-z]+\d+)\s*\.", text)
        if m:
            for n in comps:
                if n.split(".")[0].upper() == m.group(1).upper():
                    return n
        comps[text] = {"name": text, "notes": "", "apps": []}
        warnings.append(f"ODA Component baru (tidak ada di referensi): '{text}' di domain '{dom}'.")
        return text

    mapped_apps = set()
    for a in apps:
        dtext, ctext = _val(a["row"].get(COL_DOMAIN)), _val(a["row"].get(COL_COMP))
        if not ctext:
            continue
        dom = find_domain(dtext)
        if dom is None:                      # domain kosong: tebak dari kode komponen (D25 -> D.)
            m = re.match(r"\s*([A-Za-z])\d+", ctext)
            dom = find_domain(m.group(1) + ".") if m else None
            if dom is None:
                warnings.append(f"'{a['name']}': ODA Component '{ctext}' tanpa domain, dilewati.")
                continue
        comp = find_comp(dom, ctext)
        domains[dom]["components"][comp]["apps"].append(a)
        mapped_apps.add(a["key"])

    oda_out = []
    for d in domains.values():
        comps = sorted(d["components"].values(), key=lambda c: _natkey(c["name"]))
        out_comps = []
        for c in comps:
            n = len(c["apps"])
            tags = []
            if n:
                tags += [("Breakdown Kritikalitas", _breakdown(c["apps"])),
                         ("Daftar Aplikasi", ", ".join(x["name"] for x in c["apps"]))]
            tags += [("Jumlah Aplikasi Terpetakan", str(n)),
                     ("Redundant", f"YA - {n} aplikasi" if n >= 2 else "Tidak")]
            out_comps.append({"name": c["name"], "notes": c["notes"], "tags": tags,
                              "apps": [x["key"] for x in c["apps"]]})
        layout = _oda_layout(out_comps)
        oda_out.append({"name": d["name"], "notes": d["notes"], "components": out_comps, "layout": layout,
                        "n_apps": sum(len(c["apps"]) for c in out_comps)})

    # ---- Technology Stack
    cats = OrderedDict()
    for h, cat, sub in tcols:
        for a in apps:
            v = _val(a["row"].get(h))
            if not v:
                continue
            for item in [x.strip() for x in SPLIT_RE.split(v) if _val(x)]:
                c = cats.setdefault(cat, OrderedDict())
                it = c.setdefault((sub, item), {"name": item, "stereo": sub, "apps": []})
                if a not in it["apps"]:
                    it["apps"].append(a)
    tech_out = []
    for cat, items in cats.items():
        lst = []
        for it in sorted(items.values(), key=lambda x: (x["stereo"].lower(), x["name"].lower())):
            lst.append({"name": it["name"], "stereo": it["stereo"],
                        "label": f"[{it['stereo']}] {it['name']}",
                        "tags": [("Breakdown Kritikalitas", _breakdown(it["apps"])),
                                 ("Daftar Aplikasi", ", ".join(x["name"] for x in it["apps"])),
                                 ("Jumlah Aplikasi Terdampak", str(len(it["apps"])))],
                        "apps": [x["key"] for x in it["apps"]]})
        tech_out.append({"name": cat, "items": lst, "layout": _tech_layout(lst)})

    model = {
        "root": root_name, "notes": PKG_NOTES,
        "apps": [{"key": a["key"], "name": a["name"], "notes": a["notes"], "tags": a["tags"]} for a in apps],
        "domains": oda_out, "tech": tech_out,
        "index_oda": _grid(len(oda_out), 4), "index_tech": _grid(len(tech_out), 5),
    }
    stats = {"delimiter": delim, "n_apps": len(apps), "n_domains": len(oda_out),
             "n_components": sum(len(d["components"]) for d in oda_out),
             "n_realisation": sum(len(c["apps"]) for d in oda_out for c in d["components"]),
             "n_tech": sum(len(c["items"]) for c in tech_out),
             "n_dependency": sum(len(i["apps"]) for c in tech_out for i in c["items"]),
             "unmapped_apps": [a["name"] for a in apps if a["key"] not in mapped_apps]}
    return model, stats, warnings


# --------------------------------------------------------------------------- layout
def _rect(l, t, w, h):
    return {"l": int(l), "t": int(t), "r": int(l + w), "b": int(t + h)}


def _oda_layout(comps):
    """Komponen yang dipetakan di kolom 1 dengan aplikasinya di kolom 2; sisanya di grid kanan."""
    BL, BT, TITLE = 28, 12, 35
    CW, AW, H, STEP, GAP = 260, 280, 50, 70, 20
    X1, X2 = BL + 16, BL + 396
    y = BT + TITLE
    pos_c, pos_a = {}, []
    mapped = [c for c in comps if c["apps"]]
    free = [c for c in comps if not c["apps"]]
    for c in mapped:
        k = len(c["apps"])
        for j, ak in enumerate(c["apps"]):
            pos_a.append({"app": ak, "comp": c["name"], **_rect(X2, y + j * STEP, AW, H)})
        mid = y + (k - 1) * STEP / 2
        pos_c[c["name"]] = _rect(X1, mid, CW, H)
        y += k * STEP + GAP
    bottom = y
    if free:
        per_col = max(4, min(10, len(free) if not mapped else max(4, (y - BT - TITLE) // STEP)))
        x0 = (X2 + AW + 60) if mapped else X1
        for i, c in enumerate(free):
            col, row = divmod(i, per_col)
            r = _rect(x0 + col * (CW + 40), BT + TITLE + row * STEP, CW, H)
            pos_c[c["name"]] = r
            bottom = max(bottom, r["b"] + GAP)
    right = max([r["r"] for r in pos_c.values()] + [a["r"] for a in pos_a] + [X1 + CW]) + 22
    return {"boundary": {"l": BL, "t": BT, "r": right, "b": max(bottom, BT + TITLE + STEP) + 5},
            "components": pos_c, "apps": pos_a}


def _tech_layout(items):
    """Model View per teknologi; satu baris per subkategori, digabung selama <= 5 per baris."""
    W, GAPX, GAPY, X0, Y0 = 370, 30, 35, 20, 20
    groups = OrderedDict()
    for i, it in enumerate(items):
        groups.setdefault(it["stereo"], []).append(i)
    rows, cur = [], []
    for g in groups.values():
        if cur and len(cur) + len(g) > 5:
            rows.append(cur)
            cur = []
        cur += g
        while len(cur) > 5:
            rows.append(cur[:5])
            cur = cur[5:]
    if cur:
        rows.append(cur)
    out, y = {}, Y0
    for row in rows:
        hmax = 0
        for j, i in enumerate(row):
            h = max(260, 60 + 36 * len(items[i]["apps"]))
            out[i] = _rect(X0 + j * (W + GAPX), y, W, h)
            hmax = max(hmax, h)
        y += hmax + GAPY
    return [out[i] for i in range(len(items))]


def _grid(n, per_row):
    W, H, SX, SY, X0, Y0 = 170, 115, 210, 162, 60, 33
    return [_rect(X0 + (i % per_row) * SX, Y0 + (i // per_row) * SY, W, H) for i in range(n)]


# --------------------------------------------------------------------------- JScript
def convert_trm(data, root_name="TRM - Technology Reference Model"):
    model, stats, warnings = build_model(data, root_name)
    js = JSCRIPT_TRM.replace("__DATA__", json.dumps(model, indent=1, ensure_ascii=True))
    return js, model, stats, warnings


JSCRIPT_TRM = r"""// Generated by trm_mode.py  --  Bahasa: JScript
// Membangun package TRM (Applications, ODA Mapping, Technology Stack) dari CSV portofolio aplikasi.
// Cara pakai: pilih package tujuan di Project Browser, lalu Run. Package TRM dibuat di dalamnya.

var DATA = __DATA__;

function log(msg) { Session.Output(msg); }
function mustUpdate(obj, what) {
    if (!obj.Update()) { throw new Error("Gagal membuat " + what + ": " + obj.GetLastError()); }
    return obj;
}
function addTag(el, name, value) {
    var tv = el.TaggedValues.AddNew(name, "");
    value = String(value);
    if (value.length > 250) { tv.Value = "<memo>"; tv.Notes = value; } else { tv.Value = value; }
    mustUpdate(tv, "tagged value " + name);
}
function addTags(el, tags) {
    for (var i = 0; i < tags.length; i++) { addTag(el, tags[i][0], tags[i][1]); }
    el.TaggedValues.Refresh();
}
function newPackage(parent, name, notes) {
    var p = parent.Packages.AddNew(name, "");
    if (notes) { p.Notes = notes; }
    mustUpdate(p, "package " + name);
    parent.Packages.Refresh();
    return p;
}
function newElement(pkg, name, type, stereo, notes) {
    var el = pkg.Elements.AddNew(name, type);
    mustUpdate(el, type + " " + name);
    if (stereo) { el.StereotypeEx = stereo; }
    if (notes) { el.Notes = notes; }
    mustUpdate(el, type + " " + name);
    return el;
}
function newDiagram(pkg, name, type) {
    var d = pkg.Diagrams.AddNew(name, type);
    mustUpdate(d, "diagram " + name);
    pkg.Diagrams.Refresh();
    return d;
}
function place(dia, elementID, g, seq, style) {
    var o = dia.DiagramObjects.AddNew("l=" + g.l + ";r=" + g.r + ";t=" + g.t + ";b=" + g.b + ";", "");
    o.ElementID = elementID;
    o.Sequence = seq;
    mustUpdate(o, "posisi diagram");
    if (style) { o.Style = style; mustUpdate(o, "style diagram"); }
    return o;
}
function connect(src, tgtID, type) {
    var c = src.Connectors.AddNew("", type);
    c.SupplierID = tgtID;
    mustUpdate(c, type + " dari " + src.Name);
    return c;
}
function xmlEsc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;").replace(/\r?\n/g, "&#xA;");
}
function setViewProperties(el, sql) {
    var xml = "<modelview>\r\n <source customSQL=\"" + xmlEsc(sql) + "\"/>\r\n</modelview>";
    var tv = null;
    el.TaggedValues.Refresh();
    for (var i = 0; i < el.TaggedValues.Count; i++) {
        if (el.TaggedValues.GetAt(i).Name == "ViewProperties") { tv = el.TaggedValues.GetAt(i); }
    }
    if (tv == null) { tv = el.TaggedValues.AddNew("ViewProperties", ""); }
    tv.Value = "<memo>";
    tv.Notes = xml;
    mustUpdate(tv, "ViewProperties");
}
function navCell(pkg, dia, label, targetDiagramID, g, seq) {
    var el = newElement(pkg, "", "Text", "NavigationCell", "");
    el.Alias = label;
    el.Subtype = 82;   // NType 82 = Navigation Cell asli; tanpa ini EA bisa merender sbg ikon hyperlink kecil
    mustUpdate(el, "NavigationCell " + label);
    try {
        Repository.Execute("UPDATE t_object SET PDATA1 = '" + targetDiagramID + "' WHERE Object_ID = " + el.ElementID);
    } catch (e) {
        log("  ! Link NavigationCell '" + label + "' gagal diset otomatis; set manual lewat klik kanan > Navigate.");
    }
    place(dia, el.ElementID, g, seq, "font=Calibri;fontsz=140;");
}

function main() {
    Repository.EnsureOutputVisible("Script");
    Repository.ClearOutput("Script");
    var target = Repository.GetTreeSelectedPackage();
    if (target == null) { log("Pilih package tujuan di Project Browser dulu."); return; }

    var root = newPackage(target, DATA.root, DATA.notes.root);
    log("== " + DATA.root);

    // ---------------- Applications
    var appPkg = newPackage(root, "Applications", DATA.notes.apps);
    var apps = {};
    for (var i = 0; i < DATA.apps.length; i++) {
        var a = DATA.apps[i];
        var el = newElement(appPkg, a.name, "Component", "Application", a.notes);
        addTags(el, a.tags);
        apps[a.key] = el;
    }
    appPkg.Elements.Refresh();
    log("Applications: " + DATA.apps.length + " aplikasi");

    // ---------------- ODA Mapping
    var odaPkg = newPackage(root, "ODA Mapping", DATA.notes.oda);
    var odaDiagrams = [];
    var redundant = [];
    for (var d = 0; d < DATA.domains.length; d++) {
        var dom = DATA.domains[d];
        var dp = newPackage(odaPkg, dom.name, dom.notes);
        var dia = newDiagram(dp, dom.name, "Component");
        var total = dom.components.length + dom.layout.apps.length + 1;
        var seq = total;
        var bnd = newElement(dp, dom.name, "Boundary", "ODA Domain", "");
        place(dia, bnd.ElementID, dom.layout.boundary, seq--, "");
        var comps = {};
        for (var c = 0; c < dom.components.length; c++) {
            var cc = dom.components[c];
            var ce = newElement(dp, cc.name, "Component", "ODA Component", cc.notes);
            addTags(ce, cc.tags);
            comps[cc.name] = ce;
            place(dia, ce.ElementID, dom.layout.components[cc.name], seq--, "");
            for (var k = 0; k < cc.apps.length; k++) { connect(apps[cc.apps[k]], ce.ElementID, "Realisation"); }
            if (cc.apps.length >= 2) { redundant.push(cc.name + " (" + cc.apps.length + " aplikasi)"); }
        }
        for (var p = 0; p < dom.layout.apps.length; p++) {
            var pa = dom.layout.apps[p];
            place(dia, apps[pa.app].ElementID, pa, seq--, "");
        }
        dp.Elements.Refresh();
        mustUpdate(dia, "diagram " + dom.name);
        odaDiagrams.push(dia);
        log("ODA " + dom.name + ": " + dom.components.length + " component, " + dom.n_apps + " pemetaan aplikasi");
    }
    var odaIdx = newDiagram(odaPkg, "ODA Mapping", "Use Case");
    for (var n = 0; n < odaDiagrams.length; n++) {
        navCell(odaPkg, odaIdx, DATA.domains[n].name, odaDiagrams[n].DiagramID, DATA.index_oda[n], odaDiagrams.length - n);
    }
    mustUpdate(odaIdx, "diagram ODA Mapping");

    // ---------------- Technology Stack
    var techPkg = newPackage(root, "Technology Stack", DATA.notes.tech);
    var techDiagrams = [];
    var usage = [];
    for (var t = 0; t < DATA.tech.length; t++) {
        var cat = DATA.tech[t];
        var cp = newPackage(techPkg, cat.name, "");
        var cdia = newDiagram(cp, cat.name, "Use Case");
        for (var j = 0; j < cat.items.length; j++) {
            var it = cat.items[j];
            var ip = newPackage(cp, it.name, "");
            ip.Element.StereotypeEx = it.stereo;
            mustUpdate(ip.Element, "stereotype " + it.name);
            addTags(ip.Element, it.tags);
            for (var u = 0; u < it.apps.length; u++) { connect(apps[it.apps[u]], ip.Element.ElementID, "Dependency"); }

            var sql = "SELECT\n    ao.ea_guid AS CLASSGUID,\n    'Object' AS CLASSTYPE,\n" +
                      "    ao.Name AS 'Nama Aplikasi',\n    tv_status.Value AS 'Status',\n" +
                      "    tv_krit.Value AS 'Kritikalitas'\n" +
                      "FROM t_object techo\n" +
                      "INNER JOIN t_connector c ON c.End_Object_ID = techo.Object_ID AND c.Connector_Type = 'Dependency'\n" +
                      "INNER JOIN t_object ao ON ao.Object_ID = c.Start_Object_ID\n" +
                      "LEFT JOIN t_objectproperties tv_status ON tv_status.Object_ID = ao.Object_ID AND tv_status.Property = 'Status'\n" +
                      "LEFT JOIN t_objectproperties tv_krit ON tv_krit.Object_ID = ao.Object_ID AND tv_krit.Property = 'Kritikalitas'\n" +
                      "WHERE techo.ea_guid = '" + ip.PackageGUID + "'\n" +
                      "ORDER BY ao.Name";
            var mv = newElement(cp, it.label, "Class", "EAUML::ModelView", "");
            setViewProperties(mv, sql);
            place(cdia, mv.ElementID, cat.layout[j], cat.items.length - j, "Dockable=standard;HideIcon=0;");
            usage.push([it.apps.length, it.label]);
        }
        cp.Elements.Refresh();
        mustUpdate(cdia, "diagram " + cat.name);
        techDiagrams.push(cdia);
        log("Technology Stack " + cat.name + ": " + cat.items.length + " teknologi");
    }
    var techIdx = newDiagram(techPkg, "Technology Stack", "Use Case");
    for (var m = 0; m < techDiagrams.length; m++) {
        navCell(techPkg, techIdx, DATA.tech[m].name, techDiagrams[m].DiagramID, DATA.index_tech[m], techDiagrams.length - m);
    }
    mustUpdate(techIdx, "diagram Technology Stack");

    // ---------------- ringkasan
    log("");
    log("KANDIDAT REDUNDANSI (1 ODA Component dipetakan >= 2 aplikasi): " + redundant.length);
    for (var r = 0; r < redundant.length; r++) { log("  - " + redundant[r]); }
    usage.sort(function (x, y) { return y[0] - x[0]; });
    log("");
    log("TEKNOLOGI PALING BANYAK DIPAKAI:");
    for (var q = 0; q < usage.length && q < 10; q++) { log("  " + usage[q][0] + " aplikasi - " + usage[q][1]); }

    Repository.RefreshModelView(target.PackageID);
    Repository.OpenDiagram(odaIdx.DiagramID);
    log("");
    log("Selesai.");
}

main();
"""
