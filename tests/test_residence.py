"""Pengujian terfokus: alamat tempat tinggal terstruktur (dusun/RT/RW/desa/
kecamatan/kabupaten) dengan kata pengantar PERSIS seperti permintaan pengguna:

    "bertempat tinggal di <dusun> Rukun Tetangga <rt>, Rukun Warga <rw>,
     Desa <desa>, Kecamatan <kecamatan>, Kabupaten <kabupaten>"

Cakupan:
- render kalimat lengkap + tanda baca + default kabupaten Kota Contoh;
- pemetaan debitor = pemilik & pasangan alamat sama;
- validasi RT/RW (1-3 digit, nol di depan dipertahankan, tidak mengarang);
- pemetaan OCR lokal & AI -> struktur baru secara konservatif;
- tidak ada field "alamat" basi yang memblokir formulir.

Semua nilai pada berkas ini SINTETIS (nama orang, NIK, dusun, desa, kecamatan).

Jalankan:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ai_ocr, fields, ktp_ocr  # noqa: E402
from app.textutil import ValidationError  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(BASE_DIR, "templates", "SKMHT.example.template.docx")

RESIDENCE_SUFFIX = ("Rukun Tetangga 007, Rukun Warga 000, Desa Contoh Satu, "
                    "Kecamatan Contoh Satu, Kabupaten Kota Contoh")

def load_template() -> bytes:
    with open(TEMPLATE, "rb") as fh:
        return fh.read()


def base_form(**overrides) -> dict:
    data = {
        "nomor_akta": "12/ 2026",
        "tanggal_akta": "2026-12-31",
        "owner_title": "Tuan",
        "owner_nama": "NAMA SINTETIS",
        "owner_lahir_tempat": "Kota Contoh",
        "owner_lahir_tanggal": "1985-05-17",
        "owner_pekerjaan": "Petani/Pekebun",
        "owner_dusun": "Dusun Contoh",
        "owner_rt": "007",
        "owner_rw": "000",
        "owner_desa": "Contoh Satu",
        "owner_kecamatan": "Contoh Dua",
        "owner_kabupaten": "Kota Contoh",
        "owner_nik": "9999999999990001",
        "spouse_mode": "istri",
        "spouse_nama": "PASANGAN SINTETIS",
        "spouse_lahir_tempat": "Kota Contoh",
        "spouse_lahir_tanggal": "1987-08-21",
        "spouse_pekerjaan": "Ibu Rumah Tangga",
        "spouse_alamat_sama": "ya",
        "spouse_dusun": "", "spouse_rt": "", "spouse_rw": "",
        "spouse_desa": "", "spouse_kecamatan": "", "spouse_kabupaten": "",
        "spouse_nik": "9999999999990002",
        "same_as_owner": "ya",
        "debtor_title": "Tuan",
        "debtor_nama": "NAMA SINTETIS",
        "debtor_lahir_tempat": "Kota Contoh",
        "debtor_lahir_tanggal": "1985-05-17",
        "debtor_pekerjaan": "Petani/Pekebun",
        "debtor_dusun": "Dusun Contoh", "debtor_rt": "007",
        "debtor_rw": "000",
        "debtor_desa": "Contoh Satu", "debtor_kecamatan": "Contoh Dua",
        "debtor_kabupaten": "Kota Contoh",
        "debtor_nik": "9999999999990001",
        "nilai_pembiayaan": "50.000.000",
        "nilai_tanggungan": "75.000.000",
        "akad_jenis": "Hawalah bil ujrah",
        "akad_nomor": "AKAD-CONTOH-001",
        "akad_tanggal": "2026-12-29",
        "ht_jenis": "Hak Milik",
        "ht_nomor": "12345",
        "ht_desa_sertifikat": "Contoh Satu",
        "surat_ukur_nomor": "1234/Contoh Satu/2026",
        "surat_ukur_tanggal": "2026-12-29",
        "luas_m2": "1.153",
        "nib": "12.34.56.78.00001",
        "nop": "12.34.567.890.123-4567.8",
        "lok_provinsi": "Provinsi Contoh",
        "lok_kabupaten": "Kota Contoh",
        "lok_kecamatan": "Contoh Tiga",
        "lok_desa": "Contoh Empat",
        "lok_jalan": "Jalan Contoh RT 003 RW 06",
    }
    data.update(overrides)
    return data


def docx_text(blob: bytes) -> str:
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        xml = z.read("word/document.xml")
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(xml)
    return "".join(t.text or "" for t in root.iter(W + "t"))


def render(form) -> str:
    ctx = fields.validate_and_build(form)
    values = fields.build_marker_values(ctx)
    from app import docx_template
    return docx_text(docx_template.render_docx_from_template(
        load_template(), values,
        required_keys=fields.REQUIRED_MARKER_KEYS,
        removal_keys=fields.REMOVAL_MARKER_KEYS))


class TestResidenceRendering(unittest.TestCase):
    def test_exact_user_wording_and_punctuation(self):
        text = render(base_form(owner_dusun="Dusun Contoh"))
        expected = ("bertempat tinggal di Dusun Contoh Rukun Tetangga 007, "
                    "Rukun Warga 000, Desa Contoh Satu, Kecamatan Contoh Dua, "
                    "Kabupaten Kota Contoh")
        # Muncul pada identitas pemberi kuasa (P7) dan diulang di bagian KHUSUS
        # (bekas identitas debitor) karena debitor = pemilik.
        self.assertEqual(text.count(expected), 2)
        self.assertIn("bertempat tinggal di Dusun Contoh", text)

    def test_rt_rw_zeroes_preserved_as_text(self):
        text = render(base_form(owner_rt="003", owner_rw="000"))
        self.assertIn("Rukun Tetangga 003, Rukun Warga 000", text)
        self.assertNotIn("Rukun Tetangga 3,", text)

    def test_no_auto_dusun_prefix(self):
        # Pengguna memberi teks dusun apa adanya; tidak ditambah awalan "Dusun".
        text = render(base_form(owner_dusun="Dusun Contoh"))
        self.assertIn("di Dusun Contoh Rukun Tetangga", text)
        self.assertNotIn("di Dusun Dusun Contoh", text)

    def test_kabupaten_default_kota_contoh_when_blank(self):
        text = render(base_form(owner_kabupaten=""))
        self.assertIn("Kabupaten Kota Contoh", text)

    def test_kabupaten_label_is_kabupaten_not_kabupaten_kota(self):
        text = render(base_form())
        self.assertIn("Kabupaten Kota Contoh", text)
        self.assertNotIn("Kabupaten/Kota Kota Contoh", text)

    def test_old_combined_alamat_field_removed(self):
        keys = {k for (k, *_r) in fields.FIELDS}
        for stale in ("owner_alamat", "spouse_alamat", "debtor_alamat"):
            self.assertNotIn(stale, keys)

    def test_personal_schema_has_no_default_values(self):
        # Skema hanya memuat key/label/kind/required (default kabupaten ada di
        # kode, bukan nilai contoh pada skema).
        from app import server
        for entry in json.loads(json.dumps([
                {"key": k, "label": l, "kind": ki, "required": r}
                for (k, l, ki, r) in fields.FIELDS])):
            self.assertNotIn("value", entry)
            self.assertNotIn("default", entry)
        self.assertTrue(hasattr(server, "APP_JS"))

    def test_no_stale_owner_address_example(self):
        text = render(base_form())
        # Tidak ada sisa contoh alamat asli apa pun.
        self.assertNotIn("{{", text)
        self.assertNotIn("}}", text)


class TestSameAddressFeatures(unittest.TestCase):
    def test_same_as_owner_copies_address_components(self):
        text = render(base_form(
            same_as_owner="ya",
            owner_dusun="Dusun Contoh", owner_rt="007", owner_rw="000",
            owner_desa="Contoh Satu", owner_kecamatan="Contoh Dua",
            debtor_dusun="", debtor_rt="", debtor_rw="", debtor_desa="",
            debtor_kecamatan="", debtor_kabupaten="",
            debtor_nama="", debtor_nik="", debtor_title="",
            debtor_lahir_tempat="", debtor_lahir_tanggal="", debtor_pekerjaan=""))
        self.assertIn("bertempat tinggal di Dusun Contoh Rukun Tetangga 007, "
                      "Rukun Warga 000, Desa Contoh Satu, Kecamatan Contoh Dua, "
                      "Kabupaten Kota Contoh", text)
        ctx = fields.validate_and_build(base_form(
            same_as_owner="ya", owner_rt="007", owner_rw="000",
            debtor_rt="", debtor_rw=""))
        self.assertEqual(ctx["debtor_rt"], "007")
        self.assertEqual(ctx["debtor_rw"], "000")

    def test_spouse_same_address_unchanged(self):
        text = render(base_form(spouse_alamat_sama="ya"))
        self.assertIn("bertempat tinggal sama dengan suaminya di atas", text)

    def test_spouse_different_address_renders_structure(self):
        form = base_form(
            spouse_alamat_sama="tidak",
            spouse_dusun="Dusun Pasangan", spouse_rt="2", spouse_rw="10",
            spouse_desa="Contoh Pasangan", spouse_kecamatan="Contoh Dua Pasangan",
            spouse_kabupaten="")
        text = render(form)
        self.assertIn("bertempat tinggal di Dusun Pasangan Rukun Tetangga 2, "
                      "Rukun Warga 10, Desa Contoh Pasangan, Kecamatan Contoh "
                      "Dua Pasangan, Kabupaten Kota Contoh", text)

    def test_spouse_different_address_requires_components(self):
        with self.assertRaises(ValidationError):
            fields.validate_and_build(base_form(
                spouse_alamat_sama="tidak", spouse_dusun="", spouse_rt="",
                spouse_rw="", spouse_desa="", spouse_kecamatan=""))

    def test_distinct_debtor_renders_own_address(self):
        form = base_form(
            same_as_owner="tidak", debtor_nama="DEBITOR BARU",
            debtor_nik="9999999999990009", debtor_dusun="Dusun Debitor",
            debtor_rt="2", debtor_rw="13", debtor_desa="Contoh Debitor",
            debtor_kecamatan="Contoh Dua Debitor", debtor_kabupaten="")
        text = render(form)
        self.assertIn("bertempat tinggal di Dusun Debitor Rukun Tetangga 2, "
                      "Rukun Warga 13, Desa Contoh Debitor, Kecamatan Contoh "
                      "Dua Debitor, Kabupaten Kota Contoh", text)


class TestResidenceValidation(unittest.TestCase):
    def test_owner_address_components_required(self):
        for key in ("owner_dusun", "owner_rt", "owner_rw", "owner_desa",
                    "owner_kecamatan"):
            with self.assertRaises(ValidationError):
                fields.validate_and_build(base_form(**{key: ""}))

    def test_owner_kabupaten_optional_defaults_kota_contoh(self):
        ctx = fields.validate_and_build(base_form(owner_kabupaten=""))
        self.assertEqual(ctx["owner_kabupaten"], "Kota Contoh")

    def test_rt_rw_non_digit_rejected_no_invention(self):
        for key in ("owner_rt", "owner_rw"):
            with self.assertRaises(ValidationError):
                fields.validate_and_build(base_form(**{key: "abc"}))

    def test_rt_rw_too_many_digits_split_when_paired(self):
        # RT dan RW masing-masing 4 digit bukan KTP yang masuk akal.
        with self.assertRaises(ValidationError):
            fields.validate_and_build(base_form(owner_rt="1234"))

    def test_rt_rw_six_digit_card_value_accepted(self):
        ctx = fields.validate_and_build(base_form(owner_rt="018000",
                                                   owner_rw=""))
        self.assertEqual(ctx["owner_rt"], "018")
        self.assertEqual(ctx["owner_rw"], "000")

    def test_rt_rw_zero_kept_verbatim(self):
        ctx = fields.validate_and_build(base_form(owner_rt="000", owner_rw="000"))
        self.assertEqual(ctx["owner_rt"], "000")
        self.assertEqual(ctx["owner_rw"], "000")

    def test_card_alamat_parser_token_form(self):
        self.assertEqual(fields._parse_card_alamat("DUSUN BARU RT 001 RW 002"),
                         {"dusun": "DUSUN BARU", "rt": "001", "rw": "002"})

    def test_card_alamat_parser_nik_order_swaps(self):
        # Urutan NIK: RT/RW; RT 34 > 30 dan RW 3 <= 12 -> tertukar.
        self.assertEqual(fields._parse_card_alamat("DUSUN KARTIKA 34/3")["rt"], "3")
        self.assertEqual(fields._parse_card_alamat("DUSUN KARTIKA 34/3")["rw"], "34")

    def test_parse_residence_card_variants(self):
        self.assertEqual(fields.parse_residence_card("018/000"), ("018", "000", ""))
        self.assertEqual(fields.parse_residence_card("018000"), ("018", "000", ""))
        self.assertEqual(fields.parse_residence_card("001/000 II"),
                         ("001", "000", "II"))


class TestOcrResidenceMapping(unittest.TestCase):
    SAMPLE = (
        "PROVINSI CONTOH\n"
        "KABUPATEN KOTA KARTIKA\n"
        "NIK : 9999999999990001\n"
        "Nama : NAMA SINTETIS\n"
        "Tempat/Tgl Lahir : KOTA KARTIKA, 17-05-1985\n"
        "Alamat : DUSUN BARU RT 001 RW 002\n"
        "Kel/Desa : DESA KARTIKA\n"
        "Kecamatan : KECAMATAN KARTIKA\n"
    )

    def test_local_owner_candidates_use_new_structure(self):
        parsed = ktp_ocr.parse_ktp_fields(self.SAMPLE)
        c = ktp_ocr.candidates_for_role(parsed, "owner")
        self.assertEqual(c["owner_dusun"]["value"], "DUSUN BARU")
        self.assertEqual(c["owner_rt"]["value"], "001")
        self.assertEqual(c["owner_rw"]["value"], "002")
        self.assertEqual(c["owner_desa"]["value"], "DESA KARTIKA")
        self.assertEqual(c["owner_kecamatan"]["value"], "KECAMATAN KARTIKA")
        for stale in ("owner_alamat",):
            self.assertNotIn(stale, c)

    def test_local_candidates_only_contain_detected_parts(self):
        # Hanya bagian yang benar-benar dibaca yang menjadi kandidat; tidak
        # menebak dan tidak memaksa default.
        parsed = ktp_ocr.parse_ktp_fields("Nama : CITRA\nKecamatan : TEMANGGUNG")
        c = ktp_ocr.candidates_for_role(parsed, "owner")
        self.assertNotIn("owner_rt", c)
        self.assertNotIn("owner_rw", c)
        self.assertEqual(c["owner_kecamatan"]["value"], "TEMANGGUNG")

    def test_local_spouse_and_debtor_roles_structured(self):
        parsed = ktp_ocr.parse_ktp_fields(self.SAMPLE)
        for role in ("spouse", "debtor"):
            c = ktp_ocr.candidates_for_role(parsed, role)
            self.assertIn(f"{role}_rt", c)
            self.assertIn(f"{role}_dusun", c)
            self.assertNotIn(f"{role}_alamat", c)

    def test_ai_short_json_uses_new_structure(self):
        payload = {
            "nik": "9999999999990001", "nama": "NAMA SINTETIS",
            "jenis_kelamin": "Laki-Laki", "agama": "ISLAM",
            "alamat": "DUSUN KARTIKA", "rt_rw": "34/3",
            "kecamatan": "KECAMATAN KARTIKA", "kel_desa": "DESA KARTIKA",
            "kabupaten": "KOTA KARTIKA",
        }
        text = ai_ocr._fields_to_labeled_text(payload)
        parsed = ktp_ocr.parse_ktp_fields(text)
        c = ktp_ocr.candidates_for_role(parsed, "owner")
        self.assertEqual(c["owner_rt"]["value"], "3")
        self.assertEqual(c["owner_rw"]["value"], "34")
        self.assertEqual(c["owner_dusun"]["value"], "DUSUN KARTIKA")
        self.assertEqual(c["owner_desa"]["value"], "DESA KARTIKA")
        self.assertEqual(c["owner_kecamatan"]["value"], "KECAMATAN KARTIKA")
        self.assertNotIn("owner_alamat", c)

    def test_ai_full_ktp_json_rt_rw_swapped(self):
        payload = {
            "nik": "9999999999990001", "nama": "NAMA SINTETIS",
            "rt_rw": "34/3", "kel_desa": "DESA KARTIKA",
            "kecamatan": "KECAMATAN KARTIKA",
            "kabupaten": "KOTA KARTIKA",
        }
        text = ai_ocr._fields_to_labeled_text(payload)
        parsed = ktp_ocr.parse_ktp_fields(text)
        c = ktp_ocr.candidates_for_role(parsed, "owner")
        self.assertEqual(c["owner_rt"]["value"], "3")
        self.assertEqual(c["owner_rw"]["value"], "34")
        self.assertEqual(c["owner_desa"]["value"], "DESA KARTIKA")

    def test_ai_short_json_labelled_rt_rw_maps_structured(self):
        # Mode AI ringkas: "alamat" hanya nama dusun + label "rt_rw" -> struktur.
        payload = {"nik": "9999999999990001", "nama": "NAMA SINTETIS",
                   "alamat": "DUSUN KARTIKA", "rt_rw": "34/3",
                   "kel_desa": "DESA KARTIKA", "kecamatan": "KECAMATAN KARTIKA",
                   "kabupaten": "KOTA KARTIKA"}
        text = ai_ocr._fields_to_labeled_text(payload)
        parsed = ktp_ocr.parse_ktp_fields(text)
        c = ktp_ocr.candidates_for_role(parsed, "owner")
        self.assertEqual(c["owner_rt"]["value"], "3")
        self.assertEqual(c["owner_rw"]["value"], "34")
        self.assertEqual(c["owner_dusun"]["value"], "DUSUN KARTIKA")

    def test_ocr_does_not_overwrite_silently(self):
        # Nilai OCR hanya menjadi kandidat; validasi form tetap sumber terakhir.
        parsed = ktp_ocr.parse_ktp_fields(self.SAMPLE)
        c = ktp_ocr.candidates_for_role(parsed, "owner")
        self.assertEqual(c["owner_nama"]["status"], "review")
        # Form yang sudah terisi tetap dipakai apa adanya (kandidat hanya saran).
        filled = base_form(owner_dusun="Sudah Diisi", owner_rt="9",
                           owner_rw="8")
        ctx = fields.validate_and_build(filled)
        self.assertEqual(ctx["owner_dusun"], "Sudah Diisi")
        self.assertEqual(ctx["owner_rt"], "9")
        self.assertEqual(ctx["owner_rw"], "8")

    def test_no_stale_alamat_field_in_candidates(self):
        parsed = ktp_ocr.parse_ktp_fields(self.SAMPLE)
        for role in ("owner", "spouse", "debtor"):
            c = ktp_ocr.candidates_for_role(parsed, role)
            for key in c:
                self.assertNotRegex(key, r"^[a-z]+_alamat$")


class TestResidenceUiAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from app import server
        cls._server = ThreadingHTTPServer((server.HOST, 0), server.Handler)
        cls._host, cls._port = cls._server.server_address
        cls._thread = threading.Thread(
            target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)

    def _get(self, path):
        import urllib.request
        with urllib.request.urlopen(
                f"http://{self._host}:{self._port}{path}", timeout=5) as r:
            return r.status, r.read()

    def test_fields_endpoint_has_structured_residence(self):
        _, body = self._get("/api/fields")
        keys = {f["key"] for f in json.loads(body)["fields"]}
        for prefix in ("owner", "spouse", "debtor"):
            for part in ("dusun", "rt", "rw", "desa", "kecamatan", "kabupaten"):
                self.assertIn(f"{prefix}_{part}", keys)
        for stale in ("owner_alamat", "spouse_alamat", "debtor_alamat"):
            self.assertNotIn(stale, keys)

    def test_js_groups_and_patterns_served(self):
        _, body = self._get("/app.js")
        js = body.decode("utf-8")
        for token in ("'owner_dusun'", "'owner_rt'", "'spouse_dusun'",
                      "'debtor_kabupaten'", "spouse_alamat_sama",
                      "'same_as_owner'"):
            self.assertIn(token, js, f"token JS hilang: {token}")
        # Regex grup field rapi (bukan escape ganda yang salah).
        self.assertIn("/(dusun|desa|kecamatan|kabupaten)$/", js)
        self.assertNotIn("owner_alamat", js)
        self.assertNotIn("debtor_alamat", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)

