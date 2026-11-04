import copy
import unittest

from app import ai_ocr, ktp_ocr, ocr_format


class TestOcrCasing(unittest.TestCase):
    def test_local_and_ai_ktp_review(self):
        raw = {
            "nama": "AMINAH SITI-NUR", "nik": "9999999999990001",
            "tempat_lahir": "KOTA CONTOH", "tanggal_lahir": "17-05-1985",
            "jenis_kelamin": "PEREMPUAN", "pekerjaan": "PETANI/PEKEBUN",
            "alamat": "DSN CONTOH", "rt_rw": "001/002",
            "kel_desa": "CONTOH SATU", "kecamatan": "CONTOH DUA",
        }
        original = copy.deepcopy(raw)
        local = "\n".join([
            "Nama: AMINAH SITI-NUR", "NIK: 9999999999990001",
            "Tempat/Tgl Lahir: KOTA CONTOH, 17-05-1985",
            "Jenis Kelamin: PEREMPUAN", "Pekerjaan: PETANI/PEKEBUN",
            "Alamat: DSN CONTOH", "RT/RW: 001/002",
            "Kel/Desa: CONTOH SATU", "Kecamatan: CONTOH DUA",
        ])
        for mode, text in (("local", local),
                           ("ai", ai_ocr._fields_to_labeled_text(raw))):
            with self.subTest(mode=mode):
                parsed = ktp_ocr.parse_ktp_fields(text)
                fields = parsed["fields"]
                for key, expected in {
                    "nama": "AMINAH SITI-NUR", "tempat_lahir": "Kota Contoh",
                    "pekerjaan": "Petani/Pekebun", "dusun": "Contoh",
                    "kel_desa": "Contoh Satu", "kecamatan": "Contoh Dua",
                    "nik": raw["nik"], "tanggal_lahir": "1985-05-17",
                    "rt": "001", "rw": "002", "jenis_kelamin": "Perempuan",
                }.items():
                    self.assertEqual(fields[key]["value"], expected, key)
                self.assertEqual(parsed["raw_text"], text)
                for role in ("owner", "spouse", "debtor"):
                    candidates = ktp_ocr.candidates_for_role(parsed, role)
                    for entry in candidates.values():
                        source = entry["source"]
                        self.assertEqual(entry["value"], fields[source]["value"])
        self.assertEqual(raw, original)

    def test_allowlist_preserves_nonhuman_fields_and_acronyms(self):
        for key in ("nama", "pemegang_hak"):
            self.assertEqual(ocr_format.format_field(key, "Aminah Siti-Nur"),
                             "AMINAH SITI-NUR")
        for key in ("nik", "nib", "nop", "nomor_shm", "nomor_surat_ukur",
                    "tanggal_lahir", "rt", "rw", "luas_m2", "jenis_kelamin"):
            self.assertEqual(ocr_format.format_field(key, "001/ABC m2"), "001/ABC m2")
        self.assertEqual(ocr_format.format_field("alamat", "JALAN BARU RT 001 RW 002 A12"),
                         "Jalan Baru RT 001 RW 002 A12")
        self.assertEqual(ocr_format.format_field("pekerjaan", "PNS/TNI"), "PNS/TNI")


if __name__ == "__main__":
    unittest.main()
