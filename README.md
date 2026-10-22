# DiagramGene — Import ke Sparx EA

Aplikasi Streamlit untuk mengubah diagram atau portofolio aplikasi menjadi
script **JScript** yang membangun model di **Sparx Enterprise Architect**.

| Mode | Masukan | Hasil |
| --- | --- | --- |
| Alur proses | draw.io/XML, SVG/PNG dengan data draw.io tertanam, Visio `.vsdx` | Diagram BPMN 2.0 dengan pool, lane, task, gateway, event, dan relasi |
| Diagram umum | draw.io/XML, SVG/PNG dengan data draw.io tertanam, Visio `.vsdx` | Entitas UML/ArchiMate dengan posisi relatif dan relasi sumber |
| Portofolio TRM | CSV atau template Excel `.xlsx` | Applications, ODA Mapping, Technology Stack, dan diagram indeks |

## Menjalankan secara lokal

Gunakan Python **3.11 atau 3.12**. Jalankan semua perintah dari direktori proyek.
Contoh berikut untuk Linux, macOS, atau cloud workspace:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Aplikasi langsung terbuka tanpa password. Jalankan:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Pada Windows, gunakan `.venv\Scripts\python.exe` sebagai pengganti
`.venv/bin/python`.

Tidak perlu membuat file secrets atau mengatur `APP_PASSWORD`. Konfigurasi password
lama tidak lagi menampilkan login. Tombol **Reset sesi** membersihkan pilihan dan
hasil review lokal. Validasi repository EA dan persetujuan EXECUTE tetap berlaku.

Devcontainer menyiapkan venv dan dependensi otomatis, lalu menjalankan Streamlit
pada port 8501 dengan perlindungan CORS dan XSRF bawaan tetap aktif.

## Impor dengan identitas master dan relasi

Generator BPMN dan Generic sekarang memakai shared import plan, katalog berscope,
review elemen/relasi, dan preflight terhadap repository EA aktif. Default script
adalah **VALIDATE_ONLY**: tidak membuat atau mengubah model.

1. Di Sparx EA melalui Wine pada macOS, pilih root katalog dan jalankan
   `export_ea_catalogue.js` sebagai **JScript**. Simpan output JSON v2 secara privat.
2. Di sidebar DiagramGene pilih **Local Testing** atau **Holding Production**,
   upload snapshot, periksa expected identity, root/scope katalog dan package output.
   Memilih profile tidak membuktikan repository EA aktif sama; runtime memeriksa ulang.
3. Upload diagram, pilih halaman dan periksa semantic type. Pada tabel review,
   pilih master GUID yang benar untuk **REUSE**, atau setujui **NEW** per elemen.
4. Periksa endpoint, tipe, arah, nama/meaning dan ConnectorGUID di tabel relasi.
   Pembuatan relasi baru membutuhkan persetujuan per baris karena mengubah model
   repository, termasuk ketika kedua endpoint merupakan master existing.
5. Download dan jalankan script VALIDATE_ONLY di EA. Setelah validasi serta
   acceptance test EA lulus, pilih EXECUTE, setujui rencana dan generate ulang.

Actor `Manager` pada `examples/manager_dan_proses.drawio` dapat dipetakan ke satu
Actor katalog pada dua diagram dengan ElementGUID/ElementID yang sama. Pool/Lane
BPMN dapat direuse jika parent dan konteks cocok. Parent salah, ambigu, GUID stale,
MDG tidak tersedia atau repository berbeda menghentikan proses sebelum penulisan.
CSV katalog lama tetap bisa dibaca untuk discovery; gunakan snapshot v2 untuk reuse runtime.

**Status: tes otomatis bukan bukti kompatibilitas EA nyata. Acceptance EA masih
belum dijalankan dan memblokir rilis produksi.** Panduan lengkap, arsitektur, file
berubah, contoh Manager dan batas metamodel ada di
[repository-aware import](docs/repository-aware-import.md). Ikuti
[manual acceptance macOS/Wine](docs/manual-acceptance-wine.md) pada `.qea` lokal.

Setiap EXECUTE dapat membuat package/diagram output baru; tidak ada sinkronisasi
penuh atau rollback otomatis. Master dan connector existing tidak ditimpa/dihapus.
Referensi semantik resmi participant/partition/process BPMN dan resolver TRM adalah
P1. TRM tetap tersedia untuk pengujian lokal dengan persetujuan; penulisan TRM
production diblokir sampai integrasi tersebut selesai.

