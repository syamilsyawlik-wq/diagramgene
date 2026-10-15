"""
Streamlit: upload draw.io / Visio -> JScript untuk membuat diagram BPMN di Sparx EA.
Jalankan:  streamlit run app.py
Password diambil dari environment APP_PASSWORD atau .streamlit/secrets.toml.
"""
import hashlib
import hmac
import os
import re
import time
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from drawio_to_sparx import convert, list_pages
from generic_mode import convert_generic, list_generic_pages, load_generic_pages
from model_types import (EA_LABEL_TYPES, EA_TYPE_LABELS,
                         RELATION_TYPES, ARCHIMATE_NAMES, archimate, default_relation_type)
from ea_catalogue import (DEFAULT_MANAGED_TYPES, catalogue_candidates, catalogue_index, guid,
                         normalise_catalogue, read_catalogue_csv)
from trm_mode import convert_trm
from xlsx_to_csv import xlsx_to_csv_bytes
from preview import render_preview

MAX_ATTEMPTS, LOCKOUT_SEC = 5, 60
LAYOUTS = {
    "Vertikal: lane jadi kolom, alur atas ke bawah": ("vertical", False),
    "Horizontal: lane jadi baris, alur kiri ke kanan": ("horizontal", False),
    "Posisi asli dari draw.io": ("vertical", True),
}
MODES = {
    "Alur proses → BPMN": "bpmn",
    "Diagram umum → entitas & relasi": "generic",
    "Portofolio aplikasi (CSV) → TRM": "trm",
}
MODE_HELP = {
    "bpmn": "Untuk flowchart proses bisnis dengan urutan langkah dan panah, dengan atau tanpa "
            "swimlane. Hasilnya diagram BPMN 2.0 (pool, lane, task, gateway, event, data object) "
            "dengan layout disusun ulang otomatis.",
    "generic": "Untuk kerangka konseptual dan peta arsitektur. Kotak dan bentuk catatan menjadi "
               "entitas UML atau ArchiMate, dengan relasi antarelemen dari draw.io/Visio. "
               "Posisi relatif dan ukuran dipertahankan. Tipe elemen bisa disesuaikan sebelum konversi.",
    "trm": "Untuk CSV portofolio aplikasi (format TRM: Nama Aplikasi, ODA Domain, ODA Component, "
           "Kritikalitas, dan kolom tech stack). Hasilnya package TRM lengkap: Applications, ODA Mapping "
           "(analisis redundansi per ODA Domain), dan Technology Stack (Model View per teknologi).",
}
TRM_INFO = r"""
**Format CSV yang diharapkan**

- Baris pertama berisi nama kolom. Pemisah koma (`,`) atau titik koma (`;`) sama-sama bisa, termasuk hasil *Save As CSV* dari Excel.
- Wajib ada kolom **Nama Aplikasi**. Kolom **Deskripsi** jadi Notes aplikasi; kolom lain jadi tagged value dengan nama yang sama.
- **ODA Domain** dan **ODA Component** (misalnya `D. Production` dan `D25. Work Order Management`) dipakai untuk ODA Mapping. Daftar lengkap 8 domain dan 81 komponen ODA sudah ada di app; komponen yang tidak dikenal ditambahkan otomatis.
- Kolom tech stack: kolom berpola `Kategori - Subkategori` (misalnya `Data Management - Database / Data Store Platform`), plus *Operating System, Jenis Akses, Service Device, Tipe Hosting, Public Cloud Provider*. Beberapa teknologi dalam satu sel dipisah dengan koma atau ` + ` (misalnya `PHP, Flutter`).
- Sel kosong atau berisi `-` di kolom tech stack dianggap tidak ada.
"""
GENERIC_LABEL = {"container": "Wadah", "text": "Teks lepas", "note": "Bentuk catatan",
                 "box": "Kotak", "ellipse": "Elips", "diamond": "Belah ketupat", "actor": "Actor", "activity": "Activity"}
KIND_LABEL = {"task": "Task", "gateway": "Gateway", "start": "Start event",
              "end": "End event", "data": "Data object", "link": "Intermediate event"}
