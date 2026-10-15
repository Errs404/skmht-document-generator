"""Server HTTP lokal (Standard Library) untuk generator SKMHT.

Keamanan & batasan:
- Hanya bind ke 127.0.0.1 (localhost).
- Tidak ada logging payload / data pribadi.
- Dokumen & draf hanya dirakit di memori; server TIDAK menyimpan apa pun.
- Persetujuan akhir terikat pada digest data (bukan sekadar checkbox).
- Batas ukuran request.
- Escaping HTML untuk semua keluaran.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

from . import ai_ocr, docx_template, drafts, fields, ktp_ocr
from .textutil import ValidationError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Template produksi: berkas contoh berbasis MARKER {{key}} (sintetis). Berkas
# dibangun oleh tools/build_synthetic_template.py (Standard Library saja).
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "SKMHT.example.template.docx")

HOST = "127.0.0.1"
DEFAULT_PORT = 8756

MAX_BODY_BYTES = 512 * 1024          # batas ukuran payload formulir/draf
# Batas payload OCR lebih besar karena memuat gambar ter-encode base64
# (base64 ~33% lebih besar dari berkas; beri margin aman).
MAX_OCR_BODY_BYTES = 20 * 1024 * 1024
MAX_CONCURRENT = 4                    # cap permintaan bersamaan
_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT)
_ocr_semaphore = threading.BoundedSemaphore(2)  # OCR berat; batasi paralel

VALID_OCR_ROLES = ("owner", "spouse", "debtor")
VALID_OCR_MODES = ("local", "ai")

#: Masa berlaku tiket persetujuan akhir (detik). Cukup untuk satu kali klik
#: setujui lalu buat dokumen; bukan sesi yang bertahan lama.
_ACK_TTL_SECONDS = 3600

#: Batas tinjauan ulang (stateless): draft hash dianggap basi setelah ini.
_REVIEW_TTL_SECONDS = 24 * 3600

#: Label manusiawi untuk daftar field yang perlu ditinjau ulang.
_REVIEW_FIELD_LABELS = {
    "owner_nama": "Nama pemilik", "owner_nik": "NIK pemilik",
    "owner_lahir_tempat": "Tempat lahir pemilik",
    "owner_lahir_tanggal": "Tanggal lahir pemilik",
    "owner_pekerjaan": "Pekerjaan pemilik",
    "owner_dusun": "Dusun pemilik", "owner_rt": "RT pemilik",
    "owner_rw": "RW pemilik", "owner_desa": "Desa pemilik",
    "owner_kecamatan": "Kecamatan pemilik",
    "owner_kabupaten": "Kabupaten pemilik",
    "spouse_nama": "Nama pasangan", "spouse_nik": "NIK pasangan",
    "spouse_lahir_tempat": "Tempat lahir pasangan",
    "spouse_lahir_tanggal": "Tanggal lahir pasangan",
    "spouse_pekerjaan": "Pekerjaan pasangan",
    "spouse_dusun": "Dusun pasangan", "spouse_rt": "RT pasangan",
    "spouse_rw": "RW pasangan", "spouse_desa": "Desa pasangan",
    "spouse_kecamatan": "Kecamatan pasangan",
    "spouse_kabupaten": "Kabupaten pasangan",
    "debtor_nama": "Nama debitor", "debtor_nik": "NIK debitor",
    "debtor_lahir_tempat": "Tempat lahir debitor",
    "debtor_lahir_tanggal": "Tanggal lahir debitor",
    "debtor_pekerjaan": "Pekerjaan debitor",
    "debtor_dusun": "Dusun debitor", "debtor_rt": "RT debitor",
    "debtor_rw": "RW debitor", "debtor_desa": "Desa debitor",
    "debtor_kecamatan": "Kecamatan debitor",
    "debtor_kabupaten": "Kabupaten debitor",
    "dusun": "Dusun", "rt": "RT", "rw": "RW", "desa": "Kel/Desa",
    "kecamatan": "Kecamatan", "kabupaten": "Kabupaten",
    "provinsi": "Provinsi",
}


def _load_template() -> bytes:
    with open(TEMPLATE_PATH, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Tiket persetujuan akhir (stateless HMAC) + kunci pribadi proses
# ---------------------------------------------------------------------------

#: Kunci pribadi proses. Dibuat saat server mulai dan TIDAK pernah dikirim ke
#: klien. Digunakan untuk menandatangani konfirmasi ringkasan & tiket akhir,
#: sehingga tiket hanya sah untuk kunci ini (dipegang server, di luar kendali
#: browser). Ini BUKAN autentikasi: hanya pengikat integritas alur sekali-pakai.
_SERVER_KEY = os.urandom(32)


def _sign(payload: str) -> str:
    return hmac.new(_SERVER_KEY, payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _make_ack_token(digest: str, ts: int) -> str:
    return f"{digest}.{ts}.{_sign(f'{digest}.{ts}')}"


def _verify_ack_token(token: str, digest: str, now: int | None = None) -> bool:
    if not isinstance(token, str):
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    token_digest, ts_raw, sig = parts
    try:
        ts = int(ts_raw)
    except ValueError:
        return False
    now = int(time.time()) if now is None else now
    if ts > now + 60 or now - ts > _ACK_TTL_SECONDS:
        return False
    if not hmac.compare_digest(token_digest, digest):
        return False
    expected = _sign(f"{token_digest}.{ts}")
    return hmac.compare_digest(sig, expected)


def _form_fingerprint(data: dict) -> str:
    """Sidik jari data formulir (mengabaikan metadata alur/tinjauan).

    Key internal (``_``-prefixed), ``confirm_summary``, ``ack_*``, dan
    ``summary_signature`` TIDAK ikut dihitung: itu metadata alur, bukan data.
    Dengan begitu ``_review_digest`` dapat dibandingkan langsung dengan sidik
    jari formulir tanpa saling terkunci (fingerprint tidak berubah hanya karena
    status tinjauan ikut berubah).
    """
    cleaned = {}
    if isinstance(data, dict):
        for key, value in data.items():
            name = str(key)
            if name.startswith("_") or name in (
                    "confirm_summary", "ack_token", "ack_digest",
                    "summary_signature"):
                continue
            cleaned[name] = value
    payload = json.dumps(cleaned, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Review (tinjauan) server-otoritatif, stateless
# ---------------------------------------------------------------------------

def _review_status(data: dict) -> dict:
    """Hitung status tinjauan dari ``_reviewed`` & ``_review_digest``.

    Kontrak (dihitung ULANG di server, tidak memercayai boolean mentah):

    - ``_reviewed`` tidak benar -> belum ditinjau; dokumen DITOLAK.
    - ``_review_digest`` berbeda dari digest formulir sekarang -> DRIFT:
      formulir sudah berubah setelah tinjauan; wajib ditinjau ulang.
    - Cap waktu tinjauan kedaluwarsa -> wajib tinjau ulang.

    Sejak aplikasi ini tidak memakai state sesi persisten, DIGEST formulir
    saat ini adalah nilai ulasan tunggal ("one digest to rule them all"):
    mengedit field apa pun setelah menekan "Tinjau" akan mengubah digest dan
    otomatis membatalkan ulasan.
    """
    now = int(time.time())
    fingerprint = _form_fingerprint(data)

    if data.get("_reviewed") is not True:
        return {"state": "unreviewed", "reviewed": False, "drift": False,
                "stale": False, "fingerprint": fingerprint,
                "reason": "Formulir belum ditinjau. Tekan \"Tinjau & Kunci "
                          "Data\" sebelum membuat dokumen."}

    if data.get("_review_digest") != fingerprint:
        return {"state": "changed", "reviewed": False, "drift": True,
                "stale": False, "fingerprint": fingerprint,
                "reason": "Formulir berubah setelah ditinjau. Tekan \"Tinjau & "
                          "Kunci Data\" lagi untuk meninjau versi terbaru."}

    ts = data.get("_review_ts")
    if not isinstance(ts, int) or ts <= 0:
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            ts = 0
    if ts <= 0 or now - ts > _REVIEW_TTL_SECONDS:
        return {"state": "stale", "reviewed": False, "drift": False,
                "stale": True, "fingerprint": fingerprint,
                "reason": "Tinjauan sudah lama tidak diperbarui. Tekan "
                          "\"Tinjau & Kunci Data\" lagi."}

    return {"state": "reviewed", "reviewed": True, "drift": False,
            "stale": False, "fingerprint": fingerprint, "reason": None}


def _summarize_review_data(data: dict) -> dict:
    """Rangkum nilai OCR yang perlu ditinjau (untuk validasi & respons)."""
    if not isinstance(data, dict):
        return {"needs_review": [], "needs_review_labels": [],
                "reviewed_count": 0, "reviewing": False}
    items = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if value is None or str(value).strip() == "":
            continue
        items[str(key)] = {
            "value": str(value),
            "needs_review": bool(entry.get("needs_review", True)),
            "confirmed": entry.get("confirmed") is True,
        }
    needs = sorted([k for k, e in items.items()
                    if e["needs_review"] and not e["confirmed"]])
    labels = [_REVIEW_FIELD_LABELS.get(k, k) for k in needs]
    return {
        "needs_review": needs,
        "needs_review_labels": labels,
        "reviewed_count": sum(1 for e in items.values() if e["confirmed"]),
        "reviewing": bool(items),
    }


def _canonical(data: dict) -> tuple[dict, str]:
    """Validasi payload -> (ctx, ringkasan kanonik). Gagal-keras bila OCR
    belum dikonfirmasi atau ada nilai identitas masih ditandai butuh tinjauan.
    """
    review = _summarize_review_data(data.get("_review_data"))
    if review["needs_review"]:
        raise ValidationError(
            "Sebagian data berasal dari OCR dan belum dikonfirmasi: "
            + ", ".join(review["needs_review_labels"])
            + ". Konfirmasi tiap baris sebelum membuat dokumen.")
    ctx = fields.validate_and_build(_strip_internals(data))
    return ctx, fields.canonical_summary(ctx)


def _strip_internals(data: dict) -> dict:
    """Buang key internal (``_...``) agar tidak mengganggu validasi skema."""
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


def _review_provenance(data: dict) -> dict:
    """Ringkasan asal-usul nilai (impor & OCR) untuk pesan tinjauan."""
    src = data.get("_draft_source")
    imported = data.get("_imported") is True
    review = _summarize_review_data(data.get("_review_data"))
    return {
        "imported": imported,
        "draft_source": src if isinstance(src, str) else None,
        "ocr_confirmed": review["reviewed_count"],
        "ocr_pending": review["needs_review_labels"],
    }


def _render(data: dict) -> bytes:
    ctx = fields.validate_and_build(_strip_internals(data))
    values = fields.build_marker_values(ctx)
    ledger = docx_template.ledger_of(_load_template())
    known = set(values)
    unknown = sorted(set(ledger) - known)
    if unknown:
        raise docx_template.TemplateAlteredError(
            "Marker tak dikenal pada template: " + ", ".join(unknown))
    template = _load_template()
    return docx_template.render_docx_from_template(
        template, values,
        required_keys=fields.REQUIRED_MARKER_KEYS,
        removal_keys=fields.REMOVAL_MARKER_KEYS)


def _template_missing_markers() -> list[str]:
    """Marker ``{{...}}`` yang ada pada template tetapi tidak punya nilai."""
    ctx = fields.validate_and_build(_demo_form())
    values = fields.build_marker_values(ctx)
    ledger = docx_template.ledger_of(_load_template())
    return sorted(set(ledger) - set(values))


def _template_status() -> dict:
    """Status template produksi untuk UI (tanpa data pribadi)."""
    try:
        template = _load_template()
    except OSError:
        return {
            "ok": True, "available": False, "path": "templates/"
            "SKMHT.example.template.docx",
            "reason": "Template berbasis marker tidak ditemukan. Jalankan "
                      "tools/build_synthetic_template.py untuk membuatnya.",
            "hint": "python tools/build_synthetic_template.py",
        }
    try:
        ledger = docx_template.ledger_of(template)
    except docx_template.DocxTemplateError as exc:
        return {"ok": True, "available": False,
                "path": "templates/SKMHT.example.template.docx",
                "reason": "Template tidak dapat dibaca: " + str(exc)}
    ctx = fields.validate_and_build(_demo_form())
    values = fields.build_marker_values(ctx)
    missing = sorted(set(ledger) - set(values))
    missing_required = sorted(set(fields.REQUIRED_MARKER_KEYS) - set(ledger))
    return {
        "ok": True,
        "available": not missing and not missing_required,
        "path": "templates/SKMHT.example.template.docx",
        "marker_count": sum(ledger.values()),
        "markers": sorted(ledger),
        "unbound_markers": missing,
        "missing_required": missing_required,
        "reason": None if not (missing or missing_required) else
                  "Template tidak sesuai harapan (marker tidak sinkron).",
    }


def _demo_form() -> dict:
    """Formulir sintetis minimal (BUKAN data nyata) untuk validasi template."""
    return {
        "nomor_akta": "1/ 2026", "tanggal_akta": "2026-01-01",
        "owner_title": "Tuan", "owner_nama": "N", "owner_lahir_tempat": "M",
        "owner_lahir_tanggal": "1990-01-01", "owner_pekerjaan": "P",
        "owner_dusun": "D", "owner_rt": "1", "owner_rw": "1",
        "owner_desa": "D", "owner_kecamatan": "K", "owner_kabupaten": "",
        "owner_nik": "9999999999990001",
        "spouse_mode": "istri", "spouse_nama": "N", "spouse_lahir_tempat": "M",
        "spouse_lahir_tanggal": "1990-01-01", "spouse_pekerjaan": "P",
        "spouse_alamat_sama": "ya", "spouse_dusun": "", "spouse_rt": "",
        "spouse_rw": "", "spouse_desa": "", "spouse_kecamatan": "",
        "spouse_kabupaten": "", "spouse_nik": "9999999999990002",
        "same_as_owner": "ya", "debtor_title": "Tuan", "debtor_nama": "N",
        "debtor_lahir_tempat": "M", "debtor_lahir_tanggal": "1990-01-01",
        "debtor_pekerjaan": "P", "debtor_dusun": "D", "debtor_rt": "1",
        "debtor_rw": "1", "debtor_desa": "D", "debtor_kecamatan": "K",
        "debtor_kabupaten": "", "debtor_nik": "9999999999990003",
        "nilai_pembiayaan": "1.000.000", "nilai_tanggungan": "2.000.000",
        "akad_jenis": "Hawalah bil ujrah", "akad_nomor": "1/X",
        "akad_tanggal": "2026-01-01", "ht_jenis": "Hak Milik",
        "ht_nomor": "1", "ht_desa_sertifikat": "D",
        "surat_ukur_nomor": "1/D", "surat_ukur_tanggal": "2026-01-01",
        "luas_m2": "100", "nib": "1", "nop": "1",
        "lok_provinsi": "P", "lok_kabupaten": "K", "lok_kecamatan": "K",
        "lok_desa": "D", "lok_jalan": "J",
    }


def _safe_filename(ctx: dict) -> str:
    nama = ctx.get("owner_nama", "SKMHT").strip() or "SKMHT"
    nama = "".join(c for c in nama if c.isalnum() or c in " -_").strip()
    nama = nama.replace(" ", "_") or "SKMHT"
    return f"SKMHT_{nama}.docx"


def _safe_draft_filename(ctx: dict) -> str:
    base = _safe_filename(ctx)
    return base[:-len(".docx")] + ".draft.json" if base.endswith(".docx") \
        else base + ".draft.json"



class Handler(BaseHTTPRequestHandler):
    server_version = "SKMHTLocal/1.0"

    # --- Matikan logging default yang berpotensi memuat data sensitif. ---
    def log_message(self, fmt, *args):  # noqa: A003
        # Sengaja tanpa menulis detail request/klien.
        return

    # ------------------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str,
              extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:",
        )
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    # ------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode("utf-8"),
                       "text/html; charset=utf-8")
        elif self.path == "/app.css":
            self._send(200, APP_CSS.encode("utf-8"),
                       "text/css; charset=utf-8")
        elif self.path == "/app.js":
            self._send(200, APP_JS.encode("utf-8"),
                       "application/javascript; charset=utf-8")
        elif self.path == "/api/fields":
            self._send_json(200, {"fields": [
                {"key": k, "label": lbl, "kind": kind, "required": req}
                for (k, lbl, kind, req) in fields.FIELDS
            ]})
        elif self.path == "/api/template/status":
            self._send_json(200, _template_status())
        elif self.path == "/healthz":
            self._send_json(200, {"ok": True})
        elif self.path == "/api/ocr/status":
            # Status mesin OCR lokal (Tesseract) + mode AI daring. Tidak ada
            # data pribadi dan TIDAK ada panggilan jaringan berbayar di sini:
            # status AI hanya melaporkan konfigurasi, bukan kapabilitas model.
            status = ktp_ocr.engine_status()
            status["max_image_bytes"] = ktp_ocr.MAX_IMAGE_BYTES
            status["roles"] = list(VALID_OCR_ROLES)
            status["modes"] = list(VALID_OCR_MODES)
            ai = ai_ocr.status()
            status["ai"] = ai
            self._send_json(200, status)
        else:
            self._send(404, b"Not Found", "text/plain; charset=utf-8")

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    # ------------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        if self.path == "/api/ocr/ktp":
            self._handle_ocr()
            return
        if self.path == "/api/ocr/ai":
            self._handle_ocr_ai()
            return
        if self.path == "/api/review":
            self._handle_review()
            return
        if self.path == "/api/draft/save":
            self._handle_draft_save()
            return
        if self.path == "/api/draft/import":
            self._handle_draft_import()
            return
        if self.path != "/api/generate":
            self._send_json(404, {"ok": False, "error": "Endpoint tidak ada."})
            return

        length = self.headers.get("Content-Length", "0")
        try:
            length = int(length)
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Header tidak valid."})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {
                "ok": False,
                "error": "Ukuran formulir tidak wajar atau kosong.",
            })
            return

        if not _semaphore.acquire(blocking=False):
            self._send_json(429, {
                "ok": False,
                "error": "Server sibuk, silakan coba lagi sesaat.",
            })
            return
        try:
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {
                    "ok": False, "error": "Format data tidak valid."})
                return
            if not isinstance(data, dict):
                self._send_json(400, {
                    "ok": False, "error": "Format data tidak valid."})
                return

            self._handle_generate(data)
        finally:
            _semaphore.release()

    # ------------------------------------------------------------------
    def _handle_generate(self, data: dict):
        """Endpoint pembuatan dokumen (dengan gerbang tinjauan & integritas).

        Kontrak payload:

        - seluruh key formulir (lihat ``/api/fields``);
        - ``_reviewed`` (bool) + ``_review_digest`` + ``_review_ts``: status
          tinjauan (dihitung ulang server; digest harus sama dengan formulir);
        - ``_review_data``: status OCR per-field (agar data OCR tak
          terkonfirmasi memblokir pembuatan);
        - ``confirm_summary``, ``summary_signature``, ``ack_token``,
          ``ack_digest``: persetujuan akhir atas ringkasan kanonik.
        """
        # 1) Gerbang tinjauan (server-otoritatif).
        status = _review_status(data)
        if not status["reviewed"]:
            self._send_json(422, {
                "ok": False,
                "error": status["reason"] or "Formulir belum ditinjau.",
                "review_state": status["state"],
                "review_drift": status["drift"],
                "review_stale": status["stale"],
            })
            return

        try:
            ctx, summary = _canonical(data)
        except ValidationError as exc:
            self._send_json(422, {
                "ok": False, "error": str(exc),
                "review_state": "reviewed",
            })
            return

        # 2) Persetujuan akhir terikat DIGEST (bukan checkbox semata).
        digest = fields.integrity_digest(ctx)
        ack_digest = data.get("ack_digest")
        ack_token = data.get("ack_token")
        if ack_digest != digest or not _verify_ack_token(ack_token, digest):
            self._send_json(409, {
                "ok": False,
                "error": "Persetujuan akhir tidak cocok dengan data formulir. "
                         "Tinjau ringkasan terbaru lalu setujui kembali.",
                "summary": summary,
                "digest": digest,
            })
            return
        if data.get("confirm_summary") is not True:
            self._send_json(422, {
                "ok": False,
                "error": "Centang pernyataan persetujuan sebelum membuat "
                         "dokumen.",
                "summary": summary,
            })
            return

        # 3) Render dokumen dari template khusus (gagal-keras pada template).
        try:
            template = _load_template()
        except OSError:
            self._send_json(500, {
                "ok": False,
                "error": "Template SKMHT tidak ditemukan. Jalankan "
                         "\"python tools/build_synthetic_template.py\" untuk "
                         "membuatnya, lalu coba lagi."})
            return
        try:
            values = fields.build_marker_values(ctx)
            unknown = sorted(set(docx_template.ledger_of(template)) - set(values))
            if unknown:
                raise docx_template.TemplateAlteredError(
                    "Marker tak dikenal pada template: " + ", ".join(unknown))
            docx = docx_template.render_docx_from_template(
                template, values,
                required_keys=fields.REQUIRED_MARKER_KEYS,
                removal_keys=fields.REMOVAL_MARKER_KEYS)
        except docx_template.MissingMarkerError as exc:
            self._send_json(500, {
                "ok": False,
                "error": "Template tidak lengkap sehingga dokumen dibatalkan "
                         "demi keamanan data: " + str(exc)})
            return
        except docx_template.TemplateAlteredError as exc:
            self._send_json(500, {
                "ok": False,
                "error": "Template berubah/tidak sesuai harapan sehingga "
                         "dokumen dibatalkan: " + str(exc)})
            return
        except docx_template.DocxTemplateError:
            self._send_json(500, {
                "ok": False,
                "error": "Gagal menyusun dokumen dari template."})
            return

        filename = _safe_filename(ctx)
        self._send(
            200, docx,
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
            {
                "Content-Disposition":
                    f"attachment; filename=\"{filename}\"; "
                    f"filename*=UTF-8''{quote(filename)}",
            },
        )

    # ------------------------------------------------------------------
    def _read_json_body(self, limit: int):
        """Baca body JSON (dict) dengan batas ukuran. None bila galat dikirim."""
        length = self.headers.get("Content-Length", "0")
        try:
            length = int(length)
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Header tidak valid."})
            return None
        if length <= 0 or length > limit:
            self._send_json(413, {
                "ok": False,
                "error": "Ukuran permintaan tidak wajar atau kosong."})
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {
                "ok": False, "error": "Format data tidak valid."})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {
                "ok": False, "error": "Format data tidak valid."})
            return None
        return data

    def _ack_signature(self, digest: str) -> str:
        """Tanda tangan ringkasan (HMAC) yang harus di-echo saat generate."""
        return hmac.new(_SERVER_KEY, ("summary:" + digest).encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def _handle_review(self):
        """Endpoint ringkasan kanonik & status tinjauan (sumber untuk UI).

        Ringkasan DIHITUNG server dari data tervalidasi sehingga yang dilihat
        pengguna, yang disetujui, dan yang dirender selalu identik.
        """
        data = self._read_json_body(MAX_BODY_BYTES)
        if data is None:
            return

        review = _summarize_review_data(data.get("_review_data"))
        status = _review_status(data)
        try:
            ctx = fields.validate_and_build(_strip_internals(data))
            summary = fields.canonical_summary(ctx)
            digest = fields.integrity_digest(ctx)
            valid, error = True, None
        except ValidationError as exc:
            summary, digest, valid, error = None, None, False, str(exc)

        self._send_json(200, {
            "ok": True,
            "valid": valid,
            "error": error,
            "summary": summary,
            "digest": digest,
            "ack_token": (_make_ack_token(digest, int(time.time()))
                          if digest else None),
            "summary_signature": (self._ack_signature(digest) if digest
                                  else None),
            "review": {
                "state": status["state"],
                "reviewed": status["reviewed"],
                "drift": status["drift"],
                "stale": status["stale"],
                "reason": status["reason"],
                "fingerprint": status["fingerprint"],
            },
            "ocr": review,
            "provenance": _review_provenance(data),
        })

    def _handle_draft_save(self):
        """Hasilkan berkas draf JSON lokal (tanpa penyimpanan server).

        Isi draf HANYA key formulir yang dikenal; gambar KTP, kunci API, dan
        teks OCR mentah **tidak pernah** dimasukkan.
        """
        data = self._read_json_body(MAX_BODY_BYTES)
        if data is None:
            return

        draft_data = {k: v for k, v in _strip_internals(data).items()
                      if not str(k).startswith("_")}
        try:
            blob = drafts.draft_to_json(draft_data)
        except drafts.DraftError as exc:
            self._send_json(422, {"ok": False, "error": str(exc)})
            return

        try:
            ctx = fields.validate_and_build(draft_data)
            fname = _safe_draft_filename(ctx)
        except ValidationError:
            fname = "SKMHT.draft.json"

        self._send(
            200, blob, "application/json; charset=utf-8",
            {"Content-Disposition":
                f"attachment; filename=\"{fname}\"; "
                f"filename*=UTF-8''{quote(fname)}"})

    def _handle_draft_import(self):
        """Impor draf JSON lokal dengan validasi skema/versi/ukuran.

        Gagal-keras sebagai satu kesatuan: bila berkas tidak valid, TIDAK ada
        satu pun field formulir yang diisi (mencegah timpa sebagian). Setiap
        nilai yang diimpor ditandai ``needs_review`` agar harus ditinjau ulang.
        """
        data = self._read_json_body(drafts.MAX_DRAFT_BYTES + 4096)
        if data is None:
            return

        content = data.get("content")
        if content is None:
            self._send_json(422, {
                "ok": False,
                "error": "Berkas draf tidak disertakan."})
            return

        try:
            parsed = drafts.parse_draft(content)
        except drafts.DraftError as exc:
            self._send_json(422, {"ok": False, "error": str(exc)})
            return

        review_data = {
            key: {"value": value, "needs_review": True, "confirmed": False}
            for key, value in parsed["data"].items() if str(value).strip()
        }
        self._send_json(200, {
            "ok": True,
            "data": parsed["data"],
            "saved_at": parsed["saved_at"],
            "schema_version": parsed["schema_version"],
            "review_data": review_data,
            "needs_review": sorted(review_data),
            "message": ("Draf dimuat. Semua nilai dari draf WAJIB ditinjau "
                        "ulang; konfirmasi tiap kolom bertanda tinjau sebelum "
                        "membuat dokumen."),
        })

    def _read_ocr_request(self):
        """Baca & validasi payload OCR bersama untuk kedua mode.
        Mengembalikan tuple ``(data, role, image_bytes)`` atau ``None`` bila
        respons galat sudah dikirim. Menangani batas ukuran, JSON, peran, dan
        decode base64 gambar dengan aturan identik untuk mode lokal/AI.
        """
        length = self.headers.get("Content-Length", "0")
        try:
            length = int(length)
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Header tidak valid."})
            return None
        if length <= 0 or length > MAX_OCR_BODY_BYTES:
            self._send_json(413, {
                "ok": False,
                "error": "Ukuran unggahan tidak wajar atau kosong.",
            })
            return None

        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {
                "ok": False, "error": "Format data tidak valid."})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {
                "ok": False, "error": "Format data tidak valid."})
            return None

        role = str(data.get("role", "")).strip().lower()
        if role not in VALID_OCR_ROLES:
            self._send_json(422, {
                "ok": False,
                "error": "Peran harus salah satu dari: pemilik, pasangan, "
                         "atau debitor."})
            return None

        image_b64 = data.get("image_base64") or data.get("image") or ""
        if not isinstance(image_b64, str) or not image_b64.strip():
            self._send_json(422, {
                "ok": False, "error": "Gambar tidak disertakan."})
            return None
        # Buang awalan data URL bila ada (mis. "data:image/png;base64,").
        if "," in image_b64[:64] and image_b64.lstrip().startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        try:
            image_bytes = base64.b64decode(image_b64, validate=True)
        except (binascii.Error, ValueError):
            self._send_json(422, {
                "ok": False,
                "error": "Gambar tidak dapat dibaca (base64 tidak valid)."})
            return None
        return data, role, image_bytes

    def _ocr_result_payload(self, result: dict, role: str) -> dict:
        """Bentuk payload respons dari hasil OCR (dipakai kedua mode)."""
        parsed = ktp_ocr.parse_ktp_fields(result["text"])
        candidates = ktp_ocr.candidates_for_role(parsed, role)
        fields_out = {
            key: {"value": info["value"], "status": info["status"]}
            for key, info in parsed["fields"].items()
        }
        payload = {
            "ok": True,
            "role": role,
            "engine": result["engine"],
            "language": result["language"],
            "image_type": result["image_type"],
            "fields": fields_out,
            "candidates": candidates,
            "raw_text": result["text"],
        }
        if result.get("model"):
            payload["model"] = result["model"]
        return payload

    def _handle_ocr(self):
        """Endpoint OCR KTP **lokal**: gambar tidak pernah diunggah ke internet.

        Kontrak: ``{"role": "owner"|"spouse"|"debtor", "image_base64": "..."}``
        (atau ``image`` sebagai alias). Gambar hanya diproses di memori/berkas
        sementara dan TIDAK disimpan. Teks OCR tidak dipersistensi.
        """
        if not _ocr_semaphore.acquire(blocking=False):
            self._send_json(429, {
                "ok": False,
                "error": "Server sedang memproses OCR lain, coba lagi sesaat.",
            })
            return
        try:
            parsed_req = self._read_ocr_request()
            if parsed_req is None:
                return
            _data, role, image_bytes = parsed_req

            try:
                result = ktp_ocr.ocr_image(image_bytes)
            except ktp_ocr.OcrError as exc:
                # Pesan sudah aman dibaca (tanpa path privat/stack).
                self._send_json(422, {"ok": False, "error": str(exc)})
                return

            self._send_json(200, self._ocr_result_payload(result, role))
        finally:
            _ocr_semaphore.release()

    def _handle_ocr_ai(self):
        """Endpoint OCR KTP **AI daring** (opt-in per permintaan).

        Kontrak: ``{"role": ..., "image_base64": ..., "consent": true}``.
        ``consent`` WAJIB bernilai benar; tanpa itu permintaan ditolak (422)
        dan **tidak ada** gambar yang dikirim ke penyedia. Tidak ada fallback
        otomatis: mode lokal tidak pernah memanggil endpoint ini.
        """
        if not _ocr_semaphore.acquire(blocking=False):
            self._send_json(429, {
                "ok": False,
                "error": "Server sedang memproses OCR lain, coba lagi sesaat.",
            })
            return
        try:
            parsed_req = self._read_ocr_request()
            if parsed_req is None:
                return
            data, role, image_bytes = parsed_req

            # Persetujuan eksplisit per permintaan (boolean sebenarnya).
            consent = data.get("consent") is True
            if not consent:
                self._send_json(422, {
                    "ok": False,
                    "error": "Persetujuan eksplisit diperlukan sebelum "
                             "mengirim gambar KTP ke penyedia AI."})
                return

            try:
                result = ai_ocr.ocr_image_ai(image_bytes, consent=True)
            except ai_ocr.ConsentRequired as exc:
                self._send_json(422, {"ok": False, "error": str(exc)})
                return
            except ai_ocr.AiOcrError as exc:
                # Pesan sudah aman (tanpa isi balasan mentah/header/kunci).
                self._send_json(422, {"ok": False, "error": str(exc)})
                return

            payload = self._ocr_result_payload(result, role)
            payload["provider"] = ai_ocr.status()["base_url_host"]
            self._send_json(200, payload)
        finally:
            _ocr_semaphore.release()


def serve(port: int = DEFAULT_PORT) -> None:
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print("=" * 60)
    print(" Generator SKMHT (lokal) berjalan.")
    print(f" Buka di browser: {url}")
    print(" Tekan Ctrl+C untuk berhenti.")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nMenghentikan server...")
    finally:
        httpd.server_close()


# ---------------------------------------------------------------------------
# Aset UI (di-escape/tanpa CDN, disimpan inline agar tanpa file terpisah)
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Generator SKMHT (Lokal)</title>
<link rel="stylesheet" href="app.css">
</head>
<body>
<header class="topbar">
  <div class="brand">
    <span class="dot"></span>
    <h1>Generator SKMHT</h1>
  </div>
  <span class="tag">Lokal &middot; Offline</span>
</header>

<main>
  <section class="notice">
    <strong>Perhatian.</strong> Dokumen yang dihasilkan adalah
    <em>contoh demonstrasi</em> dan <strong>wajib diperiksa di Microsoft Word</strong>
    sebelum digunakan. Klausul hukum, notaris, saksi, dan identitas lembaga
    bersifat sintetis/demonstratif dan tidak diubah oleh aplikasi ini. Data
    pribadi tidak disimpan di server.
  </section>

  <section id="template-warning" class="notice warn hard" hidden>
    <strong>Template tidak siap.</strong>
    <span id="template-warning-text"></span>
  </section>

  <section id="ocr-panel" class="ocr">
    <header class="ocr-head">
      <h2>Isi dari KTP (OCR)</h2>
      <span id="ocr-status" class="badge">memeriksa mesin OCR&hellip;</span>
    </header>
    <p class="hint">
      Pilih <strong>mode</strong>, peran, lalu unggah foto/scan KTP
      (JPEG atau PNG). Hasil OCR <strong>hanya berupa saran</strong>: periksa
      dulu, lalu klik <em>Terapkan ke formulir</em>. Bidang yang sudah terisi
      tidak akan ditimpa tanpa persetujuan Anda.
    </p>
    <fieldset class="ocr-mode">
      <legend>Mode pemrosesan</legend>
      <label class="mode-opt">
        <input type="radio" name="ocr-mode" value="local" checked>
        <span><strong>Lokal (offline)</strong> &mdash; gambar tetap di
        komputer ini (Tesseract). Tidak ada unggahan.</span>
      </label>
      <label class="mode-opt">
        <input type="radio" name="ocr-mode" value="ai">
        <span><strong>AI daring</strong> &mdash; gambar <em>dikirim</em> ke
        penyedia AI yang dikonfigurasi untuk ditranskripsi.</span>
      </label>
    </fieldset>
    <div id="ocr-ai-panel" class="ocr-ai" hidden>
      <p class="ai-disclosure" id="ocr-ai-disclosure"></p>
      <label class="consent">
        <input type="checkbox" id="ocr-consent">
        <span>Saya menyetujui gambar KTP ini dikirim ke penyedia AI di atas
        untuk permintaan ini. <strong>Persetujuan tidak disimpan</strong> dan
        wajib dicentang ulang setiap kali.</span>
      </label>
    </div>
    <div class="ocr-controls">
      <label for="ocr-role">Peran data KTP</label>
      <select id="ocr-role">
        <option value="owner">Pemilik tanah (Pemberi Kuasa)</option>
        <option value="spouse">Pasangan (pemberi persetujuan)</option>
        <option value="debtor">Debitor</option>
      </select>
      <label class="file-label" for="ocr-file">Berkas KTP</label>
      <input id="ocr-file" type="file" accept="image/jpeg,image/png">
      <button type="button" id="ocr-run" class="secondary" disabled>
        Proses OCR
      </button>
    </div>
    <div id="ocr-preview-wrap" class="ocr-preview" hidden>
      <img id="ocr-preview" alt="Pratinjau KTP (lokal)" />
    </div>
    <div id="ocr-error" class="message err" hidden></div>
    <div id="ocr-review" class="ocr-review" hidden>
      <h3>Hasil OCR &mdash; tinjau sebelum menerapkan</h3>
      <p id="ocr-review-origin" class="ocr-apply-note" hidden></p>
      <table class="ocr-table">
        <thead>
          <tr><th>Bidang</th><th>Nilai terbaca</th><th>Keyakinan</th>
          <th>Isi ke formulir</th></tr>
        </thead>
        <tbody id="ocr-rows"></tbody>
      </table>
      <details class="ocr-raw">
        <summary>Teks OCR mentah (lokal)</summary>
        <pre id="ocr-raw-text"></pre>
      </details>
      <div class="actions">
        <button type="button" id="ocr-apply">Terapkan ke formulir</button>
        <button type="button" id="ocr-clear" class="secondary">Tutup hasil
        </button>
      </div>
    </div>
  </section>

  <form id="form" autocomplete="off">
    <div id="field-groups"></div>

    <section class="review-panel">
      <h2>Tinjau &amp; Kunci Data</h2>
      <p class="hint">
        Tekan <strong>Tinjau &amp; Kunci Data</strong> untuk menghitung
        ringkasan kanonik dari data yang sudah divalidasi server. Dokumen hanya
        dapat dibuat setelah tinjauan ini dikunci dan persetujuan akhir
        dicentang. Mengubah field apa pun otomatis membatalkan tinjauan.
      </p>
      <div class="actions">
        <button type="button" id="review-btn" class="secondary">
          Tinjau &amp; Kunci Data
        </button>
        <button type="button" id="draft-save" class="secondary">
          Simpan Draf
        </button>
        <label class="file-label" for="draft-open">Buka Draf</label>
        <input id="draft-open" type="file" accept=".json,application/json">
      </div>
      <div id="review-status" class="message" role="status"
           aria-live="polite"></div>
      <div id="review-summary" class="summary" hidden></div>
      <label class="consent" id="ack-wrap" hidden>
        <input type="checkbox" id="ack-check">
        <span>Saya sudah memeriksa seluruh ringkasan di atas (identitas
        pemilik/pasangan/debitor, NIK, tanggal lahir, alamat, nilai
        pembiayaan &amp; tanggungan beserta terbilang, serta data
        sertifikat/tanah) dan menyatakan data ini benar untuk
        <strong>dibuat menjadi dokumen</strong>.
        <em>Persetujuan ini terikat pada data saat ini; mengubah field
        membatalkannya.</em></span>
      </label>
      <div id="draft-note" class="draft-note" hidden></div>
    </section>

    <div class="actions">
      <button type="submit" id="submit" disabled>Buat &amp; Unduh DOCX</button>
      <button type="reset" id="reset" class="secondary">Bersihkan</button>
    </div>
  </form>

  <div id="message" class="message" role="status" aria-live="polite"></div>
</main>

<footer>
  <p>Aplikasi lokal &mdash; berjalan di <code>127.0.0.1</code>. Mode OCR
  lokal dan pembuatan dokumen tidak mengirim data ke internet. <strong>Hanya
  mode OCR &ldquo;AI daring&rdquo; yang Anda pilih sendiri</strong> (dengan
  persetujuan per permintaan) yang mengirim gambar KTP ke penyedia AI yang
  dikonfigurasi.</p>
  <p><strong>Simpan Draf:</strong> draf hanya dibuat saat Anda menekan
  <em>Simpan Draf</em> dan hanya berupa berkas JSON yang diunduh ke komputer
  Anda. Server tidak menyimpan draf. Draf <strong>tidak dienkripsi</strong>
  (berkas lokal biasa) dan tidak memuat gambar KTP, kunci API, maupun teks
  OCR mentah. Anda mengelola sendiri berkas draf dan menghapusnya bila
  tidak diperlukan. Membuka draf selalu lewat impor berkas dan setiap nilai
  wajib ditinjau ulang.</p>
</footer>

<script src="app.js"></script>
</body>
</html>
"""

