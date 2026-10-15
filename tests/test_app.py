"""Pengujian terfokus (Standard Library) untuk Generator SKMHT lokal.

Jalankan:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import docx_template, fields, textutil  # noqa: E402
from app.textutil import ValidationError  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Template aktif adalah berkas revisi pengguna (tab leader menggantikan deret
# tanda hubung manual). Berkas asli "private-original.docx" TIDAK diubah.
TEMPLATE = os.path.join(BASE_DIR, "templates", "SKMHT.example.template.docx")


def load_template() -> bytes:
    with open(TEMPLATE, "rb") as fh:
        return fh.read()


def base_form(**overrides) -> dict:
    """Formulir valid minimum, dapat ditimpa sebagian."""
    data = {
        "nomor_akta": "12/ 2026",
        "tanggal_akta": "2026-12-31",
        "owner_title": "Tuan",
        "owner_nama": "NAMA SINTETIS",
        "owner_lahir_tempat": "Kota Contoh",
        "owner_lahir_tanggal": "1985-05-17",
        "owner_pekerjaan": "Petani/Pekebun",
        "owner_dusun": "Dusun Contoh",
        "owner_rt": "001",
        "owner_rw": "002",
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
        "debtor_dusun": "Dusun Contoh", "debtor_rt": "001", "debtor_rw": "002",
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


class TestTextUtil(unittest.TestCase):
    def test_terbilang_basic(self):
        self.assertEqual(textutil.terbilang(0), "nol")
        self.assertEqual(textutil.terbilang(1), "satu")
        self.assertEqual(textutil.terbilang(11), "sebelas")
        self.assertEqual(textutil.terbilang(15), "lima belas")
        self.assertEqual(textutil.terbilang(20), "dua puluh")
        self.assertEqual(textutil.terbilang(31), "tiga puluh satu")
        self.assertEqual(textutil.terbilang(100), "seratus")
        self.assertEqual(textutil.terbilang(153), "seratus lima puluh tiga")
        self.assertEqual(textutil.terbilang(1000), "seribu")
        self.assertEqual(
            textutil.terbilang(1153), "seribu seratus lima puluh tiga")
        self.assertEqual(
            textutil.terbilang(2026), "dua ribu dua puluh lima")
        self.assertEqual(textutil.terbilang(50000000), "lima puluh juta")
        self.assertEqual(
            textutil.terbilang(75000000), "tujuh puluh lima juta")

    def test_money(self):
        self.assertEqual(textutil.format_rupiah(75000000), "75.000.000")
        self.assertEqual(textutil.parse_amount("Rp 50.000.000"), 50000000)
        self.assertEqual(textutil.parse_amount("50000000"), 50000000)
        self.assertEqual(textutil.parse_amount("50 000 000"), 50000000)
        self.assertEqual(
            textutil.rupiah_words(50000000), "lima puluh juta rupiah")

    def test_date_words(self):
        d = dt.date(2026, 12, 31)
        self.assertEqual(textutil.day_name(d), "Rabu")
        self.assertEqual(textutil.month_name(12), "Desember")
        self.assertEqual(textutil.format_tanggal_singkat(d), "31-12-2026")
        full = textutil.format_tanggal_lengkap(d)
        self.assertIn("tanggal 31 (tiga puluh satu)", full)
        self.assertIn("bulan Desember tahun 2026", full)
        self.assertIn("(dua ribu dua puluh lima)", full)

    def test_parse_date_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            textutil.parse_date("1999-11-31")  # tanggal tidak ada
        with self.assertRaises(ValidationError):
            textutil.parse_date("31-12-2026")  # format salah
        with self.assertRaises(ValidationError):
            textutil.parse_date("")
        self.assertEqual(textutil.parse_date("2026-12-29"),
                         dt.date(2026, 12, 29))

    def test_nik_validation(self):
        self.assertEqual(textutil.validate_nik("9999999999990001"),
                         "9999999999990001")
        with self.assertRaises(ValidationError):
            textutil.validate_nik("12345")          # kurang 16
        with self.assertRaises(ValidationError):
            textutil.validate_nik("999999999999000A")  # bukan angka
        with self.assertRaises(ValidationError):
            textutil.validate_nik("")               # kosong


class TestValidation(unittest.TestCase):
    def test_all_required_fields_present(self):
        for key, label, kind, required in fields.FIELDS:
            self.assertTrue(label, f"label kosong untuk {key}")
            self.assertIn(kind, ("text", "date", "money", "nik", "select"))

    def test_minimal_valid_form(self):
        ctx = fields.validate_and_build(base_form())
        self.assertEqual(ctx["owner_nama"], "NAMA SINTETIS")
        self.assertEqual(ctx["nilai_pembiayaan"], 50000000)

    def test_missing_required_rejected(self):
        bad = base_form(owner_nama="")
        with self.assertRaises(ValidationError):
            fields.validate_and_build(bad)

    def test_invalid_nik_rejected(self):
        with self.assertRaises(ValidationError):
            fields.validate_and_build(base_form(owner_nik="123"))

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValidationError):
            fields.validate_and_build(base_form(tanggal_akta="1999-11-31"))

    def test_invalid_money_rejected(self):
        with self.assertRaises(ValidationError):
            fields.validate_and_build(base_form(nilai_pembiayaan="abc"))

    def test_spouse_address_required_when_different(self):
        with self.assertRaises(ValidationError):
            fields.validate_and_build(
                base_form(spouse_alamat_sama="tidak", spouse_dusun="",
                          spouse_rt="", spouse_rw="", spouse_desa="",
                          spouse_kecamatan=""))
        ctx = fields.validate_and_build(
            base_form(spouse_alamat_sama="tidak", spouse_dusun="Jalan Lain",
                      spouse_rt="1", spouse_rw="2", spouse_desa="Desa Pasangan",
                      spouse_kecamatan="Kecamatan Pasangan", spouse_kabupaten=""))
        self.assertFalse(ctx["spouse_alamat_sama"])
        self.assertEqual(ctx["spouse_kabupaten"], "Kota Contoh")

    def test_same_as_owner_copies_identity(self):
        ctx = fields.validate_and_build(base_form(same_as_owner="ya"))
        self.assertEqual(ctx["debtor_nama"], ctx["owner_nama"])
        self.assertEqual(ctx["debtor_nik"], ctx["owner_nik"])

    def test_same_as_owner_with_blank_debtor_fields(self):
        # Ini yang dikirim UI ketika "debitor = pemilik": field debitor
        # dinonaktifkan dan dikirim kosong. Harus tetap diterima.
        form = base_form(
            same_as_owner="ya",
            debtor_title="",
            debtor_nama="",
            debtor_lahir_tempat="",
            debtor_lahir_tanggal="",
            debtor_pekerjaan="",
            debtor_dusun="", debtor_rt="", debtor_rw="", debtor_desa="",
            debtor_kecamatan="", debtor_kabupaten="",
            debtor_nik="",
        )
        ctx = fields.validate_and_build(form)
        self.assertEqual(ctx["debtor_nama"], ctx["owner_nama"])
        self.assertEqual(ctx["debtor_nik"], ctx["owner_nik"])
        self.assertEqual(ctx["debtor_title"], ctx["owner_title"])
        self.assertEqual(ctx["debtor_lahir_tanggal"], ctx["owner_lahir_tanggal"])

    def test_distinct_debtor_blank_still_rejected(self):
        # Bila debitor berbeda, field debitor tetap wajib.
        form = base_form(same_as_owner="tidak", debtor_nama="", debtor_nik="")
        with self.assertRaises(ValidationError):
            fields.validate_and_build(form)


class TestSpouseVariants(unittest.TestCase):
    """Varian pasangan lewat JALUR PRODUKSI (mesin marker).

    Template contoh sintetis memakai marker; pengujian memakai
    ``render_docx_from_template`` + ``build_marker_values`` persis seperti
    server, bukan mesin frasa lama.
    """

    def _render(self, form) -> str:
        ctx = fields.validate_and_build(form)
        values = fields.build_marker_values(ctx)
        blob = docx_template.render_docx_from_template(
            load_template(), values,
            required_keys=fields.REQUIRED_MARKER_KEYS,
            removal_keys=fields.REMOVAL_MARKER_KEYS)
        return docx_text(blob)

    def test_wife_consent(self):
        text = self._render(base_form(spouse_mode="istri",
                                      spouse_nama="PASANGAN SINTETIS"))
        self.assertIn("persetujuan istrinya", text)
        self.assertIn("PASANGAN SINTETIS", text)
        self.assertIn("Persetujuan Istri", text)
        self.assertNotIn("Persetujuan Suami", text)

    def test_husband_consent_changes_wording(self):
        form = base_form(
            spouse_mode="suami",
            owner_title="Nyonya",
            owner_nama="RATNA DEWI",
            spouse_nama="ANDI PRATAMA",
            spouse_nik="9999999999990033",
        )
        text = self._render(form)
        self.assertIn("telah mendapat persetujuan suaminya", text)
        self.assertIn("ANDI PRATAMA", text)
        self.assertIn("Persetujuan Suami", text)
        self.assertNotIn("Persetujuan Istri", text)
        self.assertNotIn("persetujuan istrinya", text)

    def test_no_stale_identities(self):
        # Template contoh TIDAK boleh memuat identitas/placeholder apa pun yang
        # bukan nilai pengguna (tidak ada sisa contoh, tidak ada marker sisa).
        for mode in ("istri", "suami"):
            form = base_form(
                spouse_mode=mode,
                owner_nama="PEMILIK BARU",
                spouse_nama="PASANGAN BARU",
                same_as_owner="tidak",
                debtor_nama="DEBITOR BARU",
                debtor_nik="9999999999990009",
            )
            text = self._render(form)
            self.assertNotIn("{{", text)
            self.assertNotIn("}}", text)
            self.assertIn("PEMILIK BARU", text)
            self.assertIn("PASANGAN BARU", text)
            self.assertIn("DEBITOR BARU", text)

    def test_signature_uses_new_names(self):
        text = self._render(base_form(
            owner_nama="PEMILIK BARU", spouse_nama="PASANGAN BARU",
            spouse_mode="istri"))
        self.assertIn("PEMILIK BARU", text)
        self.assertIn("PASANGAN BARU", text)

    def test_debtor_different_from_owner(self):
        text = self._render(base_form(
            same_as_owner="tidak",
            debtor_nama="DEBITOR BARU",
            debtor_nik="9999999999990009",
            debtor_dusun="Dusun Debitor", debtor_rt="5", debtor_rw="13",
            debtor_desa="Contoh Debitor", debtor_kecamatan="Contoh Dua Debitor",
            debtor_kabupaten="Kota Contoh"))
        self.assertIn("DEBITOR BARU", text)
        self.assertIn("9999999999990009", text)
        # alamat debitor berbeda dirender terstruktur dengan nilai debitor.
        self.assertIn("bertempat tinggal di Dusun Debitor Rukun Tetangga 5, "
                      "Rukun Warga 13, Desa Contoh Debitor, Kecamatan Contoh "
                      "Dua Debitor, Kabupaten Kota Contoh", text)

    def test_same_as_owner_uses_owner_identity(self):
        text = self._render(base_form(
            owner_nama="PEMILIK SAMA", same_as_owner="ya"))
        self.assertIn("PEMILIK SAMA", text)
        self.assertNotIn("DEBITOR BARU", text)

    def test_same_as_owner_blank_debtor_fields_render(self):
        # Representasi persis payload UI: field debitor dikosongkan.
        text = self._render(base_form(
            owner_nama="PEMILIK SAMA",
            same_as_owner="ya",
            debtor_title="", debtor_nama="", debtor_lahir_tempat="",
            debtor_lahir_tanggal="", debtor_pekerjaan="",
            debtor_dusun="", debtor_rt="", debtor_rw="", debtor_desa="",
            debtor_kecamatan="", debtor_kabupaten="",
            debtor_nik=""))
        self.assertIn("PEMILIK SAMA", text)
        self.assertNotIn("{{", text)


class TestDocxPreservation(unittest.TestCase):
    """Preservasi paket DOCX + nilai render lewat jalur produksi (marker)."""

    def _render_default(self) -> bytes:
        ctx = fields.validate_and_build(base_form())
        return docx_template.render_docx_from_template(
            load_template(), fields.build_marker_values(ctx),
            required_keys=fields.REQUIRED_MARKER_KEYS,
            removal_keys=fields.REMOVAL_MARKER_KEYS)

    def test_zip_entries_preserved(self):
        original = load_template()
        with zipfile.ZipFile(io.BytesIO(original)) as z:
            orig_names = set(z.namelist())
        with zipfile.ZipFile(io.BytesIO(self._render_default())) as z:
            new_names = set(z.namelist())
        self.assertEqual(orig_names, new_names)

    def test_only_document_xml_changes(self):
        original = load_template()
        rendered = self._render_default()
        with zipfile.ZipFile(io.BytesIO(original)) as z:
            o = {n: z.read(n) for n in z.namelist()}
        with zipfile.ZipFile(io.BytesIO(rendered)) as z:
            r = {n: z.read(n) for n in z.namelist()}
        for name in o:
            if name == "word/document.xml":
                continue
            self.assertEqual(o[name], r[name],
                             f"entri {name} berubah padahal seharusnya identik")

    def test_run_formatting_preserved(self):
        # Paragraf identitas pemilik memakai run bold untuk nama; rPr (sz/font)
        # harus tetap ada setelah penggantian.
        rendered = self._render_default()
        with zipfile.ZipFile(io.BytesIO(rendered)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn('w:sz w:val="24"', xml)
        self.assertIn("Bookman Old Style", xml)
        # Masih ada run dengan <w:b/> (tebal); ElementTree menulis "<w:b />".
        self.assertTrue("<w:b/>" in xml or "<w:b />" in xml)

    def test_original_untouched(self):
        # Aplikasi tidak menulis berkas template.
        before = os.path.getmtime(TEMPLATE)
        self._render_default()
        after = os.path.getmtime(TEMPLATE)
        self.assertEqual(before, after)

    def test_replaced_values_appear(self):
        text = docx_text(self._render_default())
        self.assertIn("NAMA SINTETIS", text)
        self.assertIn("50.000.000", text)
        self.assertIn("(lima puluh juta rupiah)", text)
        self.assertIn("75.000.000", text)
        self.assertIn("(tujuh puluh lima juta rupiah)", text)
        self.assertIn("seribu seratus lima puluh tiga meter persegi", text)
        self.assertIn("Nomor : 12/ 2026", text)

    def test_no_stale_location_leftover(self):
        # Marker pembersih ``_remove_jalan_cont`` mengosongkan paragraf sisa;
        # hanya satu baris "Jalan: <nilai pengguna> ;" yang tersisa dan tidak
        # ada sisa contoh.
        text = docx_text(self._render_default())
        self.assertEqual(text.count("Jalan: Jalan Contoh RT 003 RW 06 ;"), 1)
        self.assertNotIn("{{_remove_jalan_cont}}", text)

    def test_no_stale_land_identifiers(self):
        text = docx_text(self._render_default())
        # Nilai tanah default dirender pada blok objek (tidak ada token sisa).
        self.assertIn("Hak Milik Nomor: 12345/Contoh Satu", text)
        self.assertNotIn("{{", text)

    def test_fixed_clauses_and_actors_preserved(self):
        # Notaris, saksi, penerima kuasa, dan lembaga (aktor sintetis tetap)
        # harus tetap apa adanya pada dokumen hasil.
        text = docx_text(self._render_default())
        for value in fields.FIXED.values():
            self.assertIn(value, text, f"nilai tetap hilang: {value}")

    def test_result_is_valid_docx(self):
        blob = self._render_default()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            self.assertIn("word/document.xml", z.namelist())
            self.assertIsNone(z.testzip())

    def test_special_characters_are_escaped(self):
        from app import fields as f
        form = base_form(owner_nama='NAMA SINTETIS <X> & "Y"',
                         owner_dusun="Jalan <A> & B")
        ctx = f.validate_and_build(form)
        blob = docx_template.render_docx_from_template(
            load_template(), f.build_marker_values(ctx),
            required_keys=f.REQUIRED_MARKER_KEYS,
            removal_keys=f.REMOVAL_MARKER_KEYS)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            xml = z.read("word/document.xml")
        from xml.etree import ElementTree as ET
        ET.fromstring(xml)  # melempar bila XML rusak
        self.assertIn(b"&amp;", xml)
        self.assertIn(b"&lt;", xml)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def build_docx(body_xml: bytes, *, mc_ignorable=None,
               extra_root_attrs: str = "") -> bytes:
    """Membuat DOCX minimal (zip) dengan document.xml yang diberikan."""
    ign = f' mc:Ignorable="{mc_ignorable}"' if mc_ignorable else ""
    document = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
        b'wordprocessingml/2006/main" '
        b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
        b'2006/relationships" '
        b'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/'
        b'2006"' + ign.encode("utf-8") + extra_root_attrs.encode("utf-8") +
        b"><w:body>" + body_xml + b"</w:body></w:document>"
    )
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        b'content-types"><Default Extension="xml" ContentType="application/'
        b'xml"/><Override PartName="/word/document.xml" ContentType='
        b'"application/vnd.openxmlformats-officedocument.wordprocessingml.'
        b'document.main+xml"/></Types>'
    )
    rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        b'2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
        b'openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        b' Target="word/document.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def rpr_xml(bold=False, size=None, color=None, lang=None) -> bytes:
    parts = [b"<w:rPr>"]
    if bold:
        parts.append(b"<w:b/>")
    if size:
        parts.append(f'<w:sz w:val="{size}"/>'.encode())
    if color:
        parts.append(f'<w:color w:val="{color}"/>'.encode())
    if lang:
        parts.append(f'<w:lang w:val="{lang}"/>'.encode())
    parts.append(b"</w:rPr>")
    return b"".join(parts)


def run_xml(text, **rpr_kwargs) -> bytes:
    return (b"<w:r>" + rpr_xml(**rpr_kwargs) +
            f"<w:t xml:space=\"preserve\">{text}</w:t>".encode() + b"</w:r>")


def para_xml(*runs: bytes) -> bytes:
    return b"<w:p>" + b"".join(runs) + b"</w:p>"


def document_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        xml = z.read("word/document.xml")
    root = ET_fromstring(xml)
    return "".join(t.text or "" for t in root.iter(W + "t"))


def ET_fromstring(xml: bytes):
    from xml.etree import ElementTree as ET
    return ET.fromstring(xml)


def document_roots(blob):
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return ET.fromstring(z.read("word/document.xml"))


class TestDocxEngineFormatting(unittest.TestCase):
    """Regression untuk mesin templating: offset, gaya run, tab, namespace."""

    def _render(self, body: bytes, replacements, **kw) -> bytes:
        return docx_template.render_docx(
            build_docx(body, **kw), replacements)

    def test_multiple_styled_runs_preserved(self):
        # Run bold (nama) diapit run non-bold; hanya rentang nama yang berubah,
        # run di kiri/kanan harus tetap identik (gaya + teks).
        body = para_xml(
            run_xml("Tuan "),
            run_xml("PEMILIK LAMA CONTOH ", bold=True),
            run_xml("tinggal di sini", color="FF0000"),
        )
        blob = self._render(body, [("Tuan PEMILIK LAMA CONTOH", "Tuan NAMA BARU")])
        root = document_roots(blob)
        paras = list(root.iter(W + "p"))
        runs = paras[0].findall(W + "r")
        # jumlah run tidak boleh bertambah/berkurang
        self.assertEqual(len(runs), 3)
        # run warna merah (tidak bersinggungan) harus utuh
        red = runs[2]
        self.assertIsNotNone(red.find(W + "rPr/" + W + "color"))
        self.assertEqual(
            (red.find(W + "rPr/" + W + "color").get(W + "val")), "FF0000")
        self.assertEqual("".join(t.text or "" for t in red.findall(W + "t")),
                         "tinggal di sini")
        # nilai pengguna muncul dan run pertama (yang bersinggungan) tetap ada
        self.assertIn("NAMA BARU", document_text(blob))

    def test_split_match_across_nodes(self):
        # Kata kunci terbelah di dua node <w:t>; penggantian harus tetap utuh
        # dan mewarisi gaya node pertama.
        body = para_xml(
            run_xml("Nyonya PASANGAN ", bold=True),
            run_xml("LAMA CONTOH, lahir", color="00FF00"),
        )
        blob = self._render(
            body, [("Nyonya PASANGAN LAMA CONTOH", "Nyonya PASANGAN BARU")])
        text = document_text(blob)
        self.assertIn("Nyonya PASANGAN BARU, lahir", text)
        self.assertNotIn("LAMA CONTOH", text)
        # gaya node pertama (bold) ada pada node yang menyimpan hasil
        root = document_roots(blob)
        p = list(root.iter(W + "p"))[0]
        first_run = p.findall(W + "r")[0]
        self.assertIsNotNone(first_run.find(W + "rPr/" + W + "b"))
        self.assertEqual(
            "".join(t.text or "" for t in first_run.findall(W + "t")),
            "Nyonya PASANGAN BARU")

    def test_unaffected_tabs_preserved(self):
        # <w:tab/> di luar rentang penggantian harus tetap ada, termasuk di run
        # yang sama sekali tidak bersinggungan.
        tab_run = b'<w:r>' + rpr_xml() + b'<w:tab/>' + \
            b'<w:t xml:space="preserve">Penerima Kuasa</w:t></w:r>'
        body = para_xml(
            run_xml("NAMA LAMA   "),
            run_xml("PENERIMA KUASA CONTOH"),
            tab_run,
        )
        blob = self._render(
            body, [("NAMA LAMA   PENERIMA KUASA CONTOH",
                    "NAME BARU   PENERIMA KUASA CONTOH")])
        root = document_roots(blob)
        p = list(root.iter(W + "p"))[0]
        self.assertEqual(len(list(p.iter(W + "tab"))), 1)
        # teks run ketiga tetap
        runs = p.findall(W + "r")
        self.assertEqual(
            "".join(t.text or "" for t in runs[2].findall(W + "t")),
            "Penerima Kuasa")
        self.assertIn("NAME BARU", document_text(blob))

    def test_user_value_containing_find_token_not_rescanned(self):
        # Nilai pengguna memuat token yang sama dengan kunci lain. Karena
        # penggantian dilakukan dari kanan ke kiri atas teks ASLI, nilai yang
        # baru disisipkan TIDAK boleh dipindai ulang.
        body = para_xml(
            run_xml("A "),
            run_xml("PEMILIK "),
            run_xml("LAMA CONTOH"),
        )
        # Kunci "PEMILIK LAMA CONTOH" diganti "PEMILIK". Nilai "PEMILIK" memuat
        # substring kunci lain ("PEMILIK") untuk membuktikan tidak ada
        # pemindaian ulang.
        blob = self._render(body, [
            ("PEMILIK LAMA CONTOH", "PEMILIK"),
            ("PEMILIK", "GANTI"),
        ])
        text = document_text(blob)
        # Hasil: "A " + penggantian terpanjang "PEMILIK LAMA CONTOH"->"PEMILIK".
        # Nilai "PEMILIK" yang disisipkan tidak boleh dipindai ulang menjadi
        # "GANTI" (itu hanya berlaku untuk teks asli di posisi lain).
        self.assertEqual(text, "A PEMILIK")

    def test_user_value_token_not_rescanned_second_pass(self):
        # Nilai pengganti = token kunci lain; harus tetap apa adanya karena
        # hanya dipindai teks ASLI sekali.
        body = para_xml(run_xml("ALAMAT LAMA"))
        blob = self._render(body, [
            ("ALAMAT LAMA", "Sub Kunci"),
            ("Sub", "NONAKTIF"),
        ])
        self.assertEqual(document_text(blob), "Sub Kunci")

    def test_mc_ignorable_prefixes_and_namespaces_retained(self):
        # Prefiks yang hanya muncul pada nilai mc:Ignorable (tidak dipakai
        # sebagai nama elemen) harus tetap terdeklarasi di root.
        extra = (
            ' xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
            ' xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"'
            ' xmlns:wp14="http://schemas.microsoft.com/office/word/2010/'
            'wordprocessingDrawing"'
        )
        body = para_xml(run_xml("PEMILIK LAMA CONTOH"))
        blob = self._render(
            body, [("PEMILIK LAMA CONTOH", "NAMA BARU")],
            mc_ignorable="w14 w15 wp14", extra_root_attrs=extra)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        # mc:Ignorable dipertahankan apa adanya
        self.assertIn('mc:Ignorable="w14 w15 wp14"', xml)
        # setiap prefiks pada mc:Ignorable terdeklarasi di root
        import re
        root_tag = re.match(r'<\?xml[^>]*\?>\s*(<[^>]+>)', xml).group(1)
        decls = set(re.findall(r'xmlns:([A-Za-z_][\w.\-]*)="', root_tag))
        for prefix in ("w14", "w15", "wp14"):
            self.assertIn(prefix, decls,
                          f"prefiks {prefix} pada mc:Ignorable tidak dideklarasikan")
        # tidak ada deklarasi ganda
        names = re.findall(r'xmlns:([A-Za-z_][\w.\-]*)="', root_tag)
        self.assertEqual(len(names), len(set(names)))
        # XML tetap well-formed
        ET_fromstring(xml.encode("utf-8"))

    def test_no_synthetic_ns_prefixes_on_real_template(self):
        # Template contoh punya banyak deklarasi namespace di root; serialisasi
        # tidak boleh memakai prefiks sintetis ns0/ns1/...
        ctx = fields.validate_and_build(base_form())
        blob = docx_template.render_docx_from_template(
            load_template(), fields.build_marker_values(ctx),
            required_keys=fields.REQUIRED_MARKER_KEYS,
            removal_keys=fields.REMOVAL_MARKER_KEYS)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        self.assertIsNone(re.search(r"<ns\d+:", xml))
        self.assertIsNone(re.search(r"</ns\d+:", xml))

    def test_real_template_mc_ignorable_preserved(self):
        orig = load_template()
        with zipfile.ZipFile(io.BytesIO(orig)) as z:
            orig_xml = z.read("word/document.xml").decode("utf-8")
        import re as _re
        orig_ign = _re.search(r'mc:Ignorable="([^"]*)"', orig_xml)
        self.assertIsNotNone(orig_ign)
        ctx = fields.validate_and_build(base_form())
        blob = docx_template.render_docx_from_template(
            orig, fields.build_marker_values(ctx),
            required_keys=fields.REQUIRED_MARKER_KEYS,
            removal_keys=fields.REMOVAL_MARKER_KEYS)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            new_xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn(f'mc:Ignorable="{orig_ign.group(1)}"', new_xml)
        new_root = _re.match(r'<\?xml[^>]*\?>\s*(<[^>]+>)', new_xml).group(1)
        decls = set(_re.findall(r'xmlns:([A-Za-z_][\w.\-]*)="', new_root))
        missing = [p for p in orig_ign.group(1).split() if p not in decls]
        self.assertEqual(missing, [], f"prefiks hilang: {missing}")


class TestSyntheticTemplateContract(unittest.TestCase):
    """Kontrak template contoh sintetis lewat jalur produksi (marker).

    Template contoh memakai tab leader (right tab ber-``leader="hyphen"``) dan
    beberapa paragraf dipisah ``<w:tab/>``. Uji ini memastikan seluruh
    substitusi marker bekerja, tidak ada token sisa, aktor sintetis tetap
    terjaga, dan setelan tab/leader terbawa utuh ke dokumen hasil.
    """

    def _render(self, form) -> bytes:
        ctx = fields.validate_and_build(form)
        return docx_template.render_docx_from_template(
            load_template(), fields.build_marker_values(ctx),
            required_keys=fields.REQUIRED_MARKER_KEYS,
            removal_keys=fields.REMOVAL_MARKER_KEYS)

    def _doc_root(self, blob):
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return ET.fromstring(z.read("word/document.xml")), z

    def _leader_tabs(self, blob):
        """Kumpulkan (par_idx, val, leader, pos) untuk tiap <w:tab> di <w:tabs>."""
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        out = []
        for i, p in enumerate(root.iter(W + "p")):
            tabs = p.find(W + "pPr/" + W + "tabs")
            if tabs is None:
                continue
            for tb in tabs.findall(W + "tab"):
                out.append((i, tb.get(W + "val"), tb.get(W + "leader"),
                            tb.get(W + "pos")))
        return out

    def test_no_marker_or_stale_leftover_both_spouse_modes(self):
        for mode in ("istri", "suami"):
            form = base_form(
                spouse_mode=mode,
                owner_nama="PEMILIK BARU",
                spouse_nama="PASANGAN BARU",
                same_as_owner="tidak",
                debtor_nama="DEBITOR BARU",
                debtor_nik="9999999999990009",
            )
            text = docx_text(self._render(form))
            self.assertNotIn("{{", text)
            self.assertNotIn("}}", text)
            self.assertIn("PEMILIK BARU", text)
            self.assertIn("PASANGAN BARU", text)
            self.assertIn("DEBITOR BARU", text)

    def test_signature_name_replaced_across_tab(self):
        # Nama Pemberi Kuasa di blok tanda tangan dipisahkan nama Penerima
        # Kuasa oleh <w:tab/> (bukan spasi). Nama pengguna harus muncul dan
        # elemen tab di antaranya tetap ada.
        blob = self._render(base_form(
            owner_nama="PEMILIK BARU", spouse_mode="istri"))
        root, _ = self._doc_root(blob)
        text = "".join(t.text or "" for t in root.iter(W + "t"))
        self.assertIn("PEMILIK BARU", text)
        # Paragraf tanda tangan adalah yang memuat nama pemberi kuasa (pengguna)
        # DAN nama penerima kuasa; keduanya dipisah oleh <w:tab/>.
        sig_paras = [p for p in root.iter(W + "p")
                     if "PEMILIK BARU" in "".join(
                         t.text or "" for t in p.iter(W + "t"))
                     and "PENERIMA KUASA CONTOH" in "".join(
                         t.text or "" for t in p.iter(W + "t"))]
        self.assertTrue(sig_paras,
                        "paragraf tanda tangan pemilik+penerima kuasa hilang")
        self.assertGreaterEqual(len(list(sig_paras[0].iter(W + "tab"))), 1)

    def test_no_stale_jalan_continuation(self):
        # Marker pembersih mengosongkan paragraf sisa alamat jalan.
        text = docx_text(self._render(base_form()))
        self.assertEqual(text.count("Jalan: Jalan Contoh RT 003 RW 06 ;"), 1)
        self.assertNotIn("{{_remove_jalan_cont}}", text)

    def test_fixed_clauses_and_actors_preserved(self):
        text = docx_text(self._render(base_form()))
        for value in fields.FIXED.values():
            self.assertIn(value, text, f"nilai tetap hilang: {value}")

    def test_tab_leader_settings_carried_through(self):
        # Setelan tab leader (right tab, leader="hyphen") harus tetap ada dan
        # jumlahnya tidak boleh hilang akibat penggantian marker.
        orig = load_template()
        orig_leaders = self._leader_tabs(orig)
        self.assertTrue(any(ld == "hyphen" for (_i, _v, ld, _p)
                            in orig_leaders),
                        "template contoh semestinya memuat tab leader hyphen")
        new_leaders = self._leader_tabs(self._render(base_form()))
        # himpunan (val, leader, pos) harus identik (urutan/paragraf boleh geser)
        self.assertEqual(
            sorted((v or "", ld or "", p or "") for (_i, v, ld, p) in orig_leaders),
            sorted((v or "", ld or "", p or "") for (_i, v, ld, p) in new_leaders),
            "setelan tab/leader berubah setelah render")

    def test_tab_element_count_preserved(self):
        # Jumlah elemen <w:tab/> dalam paragraf tidak boleh berkurang.
        from xml.etree import ElementTree as ET
        orig = load_template()
        with zipfile.ZipFile(io.BytesIO(orig)) as z:
            orig_tabs = len(list(ET.fromstring(z.read("word/document.xml"))
                                 .iter(W + "tab")))
        root, _ = self._doc_root(self._render(base_form()))
        new_tabs = len(list(root.iter(W + "tab")))
        self.assertGreaterEqual(new_tabs, orig_tabs)

    def test_result_is_valid_docx_and_zip(self):
        blob = self._render(base_form())
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            self.assertIn("word/document.xml", z.namelist())
            self.assertIsNone(z.testzip())
            xml = z.read("word/document.xml")
        # XML harus bisa diparsing ulang.
        from xml.etree import ElementTree as ET
        ET.fromstring(xml)
        self.assertNotIn(b"<ns0:", xml)

    def test_only_document_xml_changes_on_template(self):
        orig = load_template()
        rendered = self._render(base_form())
        with zipfile.ZipFile(io.BytesIO(orig)) as z:
            o = {n: z.read(n) for n in z.namelist()}
        with zipfile.ZipFile(io.BytesIO(rendered)) as z:
            r = {n: z.read(n) for n in z.namelist()}
        self.assertEqual(set(o), set(r))
        for name in o:
            if name == "word/document.xml":
                continue
            self.assertEqual(o[name], r[name],
                             f"entri {name} berubah padahal seharusnya identik")


class TestServerHelpers(unittest.TestCase):
    def test_safe_filename(self):
        from app.server import _safe_filename
        ctx = {"owner_nama": "NAMA SINTETIS / X:Y"}
        name = _safe_filename(ctx)
        self.assertTrue(name.startswith("SKMHT_"))
        self.assertTrue(name.endswith(".docx"))
        self.assertNotIn("/", name)
        self.assertNotIn(":", name)

    def test_render_pipeline(self):
        from app.server import _render
        blob = _render(base_form())
        self.assertTrue(blob.startswith(b"PK"))  # signature zip/docx


class TestServerHttpSmoke(unittest.TestCase):
    """Smoke test HTTP end-to-end pada localhost (port ephemeral)."""

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

    def _url(self, path):
        return f"http://{self._host}:{self._port}{path}"

    def _get(self, path):
        import urllib.request
        with urllib.request.urlopen(self._url(path), timeout=5) as resp:
            return resp.status, resp.read(), dict(resp.headers)

    def _post(self, path, payload: bytes, content_type="application/json"):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            self._url(path), data=payload, method="POST",
            headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read(), dict(exc.headers)
            finally:
                exc.close()

    def _review_and_ack(self, form):
        """Lengkapi form dengan status tinjauan + tiket persetujuan kanonik.

        Digest tinjauan dihitung server atas SELURUH payload (termasuk key
        tinjauan), sehingga nilai ``_review_digest`` diiterasi sampai stabil.
        """
        import json as _json
        import time as _time
        seq = 0
        while True:
            seq += 1
            if seq > 5:
                raise AssertionError("digest ringkasan tidak stabil")
            payload = dict(form)
            payload["_reviewed"] = True
            payload["_review_ts"] = int(_time.time())
            status, body, _ = self._post(
                "/api/review", _json.dumps(payload).encode("utf-8"))
            self.assertEqual(status, 200)
            j = _json.loads(body)
            self.assertTrue(j["valid"], j.get("error"))
            if payload.get("_review_digest") == j["review"]["fingerprint"]:
                payload["confirm_summary"] = True
                payload["ack_digest"] = j["digest"]
                payload["ack_token"] = j["ack_token"]
                payload["summary_signature"] = j["summary_signature"]
                return payload
            form = dict(payload)
            form["_review_digest"] = j["review"]["fingerprint"]

    def test_index_served(self):
        status, body, headers = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Generator SKMHT", body)
        self.assertIn("text/html", headers.get("Content-Type", ""))

    def test_assets_served(self):
        for path in ("/app.css", "/app.js"):
            status, body, _ = self._get(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)

    def test_fields_endpoint(self):
        import json
        status, body, _ = self._get("/api/fields")
        self.assertEqual(status, 200)
        data = json.loads(body)
        keys = {f["key"] for f in data["fields"]}
        self.assertIn("owner_nama", keys)
        self.assertIn("same_as_owner", keys)

    def test_healthz(self):
        status, body, _ = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertIn(b"true", body)

    def test_generate_returns_docx(self):
        import json
        payload = json.dumps(
            self._review_and_ack(base_form())).encode("utf-8")
        status, body, headers = self._post("/api/generate", payload)
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"PK"))
        self.assertIn("wordprocessingml.document",
                      headers.get("Content-Type", ""))
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        # Dokumen hasil harus bisa dibuka & memuat nilai pengguna.
        text = docx_text(body)
        self.assertIn("NAMA SINTETIS", text)

    def test_generate_requires_review_and_ack(self):
        import json
        # Tanpa tinjauan: ditolak (422), bukan membuat dokumen.
        status, body, _ = self._post(
            "/api/generate", json.dumps(base_form()).encode("utf-8"))
        self.assertEqual(status, 422)
        self.assertFalse(body.startswith(b"PK"))

    def test_generate_same_as_owner_blank_debtor(self):
        import json
        form = base_form(
            same_as_owner="ya", debtor_title="", debtor_nama="",
            debtor_lahir_tempat="", debtor_lahir_tanggal="",
            debtor_pekerjaan="", debtor_dusun="", debtor_rt="", debtor_rw="",
            debtor_desa="", debtor_kecamatan="", debtor_kabupaten="",
            debtor_nik="")
        status, body, _ = self._post(
            "/api/generate",
            json.dumps(self._review_and_ack(form)).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertIn("NAMA SINTETIS", docx_text(body))

    def test_generate_invalid_input_is_422(self):
        import json
        form = base_form(owner_nik="123")  # NIK salah
        status, body, _ = self._post(
            "/api/generate", json.dumps(form).encode("utf-8"))
        self.assertEqual(status, 422)
        self.assertIn(b"ok", body)

    def test_generate_oversized_body_is_413(self):
        from app import server
        big = b"x" * (server.MAX_BODY_BYTES + 10)
        status, body, _ = self._post("/api/generate", big)
        self.assertEqual(status, 413)

    def test_generate_bad_json_is_400(self):
        status, body, _ = self._post("/api/generate", b"{not json")
        self.assertEqual(status, 400)

    def test_unknown_path_is_404(self):
        import urllib.error
        import urllib.request
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self._url("/nope"), timeout=5)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_no_external_resources_or_storage(self):
        # Privasi: tidak ada CDN/URL eksternal, tidak ada penyimpanan browser.
        import re
        for path in ("/", "/app.css", "/app.js"):
            _, body, _ = self._get(path)
            text = body.decode("utf-8").lower()
            for forbidden in ("localstorage", "sessionstorage",
                              "indexeddb", "document.cookie"):
                self.assertNotIn(forbidden, text,
                                 f"{forbidden} ditemukan di {path}")
            # Tidak boleh ada URL http(s) absolut pada aset yang dilayani.
            self.assertIsNone(
                re.search(r"https?://(?!127\.0\.0\.1)", text),
                f"URL eksternal ditemukan di {path}")

    def test_personal_fields_blank_by_default(self):
        # Skema tidak boleh menyertakan nilai contoh apa pun.
        import json
        _, body, _ = self._get("/api/fields")
        for f in json.loads(body)["fields"]:
            self.assertNotIn("value", f)
            self.assertNotIn("default", f)


# ===========================================================================
# OCR KTP lokal (Tesseract) — parser, validasi, dan endpoint (mesin mock).
# ===========================================================================

SAMPLE_KTP_TEXT = (
    "PROVINSI CONTOH\n"
    "KABUPATEN KOTA KARTIKA\n"
    "NIK : 9999999999990001\n"
    "Nama : NAMA SINTETIS\n"
    "Tempat/Tgl Lahir : KOTA KARTIKA, 17-05-1985\n"
    "Jenis Kelamin : Laki-Laki\n"
    "Agama : ISLAM\n"
    "Status Perkawinan : KAWIN\n"
    "Pekerjaan : PETANI/PEKEBUN\n"
    "Kewarganegaraan : WNI\n"
    "Alamat : DUSUN BARU RT 001 RW 002\n"
    "RT/RW : 001/000\n"
    "Kel/Desa : DESA KARTIKA\n"
    "Kecamatan : KECAMATAN KARTIKA\n"
)


class TestKtpParser(unittest.TestCase):
    """Parser KTP konservatif: tidak menebak, menerima pola label jelas."""

    def setUp(self):
        from app import ktp_ocr
        self.k = ktp_ocr

    def test_parse_full_sample(self):
        r = self.k.parse_ktp_fields(SAMPLE_KTP_TEXT)
        f = r["fields"]
        self.assertEqual(f["nik"]["value"], "9999999999990001")
        self.assertEqual(f["nik"]["status"], "format_valid")
        self.assertEqual(f["nama"]["value"], "NAMA SINTETIS")
        self.assertEqual(f["tempat_lahir"]["value"], "KOTA KARTIKA")
        self.assertEqual(f["tanggal_lahir"]["value"], "1985-05-17")
        self.assertEqual(f["jenis_kelamin"]["value"], "Laki-Laki")
        self.assertEqual(f["pekerjaan"]["value"], "PETANI/PEKEBUN")
        self.assertIn("DUSUN BARU", f["alamat"]["value"])
        self.assertEqual(f["kecamatan"]["value"], "KECAMATAN KARTIKA")

    def test_screenshot_like_noise_keeps_detected_values_reviewable(self):
        text = (
            "KABUPATEN KOTA KARTIKAE E EEE\n"
            "NIK- - 1234567890123456 pees\n"
            "- Alama DUSUN KARTIKA | SSS | =\n"
            "- Kel/Desa == DESA KARTIKAE - = - ...\n"
            "Pekerjaan - - PELAJAR/MAHASISWA ...\n"
        )
        fields = self.k.parse_ktp_fields(text)["fields"]
        self.assertEqual(fields["nik"]["value"], "1234567890123456")
        self.assertEqual(fields["nik"]["status"], "format_valid")
        self.assertIn("DUSUN KARTIKA", fields["alamat"]["value"])
        self.assertIn("DESA KARTIKAE", fields["kel_desa"]["value"])
        self.assertIn("PELAJAR/MAHASISWA", fields["pekerjaan"]["value"])
        self.assertEqual(fields["pekerjaan"]["status"], "review")

    def test_nik_format_valid_does_not_claim_ocr_correctness(self):
        result = self.k.parse_ktp_fields("NIK : 1234567890123456")
        self.assertEqual(result["fields"]["nik"]["status"], "format_valid")
        self.assertNotEqual(result["fields"]["nik"]["status"], "confident")

    def test_nik_wrong_length_not_guessed(self):
        # NIK 14 digit dengan label: jangan menebak/melengkapi angka.
        r = self.k.parse_ktp_fields("NIK : 99999999999900\nNama : X")
        self.assertEqual(r["fields"]["nik"]["value"], "")
        self.assertEqual(r["fields"]["nik"]["status"], "review")

    def test_nik_unlabeled_single_16_digits_is_review(self):
        r = self.k.parse_ktp_fields("nomor 1234567890123456 saja")
        self.assertEqual(r["fields"]["nik"]["value"], "1234567890123456")
        self.assertEqual(r["fields"]["nik"]["status"], "review")

    def test_nik_unlabeled_ambiguous_is_missing(self):
        r = self.k.parse_ktp_fields(
            "1111111111111111 dan 2222222222222222")
        self.assertEqual(r["fields"]["nik"]["value"], "")
        self.assertEqual(r["fields"]["nik"]["status"], "missing")

    def test_nik_no_invented_digits(self):
        # Tidak boleh mengembalikan digit yang tidak ada di teks.
        r = self.k.parse_ktp_fields("NIK : 999999999999X001")
        self.assertNotEqual(r["fields"]["nik"]["value"], "9999999999990001")

    def test_invalid_birth_date_blank(self):
        r = self.k.parse_ktp_fields("Tempat/Tgl Lahir : KOTA KARTIKA, 99-99-9999")
        self.assertEqual(r["fields"]["tanggal_lahir"]["value"], "")
        self.assertEqual(r["fields"]["tanggal_lahir"]["status"], "missing")

    def test_birth_without_place_still_parses_date(self):
        r = self.k.parse_ktp_fields("Tempat/Tgl Lahir : 17-05-1985")
        self.assertEqual(r["fields"]["tanggal_lahir"]["value"], "1985-05-17")
        self.assertEqual(r["fields"]["tempat_lahir"]["value"], "")

    def test_gender_perempuan(self):
        r = self.k.parse_ktp_fields("Jenis Kelamin : PEREMPUAN")
        self.assertEqual(r["fields"]["jenis_kelamin"]["value"], "Perempuan")

    def test_gender_unknown_blank(self):
        r = self.k.parse_ktp_fields("Jenis Kelamin : XYZ")
        self.assertEqual(r["fields"]["jenis_kelamin"]["value"], "")

    def test_empty_text_all_blank_missing(self):
        r = self.k.parse_ktp_fields("")
        for key, info in r["fields"].items():
            self.assertEqual(info["value"], "", f"{key} harus kosong")
            self.assertEqual(info["status"], "missing")

    def test_raw_text_preserved_locally(self):
        r = self.k.parse_ktp_fields(SAMPLE_KTP_TEXT)
        self.assertEqual(r["raw_text"], SAMPLE_KTP_TEXT)

    def test_candidates_for_role_owner(self):
        r = self.k.parse_ktp_fields(SAMPLE_KTP_TEXT)
        c = self.k.candidates_for_role(r, "owner")
        self.assertEqual(c["owner_nik"]["value"], "9999999999990001")
        self.assertEqual(c["owner_nama"]["value"], "NAMA SINTETIS")
        self.assertEqual(c["owner_lahir_tanggal"]["value"], "1985-05-17")
        # Key milik peran lain tidak boleh muncul.
        self.assertNotIn("spouse_nik", c)
        self.assertNotIn("debtor_nik", c)

    def test_candidates_for_role_spouse_and_debtor(self):
        r = self.k.parse_ktp_fields(SAMPLE_KTP_TEXT)
        for role in ("spouse", "debtor"):
            c = self.k.candidates_for_role(r, role)
            self.assertIn(f"{role}_nik", c)
            self.assertIn(f"{role}_nama", c)

    def test_candidates_unknown_role_empty(self):
        r = self.k.parse_ktp_fields(SAMPLE_KTP_TEXT)
        self.assertEqual(self.k.candidates_for_role(r, "nobody"), {})

    def test_candidate_values_never_empty(self):
        # Hanya field dengan value terisi yang masuk kandidat.
        r = self.k.parse_ktp_fields("Nama : CITRA")
        c = self.k.candidates_for_role(r, "owner")
        self.assertEqual(c["owner_nama"]["value"], "CITRA")
        self.assertNotIn("owner_nik", c)


class TestKtpImageValidation(unittest.TestCase):
    def setUp(self):
        from app import ktp_ocr
        self.k = ktp_ocr

    def test_detect_signatures(self):
        self.assertEqual(self.k.detect_image_type(b"\xff\xd8\xff\xe0xx"),
                         "jpeg")
        self.assertEqual(self.k.detect_image_type(b"\x89PNG\r\n\x1a\nxx"),
                         "png")
        self.assertIsNone(self.k.detect_image_type(b"GIF89a"))
        self.assertIsNone(self.k.detect_image_type(b""))

    def test_validate_rejects_non_image(self):
        with self.assertRaises(self.k.OcrError):
            self.k.validate_image(b"not an image")

    def test_validate_rejects_empty(self):
        with self.assertRaises(self.k.OcrError):
            self.k.validate_image(b"")

    def test_validate_rejects_oversized(self):
        big = b"\xff\xd8\xff" + b"x" * (self.k.MAX_IMAGE_BYTES + 1)
        with self.assertRaises(self.k.OcrError):
            self.k.validate_image(big)

    def test_validate_accepts_real_signature(self):
        self.assertEqual(self.k.validate_image(b"\xff\xd8\xff\xe0rest"),
                         "jpeg")
        self.assertEqual(self.k.validate_image(b"\x89PNG\r\n\x1a\nrest"),
                         "png")


class TestKtpOcrEngineMock(unittest.TestCase):
    """Uji jalur pipeline OCR dengan mesin tiruan (tanpa Tesseract asli)."""

    def setUp(self):
        from app import ktp_ocr
        self.k = ktp_ocr

    @staticmethod
    def _png_bytes(size=(600, 360)):
        from PIL import Image
        out = io.BytesIO()
        Image.new("RGB", size, "white").save(out, "PNG")
        return out.getvalue()

    def test_ocr_image_with_mock_runner_uses_bounded_two_passes(self):
        calls = []

        def fake_runner(exe, image_path, lang, psm):
            from PIL import Image
            with Image.open(image_path) as prepared:
                size = prepared.size
                fmt = prepared.format
            calls.append({"path": image_path, "lang": lang, "psm": psm,
                          "exists": os.path.exists(image_path),
                          "size": size, "format": fmt})
            if psm == 11:
                return SAMPLE_KTP_TEXT
            return "KABUPATEN noise"

        orig = self.k.find_tesseract
        orig_langs = self.k._list_languages
        # Paksa path "ada" tanpa perlu Tesseract asli.
        self.k.find_tesseract = lambda: "tesseract-mock"
        self.k._list_languages = lambda exe: ["ind", "eng"]
        try:
            result = self.k.ocr_image(self._png_bytes(), runner=fake_runner)
        finally:
            self.k.find_tesseract = orig
            self.k._list_languages = orig_langs
        self.assertEqual(result["text"], SAMPLE_KTP_TEXT)
        self.assertEqual(result["image_type"], "png")
        self.assertEqual(result["engine"], "tesseract")
        self.assertEqual([call["psm"] for call in calls], [6, 11])
        self.assertTrue(all(call["exists"] for call in calls))
        self.assertTrue(all(call["format"] == "PNG" for call in calls))
        self.assertTrue(all(self.k.MIN_OCR_WIDTH <= call["size"][0]
                            <= self.k.MAX_OCR_WIDTH for call in calls))
        self.assertTrue(all(call["size"][0] * call["size"][1]
                            <= self.k.MAX_WORKING_PIXELS for call in calls))
        self.assertTrue(all(not os.path.exists(call["path"]) for call in calls))

    def test_temp_file_cleaned_on_runner_error(self):
        captured = {}

        def failing_runner(exe, image_path, lang, psm):
            captured["path"] = image_path
            raise RuntimeError("boom")

        orig = self.k.find_tesseract
        orig_langs = self.k._list_languages
        self.k.find_tesseract = lambda: "tesseract-mock"
        self.k._list_languages = lambda exe: ["ind"]
        try:
            with self.assertRaises(RuntimeError):
                self.k.ocr_image(self._png_bytes(), runner=failing_runner)
        finally:
            self.k.find_tesseract = orig
            self.k._list_languages = orig_langs
        # Berkas sementara harus dihapus walau runner gagal.
        self.assertFalse(os.path.exists(captured["path"]))
        self.assertFalse(os.path.exists(os.path.dirname(captured["path"])))

    def test_rejects_valid_signature_with_corrupt_image_body(self):
        orig = self.k.find_tesseract
        orig_langs = self.k._list_languages
        self.k.find_tesseract = lambda: "tesseract-mock"
        self.k._list_languages = lambda exe: ["ind"]
        try:
            with self.assertRaises(self.k.OcrError) as ctx:
                self.k.ocr_image(b"\x89PNG\r\n\x1a\ncorrupt")
        finally:
            self.k.find_tesseract = orig
            self.k._list_languages = orig_langs
        self.assertIn("rusak", str(ctx.exception).lower())

    def test_source_pixel_limit_enforced(self):
        orig_limit = self.k.MAX_SOURCE_PIXELS
        orig = self.k.find_tesseract
        orig_langs = self.k._list_languages
        self.k.MAX_SOURCE_PIXELS = 100
        self.k.find_tesseract = lambda: "tesseract-mock"
        self.k._list_languages = lambda exe: ["ind"]
        try:
            with self.assertRaises(self.k.OcrError) as ctx:
                self.k.ocr_image(self._png_bytes(size=(20, 20)))
        finally:
            self.k.MAX_SOURCE_PIXELS = orig_limit
            self.k.find_tesseract = orig
            self.k._list_languages = orig_langs
        self.assertIn("dimensi", str(ctx.exception).lower())

    def test_ocr_image_without_engine_raises_readable(self):
        orig = self.k.find_tesseract
        self.k.find_tesseract = lambda: None
        try:
            with self.assertRaises(self.k.OcrError) as ctx:
                self.k.ocr_image(b"\x89PNG\r\n\x1a\nxx")
        finally:
            self.k.find_tesseract = orig
        # Pesan aman & informatif (tidak memuat path/lokasi privat).
        self.assertIn("Tesseract", str(ctx.exception))
        self.assertNotIn("C:\\", str(ctx.exception))

    def test_ocr_image_invalid_signature_rejected(self):
        with self.assertRaises(self.k.OcrError):
            self.k.ocr_image(b"garbage-not-image")

    def test_engine_status_shape_without_engine(self):
        orig = self.k.find_tesseract
        self.k.find_tesseract = lambda: None
        try:
            st = self.k.engine_status()
        finally:
            self.k.find_tesseract = orig
        self.assertFalse(st["available"])
        self.assertIsNone(st["engine"])
        self.assertIn("detail", st)
        self.assertNotIn("C:\\", st["detail"])

    def test_run_tesseract_timeout_is_readable(self):
        import subprocess
        calls = {"n": 0}

        def fake_run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

        orig = subprocess.run
        subprocess.run = fake_run
        try:
            with self.assertRaises(self.k.OcrError) as ctx:
                self.k._run_tesseract("tesseract-mock", "x.png", "ind")
        finally:
            subprocess.run = orig
        self.assertIn("waktu", str(ctx.exception).lower())


class TestKtpOcrEndpoint(unittest.TestCase):
    """Uji endpoint OCR HTTP dengan mesin OCR ditiru (mock)."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from app import server, ktp_ocr

        # Ganti jalur OCR dengan mesin tiruan agar tidak butuh Tesseract.
        cls._orig_ocr_image = ktp_ocr.ocr_image

        def fake_ocr_image(data, filename="", runner=None):
            ktp_ocr.validate_image(data)  # tetap validasi tanda tangan asli
            return {"text": SAMPLE_KTP_TEXT, "image_type": "jpeg",
                    "language": "ind", "engine": "tesseract"}
        ktp_ocr.ocr_image = fake_ocr_image
        server.ktp_ocr.ocr_image = fake_ocr_image

        cls._server = ThreadingHTTPServer((server.HOST, 0), server.Handler)
        cls._host, cls._port = cls._server.server_address
        cls._thread = threading.Thread(
            target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        from app import ktp_ocr
        ktp_ocr.ocr_image = cls._orig_ocr_image
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)

    def _url(self, path):
        return f"http://{self._host}:{self._port}{path}"

    def _post(self, path, payload: bytes):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            self._url(path), data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read()
            finally:
                exc.close()

    def _post_json(self, path, obj):
        import json
        return self._post(path, json.dumps(obj).encode("utf-8"))

    def test_status_endpoint(self):
        import json
        import urllib.request
        with urllib.request.urlopen(
                self._url("/api/ocr/status"), timeout=5) as resp:
            data = json.loads(resp.read())
        self.assertIn("available", data)
        self.assertEqual(data["roles"], ["owner", "spouse", "debtor"])
        self.assertIn("max_image_bytes", data)

    def test_ocr_success_owner(self):
        import base64
        import json
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
        status, body = self._post_json(
            "/api/ocr/ktp", {"role": "owner", "image_base64": png})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["role"], "owner")
        self.assertEqual(data["candidates"]["owner_nik"]["value"],
                         "9999999999990001")
        self.assertIn("raw_text", data)

    def test_ocr_data_url_prefix_accepted(self):
        import base64
        import json
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
        status, body = self._post_json(
            "/api/ocr/ktp",
            {"role": "spouse", "image_base64": "data:image/png;base64," + png})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_ocr_invalid_role_is_422(self):
        import base64
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
        status, body = self._post_json(
            "/api/ocr/ktp", {"role": "boss", "image_base64": png})
        self.assertEqual(status, 422)

    def test_ocr_missing_image_is_422(self):
        status, body = self._post_json("/api/ocr/ktp", {"role": "owner"})
        self.assertEqual(status, 422)
        self.assertIn(b"Gambar", body)

    def test_ocr_bad_base64_is_422(self):
        status, body = self._post_json(
            "/api/ocr/ktp",
            {"role": "owner", "image_base64": "@@@not-base64@@@"})
        self.assertEqual(status, 422)

    def test_ocr_non_image_payload_is_422(self):
        import base64
        notimg = base64.b64encode(b"this is not an image").decode()
        status, body = self._post_json(
            "/api/ocr/ktp", {"role": "owner", "image_base64": notimg})
        self.assertEqual(status, 422)

    def test_ocr_oversized_body_is_413(self):
        # Kirim Content-Length besar (di atas batas) dengan badan kecil lewat
        # socket mentah: server harus menolak lebih dulu tanpa membaca badan,
        # sehingga koneksi tidak menggantung/mengirim 20 MB sungguhan.
        import socket
        from app import server
        big_len = server.MAX_OCR_BODY_BYTES + 10
        req = (
            "POST /api/ocr/ktp HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {big_len}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        with socket.create_connection((self._host, self._port),
                                      timeout=5) as sock:
            sock.sendall(req)
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        response = b"".join(chunks)
        self.assertIn(b"413", response.split(b"\r\n", 1)[0])

    def test_ocr_bad_json_is_400(self):
        status, _ = self._post("/api/ocr/ktp", b"{not json")
        self.assertEqual(status, 400)

    def test_ocr_error_messages_are_readable_no_paths(self):
        import base64
        import json
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
        # Paksa mesin mengembalikan galat dan pastikan pesannya bersih.
        from app import ktp_ocr
        orig = ktp_ocr.ocr_image
        ktp_ocr.ocr_image = lambda *a, **k: (_ for _ in ()).throw(
            ktp_ocr.OcrError("Mesin OCR gagal memproses gambar."))
        try:
            status, body = self._post_json(
                "/api/ocr/ktp", {"role": "owner", "image_base64": png})
        finally:
            ktp_ocr.ocr_image = orig
        self.assertEqual(status, 422)
        text = body.decode("utf-8")
        self.assertNotIn("C:\\", text)
        self.assertNotIn("Traceback", text)


