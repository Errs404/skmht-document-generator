"""Endpoint guards without sockets or private input."""
import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from app import server, pdf_ocr, pdf_ui


class PdfEndpointTests(unittest.TestCase):
    def request(self, path, payload, origin='http://127.0.0.1:8756'):
        handler = object.__new__(server.Handler)
        body = json.dumps(payload).encode()
        handler.path = path
        handler.headers = {'Host': '127.0.0.1:8756', 'Origin': origin,
                           'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        result = []
        handler._send_json = lambda code, data: result.append((code, data))
        handler._handle_pdf()
        return result[0]

    def test_consent_and_origin_prevent_processing(self):
        with patch.object(pdf_ocr, 'extract_page') as extract:
            self.assertEqual(self.request('/api/pdf/page', {'consent': 'true'})[0], 422)
            self.assertEqual(self.request('/api/pdf/page', {'consent': True}, 'https://evil.invalid')[0], 403)
            extract.assert_not_called()

    def test_inspection_and_page_contract(self):
        payload = {'pdf_base64': base64.b64encode(b'%PDF-synthetic').decode()}
        with patch.object(pdf_ocr, 'inspect_pdf', return_value={'page_count': 7}):
            self.assertEqual(self.request('/api/pdf/inspect', payload), (200, {'ok': True, 'page_count': 7}))
        payload.update(consent=True, page=7, category='shm')
        diagnostics = {'provider_record_count': 0, 'normalized_record_count': 0,
                       'recognized_field_count': 0, 'reason': 'empty_model'}
        with patch.object(pdf_ocr, 'extract_page', return_value={'page': 7, 'records': [], 'diagnostics': diagnostics}) as extract:
            code, response = self.request('/api/pdf/page', payload)
            self.assertEqual(code, 200)
            self.assertEqual(response['diagnostics'], diagnostics)
            extract.assert_called_once_with(b'%PDF-synthetic', 7, 'shm', consent=True)
        with patch.object(pdf_ocr, 'extract_page', side_effect=pdf_ocr.PdfOcrError('Balasan AI bukan JSON records yang sah.')):
            self.assertEqual(self.request('/api/pdf/page', payload)[0], 422)

    def test_aliases(self):
        records = pdf_ocr._parse_records(json.dumps({'records':[{'fields':{'no_shm':'00123', 'kelurahan':'Contoh'}}]}), 'shm')
        self.assertEqual(records[0]['fields']['ht_nomor'], '00123')
        self.assertEqual(records[0]['fields']['lok_desa'], 'Contoh')

    def test_pdf_ui_node_test(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node.js not available")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".js", mode="w", encoding="utf-8") as f:
            f.write(pdf_ui.JS)
            temp_path = f.name
        try:
            test_js = os.path.join(os.path.dirname(__file__), "pdf_ui_test.js")
            res = subprocess.run([node, test_js, temp_path],
                                 capture_output=True, text=True, check=False)
            self.assertEqual(res.returncode, 0, f"pdf_ui_test.js failed: {res.stdout}\n{res.stderr}")
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
