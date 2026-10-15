"""OCR KTP lokal (offline) untuk Generator SKMHT.

Prinsip desain
--------------
- **Lokal & offline.** Tidak ada layanan cloud dan tidak ada upload ke mana
  pun. OCR dijalankan lewat ``subprocess`` ke mesin lokal **Tesseract**.
- **Pemrosesan gambar lokal.** Pillow dipakai untuk membetulkan orientasi,
  memperbesar gambar kecil, dan membuat dua varian kontras sebelum Tesseract.
  Tidak ada data yang dikirim keluar komputer.
- **Tanpa penyimpanan permanen.** Gambar unggahan ditulis ke berkas sementara
  (``tempfile``) hanya selama pemrosesan, lalu dihapus pada blok ``finally``.
  Teks OCR dikembalikan ke pemanggil di memori dan tidak disimpan.
- **Tidak menebak.** Parser hanya menerima pola label KTP Indonesia yang
  jelas (mis. ``NIK``, ``Nama``, ``Tempat/Tgl Lahir``). Nilai yang tidak
  cocok pola dibiarkan kosong. Bidang hasil disertai status keyakinan
  (``format_valid``/``review``) dan teks mentah lokal untuk ditinjau pengguna.

Alur pemakaian
--------------
1. ``engine_status()`` memeriksa apakah Tesseract tersedia (PATH / lokasi
   pemasangan Windows umum) dan bahasa apa yang terpasang.
2. ``ocr_image(data, ...)`` menjalankan OCR atas byte gambar.
3. ``parse_ktp_fields(text)`` mengurai teks OCR menjadi kandidat bidang KTP
   secara konservatif.

Semua kejadian galat dikembalikan sebagai ``OcrError`` dengan pesan yang
aman dibaca pengguna (tanpa jejak tumpukan/path privat).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from io import BytesIO

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError
except ImportError:  # Pesan runtime yang terarah diberikan oleh _require_pillow.
    Image = ImageEnhance = ImageFilter = ImageOps = None
    UnidentifiedImageError = OSError

# ---------------------------------------------------------------------------
# Batas & konstanta
# ---------------------------------------------------------------------------

#: Ukuran maksimum berkas gambar yang diproses (byte).
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MiB

#: Waktu maksimum satu proses OCR (detik).
OCR_TIMEOUT_SECONDS = 40

# Batas piksel hasil decode dan hasil preprocessing, bukan hanya ukuran berkas.
# Ini mencegah gambar terkompresi kecil berkembang menjadi alokasi memori besar.
MAX_SOURCE_PIXELS = 30_000_000
MAX_WORKING_PIXELS = 12_000_000
MIN_OCR_WIDTH = 1800
MAX_OCR_WIDTH = 2800

#: Bahasa OCR yang dicoba, berurutan sesuai preferensi.
#: "ind" = Indonesia. "eng" dipakai sebagai cadangan bila paket Indonesia
#: tidak terpasang (hasil tetap ditandai perlu tinjauan).
PREFERRED_LANGS = ("ind", "ind+eng", "eng")

#: Nama executable Tesseract.
_TESSERACT_NAMES = ("tesseract", "tesseract.exe")

#: Lokasi pemasangan Tesseract di Windows yang umum (tanpa PATH).
_WINDOWS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

#: Tanda tangan (magic bytes) berkas gambar yang didukung.
_SIGNATURES = (
    ("jpeg", b"\xff\xd8\xff"),
    ("png", b"\x89PNG\r\n\x1a\n"),
)

class OcrError(Exception):
    """Galat OCR yang aman ditampilkan ke pengguna (tanpa detail internal)."""

# ---------------------------------------------------------------------------
# Deteksi mesin OCR (Tesseract)
# ---------------------------------------------------------------------------

def find_tesseract() -> str | None:
    """Mengembalikan path executable Tesseract, atau None bila tidak ada.

    Pencarian berurutan: variabel lingkungan ``TESSERACT_CMD``, PATH, lalu
    lokasi pemasangan Windows yang umum di ``LOCALAPPDATA`` dan
    ``Program Files``. Tidak mengunduh atau memasang apa pun.
    """
    override = os.environ.get("TESSERACT_CMD")
    if override and os.path.isfile(override):
        return override

    for name in _TESSERACT_NAMES:
        found = shutil.which(name)
        if found:
            return found

    candidates = list(_WINDOWS_CANDIDATES)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(
            local, "Programs", "Tesseract-OCR", "tesseract.exe"))
        candidates.append(os.path.join(
            local, "Tesseract-OCR", "tesseract.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None

def _list_languages(exe: str) -> list[str]:
    """Mengembalikan daftar kode bahasa yang terpasang pada Tesseract."""
    try:
        proc = subprocess.run(
            [exe, "--list-langs"],
            capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = (proc.stdout or b"") + (proc.stderr or b"")
    langs = []
    for line in out.decode("utf-8", "replace").splitlines():
        token = line.strip()
        if token and token.lower() != "list of available languages" \
                and " " not in token:
            langs.append(token)
    return langs

def _pick_language(langs: list[str]) -> str:
    """Memilih opsi ``-l`` yang tersedia, atau string kosong bila tak ada."""
    if "ind" in langs:
        return "ind+eng" if "eng" in langs else "ind"
    if "eng" in langs:
        return "eng"
    return ""

def engine_status() -> dict:
    """Ringkasan status mesin OCR untuk ditampilkan di UI.

    Mengembalikan dict::

        {
          "available": bool,
          "engine": "tesseract" | None,
          "path": str | None,        # hanya nama berkas (bukan path penuh)
          "languages": [..],
          "language": "ind+eng" | .. | "",
          "indonesian": bool,        # paket bahasa Indonesia tersedia
          "detail": str,             # pesan status yang aman dibaca
        }
    """
    exe = find_tesseract()
    if not exe:
        return {
            "available": False,
            "engine": None,
            "path": None,
            "languages": [],
            "language": "",
            "indonesian": False,
            "detail": (
                "Mesin OCR Tesseract belum terpasang. Unggah dokumen tidak "
                "akan diproses sampai Tesseract tersedia. Lihat panduan "
                "pemasangan di README (bagian OCR KTP)."
            ),
            "preprocessing": Image is not None,
        }
    if Image is None:
        return {
            "available": False,
            "engine": "tesseract",
            "path": os.path.basename(exe),
            "languages": [],
            "language": "",
            "indonesian": False,
            "preprocessing": False,
            "detail": (
                "Tesseract terdeteksi, tetapi Pillow belum terpasang. "
                "Jalankan 'python -m pip install -r requirements.txt'."
            ),
        }
    langs = _list_languages(exe)
    lang = _pick_language(langs)
    indonesian = "ind" in langs
    if not indonesian:
        detail = (
            "Tesseract terdeteksi, tetapi paket bahasa Indonesia (ind) tidak "
            "terpasang. OCR memakai bahasa Inggris; hasil wajib ditinjau."
        )
    else:
        detail = "Mesin OCR Tesseract siap (bahasa Indonesia tersedia)."
    return {
        "available": True,
        "engine": "tesseract",
        "path": os.path.basename(exe),
        "languages": langs,
        "language": lang,
        "indonesian": indonesian,
        "detail": detail,
        "preprocessing": True,
    }

# ---------------------------------------------------------------------------
# Validasi berkas gambar
# ---------------------------------------------------------------------------

def detect_image_type(data: bytes) -> str | None:
    """Mengembalikan ``"jpeg"``/``"png"`` berdasarkan tanda tangan berkas.

    None bila bukan JPEG/PNG yang dikenali. Memeriksa isi berkas, bukan
    ekstensi/nama, agar tipe MIME palsu tidak lolos.
    """
    if not data:
        return None
    for name, sig in _SIGNATURES:
        if data.startswith(sig):
            return name
    return None

def validate_image(data: bytes, filename: str = "") -> str:
    """Memvalidasi berkas gambar unggahan.

    Mengembalikan tipe terdeteksi (``"jpeg"``/``"png"``) atau melempar
    ``OcrError`` dengan pesan yang dapat dibaca pengguna.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise OcrError("Berkas gambar tidak valid.")
    data = bytes(data)
    if not data:
        raise OcrError("Berkas gambar kosong.")
    if len(data) > MAX_IMAGE_BYTES:
        mb = MAX_IMAGE_BYTES // (1024 * 1024)
        raise OcrError(f"Ukuran berkas melebihi batas {mb} MB.")
    kind = detect_image_type(data)
    if kind is None:
        raise OcrError(
            "Format berkas tidak dikenali. Gunakan gambar JPEG atau PNG "
            "hasil pemindaian/foto KTP.")
    return kind

