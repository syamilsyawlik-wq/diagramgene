// In-memory EA Automation API contract tests; not a substitute for real EA validation.
const fs = require('fs');
const vm = require('vm');
let script = fs.readFileSync(0, 'utf8');
let fixture = {};
if (script.trimStart().startsWith('{')) {
    const input = JSON.parse(script);
    script = input.script;
    fixture = input.fixture || {};
}
let nextId = 1;
const elements = [], connectors = [], diagramObjects = [], diagramLinks = [], packages = [], logs = [];
function updateable(object = {}) {
    return Object.assign(object, {
        UpdateCalls: 0,
        Update() { this.UpdateCalls++; return true; },
        GetLastError() { return ''; }
    });
}
function collection(add) {
    const values = [];
    return {
        values,
        get Count() { return values.length; },
        GetAt(index) { return values[index]; },
        AddNew(...args) { const value = add(...args); values.push(value); return value; },
        Refresh() {}
    };
}
function element(name, type, owner) {
    const el = updateable({ Name: name, Type: type, ElementID: nextId++, PackageID: owner.PackageID,
                           ElementGUID: '{E' + nextId + '}', StereotypeEx: '', Notes: '' });
    el.Connectors = collection((label, connectorType) => {
        const link = updateable({ Name: label, Type: connectorType, ConnectorID: nextId++,
                                 ClientID: el.ElementID, Direction: 'Unspecified', StereotypeEx: '' });
        connectors.push(link);
        return link;
    });
    elements.push(el);
    return el;
}
function diagram() {
    const dia = updateable({ DiagramID: nextId++ });
    dia.DiagramObjects = collection(position => {
        const obj = updateable({ position, DiagramID: dia.DiagramID });
        diagramObjects.push(obj);
        return obj;
    });
    dia.DiagramLinks = collection(() => {
        const link = updateable({ DiagramID: dia.DiagramID });
        diagramLinks.push(link);
        return link;
    });
    return dia;
}
function pkg(name = '', guid = '', seeded = false) {
    const p = updateable({ Name: name, PackageID: nextId++, PackageGUID: guid, seeded });
    p.Packages = collection(childName => pkg(childName));
    p.Elements = collection((elementName, type) => element(elementName, type, p));
    p.Diagrams = collection(diagram);
    packages.push(p);
    return p;
}
function seedPackage(seed) {
    const p = pkg(seed.name, seed.guid, true);
    for (const item of seed.elements || []) {
        const el = p.Elements.AddNew(item.name, item.type);
        Object.assign(el, { ElementGUID: item.guid, Notes: item.notes || '', StereotypeEx: item.stereotype || '', seeded: true });
    }
    for (const child of seed.children || []) { p.Packages.values.push(seedPackage(child)); }
    return p;
}
const target = pkg('Import target', '{TARGET}', true);
for (const seed of fixture.packages || []) { seedPackage(seed); }
for (const seed of fixture.connectors || []) {
    const src = elements.find(el => el.ElementGUID === seed.source);
    const tgt = elements.find(el => el.ElementGUID === seed.target);
    const c = src.Connectors.AddNew(seed.name || '', seed.type || 'Association');
    Object.assign(c, { SupplierID: tgt.ElementID, Direction: seed.direction || 'Unspecified', StereotypeEx: seed.stereotype || '', seeded: true });
}
const context = {
    Session: { Output(message) { logs.push(message); } },
    Repository: {
        EnsureOutputVisible() {}, ClearOutput() {}, RefreshModelView() {}, OpenDiagram() {},
        GetTreeSelectedPackage() { return fixture.selectedPackageGuid ? packages.find(p => p.PackageGUID === fixture.selectedPackageGuid) : target; },
        GetPackageByGuid(guid) { return packages.find(p => p.PackageGUID.toUpperCase() === guid.toUpperCase()) || null; }
    }
};
let error = null;
try {
    for (let run = 0; run < (fixture.runs || 1); run++) { vm.runInNewContext(script, context, { timeout: 10000 }); }
}
catch (exception) { error = exception.message; }
process.stdout.write(JSON.stringify({ elements, connectors, diagramObjects, diagramLinks,
    packages: packages.map(p => ({ Name: p.Name, PackageID: p.PackageID, PackageGUID: p.PackageGUID, seeded: p.seeded })),
    logs, error }));
if (error && !fixture.expectError) { process.exitCode = 1; }
