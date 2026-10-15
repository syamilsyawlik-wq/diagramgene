"""Catalogue metadata and self-contained JScript for reusing canonical EA objects."""
import csv
import io
import re

from model_types import EA_ELEMENT_TYPES, archimate

GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
DEFAULT_MANAGED_TYPES = ("Actor", archimate("BusinessActor"), archimate("BusinessRole"))


def guid(value):
    value = str(value).strip()
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    match = GUID_RE.fullmatch(value)
    if not match:
        raise ValueError("GUID EA tidak valid; gunakan GUID package/elemen dari Sparx EA.")
    return "{" + match.group(0).upper() + "}"


def name_key(value):
    return " ".join(str(value).split()).lower()


def descendant_packages(snapshot, root):
    """Catalogue scope includes descendants, never a same-named sibling OPCO."""
    allowed = {root}
    while True:
        expanded = allowed | {p['guid'] for p in snapshot.get('packages', []) if p.get('parent_guid') in allowed}
        if expanded == allowed: return allowed
        allowed = expanded


def type_matches(entry, ea_type):
    if '::' in ea_type:
        return ea_type in [s.strip() for s in entry.get('stereotype', '').split(',')]
    return entry.get('base_type', entry.get('ea_type')) == ea_type and not entry.get('stereotype')


def scoped_candidates(entries, node, scope, opco=''):
    candidates = [e for e in entries if e.get('package_guid') in scope and type_matches(e, node['ea_type'])
                  and (not opco or e.get('opco') == opco)
                  and (not node.get('qualified_package_path') or e.get('package_path') == node['qualified_package_path'])]
    if node.get('business_id'):
        return [e for e in candidates if e.get('business_id') == node['business_id']], False
    exact = [e for e in candidates if name_key(e['name']) == name_key(node['name'])]
    if exact: return exact, False
    # Aliases are suggestions only; choosing their explicit GUID confirms identity.
    return [e for e in candidates if e.get('alias') and name_key(e['alias']) == name_key(node['name'])], True


def normalise_catalogue(options):
    if not options:
        return None
    managed = list(options.get("managed_types", DEFAULT_MANAGED_TYPES))
    if any(t not in EA_ELEMENT_TYPES or t in ("Note", "Boundary") for t in managed):
        raise ValueError("Tipe katalog harus merupakan entitas model yang didukung.")
    policy = options.get("on_missing", "error")
    if policy not in ("error", "create"):
        raise ValueError("Kebijakan objek katalog yang tidak ditemukan tidak valid.")
    bindings = {page: {key: guid(value) for key, value in entries.items() if value}
                for page, entries in options.get("bindings", {}).items()}
    return {"package_guid": guid(options.get("package_guid", "")), "managed_types": managed,
            "on_missing": policy, "bindings": bindings}