# ---------------------------------------------------------------------------
# Menjalankan OCR
# ---------------------------------------------------------------------------

def _run_tesseract(exe: str, image_path: str, lang: str, psm: int = 6) -> str:
    """Menjalankan Tesseract atas satu berkas gambar, mengembalikan teks.

    Memakai ``stdout`` sebagai keluaran (tanpa berkas hasil di disk). Batas
    waktu ``OCR_TIMEOUT_SECONDS`` diterapkan.
    """
    cmd = [exe, image_path, "stdout", "--psm", str(psm), "--oem", "3"]
    if lang:
        cmd += ["-l", lang]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=OCR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise OcrError(
            "Proses OCR melebihi batas waktu. Coba gambar yang lebih kecil "
            "atau lebih jelas.")
    except (OSError, subprocess.SubprocessError):
        raise OcrError("Gagal menjalankan mesin OCR.")
    if proc.returncode != 0:
        raise OcrError("Mesin OCR gagal memproses gambar.")
    return proc.stdout.decode("utf-8", "replace")

def _require_pillow() -> None:
    if Image is None:
        raise OcrError(
            "Pillow belum terpasang. Jalankan 'python -m pip install -r "
            "requirements.txt' lalu mulai ulang aplikasi.")

def _prepare_ocr_variants(data: bytes, directory: str) -> list[tuple[str, int]]:
    """Decode aman dan buat dua varian OCR beresolusi wajar.

    Varian pertama mempertahankan gradasi abu-abu (PSM 6: blok teks). Varian
    kedua memakai ambang global konservatif (PSM 11: teks tersebar), yang lebih
    tahan terhadap latar KTP, pantulan, dan garis dekoratif. Seluruh hasil
    berada di direktori sementara milik satu permintaan.
    """
    _require_pillow()
    try:
        with Image.open(BytesIO(data)) as source:
            source.verify()
        with Image.open(BytesIO(data)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                raise OcrError("Dimensi gambar terlalu besar untuk diproses.")
            image = ImageOps.exif_transpose(source).convert("L")
    except OcrError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise OcrError("Isi gambar JPEG/PNG rusak atau tidak dapat dibaca.")

    width, height = image.size
    target_width = min(MAX_OCR_WIDTH, max(MIN_OCR_WIDTH, width))
    scale = target_width / width
    target_height = max(1, round(height * scale))
    if target_width * target_height > MAX_WORKING_PIXELS:
        scale = (MAX_WORKING_PIXELS / (width * height)) ** 0.5
        target_width = max(1, round(width * scale))
        target_height = max(1, round(height * scale))
    if (target_width, target_height) != image.size:
        image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)

    gray = ImageOps.autocontrast(image, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.35)
    gray = gray.filter(ImageFilter.SHARPEN)

    # Ambang diturunkan sedikit dari rerata agar teks gelap dipertahankan tanpa
    # mengubah karakter menjadi dugaan baru.
    histogram = gray.histogram()
    total = sum(histogram) or 1
    mean = sum(level * count for level, count in enumerate(histogram)) / total
    threshold = max(105, min(205, int(mean * 0.86)))
    binary = gray.point(lambda value: 255 if value > threshold else 0, mode="1")

    variants = []
    for name, prepared, psm in (("gray", gray, 6), ("binary", binary, 11)):
        path = os.path.join(directory, f"{name}.png")
        prepared.save(path, format="PNG", optimize=False)
        variants.append((path, psm))
    return variants