APP_CSS = """
:root{
  --bg:#0f172a; --panel:#ffffff; --ink:#1f2937; --muted:#6b7280;
  --line:#e5e7eb; --accent:#1d4ed8; --accent-2:#1e40af;
  --warn-bg:#fff7ed; --warn-line:#fdba74; --ok:#047857; --err:#b91c1c;
}
*{box-sizing:border-box}
body{
  margin:0; background:#f1f5f9; color:var(--ink);
  font-family:Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  line-height:1.5;
}
.topbar{
  display:flex; align-items:center; justify-content:space-between;
  gap:1rem; padding:.85rem 1.25rem; background:var(--bg); color:#fff;
  position:sticky; top:0; z-index:5; flex-wrap:wrap;
}
.brand{display:flex; align-items:center; gap:.6rem}
.brand h1{font-size:1.1rem; margin:0; font-weight:600}
.dot{width:.7rem;height:.7rem;border-radius:50%;background:#34d399;display:inline-block}
.tag{font-size:.75rem;background:rgba(255,255,255,.12);padding:.25rem .6rem;border-radius:999px}
main{max-width:960px; margin:0 auto; padding:1.25rem}
.notice{
  background:var(--warn-bg); border:1px solid var(--warn-line);
  border-radius:10px; padding:.85rem 1rem; margin-bottom:1.25rem; font-size:.92rem;
}
form{
  background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:1.25rem; box-shadow:0 1px 2px rgba(0,0,0,.04);
}
fieldset{border:0; border-top:1px solid var(--line); margin:1.25rem 0 0; padding:1rem 0 0}
fieldset:first-of-type{border-top:0; margin-top:0; padding-top:0}
legend{font-weight:700; font-size:1rem; color:var(--accent-2); padding:0 .25rem}
.grid{display:grid; grid-template-columns:repeat(2,1fr); gap:.9rem 1rem}
.field{display:flex; flex-direction:column; gap:.3rem}
.field.full{grid-column:1 / -1}
label{font-size:.85rem; font-weight:600; color:#374151}
.req{color:var(--err)}
input,select{
  padding:.55rem .65rem; border:1px solid var(--line); border-radius:8px;
  font-size:.95rem; background:#fff; color:var(--ink); width:100%;
}
input:focus,select:focus{outline:2px solid var(--accent); border-color:var(--accent)}
input[aria-invalid="true"],select[aria-invalid="true"]{border-color:var(--err); background:#fef2f2}
.hint{font-size:.75rem; color:var(--muted)}
.inline{display:flex; gap:1rem; align-items:center; flex-wrap:wrap}
.inline label{display:flex; align-items:center; gap:.35rem; font-weight:500}
.actions{display:flex; gap:.75rem; margin-top:1.5rem; flex-wrap:wrap}
button{
  padding:.65rem 1.1rem; border-radius:8px; border:1px solid var(--accent);
  background:var(--accent); color:#fff; font-size:.95rem; font-weight:600;
  cursor:pointer;
}
button:hover{background:var(--accent-2)}
button.secondary{background:#fff; color:var(--accent)}
button:disabled{opacity:.6; cursor:not-allowed}
.message{margin-top:1rem; padding:.85rem 1rem; border-radius:10px; display:none; font-size:.92rem}
.message.show{display:block}
.message.err{background:#fef2f2; border:1px solid #fca5a5; color:var(--err)}
.message.ok{background:#ecfdf5; border:1px solid #6ee7b7; color:var(--ok)}
.message.warn{background:var(--warn-bg); border:1px solid var(--warn-line); color:#7c2d12}
.notice.hard{background:#fef2f2; border-color:#fca5a5}
.review-panel{margin-top:1.5rem; border-top:1px solid var(--line); padding-top:1rem}
.review-panel h2{font-size:1rem; margin:.2rem 0 .5rem; color:var(--accent-2)}
.summary{margin-top:1rem; border:1px solid var(--line); border-radius:10px; padding:.5rem .9rem}
.summary h3{font-size:.9rem; margin:.6rem 0 .35rem; color:var(--accent-2)}
.summary dl{display:grid; grid-template-columns:auto 1fr; gap:.15rem .7rem; margin:0 0 .4rem}
.summary dt{font-weight:600; color:#374151; font-size:.82rem}
.summary dd{margin:0; font-size:.85rem; word-break:break-word}
.summary .money{font-weight:600}
.summary .notes{margin:.3rem 0 0; padding-left:1.1rem; font-size:.82rem; color:#7c2d12}
.summary .cols{display:grid; grid-template-columns:repeat(3,1fr); gap:.6rem}
.summary .col{border:1px solid var(--line); border-radius:8px; padding:.45rem .6rem}
.summary .col h4{font-size:.8rem; margin:.1rem 0 .35rem; color:var(--accent-2)}
.stale{background:#fef3c7 !important}
.field.review-flag{outline:2px solid #f59e0b; border-radius:8px}
.draft-note{margin-top:.75rem; font-size:.82rem; color:#7c2d12; background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:8px; padding:.6rem .75rem}
.draft-note.show{display:block}
footer{max-width:960px; margin:0 auto; padding:1rem 1.25rem 2.5rem; color:var(--muted); font-size:.8rem}
code{background:#e2e8f0; padding:.1rem .35rem; border-radius:4px}
.ocr{
  background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:1.1rem 1.25rem; margin-bottom:1.25rem;
  box-shadow:0 1px 2px rgba(0,0,0,.04);
}
.ocr-head{display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap}
.ocr-head h2{font-size:1.05rem; margin:0; color:var(--accent-2)}
.badge{font-size:.72rem; padding:.2rem .6rem; border-radius:999px; background:#e2e8f0; color:#334155}
.badge.ok{background:#dcfce7; color:#166534}
.badge.warn{background:#fef3c7; color:#92400e}
.badge.err{background:#fee2e2; color:#991b1b}
.ocr-controls{display:flex; gap:.85rem; align-items:flex-end; flex-wrap:wrap; margin:.75rem 0}
.ocr-mode{border:1px solid var(--line); border-radius:10px; padding:.6rem .85rem; margin:.75rem 0}
.ocr-mode legend{font-weight:700; font-size:.85rem; color:var(--accent-2); padding:0 .25rem}
.mode-opt{display:flex; gap:.5rem; align-items:flex-start; font-weight:500; font-size:.85rem; padding:.25rem 0}
.mode-opt input{margin-top:.2rem; width:auto}
.ocr-ai{border:1px solid var(--warn-line); background:var(--warn-bg); border-radius:10px; padding:.75rem .85rem; margin:.5rem 0}
.ai-disclosure{font-size:.82rem; margin:0 0 .5rem; color:#7c2d12}
.consent{display:flex; gap:.5rem; align-items:flex-start; font-size:.82rem; font-weight:500}
.consent input{margin-top:.2rem; width:auto}
.ocr-controls label{font-size:.8rem; font-weight:600; color:#374151; display:flex; flex-direction:column; gap:.3rem}
.file-label{min-width:180px}
.ocr-preview{margin:.5rem 0}
.ocr-preview img{max-width:340px; max-height:220px; border:1px solid var(--line); border-radius:8px; background:#f8fafc}
.ocr-review{margin-top:.75rem; border-top:1px solid var(--line); padding-top:.85rem}
.ocr-review h3{font-size:.95rem; margin:.2rem 0 .6rem; color:var(--accent-2)}
.ocr-table{width:100%; border-collapse:collapse; font-size:.85rem}
.ocr-table th,.ocr-table td{text-align:left; padding:.4rem .5rem; border-bottom:1px solid var(--line); vertical-align:top}
.ocr-table th{font-size:.75rem; text-transform:uppercase; letter-spacing:.03em; color:var(--muted)}
.ocr-table td.val{font-family:Consolas, "Courier New", monospace; word-break:break-word}
.ocr-table .conf{font-size:.72rem; padding:.1rem .45rem; border-radius:999px; white-space:nowrap}
.conf.format_valid{background:#dbeafe; color:#1e40af}
.conf.review{background:#fef3c7; color:#92400e}
.conf.missing{background:#e2e8f0; color:#64748b}
.ocr-raw{margin:.75rem 0}
.ocr-raw summary{cursor:pointer; font-size:.82rem; color:var(--muted)}
.ocr-raw pre{max-height:180px; overflow:auto; background:#0f172a; color:#e2e8f0; padding:.75rem; border-radius:8px; font-size:.78rem; white-space:pre-wrap}
.ocr-apply-note{font-size:.75rem; color:var(--muted); margin:.4rem 0 0}
@media (max-width:640px){
  .grid{grid-template-columns:1fr}
  main{padding:1rem}
  form{padding:1rem}
  .ocr{padding:1rem}
  .summary .cols{grid-template-columns:1fr}
}
"""

