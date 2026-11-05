import io
import json
import subprocess
import unittest
from unittest.mock import patch

import pypdfium2 as pdfium
from PIL import Image

from app import pdf_ocr


def synthetic_pdf(pages=1, width=600, height=800):
    with pdfium.PdfDocument.new() as document:
        for _ in range(pages):
            document.new_page(width, height).close()
        output = io.BytesIO()
        document.save(output)
        return output.getvalue()


class PdfTests(unittest.TestCase):
    def setUp(self):
        # A missed client mock must never send even synthetic data externally.
        guard = patch.object(pdf_ocr.ai_ocr, "_post",
                             side_effect=AssertionError("Network forbidden in PDF tests"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_inspect_is_local(self):
        with patch.object(pdf_ocr.ai_ocr, "_request_json") as network:
            self.assertEqual(pdf_ocr.inspect_pdf(synthetic_pdf(2)), {"page_count": 2})
        network.assert_not_called()

    def test_invalid_documents(self):
        for data in (b"", b"not pdf", b"%PDF-1.7 corrupt", synthetic_pdf(21),
                     b"%PDF-" + b"x" * pdf_ocr.MAX_PDF_BYTES):
            with self.subTest(size=len(data)), self.assertRaises(pdf_ocr.PdfOcrError):
                pdf_ocr.inspect_pdf(data)

    def test_encrypted_even_when_document_opens(self):
        # Models an empty-user-password PDF: load succeeds, revision is >= 0.
        with patch("pypdfium2.raw.FPDF_GetSecurityHandlerRevision", return_value=4):
            with self.assertRaisesRegex(pdf_ocr.PdfOcrError, "terenkripsi"):
                pdf_ocr._worker(synthetic_pdf(), 0)

    def test_render_edge_and_page_range(self):
        data = synthetic_pdf(width=5000, height=9000)
        image = pdf_ocr._run_worker(data, 1)
        with Image.open(io.BytesIO(image)) as rendered:
            self.assertLessEqual(max(rendered.size), 1800)
        with self.assertRaises(pdf_ocr.PdfOcrError):
            pdf_ocr._run_worker(data, 2)

    def test_timeout_sanitized(self):
        with patch.object(pdf_ocr.subprocess, "run", side_effect=
                          subprocess.TimeoutExpired("private", 30, output=b"secret")):
            with self.assertRaisesRegex(pdf_ocr.PdfOcrError, "batas waktu"):
                pdf_ocr.inspect_pdf(b"%PDF-1.7")

    def test_consent_strict_no_worker_or_network(self):
        with patch.object(pdf_ocr, "_run_worker") as worker, \
                patch.object(pdf_ocr.ai_ocr, "_request_json") as network:
            for consent in (False, None, 1, "true"):
                with self.assertRaises(pdf_ocr.ConsentRequired):
                    pdf_ocr.extract_page(b"%PDF-", 1, "identity", consent)
        worker.assert_not_called()
        network.assert_not_called()

    def test_boundary_validation(self):
        for page, category in ((True, "identity"), (0, "identity"),
                               (21, "identity"), (1, "other"), (1, [])):
            with self.assertRaises(pdf_ocr.PdfOcrError):
                pdf_ocr.extract_page(b"%PDF-", page, category, True)

    def parse(self, category, *fields):
        return pdf_ocr._parse_records(json.dumps({"records": [
            {"fields": field} for field in fields]}), category)

    def test_identity_separate_role_neutral_preserves_zeros(self):
        records = self.parse("identity", {"nama": "BUDI", "nik": "0012345678901234",
                            "rt_rw": "001/002", "tanggal_lahir": "02-03-1990"},
                             {"nama": "SITI", "owner_nama": "Injected"})
        self.assertEqual(len(records), 2)
        first = records[0]["fields"]
        self.assertEqual(first["nik"], "0012345678901234")
        self.assertEqual(first["rt"], "001")
        self.assertEqual(first["lahir_tanggal"], "1990-03-02")
        self.assertNotIn("owner_nama", records[1]["fields"])

    def test_shm_whitelist(self):
        fields = self.parse("shm", {"nomor_shm": "0012", "desa": "SUKA",
                            "kecamatan": "MAJU", "nop": "0001", "nama": "NO",
                            "luas_m2": "00150", "nib": "00123"})[0]["fields"]
        self.assertEqual(fields["ht_nomor"], "0012")
        self.assertEqual(fields["lok_desa"], fields["ht_desa_sertifikat"])
        self.assertEqual(fields["luas_m2"], "00150")
        self.assertNotIn("nop", fields)
        self.assertNotIn("nama", fields)

    def test_akad_distinct_no_inference(self):
        fields = self.parse("akad", {"akad_nomor": "001/A", "akad_jenis": "Murabahah",
                            "akad_tanggal": "31-02-2025", "nilai_pembiayaan": "001000",
                            "nilai_tanggungan": 1000, "nomor_akta": "11"})[0]["fields"]
        self.assertEqual(fields["nilai_pembiayaan"], "001000")
        self.assertNotIn("nilai_tanggungan", fields)
        self.assertNotIn("akad_tanggal", fields)
        self.assertNotIn("nomor_akta", fields)

    def test_strict_json(self):
        for text in ('prefix {"records": []}',
                     '{"records": [], "records": []}', '{"records": null}',
                     '{"records": [1]}', '{"records": NaN}'):
            with self.subTest(text=text), self.assertRaises(pdf_ocr.PdfOcrError):
                pdf_ocr._parse_records(text, "identity")

    def test_supported_contract_shapes(self):
        fields = {"nama": "TEST ALPHA", "nik": "0012345678901234",
                  "desa": "TEST DESA", "tanggal_lahir": "02-03-1990"}
        expected = self.parse("identity", fields)
        for obj in ({"records": [{"fields": fields}]}, [{"fields": fields}],
                    {"fields": fields}, fields, [fields], {"records": [fields]}):
            for text in (json.dumps(obj), '\ufeff' + json.dumps(obj),
                         '```json\n' + json.dumps(obj) + '\n```'):
                self.assertEqual(pdf_ocr._parse_records(text, "identity"), expected)
        self.assertEqual(expected[0]["fields"]["desa"], "Test Desa")
        self.assertNotIn("title", expected[0]["fields"])

    def test_ambiguous_wrappers_and_truncation_rejected(self):
        for obj in ({"data": {"nama": "TEST"}},
                    {"nama": "TEST", "other": {"nama": "SECOND"}},
                    {"records": [], "fields": {"nama": "TEST"}},
                    {"fields": {"nama": "TEST"}, "person": {"nama": "SECOND"}}):
            with self.assertRaises(pdf_ocr.PdfOcrError):
                pdf_ocr._parse_records(json.dumps(obj), "identity")
        with self.assertRaisesRegex(pdf_ocr.PdfOcrError, "terpotong"):
            pdf_ocr._parse_records('{"records":[{"fields":', "identity")
        self.assertEqual(self.parse("identity", {"nik": 1234567890123456}), [])

    def test_http_contract_and_finish_reason_no_retry(self):
        ai = pdf_ocr.ai_ocr
        for finish in ("stop", "length"):
            envelope = json.dumps({"choices": [{"finish_reason": finish,
                "message": {"content": '```json\n{"records":[{"fields":{"nama":"TEST ALPHA"}},{"fields":{"nama":"TEST BETA"}}]}\n```'}}]})
            with patch.object(ai, "_post", return_value=envelope) as post:
                if finish == "length":
                    with self.assertRaisesRegex(ai.AiOcrError, "terpotong"):
                        ai._request_json("test", pdf_ocr._prompt("identity"), [], json_mode=True)
                else:
                    text = ai._request_json("test", pdf_ocr._prompt("identity"), [], json_mode=True)
                    self.assertEqual(len(pdf_ocr._parse_records(text, "identity")), 2)
                post.assert_called_once()
                body = json.loads(post.call_args.args[0].data)
                self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_extraction_mock_network_real_render(self):
        with patch.object(pdf_ocr.ai_ocr, "_api_key", return_value="test"), \
                patch.object(pdf_ocr.ai_ocr, "_request_json", return_value=
                             '{"records":[{"fields":{"akad_nomor":"001/A"}}]}') as request:
            result = pdf_ocr.extract_page(synthetic_pdf(), 1, "akad", True)
        self.assertEqual(result, {"page": 1, "records": [{"fields": {"akad_nomor": "001/A"}}],
                         "diagnostics": {"provider_record_count": 1, "normalized_record_count": 1,
                                         "recognized_field_count": 1, "reason": None}})
        self.assertEqual(request.call_args.args[2][0][1], "png")
        self.assertTrue(request.call_args.args[2][0][0].startswith(b"\x89PNG"))

    def test_safe_empty_diagnostics(self):
        for records, recognized, reason in [([], 0, 'empty_model'),
                ([{'fields': {'nik': 123, 'unknown': 'PRIVATE'}}], 0, 'no_usable_fields'),
                ([{'fields': {'akad_tanggal': '31-02-2025'}}], 1, 'no_usable_fields')]:
            with self.subTest(reason=reason):
                diagnostics = {}
                self.assertEqual(pdf_ocr._parse_records(json.dumps({'records': records}), 'akad', diagnostics), [])
                self.assertEqual(diagnostics, {'provider_record_count': len(records),
                    'normalized_record_count': 0, 'recognized_field_count': recognized, 'reason': reason})

    def test_missing_records_is_error(self):
        for value in ({}, {'records': {}}, {'records': [{'fields': []}]}):
            with self.assertRaises(pdf_ocr.PdfOcrError):
                pdf_ocr._parse_records(json.dumps(value), 'identity')


if __name__ == "__main__":
    unittest.main()