def _score_ocr_text(text: str) -> tuple[int, int]:
    """Nilai layout pass tanpa menyimpan/menampilkan data pribadi."""
    parsed = parse_ktp_fields(text)
    values = [entry for entry in parsed["fields"].values() if entry["value"]]
    labels = sum(
        1 for pattern in _LABELS.values() if _label_regex(pattern).search(text))
    # Label dan nilai yang berhasil dipasangkan lebih penting daripada teks
    # panjang/garbled. Panjang hanya menjadi tie breaker terbatas.
    return labels * 4 + len(values) * 6, min(len(text), 4000)

def ocr_image(data: bytes, filename: str = "", runner=None) -> dict:
    """Menjalankan OCR atas byte gambar dan mengembalikan hasilnya.

    Parameter ``runner`` memudahkan pengujian: callable
    ``runner(exe, image_path, lang, psm) -> str``. Bila None, pemanggil default
    (``_run_tesseract``) yang dipakai.

    Mengembalikan dict::

        {
          "text": str,          # teks OCR mentah
          "image_type": str,    # "jpeg" | "png"
          "language": str,      # bahasa yang dipakai
          "engine": "tesseract",
        }

    Melempar ``OcrError`` untuk semua kegagalan yang dapat dibaca pengguna.
    """
    kind = validate_image(data, filename)

    exe = find_tesseract()
    if not exe:
        raise OcrError(
            "Mesin OCR Tesseract belum terpasang sehingga gambar tidak dapat "
            "diproses. Lihat panduan di README.")

    lang = _pick_language(_list_languages(exe))
    run = runner or _run_tesseract

    # Satu direktori acak per permintaan; semua varian selalu dibersihkan.
    try:
        with tempfile.TemporaryDirectory(prefix="ktp_ocr_") as tmp_dir:
            variants = _prepare_ocr_variants(bytes(data), tmp_dir)
            results = [run(exe, path, lang, psm) for path, psm in variants]
            text = max(results, key=_score_ocr_text, default="")
    except OcrError:
        raise
    except Exception:
        # Jangan bocorkan path/data internal dari Pillow atau runner produksi.
        if runner is None:
            raise OcrError("Mesin OCR gagal memproses gambar.")
        raise

    return {
        "text": text or "",
        "image_type": kind,
        "language": lang,
        "engine": "tesseract",
    }

