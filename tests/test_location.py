"""Location formatting preserves user-entered zero padding and case."""
import io
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app import docx_template, drafts, fields, server
from app.textutil import ValidationError


class LocationTests(unittest.TestCase):
    def form(self, **changes):
        data = server._demo_form()
        data.update(lok_jalan="Bakalan", lok_rt="003", lok_rw="06")
        data.update(changes)
        return data

    def test_exact_marker_and_summary(self):
        ctx = fields.validate_and_build(self.form())
        values = fields.build_marker_values(ctx)
        self.assertEqual(values["lok_jalan"], "Bakalan")
        self.assertEqual(values["lok_rt"], "003")
        self.assertEqual(values["lok_rw"], "06")
        self.assertEqual(fields.canonical_summary(ctx)["lokasi"]["lok_jalan"],
                         "Bakalan Rukun Tetangga 003, Rukun Warga 06.")
        self.assertEqual(ctx["lok_jalan"], "Bakalan")

    def test_digits_required_and_no_coercion(self):
        for key in ("lok_rt", "lok_rw"):
            for value in ("", "0033", "RT003", "3x", "-1"):
                with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                    fields.validate_and_build(self.form(**{key: value}))

    def test_split_template_render(self):
        values = fields.build_marker_values(fields.validate_and_build(self.form()))
        template = server._load_template()
        result = docx_template.render_docx_from_template(
            template, values, required_keys=fields.REQUIRED_MARKER_KEYS,
            removal_keys=fields.REMOVAL_MARKER_KEYS)
        with ZipFile(io.BytesIO(result)) as z:
            self.assertIsNone(z.testzip())
            root = ET.fromstring(z.read("word/document.xml"))
        text = "".join(n.text or "" for n in root.iter(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        self.assertEqual(text.count("Bakalan Rukun Tetangga 003, Rukun Warga 06."), 1)
        self.assertNotIn("{{", text)
        self.assertTrue(server._template_status()["available"])

    def test_draft_roundtrip(self):
        data = self.form()
        parsed = drafts.parse_draft(drafts.draft_to_json(data))
        self.assertEqual(parsed["data"]["lok_rt"], "003")
        self.assertEqual(parsed["data"]["lok_rw"], "06")

    def test_legacy_explicit_suffix(self):
        for street in ("Bakalan RT003/RW06", "Bakalan RT 003 RW 06",
                       "Bakalan Rukun Tetangga 003, Rukun Warga 06."):
            ctx = fields.validate_and_build(self.form(lok_jalan=street, lok_rt="", lok_rw=""))
            self.assertEqual(fields.format_location(ctx),
                             "Bakalan Rukun Tetangga 003, Rukun Warga 06.")

    def test_legacy_without_numbers_requires_completion(self):
        with self.assertRaises(ValidationError):
            fields.validate_and_build(self.form(lok_rt="", lok_rw=""))

    def test_conflicting_legacy_rejected(self):
        with self.assertRaises(ValidationError):
            fields.validate_and_build(self.form(lok_jalan="Bakalan RT001/RW06"))

    def test_case_and_terminal_punctuation(self):
        ctx = fields.validate_and_build(self.form(lok_jalan="Jalan bARu.;"))
        self.assertEqual(ctx["lok_jalan"], "Jalan bARu")
        self.assertEqual(fields.format_location(ctx),
                         "Jalan bARu Rukun Tetangga 003, Rukun Warga 06.")


if __name__ == "__main__":
    unittest.main()