### Diagram umum: entitas yang bisa direlasikan

Pilih **Diagram umum → entitas & relasi**, lalu pilih profil **UML umum** atau
**ArchiMate 3**. Pada UML, kotak dan bentuk catatan menjadi **Class** secara default.
Pilih **Component**, **Node**, atau **Artifact** sebagai
tipe default jika sesuai model yang diinginkan; pengaturan ini berlaku sekaligus
untuk seluruh kotak dan bentuk catatan.

Sesudah upload, buka **Pemetaan tipe elemen sebelum konversi** untuk menyesuaikan
tipe per elemen. Contoh: CRM → Component, Server/Network → Node, Data pelanggan →
Class. Bentuk Actor/umlActor dipetakan menjadi Actor dan umlActivity menjadi Activity.
Wadah diusulkan sebagai Boundary dan teks lepas sebagai Note; review menentukan tipe dan master final.

Profil **ArchiMate 3** menyediakan Business Actor/Role/Process/Service/Object,
Application Component/Service/Function/Interface, Data Object, Node, Device,
System Software, Communication Network, Technology Service, Artifact, Capability,
Goal, Requirement, dan Work Package. Bentuk sumber yang dikenal, nama elemen, dan
lapisan Business/Application/Technology/Data memberi usulan tipe. Kolom
**Dasar pemetaan** menunjukkan asal usulan; periksa khususnya hasil dari nama
atau lapisan, karena makna bisnis tidak selalu tersedia dalam diagram sumber.
Tipe default dipakai bila tidak ada petunjuk. Profil MDG **ArchiMate 3** harus
aktif pada instalasi Sparx EA tujuan.

Connector dibuat antara ID entitas hasil konversi, sehingga penggantian tipe tidak
membutuhkan penggambaran ulang relasi. Nama relasi dan arah panah dari sumber dipertahankan sebagai kandidat. Relasi
memerlukan konfirmasi makna dan validasi endpoint/metamodel sebelum penulisan.
Panah mengusulkan Dependency, sedangkan garis tanpa panah mengusulkan Association pada UML.
Profil ArchiMate memakai Association sebagai awal; tabel **Pemetaan tipe relasi**
menyediakan Association, Serving, Access, Realization, Flow, Triggering, dan Assignment.
Business Actor/Role ke Business Process memakai Assignment sebagai default;
UML Actor ke proses memakai Association.
Tipe dapat diubah tanpa memutus endpoint. Makna seperti Serving atau Access tidak
ditebak hanya dari panah. Relasi yang tidak tercantum di sumber tidak dibuat otomatis.

Gunakan `examples/arsitektur_entitas.drawio` untuk mencoba contoh enam entitas
dalam lapisan Data, Business, Technology, dan Application dengan lima connector.
Hasil lama yang sudah diimpor sebagai Note tidak dimigrasikan otomatis; generate
script baru dan jalankan pada package tujuan yang baru/sandbox untuk memeriksa hasil.

## Format masukan

- Upload maksimal **10 MB**, diatur melalui `.streamlit/config.toml`.
- `.drawio`/`.xml`: dapat terkompresi atau XML biasa, mendukung beberapa halaman.
- `.svg`/`.png`: ekspor draw.io dengan **Include a copy of my diagram** aktif.
  Gambar biasa, hasil scan, dan PDF tidak didukung.
- `.vsdx`: mode BPMN dan entitas UML/ArchiMate, termasuk pilihan halaman. Reader
  menggunakan geometri numerik yang tersimpan dan referensi connector. Simbol
  master beserta child dekoratifnya dijadikan satu entitas; grup biasa menjadi
  wadah. Rotasi, bentuk khusus, dan evaluasi formula Visio tidak direproduksi.
  Simpan `.vsd` lama menjadi `.vsdx` melalui Visio dahulu.
- Diagram umum mempertahankan geometri relatif dan teks; gambar serta seluruh
  warna, font, dan bentuk khusus tidak otomatis disalin. Bentuk di Sparx mengikuti
  tipe model yang dipilih, sehingga Class tidak tampil seperti kertas Note.
- CSV TRM wajib memuat `Nama Aplikasi`; pemisah koma dan titik koma didukung.
  `Deskripsi` menjadi notes, kolom lain menjadi tagged values. `ODA Domain` dan
  `ODA Component` dipakai untuk pemetaan. Referensi bawaan memuat 8 domain dan
  81 komponen; komponen yang tidak dikenal dapat ditambahkan saat konversi.