# ---------------------------------------------------------------------------
# Parser KTP (konservatif, Bahasa Indonesia)
# ---------------------------------------------------------------------------

# Label yang mungkin muncul pada KTP. Alternatif dipisah "|".
# Pencocokan toleran terhadap spasi dan tanda baca yang umum salah-baca.
_LABEL_PATTERNS = (
    ("nik", r"N\s*[I1l]\s*K"),
    ("nama", r"N\s*a\s*m\s*a"),
    ("tempat_lahir", r"T\s*e\s*m\s*p\s*a\s*t\s*/?\s*T\s*[gq]\s*l\.?\s*Lahir"),
    ("jenis_kelamin", r"J\s*e\s*n\s*i\s*s\s*K\s*e\s*l\s*a\s*m\s*i\s*n"),
    ("agama", r"A\s*g\s*a\s*m\s*a"),
    ("status", r"S\s*t\s*a\s*t\s*u\s*s\s*P\s*e\s*r\s*k\s*a\s*w\s*i\s*n\s*a\s*n"),
    ("pekerjaan", r"P\s*e\s*k\s*e\s*r\s*j\s*a\s*a\s*n"),
    ("kewarganegaraan", r"K\s*e\s*w\s*a\s*r\s*g\s*a\s*n\s*e\s*g\s*a\s*r\s*a\s*a\s*n"),
    ("alamat", r"A\s*l\s*a\s*m\s*a\s*t?"),
    ("rt_rw", r"R\s*T\s*/?\s*R\s*W"),
    ("kel_desa", r"K\s*e\s*l\s*/?\s*D\s*e\s*s\s*a"),
    ("kecamatan", r"K\s*e\s*c\s*a\s*m\s*a\s*t\s*a\s*n"),
    ("kabupaten", r"K\s*a\s*b\s*u\s*p\s*a\s*t\s*e\s*n"),
    ("provinsi", r"P\s*r\s*o\s*v\s*i\s*n\s*s\s*i"),
)

#: Peta nama label -> pola, agar pemakaian tidak bergantung indeks posisi.
_LABELS = dict(_LABEL_PATTERNS)

