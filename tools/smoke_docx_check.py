"""Unduh DOCX via API dan verifikasi tidak ada marker / identitas basi."""
import io
import json
import re
import time
import urllib.request
import zipfile

BASE = "http://127.0.0.1:8791"
FORM = {
    "nomor_akta": "1/ 2026", "tanggal_akta": "2026-01-05",
    "owner_title": "Tuan", "owner_nama": "Sintetis Pemilik",
    "owner_lahir_tempat": "Bandung", "owner_lahir_tanggal": "1990-01-01",
    "owner_pekerjaan": "Karyawan", "owner_dusun": "Dusun A", "owner_rt": "1",
    "owner_rw": "2", "owner_desa": "Desa X", "owner_kecamatan": "Kec Y",
    "owner_kabupaten": "Kab Z", "owner_nik": "9999999999990001",
    "spouse_mode": "istri", "spouse_nama": "Sintetis Istri",
    "spouse_lahir_tempat": "Bandung", "spouse_lahir_tanggal": "1991-02-02",
    "spouse_pekerjaan": "Ibu Rumah Tangga", "spouse_alamat_sama": "ya",
    "spouse_nik": "9999999999990002", "same_as_owner": "ya",
    "debtor_title": "Tuan", "debtor_nama": "Sintetis Debitor",
    "debtor_lahir_tempat": "Bandung", "debtor_lahir_tanggal": "1990-01-01",
    "debtor_pekerjaan": "Karyawan", "debtor_dusun": "Dusun A", "debtor_rt": "1",
    "debtor_rw": "2", "debtor_desa": "Desa X", "debtor_kecamatan": "Kec Y",
    "debtor_kabupaten": "Kab Z", "debtor_nik": "9999999999990003",
    "nilai_pembiayaan": "50.000.000", "nilai_tanggungan": "75.000.000",
    "akad_jenis": "Hawalah bil ujrah", "akad_nomor": "10/I",
    "akad_tanggal": "2026-01-01", "ht_jenis": "Hak Milik", "ht_nomor": "100",
    "ht_desa_sertifikat": "Desa X", "surat_ukur_nomor": "5/X",
    "surat_ukur_tanggal": "2026-12-01", "luas_m2": "200", "nib": "1",
    "nop": "1", "lok_provinsi": "Jawa Barat", "lok_kabupaten": "Kab Z",
    "lok_kecamatan": "Kec Y", "lok_desa": "Desa X", "lok_jalan": "Jl. Contoh",
}


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


_, raw = post("/api/review", FORM)
rev = json.loads(raw)
ack = dict(FORM)
ack["_reviewed"] = True
ack["_review_digest"] = rev["review"]["fingerprint"]
ack["_review_ts"] = int(time.time())
ack["_review_data"] = {}
ack["confirm_summary"] = True
ack["ack_digest"] = rev["digest"]
ack["ack_token"] = rev["ack_token"]
ack["summary_signature"] = rev["summary_signature"]
st, docx = post("/api/generate", ack)
assert st == 200 and docx[:2] == b"PK", (st, docx[:40])

z = zipfile.ZipFile(io.BytesIO(docx))
names = z.namelist()
assert "word/document.xml" in names
doc = z.read("word/document.xml").decode("utf-8")

leftover = re.findall(r"\{\{[^}]*\}\}", doc)
print("leftover markers     :", len(leftover), leftover[:5])
assert not leftover, leftover

assert "Sintetis Pemilik" in doc
assert "Sintetis Istri" in doc
assert "dua ratus" in doc  # terbilang luas
assert "lima puluh juta rupiah" in doc
# tidak ada teks contoh/template basi yang jelas
for forbidden in ("{{", "}}", "XXX", "Contoh Nama"):
    assert forbidden not in doc, forbidden
print("dynamic values present: OK")
print("docx entries         :", len(names))
print("VERIFIKASI DOCX LULUS.")