- Teknologi dibaca dari kolom `Kategori - Subkategori`, serta `Operating System`,
  `Jenis Akses`, `Service Device`, `Tipe Hosting`, dan `Public Cloud Provider`.
  Pisahkan beberapa teknologi dengan koma atau ` + `.
- XLSX harus mengikuti template dua tingkat pada sheet `Aplikasi`, dengan header
  `Nama Aplikasi` di 10 baris pertama. Baris `(Contoh)` dibuang otomatis.

## Pengembangan dan pengujian

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Suite mencakup startup tanpa password/secrets, reset sesi,
navigasi mode, layout BPMN, diagram umum, draw.io terkompresi/embedded SVG,
pemetaan TRM, nama aplikasi duplikat, daftar aplikasi belum terpetakan, konversi
XLSX, entitas serta endpoint connector UML/ArchiMate, reader VSDX, dan penolakan
masukan tidak valid. Pengujian memakai
data sintetis dan tidak memerlukan password atau instalasi Sparx EA. Pengujian
JScript memakai stub Automation API dan membutuhkan Node.js (CI menggunakan Node
22); tes tersebut dilewati bila Node.js tidak tersedia. Stub memeriksa pembuatan
elemen/connector, bukan rendering atau perilaku aplikasi Sparx EA sebenarnya.

Workflow GitHub Actions menjalankan suite pada Python 3.11 dan 3.12 setelah
perubahan didorong ke GitHub. Eksekusi JScript di Sparx EA serta pemeriksaan
tampilan model tetap membutuhkan validasi manual di EA.

`requirements.txt` berisi dependensi utama; `requirements.lock` mengunci seluruh
versi untuk instalasi yang konsisten. Untuk memperbaruinya dengan `uv`:

```bash
uv pip compile --python-version 3.11 --output-file requirements.lock requirements.txt
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m unittest discover -s tests -v
```

Validasi kedua versi Python sebelum mengirim pembaruan lockfile.

## Struktur kode

- `app.py`: akses langsung, upload, konfigurasi mode, preview, dan download.
- `drawio_to_sparx.py`: pembacaan draw.io, pemetaan BPMN, layout, generator JScript.
- `visio_reader.py`: pembaca Visio `.vsdx`.
- `generic_mode.py`: pemetaan diagram umum ke elemen Sparx.
- `model_types.py`: katalog UML/ArchiMate, usulan tipe, dan pemetaan relasi.
- `ea_catalogue.py` / `catalogue_snapshot.py`: metadata, GUID, hierarchy dan scoped catalogue resolver.
- `import_plan.py` / `semantic_rules.py`: shared source model, semantic dan relationship preflight.
- `repository_profiles.py` / `repository_review.py`: profile dan tabel review Streamlit.
- `runtime/`: metadata, repository identity, exporter dan governed JScript runtime.
- `export_ea_catalogue.js`: ekspor metadata katalog dari Sparx EA tanpa mengubah model.
- `trm_mode.py` dan `oda_reference.json`: pemodelan portofolio, ODA, dan teknologi.
- `xlsx_to_csv.py`: konversi template Excel ke CSV.
- `preview.py`: preview layout dengan Matplotlib.
- `tests/`: pengujian regresi; `examples/`: berkas sintetis untuk mencoba aplikasi.

Konverter BPMN dan Excel juga tersedia melalui CLI:

```bash
.venv/bin/python drawio_to_sparx.py input.drawio output.js --horizontal
.venv/bin/python xlsx_to_csv.py input.xlsx output.csv
```

CLI BPMN tanpa metadata menghasilkan rencana VALIDATE_ONLY yang belum terikat;
gunakan Streamlit untuk melengkapi profile, mapping dan persetujuan sebelum eksekusi.
API Python `convert`/`convert_generic` menerima argumen profile, snapshot, keputusan
elemen/relasi dan persetujuan eksplisit.

## Penggunaan internal

Aplikasi lokal berjalan di `127.0.0.1` tanpa login. Akses aplikasi tidak memberikan
izin menulis ke repository EA: preflight, kebijakan production, dan persetujuan
impor tetap berlaku. File secrets lama, diagram internal, dan hasil konversi
diabaikan oleh Git; hanya contoh sintetis di `examples/` yang disertakan.
