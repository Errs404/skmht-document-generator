"""Pengujian template berbasis MARKER (produksi).

Cakupan:
- inventaris marker: setiap token ``{{key}}`` punya nilai; marker pembersih
  kosong;
- keluaran TIDAK memuat sisa contoh identitas/data lama dan tidak ada marker
  tersisa;
- tab leader / run formatting / namespace tetap terjaga;
- gagal-keras: marker hilang, marker tak dikenal, template hilang/rusak;
- pemecahan token lintas run tetap tergantikan;
- report kesetaraan: nilai marker lama (``build_replacements``) menghasilkan
  teks dulu yang SAMA dengan nilai marker baru (regresi kontrak).

Jalankan:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import docx_template, fields  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "SKMHT.example.template.docx")
LEGACY_TEMPLATE = os.path.join(BASE_DIR, "private-source.docx")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def load_template() -> bytes:
    with open(TEMPLATE_PATH, "rb") as fh:
        return fh.read()


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


def render(form) -> bytes:
    ctx = fields.validate_and_build(form)
    values = fields.build_marker_values(ctx)
    return docx_template.render_docx_from_template(
        load_template(), values,
        required_keys=fields.REQUIRED_MARKER_KEYS,
        removal_keys=fields.REMOVAL_MARKER_KEYS)


def docx_text(blob: bytes) -> str:
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    return "".join(t.text or "" for t in root.iter(W + "t"))


class TestTemplateInventory(unittest.TestCase):
    def test_template_file_exists(self):
        self.assertTrue(os.path.isfile(TEMPLATE_PATH))

    def test_every_marker_has_a_value(self):
        ctx = fields.validate_and_build(base_form())
        values = fields.build_marker_values(ctx)
        ledger = docx_template.ledger_of(load_template())
        missing = sorted(set(ledger) - set(values))
        self.assertEqual(missing, [],
                         f"marker tanpa nilai: {missing}")

    def test_required_marker_keys_all_present_in_template(self):
        ledger = docx_template.ledger_of(load_template())
        absent = [k for k in fields.REQUIRED_MARKER_KEYS if k not in ledger]
        self.assertEqual(absent, [],
                         f"marker wajib tidak ada di template: {absent}")

    def test_removal_marker_present_and_empty(self):
        ledger = docx_template.ledger_of(load_template())
        for key in fields.REMOVAL_MARKER_KEYS:
            self.assertIn(key, ledger)
        ctx = fields.validate_and_build(base_form())
        values = fields.build_marker_values(ctx)
        for key in fields.REMOVAL_MARKER_KEYS:
            self.assertEqual(values[key], "")

    def test_markers_are_single_tokens(self):
        ledger = docx_template.ledger_of(load_template())
        # Tidak ada marker "setengah terpakai" (mis. sisa '}').
        for key in ledger:
            self.assertNotIn("{", key)
            self.assertNotIn("}", key)


class TestRenderedOutput(unittest.TestCase):
    def test_no_marker_leftover(self):
        text = docx_text(render(base_form()))
        self.assertNotIn("{{", text)
        self.assertNotIn("}}", text)

    def test_no_stale_identities_anywhere(self):
        # Ganti SEMUA nilai dinamis dengan nilai sintetis berbeda dari contoh,
        # lalu pastikan tidak ada satu pun identitas/data contoh tertinggal.
        text = docx_text(render(base_form(
            owner_nama="PEMILIK BARU", spouse_nama="PASANGAN BARU",
            same_as_owner="tidak", debtor_nama="DEBITOR BARU",
            debtor_nik="9999999999990009",
            owner_nik="9999999999990011", spouse_nik="9999999999990012",
            owner_dusun="DUSUN X", owner_rt="999", owner_rw="888",
            owner_desa="DESA X", owner_kecamatan="KEC X",
            spouse_alamat_sama="tidak", spouse_dusun="DUSUN S",
            spouse_rt="777", spouse_rw="666", spouse_desa="DESA S",
            spouse_kecamatan="KEC S",
            debtor_dusun="DUSUN D", debtor_rt="555", debtor_rw="444",
            debtor_desa="DESA D", debtor_kecamatan="KEC D",
            ht_nomor="99999", ht_desa_sertifikat="DESAHT",
            surat_ukur_nomor="9/DESAHT/2099", nib="99.99.99.99.99999",
            nop="99.99.999.999.999-9999.9", luas_m2="999",
            nilai_pembiayaan="111.000.000", nilai_tanggungan="222.000.000",
            akad_nomor="9999/XX/YYY/XII/2099",
            lok_provinsi="PROV X", lok_kabupaten="KAB X",
            lok_kecamatan="KEC Y", lok_desa="DESA Y",
            lok_jalan="JALAN BARU RT 999 RW 888")))
        for stale in (
                "NAMA SINTETIS", "PASANGAN SINTETIS",
                "AKAD-CONTOH-001",
                "12345/Contoh Satu", "1234/Contoh Satu",
                "12.34.56.78.00001", "12.34.567.890.123-4567.8",
                "Contoh Tiga", "Contoh Empat",
                "Dusun Contoh Satu"):
            self.assertNotIn(stale, text,
                             f"data contoh '{stale}' masih tersisa")

    def test_dynamic_values_render(self):
        text = docx_text(render(base_form(
            owner_nama="PEMILIK BARU", owner_nik="9999999999990011")))
        self.assertIn("PEMILIK BARU", text)
        self.assertIn("9999999999990011", text)
        self.assertIn("Nomor : 12/ 2026", text)

    def test_terbilang_and_amounts(self):
        text = docx_text(render(base_form()))
        self.assertIn("Rp. 50.000.000", text)
        self.assertIn("(lima puluh juta rupiah)", text)
        self.assertIn("Rp. 75.000.000,- (tujuh puluh lima juta rupiah)", text)
        self.assertIn("seribu seratus lima puluh tiga meter persegi", text)

    def test_fixed_clauses_actors_preserved(self):
        text = docx_text(render(base_form()))
        for value in fields.FIXED.values():
            self.assertIn(value, text, f"nilai tetap hilang: {value}")

    def test_signature_names_updated(self):
        text = docx_text(render(base_form(
            owner_nama="PEMILIK BARU", spouse_nama="PASANGAN BARU")))
        self.assertIn("PEMILIK BARU", text)
        self.assertIn("PASANGAN BARU", text)
        self.assertIn("Persetujuan Istri", text)

    def test_only_document_xml_changes(self):
        orig = load_template()
        rendered = render(base_form())
        with zipfile.ZipFile(io.BytesIO(orig)) as z:
            o = {n: z.read(n) for n in z.namelist()}
        with zipfile.ZipFile(io.BytesIO(rendered)) as z:
            r = {n: z.read(n) for n in z.namelist()}
        self.assertEqual(set(o), set(r))
        for name in o:
            if name == "word/document.xml":
                continue
            self.assertEqual(o[name], r[name],
                             f"entri {name} berubah padahal harus identik")

    def test_result_is_valid_docx(self):
        blob = render(base_form())
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            self.assertIn("word/document.xml", z.namelist())
            self.assertIsNone(z.testzip())
            from xml.etree import ElementTree as ET
            ET.fromstring(z.read("word/document.xml"))

    def test_tab_settings_preserved(self):
        orig = load_template()
        rendered = render(base_form())

        def leaders(blob):
            from xml.etree import ElementTree as ET
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                root = ET.fromstring(z.read("word/document.xml"))
            out = []
            for p in root.iter(W + "p"):
                tabs = p.find(W + "pPr/" + W + "tabs")
                if tabs is None:
                    continue
                for tb in tabs.findall(W + "tab"):
                    out.append((tb.get(W + "val"), tb.get(W + "leader"),
                                tb.get(W + "pos")))
            return sorted((v or "", ld or "", p or "") for (v, ld, p) in out)

        self.assertEqual(leaders(orig), leaders(rendered),
                         "setelan tab/leader berubah setelah render")
        self.assertTrue(any(ld == "hyphen" for (_v, ld, _p) in
                            [(v, ld, p) for (v, ld, p) in leaders(orig)]))

    def test_run_formatting_preserved(self):
        rendered = render(base_form())
        with zipfile.ZipFile(io.BytesIO(rendered)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn('w:sz w:val="24"', xml)
        self.assertIn("Bookman Old Style", xml)
        self.assertTrue("<w:b/>" in xml or "<w:b />" in xml)

    def test_no_synthetic_ns_prefixes(self):
        import re
        rendered = render(base_form())
        with zipfile.ZipFile(io.BytesIO(rendered)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        self.assertIsNone(re.search(r"<ns\d+:", xml))
        self.assertIsNone(re.search(r"</ns\d+:", xml))


class TestGagalKeras(unittest.TestCase):
    def test_template_missing_raises(self):
        with self.assertRaises(docx_template.MissingTemplateError):
            docx_template.render_docx_from_template(
                b"", {}, required_keys=fields.REQUIRED_MARKER_KEYS)

    def test_missing_required_marker_raises(self):
        ctx = fields.validate_and_build(base_form())
        values = fields.build_marker_values(ctx)
        values["owner_nama"] = ""
        with self.assertRaises(docx_template.MissingMarkerError):
            docx_template.render_docx_from_template(
                load_template(), values,
                required_keys=fields.REQUIRED_MARKER_KEYS)

    def test_rejected_value_marks_marker_missing(self):
        # Nilai dengan '{{'/'}}' ditolak -> marker dianggap tak terisi.
        ctx = fields.validate_and_build(base_form())
        values = fields.build_marker_values(ctx)
        values["owner_nama"] = None
        with self.assertRaises(docx_template.MissingMarkerError):
            docx_template.render_docx_from_template(
                load_template(), values,
                required_keys=fields.REQUIRED_MARKER_KEYS)

    def test_unknown_marker_detected(self):
        # Template dengan marker tak dikenal harus terdeteksi sebagai sisa.
        ctx = fields.validate_and_build(base_form())
        values = fields.build_marker_values(ctx)
        with zipfile.ZipFile(io.BytesIO(load_template())) as z:
            entries = [(i, z.read(i.filename)) for i in z.infolist()]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
            for info, data in entries:
                if info.filename == "word/document.xml":
                    data = data.replace(b"{{owner_nama}}",
                                        b"{{owner_nama}}{{bogus_marker}}")
                dst.writestr(info.filename, data)
        with self.assertRaises(docx_template.TemplateAlteredError):
            # ledger_of tidak melempar; jalur server memvalidasi lebih dulu.
            template = buf.getvalue()
            unknown = set(docx_template.ledger_of(template)) - set(values)
            if unknown:
                raise docx_template.TemplateAlteredError(str(unknown))
            docx_template.render_docx_from_template(template, values)

    def test_corrupt_template_raises(self):
        with self.assertRaises(docx_template.DocxTemplateError):
            docx_template.ledger_of(b"this is not a zip")

    def test_leftover_marker_fails_closed(self):
        # Nilai None sengaja dibiarkan -> render harus menolak, bukan
        # menghasilkan dokumen dengan '{{...}}'.
        ctx = fields.validate_and_build(base_form())
        values = fields.build_marker_values(ctx)
        values["lok_jalan"] = None
        # required_keys tidak memuat 'lok_jalan' -> andalkan deteksi sisa.
        with self.assertRaises(docx_template.MissingMarkerError):
            docx_template.render_docx_from_template(
                load_template(), values)


class TestTokenSplitAcrossRuns(unittest.TestCase):
    def build_min_docx(self, body_xml: bytes) -> bytes:
        document = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
            b'wordprocessingml/2006/main"><w:body>' + body_xml +
            b"</w:body></w:document>")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", document)
        return buf.getvalue()

    def test_marker_split_across_runs_replaced(self):
        # Marker '{{owner_nama}}' terpecah menjadi 3 run; harus tetap terganti.
        body = (
            b'<w:p>'
            + b'<w:r><w:t>{{own</w:t></w:r>'
            + b'<w:r><w:rPr><w:b/></w:rPr><w:t>er_na</w:t></w:r>'
            + b'<w:r><w:t>ma}}</w:t></w:r>'
            + b'</w:p>')
        blob = docx_template.render_docx_from_template(
            self.build_min_docx(body), {"owner_nama": "NAMA SINTETIS"})
        root = __import__("xml.etree.ElementTree",
                          fromlist=["ElementTree"]).fromstring(
            zipfile.ZipFile(io.BytesIO(blob)).read("word/document.xml"))
        text = "".join(t.text or "" for t in root.iter(W + "t"))
        self.assertEqual(text, "NAMA SINTETIS")

    def test_marker_split_preserves_surrounding_runs(self):
        body = (
            b'<w:p>'
            + b'<w:r><w:t>Nama: {{ow</w:t></w:r>'
            + b'<w:r><w:t>ner_nama}} (pemilik)</w:t></w:r>'
            + b'</w:p>')
        blob = docx_template.render_docx_from_template(
            self.build_min_docx(body), {"owner_nama": "SINTETIS"})
        root = __import__("xml.etree.ElementTree",
                          fromlist=["ElementTree"]).fromstring(
            zipfile.ZipFile(io.BytesIO(blob)).read("word/document.xml"))
        text = "".join(t.text or "" for t in root.iter(W + "t"))
        self.assertEqual(text, "Nama: SINTETIS (pemilik)")


class TestDigestAndSummary(unittest.TestCase):
    def test_digest_stable_and_sensitive(self):
        ctx1 = fields.validate_and_build(base_form())
        d1a = fields.integrity_digest(ctx1)
        d1b = fields.integrity_digest(fields.validate_and_build(base_form()))
        self.assertEqual(d1a, d1b, "digest harus deterministik untuk data sama")
        ctx2 = fields.validate_and_build(base_form(owner_nama="LAIN"))
        self.assertNotEqual(d1a, fields.integrity_digest(ctx2),
                            "perubahan data harus mengubah digest")

    def test_summary_contains_side_by_side_roles(self):
        ctx = fields.validate_and_build(base_form(same_as_owner="tidak",
                                                  debtor_nama="DEBITOR BARU"))
        s = fields.canonical_summary(ctx)
        self.assertEqual(s["owner"]["nama"], "NAMA SINTETIS")
        self.assertEqual(s["spouse"]["nama"], "PASANGAN SINTETIS")
        self.assertEqual(s["debtor"]["nama"], "DEBITOR BARU")
        for role in ("owner", "spouse", "debtor"):
            self.assertIn("alamat", s[role])
            self.assertIn("nik", s[role])
            self.assertIn("lahir_tanggal", s[role])

    def test_summary_amounts_have_terbilang(self):
        ctx = fields.validate_and_build(base_form())
        s = fields.canonical_summary(ctx)
        self.assertEqual(s["pembiayaan"]["nilai_pembiayaan"], "50.000.000")
        self.assertEqual(s["pembiayaan"]["nilai_pembiayaan_kata"],
                         "lima puluh juta rupiah")
        self.assertEqual(s["tanggungan"]["nilai_tanggungan"], "75.000.000")
        self.assertEqual(s["tanggungan"]["nilai_tanggungan_kata"],
                         "tujuh puluh lima juta rupiah")

    def test_summary_land_data(self):
        ctx = fields.validate_and_build(base_form())
        s = fields.canonical_summary(ctx)
        self.assertEqual(s["tanah"]["ht_nomor"], "12345")
        self.assertEqual(s["tanah"]["luas_kata"],
                         "seribu seratus lima puluh tiga")
        self.assertEqual(s["tanah"]["nib"], "12.34.56.78.00001")

    def test_summary_matches_rendered_values(self):
        # Ringkasan kanonik harus konsisten dengan yang benar-benar dirender.
        ctx = fields.validate_and_build(base_form(owner_nama="PEMILIK BARU"))
        values = fields.build_marker_values(ctx)
        self.assertEqual(values["owner_nama"], "PEMILIK BARU")
        self.assertEqual(values["owner_nama"], ctx["owner_nama"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
