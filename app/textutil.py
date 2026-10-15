"""Utilitas teks Bahasa Indonesia untuk dokumen SKMHT.

Semua fungsi di modul ini murni (tanpa I/O) agar mudah diuji.
Acuan: penulisan tanggal & terbilang sesuai contoh pada dokumen asli.
"""

from __future__ import annotations

import datetime as _dt

# ---------------------------------------------------------------------------
# Tanggal
# ---------------------------------------------------------------------------

HARI = {
    0: "Senin",
    1: "Selasa",
    2: "Rabu",
    3: "Kamis",
    4: "Jumat",
    5: "Sabtu",
    6: "Minggu",
}

BULAN = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


class ValidationError(ValueError):
    """Kesalahan validasi masukan yang dapat ditampilkan ke pengguna."""


def parse_date(value: str) -> _dt.date:
    """Mengurai tanggal dengan format YYYY-MM-DD.

    Melempar ValidationError bila format salah atau tanggal tidak valid
    (mis. 31-11-1999).
    """
    if value is None:
        raise ValidationError("Tanggal wajib diisi.")
    text = str(value).strip()
    if not text:
        raise ValidationError("Tanggal wajib diisi.")
    try:
        return _dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(
            "Tanggal tidak valid. Gunakan format YYYY-MM-DD dan tanggal yang benar."
        )


def day_name(d: _dt.date) -> str:
    """Nama hari dalam Bahasa Indonesia."""
    return HARI[d.weekday()]


def day_word(n: int) -> str:
    """Angka hari (1-31) menjadi kata, mis. 31 -> 'tiga puluh satu'."""
    return terbilang(n)


def month_name(month: int) -> str:
    return BULAN[int(month)]


def year_words(year: int) -> str:
    """Tahun sebagai kata, mis. 2026 -> 'dua ribu dua puluh lima'."""
    return terbilang(int(year))


def format_tanggal_lengkap(d: _dt.date) -> str:
    """Tanggal lengkap bergaya dokumen asli.

    Contoh: 'Senin, tanggal 31 (tiga puluh satu) bulan Desember tahun 2026
    (dua ribu dua puluh lima)'.
    """
    return (
        f"{day_name(d)}, tanggal {d.day} ({day_word(d.day)}) "
        f"bulan {month_name(d.month)} tahun {d.year} ({year_words(d.year)})"
    )


def format_tanggal_singkat(d: _dt.date) -> str:
    """Tanggal 'DD-MM-YYYY' bergaya dokumen asli (mis. 29-12-2026)."""
    return f"{d.day:02d}-{d.month:02d}-{d.year:04d}"


def format_tanggal_kata(d: _dt.date) -> str:
    """Tanggal sebagai kata tanpa nama hari.

    Contoh: 'dua puluh sembilan Desember seribu sembilan ratus sembilan puluh
    empat' untuk meniru gaya 'dua puluh sembilan Desember dua ribu dua puluh
    empat'.
    """
    return f"{terbilang(d.day)} {month_name(d.month)} {terbilang(d.year)}"


# ---------------------------------------------------------------------------
# Terbilang
# ---------------------------------------------------------------------------

_SATUAN = [
    "",
    "satu",
    "dua",
    "tiga",
    "empat",
    "lima",
    "enam",
    "tujuh",
    "delapan",
    "sembilan",
    "sepuluh",
    "sebelas",
]


def _terbilang_kecil(n: int) -> str:
    """Terbilang untuk 0..999."""
    if n < 0:
        raise ValueError("terbilang tidak mendukung bilangan negatif")
    if n < 12:
        return _SATUAN[n] if n > 0 else ""
    if n < 20:
        return f"{_SATUAN[n - 10]} belas".strip()
    if n < 100:
        puluhan = n // 10
        sisa = n % 10
        bagian = f"{_SATUAN[puluhan]} puluh"
        if sisa:
            bagian += f" {_SATUAN[sisa]}"
        return bagian
    if n < 200:
        ratusan = "seratus"
    else:
        ratusan = f"{_SATUAN[n // 100]} ratus"
    sisa = n % 100
    if sisa:
        return f"{ratusan} {_terbilang_kecil(sisa)}"
    return ratusan