# Nama field target yang dapat diisi otomatis dari KTP (peran pemilik).
# Dipetakan ke key formulir SKMHT terstruktur (dusun/RT/RW/desa/kecamatan/
# kabupaten). Bagian alamat dipetakan HANYA bila benar-benar terbaca; kandidat
# tetap berupa saran dan tidak menimpa nilai formulir tanpa persetujuan.
def _role_address_fields(prefix: str) -> dict:
    return {
        "dusun": f"{prefix}_dusun",
        "rt": f"{prefix}_rt",
        "rw": f"{prefix}_rw",
        "kel_desa": f"{prefix}_desa",
        "kecamatan": f"{prefix}_kecamatan",
        "kabupaten": f"{prefix}_kabupaten",
    }


ROLE_FIELD_MAP = {
    "owner": {
        "nik": "owner_nik",
        "nama": "owner_nama",
        "tempat_lahir": "owner_lahir_tempat",
        "tanggal_lahir": "owner_lahir_tanggal",
        "pekerjaan": "owner_pekerjaan",
        **_role_address_fields("owner"),
    },
    "spouse": {
        "nik": "spouse_nik",
        "nama": "spouse_nama",
        "tempat_lahir": "spouse_lahir_tempat",
        "tanggal_lahir": "spouse_lahir_tanggal",
        "pekerjaan": "spouse_pekerjaan",
        **_role_address_fields("spouse"),
    },
    "debtor": {
        "nik": "debtor_nik",
        "nama": "debtor_nama",
        "tempat_lahir": "debtor_lahir_tempat",
        "tanggal_lahir": "debtor_lahir_tanggal",
        "pekerjaan": "debtor_pekerjaan",
        **_role_address_fields("debtor"),
    },
}

#: Opsi jenis kelamin KTP -> sapaan formulir yang aman dipetakan.
GENDER_TO_TITLE = {
    "laki-laki": "Tuan",
    "laki - laki": "Tuan",
    "perempuan": "Nyonya",
}