APP_JS = """
(function(){
  'use strict';
  var GROUPS = [
    {title:'Data Akta', keys:['nomor_akta','tanggal_akta']},
    {title:'Pemberi Kuasa \u2014 Pemilik Tanah', keys:[
      'owner_title','owner_nama','owner_lahir_tempat','owner_lahir_tanggal',
      'owner_pekerjaan','owner_dusun','owner_rt','owner_rw','owner_desa',
      'owner_kecamatan','owner_kabupaten','owner_nik']},
    {title:'Persetujuan Pasangan', keys:[
      'spouse_mode','spouse_nama','spouse_lahir_tempat','spouse_lahir_tanggal',
      'spouse_pekerjaan','spouse_alamat_sama','spouse_dusun','spouse_rt',
      'spouse_rw','spouse_desa','spouse_kecamatan','spouse_kabupaten',
      'spouse_nik']},
    {title:'Debitor', keys:[
      'same_as_owner','debtor_title','debtor_nama','debtor_lahir_tempat',
      'debtor_lahir_tanggal','debtor_pekerjaan','debtor_dusun','debtor_rt',
      'debtor_rw','debtor_desa','debtor_kecamatan','debtor_kabupaten',
      'debtor_nik']},
    {title:'Nilai Pembiayaan', keys:['nilai_pembiayaan','nilai_tanggungan']},
    {title:'Akad Pembiayaan', keys:['akad_jenis','akad_nomor','akad_tanggal']},
    {title:'Objek Hak Tanggungan', keys:[
      'ht_jenis','ht_nomor','ht_desa_sertifikat','surat_ukur_nomor',
      'surat_ukur_tanggal','luas_m2','nib','nop']},
    {title:'Lokasi Objek', keys:[
      'lok_provinsi','lok_kabupaten','lok_kecamatan','lok_desa','lok_jalan']}
  ];
  var SELECTS = {
    owner_title:['Tuan','Nyonya','Nona'],
    debtor_title:['Tuan','Nyonya','Nona'],
    spouse_mode:[['istri','Istri (pemilik laki-laki)'],['suami','Suami (pemilik perempuan)']],
    spouse_alamat_sama:[['ya','Ya, sama dengan pemilik'],['tidak','Tidak, alamat berbeda']],
    same_as_owner:[['ya','Ya, debitor = pemilik'],['tidak','Tidak, debitor berbeda']]
  };
  var meta = {};

  function el(tag, attrs, children){
    var e = document.createElement(tag);
    if(attrs){ for(var k in attrs){ e.setAttribute(k, attrs[k]); } }
    (children||[]).forEach(function(c){ e.appendChild(c); });
    return e;
  }

  function buildField(m){
    var wrap = el('div', {class:'field' +
      (/(dusun|desa|kecamatan|kabupaten)$/.test(m.key) ? ' full':'')});
    var id = 'f_' + m.key;
    var lab = el('label', {for:id});
    lab.textContent = m.label;
    if(m.required){ var s=el('span',{class:'req'}); s.textContent=' *'; lab.appendChild(s); }
    wrap.appendChild(lab);
    var control;
    if(SELECTS[m.key]){
      control = el('select', {id:id, name:m.key});
      var opts = SELECTS[m.key];
      var blank = el('option', {value:''}); blank.textContent='-- pilih --';
      control.appendChild(blank);
      opts.forEach(function(o){
        var val = Array.isArray(o)?o[0]:o, txt = Array.isArray(o)?o[1]:o;
        var op = el('option', {value:val}); op.textContent = txt;
        control.appendChild(op);
      });
    } else {
      var type = m.kind==='date' ? 'date' : 'text';
      control = el('input', {id:id, name:m.key, type:type});
      if(m.kind==='nik'){ control.setAttribute('inputmode','numeric'); control.setAttribute('maxlength','16'); }
      if(m.kind==='money'){ control.setAttribute('inputmode','numeric'); control.setAttribute('placeholder','mis. 50.000.000'); }
      if(m.kind==='text' && m.key==='nomor_akta'){ control.setAttribute('placeholder','mis. 12/ 2026'); }
      if(m.kind==='text' && /\\.dusun$/.test(m.key)){ control.setAttribute('placeholder','mis. Nama Dusun (tanpa awalan "Dusun")'); }
      if(m.kind==='text' && /\\.(rt|rw)$/.test(m.key)){ control.setAttribute('inputmode','numeric'); control.setAttribute('maxlength','3'); control.setAttribute('placeholder','angka, mis. 003 / 000'); }
    }
    if(m.required){ control.setAttribute('required',''); }
    wrap.appendChild(control);
    var hint = el('div', {class:'hint'});
    hint.textContent = hintFor(m);
    wrap.appendChild(hint);
    return {wrap:wrap, control:control};
  }

  function hintFor(m){
    if(m.kind==='date'){ return 'Format YYYY-MM-DD (tanggal tidak valid ditolak).'; }
    if(m.kind==='nik'){ return 'Tepat 16 digit angka.'; }
    if(m.kind==='money'){ return 'Angka rupiah, mis. 50.000.000.'; }
    if(m.key==='luas_m2'){ return 'Angka luas, mis. 1153 atau 1.153.'; }
    if(/\\.(rt|rw)$/.test(m.key)){ return 'Angka 1-3 digit; nol di depan dipertahankan (mis. 003/000).'; }
    if(/\\.dusun$/.test(m.key)){ return 'Isi teks dusun apa adanya (tanpa awalan "Dusun").'; }
    if(/\\.kabupaten$/.test(m.key)){ return 'Kosongkan untuk memakai default Kota Contoh.'; }
    return '';
  }

  function render(ms){
    var byKey = {};
    ms.forEach(function(m){ byKey[m.key]=m; });
    meta = byKey;
    var container = document.getElementById('field-groups');
    GROUPS.forEach(function(g){
      var fs = el('fieldset');
      var lg = el('legend'); lg.textContent = g.title; fs.appendChild(lg);
      var grid = el('div', {class:'grid'});
      g.keys.forEach(function(k){
        if(!byKey[k]) return;
        var f = buildField(byKey[k]);
        grid.appendChild(f.wrap);
      });
      fs.appendChild(grid);
      container.appendChild(fs);
    });
    wireConditionals();
  }

  function setDisabled(keys, disabled){
    keys.forEach(function(k){
      var c = document.getElementById('f_'+k);
      if(c){ c.disabled = disabled; }
    });
  }

  function wireConditionals(){
    var same = document.getElementById('f_same_as_owner');
    var dkeys = ['debtor_title','debtor_nama','debtor_lahir_tempat',
      'debtor_lahir_tanggal','debtor_pekerjaan','debtor_dusun','debtor_rt',
      'debtor_rw','debtor_desa','debtor_kecamatan','debtor_kabupaten',
      'debtor_nik'];
    function updSame(){ setDisabled(dkeys, same.value === 'ya'); }
    same.addEventListener('change', updSame); updSame();

    var alamat = document.getElementById('f_spouse_alamat_sama');
    var akeys = ['spouse_dusun','spouse_rt','spouse_rw','spouse_desa',
      'spouse_kecamatan','spouse_kabupaten'];
    function updAlamat(){ setDisabled(akeys, alamat.value === 'ya'); }
    alamat.addEventListener('change', updAlamat); updAlamat();
  }

  function collect(){
    var data = {};
    Object.keys(meta).forEach(function(k){
      var c = document.getElementById('f_'+k);
      if(!c) return;
      if(c.disabled){
        // Field yang dinonaktifkan karena "sama dengan" tetap dikirim kosong
        // (server akan menyalin dari sumbernya).
        data[k] = '';
      } else {
        data[k] = c.value;
      }
    });
    return data;
  }
  function showMessage(kind, text){
    var m = document.getElementById('message');
    m.className = 'message show ' + kind;
    m.textContent = text;
    if(kind==='ok'){ m.scrollIntoView({behavior:'smooth', block:'nearest'}); }
  }

  function status(){
    var m = document.getElementById('message');
    m.className='message';
    m.textContent='';
  }

  // ===================================================================
  // Tinjauan (review) & draf. Server adalah otoritas: ringkasan kanonik,
  // digest integritas, dan status tinjauan SEMUA dihitung server. UI hanya
  // menampilkan dan mengirim kembali token yang diterima.
  // ===================================================================
  var reviewState = {
    reviewed: false, digest: null, ackToken: null, summarySignature: null,
    summary: null, ocrData: {}, ocrPending: [], draftSource: null,
    imported: false, acknowledged: false
  };
  var reviewSeq = 0;

  var SUMMARY_FIELDS = [
    ['nama','Nama'], ['sapaan','Sapaan'], ['lahir_tempat','Tempat lahir'],
    ['lahir_tanggal','Tanggal lahir'], ['pekerjaan','Pekerjaan'],
    ['nik','NIK'], ['alamat','Alamat']
  ];
  var SUMMARY_MONEY = [
    ['nilai_pembiayaan','Nilai pembiayaan (Debitor)'],
    ['nilai_tanggungan','Nilai Tanggungan Peringkat Pertama']
  ];
  var SUMMARY_TANAH = [
    ['ht_jenis','Jenis hak'], ['ht_nomor','Nomor hak'],
    ['ht_desa_sertifikat','Desa/Kelurahan sertifikat'],
    ['surat_ukur_nomor','Nomor Surat Ukur'],
    ['surat_ukur_tanggal','Tanggal Surat Ukur'],
    ['luas_m2','Luas (M2)'], ['luas_kata','Luas (kata)'],
    ['nib','NIB'], ['nop','NOP']
  ];
  var SUMMARY_LOKASI = [
    ['lok_provinsi','Provinsi'], ['lok_kabupaten','Kabupaten/Kota'],
    ['lok_kecamatan','Kecamatan'], ['lok_desa','Desa/Kelurahan'],
    ['lok_jalan','Jalan / RT / RW']
  ];

  function reviewSetStatus(kind, text){
    var el2 = document.getElementById('review-status');
    el2.className = 'message show ' + kind;
    el2.textContent = text;
  }
  function reviewClearStatus(){
    var el2 = document.getElementById('review-status');
    el2.className = 'message';
    el2.textContent = '';
  }

  function payload(){
    var data = collect();
    data._reviewed = reviewState.reviewed;
    data._review_digest = reviewState.reviewed ? reviewState.digest : null;
    data._review_ts = reviewState.reviewed ? Math.floor(Date.now()/1000) : null;
    data._review_data = reviewState.ocrData;
    data._imported = reviewState.imported;
    data._draft_source = reviewState.draftSource;
    data.confirm_summary = reviewState.acknowledged;
    data.ack_digest = reviewState.acknowledged ? reviewState.digest : null;
    data.ack_token = reviewState.acknowledged ? reviewState.ackToken : null;
    data.summary_signature = reviewState.acknowledged
      ? reviewState.summarySignature : null;
    return data;
  }

  function invalidateReview(reason){
    reviewState.reviewed = false;
    reviewState.digest = null;
    reviewState.ackToken = null;
    reviewState.summarySignature = null;
    reviewState.acknowledged = false;
    var ack = document.getElementById('ack-check');
    if(ack){ ack.checked = false; }
    document.getElementById('ack-wrap').hidden = true;
    document.getElementById('submit').disabled = true;
    if(reason){ reviewSetStatus('warn', reason); }
    else { reviewClearStatus(); }
  }

  function moneyText(obj){
    if(!obj) return '';
    var n = obj.nilai_pembiayaan || obj.nilai_tanggungan || '';
    var w = obj.nilai_pembiayaan_kata || obj.nilai_tanggungan_kata || '';
    return 'Rp ' + n + ' (' + w + ')';
  }

  function renderSummary(s, provenance){
    var box = document.getElementById('review-summary');
    var h = '';
    if(provenance && provenance.imported){
      h += '<p class="hint">Sumber: <strong>draf impor</strong>'
        + (provenance.draft_source
            ? ' (' + escapeHtml(provenance.draft_source) + ')' : '')
        + ' &mdash; wajib ditinjau ulang.</p>';
    }
    h += '<h3>Data akta</h3><dl>'
      + '<dt>Nomor akta</dt><dd>' + escapeHtml(s.akta.nomor_akta) + '</dd>'
      + '<dt>Tanggal akta</dt><dd>' + escapeHtml(s.akta.tanggal_akta_inc)
      + '</dd></dl>';

    h += '<h3>Identitas (berdampingan)</h3><div class="cols">';
    var cols = [['Pemilik (Pemberi Kuasa)','owner'],
                ['Pasangan (Persetujuan)','spouse'],
                ['Debitor','debtor']];
    cols.forEach(function(c){
      h += '<div class="col"><h4>' + c[0] + '</h4><dl>';
      SUMMARY_FIELDS.forEach(function(f){
        h += '<dt>' + f[1] + '</dt><dd>' + escapeHtml(s[c[1]][f[0]] || '\u2014')
          + '</dd>';
      });
      h += '</dl></div>';
    });
    h += '</div>';

    h += '<h3>Pembiayaan &amp; Tanggungan</h3><dl>'
      + '<dt>Nilai pembiayaan</dt><dd class="money">Rp '
      + escapeHtml(s.pembiayaan.nilai_pembiayaan) + ' ('
      + escapeHtml(s.pembiayaan.nilai_pembiayaan_kata) + ')</dd>'
      + '<dt>Nilai tanggungan</dt><dd class="money">Rp '
      + escapeHtml(s.tanggungan.nilai_tanggungan) + ' ('
      + escapeHtml(s.tanggungan.nilai_tanggungan_kata) + ')</dd></dl>';

    h += '<h3>Akad</h3><dl>'
      + '<dt>Jenis</dt><dd>' + escapeHtml(s.akad.jenis) + '</dd>'
      + '<dt>Nomor</dt><dd>' + escapeHtml(s.akad.nomor) + '</dd>'
      + '<dt>Tanggal</dt><dd>' + escapeHtml(s.akad.tanggal) + '</dd></dl>';

    h += '<h3>Objek Hak Tanggungan (data tanah)</h3><dl>';
    SUMMARY_TANAH.forEach(function(f){
      h += '<dt>' + f[1] + '</dt><dd>' + escapeHtml(s.tanah[f[0]] || '\u2014')
        + '</dd>';
    });
    h += '</dl><h3>Lokasi objek</h3><dl>';
    SUMMARY_LOKASI.forEach(function(f){
      h += '<dt>' + f[1] + '</dt><dd>' + escapeHtml(s.lokasi[f[0]] || '\u2014')
        + '</dd>';
    });
    h += '</dl>';

    if(s.catatan && s.catatan.length){
      h += '<h3>Catatan</h3><ul class="notes">';
      s.catatan.forEach(function(c){ h += '<li>' + escapeHtml(c) + '</li>'; });
      h += '</ul>';
    }
    box.innerHTML = h;
    box.hidden = false;
  }

  function renderOcrPending(pending){
    // Tandai field formulir yang masih butuh konfirmasi OCR.
    Object.keys(meta).forEach(function(k){
      var wrap = document.getElementById('f_'+k);
      if(wrap){ wrap.closest('.field').classList.remove('review-flag'); }
    });
    (pending || []).forEach(function(k){
      var c = document.getElementById('f_'+k);
      if(c){ c.closest('.field').classList.add('review-flag'); }
    });
    if(pending && pending.length){
      reviewSetStatus('warn', 'Data dari OCR/draf belum dikonfirmasi: '
        + pending.map(function(k){
            return (REVIEW_LABELS[k] || k); }).join(', ')
        + '. Isi ulang atau konfirmasi di panel OCR sebelum meninjau ulang.');
    }
  }
  var REVIEW_LABELS = {
    owner_nama:'Nama pemilik', owner_nik:'NIK pemilik',
    owner_lahir_tempat:'Tempat lahir pemilik',
    owner_lahir_tanggal:'Tanggal lahir pemilik',
    owner_pekerjaan:'Pekerjaan pemilik', owner_dusun:'Dusun pemilik',
    owner_rt:'RT pemilik', owner_rw:'RW pemilik', owner_desa:'Desa pemilik',
    owner_kecamatan:'Kecamatan pemilik', owner_kabupaten:'Kabupaten pemilik',
    spouse_nama:'Nama pasangan', spouse_nik:'NIK pasangan',
    spouse_lahir_tempat:'Tempat lahir pasangan',
    spouse_lahir_tanggal:'Tanggal lahir pasangan',
    spouse_pekerjaan:'Pekerjaan pasangan', spouse_dusun:'Dusun pasangan',
    spouse_rt:'RT pasangan', spouse_rw:'RW pasangan',
    spouse_desa:'Desa pasangan', spouse_kecamatan:'Kecamatan pasangan',
    spouse_kabupaten:'Kabupaten pasangan',
    debtor_nama:'Nama debitor', debtor_nik:'NIK debitor',
    debtor_lahir_tempat:'Tempat lahir debitor',
    debtor_lahir_tanggal:'Tanggal lahir debitor',
    debtor_pekerjaan:'Pekerjaan debitor', debtor_dusun:'Dusun debitor',
    debtor_rt:'RT debitor', debtor_rw:'RW debitor', debtor_desa:'Desa debitor',
    debtor_kecamatan:'Kecamatan debitor', debtor_kabupaten:'Kabupaten debitor'
  };

  function doReview(){
    var btn = document.getElementById('review-btn');
    btn.disabled = true;
    var seq = ++reviewSeq;
    reviewClearStatus();
    reviewSetStatus('warn', 'Menghitung ringkasan kanonik\u2026');
    fetch('/api/review', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload())
    }).then(function(r){ return r.json(); }).then(function(j){
      if(seq !== reviewSeq){ return; }  // respons usang diabaikan
      if(!j.ok){ throw new Error(j.error || 'Gagal menghitung ringkasan.'); }
      if(!j.valid){
        invalidateReview();
        reviewSetStatus('err', j.error || 'Data belum lengkap/valid.');
        document.getElementById('review-summary').hidden = true;
        return;
      }
      if((j.ocr && j.ocr.needs_review && j.ocr.needs_review.length)){
        invalidateReview();
        renderOcrPending(j.ocr.needs_review);
        document.getElementById('review-summary').hidden = true;
        return;
      }
      reviewState.update = null;
      reviewState.digest = j.digest;
      reviewState.ackToken = j.ack_token;
      reviewState.summarySignature = j.summary_signature;
      reviewState.summary = j.summary;
      reviewState.reviewed = true;
      reviewState.acknowledged = false;
      var ackCheck = document.getElementById('ack-check');
      ackCheck.checked = false;
      reviewState.acknowledged = false;
      document.getElementById('ack-wrap').hidden = false;
      document.getElementById('submit').disabled = true;
      renderSummary(j.summary, j.provenance);
      renderOcrPending(j.ocr ? j.ocr.needs_review : []);
      reviewSetStatus('ok', 'Data terkunci. Periksa ringkasan, lalu centang '
        + 'persetujuan untuk mengaktifkan tombol Buat.');
    }).catch(function(err){
      if(seq !== reviewSeq){ return; }
      invalidateReview();
      reviewSetStatus('err', err.message || 'Gagal meninjau data.');
    }).finally(function(){
      if(seq === reviewSeq){ btn.disabled = false; }
    });
  }

  function wireReview(){
    var form = document.getElementById('form');
    // Setiap perubahan input/select membatalkan tinjauan (drift).
    form.addEventListener('input', function(){ invalidateReview(); });
    form.addEventListener('change', function(){ onChangeField(); });
    document.getElementById('review-btn').addEventListener('click', doReview);
    document.getElementById('ack-check').addEventListener('change',
      function(){
        reviewState.acknowledged = this.checked;
        document.getElementById('submit').disabled = !this.checked;
      });
  }

  function onChangeField(){
    invalidateReview();
    wireConditionals();
  }

  document.getElementById('form').addEventListener('submit', function(ev){
    ev.preventDefault();
    status();
    if(!reviewState.reviewed){
      showMessage('err', 'Tinjau & kunci data terlebih dahulu sebelum '
        + 'membuat dokumen.');
      return;
    }
    if(!document.getElementById('ack-check').checked){
      showMessage('err', 'Centang pernyataan persetujuan terlebih dahulu.');
      return;
    }
    var btn = document.getElementById('submit');
    btn.disabled = true;
    btn.textContent = 'Menyusun...';
    fetch('/api/generate', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload())
    }).then(function(res){
      if(!res.ok){
        return res.json().then(function(j){
          if(j.summary){ renderSummary(j.summary, {}); }
          var e = new Error(j.error || 'Gagal.');
          e.reviewState = j.review_state;
          throw e;
        }).catch(function(e){
          throw (e instanceof Error ? e : new Error('Gagal.'));
        });
      }
      var cd = res.headers.get('Content-Disposition') || '';
      var name = 'SKMHT_contoh.docx';
      var mm = /filename\\*=UTF-8''([^;]+)/.exec(cd) || /filename="([^"]+)"/.exec(cd);
      if(mm){ name = decodeURIComponent(mm[1]); }
      return res.blob().then(function(blob){
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click();
        document.body.removeChild(a);
        setTimeout(function(){ URL.revokeObjectURL(url); }, 4000);
        showMessage('ok', 'Dokumen berhasil dibuat dan diunduh sebagai '
          + name + '. Ingat: ini DRAF, wajib diperiksa di Microsoft Word.');
      });
    }).catch(function(err){
      showMessage('err', err.message || 'Terjadi kesalahan.');
      if(err.reviewState){
        // Server menolak karena tinjauan tidak sah (mis. setelah reload).
        invalidateReview('Tinjauan tidak lagi sah. Tekan "Tinjau & Kunci '
          + 'Data" lagi setelah memeriksa data.');
      }
    }).finally(function(){
      btn.textContent = 'Buat & Unduh DOCX';
      document.getElementById('submit').disabled =
        !document.getElementById('ack-check').checked;
    });
  });

  document.getElementById('reset').addEventListener('click', function(){
    setTimeout(function(){
      reviewState.ocrData = {};
      reviewState.imported = false;
      reviewState.draftSource = null;
      document.getElementById('review-summary').hidden = true;
      document.getElementById('draft-note').hidden = true;
      invalidateReview();
      wireConditionals();
      status();
    }, 0);
  });

  // ------------------ Simpan / Buka Draf -------------------------------
  document.getElementById('draft-save').addEventListener('click', function(){
    var btn = this;
    btn.disabled = true;
    fetch('/api/draft/save', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(collect())
    }).then(function(res){
      if(!res.ok){
        return res.json().then(function(j){
          throw new Error(j.error || 'Gagal menyimpan draf.'); });
      }
      var cd = res.headers.get('Content-Disposition') || '';
      var name = 'SKMHT.draft.json';
      var mm = /filename\\*=UTF-8''([^;]+)/.exec(cd) || /filename="([^"]+)"/.exec(cd);
      if(mm){ name = decodeURIComponent(mm[1]); }
      return res.blob().then(function(blob){
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click();
        document.body.removeChild(a);
        setTimeout(function(){ URL.revokeObjectURL(url); }, 4000);
        showMessage('ok', 'Draf disimpan sebagai ' + name + '. Berkas ini '
          + 'TIDAK dienkripsi; simpan & hapus sesuai kebutuhan Anda.');
      });
    }).catch(function(err){
      showMessage('err', err.message || 'Gagal menyimpan draf.');
    }).finally(function(){ btn.disabled = false; });
  });

  document.getElementById('draft-open').addEventListener('change',
    function(ev){
      var file = ev.target.files && ev.target.files[0];
      ev.target.value = '';  // agar berkas sama dapat dibuka ulang
      if(!file){ return; }
      var reader = new FileReader();
      reader.onload = function(){
        var content = String(reader.result || '');
        fetch('/api/draft/import', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({content: content, filename: file.name})
        }).then(function(res){
          return res.json().then(function(j){
            if(!res.ok || !j.ok){ throw new Error(j.error || 'Impor gagal.'); }
            return j;
          });
        }).then(function(j){
          applyDraft(j, file.name);
        }).catch(function(err){
          showMessage('err', 'Impor draf ditolak: '
            + (err.message || 'berkas tidak valid.')
            + ' Formulir TIDAK diubah.');
        });
      };
      reader.onerror = function(){ showMessage('err', 'Gagal membaca berkas draf.'); };
      reader.readAsText(file);
    });

  function confirmReplaceIfFilled(incoming){
    // Konfirmasi bila formulir sudah berisi data (jangan menimpa tanpa sadar).
    var filled = Object.keys(meta).filter(function(k){
      var c = document.getElementById('f_'+k);
      return c && c.value && c.value.trim();
    });
    if(!filled.length){ return true; }
    var count = incoming ? Object.keys(incoming).length : 0;
    return window.confirm('Formulir saat ini sudah berisi ' + filled.length
      + ' kolom. Ganti seluruh isi formulir dengan ' + count
      + ' nilai dari draf? Tindakan ini menimpa isian sekarang.');
  }

  function applyDraft(j, filename){
    var data = j.data || {};
    if(!confirmReplaceIfFilled(data)){
      showMessage('warn', 'Impor dibatalkan; formulir tidak diubah.');
      return;
    }
    // Isi hanya key yang dikenal; nonaktifkan logika kondisional dulu agar
    // field dependen tidak tercampur.
    Object.keys(meta).forEach(function(k){
      var c = document.getElementById('f_'+k);
      if(c && Object.prototype.hasOwnProperty.call(data, k)){ c.value = data[k]; }
    });
    wireConditionals();
    reviewState.ocrData = j.review_data || {};
    reviewState.imported = true;
    reviewState.draftSource = filename || null;
    reviewState.ocrPending = j.needs_review || [];
    var note = document.getElementById('draft-note');
    note.className = 'draft-note show';
    note.textContent = j.message || ('Draf ' + (filename || '')
      + ' dimuat. Nilai dari draf WAJIB ditinjau ulang.');
    note.hidden = false;
    invalidateReview();
    renderOcrPending(reviewState.ocrPending);
    showMessage('ok', 'Draf dimuat. Periksa & konfirmasi setiap kolom '
      + 'bertanda, lalu tekan "Tinjau & Kunci Data".');
  }

  // ------------------ Status template (gagal-keras) --------------------
  function loadTemplateStatus(){
    fetch('/api/template/status').then(function(r){ return r.json(); })
      .then(function(j){
        var box = document.getElementById('template-warning');
        if(j.available){ box.hidden = true; return; }
        box.hidden = false;
        document.getElementById('template-warning-text').textContent = ' '
          + (j.reason || 'Template tidak siap.')
          + (j.hint ? ' Jalankan: ' + j.hint : '')
          + ' Dokumen tidak dapat dibuat sampai template tersedia.';
        document.getElementById('submit').disabled = true;
      }).catch(function(){
        // Jangan memblokir aplikasi bila endpoint status sendiri gagal.
      });
  }

  wireReview();
  loadTemplateStatus();

  fetch('/api/fields').then(function(r){ return r.json(); })
    .then(function(j){ render(j.fields); })
    .catch(function(){ showMessage('err','Gagal memuat skema formulir.'); });

  // ===================================================================
  // OCR KTP lokal: pilih peran -> unggah gambar -> tinjau -> terapkan.
  // Tidak ada penimpaan otomatis: hanya field yang dicentang pengguna
  // yang diisi, dan field yang sudah berisi nilai tidak diubah tanpa
  // persetujuan eksplisit.
  // ===================================================================
  var OCR_ROW_META = [
    ['nik','NIK'],['nama','Nama'],['tempat_lahir','Tempat lahir'],
    ['tanggal_lahir','Tanggal lahir'],['jenis_kelamin','Jenis kelamin'],
    ['pekerjaan','Pekerjaan'],['alamat','Alamat'],['dusun','Dusun'],
    ['rt','RT'],['rw','RW'],['desa','Kel/Desa'],['kecamatan','Kecamatan'],
    ['kabupaten','Kabupaten'],['provinsi','Provinsi']
  ];
  var ocrState = { candidates:{}, selected:{}, previewUrl:null,
                   mode:'local', ai:null, localAvailable:false };

  function ocrEl(id){ return document.getElementById(id); }

  function ocrSetError(msg){
    var box = ocrEl('ocr-error');
    if(msg){ box.textContent = msg; box.hidden = false; }
    else { box.textContent = ''; box.hidden = true; }
  }

  function ocrSetStatus(state, text){
    var b = ocrEl('ocr-status');
    b.className = 'badge ' + (state || '');
    b.textContent = text;
  }

  function ocrCurrentMode(){
    var r = document.querySelector('input[name=ocr-mode]:checked');
    return r ? r.value : 'local';
  }

  function ocrAiDisclosure(){
    var box = ocrEl('ocr-ai-disclosure');
    var ai = ocrState.ai || {};
    var host = ai.base_url_host || 'tidak diketahui';
    var model = ai.model || 'tidak diketahui';
    var warn = '';
    if(!ai.configured){
      warn = ' <strong>Endpoint AI belum dikonfigurasi</strong>, mode ini belum '
        + 'bisa dipakai.';
    } else if(!ai.has_api_key){
      warn = ' <strong>Kunci API belum disetel</strong> '
        + '(SKMHT_AI_API_KEY); mode ini akan gagal sampai kunci ada.';
    }
    // DITAMPILKAN: penyedia + model yang dipakai. Kapabilitas gambar TIDAK
    // diklaim benar kecuali sudah diverifikasi lewat probe terpisah.
    box.innerHTML = 'Gambar akan dikirim ke penyedia AI: <code>'
      + escapeHtml(host) + '</code> &middot; model: <code>'
      + escapeHtml(model) + '</code> (belum diverifikasi untuk gambar).'
      + warn;
  }

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, function(c){
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }

  function ocrUpdateRunButton(){
    var btn = ocrEl('ocr-run');
    var hasFile = !!(ocrEl('ocr-file').files && ocrEl('ocr-file').files.length);
    if(!hasFile){ btn.disabled = true; return; }
    if(ocrCurrentMode() === 'ai'){
      var ai = ocrState.ai || {};
      var ready = ai.configured && ai.has_api_key;
      var consented = ocrEl('ocr-consent').checked;
      btn.disabled = !(ready && consented);
    } else {
      btn.disabled = !ocrState.localAvailable;
    }
  }

  function ocrApplyMode(){
    var mode = ocrCurrentMode();
    ocrState.mode = mode;
    ocrEl('ocr-ai-panel').hidden = (mode !== 'ai');
    if(mode === 'ai'){ ocrAiDisclosure(); }
    ocrUpdateRunButton();
    // Hasil mode berbeda tidak boleh tercampur.
    ocrEl('ocr-review').hidden = true;
    ocrSetError('');
  }

  function ocrLoadStatus(){
    fetch('/api/ocr/status').then(function(r){ return r.json(); })
      .then(function(s){
        ocrState.ai = s.ai || {};
        ocrState.localAvailable = !!s.available;
        if(s.available && s.indonesian){
          ocrSetStatus('ok', 'OCR lokal siap (Tesseract, bahasa Indonesia)');
        } else if(s.available){
          ocrSetStatus('warn', 'OCR lokal siap (Tesseract) \u2014 bahasa '
            + 'Indonesia belum terpasang, hasil wajib ditinjau');
        } else {
          ocrSetStatus('warn', 'Mesin OCR lokal belum siap \u2014 mode AI '
            + 'daring tetap dapat dipakai bila dikonfigurasi');
          ocrSetError((s.detail || 'OCR lokal belum dapat dipakai. Lihat '
            + 'panduan di README.') + ' Fitur lain tetap berfungsi normal.');
        }
        ocrApplyMode();
      }).catch(function(){
        ocrSetStatus('err','Gagal memeriksa status OCR');
        ocrUpdateRunButton();
      });
  }

  function ocrClearPreview(){
    if(ocrState.previewUrl){ URL.revokeObjectURL(ocrState.previewUrl); }
    ocrState.previewUrl = null;
    ocrEl('ocr-preview').removeAttribute('src');
    ocrEl('ocr-preview-wrap').hidden = true;
  }

  function ocrFileSelected(){
    var input = ocrEl('ocr-file');
    ocrSetError('');
    ocrEl('ocr-review').hidden = true;
    ocrClearPreview();
    var f = input.files && input.files[0];
    if(!f){
      ocrUpdateRunButton();
      return;
    }
    var okType = (f.type === 'image/jpeg' || f.type === 'image/png');
    if(!okType){
      ocrSetError('Gunakan gambar JPEG atau PNG.');
      ocrEl('ocr-run').disabled = true;
      return;
    }
    ocrState.previewUrl = URL.createObjectURL(f);
    ocrEl('ocr-preview').src = ocrState.previewUrl;
    ocrEl('ocr-preview-wrap').hidden = false;
    ocrUpdateRunButton();
  }

  function ocrRun(){
    var input = ocrEl('ocr-file');
    var f = input.files && input.files[0];
    if(!f){ ocrSetError('Pilih berkas KTP terlebih dahulu.'); return; }
    var mode = ocrCurrentMode();
    var role = ocrEl('ocr-role').value;
    var btn = ocrEl('ocr-run');
    var label = btn.textContent;
    var endpoint = (mode === 'ai') ? '/api/ocr/ai' : '/api/ocr/ktp';
    var payload = {role: role};
    if(mode === 'ai'){
      if(!ocrEl('ocr-consent').checked){
        ocrSetError('Centang persetujuan sebelum mengirim gambar ke AI.');
        return;
      }
      // Konfirmasi terakhir sebelum gambar benar-benar dikirim ke penyedia.
      if(!window.confirm('Kirim gambar KTP ini ke penyedia AI ('
          + (ocrState.ai && ocrState.ai.base_url_host || 'penyedia')
          + ') sekarang? Data akan meninggalkan komputer ini.')){
        return;
      }
      payload.consent = true;
    }
    btn.disabled = true; btn.textContent = 'Memproses\u2026';
    ocrSetError('');
    var reader = new FileReader();
    reader.onload = function(){
      // reader.result = "data:<mime>;base64,<data>"
      var b64 = String(reader.result).split(',', 2)[1] || '';
      payload.image_base64 = b64;
      fetch(endpoint, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      }).then(function(res){
        return res.json().then(function(j){
          if(!res.ok || !j.ok){ throw new Error(j.error || 'Gagal OCR.'); }
          return j;
        });
      }).then(function(j){
        ocrState.candidates = j.candidates || {};
        renderOcrReview(j, mode);
      }).catch(function(err){
        ocrSetError(err.message || 'Gagal memproses OCR.');
      }).finally(function(){
        btn.textContent = label;
        // Persetujuan dipakai sekali; wajib dicentang ulang.
        if(mode === 'ai'){ ocrEl('ocr-consent').checked = false; }
        ocrUpdateRunButton();
      });
    };
    reader.onerror = function(){
      ocrSetError('Gagal membaca berkas.');
      btn.textContent = label;
      ocrUpdateRunButton();
    };
    reader.readAsDataURL(f);
  }

  function confLabel(status){
    if(status === 'format_valid'){ return 'Format valid — cek isi'; }
    if(status === 'review'){ return 'Perlu tinjau'; }
    return 'Tidak terbaca';
  }

  function renderOcrReview(j, mode){
    var tbody = ocrEl('ocr-rows');
    while(tbody.firstChild){ tbody.removeChild(tbody.firstChild); }
    var fields = j.fields || {};
    var cands = j.candidates || {};
    // Beri tahu asal hasil: lokal atau AI (beserta penyedia/model).
    var origin = ocrEl('ocr-review-origin');
    if(origin){
      if(mode === 'ai'){
        origin.textContent = 'Hasil mode AI daring \u2014 penyedia: '
          + (j.provider || '?') + ', model: ' + (j.model || '?')
          + '. Transkripsi AI adalah data saran, bukan kepastian.';
        origin.hidden = false;
      } else {
        origin.textContent = 'Hasil mode OCR lokal (Tesseract) \u2014 gambar '
          + 'tidak diunggah.';
        origin.hidden = false;
      }
    }
    // Peta form_key -> apakah field formulir sudah terisi.
    var formFilled = {};
    Object.keys(cands).forEach(function(fk){
      var c = document.getElementById('f_' + fk);
      formFilled[fk] = !!(c && c.value && c.value.trim());
    });
    var anyRow = false;
    OCR_ROW_META.forEach(function(pair){
      var ktpKey = pair[0], label = pair[1];
      var info = fields[ktpKey] || {value:'', status:'missing'};
      if(!info.value){ return; }  // jangan tampilkan baris kosong
      anyRow = true;
      var tr = document.createElement('tr');
      var tdL = el('td'); tdL.textContent = label;
      var tdV = el('td', {class:'val'}); tdV.textContent = info.value;
      var tdC = el('td');
      var span = el('span', {class:'conf ' + info.status});
      span.textContent = confLabel(info.status);
      tdC.appendChild(span);
      var tdChk = el('td');
      // Cari form_key yang menerima nilai ini untuk peran terpilih.
      var formKey = null;
      Object.keys(cands).forEach(function(fk){
        if(cands[fk].source === ktpKey && !formKey){ formKey = fk; }
      });
      if(formKey){
        var cb = el('input', {type:'checkbox', 'data-form-key':formKey});
        cb.id = 'ocr_chk_' + formKey;
        // Default dicentang bila field formulir masih kosong, dan hanya bila
        // Kandidat terdeteksi (format_valid/review), tetapi tetap wajib dicek.
        cb.checked = !formFilled[formKey] && info.status !== 'missing';
        tdChk.appendChild(cb);
        if(formFilled[formKey]){
          var note = el('div', {class:'ocr-apply-note'});
          note.textContent = 'Field formulir sudah terisi \u2014 dicentang '
            + 'berarti MENIMPA.';
          tdChk.appendChild(note);
        }
      } else {
        tdChk.textContent = '\u2014';
      }
      tr.appendChild(tdL); tr.appendChild(tdV);
      tr.appendChild(tdC); tr.appendChild(tdChk);
      tbody.appendChild(tr);
    });

    if(!anyRow){
      ocrSetError('Tidak ada bidang KTP yang terbaca dengan jelas. Coba ' +
        'gambar yang lebih tajam/terang.');
      ocrEl('ocr-review').hidden = true;
      return;
    }
    ocrEl('ocr-raw-text').textContent = j.raw_text || '';
    ocrEl('ocr-review').hidden = false;
  }

  function ocrApply(){
    var applied = 0, skipped = 0;
    var inputs = ocrEl('ocr-rows').querySelectorAll('input[type=checkbox]');
    inputs.forEach(function(cb){
      if(!cb.checked){ return; }
      var fk = cb.getAttribute('data-form-key');
      var src = ocrState.candidates[fk];
      var ctrl = document.getElementById('f_' + fk);
      if(!src || !ctrl){ skipped++; return; }
      if(ctrl.disabled){
        // Field dinonaktifkan (mis. debitor = pemilik) -> lewati.
        skipped++; return;
      }
      var existing = (ctrl.value || '').trim();
      if(existing){
        // Konfirmasi eksplisit sebelum menimpa nilai yang sudah ada.
        var proceed = window.confirm(
          'Field sudah berisi "' + existing + '". Timpa dengan "' +
          src.value + '"?');
        if(!proceed){ skipped++; return; }
      }
      // Khusus tanggal: server memakai format YYYY-MM-DD pada input[type=date].
      ctrl.value = src.value;
      // Tandai nilai ini berasal dari OCR dan BELUM ditinjau. Server menolak
      // membuat dokumen sampai nilai ini dikonfirmasi/diubah.
      reviewState.ocrData[fk] = {
        value: src.value, needs_review: true, confirmed: false
      };
      applied++;
    });
    if(applied){
      invalidateReview();
      renderOcrPending(Object.keys(reviewState.ocrData).filter(function(k){
        var e = reviewState.ocrData[k];
        return e && e.needs_review && !e.confirmed;
      }));
      showMessage('warn', applied + ' field diisi dari KTP dan ditandai '
        + 'PERLU DITINJAU. Periksa & ubah bila salah; dokumen tidak dapat '
        + 'dibuat sampai nilai ini dikonfirmasi/diperbaiki.'
        + (skipped ? ' (' + skipped + ' dilewati.)' : ''));
    } else {
      showMessage('err', 'Tidak ada field yang diterapkan.');
    }
    ocrEl('ocr-review').hidden = true;
  }

  function wireOcr(){
    var file = ocrEl('ocr-file');
    if(!file){ return; }
    file.addEventListener('change', ocrFileSelected);
    ocrEl('ocr-run').addEventListener('click', ocrRun);
    ocrEl('ocr-apply').addEventListener('click', ocrApply);
    ocrEl('ocr-clear').addEventListener('click', function(){
      ocrEl('ocr-review').hidden = true;
    });
    ocrEl('ocr-role').addEventListener('change', function(){
      // Peran berubah -> hasil lama tidak lagi relevan.
      ocrEl('ocr-review').hidden = true;
      ocrSetError('');
    });
    // Mode lokal <-> AI: tampilkan panel AI + persetujuan hanya bila dipilih.
    document.querySelectorAll('input[name=ocr-mode]').forEach(function(rd){
      rd.addEventListener('change', ocrApplyMode);
    });
    ocrEl('ocr-consent').addEventListener('change', ocrUpdateRunButton);
    ocrLoadStatus();
  }

  wireOcr();
})();
"""