class TestKtpUiAssets(unittest.TestCase):
    """Uji asap UI OCR: elemen wajib ada pada aset yang dilayani."""

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

    def test_html_has_ocr_controls(self):
        _, body = self._get("/")
        html = body.decode("utf-8")
        for token in ('id="ocr-role"', 'id="ocr-file"', 'id="ocr-run"',
                      'id="ocr-preview"', 'id="ocr-review"',
                      'id="ocr-apply"', 'id="ocr-raw-text"',
                      'accept="image/jpeg,image/png"'):
            self.assertIn(token, html, f"token UI OCR hilang: {token}")

    def test_js_has_ocr_logic_and_no_cdn_or_storage(self):
        _, body = self._get("/app.js")
        js = body.decode("utf-8")
        self.assertIn("Format valid — cek isi", js)
        self.assertNotIn("return 'Yakin'", js)
        for token in ("/api/ocr/status", "/api/ocr/ktp", "ocrApply",
                      "window.confirm"):
            self.assertIn(token, js, f"token JS OCR hilang: {token}")
        low = js.lower()
        for forbidden in ("localstorage", "sessionstorage", "indexeddb",
                          "document.cookie"):
            self.assertNotIn(forbidden, low)
        # Tidak ada URL http(s) absolut (tanpa CDN).
        import re
        self.assertIsNone(re.search(r"https?://(?!127\.0\.0\.1)", low))

    def test_role_select_has_three_roles(self):
        _, body = self._get("/")
        html = body.decode("utf-8")
        for value in ('value="owner"', 'value="spouse"', 'value="debtor"'):
            self.assertIn(value, html)


