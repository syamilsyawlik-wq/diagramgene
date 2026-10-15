// Read-only identity. Never emit ConnectionString or credential-bearing fields.
function dgIdentity(repo) {
    var raw;
    try { raw = String(repo.ConnectionString || ''); }
    catch (e) { throw new Error('Repository identity unavailable from Automation API.'); }
    var path = raw.replace(/^\s+|\s+$/g, '').replace(/\\/g, '/');
    if (/\.qeax?$/i.test(path) && (/^[A-Za-z]:\//.test(path) || /^\//.test(path)) && path.indexOf(';') < 0) {
        return {kind: 'local', locator: path};
    }
    var fields = {}, parts = raw.replace(/^EAConnectString:/, '').split(';');
    for (var i = 0; i < parts.length; i++) {
        var eq = parts[i].indexOf('=');
        if (eq < 0) { continue; }
        var key = parts[i].substring(0, eq).replace(/^\s+|\s+$/g, '').toLowerCase();
        var value = parts[i].substring(eq + 1).replace(/^\s+|\s+$/g, '');
        if (key == 'connect') {
            var nested = value.indexOf('=');
            if (nested >= 0) { fields[value.substring(0, nested).toLowerCase()] = value.substring(nested + 1); }
        } else if (key == 'server' || key == 'data source' || key == 'database' || key == 'initial catalog' || key == 'provider') {
            fields[key] = value;
        }
    }
    var server = fields.server || fields['data source'], database = fields.database || fields['initial catalog'];
    if (server && database && fields.provider && !/[?@{}]/.test(server + database) && (server + database).indexOf('://') < 0) {
        return {kind: 'server', server: server, database: database, provider: fields.provider};
    }
    throw new Error('Repository identity cannot be verified safely: unsupported/opaque connection (including unqualified DSN/PCS). No writes allowed.');
}
