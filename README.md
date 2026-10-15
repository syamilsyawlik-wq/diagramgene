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
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Isi `APP_PASSWORD` di `.streamlit/secrets.toml` dengan password sendiri, lalu:

```bash
.venv/bin/python -m streamlit run app.py
```

Pada Windows, gunakan `.venv\Scripts\python.exe` sebagai pengganti
`.venv/bin/python`, dan salin file contoh melalui File Explorer atau PowerShell.

Alternatif untuk deployment/cloud: sediakan environment variable `APP_PASSWORD`
melalui pengaturan rahasia platform. Environment variable yang tidak kosong
diprioritaskan di atas file secrets. Tanpa keduanya, aplikasi menampilkan petunjuk
konfigurasi dan menutup akses konversi. Jangan commit password.

Devcontainer menyiapkan venv dan dependensi otomatis, lalu menjalankan Streamlit
pada port 8501 dengan perlindungan CORS dan XSRF bawaan tetap aktif.

## Mencoba konversi

1. Login dan pilih mode.
2. Upload `examples/proses_sederhana.drawio` untuk BPMN atau diagram umum,
   atau `examples/portofolio_aplikasi.csv` untuk TRM. Contoh ini berisi data sintetis.
3. Untuk mode diagram umum, konfigurasi katalog EA seperti petunjuk berikut.
   Untuk mencoba tanpa katalog, nonaktifkan **Pakai ulang objek dari katalog EA**.
4. Buat script, periksa preview/ringkasan dan peringatan, lalu unduh file `.js`.
5. Di Sparx EA, buka **Specialize > Scripting**, buat script berbahasa **JScript**,
   dan paste hasilnya.
6. Pilih package tujuan di Project Browser, lalu jalankan script. Coba dahulu
   pada package sandbox atau file `.qea` lokal.

Setiap eksekusi membuat sub-package dan diagram output baru. Objek yang terikat
ke katalog memakai identitas yang sama; objek lokal yang tidak dikelola katalog
tetap dibuat baru. Preview merupakan perkiraan layout, bukan render Sparx EA.

### Pakai Actor Manager dari katalog perusahaan

Fitur ini tersedia di **Diagram umum → entitas & relasi**, untuk UML dan ArchiMate.
Tujuannya menggunakan objek model yang sama pada banyak diagram. Contohnya,
Actor `Manager` dalam katalog dipasang ke diagram Persetujuan Anggaran dan
Persetujuan Pengadaan dengan **ElementID dan GUID yang sama**. Connector dari
kedua proses mengarah ke Actor katalog tersebut; Actor tidak disalin ke package output.

1. Aktifkan **Pakai ulang objek dari katalog EA** (aktif secara default).
2. Masukkan **GUID root package katalog** pada model EA tujuan. Seluruh
   sub-package katalog ikut dicari; objek di luar root tersebut tidak dipakai.
3. Opsional untuk pemeriksaan sebelum impor: unduh `export_ea_catalogue.js`,
   pilih root package katalog di EA, dan jalankan sebagai JScript. Script hanya
   membaca model. Salin output mulai header `GUID,Name,...` ke file CSV UTF-8,
   lalu upload sebagai **Metadata katalog EA**. Jangan sertakan pesan lain di CSV.
4. Upload diagram. Bentuk Actor dikenali sebagai UML Actor / ArchiMate Business
   Actor. Jika sumber hanya berisi kotak atau bentuk catatan bertuliskan `Manager`,
   metadata katalog dapat mengusulkan tipe Actor dan GUID yang cocok.
5. Periksa tabel tipe dan **Cocokkan dengan objek katalog EA**. Jika nama ambigu,
   tentukan tipe dan GUID objek yang benar dari kandidat beserta package asalnya.
   Tipe Class hasil default tidak dianggap bukti bahwa sebuah kotak adalah data
   Class jika ada beberapa kandidat katalog bernama sama.
6. Generate script, pilih package output di EA, dan jalankan. Script memvalidasi
   semua binding terlebih dahulu, lalu menempatkan referensi objek katalog pada
   diagram dan membuat/memakai ulang connector ke objek tersebut.