# ===========================================================================
# OCR KTP mode AI daring (opt-in) — parsing keluaran tak terpercaya, gerbang
# persetujuan, tanpa unggah di mode lokal, dan endpoint dengan penyedia tiruan.
# ===========================================================================

#: Balasan penyedia tiruan yang valid (JSON transkripsi).
AI_PROVIDER_JSON = (
    '{"nik":"9999999999990001","nama":"NAMA SINTETIS",'
    '"tempat_lahir":"KOTA KARTIKA","tanggal_lahir":"17-05-1985",'
    '"jenis_kelamin":"Laki-Laki","pekerjaan":"PETANI/PEKEBUN",'
    '"alamat":"DUSUN BARU RT 001 RW 002"}'
)


def ai_chat_response(content: str) -> bytes:
    """Bentuk balasan gaya OpenAI chat-completions berisi ``content``."""
    import json
    return json.dumps({
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant",
                                             "content": content},
                     "finish_reason": "stop"}],
    }).encode("utf-8")


class TestAiOcrParsing(unittest.TestCase):
    """Keluaran penyedia diperlakukan sebagai DATA MENTAH tak terpercaya."""

    def setUp(self):
        from app import ai_ocr
        self.ai = ai_ocr

    def test_extract_plain_json(self):
        self.assertEqual(
            self.ai._extract_json_object('{"nik":"1"}'), '{"nik":"1"}')

    def test_extract_fenced_json(self):
        text = "```json\n{\"nik\":\"1\"}\n```"
        self.assertEqual(self.ai._extract_json_object(text), '{"nik":"1"}')

    def test_extract_prose_wrapped_json(self):
        text = 'Tentu! Berikut hasilnya: {"nik":"1"} semoga membantu.'
        self.assertEqual(self.ai._extract_json_object(text), '{"nik":"1"}')

    def test_extract_missing_json_raises(self):
        with self.assertRaises(self.ai.AiOcrError):
            self.ai._extract_json_object("tidak ada json di sini")

    def test_parse_drops_unknown_keys(self):
        data = self.ai._parse_provider_json(
            '{"nik":"1234567890123456","secret":"x","bogus":1}')
        self.assertEqual(data.get("nik"), "1234567890123456")
        self.assertNotIn("secret", data)
        self.assertNotIn("bogus", data)

    def test_parse_drops_non_string_values(self):
        data = self.ai._parse_provider_json(
            '{"nik":"1234567890123456","nama":["bad"],"alamat":{"x":1}}')
        self.assertEqual(data.get("nik"), "1234567890123456")
        self.assertNotIn("nama", data)
        self.assertNotIn("alamat", data)

    def test_parse_malformed_json_raises(self):
        with self.assertRaises(self.ai.AiOcrError):
            self.ai._parse_provider_json('{"nik": }')

    def test_parse_empty_object_is_empty(self):
        self.assertEqual(self.ai._parse_provider_json("{}"), {})

    def test_parse_non_object_json_raises(self):
        with self.assertRaises(self.ai.AiOcrError):
            self.ai._parse_provider_json("[1, 2, 3]")

    def test_read_choice_content_handles_list_parts(self):
        import json
        raw = json.dumps({"choices": [{"message": {"content": [
            {"type": "text", "text": "hello"}]}}]}).encode()
        self.assertEqual(self.ai._read_choice_content(raw), "hello")

    def test_read_choice_content_provider_error_is_safe(self):
        import json
        raw = json.dumps({"error": {"message": "boom"}}).encode()
        with self.assertRaises(self.ai.AiOcrError) as ctx:
            self.ai._read_choice_content(raw)
        # Pesan tidak membocorkan isi balasan.
        self.assertNotIn("boom", str(ctx.exception))


