"""Pemetaan data formulir SKMHT -> nilai marker template.

Modul ini mendefinisikan:
- Skema field formulir (label, jenis, wajib/tidak).
- ``validate_and_build``: validasi + normalisasi masukan.
- ``build_marker_values``: mengubah konteks tervalidasi menjadi peta
  ``{key: nilai}`` untuk marker ``{{key}}``; dipakai
  ``docx_template.render_docx_from_template`` (jalur produksi).

Prinsip:
- Klausul tetap (notaris, saksi, penerima kuasa, lembaga) memakai aktor
  sintetis demonstratif pada template dan TIDAK diubah saat render.
- Data variabel personalia default kosong dan wajib diisi, KECUALI bagian
  kabupaten pada alamat tempat tinggal yang default-nya "Kota Contoh".

Alamat tempat tinggal diisi terstruktur (dusun, RT, RW, desa, kecamatan,
kabupaten) dan dirender dengan kata pengantar persis: "bertempat tinggal di
<dusun> Rukun Tetangga <rt>, Rukun Warga <rw>, Desa <desa>, Kecamatan
<kecamatan>, Kabupaten <kabupaten>".

Catatan teknis: nilai marker disisipkan ke teks run gabungan per paragraf,
sehingga marker yang terpecah lintas run tetap tergantikan.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import textutil
from .textutil import ValidationError

# ---------------------------------------------------------------------------
# Nilai tetap (fixed) dari dokumen asli / ketetapan pengguna.
# Nilai-nilai ini HARUS tetap ada di dokumen hasil (diuji di tests/).
# ---------------------------------------------------------------------------

FIXED = {
    "notaris_nama": "NOTARIS CONTOH, Sarjana Hukum, Magister Kenotariatan",
    "witness1": "SAKSI CONTOH SATU",
    "witness2": "SAKSI CONTOH DUA",
    "penerima_kuasa": "PENERIMA KUASA CONTOH",
    "lembaga": "LEMBAGA PEMBIAYAAN CONTOH",
    "lembaga_qq": "LEMBAGA PEMBIAYAAN CONTOH",
}

# ---------------------------------------------------------------------------
# Alamat tempat tinggal (terstruktur) untuk pemilik / pasangan / debitor.
#
# Kata pengantar PERSIS seperti permintaan pengguna:
#   "bertempat tinggal di <dusun> Rukun Tetangga <rt>, Rukun Warga <rw>,
#    Desa <desa>, Kecamatan <kecamatan>, Kabupaten <kabupaten>"
#
# Catatan:
# - Pengguna mengisi teks dusun apa adanya dan placeholder dusun TIDAK
#   ditambahi awalan "Dusun" oleh aplikasi (lihat ``_dusun_text``).
# - Kabupaten default "Kota Contoh" bila dikosongkan; satu-satunya nilai default.
# - RT/RW mempertahankan angka nol di depan sebagai teks (mis. "003", "000").
# - Label distrik yang diminta adalah "Kabupaten" (bukan "Kabupaten/Kota").
# ---------------------------------------------------------------------------

#: Kabupaten default bila pengguna mengosongkan (hanya kabupaten).
DEFAULT_KABUPATEN = "Kota Contoh"

#: Urutan (field, label) bagian alamat tempat tinggal.
RESIDENCE_PARTS = (
    ("dusun", "Dusun"),
    ("rt", "Rukun Tetangga"),
    ("rw", "Rukun Warga"),
    ("desa", "Desa"),
    ("kecamatan", "Kecamatan"),
    ("kabupaten", "Kabupaten"),
)

#: Field bagian alamat yang WAJIB diisi (kabupaten punya default).
RESIDENCE_REQUIRED_PARTS = ("dusun", "rt", "rw", "desa", "kecamatan")

#: Nama bagian alamat (dipakai untuk melewati validasi generik loop field).
_RESIDENCE_PART_NAMES = tuple(part for (part, _label) in RESIDENCE_PARTS)


# ---------------------------------------------------------------------------
# Skema field: (key, label, jenis, wajib)
# jenis: "text" | "date" | "money" | "nik" | "select"
# ---------------------------------------------------------------------------

FIELDS = [
    ("nomor_akta", "Nomor Surat Kuasa (opsional)", "text", False),
    ("tanggal_akta", "Tanggal akta", "date", True),

    ("owner_title", "Sapaan pemilik tanah", "select", True),
    ("owner_nama", "Nama pemilik tanah (Pemberi Kuasa)", "text", True),
    ("owner_lahir_tempat", "Tempat lahir pemilik", "text", True),
    ("owner_lahir_tanggal", "Tanggal lahir pemilik", "date", True),
    ("owner_pekerjaan", "Pekerjaan pemilik", "text", True),
    ("owner_dusun", "Dusun pemilik (isi teks dusun)", "text", True),
    ("owner_rt", "RT pemilik (angka, nol di depan dipertahankan)", "text", True),
    ("owner_rw", "RW pemilik (angka, nol di depan dipertahankan)", "text", True),
    ("owner_desa", "Desa/Kelurahan pemilik", "text", True),
    ("owner_kecamatan", "Kecamatan pemilik", "text", True),
    ("owner_kabupaten", "Kabupaten pemilik (default Kota Contoh)", "text", False),
    ("owner_nik", "NIK pemilik", "nik", True),

    ("spouse_mode", "Pasangan pemberi persetujuan", "select", True),
    ("spouse_nama", "Nama pasangan (pemberi persetujuan)", "text", True),
    ("spouse_lahir_tempat", "Tempat lahir pasangan", "text", True),
    ("spouse_lahir_tanggal", "Tanggal lahir pasangan", "date", True),
    ("spouse_pekerjaan", "Pekerjaan pasangan", "text", True),
    ("spouse_alamat_sama", "Alamat pasangan sama dengan pemilik", "select", True),
    ("spouse_dusun", "Dusun pasangan (isi teks dusun)", "text", False),
    ("spouse_rt", "RT pasangan (angka)", "text", False),
    ("spouse_rw", "RW pasangan (angka)", "text", False),
    ("spouse_desa", "Desa/Kelurahan pasangan", "text", False),
    ("spouse_kecamatan", "Kecamatan pasangan", "text", False),
    ("spouse_kabupaten", "Kabupaten pasangan (default Kota Contoh)", "text", False),
    ("spouse_nik", "NIK pasangan", "nik", True),

    ("same_as_owner", "Debitor sama dengan pemilik tanah", "select", True),
    ("debtor_title", "Sapaan debitor", "select", True),
    ("debtor_nama", "Nama debitor", "text", True),
    ("debtor_lahir_tempat", "Tempat lahir debitor", "text", True),
    ("debtor_lahir_tanggal", "Tanggal lahir debitor", "date", True),
    ("debtor_pekerjaan", "Pekerjaan debitor", "text", True),
    ("debtor_dusun", "Dusun debitor (isi teks dusun)", "text", True),
    ("debtor_rt", "RT debitor (angka)", "text", True),
    ("debtor_rw", "RW debitor (angka)", "text", True),
    ("debtor_desa", "Desa/Kelurahan debitor", "text", True),
    ("debtor_kecamatan", "Kecamatan debitor", "text", True),
    ("debtor_kabupaten", "Kabupaten debitor (default Kota Contoh)", "text", False),
    ("debtor_nik", "NIK debitor", "nik", True),

    ("nilai_pembiayaan", "Nilai pembiayaan (Debitor)", "money", True),
    ("nilai_tanggungan", "Nilai Tanggungan Peringkat Pertama", "money", True),

    ("akad_jenis", "Jenis akad", "text", True),
    ("akad_nomor", "Nomor akad", "text", True),
    ("akad_tanggal", "Tanggal akad", "date", True),

    ("ht_jenis", "Jenis hak atas tanah", "text", True),
    ("ht_nomor", "Nomor hak atas tanah", "text", True),
    ("ht_desa_sertifikat", "Desa/Kelurahan pada sertifikat", "text", True),
    ("surat_ukur_nomor", "Nomor Surat Ukur (lengkap)", "text", True),
    ("surat_ukur_tanggal", "Tanggal Surat Ukur", "date", True),
    ("luas_m2", "Luas (M2)", "text", True),
    ("nib", "Nomor Identifikasi Bidang Tanah (NIB)", "text", True),
    ("nop", "Nomor Objek Pajak (NOP)", "text", True),

    ("lok_provinsi", "Provinsi", "text", True),
    ("lok_kabupaten", "Kabupaten/Kota", "text", True),
    ("lok_kecamatan", "Kecamatan", "text", True),
    ("lok_desa", "Desa/Kelurahan", "text", True),
    ("lok_jalan", "Jalan / RT / RW", "text", True),
]

FIELD_KEYS = {k for (k, *_rest) in FIELDS}

TITLES = ("Tuan", "Nyonya", "Nona")


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dusun_text(value) -> str:
    """Teks dusun apa adanya.

    Pengguna mengisi placeholder dusun sendiri, jadi aplikasi TIDAK menambahkan
    awalan "Dusun". Hanya spasi/tanda pisah berlebih dirapikan.
    """
    return _clean(value).strip(" ,;.-")


def _rt_rw_text(value, label: str, required: bool):
    """Validasi satu bagian RT/RW.

    Menerima 1-3 digit; angka nol dipertahankan sebagai teks. Satu deret 6
    digit (nilai KTP yang tertulis menyatu, mis. "018000") diterima apa adanya.
    Nilai kosong/tanda "-" -> None (pemanggil menerapkan wajib/opsional).
    Tidak pernah mengarang angka.
    """
    text = _clean(value)
    if text in ("", "-"):
        return None
    digits = re.sub(r"\D", "", text)
    if not digits or len(digits) > 6 or (4 <= len(digits) <= 5):
        raise ValidationError(f"{label} harus berupa angka 1-3 digit.")
    return digits


def _resolve_residence(ctx: dict, role: str, require: bool) -> None:
    """Validasi & simpan bagian alamat tempat tinggal untuk satu peran."""
    keys = _RESIDENCE_KEYS[role]
    part_values = {}
    for (part, _label), key in zip(RESIDENCE_PARTS, keys):
        part_values[part] = ctx.get(key, "")

    rt = _rt_rw_text(part_values.get("rt"), "Nomor Rukun Tetangga", require)
    rw = _rt_rw_text(part_values.get("rw"), "Nomor Rukun Warga", require)

    if rt and len(rt) == 6 and not rw:
        rt, rw = _split_rt_rw(rt)

    if require:
        for (part, label), key in zip(RESIDENCE_PARTS, keys):
            if part in ("rt", "rw", "kabupaten"):
                continue
            if not _clean(part_values.get(part)):
                raise ValidationError(
                    f"{label} wajib diisi (alamat tempat tinggal).")
        if not rt:
            raise ValidationError(
                "Nomor Rukun Tetangga wajib diisi (1-3 digit angka).")
        if not rw:
            raise ValidationError(
                "Nomor Rukun Warga wajib diisi (1-3 digit angka).")

    ctx[keys[0]] = _dusun_text(part_values.get("dusun"))
    ctx[keys[1]] = rt
    ctx[keys[2]] = rw
    ctx[keys[3]] = _clean(part_values.get("desa"))
    ctx[keys[4]] = _clean(part_values.get("kecamatan"))
    ctx[keys[5]] = _clean(part_values.get("kabupaten")) or DEFAULT_KABUPATEN


def format_residence(ctx: dict, role: str) -> str:
    """Kalimat alamat tempat tinggal dengan kata pengantar PERSIS.

    "bertempat tinggal di <dusun> Rukun Tetangga <rt>, Rukun Warga <rw>,
     Desa <desa>, Kecamatan <kecamatan>, Kabupaten <kabupaten>"
    """
    keys = _RESIDENCE_KEYS[role]
    return (
        "bertempat tinggal di " + _dusun_text(ctx.get(keys[0]))
        + " Rukun Tetangga " + _clean(ctx.get(keys[1]))
        + ", Rukun Warga " + _clean(ctx.get(keys[2]))
        + ", Desa " + _clean(ctx.get(keys[3]))
        + ", Kecamatan " + _clean(ctx.get(keys[4]))
        + ", Kabupaten " + (_clean(ctx.get(keys[5])) or DEFAULT_KABUPATEN)
    )


# ---------------------------------------------------------------------------
# Validasi & normalisasi
# ---------------------------------------------------------------------------

# Pasangan field identitas debitor -> field pemilik (sumber penyalinan bila
# debitor sama dengan pemilik tanah). Bagian alamat dipetakan per-komponen
# sehingga RT/RW (termasuk angka nol di depan) ikut tersalin apa adanya.
_DEBTOR_FROM_OWNER = {
    "debtor_title": "owner_title",
    "debtor_nama": "owner_nama",
    "debtor_lahir_tempat": "owner_lahir_tempat",
    "debtor_lahir_tanggal": "owner_lahir_tanggal",
    "debtor_pekerjaan": "owner_pekerjaan",
    "debtor_dusun": "owner_dusun",
    "debtor_rt": "owner_rt",
    "debtor_rw": "owner_rw",
    "debtor_desa": "owner_desa",
    "debtor_kecamatan": "owner_kecamatan",
    "debtor_kabupaten": "owner_kabupaten",
    "debtor_nik": "owner_nik",
}

#: Kunci field bagian alamat tempat tinggal per peran.
_RESIDENCE_KEYS = {
    "owner": ("owner_dusun", "owner_rt", "owner_rw", "owner_desa",
              "owner_kecamatan", "owner_kabupaten"),
    "spouse": ("spouse_dusun", "spouse_rt", "spouse_rw", "spouse_desa",
               "spouse_kecamatan", "spouse_kabupaten"),
    "debtor": ("debtor_dusun", "debtor_rt", "debtor_rw", "debtor_desa",
               "debtor_kecamatan", "debtor_kabupaten"),
}

#: Bulan Romawi sesuai aturan penomoran KTP (Januari..Desember).
_ROMAN_MONTHS = ("I", "II", "III", "IV", "V", "VI",
                 "VII", "VIII", "IX", "X", "XI", "XII")


def _split_rt_rw(text: str) -> tuple[str, str]:
    """(rt, rw) dari teks gabungan RT/RW; kosong bila tidak jelas."""
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 6:
        return digits[:3], digits[3:]
    if len(digits) == 3:
        return digits, ""
    if len(digits) == 2:
        return digits[0], digits[1]
    if len(digits) == 1:
        return digits, ""
    if len(digits) > 6:
        return "", ""
    return "", ""


def _digits_to_roman(value: str) -> str:
    """Ubah angka 1..12 menjadi bulan Romawi; selain itu kosong."""
    return _ROMAN_MONTHS[int(value) - 1] if value.isdigit() \
        and 1 <= int(value) <= 12 else ""


def _fix_rt_rw_swap(rt: str, rw: str) -> tuple[str, str]:
    """Perbaiki RT/RW tertukar pada KTP nyata (RT <= 12 sedangkan RW >= 31).

    RT perumahan selalu jauh di bawah 31, sedangkan RW bernomor sampai 30+
    lazim. Bila RT > 30 dan RW <= 12, keduanya jelas tertukar.
    """
    def as_int(value):
        return int(value) if value.isdigit() else None

    rt_i, rw_i = as_int(rt), as_int(rw)
    if rt_i is not None and rw_i is not None and rt_i > 30 and rw_i <= 12:
        return rw, rt
    return rt, rw


def _parse_card_alamat(text: str) -> dict:
    """Uraikan baris 'Alamat/Tempat Tinggal' KTP menjadi bagian terstruktur.

    Mendukung dua bentuk yang umum:
    1. Bertoken: ``DUSUN BARU RT 001 RW 002`` -> dusun="DUSUN BARU", RT/RW.
    2. NIK-11: ``DUSUN BARU 001/002`` (urutan NIK: RT/RW) -> diperbaiki bila
       terlihat tertukar.
    Bila tidak jelas, hanya bagian yang benar-benar terbaca yang diisi; tidak
    ada angka/teks yang dikarang.
    """
    out = {}
    text = text or ""

    rt = rw = ""
    # 1) Token terpisah: "RT 001 RW 002", "Rukun Tetangga 001 Rukun Warga 002".
    m_rt = re.search(r"(?i)\bR?T\b\s*[:/\-]?\s*(\d{1,3})", text)
    m_rw = re.search(r"(?i)\bR?W\b\s*[:/\-]?\s*(\d{1,3})", text)
    if m_rt:
        rt = m_rt.group(1)
    if m_rw:
        rw = m_rw.group(1)
    # 2) Bentuk berslash: "RT/RW 001/002", "001/002", "34/3".
    if not (rt and rw):
        pair = re.search(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)", text)
        if pair:
            rt, rw = _fix_rt_rw_swap(pair.group(1), pair.group(2))
        else:
            combined = re.search(r"(?i)\bRT\s*/?\s*RW\b\s*(\d{6})", text)
            if combined:
                rt, rw = combined.group(1)[:3], combined.group(1)[3:]
    if rt or rw:
        rt, rw = _fix_rt_rw_swap(rt, rw)
        if rt:
            out["rt"] = rt
        if rw:
            out["rw"] = rw

    # Dusun: buang token RT/RW, angka, bulan Romawi, dan "0" dari sisa teks.
    remainder = text
    remainder = re.sub(r"(?i)\bRT\b\s*/?\s*\d*", " ", remainder)
    remainder = re.sub(r"(?i)\bRW\b\s*[:/\-]?\s*\d*", " ", remainder)
    remainder = re.sub(r"\d+\s*[/\-]\s*\d+", " ", remainder)
    remainder = re.sub(r"(?<![A-Za-z])(" + "|".join(_ROMAN_MONTHS)
                       + r")(?![A-Za-z])", " ", remainder)
    remainder = re.sub(r"\b\d{1,6}\b", " ", remainder)
    remainder = re.sub(r"\b0\b", " ", remainder)
    remainder = _clean(remainder).strip(" ,;.-|")
    if remainder:
        out["dusun"] = remainder
    return out


def parse_residence_card(text: str) -> tuple[str, str, str]:
    """Uraikan teks KTP (mode AI, ringkas) -> (rt, rw, kode_bulan_romawi).

    Menerima ``018/000``, ``RT 018 RW 000``, maupun ``018000`` (urutan NIK).
    Mengembalikan string kosong untuk bagian yang tidak terbaca.
    """
    text = text or ""
    pair = re.search(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)", text)
    if pair:
        rt, rw = pair.group(1), pair.group(2)
        roman = ""
    else:
        m = re.search(r"(?<!\d)(\d{1,3})\s+(\d{1,3})(?!\d)", text)
        if m:
            rt, rw = m.group(1), m.group(2)
            roman = ""
        else:
            run = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
            if run:
                rt, rw, roman = run.group(1)[:3], run.group(1)[3:], ""
            else:
                single = re.search(r"(?<!\d)(\d{1,3})(?!\d)", text)
                rt, rw, roman = (single.group(1), "", "") if single else ("", "", "")
    if not roman:
        rm = re.search(r"(?<![A-Za-z])(" + "|".join(_ROMAN_MONTHS) + r")(?![A-Za-z])",
                       text)
        roman = rm.group(1) if rm else ""
    return rt, rw, roman


def validate_and_build(data: dict) -> dict:
    """Memvalidasi input mentah dan mengembalikan konteks siap-render."""
    if not isinstance(data, dict):
        raise ValidationError("Data formulir tidak valid.")

    ctx: dict = {}

    # Tentukan lebih dahulu apakah debitor sama dengan pemilik. Bila ya,
    # field identitas debitor bersumber dari pemilik sehingga field debitor
    # yang kosong (mis. dinonaktifkan di UI) tidak dianggap wajib.
    same_as_owner = _clean(data.get("same_as_owner")) == "ya"

    for key, label, kind, required in FIELDS:
        raw = data.get(key, "")
        if same_as_owner and key in _DEBTOR_FROM_OWNER:
            raw = data.get(_DEBTOR_FROM_OWNER[key], "")
            # Bagian kabupaten punya default (Kota Contoh) -> tetap opsional.
            if not key.endswith("_kabupaten"):
                required = True  # tetap wajib, tetapi sumbernya dari pemilik
        if kind == "date":
            text = _clean(raw)
            if text == "" and not required:
                ctx[key] = None
                continue
            try:
                ctx[key] = textutil.parse_date(text)
            except ValidationError:
                raise ValidationError(f"{label} wajib diisi atau tidak valid.")
        elif kind == "money":
            try:
                ctx[key] = textutil.parse_amount(raw)
            except ValidationError as exc:
                raise ValidationError(f"{label}: {exc}")
        elif kind == "nik":
            try:
                ctx[key] = textutil.validate_nik(raw, label)
            except ValidationError as exc:
                raise ValidationError(str(exc))
        else:
            text = _clean(raw)
            # Bagian alamat tempat tinggal divalidasi khusus (format angka,
            # nol di depan, default kabupaten) oleh ``_resolve_residence``.
            if (required and text == ""
                    and key.split("_", 1)[-1] not in _RESIDENCE_PART_NAMES):
                raise ValidationError(f"{label} wajib diisi.")
            ctx[key] = text

    if ctx["owner_title"].title() not in TITLES:
        raise ValidationError("Sapaan pemilik tanah tidak valid.")
    ctx["owner_title"] = ctx["owner_title"].title()
    if ctx["debtor_title"].title() not in TITLES:
        raise ValidationError("Sapaan debitor tidak valid.")
    ctx["debtor_title"] = ctx["debtor_title"].title()

    spouse_mode = _clean(data.get("spouse_mode")).lower()
    if spouse_mode not in ("istri", "suami"):
        raise ValidationError("Pasangan pemberi persetujuan harus 'istri'/'suami'.")
    ctx["spouse_mode"] = spouse_mode

    if _clean(data.get("spouse_alamat_sama")) not in ("ya", "tidak"):
        raise ValidationError("Status alamat pasangan tidak valid.")
    ctx["spouse_alamat_sama"] = _clean(data.get("spouse_alamat_sama")) == "ya"

    if _clean(data.get("same_as_owner")) not in ("ya", "tidak"):
        raise ValidationError("Status debitor sama dengan pemilik tidak valid.")
    ctx["same_as_owner"] = same_as_owner

    # Alamat tempat tinggal terstruktur (pemilik/debitor selalu; pasangan bila
    # alamatnya berbeda). Validasi bagian RT/RW berupa 1-3 digit (nol di depan
    # dipertahankan) dan kabupaten default Kota Contoh.
    _resolve_residence(ctx, "owner", require=True)
    _resolve_residence(ctx, "spouse",
                       require=not ctx["spouse_alamat_sama"])
    _resolve_residence(ctx, "debtor", require=not ctx["same_as_owner"])

    # Luas: angka positif, keluarannya kata.
    luas_raw = _clean(data.get("luas_m2"))
    normalized = luas_raw.replace(".", "").replace(",", ".").strip()
    try:
        luas_val = float(normalized)
        if luas_val <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ValidationError("Luas (M2) harus berupa angka positif.")
    ctx["luas_raw"] = luas_raw
    ctx["luas_kata"] = textutil.terbilang(int(round(luas_val)))

    if not ctx["nomor_akta"]:
        ctx["nomor_akta"] = "...................."

    # Label & kata ganti pasangan diturunkan di sini (sumber tunggal) agar
    # ringkasan kanonik dan nilai marker memakai perhitungan yang sama.
    if ctx["spouse_mode"] == "istri":
        ctx["spouse_title"] = "Nyonya"
        ctx["_rel_spouse"] = "suaminya"
    else:
        ctx["spouse_title"] = "Tuan"
        ctx["_rel_spouse"] = "istrinya"

    # Bila debitor sama dengan pemilik, identitasnya sudah disalin dari
    # pemilik pada loop validasi di atas (lihat ``_DEBTOR_FROM_OWNER``).

    return ctx


# ===========================================================================
# Template marker (produksi): nilai {{key}}, marker wajib, & ringkasan kanonik
# ===========================================================================
#
# Fungsi di bawah menjadi SUMBER TUNGGAL nilai yang dirender (dipakai mesin
# marker). Semua nilai dihitung dari ``ctx`` tervalidasi sehingga data ringkasan
# yang dilihat pengguna, yang ditandatangani persetujuannya, dan yang dirender
# ke dokumen SELALU berasal dari perhitungan yang sama (tidak ada percabangan
# logika domain).

#: Peran-peran identitas (dipakai ringkasan & marker).
_ROLES = ("owner", "spouse", "debtor")

#: Urutan bagian alamat pada ringkasan & nilai marker.
_ADDRESS_PARTS = ("dusun", "rt", "rw", "desa", "kecamatan", "kabupaten")

#: Nama bulan Indonesia (untuk ringkasan/canonical, tanpa I/O).
_BULAN = ("", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember")


def _tanggal_ringkas(d) -> str:
    """Tanggal gaya ringkas '01-01-2000' (aman bila None)."""
    return textutil.format_tanggal_singkat(d) if d else ""


def _tanggal_panjang(d) -> str:
    """Tanggal gaya Indonesia '1 Januari 2000' (aman bila None)."""
    if not d:
        return ""
    return f"{d.day} {_BULAN[d.month]} {d.year}"


def _terbilang_teks(n) -> str:
    return textutil.terbilang(int(n)) if n else ""


def build_marker_values(ctx: dict) -> dict:
    """Nilai untuk SETIAP marker ``{{key}}`` pada template khusus.

    ``None`` menandakan nilai yang ditolak validasi (mis. nama memuat
    ``{{``/``}}`` atau baris baru). Mesin render akan membiarkannya sehingga
    marker terdeteksi sebagai tak terisi dan proses dibatalkan (gagal-keras).
    """
    values: dict[str, str | None] = {}

    # --- Marker statis (tetap) -------------------------------------------
    values["persetujuan_label"] = "  Persetujuan " + (
        "Istri" if ctx["spouse_mode"] == "istri" else "Suami")

    # --- Marker pembersih (WAJIB kosong) ---------------------------------
    values["_remove_jalan_cont"] = ""

    # --- Nomor & tanggal akta --------------------------------------------
    values["nomor_akta"] = ctx["nomor_akta"]
    values["tanggal_akta_lengkap"] = textutil.format_tanggal_lengkap(
        ctx["tanggal_akta"])

    # --- Identitas owner/spouse/debtor -----------------------------------
    for role in _ROLES:
        values[f"{role}_title"] = ctx[f"{role}_title"]
        values[f"{role}_nama"] = ctx[f"{role}_nama"]
        values[f"{role}_lahir_tempat"] = ctx[f"{role}_lahir_tempat"]
        values[f"{role}_pekerjaan"] = ctx[f"{role}_pekerjaan"]
        values[f"{role}_nik"] = ctx[f"{role}_nik"]

    values["owner_lahir_tanggal_kata"] = textutil.format_tanggal_kata(
        ctx["owner_lahir_tanggal"])
    values["owner_lahir_tanggal_singkat"] = textutil.format_tanggal_singkat(
        ctx["owner_lahir_tanggal"])
    values["owner_alamat"] = format_residence(ctx, "owner")

    values["spouse_lahir_tanggal_kata"] = textutil.format_tanggal_kata(
        ctx["spouse_lahir_tanggal"])
    values["spouse_lahir_tanggal_singkat"] = textutil.format_tanggal_singkat(
        ctx["spouse_lahir_tanggal"])
    values["spouse_alamat"] = format_spouse_alamat(ctx)
    values["spouse_intro"] = _spouse_intro(ctx)
    values["spouse_nama_sig"] = ctx["spouse_nama"]

    values["debtor_lahir_tanggal_kata"] = textutil.format_tanggal_kata(
        ctx["debtor_lahir_tanggal"])
    values["debtor_lahir_tanggal_singkat"] = textutil.format_tanggal_singkat(
        ctx["debtor_lahir_tanggal"])
    values["debtor_alamat"] = format_residence(ctx, "debtor")

    # --- Nilai pembiayaan & tanggungan -----------------------------------
    values["nilai_pembiayaan_teks"] = (
        "Selaku Debitor sejumlah Rp. "
        + textutil.format_rupiah(ctx["nilai_pembiayaan"]) + ",")
    values["nilai_pembiayaan_kata"] = (
        "(" + textutil.rupiah_words(ctx["nilai_pembiayaan"]) + ")")
    values["nilai_tanggungan_teks"] = (
        "Rp. " + textutil.format_rupiah(ctx["nilai_tanggungan"]) + ",- ("
        + textutil.rupiah_words(ctx["nilai_tanggungan"]) + ")")

    # --- Akad -------------------------------------------------------------
    values["akad_jenis_teks"] = f"Akad Pembiayaan {_clean(ctx['akad_jenis'])}"
    values["akad_nomor_teks"] = f"Nomor : {_clean(ctx['akad_nomor'])}"
    values["akad_tanggal_teks"] = (
        "yang dibuat di bawah tangan, tanggal "
        + textutil.format_tanggal_kata(ctx["akad_tanggal"]) + " ("
        + textutil.format_tanggal_singkat(ctx["akad_tanggal"]) + ")")

    # --- Objek Hak Tanggungan / tanah ------------------------------------
    values["ht_teks"] = (
        f"{_clean(ctx['ht_jenis'])} Nomor: {_clean(ctx['ht_nomor'])}/"
        f"{_clean(ctx['ht_desa_sertifikat'])}")
    values["surat_ukur_tanggal_teks"] = (
        textutil.format_tanggal_kata(ctx["surat_ukur_tanggal"]) + " ("
        + textutil.format_tanggal_singkat(ctx["surat_ukur_tanggal"]) + ")")
    values["surat_ukur_nomor"] = _clean(ctx["surat_ukur_nomor"])
    values["luas_m2"] = ctx["luas_raw"]
    values["luas_kata"] = ctx["luas_kata"]
    values["nib"] = _clean(ctx["nib"])
    values["nop"] = _clean(ctx["nop"])

    # --- Lokasi objek -----------------------------------------------------
    values["lok_provinsi"] = _clean(ctx["lok_provinsi"])
    values["lok_kabupaten"] = _clean(ctx["lok_kabupaten"])
    values["lok_kecamatan"] = _clean(ctx["lok_kecamatan"])
    values["lok_desa"] = _clean(ctx["lok_desa"])
    values["lok_jalan"] = _clean(ctx["lok_jalan"])

    # --- Sanitasi: tolak nilai yang merusak marker/XML (gagal-keras) ------
    for key, value in list(values.items()):
        if value is None:
            continue
        text = str(value)
        if "{{" in text or "}}" in text or "\n" in text or "\r" in text:
            values[key] = None
    return values


def _spouse_intro(ctx: dict) -> str:
    """Kalimat pengantar persetujuan pasangan (istri/suami) - tetap apa adanya."""
    if ctx["spouse_mode"] == "istri":
        return ("Menurut keterangannya suami dalam melakukan perbuatan hukum "
                "yang dimaksud dalam akta ini, telah mendapat persetujuan "
                "istrinya :")
    return ("Menurut keterangannya istri dalam melakukan perbuatan hukum yang "
            "dimaksud dalam akta ini, telah mendapat persetujuan suaminya :")


def format_spouse_alamat(ctx: dict) -> str:
    """Alamat pasangan: sama dengan pemilik (relatif) atau alamat terstruktur."""
    if ctx["spouse_alamat_sama"]:
        rel = "suaminya" if ctx["spouse_mode"] == "istri" else "istrinya"
        return "bertempat tinggal sama dengan " + rel + " di atas"
    return format_residence(ctx, "spouse")


#: Key marker yang WAJIB terisi agar dokumen tidak pernah berisi sisa contoh.
REQUIRED_MARKER_KEYS = (
    "nomor_akta",
    "tanggal_akta_lengkap",
    "owner_title", "owner_nama", "owner_lahir_tempat",
    "owner_lahir_tanggal_kata", "owner_lahir_tanggal_singkat",
    "owner_pekerjaan", "owner_alamat", "owner_nik",
    "spouse_intro", "spouse_title", "spouse_nama", "spouse_lahir_tempat",
    "spouse_lahir_tanggal_kata", "spouse_lahir_tanggal_singkat",
    "spouse_pekerjaan", "spouse_alamat", "spouse_nik", "spouse_nama_sig",
    "debtor_title", "debtor_nama", "debtor_lahir_tempat",
    "debtor_lahir_tanggal_kata", "debtor_lahir_tanggal_singkat",
    "debtor_pekerjaan", "debtor_alamat", "debtor_nik",
    "nilai_pembiayaan_teks", "nilai_pembiayaan_kata",
    "akad_jenis_teks", "akad_nomor_teks", "akad_tanggal_teks",
    "nilai_tanggungan_teks",
    "ht_teks", "surat_ukur_tanggal_teks", "surat_ukur_nomor",
    "luas_m2", "luas_kata", "nib", "nop",
    "lok_provinsi", "lok_kabupaten", "lok_kecamatan", "lok_desa", "lok_jalan",
    "persetujuan_label",
)

#: Marker pembersih yang WAJIB bernilai kosong.
REMOVAL_MARKER_KEYS = ("_remove_jalan_cont",)


# ---------------------------------------------------------------------------
# Ringkasan kanonik + digest integritas
# ---------------------------------------------------------------------------

#: Versi skema ringkasan/digest. Naikkan bila struktur ringkasan berubah.
SUMMARY_SCHEMA_VERSION = 1

#: Label bahasa Indonesia untuk bagian ringkasan.
_LABELS = {
    "nomor_akta": "Nomor akta",
    "tanggal_akta": "Tanggal akta",
    "nama": "Nama",
    "sapaan": "Sapaan",
    "lahir_tempat": "Tempat lahir",
    "lahir_tanggal": "Tanggal lahir",
    "pekerjaan": "Pekerjaan",
    "nik": "NIK",
    "alamat": "Alamat",
    "nilai_pembiayaan": "Nilai pembiayaan (Debitor)",
    "nilai_tanggungan": "Nilai Tanggungan Peringkat Pertama",
    "akad_jenis": "Jenis akad",
    "akad_nomor": "Nomor akad",
    "akad_tanggal": "Tanggal akad",
    "ht_jenis": "Jenis hak atas tanah",
    "ht_nomor": "Nomor hak atas tanah",
    "ht_desa_sertifikat": "Desa/Kelurahan pada sertifikat",
    "surat_ukur_nomor": "Nomor Surat Ukur",
    "surat_ukur_tanggal": "Tanggal Surat Ukur",
    "luas_m2": "Luas (M2)",
    "luas_kata": "Luas (kata)",
    "nib": "NIB",
    "nop": "NOP",
    "lok_provinsi": "Provinsi",
    "lok_kabupaten": "Kabupaten/Kota",
    "lok_kecamatan": "Kecamatan",
    "lok_desa": "Desa/Kelurahan",
    "lok_jalan": "Jalan / RT / RW",
    "spouse_mode": "Pasangan pemberi persetujuan",
    "spouse_alamat_sama": "Alamat pasangan",
    "same_as_owner": "Debitor",
}

#: Peta field identitas ringkasan (per peran) -> key ctx.
_ROLE_SUMMARY_KEYS = {
    "nama": "nama",
    "sapaan": "title",
    "lahir_tempat": "lahir_tempat",
    "lahir_tanggal": "lahir_tanggal",
    "pekerjaan": "pekerjaan",
    "nik": "nik",
    "alamat": "alamat",
}


def _canonical_role(ctx: dict, role: str) -> list[list[str]]:
    return [
        ["nama", ctx[f"{role}_nama"]],
        ["sapaan", ctx[f"{role}_title"]],
        ["lahir_tempat", ctx[f"{role}_lahir_tempat"]],
        ["lahir_tanggal", _tanggal_panjang(ctx[f"{role}_lahir_tanggal"])],
        ["pekerjaan", ctx[f"{role}_pekerjaan"]],
        ["nik", ctx[f"{role}_nik"]],
        ["alamat", format_residence(ctx, role)
         if role != "spouse"
         else format_spouse_alamat(ctx)],
    ]


def canonical_summary(ctx: dict) -> dict:
    """Ringkasan kanonik tervalidasi (sumber tunggal untuk UI & digest).

    Struktur:

        {
          "schema_version": int,
          "akta": {"nomor_akta", "tanggal_akta", "tanggal_akta_inc"},
          "owner":  {...}, "spouse": {...}, "debtor": {...},
          "pembiayaan": {"nilai_pembiayaan", "nilai_pembiayaan_kata"},
          "tanggungan": {"nilai_tanggungan", "nilai_tanggungan_kata"},
          "akad": {...}, "tanah": {...}, "lokasi": {...},
          "catatan": [...]
        }

    Seluruh nilai berasal dari ``ctx`` tervalidasi, sehingga ringkasan yang
    dilihat, yang disetujui, dan yang dirender tidak boleh berbeda.
    """
    akad_tanggal_kata = _tanggal_panjang(ctx["akad_tanggal"])
    surat_ukur_kata = _tanggal_panjang(ctx["surat_ukur_tanggal"])
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "akta": {
            "nomor_akta": ctx["nomor_akta"],
            "tanggal_akta": _tanggal_panjang(ctx["tanggal_akta"]),
            "tanggal_akta_inc": textutil.format_tanggal_lengkap(
                ctx["tanggal_akta"]),
        },
        "owner": _role_summary(ctx, "owner"),
        "spouse": _role_summary(ctx, "spouse"),
        "debtor": _role_summary(ctx, "debtor"),
        "pembiayaan": {
            "nilai_pembiayaan": textutil.format_rupiah(ctx["nilai_pembiayaan"]),
            "nilai_pembiayaan_kata": textutil.rupiah_words(
                ctx["nilai_pembiayaan"]),
        },
        "tanggungan": {
            "nilai_tanggungan": textutil.format_rupiah(ctx["nilai_tanggungan"]),
            "nilai_tanggungan_kata": textutil.rupiah_words(
                ctx["nilai_tanggungan"]),
        },
        "akad": {
            "jenis": _clean(ctx["akad_jenis"]),
            "nomor": _clean(ctx["akad_nomor"]),
            "tanggal": akad_tanggal_kata,
            "tanggal_singkat": _tanggal_ringkas(ctx["akad_tanggal"]),
        },
        "tanah": {
            "ht_jenis": _clean(ctx["ht_jenis"]),
            "ht_nomor": _clean(ctx["ht_nomor"]),
            "ht_desa_sertifikat": _clean(ctx["ht_desa_sertifikat"]),
            "surat_ukur_nomor": _clean(ctx["surat_ukur_nomor"]),
            "surat_ukur_tanggal": surat_ukur_kata + " ("
            + _tanggal_ringkas(ctx["surat_ukur_tanggal"]) + ")",
            "luas_m2": ctx["luas_raw"],
            "luas_kata": ctx["luas_kata"],
            "nib": _clean(ctx["nib"]),
            "nop": _clean(ctx["nop"]),
        },
        "lokasi": {
            "lok_provinsi": _clean(ctx["lok_provinsi"]),
            "lok_kabupaten": _clean(ctx["lok_kabupaten"]),
            "lok_kecamatan": _clean(ctx["lok_kecamatan"]),
            "lok_desa": _clean(ctx["lok_desa"]),
            "lok_jalan": _clean(ctx["lok_jalan"]),
        },
        "catatan": _summary_catatan(ctx),
    }


def _role_summary(ctx: dict, role: str) -> dict:
    alamat = (format_spouse_alamat(ctx) if role == "spouse"
              else format_residence(ctx, role))
    return {
        "nama": ctx[f"{role}_nama"],
        "sapaan": ctx[f"{role}_title"],
        "lahir_tempat": ctx[f"{role}_lahir_tempat"],
        "lahir_tanggal": _tanggal_panjang(ctx[f"{role}_lahir_tanggal"]),
        "pekerjaan": ctx[f"{role}_pekerjaan"],
        "nik": ctx[f"{role}_nik"],
        "alamat": alamat,
    }


def _summary_catatan(ctx: dict) -> list[str]:
    catatan = []
    if ctx["spouse_mode"] == "suami":
        catatan.append(
            "Pasangan adalah SUAMI pemilik; kalimat persetujuan serta label "
            "tanda tangan memakai frasa suami.")
    if ctx["spouse_alamat_sama"]:
        catatan.append(
            "Alamat pasangan disamakan dengan pemilik (\"bertempat tinggal "
            "sama dengan ... di atas\").")
    if ctx["same_as_owner"]:
        catatan.append(
            "Debitor SAMA dengan pemilik tanah; identitas debitor disalin dari "
            "pemilik.")
    return catatan


def _digestable(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def integrity_digest(ctx: dict) -> str:
    """Digest kanonik (SHA-256) atas seluruh data dinamis yang dirender.

    Dipakai agar persetujuan pengguna terikat pada data yang benar-benar
    divalidasi: server menghitung ulang digest dari payload dan menolak bila
    berbeda dengan digest yang disetujui (bukan sekadar checkbox).
    """
    payload = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "summary": canonical_summary(ctx),
        "markers": {k: ("" if v is None else str(v))
                    for k, v in sorted(build_marker_values(ctx).items())},
    }
    return hashlib.sha256(_digestable(payload).encode("utf-8")).hexdigest()