**Tipe yang wajib memakai katalog** awalnya Actor, ArchiMate Business Actor, dan
Business Role. Tambahkan Activity, Business Process, Application Component, atau
tipe lain jika katalog tersebut juga menjadi sumber master untuk proses/aplikasi/data.
Pencocokan otomatis memakai nama (abaikan kapitalisasi dan spasi berlebih) serta
tipe. Binding GUID eksplisit tetap berlaku ketika nama visual berbeda dari nama
master. Saat runtime, tipe dan keberadaan GUID di root katalog diperiksa ulang;
CSV merupakan snapshot metadata, bukan pengganti model EA tujuan.

Default **Batalkan impor** menghentikan proses sebelum perubahan model bila nama
ambigu, master wajib belum ada, GUID tidak ditemukan, atau tipe tidak cocok. Tidak
ada fallback ke Note atau Actor lokal. Opsi **Buat master baru di katalog** dapat
dipilih secara eksplisit untuk membuat master yang belum ada di root katalog;
referensi berikutnya dalam impor yang sama menggunakan master baru tersebut.
Objek katalog yang telah ada tidak diganti nama, dipindahkan, atau ditimpa notes-nya.

Connector yang sudah ada dipakai ulang jika endpoint, tipe, stereotype, nama,
dan arah identik. Pengulangan impor tetap membuat diagram/package output baru;
fitur ini bukan sinkronisasi atau penghapusan model lama secara otomatis. Jika
satu objek katalog muncul beberapa kali pada halaman sumber, diagram hasil
menempatkannya sekali dan semua connector tetap mengarah ke objek yang sama.

Coba `examples/manager_dan_proses.drawio`: dua diagram proses memakai Actor Manager
yang sama. Jalankan pada salinan model/sandbox untuk memverifikasi integrasi dengan
katalog perusahaan. UI tidak membuka file `.qea` di server; akses model dan reuse
terjadi saat JScript dijalankan di dalam Sparx EA. Reuse katalog ini belum diterapkan
ke generator BPMN dan TRM; lane BPMN tidak otomatis dianggap Actor katalog.

### Diagram umum: entitas yang bisa direlasikan

Pilih **Diagram umum → entitas & relasi**, lalu pilih profil **UML umum** atau
**ArchiMate 3**. Pada UML, kotak dan bentuk catatan menjadi **Class** secara default.
Pilih **Component**, **Node**, atau **Artifact** sebagai
tipe default jika sesuai model yang diinginkan; pengaturan ini berlaku sekaligus
untuk seluruh kotak dan bentuk catatan.

Sesudah upload, buka **Pemetaan tipe elemen sebelum konversi** untuk menyesuaikan
tipe per elemen. Contoh: CRM → Component, Server/Network → Node, Data pelanggan →
Class. Bentuk Actor/umlActor dipetakan menjadi Actor dan umlActivity menjadi Activity.
Wadah tetap Boundary dan teks lepas tetap Note, kecuali diubah atau dicocokkan ke katalog.

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
membutuhkan penggambaran ulang relasi. Nama relasi dan arah panah dari sumber tetap
dipakai, termasuk arah terbalik, dua arah, dan relasi ke diri sendiri. Panah menjadi
Dependency, sedangkan garis tanpa panah menjadi Association pada profil UML.
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

Suite mencakup startup tanpa secrets, login/logout dan pembatasan percobaan,
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

- `app.py`: login, upload, konfigurasi mode, preview, dan download.
- `drawio_to_sparx.py`: pembacaan draw.io, pemetaan BPMN, layout, generator JScript.
- `visio_reader.py`: pembaca Visio `.vsdx`.
- `generic_mode.py`: pemetaan diagram umum ke elemen Sparx.
- `model_types.py`: katalog UML/ArchiMate, usulan tipe, dan pemetaan relasi.
- `ea_catalogue.py`: parsing metadata katalog, validasi binding GUID, resolver reuse JScript.
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

## Penggunaan internal

Password bersama melindungi halaman aplikasi; pembatasan percobaan login berlaku
per session. Gunakan server/jaringan internal untuk dokumen internal, dan HTTPS
ketika diakses melalui jaringan. File secrets, diagram internal, dan hasil
konversi diabaikan oleh Git; hanya contoh sintetis di `examples/` yang disertakan.