class TestAiOcrPipeline(unittest.TestCase):
    """Jalur lengkap dengan klien HTTP ditiru (tanpa jaringan nyata)."""

    def setUp(self):
        from app import ai_ocr
        self.ai = ai_ocr
        self._orig_post = ai_ocr._post

    def tearDown(self):
        self.ai._post = self._orig_post

    @staticmethod
    def _png_bytes():
        from PIL import Image
        out = io.BytesIO()
        Image.new("RGB", (60, 40), "white").save(out, "PNG")
        return out.getvalue()

    def test_consent_required_blocks_before_network(self):
        calls = {"n": 0}

        def spy(_req):
            calls["n"] += 1
            return "{}"
        self.ai._post = spy
        with self.assertRaises(self.ai.ConsentRequired):
            self.ai.ocr_image_ai(self._png_bytes(), consent=False)
        self.assertEqual(calls["n"], 0, "tidak boleh ada panggilan jaringan "
                                        "tanpa persetujuan")

    def test_missing_api_key_blocks_before_network(self):
        from unittest import mock
        calls = {"n": 0}

        def spy(_req):
            calls["n"] += 1
            return "{}"
        self.ai._post = spy
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKMHT_AI_API_KEY", None)
            with self.assertRaises(self.ai.AiOcrError) as ctx:
                self.ai.ocr_image_ai(self._png_bytes(), consent=True)
        self.assertEqual(calls["n"], 0)
        self.assertIn("SKMHT_AI_API_KEY", str(ctx.exception))

    def test_successful_ai_extraction_and_conservative_parse(self):
        from unittest import mock
        captured = {}

        def fake_post(req):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return ai_chat_response(AI_PROVIDER_JSON).decode("utf-8")
        self.ai._post = fake_post
        with mock.patch.dict(os.environ, {"SKMHT_AI_API_KEY": "test-key"}):
            result = self.ai.ocr_image_ai(self._png_bytes(), consent=True)

        # Permintaan berbentuk chat-completions dengan image_url data URL.
        self.assertTrue(captured["url"].endswith("/chat/completions"))
        content = captured["body"]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(
            content[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        # Prompt hanya transkripsi: menolak alat/pengambilan URL.
        self.assertNotIn("tools", captured["body"])
        self.assertIn("jangan mengakses tautan", captured["body"]["messages"][0]
                      ["content"][0]["text"].lower())

        # Hasil diurai ulang lewat parser lokal yang konservatif.
        from app import ktp_ocr
        parsed = ktp_ocr.parse_ktp_fields(result["text"])
        self.assertEqual(parsed["fields"]["nik"]["value"], "9999999999990001")
        self.assertEqual(parsed["fields"]["nik"]["status"], "format_valid")
        self.assertEqual(parsed["fields"]["nama"]["status"], "review")
        self.assertEqual(result["engine"], "ai")
        self.assertEqual(result["model"], "example-vision-model")

    def test_ai_invalid_nik_not_guessed(self):
        from unittest import mock

        def fake_post(_req):
            return ai_chat_response(
                '{"nik":"12345","nama":"X"}').decode("utf-8")
        self.ai._post = fake_post
        with mock.patch.dict(os.environ, {"SKMHT_AI_API_KEY": "k"}):
            result = self.ai.ocr_image_ai(self._png_bytes(), consent=True)
        from app import ktp_ocr
        parsed = ktp_ocr.parse_ktp_fields(result["text"])
        # NIK salah panjang -> dikosongkan, tidak dilengkapi.
        self.assertEqual(parsed["fields"]["nik"]["value"], "")

    def test_ai_invalid_date_blanked(self):
        from unittest import mock

        def fake_post(_req):
            return ai_chat_response(
                '{"tanggal_lahir":"99-99-9999"}').decode("utf-8")
        self.ai._post = fake_post
        with mock.patch.dict(os.environ, {"SKMHT_AI_API_KEY": "k"}):
            result = self.ai.ocr_image_ai(self._png_bytes(), consent=True)
        from app import ktp_ocr
        parsed = ktp_ocr.parse_ktp_fields(result["text"])
        self.assertEqual(parsed["fields"]["tanggal_lahir"]["value"], "")

    def test_ai_malformed_provider_json_raises(self):
        from unittest import mock

        def fake_post(_req):
            return ai_chat_response("bukan json sama sekali").decode("utf-8")
        self.ai._post = fake_post
        with mock.patch.dict(os.environ, {"SKMHT_AI_API_KEY": "k"}):
            with self.assertRaises(self.ai.AiOcrError):
                self.ai.ocr_image_ai(self._png_bytes(), consent=True)

    def test_ai_rejects_non_image_before_send(self):
        from unittest import mock
        calls = {"n": 0}

        def spy(_req):
            calls["n"] += 1
            return "{}"
        self.ai._post = spy
        with mock.patch.dict(os.environ, {"SKMHT_AI_API_KEY": "k"}):
            with self.assertRaises(ktp_error()):
                self.ai.ocr_image_ai(b"not-an-image", consent=True)
        self.assertEqual(calls["n"], 0)


def ktp_error():
    from app import ktp_ocr
    return ktp_ocr.OcrError


class TestAiOcrNoRedirect(unittest.TestCase):
    """Pengalihan harus ditolak agar kunci/gambar tidak bocor ke host lain."""

    def test_redirect_rejected(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from unittest import mock
        from app import ai_ocr

        class RedirHandler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                return

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/evil")
                self.send_header("Content-Length", "0")
                self.end_headers()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), RedirHandler)
        host, port = srv.server_address
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.dict(os.environ, {
                    "SKMHT_AI_API_KEY": "k",
                    "SKMHT_AI_BASE_URL": f"http://{host}:{port}"}):
                png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
                with self.assertRaises(ai_ocr.AiOcrError) as ctx:
                    ai_ocr.ocr_image_ai(png, consent=True)
            self.assertIn("mengalihkan", str(ctx.exception).lower())
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=5)