FORMAT_INFO = r"""
**Format yang bisa diupload** (maks. 10 MB):

| Format | Keterangan |
|---|---|
| `.drawio`, `.xml` | File draw.io, terkompresi maupun tidak, boleh lebih dari satu halaman. |
| `.svg`, `.png` | Hasil *File > Export as* dari draw.io dengan opsi **Include a copy of my diagram** dicentang. SVG/PNG biasa (gambar saja) tidak bisa dibaca. |
| `.vsdx` | Visio 2013 ke atas. Mendukung mode *Alur proses* dan *Diagram umum*. |

Diagram boleh memakai swimlane (pool dan lane), lane dari kotak biasa, atau tanpa lane sama sekali.
Shape dikenali dari library Flowchart, BPMN, UML, dan shape dasar draw.io.

File `.vsd` (Visio versi lama) belum didukung: buka di Visio, lalu *File > Save As > Visio Drawing (\*.vsdx)*.
PDF dan gambar hasil scan juga belum didukung.
"""

st.set_page_config(page_title="Import ke Sparx EA", page_icon="🧑‍🍳", layout="centered")


# --------------------------------------------------------------------------- auth
def require_login():
    if st.session_state.get("authed"):
        return
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected:
        try:
            expected = st.secrets.get("APP_PASSWORD", "")
        except StreamlitSecretNotFoundError:
            expected = ""
    if not expected:
        st.error("APP_PASSWORD belum diatur. Isi environment variable APP_PASSWORD "
                 "atau salin .streamlit/secrets.toml.example ke .streamlit/secrets.toml "
                 "dan isi password-nya, lalu jalankan ulang.")
        st.stop()

    st.title("Import ke Sparx EA")
    locked_until = st.session_state.get("locked_until", 0)
    if time.time() < locked_until:
        st.error(f"Terlalu banyak percobaan. Coba lagi dalam {int(locked_until - time.time())} detik.")
        st.stop()

    with st.form("login"):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Masuk", type="primary")
    if submitted:
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state.authed = True
            st.session_state.attempts = 0
            st.rerun()
        attempts = st.session_state.get("attempts", 0) + 1
        st.session_state.attempts = attempts
        if attempts >= MAX_ATTEMPTS:
            st.session_state.locked_until = time.time() + LOCKOUT_SEC
            st.session_state.attempts = 0
        st.error("Password salah.")
    st.stop()


require_login()