def _normalize_ws(text: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", text).strip()

def _label_regex(label_pattern: str) -> re.Pattern:
    """Regex label + pemisah pada satu baris, toleran bullet OCR pendek."""
    return re.compile(
        r"(?im)^[^\w\n]{0,4}" + label_pattern
        + r"[^\w\n]{0,8}(.*)$"
    )

def _clean_value(value: str) -> str:
    """Membersihkan nilai: rapikan spasi, buang titik dua/garis ekor OCR."""
    v = _normalize_ws(value)
    v = re.sub(r"^[\s:;\u2022|=_-]+", "", v)
    v = v.strip(" :;\u2022|")
    # Buang deret tanda hubung/titik yang jadi derau (mis. header KTP).
    v = re.sub(r"[-_=]{2,}", " ", v)
    return v.strip()

def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")

def _first_label_value(text: str, label_pattern: str) -> str:
    m = _label_regex(label_pattern).search(text)
    if not m:
        return ""
    return _clean_value(m.group(1))

def _parse_nik(text: str) -> tuple[str, str]:
    """Mengembalikan (nik, status); 16 digit hanya berarti format valid."""
    # Cari NIK 16 digit. Utamakan yang berdekatan dengan label NIK.
    label_m = _label_regex(_LABELS["nik"]).search(text)
    if label_m:
        same_line = _digits_only(label_m.group(1))
        if len(same_line) == 16:
            return same_line, "format_valid"
        # NIK bisa "tumpah" ke baris berikutnya.
        after = text[label_m.end():label_m.end() + 40]
        for cand in re.findall(r"\d[\d\s]{14,}\d", after):
            digits = _digits_only(cand)
            if len(digits) == 16:
                return digits, "format_valid"
        if same_line and len(same_line) != 16:
            # Ada digit tetapi panjang tidak pas: jangan menebak angka.
            return "", "review"
        return "", "review"

    # Tanpa label: hanya terima bila ada tepat satu deret 16 digit yang jelas.
    found = [d for d in re.findall(r"\d{16}", text)]
    unique = set(found)
    if len(unique) == 1:
        return found[0], "review"
    return "", "missing"

def _parse_birth(text: str) -> dict:
    """Mengurai 'Tempat/Tgl Lahir' menjadi tempat + tanggal (YYYY-MM-DD).

    Hanya mengembalikan tanggal bila formatnya jelas (DD-MM-YYYY). Tidak
    mengarang komponen yang hilang. Toleran terhadap ':' dan pemisah koma.
    """
    m = _label_regex(_LABELS["tempat_lahir"]).search(text)
    if not m:
        return {"tempat_lahir": "", "tanggal_lahir": "",
                "birth_status": "missing"}
    raw = _clean_value(m.group(1))
    if not raw:
        return {"tempat_lahir": "", "tanggal_lahir": "",
                "birth_status": "missing"}

    # Pisahkan tempat dan tanggal: tanggal muncul sebagai d/m/Y lewat '-'/'/'.
    dm = re.search(r"(\d{1,2})\s*[-/.\s]\s*(\d{1,2})\s*[-/.\s]\s*(\d{4})", raw)
    tempat = ""
    tanggal = ""
    status = "review"
    if dm:
        tempat = _normalize_ws(raw[:dm.start()]).strip(" ,")
        day, month, year = (int(dm.group(1)), int(dm.group(2)),
                            int(dm.group(3)))
        if 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100:
            tanggal = f"{year:04d}-{month:02d}-{day:02d}"
            status = "format_valid" if tempat else "review"
    else:
        tempat = _normalize_ws(raw).strip(" ,")
    return {"tempat_lahir": tempat, "tanggal_lahir": tanggal,
            "birth_status": status}

def _parse_alamat(text: str) -> dict:
    """Mengurai alamat KTP menjadi bagian terstruktur secara konservatif.

    Mengembalikan dict ``{"alamat", "dusun", "rt", "rw", "desa", "kecamatan",
    "kabupaten"}``. Hanya bagian yang benar-benar ditemukan yang diisi; nilai
    tidak diarang. Urutan RT/RW pada NIK (RT dulu, lalu RW) diperbaiki bila
    terlihat tertukar (RT <= 12 sedangkan RW >= 31).
    """
    out = {"alamat": "", "dusun": "", "rt": "", "rw": "",
           "desa": "", "kecamatan": "", "kabupaten": ""}

    alamat_line = _first_label_value(text, _LABELS["alamat"])
    if alamat_line:
        out["alamat"] = alamat_line

    rtrw = _first_label_value(text, _LABELS["rt_rw"])
    rt = rw = ""
    if rtrw:
        digits = re.findall(r"\d{1,3}", rtrw)
        if len(digits) >= 2:
            rt, rw = digits[0], digits[1]
        elif len(digits) == 1:
            rt = digits[0]
    if not (rt and rw):
        # Ambil RT/RW dari baris Alamat: token "RT 001 RW 002" atau "001/002".
        m_rt = re.search(r"(?i)\bR?T\b\s*[:/\-]?\s*(\d{1,3})", alamat_line or "")
        m_rw = re.search(r"(?i)\bR?W\b\s*[:/\-]?\s*(\d{1,3})", alamat_line or "")
        if m_rt and not rt:
            rt = m_rt.group(1)
        if m_rw and not rw:
            rw = m_rw.group(1)
        if not (rt and rw) and alamat_line:
            pair = re.search(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)",
                             alamat_line)
            if pair:
                rt, rw = pair.group(1), pair.group(2)

    # Perbaiki RT/RW tertukar (urutan NIK: RT lalu RW).
    rt_i = int(rt) if rt.isdigit() else None
    rw_i = int(rw) if rw.isdigit() else None
    if rt_i is not None and rw_i is not None and rt_i > 30 and rw_i <= 12:
        rt, rw = rw, rt
    out["rt"], out["rw"] = rt, rw

    # Dusun: dari baris Alamat, buang token RT/RW/angka.
    if alamat_line:
        dusun = re.sub(r"(?i)\bRT\b\s*/?\s*[:\-]?\s*\d*", " ", alamat_line)
        dusun = re.sub(r"(?i)\bRW\b\s*[:/\-]?\s*\d*", " ", dusun)
        dusun = re.sub(r"\d+\s*/\s*\d+", " ", dusun)
        dusun = re.sub(r"\b\d{1,6}\b", " ", dusun)
        out["dusun"] = _normalize_ws(dusun).strip(" ,;.-|")

    out["desa"] = _first_label_value(text, _LABELS["kel_desa"])
    out["kecamatan"] = _first_label_value(text, _LABELS["kecamatan"])
    out["kabupaten"] = _first_label_value(text, _LABELS["kabupaten"])
    return out