class TestAiOcrConfig(unittest.TestCase):
    def test_defaults(self):
        from unittest import mock
        from app import ai_ocr
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("SKMHT_AI_BASE_URL", "SKMHT_AI_MODEL", "SKMHT_AI_TIMEOUT"):
                os.environ.pop(k, None)
            self.assertEqual(ai_ocr.base_url(), "http://localhost:8000/v1")
            self.assertEqual(ai_ocr.model_name(), "example-vision-model")

    def test_env_override(self):
        from unittest import mock
        from app import ai_ocr
        with mock.patch.dict(os.environ, {
                "SKMHT_AI_BASE_URL": "http://example.test/v1/",
                "SKMHT_AI_MODEL": "ag/other-model"}):
            self.assertEqual(ai_ocr.base_url(), "http://example.test/v1")
            self.assertEqual(ai_ocr.model_name(), "ag/other-model")

    def test_timeout_bounds(self):
        from unittest import mock
        from app import ai_ocr
        with mock.patch.dict(os.environ, {"SKMHT_AI_TIMEOUT": "9999"}):
            self.assertEqual(ai_ocr._timeout(), ai_ocr.MAX_TIMEOUT)
        with mock.patch.dict(os.environ, {"SKMHT_AI_TIMEOUT": "1"}):
            self.assertEqual(ai_ocr._timeout(), ai_ocr.MIN_TIMEOUT)

    def test_status_has_no_network_side_effect(self):
        from app import ai_ocr
        st = ai_ocr.status()
        self.assertIn("configured", st)
        self.assertIn("model", st)
        self.assertFalse(st["capability_verified"])