with st.sidebar:
    st.caption("Masuk sebagai pengguna internal")
    if st.button("Keluar"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# --------------------------------------------------------------------------- UI
st.title("Import ke Sparx EA")
st.write("Upload diagram dari draw.io atau Visio, atau CSV portofolio aplikasi. Hasilnya script JScript "
         "untuk membangun diagram dan model di Sparx EA.")

mode_label = st.radio("1. Pilih jenis diagram", list(MODES), index=None,
                      help="Pilih dulu sebelum upload.")
if mode_label is None:
    st.info("Pilih jenis diagram dulu.\n\n"
            "- **Alur proses**: flowchart proses bisnis dengan langkah dan panah.\n"
            "- **Diagram umum**: kerangka konseptual, peta, atau diagram tanpa alur proses.\n"
            "- **Portofolio aplikasi (CSV)**: daftar aplikasi beserta ODA dan tech stack → package TRM.")
    st.stop()
mode = MODES[mode_label]
st.caption(MODE_HELP[mode])
generic_default_type = "Class"
generic_profile = "uml"
use_catalogue = False
catalogue_data = None
catalogue_names = {}
catalogue_options = None
catalogue_error = ""
catalogue_digest = ""
if mode == "generic":
    profile_label = st.radio("Profil pemodelan", ["UML umum", "ArchiMate 3"], horizontal=True)
    generic_profile = "archimate" if profile_label == "ArchiMate 3" else "uml"
    default_options = (["Class", "Component", "Node", "Artifact"] if generic_profile == "uml" else
                       [archimate("ApplicationComponent")] +
                       [archimate(n) for n in ARCHIMATE_NAMES if n != "ApplicationComponent"])
    generic_default_type = st.selectbox(
        "Tipe entitas default untuk kotak dan bentuk catatan",
        default_options, format_func=lambda value: EA_TYPE_LABELS[value],
        help="UML: berlaku untuk seluruh kotak. ArchiMate: tipe cadangan untuk elemen yang tidak "
             "dikenali dari bentuk, nama, atau lapisan. Teks lepas tetap Note dan wadah tetap Boundary.")
    if generic_profile == "archimate":
        st.info("Tipe dari nama/lapisan adalah usulan: periksa tabel pemetaan sebelum konversi. "
                "Profil ArchiMate 3 harus aktif di Sparx EA. Tipe relasi dapat dipilih di tabel relasi.")
    use_catalogue = st.checkbox("Pakai ulang objek dari katalog EA", value=True,
                                help="Diagram memakai ElementID/GUID objek katalog yang sama, bukan salinan baru.")
    if use_catalogue:
        st.caption("Actor Manager akan dipakai ulang dari katalog dan dihubungkan ke proses baru. "
                   "Pencocokan diperiksa saat script dijalankan pada model EA tujuan.")
        with st.expander("Katalog EA: konfigurasi dan ekspor metadata", expanded=True):
            st.download_button("Download script Export katalog EA",
                               Path(__file__).with_name("export_ea_catalogue.js").read_text(encoding="utf-8"),
                               file_name="export_ea_catalogue.js", mime="text/javascript")
            st.caption("Opsional: pilih root package katalog di EA, jalankan script ekspor, "
                       "salin output CSV ke file UTF-8, lalu upload untuk melihat kandidat dan memilih GUID.")
            catalogue_upload = st.file_uploader("Metadata katalog EA (CSV, opsional)", type=["csv"], key="catalogue_upload")
            if catalogue_upload is not None:
                try:
                    catalogue_raw = catalogue_upload.getvalue()
                    catalogue_digest = hashlib.sha256(catalogue_raw).hexdigest()
                    catalogue_data = read_catalogue_csv(catalogue_raw)
                    catalogue_names = catalogue_index(catalogue_data["elements"])
                    st.caption(f"{len(catalogue_data['elements'])} objek katalog dapat dipetakan; "
                               f"{catalogue_data['skipped']} tipe tidak didukung dilewati.")
                except (ValueError, UnicodeError) as exc:
                    catalogue_error = str(exc)
            catalogue_root = st.text_input("GUID root package katalog",
                                          value=catalogue_data["package_guid"] if catalogue_data else "",
                                          key=f"catalogue_root_{catalogue_digest}",
                                          help="GUID package pada model EA tujuan; pencarian mencakup seluruh sub-package.")
            managed_types = st.multiselect("Tipe yang wajib memakai katalog",
                                           [t for t in EA_TYPE_LABELS if t not in ("Note", "Boundary")],
                                           default=list(DEFAULT_MANAGED_TYPES),
                                           format_func=lambda t: EA_TYPE_LABELS[t])
            missing_policy = st.selectbox("Jika objek katalog belum ada",
                                          ["Batalkan impor", "Buat master baru di katalog"])
            try:
                catalogue_options = normalise_catalogue({"package_guid": catalogue_root,
                    "managed_types": managed_types, "on_missing": "error" if missing_policy == "Batalkan impor" else "create"})
                if catalogue_data and catalogue_options["package_guid"] != catalogue_data["package_guid"]:
                    catalogue_error = "GUID root berbeda dari metadata CSV. Ekspor katalog dari package tujuan yang benar."
            except ValueError as exc:
                catalogue_error = str(exc)
        if catalogue_error:
            st.warning(catalogue_error)

if mode == "trm":
    root_name = st.text_input("Nama package TRM", value="TRM - Technology Reference Model",
                              help="Package ini dibuat di dalam package yang dipilih di Project Browser.")
    up = st.file_uploader("2. Upload CSV portofolio aplikasi atau template TRM (.xlsx)", type=["csv", "xlsx"],
                          help="File .xlsx dibaca dari sheet 'Aplikasi' lalu dikonversi otomatis ke CSV.")
    st.markdown(TRM_INFO)
    if up is None:
        st.stop()
    raw = up.getvalue()
    if up.name.lower().endswith(".xlsx"):
        try:
            raw, info = xlsx_to_csv_bytes(raw)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:  # noqa: BLE001
            st.error(f"File .xlsx tidak bisa dibaca ({type(exc).__name__}: {exc}).")
            st.stop()
        st.caption(f"Template dibaca: {info['n_rows']} aplikasi, "
                   f"{len(info['skipped_examples'])} baris contoh dibuang.")
        csv_stem = re.sub(r"[^\w\-]+", "_", Path(up.name).stem).strip("_") or "trm"
        st.download_button("Download CSV hasil konversi", raw, file_name=f"{csv_stem}.csv", mime="text/csv")
    if st.button("Buat script", type="primary"):
        with st.spinner("Membaca CSV dan menyusun model TRM..."):
            try:
                js, model, stats, warns = convert_trm(raw, root_name.strip() or "TRM - Technology Reference Model")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Konversi gagal ({type(exc).__name__}: {exc}).")
                st.stop()
        st.session_state.trm = {"key": (hashlib.sha256(raw).hexdigest(), root_name), "js": js,
                                "model": model, "stats": stats, "warns": warns, "name": up.name}
    res = st.session_state.get("trm")
    if not res or res["key"] != (hashlib.sha256(raw).hexdigest(), root_name):
        st.stop()
    stt, mdl = res["stats"], res["model"]
    st.success(f"Script siap: {stt['n_apps']} aplikasi, {stt['n_components']} ODA Component, "
               f"{stt['n_tech']} teknologi.")
    for w in res["warns"]:
        st.warning(w)
    if stt["unmapped_apps"]:
        st.warning("Aplikasi belum terpetakan ke ODA (tidak muncul di ODA Mapping): " + ", ".join(stt["unmapped_apps"]))
    stem = re.sub(r"[^\w\-]+", "_", Path(res["name"]).stem).strip("_") or "trm"
    st.download_button("Download script JScript", res["js"].encode("utf-8"),
                       file_name=f"{stem}_trm_sparx.js", mime="text/javascript", type="primary")
    with st.expander("Salin script (tanpa download)"):
        st.caption("Klik ikon salin di pojok kanan atas kotak kode, lalu paste ke script JScript baru di Sparx.")
        st.code(res["js"], language="javascript")
    c1, c2, c3 = st.columns(3)
    c1.metric("Relasi Realisation (aplikasi → ODA)", stt["n_realisation"])
    c2.metric("Relasi Dependency (aplikasi → teknologi)", stt["n_dependency"])
    c3.metric("Kandidat redundansi", sum(1 for d in mdl["domains"] for c in d["components"] if len(c["apps"]) >= 2))
    names = {a["key"]: a["name"] for a in mdl["apps"]}
    with st.expander("ODA Mapping per domain"):
        st.dataframe([{"ODA Domain": d["name"], "Component": len(d["components"]),
                       "Component terpetakan": sum(1 for c in d["components"] if c["apps"]),
                       "Pemetaan aplikasi": d["n_apps"]} for d in mdl["domains"]],
                     hide_index=True, use_container_width=True)
    with st.expander("Kandidat redundansi (1 ODA Component dipakai ≥ 2 aplikasi)"):
        st.dataframe([{"ODA Component": c["name"], "Jumlah": len(c["apps"]),
                       "Aplikasi": ", ".join(names[k] for k in c["apps"])}
                      for d in mdl["domains"] for c in d["components"] if len(c["apps"]) >= 2],
                     hide_index=True, use_container_width=True)
    with st.expander("Technology Stack"):
        st.dataframe([{"Kategori": cat["name"], "Subkategori": it["stereo"], "Teknologi": it["name"],
                       "Jumlah aplikasi": len(it["apps"])} for cat in mdl["tech"] for it in cat["items"]],
                     hide_index=True, use_container_width=True)
    with st.expander("Cara menjalankan di Sparx EA"):
        st.markdown(
            "1. Buka **Specialize > Scripting**, buat script baru dengan bahasa **JScript**, paste isi file, simpan.\n"
            "2. Pilih package tujuan di Project Browser (disarankan package sandbox dulu).\n"
            "3. Jalankan. Package TRM dibuat di dalam package itu, lengkap dengan diagram dan halaman indeks.\n"
            "4. Ringkasan redundansi dan teknologi terbanyak muncul di tab **Output > Script**.\n"
            "5. Kalau menjalankan ulang, hapus dulu package TRM hasil sebelumnya supaya tidak dobel."
        )
    st.stop()

upload_types = ["drawio", "xml", "svg", "png", "vsdx"]
uploaded = st.file_uploader("2. Upload file diagram", type=upload_types,
                            help="Format: " + ", ".join("." + t for t in upload_types) + ". Detail di bawah.")
st.markdown(FORMAT_INFO)

if uploaded is None:
    st.stop()

data = uploaded.getvalue()
digest = hashlib.sha256(data).hexdigest()

@st.cache_data(show_spinner="Membaca file...")
def cached_pages(file_digest, raw, diagram_mode):
    return list_generic_pages(raw) if diagram_mode == "generic" else list_pages(raw)


@st.cache_data(show_spinner="Membaca elemen model...")
def cached_generic_pages(file_digest, raw, default_type, profile):
    return load_generic_pages(raw, default_type=default_type, profile=profile)


try:
    page_list = cached_pages(digest, data, mode)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # noqa: BLE001 - tampilkan ke pengguna
    st.error(f"File tidak bisa dibaca sebagai diagram draw.io atau Visio "
             f"({type(exc).__name__}: {exc}).")
    st.stop()
page_names = [n for n, _ in page_list]
titles = dict(page_list)
if not page_names:
    st.error("Tidak ada halaman diagram di file ini.")
    st.stop()

col1, col2 = st.columns([3, 2])
with col1:
    chosen = st.multiselect("Halaman yang dikonversi", page_names, default=page_names,
                            format_func=lambda n: f"{titles[n]} ({n})")
with col2:
    if mode == "bpmn":
        layout_label = st.radio("Layout", list(LAYOUTS), index=0,
                                help="Vertikal/horizontal: layout disusun ulang otomatis dari urutan "
                                     "alur, biasanya paling rapi. Posisi asli: mengikuti draw.io apa "
                                     "adanya, jadi kalau diagram aslinya padat, hasilnya ikut padat.")
    else:
        layout_label = "Posisi asli dari draw.io"
        st.caption("Layout: posisi asli dari draw.io.")
orient, keep = LAYOUTS[layout_label]

element_types = {}
relation_types = {}
if mode == "generic" and chosen:
    try:
        generic_pages, _ = cached_generic_pages(digest, data, generic_default_type, generic_profile)
    except Exception as exc:
        st.error(f"Elemen diagram tidak bisa dibaca ({type(exc).__name__}: {exc}).")
        st.stop()
    if catalogue_data:
        for pg in generic_pages:
            for it in pg["items"]:
                trusted_type = it["ea_type"] if it["mapping_basis"] != "default" else None
                candidates = catalogue_candidates(catalogue_names, it["text"], trusted_type)
                if len(candidates) == 1:
                    it["ea_type"] = candidates[0]["ea_type"]
                    it["mapping_basis"] = "katalog EA (periksa GUID)"
    rows = [{"Halaman": pg["name"], "ID": it["key"], "Nama": it["text"],
             "Tipe elemen": EA_TYPE_LABELS[it["ea_type"]], "Dasar pemetaan": it["mapping_basis"]}
            for pg in generic_pages if pg["name"] in chosen for it in pg["items"]]
    with st.expander("Pemetaan tipe elemen sebelum konversi"):
        st.caption("Misalnya CRM → Component, Server → Node, Data pelanggan → Class. "
                   "Mengubah tipe tidak memutus relasi. Gunakan Note hanya untuk anotasi.")
        selection_key = hashlib.sha256(repr(tuple(chosen)).encode()).hexdigest()[:12]
        edited = st.data_editor(
            rows, hide_index=True, disabled=["Halaman", "ID", "Nama", "Dasar pemetaan"],
            column_config={"Tipe elemen": st.column_config.SelectboxColumn(
                "Tipe elemen", options=list(EA_LABEL_TYPES), required=True)},
            key=f"generic_mapping_{digest}_{generic_profile}_{generic_default_type}_{selection_key}_{catalogue_digest}")
    defaults = {(r["Halaman"], r["ID"]): r["Tipe elemen"] for r in rows}
    edited_types = {(r["Halaman"], r["ID"]): EA_LABEL_TYPES[r["Tipe elemen"]] for r in edited}
    type_digest = hashlib.sha256(repr(sorted(edited_types.items())).encode()).hexdigest()[:12]
    for row in edited:
        if row["Tipe elemen"] != defaults[(row["Halaman"], row["ID"])] or catalogue_data:
            element_types.setdefault(row["Halaman"], {})[row["ID"]] = EA_LABEL_TYPES[row["Tipe elemen"]]
    if use_catalogue and catalogue_options and catalogue_data:
        binding_rows = []
        candidates_by_row = {}
        basis = {(r["Halaman"], r["ID"]): r["Dasar pemetaan"] for r in rows}
        for row in edited:
            kind = EA_LABEL_TYPES[row["Tipe elemen"]]
            key = (row["Halaman"], row["ID"])
            trusted_type = kind if basis[key] != "default" or row["Tipe elemen"] != defaults[key] else None
            candidates = catalogue_candidates(catalogue_names, row["Nama"], trusted_type)
            candidates_by_row[key] = candidates
            binding_rows.append({"Halaman": row["Halaman"], "ID": row["ID"], "Nama": row["Nama"],
                                 "Tipe elemen": row["Tipe elemen"],
                                 "GUID katalog": candidates[0]["guid"] if len(candidates) == 1 else "",
                                 "Kandidat": " | ".join(c["package_path"] + " / " + c["name"] + " " + c["guid"] for c in candidates)})
        with st.expander("Cocokkan dengan objek katalog EA", expanded=True):
            st.caption("GUID kosong: pencarian saat runtime berdasarkan nama + tipe untuk tipe wajib katalog. "
                       "Nama ganda harus dipilih dengan GUID. Objek yang dipakai ulang tetap berada dalam package asal.")
            bound_rows = st.data_editor(binding_rows, hide_index=True,
                disabled=["Halaman", "ID", "Nama", "Tipe elemen", "Kandidat"],
                key=f"catalogue_bindings_{digest}_{generic_profile}_{catalogue_digest}_{selection_key}_{type_digest}")
        known = {e["guid"]: e for e in catalogue_data["elements"]}
        for row in bound_rows:
            candidates = candidates_by_row[(row["Halaman"], row["ID"])]
            if row["GUID katalog"].strip():
                try:
                    selected_guid = guid(row["GUID katalog"])
                    if selected_guid not in known:
                        raise ValueError(f"{row['Nama']}: GUID tidak terdapat dalam metadata katalog.")
                    if known[selected_guid]["ea_type"] != EA_LABEL_TYPES[row["Tipe elemen"]]:
                        raise ValueError(f"{row['Nama']}: ubah tipe elemen menjadi {EA_TYPE_LABELS[known[selected_guid]['ea_type']]} sesuai objek katalog.")
                    catalogue_options["bindings"].setdefault(row["Halaman"], {})[row["ID"]] = selected_guid
                except ValueError as exc:
                    catalogue_error = str(exc)
            elif len(candidates) > 1:
                catalogue_error = f"{row['Nama']}: nama katalog ambigu; pilih GUID pada tabel pencocokan."
        if catalogue_error:
            st.error(catalogue_error)
    relation_rows = []
    for pg in generic_pages:
        if pg["name"] not in chosen:
            continue
        names = {it["key"]: it["text"] for it in pg["items"]}
        relation_rows.extend({"Halaman": pg["name"], "ID": link["key"], "Dari": names[link["src"]],
                              "Ke": names[link["tgt"]], "Nama": link["name"],
                              "Tipe relasi": default_relation_type(edited_types[(pg["name"], link["src"])],
                                  edited_types[(pg["name"], link["tgt"])], link["directed"], generic_profile)}
                             for link in pg["links"])
    if relation_rows:
        with st.expander("Pemetaan tipe relasi sebelum konversi"):
            st.caption("Panah tidak selalu menjelaskan makna relasi. Pilih misalnya Serving atau Access "
                       "untuk ArchiMate; endpoint dan arah dari sumber tetap dipertahankan.")
            edited_relations = st.data_editor(
                relation_rows, hide_index=True, disabled=["Halaman", "ID", "Dari", "Ke", "Nama"],
                column_config={"Tipe relasi": st.column_config.SelectboxColumn(
                    "Tipe relasi", options=list(RELATION_TYPES), required=True)},
                key=f"generic_relations_{digest}_{generic_profile}_{selection_key}_{type_digest}")
        for row in edited_relations:
            relation_types.setdefault(row["Halaman"], {})[row["ID"]] = row["Tipe relasi"]

mapping_key = tuple((page, tuple(sorted(types.items()))) for page, types in sorted(element_types.items()))
relations_key = tuple((page, tuple(sorted(types.items()))) for page, types in sorted(relation_types.items()))
conversion_key = (digest, tuple(chosen), layout_label, mode, generic_default_type, generic_profile, mapping_key, relations_key,
                  repr(catalogue_options), catalogue_error)

if st.button("Buat script", type="primary", disabled=not chosen or bool(catalogue_error)):
    with st.spinner("Membaca diagram dan menyusun layout..."):
        try:
            if mode == "generic":
                js, pages, notes = convert_generic(data, page_names=chosen,
                                                  default_type=generic_default_type, element_types=element_types,
                                                  profile=generic_profile, relation_types=relation_types, catalogue=catalogue_options)
            else:
                js, pages, notes = convert(data, orient=orient, keep_layout=keep, page_names=chosen)
            previews = [render_preview(pg) for pg in pages]
        except Exception as exc:  # noqa: BLE001
            st.error(f"Konversi gagal ({type(exc).__name__}: {exc}).")
            st.stop()
    st.session_state.result = {"key": conversion_key,
                               "js": js, "pages": pages, "previews": previews, "notes": notes,
                               "name": uploaded.name}

result = st.session_state.get("result")
if not result or result["key"] != conversion_key:
    st.stop()

# --------------------------------------------------------------------------- output
st.success(f"Script siap: {len(result['pages'])} diagram.")
for note in result.get("notes", []):
    st.warning(note)
stem = re.sub(r"[^\w\-]+", "_", Path(result["name"]).stem).strip("_") or "diagram"
st.download_button("Download script JScript", result["js"].encode("utf-8"),
                   file_name=f"{stem}_sparx.js", mime="text/javascript", type="primary")

for pg, png in zip(result["pages"], result["previews"]):
    if pg.get("mode") == "generic":
        st.subheader(pg["name"])
        st.caption(f"{len(pg['items'])} elemen, {len(pg['links'])} connector")
        with st.expander("Preview"):
            st.image(png, caption="Preview kasar dari posisi asli draw.io.")
        with st.expander("Daftar elemen"):
            st.dataframe([{"Jenis": GENERIC_LABEL.get(it["kind"], it["kind"]),
                           "Tipe Sparx": EA_TYPE_LABELS[it["ea_type"]],
                           "Teks": it["text"].replace("\n", " / ")[:120]} for it in pg["items"]],
                         hide_index=True, use_container_width=True)
    else:
        lanes = {l["key"]: l["name"] for l in pg["lanes"]}
        seq = sum(1 for f in pg["flows"] if f["kind"] == "seq")
        st.subheader(pg["pool"]["name"])
        st.caption(f"{len(pg['lanes'])} lane, {len(pg['nodes'])} elemen, "
                   f"{seq} sequence flow, {len(pg['flows']) - seq} data association")
        with st.expander("Preview layout"):
            st.image(png, caption="Preview kasar. Garis di Sparx digambar orthogonal.")
        with st.expander("Daftar elemen"):
            st.dataframe(
                [{"Lane": lanes.get(n["lane"], ""), "Jenis": KIND_LABEL[n["kind"]], "Nama": n["name"]}
                 for n in pg["nodes"]],
                hide_index=True, use_container_width=True)
        if pg.get("skipped"):
            with st.expander(f"Shape yang tidak dikonversi ({len(pg['skipped'])})"):
                st.caption("Shape ini tidak dikenali sebagai bagian alur proses, misalnya teks lepas, "
                           "catatan, gambar, kop dokumen, atau garis yang tidak menempel ke shape. "
                           "Tambahkan manual di Sparx kalau perlu.")
                st.dataframe([{"Jenis": sk["master"], "Teks": sk["text"]} for sk in pg["skipped"]],
                             hide_index=True, use_container_width=True)
    if pg.get("skipped") and pg.get("mode") == "generic":
        with st.expander(f"Shape yang tidak dikonversi ({len(pg['skipped'])})"):
            st.dataframe([{"Jenis": sk["master"], "Teks": sk["text"]} for sk in pg["skipped"]],
                         hide_index=True, use_container_width=True)

with st.expander("Cara menjalankan di Sparx EA"):
    st.markdown(
        "1. Buka **Specialize > Scripting**, buat script baru dengan bahasa **JScript**.\n"
        "2. Paste isi file yang di-download, lalu simpan.\n"
        "3. Pilih package tujuan di Project Browser (disarankan package sandbox atau file .qea lokal).\n"
        "4. Jalankan script. Tiap halaman dibuatkan sub-package dan diagram sendiri.\n"
        "5. Kalau menjalankan ulang, hapus dulu package hasil sebelumnya supaya tidak dobel."
    )
with st.expander("Salin script (tanpa download)"):
    st.caption("Klik ikon salin di pojok kanan atas kotak kode, lalu paste ke script JScript baru di Sparx.")
    st.code(result["js"], language="javascript")
