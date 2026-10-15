"""End-to-end HTTP smoke (sintetis) meniru alur klien UI.

Alur: review -> ambil digest+ack_token -> generate (setuju) -> DOCX valid.
Tidak memakai data pribadi nyata; hanya data sintetis.
"""
import json
import urllib.request

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
    "spouse_dusun": "", "spouse_rt": "", "spouse_rw": "", "spouse_desa": "",
    "spouse_kecamatan": "", "spouse_kabupaten": "",
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
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


# 1) Save draft (klien: unduhan lokal)
st, raw, _ = post("/api/draft/save", FORM)
draft = json.loads(raw)
raw_draft_text = raw.decode("utf-8")
print("1. save draft       :", st, "bytes:", len(raw))
assert st == 200 and draft["kind"] == "skmht-draft"

# 2) Generate tanpa review -> wajib ditolak
st, raw, _ = post("/api/generate", FORM)
print("2. no review        :", st, "(expect 422)")
assert st == 422

# 3) Review
st, raw, _ = post("/api/review", FORM)
rev = json.loads(raw)
print("3. review           :", st, "valid:", rev["valid"],
      "digest:", rev["digest"][:12] + "...",
      "fp:", rev["review"]["fingerprint"][:12] + "...")
assert st == 200 and rev["valid"]

# 4) Generate dengan ack (meniru payload() klien persis)
ack = dict(FORM)
ack["_reviewed"] = True
ack["_review_digest"] = rev["review"]["fingerprint"]
ack["_review_ts"] = int(__import__("time").time())
ack["_review_data"] = {}
ack["confirm_summary"] = True
ack["ack_digest"] = rev["digest"]
ack["ack_token"] = rev["ack_token"]
ack["summary_signature"] = rev["summary_signature"]
st, raw, hdr = post("/api/generate", ack)
print("4. generate         :", st, "bytes:", len(raw),
      "ctype:", hdr.get("Content-Type"))
if st != 200:
    print("   ->", raw[:300])
assert st == 200 and raw[:2] == b"PK"  # zip/docx magic
name = hdr.get("Content-Disposition", "")
print("   filename         :", name[:60])

# 5) Import draft -> nilai ditandai perlu tinjau ulang (server-side)
st, raw, _ = post("/api/draft/import", {"content": raw_draft_text})
imp = json.loads(raw)
print("5. import draft     :", st, "ok:", imp.get("ok"),
      "needs_review:", len(imp.get("needs_review", [])))
if st != 200:
    print("   ->", raw[:300])
assert st == 200 and imp["ok"]
assert imp["needs_review"], "nilai impor harus ditandai perlu tinjau"

print("\nSEMUA LANGKAH SMOKE LULUS (sintetis).")
