// Bahasa: JScript. Pilih root package katalog di Project Browser, lalu Run.
// Salin output CSV (mulai baris GUID,Name,...) ke file UTF-8 .csv, lalu upload ke app.
// Script ini hanya membaca model dan menulis metadata ke tab Script Output.
function csvCell(value) { return '"' + String(value || "").replace(/"/g, '""') + '"'; }
function main() {
    var root = Repository.GetTreeSelectedPackage();
    if (root == null) { Session.Output("Pilih root package katalog dahulu."); return; }
    Repository.EnsureOutputVisible("Script");
    Repository.ClearOutput("Script");
    Session.Output("GUID,Name,Type,Stereotype,PackagePath,CataloguePackageGUID");
    var stack = [{pkg: root, path: root.Name}];
    while (stack.length) {
        var current = stack.pop(), pkg = current.pkg;
        for (var i = 0; i < pkg.Elements.Count; i++) {
            var el = pkg.Elements.GetAt(i);
            Session.Output([csvCell(el.ElementGUID), csvCell(el.Name), csvCell(el.Type),
                            csvCell(el.StereotypeEx || el.Stereotype), csvCell(current.path),
                            csvCell(root.PackageGUID)].join(","));
        }
        for (var j = pkg.Packages.Count - 1; j >= 0; j--) {
            var child = pkg.Packages.GetAt(j);
            stack.push({pkg: child, path: current.path + " / " + child.Name});
        }
    }
}
main();
