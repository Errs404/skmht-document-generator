"""Pengujian alur draf & gerbang tinjauan/persetujuan (integritas data).

Cakupan:
- Skema draf: sanitasi (hanya key dikenal), penolakan key sensitif
  (gambar/KTP/kunci API/OCR), batas ukuran, versi skema, JSON rusak;
- impor gagal-keras: berkas tidak valid -> TIDAK ada penimpaan sebagian;
- impor menandai SETIAP nilai ``needs_review`` (tinjauan ulang wajib);
- gerbang tinjauan server: generate ditolak tanpa tinjauan, setelah drift,
  dan tanpa persetujuan akhir ber-digest;
- persetujuan terikat digest (bukan checkbox): digest salah -> ditolak;
- data OCR belum dikonfirmasi memblokir pembuatan dokumen;
- tidak ada klaim enkripsi / penyimpanan otomatis pada aset UI.

Jalankan:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import drafts, fields, server  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def base_form(**overrides) -> dict:
    data = {
        "nomor_akta": "12/ 2026", "tanggal_akta": "2026-12-31",
        "owner_title": "Tuan", "owner_nama": "NAMA SINTETIS",
        "owner_lahir_tempat": "Kota Contoh", "owner_lahir_tanggal": "1985-05-17",
        "owner_pekerjaan": "Petani/Pekebun", "owner_dusun": "Dusun Contoh",
        "owner_rt": "001", "owner_rw": "002", "owner_desa": "Contoh Satu",
        "owner_kecamatan": "Contoh Dua", "owner_kabupaten": "Kota Contoh",
        "owner_nik": "9999999999990001",
        "spouse_mode": "istri", "spouse_nama": "PASANGAN SINTETIS",
        "spouse_lahir_tempat": "Kota Contoh",
        "spouse_lahir_tanggal": "1987-08-21",
        "spouse_pekerjaan": "Ibu Rumah Tangga", "spouse_alamat_sama": "ya",
        "spouse_dusun": "", "spouse_rt": "", "spouse_rw": "",
        "spouse_desa": "", "spouse_kecamatan": "", "spouse_kabupaten": "",
        "spouse_nik": "9999999999990002",
        "same_as_owner": "ya", "debtor_title": "Tuan",
        "debtor_nama": "NAMA SINTETIS", "debtor_lahir_tempat": "Kota Contoh",
        "debtor_lahir_tanggal": "1985-05-17",
        "debtor_pekerjaan": "Petani/Pekebun", "debtor_dusun": "Dusun Contoh",
        "debtor_rt": "001", "debtor_rw": "002", "debtor_desa": "Contoh Satu",
        "debtor_kecamatan": "Contoh Dua", "debtor_kabupaten": "Kota Contoh",
        "debtor_nik": "9999999999990001",
        "nilai_pembiayaan": "50.000.000", "nilai_tanggungan": "75.000.000",
        "akad_jenis": "Hawalah bil ujrah",
        "akad_nomor": "AKAD-CONTOH-001", "akad_tanggal": "2026-12-29",
        "ht_jenis": "Hak Milik", "ht_nomor": "12345",
        "ht_desa_sertifikat": "Contoh Satu",
        "surat_ukur_nomor": "1234/Contoh Satu/2026",
        "surat_ukur_tanggal": "2026-12-29", "luas_m2": "1.153",
        "nib": "12.34.56.78.00001", "nop": "12.34.567.890.123-4567.8",
        "lok_provinsi": "Provinsi Contoh", "lok_kabupaten": "Kota Contoh",
        "lok_kecamatan": "Contoh Tiga", "lok_desa": "Contoh Empat",
        "lok_jalan": "Jalan Contoh RT 003 RW 06",
    }
    data.update(overrides)
    return data


class TestDraftSchema(unittest.TestCase):
    def test_build_draft_keeps_only_known_keys(self):
        blob = drafts.draft_to_json(base_form())
        obj = json.loads(blob)
        self.assertEqual(obj["kind"], drafts.KIND)
        self.assertEqual(obj["schema_version"], drafts.SCHEMA_VERSION)
        keys = set(obj["data"])
        self.assertTrue(keys.issubset(fields.FIELD_KEYS))
        self.assertIn("owner_nama", keys)

    def test_never_includes_sensitive_markers(self):
        form = base_form()
        form["image_base64"] = "AAAA"
        form["ktp_image"] = "data:image/png;base64,AAAA"
        form["api_key"] = "secret-key"
        form["raw_ocr_text"] = "NIK 123"
        form["authorization"] = "Bearer x"
        form["_review_data"] = {"owner_nama": {"value": "X"}}
        form["_reviewed"] = True
        blob = drafts.draft_to_json({k: v for k, v in form.items()
                                     if not k.startswith("_")})
        text = blob.decode("utf-8")
        for forbidden in ("image_base64", "ktp_image", "api_key",
                          "raw_ocr_text", "authorization", "_review_data",
                          "secret-key", "data:image"):
            self.assertNotIn(forbidden, text,
                             f"penanda sensitif '{forbidden}' masuk draf")

    def test_unknown_keys_dropped(self):
        obj = drafts.build_draft({"owner_nama": "X", "tidak_ada": "Y",
                                  "lol": "Z"})
        self.assertIn("owner_nama", obj["data"])
        self.assertNotIn("tidak_ada", obj["data"])
        self.assertNotIn("lol", obj["data"])

    def test_oversized_value_rejected(self):
        with self.assertRaises(drafts.DraftError):
            drafts.build_draft({"owner_nama": "x" * 5000})

    def test_parse_rejects_broken_json(self):
        with self.assertRaises(drafts.DraftError):
            drafts.parse_draft(b"{not json")

    def test_parse_rejects_wrong_kind(self):
        with self.assertRaises(drafts.DraftError):
            drafts.parse_draft(json.dumps({"kind": "other",
                                           "schema_version": 1,
                                           "data": {}}).encode())

    def test_parse_rejects_unknown_schema_version(self):
        payload = {"kind": drafts.KIND, "schema_version": 99, "data": {}}
        with self.assertRaises(drafts.DraftError):
            drafts.parse_draft(json.dumps(payload).encode())

    def test_parse_rejects_oversized_file(self):
        big = b'{"kind":"skmht-draft","schema_version":1,"data":{"x":"' + \
            b"a" * (drafts.MAX_DRAFT_BYTES + 10) + b'"}}'
        with self.assertRaises(drafts.DraftError):
            drafts.parse_draft(big)

    def test_parse_rejects_non_object_data(self):
        payload = {"kind": drafts.KIND, "schema_version": 1, "data": [1, 2]}
        with self.assertRaises(drafts.DraftError):
            drafts.parse_draft(json.dumps(payload).encode())

    def test_roundtrip(self):
        original = base_form()
        blob = drafts.draft_to_json(original)
        parsed = drafts.parse_draft(blob)
        for key in original:
            if key in fields.FIELD_KEYS:
                self.assertEqual(parsed["data"][key], str(original[key]))


class TestReviewStatus(unittest.TestCase):
    def test_unreviewed_rejected(self):
        st = server._review_status(base_form())
        self.assertFalse(st["reviewed"])
        self.assertEqual(st["state"], "unreviewed")

    def test_reviewed_with_matching_digest(self):
        form = base_form()
        form["_reviewed"] = True
        form["_review_ts"] = int(time.time())
        form["_review_digest"] = server._form_fingerprint(form)
        st = server._review_status(form)
        self.assertTrue(st["reviewed"], st)
        self.assertEqual(st["state"], "reviewed")

    def test_drift_detected_on_edit(self):
        form = base_form()
        form["_reviewed"] = True
        form["_review_ts"] = int(time.time())
        form["_review_digest"] = server._form_fingerprint(form)
        form["owner_nama"] = "DIUBAH"   # edit setelah tinjauan
        st = server._review_status(form)
        self.assertFalse(st["reviewed"])
        self.assertTrue(st["drift"])
        self.assertEqual(st["state"], "changed")

    def test_stale_review_rejected(self):
        form = base_form()
        form["_reviewed"] = True
        form["_review_ts"] = 1  # kedaluwarsa
        form["_review_digest"] = server._form_fingerprint(form)
        st = server._review_status(form)
        self.assertFalse(st["reviewed"])
        self.assertTrue(st["stale"])


class TestAckToken(unittest.TestCase):
    def test_token_roundtrip(self):
        ctx = fields.validate_and_build(base_form())
        digest = fields.integrity_digest(ctx)
        tok = server._make_ack_token(digest, int(time.time()))
        self.assertTrue(server._verify_ack_token(tok, digest))

    def test_token_wrong_digest_rejected(self):
        tok = server._make_ack_token("abc", int(time.time()))
        self.assertFalse(server._verify_ack_token(tok, "def"))

    def test_token_forged_signature_rejected(self):
        digest = "abc"
        forged = f"{digest}.{int(time.time())}.deadbeef"
        self.assertFalse(server._verify_ack_token(forged, digest))

    def test_token_expired_rejected(self):
        digest = "abc"
        old = int(time.time()) - 100000
        tok = server._make_ack_token(digest, old)
        self.assertFalse(server._verify_ack_token(tok, digest))

    def test_token_malformed_rejected(self):
        self.assertFalse(server._verify_ack_token("notatoken", "abc"))


class TestDraftHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls._server = ThreadingHTTPServer((server.HOST, 0), server.Handler)
        cls._host, cls._port = cls._server.server_address
        cls._thread = threading.Thread(target=cls._server.serve_forever,
                                       daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)

    def _post(self, path, payload_bytes):
        req = urllib.request.Request(
            f"http://{self._host}:{self._port}{path}",
            data=payload_bytes, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def _review_ack(self, form):
        seq = 0
        while True:
            seq += 1
            self.assertLess(seq, 6)
            payload = dict(form)
            payload["_reviewed"] = True
            payload["_review_ts"] = int(time.time())
            status, body, _ = self._post(
                "/api/review", json.dumps(payload).encode())
            self.assertEqual(status, 200)
            j = json.loads(body)
            self.assertTrue(j["valid"], j.get("error"))
            if payload.get("_review_digest") == j["review"]["fingerprint"]:
                payload["confirm_summary"] = True
                payload["ack_digest"] = j["digest"]
                payload["ack_token"] = j["ack_token"]
                payload["summary_signature"] = j["summary_signature"]
                return payload
            form = payload
            form["_review_digest"] = j["review"]["fingerprint"]

    def test_draft_save_returns_json_attachment(self):
        status, body, headers = self._post(
            "/api/draft/save", json.dumps(base_form()).encode())
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"),
                         "application/json; charset=utf-8")
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        obj = json.loads(body)
        self.assertEqual(obj["kind"], drafts.KIND)

    def test_draft_import_marks_review_and_roundtrips(self):
        saved = drafts.draft_to_json(base_form()).decode("utf-8")
        status, body, _ = self._post(
            "/api/draft/import", json.dumps({"content": saved}).encode())
        self.assertEqual(status, 200)
        j = json.loads(body)
        self.assertTrue(j["ok"])
        self.assertEqual(j["data"]["owner_nama"], "NAMA SINTETIS")
        for key, entry in j["review_data"].items():
            self.assertTrue(entry["needs_review"])
            self.assertFalse(entry["confirmed"])

    def test_draft_import_rejects_malformed(self):
        status, body, _ = self._post(
            "/api/draft/import", json.dumps({"content": "{bad json"}).encode())
        self.assertEqual(status, 422)
        self.assertFalse(json.loads(body)["ok"])

    def test_draft_import_rejects_unknown_version(self):
        payload = json.dumps({"content": json.dumps(
            {"kind": drafts.KIND, "schema_version": 42, "data": {}})})
        status, body, _ = self._post("/api/draft/import", payload.encode())
        self.assertEqual(status, 422)
        self.assertIn("versi", json.loads(body)["error"].lower())

    def test_generate_rejected_without_review(self):
        status, body, _ = self._post(
            "/api/generate", json.dumps(base_form()).encode())
        self.assertEqual(status, 422)
        self.assertFalse(body.startswith(b"PK"))

    def test_generate_rejected_with_wrong_digest(self):
        # Lapisan 1 (tinjauan) menangkap drift lebih dulu: mengubah field
        # setelah setuju membuat digest tinjauan basi -> 422.
        form = self._review_ack(base_form())
        form["owner_nama"] = "DIUBAH SETELAH SETUJU"
        status, body, _ = self._post(
            "/api/generate", json.dumps(form).encode())
        self.assertEqual(status, 422)
        self.assertFalse(body.startswith(b"PK"))

    def test_generate_rejected_with_tampered_ack_digest(self):
        # Lapisan 2: bila tinjauan tetap "valid" tetapi ack_digest/ack_token
        # dipalsukan, gerbang digest menolak (409) — bukan sekadar checkbox.
        form = self._review_ack(base_form())
        form["ack_digest"] = "0" * 64
        status, body, _ = self._post(
            "/api/generate", json.dumps(form).encode())
        self.assertEqual(status, 409)
        self.assertFalse(body.startswith(b"PK"))

    def test_generate_rejected_without_ack_checkbox(self):
        # Tinjauan valid tetapi pernyataan persetujuan tidak dicentang.
        form = self._review_ack(base_form())
        form["confirm_summary"] = False
        status, body, _ = self._post(
            "/api/generate", json.dumps(form).encode())
        self.assertEqual(status, 422)

    def test_generate_ok_after_review_and_ack(self):
        form = self._review_ack(base_form())
        status, body, _ = self._post(
            "/api/generate", json.dumps(form).encode())
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"PK"))

    def test_generate_blocked_by_unconfirmed_ocr(self):
        form = self._review_ack(base_form())
        form["_review_data"] = {
            "owner_nama": {"value": "SINTETIS", "needs_review": True,
                           "confirmed": False}}
        status, body, _ = self._post(
            "/api/generate", json.dumps(form).encode())
        self.assertEqual(status, 422)
        self.assertIn("ocr", json.loads(body)["error"].lower())

    def test_review_endpoint_returns_canonical_summary(self):
        status, body, _ = self._post(
            "/api/review", json.dumps(base_form()).encode())
        self.assertEqual(status, 200)
        j = json.loads(body)
        self.assertTrue(j["valid"])
        self.assertEqual(j["summary"]["owner"]["nama"], "NAMA SINTETIS")
        self.assertEqual(j["summary"]["pembiayaan"]["nilai_pembiayaan_kata"],
                         "lima puluh juta rupiah")
        # Ringkasan kanonik memuat identitas berdampingan untuk 3 peran.
        for role in ("owner", "spouse", "debtor"):
            self.assertIn("nik", j["summary"][role])


class TestUiAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls._server = ThreadingHTTPServer((server.HOST, 0), server.Handler)
        cls._host, cls._port = cls._server.server_address
        cls._thread = threading.Thread(target=cls._server.serve_forever,
                                       daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)

    def _get(self, path):
        with urllib.request.urlopen(
                f"http://{self._host}:{self._port}{path}", timeout=5) as r:
            return r.status, r.read()

    def test_ui_has_draft_and_review_controls(self):
        _, body = self._get("/")
        html = body.decode("utf-8")
        for token in ("Simpan Draf", "Buka Draf", "Tinjau &amp; Kunci Data",
                      "draft-save", "draft-open", "review-btn", "ack-check"):
            self.assertIn(token, html, f"kontrol UI hilang: {token}")

    def test_ui_privacy_disclosure(self):
        _, body = self._get("/")
        html = body.decode("utf-8").lower()
        self.assertIn("tidak dienkripsi", html)
        self.assertIn("tidak menyimpan draf", html)

    def test_no_encryption_or_persistence_claims(self):
        for path in ("/", "/app.js"):
            _, body = self._get(path)
            text = body.decode("utf-8").lower()
            for forbidden in ("localstorage", "sessionstorage", "indexeddb",
                              "document.cookie"):
                self.assertNotIn(forbidden, text)
            self.assertNotIn("terenkripsi", text)
            self.assertNotIn("aman terenkripsi", text)
            self.assertNotIn("database terenkripsi", text)

    def test_js_uses_review_payload_fields(self):
        _, body = self._get("/app.js")
        js = body.decode("utf-8")
        for token in ("_reviewed", "_review_digest", "ack_digest", "ack_token",
                      "/api/review", "/api/draft/save", "/api/draft/import"):
            self.assertIn(token, js, f"token JS hilang: {token}")

    def test_template_status_endpoint(self):
        import json as _json
        _, body = self._get("/api/template/status")
        j = _json.loads(body)
        self.assertTrue(j["available"], j)
        self.assertEqual(j["unbound_markers"], [])
        self.assertEqual(j["missing_required"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
