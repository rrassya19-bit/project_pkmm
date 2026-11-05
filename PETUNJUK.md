# BARA — Indonesia Fire Watch

Prototipe HTML/CSS/JavaScript + Flask untuk pemantauan Indonesia. Model asli disalin, tidak dilatih ulang. Jalankan melalui server, bukan dengan klik langsung index.html.

## 1. Menjalankan

Buka PowerShell:

```powershell
cd C:\project_pkmm
python -m pip install -r requirements.txt
python server.py
```

Buka http://127.0.0.1:5000. Setelah dependensi terpasang, cukup klik dua kali `start.bat`. Tutup terminal atau Ctrl+C untuk menghentikan server. Server hanya menerima koneksi komputer sendiri.

## 2. Mendapat NASA FIRMS MAP_KEY

1. Buka https://firms.modaps.eosdis.nasa.gov/api/.
2. Pilih **Get MAP_KEY** / **Request MAP_KEY** (tautan formulir: https://firms.modaps.eosdis.nasa.gov/api/map_key/).
3. Isi email dan keterangan penggunaan penelitian/PKMM sesuai formulir NASA. Ikuti verifikasi email dan ketentuan yang ditampilkan. Akun Earthdata, jika diminta NASA, dibuat melalui https://urs.earthdata.nasa.gov/.
4. Salin MAP_KEY yang diberikan NASA. Jangan masukkan password Earthdata sebagai MAP_KEY.
5. Buka berkas `C:\project_pkmm\.env` menggunakan Notepad. Isi:

```ini
FIRMS_MAP_KEY=MAP_KEY_ANDA_DARI_NASA
NDWI_FORMULA=green_nir
```

6. Simpan sebagai `.env`, bukan `.env.txt`. Di File Explorer aktifkan View → Show → File name extensions untuk memeriksa nama.
7. Hentikan server dengan Ctrl+C, jalankan `python server.py` lagi, lalu klik **Perbarui** di web.
8. Jika gagal: periksa key aktif, email terverifikasi, kuota API, koneksi internet, dan log terminal. Key hanya dibaca backend; tidak dikirim ke JavaScript. Jangan unggah `.env` ke Git atau membagikan tangkapan layar isinya.

Endpoint yang dipakai:
`https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_SNPP_NRT/94,-12,142,7/{1-3}`

Pilihan 1–3 hari mengikuti hari akuisisi API, bukan jaminan jendela 24 jam tepat. Cache dan penyegaran otomatis 5 menit untuk menghemat kuota. Web yang tertutup tidak melakukan polling. Data NRT bergantung lintasan dan keterlambatan pemrosesan; bukan CCTV atau pemantauan setiap detik.

## Pemantauan grid otomatis dan prioritas

1. Restart server (Ctrl+C lalu jalankan `start.bat`), refresh browser dengan Ctrl+F5.
2. Zoom ke area yang ingin dipantau. Klik **Pilih area di peta (2 sudut)**, lalu klik dua sudut berseberangan. Lebar/tinggi harus 0,005?2 derajat (maksimal sekitar 220 km).
3. Pilih interval **30 menit**, **1 jam**, atau **3 jam**. Klik **Simpan area & mulai**. Ini mengganti grid sebelumnya dan mulai siklus pertama segera.
4. Area dipecah menjadi grid 3?3. Hanya pusat grid di daratan Indonesia dipakai, sehingga jumlah titik bisa kurang dari 9. Ini sampel titik, bukan seluruh piksel area.
5. Server membaca maksimal **5 titik per siklus, satu per satu**. Giliran berikutnya melanjutkan dari titik terakhir, jadi 9 titik memperoleh pemeriksaan pertama dalam dua siklus. Interval dihitung setelah siklus selesai; waktu unduh tidak dihitung sebagai jeda.
6. Katalog selalu mencari citra dalam **30 hari terakhir**, awan scene <40%, dan piksel SCL layak. Citra identik yang sudah dibaca disimpan dalam cache memori, maksimal 128 pasangan lokasi/citra; kanal tidak diunduh ulang selama cache tersedia.
7. **Analisis sekarang** memajukan jadwal satu siklus (maksimal 5 titik). Tombol tidak memulai siklus kedua ketika siklus pertama masih berjalan. **Jeda** menghentikan setelah titik yang sedang diproses selesai. **Lanjutkan** memulai kembali segera. Untuk mengganti area saat sibuk: jeda dan tunggu titik saat ini selesai.
8. Hasil dan jadwal tersimpan di `monitor_state.json`. Browser boleh ditutup. **Server dan komputer harus tetap hidup**. Setelah server dinyalakan ulang, pemantauan berlanjut jika sebelumnya aktif; siklus yang terlewat tidak ditumpuk.

**Prioritas 1 ? indikasi kebakaran aktif:** deteksi termal FIRMS seluruh Indonesia yang diakuisisi dalam 24 jam terakhir, belum kebakaran terkonfirmasi. Diurutkan per tanggal terbaru, keyakinan deteksi, FRP terbesar, lalu jam terbaru. Panel menampilkan maksimal 50 deteksi teratas; tabel hotspot dan CSV tetap tersedia di bawah.

**Prioritas 2 ? potensi:** titik pada area grid pilihan, kelas 1 CatBoost, citra maksimal 14 hari. Diurutkan skor kelas 1 tertinggi lalu citra terbaru. Titik potensi dalam jarak 1 km dari deteksi aktif tidak ditampilkan ulang sebagai prioritas pencegahan. Kelas 0 tidak masuk prioritas potensi.

Titik yang menunggu, gagal, atau tertutup awan terlihat di **Status tiap titik grid**; kegagalan bukan label aman. Citra 15?30 hari tetap dapat dianalisis dan terlihat sebagai citra lama, tetapi tidak masuk prioritas potensi. Jika FIRMS gagal diperbarui, panel menyatakan data belum lengkap. Tidak ada notifikasi SMS/WhatsApp; prioritas tampil pada dashboard.

Model telah diberi arti kelas oleh pemilik, tetapi kalibrasi probabilitas, formula NDWI, horizon prediksi, dan akurasi operasional masih perlu diverifikasi melalui notebook pelatihan. Skor 80% kelas 1 tidak otomatis berarti peluang kebakaran 80% di dunia nyata.

## 3. Menggunakan Sentinel-2 dan CatBoost

Tidak membutuhkan kredensial Sentinel Hub/GEE. Aplikasi memakai katalog publik Earth Search v1 dan COG Sentinel-2 L2A di AWS:
https://earth-search.aws.element84.com/v1

Untuk analisis manual, buka **Analisis manual satu titik**.

1. Klik titik daratan Indonesia atau isi lintang/bujur.
2. Pilih rentang tanggal maksimal 90 hari. Disarankan 30 hari untuk mencari citra layak.
3. Klik **Analisis dengan CatBoost**. Backend mencari maksimal 40 citra, mengurutkan yang terbaru, lalu mencoba 5 citra terakhir dengan awan scene <40%.
4. Kanal diambil pada satu piksel di lokasi tersebut. Masker SCL menolak no-data, piksel rusak, bayangan awan, awan, cirrus, dan salju.
5. Hasil memuat kelas asli, probabilitas setiap kelas, nilai fitur, ID citra dan tanggal akuisisi. Ini analisis titik, belum berupa raster risiko seluruh Indonesia.

Fitur paket model: B2, B3, B4, B8, B11, B12, NDVI, NDWI, longitude, latitude. Model tidak memerlukan dNBR. Citra yang diambil adalah satu piksel per band pada resolusi native (10/20 m), bukan rata-rata wilayah.

Praproses saat ini:
- Band diskalakan ke reflektansi ×10000; metadata scale/offset dibaca dan offset tidak diterapkan dua kali jika Earth Search sudah mengharmonisasikannya.
- NDVI = (B8 - B4) / (B8 + B4).
- NDWI default = (B3 - B8) / (B3 + B8), yakni green/NIR.
- Jika pelatihan memakai NDWI Gao / moisture index, isi `NDWI_FORMULA=nir_swir` di `.env` untuk rumus (B8 - B11)/(B8 + B11), lalu restart server.
- Hanya dua nilai NDWI_FORMULA di atas yang didukung.

**Batas validasi model:** file joblib hanya memuat estimator dan nama fitur, tanpa dokumentasi definisi target, formula NDWI, periode prediksi, kalibrasi probabilitas, maupun praproses pelatihan. CSV Sentinel-2 yang ditemukan di Downloads memakai nilai band skala ribuan, tetapi itu belum membuktikan seluruh pipeline pelatihan. Pemilik model telah mengonfirmasi kelas 1 = berpotensi terbakar dan kelas 0 = aman. Web memakai label tersebut, dengan keterangan bahwa aman menurut model bukan jaminan keamanan. Probabilitas kelas bukan kepastian kebakaran atau ramalan waktu kejadian. Cocokkan dengan notebook pembuat model sebelum penggunaan operasional; model berbasis citra bisa mengenali area yang sudah terbakar alih-alih memprediksi sebelum terjadi.

## 4. Membaca hotspot dan titik kebakaran

Lingkaran menunjukkan **anomali termal FIRMS**. Warna merah berarti keyakinan deteksi tinggi, bukan tingkat keparahan atau kebakaran terkonfirmasi. FRP adalah daya radiatif dalam MW, bukan luas area terbakar. Tidak semua kebakaran terdeteksi, dan tidak setiap hotspot adalah kebakaran vegetasi. Titik kebakaran terkonfirmasi memerlukan data lapangan/instansi atau validasi tambahan; aplikasi tidak membuat titik konfirmasi palsu.

Data hanya Indonesia: API area dengan bounding box Indonesia, lalu penyaringan poligon daratan untuk membuang titik negara tetangga. Batas disimpan di `indonesia.geojson`, sumber https://github.com/datasets/geo-countries (Natural Earth). Batas bersifat kartografis; pulau kecil dapat terlewat pada skala data tersebut. Hotspot laut/offshore tidak ditampilkan. Tombol unduh CSV mengikuti filter tampilan; tabel menampilkan maksimal 300 baris terbaru, peta dan unduhan memuat seluruh hasil filter.

## 5. Struktur proyek

- `server.py`: server, FIRMS, ekstraksi Sentinel-2, inferensi model.
- `static/index.html`, `style.css`, `app.js`: frontend tanpa build tool.
- `model_early_warning_sentinel2.joblib`: salinan model Anda.
- `.env`: konfigurasi lokal rahasia, dikecualikan Git.
- `indonesia.geojson`: batas wilayah lokal.
- `monitoring.py`: jadwal backend, grid 3?3, antrean terbatas, pengurutan prioritas.
- `monitor_state.json`: area, jadwal, dan hasil; dibuat otomatis dan tidak diikutkan Git.
- `test_app.py`, `test_monitoring.py`: pengujian lokal tanpa key NASA.
- `start.bat`: peluncur Windows.

## 6. Pemeriksaan

```powershell
cd C:\project_pkmm
python -m unittest test_app test_monitoring
node --check static/app.js
node test_frontend.cjs
```

Peta menggunakan Leaflet/CARTO/OpenStreetMap dan font Google sehingga membutuhkan internet. Tidak ada data demo yang disamarkan sebagai data live. Jangan jalankan Flask development server langsung sebagai layanan internet publik; versi ini untuk penggunaan lokal dahulu.

## Hasil verifikasi implementasi

- 15 pengujian lokal lulus: model asli, API, batas Indonesia, grid dan batas area, antrean bergiliran, jeda, penyimpanan, kegagalan per titik, cache citra, dan urutan prioritas.
- Sintaks Python dan JavaScript lulus.
- HTTP halaman, CSS, JavaScript, status model, dan batas Indonesia semuanya 200.
- Uji lengkap Sentinel-2 → fitur → CatBoost berhasil di longitude 116.3, latitude -8.5, rentang 1–31 Agustus 2025. Citra yang dipilih: S2B_50LMR_20250824_0_L2A, akuisisi 24 Agustus 2025. Ini pemeriksaan integrasi, bukan pengukuran akurasi model.
- NASA FIRMS live telah diuji menggunakan MAP_KEY lokal melalui endpoint area; key tidak ditampilkan dalam log pengujian.
- Tampilan belum diperiksa secara visual di browser karena sesi tidak menyediakan browser.

Verifikasi pemantauan otomatis: satu titik grid daratan Lombok berhasil membaca citra `S2B_50LMR_20261018_0_L2A` (18 Oktober 2026) dan menjalankan CatBoost asli. Logika frontend pemilihan dua sudut, reset pilihan, status piksel gagal, dan skor prioritas lulus `node test_frontend.cjs`. Ini pengujian integrasi, bukan penilaian akurasi prediksi.

Hasil kelas 1 dengan citra lebih dari 14 hari sekarang tetap ditampilkan pada bagian **hasil kelas 1 ? citra lama**, terpisah dari prioritas terbaru. Hasil ini bukan nol atau kelas 0: ia memerlukan citra baru sebelum dipakai sebagai peringatan terkini. Ringkasan grid menunjukkan jumlah hasil kelas 1 dan titik yang masih menunggu.