def parse_ktp_fields(text: str) -> dict:
    """Mengurai teks OCR KTP menjadi kandidat bidang secara konservatif.

    Mengembalikan dict::

        {
          "fields": {
              "nik":   {"value": ..., "status": "format_valid"|"review"|"missing"},
              "nama":  {...},
              "tempat_lahir": {...},
              "tanggal_lahir": {...},
              "jenis_kelamin": {"value": "Laki-Laki"|"Perempuan"|"", ...},
              "pekerjaan": {...},
              "alamat": {...},
              "rt_rw": {...}, "kel_desa": {...}, "kecamatan": {...},
              "kabupaten": {...}, "provinsi": {...},
          },
          "raw_text": str,     # teks OCR lokal untuk ditinjau pengguna
        }

    Tidak ada nilai yang "ditebak". Bidang yang tidak terdeteksi bernilai
    kosong dengan status ``"missing"``.
    """
    text = text or ""
    fields: dict[str, dict] = {}

    def put(key: str, value: str, status: str):
        fields[key] = {"value": value, "status": status}

    # NIK
    nik, nik_status = _parse_nik(text)
    put("nik", nik, nik_status)

    # Nama
    nama = _first_label_value(text, _LABELS["nama"])
    # Buang derau nama kalau hanya berisi digit/simbol.
    if nama and not re.search(r"[A-Za-z]{2,}", nama):
        nama = ""
    put("nama", nama, "review" if nama else "missing")

    # Tempat & tanggal lahir
    birth = _parse_birth(text)
    put("tempat_lahir", birth["tempat_lahir"],
        "review" if birth["tempat_lahir"] else "missing")
    put("tanggal_lahir", birth["tanggal_lahir"],
        birth["birth_status"] if birth["tanggal_lahir"] else "missing")

    # Jenis kelamin -> hanya dipetakan aman bila jelas.
    jk_raw = _first_label_value(text, _LABELS["jenis_kelamin"]).lower()
    jk = ""
    if jk_raw.startswith("laki") or jk_raw.startswith("laki-laki"):
        jk = "Laki-Laki"
    elif jk_raw.startswith("perempuan"):
        jk = "Perempuan"
    put("jenis_kelamin", jk, "review" if jk else "missing")

    # Pekerjaan
    pekerjaan = _first_label_value(text, _LABELS["pekerjaan"])
    if pekerjaan and not re.search(r"[A-Za-z]{2,}", pekerjaan):
        pekerjaan = ""
    # "Belum/Tidak Bekerja" adalah nilai KTP yang sah.
    put("pekerjaan", pekerjaan, "review" if pekerjaan else "missing")

    # Alamat terstruktur (konservatif).
    alamat = _parse_alamat(text)
    put("alamat", alamat["alamat"], "review" if alamat["alamat"] else "missing")

    # Bagian alamat terpisah: pakai hasil penguraian; fallback ke label mentah
    # (mis. baris RT/RW standalone) tanpa mengarang.
    for key in ("dusun", "rt", "rw", "kel_desa", "kecamatan", "kabupaten",
                "provinsi"):
        if key in alamat and alamat.get(key):
            val = alamat[key]
        elif key in _LABELS:
            val = _first_label_value(text, _LABELS[key])
        else:
            val = ""
        put(key, val, "review" if val else "missing")

    return {"fields": fields, "raw_text": text}

def candidates_for_role(parsed: dict, role: str) -> dict:
    """Memetakan hasil parser ke key formulir SKMHT untuk sebuah peran.

    Mengembalikan dict ``{form_key: {"value":..., "status":..., "source":...}}``
    yang hanya memuat key formulir yang diketahui untuk peran tersebut.
    """
    mapping = ROLE_FIELD_MAP.get(role)
    if not mapping:
        return {}
    out: dict = {}
    fields = (parsed or {}).get("fields", {})
    for ktp_key, form_key in mapping.items():
        entry = fields.get(ktp_key)
        if not entry or not entry.get("value"):
            continue
        out[form_key] = {
            "value": entry["value"],
            "status": entry.get("status", "review"),
            "source": ktp_key,
        }
    return out