class TestAiOcrEndpoint(unittest.TestCase):
    """Endpoint HTTP /api/ocr/ai dengan penyedia ditiru (tanpa jaringan nyata)."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from app import server, ktp_ocr

        # Ganti OCR lokal agar tidak butuh Tesseract (mode lokal tetap diuji).
        cls._orig_local = ktp_ocr.ocr_image
        ktp_ocr.ocr_image = lambda data, filename="", runner=None: {
            "text": SAMPLE_KTP_TEXT, "image_type": "jpeg",
            "language": "ind", "engine": "tesseract"}
        server.ktp_ocr.ocr_image = ktp_ocr.ocr_image

        cls._server = ThreadingHTTPServer((server.HOST, 0), server.Handler)
        cls._host, cls._port = cls._server.server_address
        cls._thread = threading.Thread(
            target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        from app import ktp_ocr
        ktp_ocr.ocr_image = cls._orig_local
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)

    def _url(self, path):
        return f"http://{self._host}:{self._port}{path}"

    def _post(self, path, obj):
        import urllib.request
        import urllib.error
        payload = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read()
            finally:
                exc.close()

    @staticmethod
    def _png_b64():
        import base64
        return base64.b64encode(
            b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()

    def test_ai_endpoint_without_consent_is_422_no_upload(self):
        from unittest import mock
        calls = {"n": 0}
        from app import ai_ocr
        orig = ai_ocr.ocr_image_ai

        def spy(*a, **k):
            calls["n"] += 1
            raise AssertionError("tidak boleh dipanggil tanpa persetujuan")
        ai_ocr.ocr_image_ai = spy
        try:
            status, body = self._post("/api/ocr/ai", {
                "role": "owner", "image_base64": self._png_b64()})
        finally:
            ai_ocr.ocr_image_ai = orig
        self.assertEqual(status, 422)
        self.assertEqual(calls["n"], 0)
        self.assertIn(b"Persetujuan", body)

    def test_ai_endpoint_success_with_consent(self):
        from unittest import mock
        from app import ai_ocr
        orig = ai_ocr.ocr_image_ai

        def fake(data, consent, filename=""):
            assert consent is True
            return {"text": "NIK : 9999999999990001\nNama : NAMA SINTETIS",
                    "image_type": "png", "language": "ai", "engine": "ai",
                    "model": "example-vision-model"}
        ai_ocr.ocr_image_ai = fake
        try:
            status, body = self._post("/api/ocr/ai", {
                "role": "owner", "image_base64": self._png_b64(),
                "consent": True})
        finally:
            ai_ocr.ocr_image_ai = orig
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["candidates"]["owner_nik"]["value"],
                         "9999999999990001")
        self.assertEqual(data["model"], "example-vision-model")

    def test_ai_endpoint_consent_wrong_type_is_422(self):
        # consent harus boolean true, bukan string "true"/1.
        status, body = self._post("/api/ocr/ai", {
            "role": "owner", "image_base64": self._png_b64(),
            "consent": "true"})
        self.assertEqual(status, 422)

    def test_ai_endpoint_provider_error_is_422_readable(self):
        from app import ai_ocr
        orig = ai_ocr.ocr_image_ai

        def boom(data, consent, filename=""):
            raise ai_ocr.AiOcrError("Penyedia AI menolak permintaan.")
        ai_ocr.ocr_image_ai = boom
        try:
            status, body = self._post("/api/ocr/ai", {
                "role": "owner", "image_base64": self._png_b64(),
                "consent": True})
        finally:
            ai_ocr.ocr_image_ai = orig
        self.assertEqual(status, 422)
        text = body.decode("utf-8")
        self.assertNotIn("Traceback", text)
        self.assertNotIn("C:\\", text)

    def test_ai_endpoint_invalid_role_is_422(self):
        status, _ = self._post("/api/ocr/ai", {
            "role": "boss", "image_base64": self._png_b64(), "consent": True})
        self.assertEqual(status, 422)

    def test_local_endpoint_never_calls_ai(self):
        """Mode lokal TIDAK boleh memicu panggilan AI (tanpa unggah)."""
        from app import ai_ocr
        orig = ai_ocr.ocr_image_ai
        calls = {"n": 0}

        def spy(*a, **k):
            calls["n"] += 1
            raise AssertionError("mode lokal tidak boleh memanggil AI")
        ai_ocr.ocr_image_ai = spy
        try:
            status, body = self._post("/api/ocr/ktp", {
                "role": "owner", "image_base64": self._png_b64()})
        finally:
            ai_ocr.ocr_image_ai = orig
        self.assertEqual(status, 200)
        self.assertEqual(calls["n"], 0)

    def test_status_endpoint_reports_ai_without_probe(self):
        import urllib.request
        from app import ai_ocr
        orig = ai_ocr._post

        def spy(_req):
            raise AssertionError("status tidak boleh memanggil jaringan")
        ai_ocr._post = spy
        try:
            with urllib.request.urlopen(
                    self._url("/api/ocr/status"), timeout=5) as resp:
                data = json.loads(resp.read())
        finally:
            ai_ocr._post = orig
        self.assertIn("ai", data)
        self.assertIn("configured", data["ai"])
        self.assertFalse(data["ai"]["capability_verified"])
        self.assertEqual(data["modes"], ["local", "ai"])


@unittest.skipUnless(
    os.environ.get("SKMHT_AI_API_KEY"),
    "Butuh SKMHT_AI_API_KEY untuk uji probe gambar nyata ke router AI")
class TestAiOcrLiveProbe(unittest.TestCase):
    """Probe NYATA (opt-in) ke router untuk membuktikan dukungan gambar.

    Dilewati kecuali ``SKMHT_AI_API_KEY`` disetel. Mengirim **gambar sintetis**
    kecil (token uji, bukan KTP nyata) dan memastikan balasan memuat karakter
    penanda — bukan sekadar HTTP 200. Tidak menuliskan payload/isi balasan.
    """

    def test_configured_ag_model_accepts_image(self):
        from app import ai_ocr
        model = ai_ocr.model_name()
        if not model.startswith("ag/"):
            self.skipTest(f"model aktif '{model}' bukan kandidat ag/")
        result = ai_ocr.probe_vision(model=model)
        self.assertTrue(
            result["matched"],
            f"Model {model} tidak memproveksi dukungan gambar: "
            f"status={result['status']} detail={result['detail']}")


class TestAiOcrUiAssets(unittest.TestCase):
    """Aset UI menyediakan pemilih mode, pengungkapan model, dan persetujuan."""

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

    def test_html_has_mode_and_consent_controls(self):
        _, body = self._get("/")
        html = body.decode("utf-8")
        for token in ('name="ocr-mode"', 'value="local"', 'value="ai"',
                      'id="ocr-consent"', 'id="ocr-ai-panel"',
                      'id="ocr-ai-disclosure"', 'id="ocr-review-origin"'):
            self.assertIn(token, html, f"token UI mode AI hilang: {token}")

    def test_js_discloses_model_and_routes_ai_endpoint(self):
        _, body = self._get("/app.js")
        js = body.decode("utf-8")
        for token in ("/api/ocr/ai", "/api/ocr/ktp", "ocr-consent",
                      "ocrCurrentMode", "window.confirm"):
            self.assertIn(token, js, f"token JS mode AI hilang: {token}")
        # Tidak boleh ada penyimpanan persetujuan di browser.
        low = js.lower()
        for forbidden in ("localstorage", "sessionstorage", "indexeddb",
                          "document.cookie"):
            self.assertNotIn(forbidden, low)


if __name__ == "__main__":
    unittest.main(verbosity=2)