def read_catalogue_csv(raw):
    """Read the metadata-only CSV produced by export_ea_catalogue.js."""
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    if text.lstrip().startswith('{'):
        from catalogue_snapshot import read_snapshot
        return read_snapshot(text)
    try:
        dialect = csv.Sniffer().sniff(text[:10000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    required = {"GUID", "Name", "Type", "Stereotype", "PackagePath", "CataloguePackageGUID"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Format katalog tidak sesuai. Gunakan script Export katalog EA yang disediakan.")
    entries, roots, seen, skipped = [], set(), {}, 0
    for row in reader:
        if not any(row.values()):
            continue
        if None in row or any(row.get(field) is None for field in required):
            raise ValueError("Baris CSV katalog tidak lengkap atau memiliki jumlah kolom yang salah.")
        root = guid(row["CataloguePackageGUID"])
        roots.add(root)
        element_guid = guid(row["GUID"])
        stereotypes = [s.strip() for s in row["Stereotype"].split(",") if s.strip()]
        ea_type = next((t for t in EA_ELEMENT_TYPES if "::" in t and
                        any(s == t or s == t.split("::", 1)[1] for s in stereotypes)), row["Type"].strip())
        if ea_type not in EA_ELEMENT_TYPES or ea_type in ("Note", "Boundary"):
            skipped += 1
            continue
        entry = {"guid": element_guid, "name": row["Name"], "ea_type": ea_type,
                 "package_path": row["PackagePath"], "stereotype": row["Stereotype"]}
        if element_guid in seen and seen[element_guid] != entry:
            raise ValueError("Katalog memuat data berbeda untuk GUID yang sama.")
        if element_guid not in seen:
            entries.append(entry)
            seen[element_guid] = entry
    if len(roots) != 1:
        raise ValueError("CSV harus berisi satu root package katalog dan minimal satu baris data.")
    return {"package_guid": roots.pop(), "elements": entries, "skipped": skipped}


def catalogue_index(entries):
    index = {}
    for entry in entries:
        index.setdefault(name_key(entry["name"]), []).append(entry)
    return index


def catalogue_candidates(entries, name, ea_type):
    matches = entries.get(name_key(name), []) if isinstance(entries, dict) else [
        entry for entry in entries if name_key(entry["name"]) == name_key(name)]
    typed = [entry for entry in matches if entry["ea_type"] == ea_type]
    return typed or matches


JS_CATALOGUE = r'''
// All catalogue resolution happens before any package, element, or connector is created.
var catalogueRoot = null, catalogueByName = {}, catalogueByGuid = {};
var plannedElements = {}, canonicalElements = {};

function normalName(value) {
    return String(value || "").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "").toLowerCase();
}
function normalGuid(value) { return String(value || "").toUpperCase(); }
function hasStereotype(element, qualified) {
    var values = String(element.StereotypeEx || element.Stereotype || "").split(",");
    for (var i = 0; i < values.length; i++) {
        var value = values[i].replace(/^\s+|\s+$/g, "");
        if (value == qualified || value == qualified.split("::").pop()) { return true; }
    }
    return false;
}
function matchesType(element, type) {
    if (type.indexOf("::") >= 0) { return hasStereotype(element, type); }
    if (String(element.Type) != type) { return false; }
    return String(element.StereotypeEx || element.Stereotype || "").indexOf("ArchiMate_") < 0;
}
function isManaged(type) {
    if (!CATALOGUE) { return false; }
    for (var i = 0; i < CATALOGUE.managed_types.length; i++) {
        if (CATALOGUE.managed_types[i] == type) { return true; }
    }
    return false;
}
function canonicalKey(item) { return item.ea_type + "|" + normalName(item.text); }
function sourceKey(page, item) { return "$" + encodeURIComponent(page.name) + "|" + encodeURIComponent(item.key); }

function preflightCatalogue() {
    if (!CATALOGUE) { return; }
    catalogueRoot = Repository.GetPackageByGuid(CATALOGUE.package_guid);
    if (catalogueRoot == null) { throw new Error("Package katalog tidak ditemukan: " + CATALOGUE.package_guid); }
    var stack = [catalogueRoot];
    while (stack.length) {
        var pkg = stack.pop();
        pkg.Elements.Refresh();
        for (var i = 0; i < pkg.Elements.Count; i++) {
            var element = pkg.Elements.GetAt(i);
            var name = "$" + normalName(element.Name);
            if (!catalogueByName[name]) { catalogueByName[name] = []; }
            catalogueByName[name].push(element);
            catalogueByGuid[normalGuid(element.ElementGUID)] = element;
        }
        pkg.Packages.Refresh();
        for (var j = 0; j < pkg.Packages.Count; j++) { stack.push(pkg.Packages.GetAt(j)); }
    }
    for (var p = 0; p < PAGES.length; p++) {
        var page = PAGES[p];
        for (var k = 0; k < page.items.length; k++) {
            var item = page.items[k], resolved = null;
            var bound = item.catalogue_guid;
            if (bound) {
                resolved = catalogueByGuid[normalGuid(bound)];
                if (!resolved) { throw new Error(page.name + ": GUID tidak ditemukan di package katalog: " + bound); }
                if (!matchesType(resolved, item.ea_type)) {
                    throw new Error(page.name + ": tipe objek katalog berbeda untuk " + item.text + ". Perbarui pemetaan tipe.");
                }
            } else if (isManaged(item.ea_type)) {
                var candidates = [];
                var named = catalogueByName["$" + normalName(item.text)] || [];
                for (var n = 0; n < named.length; n++) {
                    var candidate = named[n];
                    if (matchesType(candidate, item.ea_type)) {
                        candidates.push(candidate);
                    }
                }
                if (candidates.length > 1) {
                    throw new Error(page.name + ": nama katalog ambigu: " + item.text + ". Pilih GUID objek yang benar sebelum impor.");
                }
                if (candidates.length == 1) { resolved = candidates[0]; }
                if (!resolved && CATALOGUE.on_missing == "error") {
                    throw new Error(page.name + ": objek katalog belum ada: " + item.text + " (" + item.ea_type + "). Impor dibatalkan.");
                }
                if (!resolved && !normalName(item.text)) { throw new Error("Nama entitas katalog tidak boleh kosong."); }
            }
            if (resolved) {
                plannedElements[sourceKey(page, item)] = resolved;
            }
        }
    }
}

function resolveElement(pkg, page, item) {
    var existing = plannedElements[sourceKey(page, item)];
    if (existing) {
        log("  = katalog " + existing.Name + " " + existing.ElementGUID);
        return { element: existing, created: false };
    }
    var managed = isManaged(item.ea_type), key = canonicalKey(item);
    if (managed && canonicalElements[key]) { return { element: canonicalElements[key], created: false }; }
    var owner = managed ? catalogueRoot : pkg;
    var name = item.ea_type == "Note" ? firstLine(item.text) : String(item.text || "").replace(/\n/g, " ");
    var element = owner.Elements.AddNew(name, item.ea_type);
    mustUpdate(element, "elemen " + name);
    if (managed) {
        canonicalElements[key] = element;
        owner.Elements.Refresh();
    }
    return { element: element, created: true };
}

function sameConnector(candidate, src, tgt, link) {
    if (candidate.ClientID != src.ElementID || candidate.SupplierID != tgt.ElementID ||
        String(candidate.Name || "") != String(link.name || "") ||
        String(candidate.Type) != link.ea_type || String(candidate.Direction) != link.direction) { return false; }
    if (link.stereotype) { return hasStereotype(candidate, link.stereotype); }
    return !String(candidate.StereotypeEx || candidate.Stereotype || "");
}
function resolveConnector(src, tgt, link) {
    src.Connectors.Refresh();
    for (var i = 0; i < src.Connectors.Count; i++) {
        var candidate = src.Connectors.GetAt(i);
        if (sameConnector(candidate, src, tgt, link)) { return candidate; }
    }
    var connector = src.Connectors.AddNew(link.name, link.ea_type);
    connector.SupplierID = tgt.ElementID;
    connector.Direction = link.direction;
    if (link.stereotype) { connector.StereotypeEx = link.stereotype; }
    mustUpdate(connector, "connector " + src.Name + " -> " + tgt.Name);
    src.Connectors.Refresh();
    return connector;
}
'''