def terbilang(n: int) -> str:
    """Bilangan bulat menjadi kata Bahasa Indonesia.

    Contoh: 153 -> 'seratus lima puluh tiga', 1153 -> 'seribu seratus lima
    puluh tiga', 2026 -> 'dua ribu dua puluh lima', 50000000 -> 'lima puluh
    juta', 75000000 -> 'tujuh puluh lima juta'.
    """
    n = int(n)
    if n == 0:
        return "nol"
    if n < 0:
        return "minus " + terbilang(-n)

    bagian = []
    triliun = n // 1_000_000_000_000
    n %= 1_000_000_000_000
    miliar = n // 1_000_000_000
    n %= 1_000_000_000
    juta = n // 1_000_000
    n %= 1_000_000
    ribu = n // 1_000
    n %= 1_000
    sisa = n

    if triliun:
        bagian.append(f"{terbilang(triliun)} triliun")
    if miliar:
        bagian.append(f"{terbilang(miliar)} miliar")
    if juta:
        bagian.append(f"{terbilang(juta)} juta")
    if ribu:
        if ribu == 1:
            bagian.append("seribu")
        else:
            bagian.append(f"{_terbilang_kecil(ribu)} ribu")
    if sisa:
        bagian.append(_terbilang_kecil(sisa))

    return " ".join(bagian)


# ---------------------------------------------------------------------------
# Uang
# ---------------------------------------------------------------------------

def format_rupiah(amount: int) -> str:
    """Format ribuan dengan titik, tanpa simbol. 50000000 -> '50.000.000'."""
    amount = int(amount)
    if amount < 0:
        raise ValidationError("Nilai uang tidak boleh negatif.")
    return f"{amount:,}".replace(",", ".")


def parse_amount(value: str) -> int:
    """Mengurai masukan uang pengguna.

    Menerima '50.000.000', '50000000', '50 000 000', 'Rp 50.000.000'.
    Melempar ValidationError bila bukan bilangan bulat non-negatif.
    """
    if value is None:
        raise ValidationError("Nilai uang wajib diisi.")
    text = str(value).strip()
    if not text:
        raise ValidationError("Nilai uang wajib diisi.")
    cleaned = (
        text.lower()
        .replace("rp", "")
        .replace(".", "")
        .replace(",", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    if not cleaned.isdigit():
        raise ValidationError("Nilai uang harus berupa angka (mis. 50.000.000).")
    amount = int(cleaned)
    if amount <= 0:
        raise ValidationError("Nilai uang harus lebih besar dari nol.")
    if amount > 999_999_999_999_999:
        raise ValidationError("Nilai uang terlalu besar.")
    return amount


def rupiah_words(amount: int) -> str:
    """Terbilang rupiah. 50000000 -> 'lima puluh juta rupiah'."""
    return f"{terbilang(int(amount))} rupiah"


# ---------------------------------------------------------------------------
# NIK
# ---------------------------------------------------------------------------

def validate_nik(value: str, label: str = "NIK") -> str:
    """Memvalidasi NIK: tepat 16 digit angka.

    Mengembalikan string digit (tanpa spasi). Tidak mengubah menjadi angka
    agar nol di depan tidak hilang.
    """
    if value is None:
        raise ValidationError(f"{label} wajib diisi.")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{label} wajib diisi.")
    if not text.isdigit():
        raise ValidationError(f"{label} harus berupa 16 digit angka.")
    if len(text) != 16:
        raise ValidationError(
            f"{label} harus tepat 16 digit (saat ini {len(text)} digit)."
        )
    return text
