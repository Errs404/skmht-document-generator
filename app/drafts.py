"""Draf lokal eksplisit: skema, validasi impor, dan pembuatan berkas.

Prinsip keamanan (sesuai keputusan pengguna):

- **Tidak ada penyimpanan otomatis.** Draf hanya dibuat saat pengguna
  menekan **Simpan Draf** dan hanya diunduh ke komputer pengguna. Server
  TIDAK menulis draf ke disk dan tidak memakai cookie/localStorage.
- **Tidak ada data yang dipulihkan otomatis.** Membuka draf selalu melalui
  impor berkas lokal yang dipilih pengguna.
- **Tidak pernah memuat gambar KTP, kunci API, atau teks OCR mentah.**
  Skema hanya menerima key formulir yang dikenal; kunci lain diabaikan.
- **Impor wajib ditinjau ulang.** Setiap nilai yang diimpor ditandai
  ``needs_review`` = True (server menghitung ulang; nilai dari berkas tidak
  dipercaya). Setelah pengguna mengonfirmasi tinjauan barulah nilai dianggap
  sudah ditinjau.
- **Gagal-keras & tanpa penimpaan sebagian.** Impor yang tidak valid
  (JSON rusak, versi skema tak dikenal, ukuran melebihi batas) ditolak
  sebagai satu kesatuan; formulir tidak diubah sebagian.
- **Privasi.** Draf disimpan **tanpa enkripsi**; pengguna mengelola sendiri
  berkas dan penghapusannya. Tidak ada klaim enkripsi/basis data/cloud.
"""

from __future__ import annotations

import json
import re

#: Penanda jenis berkas draf.
KIND = "skmht-draft"

#: Versi skema draf. Impor menerima versi yang dikenal ini saja.
SCHEMA_VERSION = 1

#: Batas ukuran berkas draf yang wajar (byte).
MAX_DRAFT_BYTES = 1 * 1024 * 1024  # 1 MiB

#: Batas panjang satu nilai teks pada draf (mencegah nilai raksasa).
MAX_VALUE_CHARS = 4000

#: Batas jumlah key yang diterima (jaring pengaman).
MAX_KEYS = 500

#: Pola key formulir yang boleh masuk draf (hanya key skema yang dikenal,
#: diverifikasi lebih lanjut terhadap ``fields.FIELD_KEYS``).
_SAFE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

#: Key yang DILARANG muncul pada draf apa pun alasannya.
_FORBIDDEN_SUBSTRINGS = (
    "image", "base64", "ktp_image", "api_key", "apikey", "authorization",
    "ocr", "raw_text", "rawtext", "secret", "token", "password",
)


class DraftError(ValueError):
    """Kesalahan draf yang aman ditampilkan ke pengguna."""


def _is_forbidden(key: str) -> bool:
    return any(part in key for part in _FORBIDDEN_SUBSTRINGS)


def sanitize_form_data(data) -> dict:
    """Kembalikan hanya key formulir yang dikenal & aman dari ``data``.

    - Hanya key yang ada pada ``fields.FIELD_KEYS`` (bila tersedia).
    - Menolak key yang mengandung penanda sensitif (gambar/kunci/OCR).
    - Nilai dipaksa menjadi string berbatas panjang; nilai non-string
      ditolak (kecuali None -> "").
    """
    from . import fields as _fields

    if not isinstance(data, dict):
        raise DraftError("Data draf harus berupa objek.")
    if len(data) > MAX_KEYS:
        raise DraftError("Terlalu banyak field pada draf.")

    out: dict[str, str] = {}
    for raw_key, raw_value in data.items():
        key = str(raw_key).strip()
        if not _SAFE_KEY_RE.match(key):
            continue  # key tidak aman -> abaikan (bukan key skema)
        if _is_forbidden(key):
            continue  # jangan pernah simpan penanda sensitif
        if key not in _fields.FIELD_KEYS:
            continue  # key tak dikenal -> abaikan
        if raw_value is None:
            out[key] = ""
            continue
        if not isinstance(raw_value, (str, int, float, bool)):
            continue  # tipe tak terduga -> abaikan
        text = str(raw_value)
        if len(text) > MAX_VALUE_CHARS:
            raise DraftError(
                f"Nilai field '{key}' terlalu panjang untuk sebuah draf.")
        out[key] = text
    return out


def build_draft(form_data, *, saved_at: str | None = None) -> dict:
    """Bangun objek draf tervalidasi (tanpa apa pun yang sensitif)."""
    cleaned = sanitize_form_data(form_data)
    draft = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "app": "generator-skmht",
        "data": cleaned,
    }
    if saved_at:
        draft["saved_at"] = str(saved_at)[:40]
    return draft


def draft_to_json(form_data, *, saved_at: str | None = None) -> bytes:
    """Serialisasi draf ke byte JSON (UTF-8, indentasi rapi)."""
    draft = build_draft(form_data, saved_at=saved_at)
    return json.dumps(draft, ensure_ascii=False, indent=2).encode("utf-8")


def parse_draft(raw) -> dict:
    """Urai & validasi byte/teks draf untuk impor (gagal-keras, satu kesatuan).

    Mengembalikan ``{"data": {key: str}, "saved_at": str|None,
    "schema_version": int}``.

    Menolak: ukuran melebihi batas, bukan JSON, bukan objek, penanda
    ``kind`` salah, versi skema tak dikenal, dan ``data`` yang bukan objek.
    """
    if isinstance(raw, (bytes, bytearray, memoryview)):
        raw_bytes = bytes(raw)
    elif isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raise DraftError("Isi draf tidak dapat dibaca.")

    if not raw_bytes.strip():
        raise DraftError("Berkas draf kosong.")
    if len(raw_bytes) > MAX_DRAFT_BYTES:
        mb = MAX_DRAFT_BYTES // (1024 * 1024)
        raise DraftError(f"Ukuran berkas draf melebihi batas {mb} MB.")

    try:
        obj = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DraftError(
            "Berkas draf bukan JSON yang valid. Pastikan berkas ini dibuat "
            "oleh aplikasi ini (menu \"Simpan Draf\").")

    if not isinstance(obj, dict):
        raise DraftError("Struktur berkas draf tidak dikenali.")

    if obj.get("kind") != KIND:
        raise DraftError(
            "Berkas ini bukan draf SKMHT yang dikenali oleh aplikasi.")

    version = obj.get("schema_version")
    if not isinstance(version, int) or version != SCHEMA_VERSION:
        raise DraftError(
            f"Versi skema draf tidak didukung (ditemukan: {version!r}, "
            f"didukung: {SCHEMA_VERSION}). Draf dari versi aplikasi lain "
            "ditolak agar data tidak salah tafsir.")

    data = obj.get("data")
    if not isinstance(data, dict):
        raise DraftError("Bagian data pada draf tidak valid.")

    cleaned = sanitize_form_data(data)
    saved_at = obj.get("saved_at")
    if saved_at is not None and not isinstance(saved_at, str):
        saved_at = None
    return {
        "data": cleaned,
        "saved_at": saved_at,
        "schema_version": version,
    }
