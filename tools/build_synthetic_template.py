#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bangun template DOCX SINTETIS berbasis marker untuk edisi publik.

Skrip ini membuat ``templates/SKMHT.example.template.docx`` DARI NOL memakai
hanya pustaka standar (``zipfile`` + ``xml.etree``). Templat ini:

- memuat SELURUH marker ``{{key}}`` yang dibutuhkan aplikasi
  (lihat ``app.fields.REQUIRED_MARKER_KEYS`` dan
  ``app.fields.REMOVAL_MARKER_KEYS``), sehingga kontrak render tetap utuh;
- memakai teks klausul generik/demonstratif (BUKAN salinan dokumen nyata),
  aktor sintetis tetap, dan penanda "CONTOH"/"DEMO" yang eksplisit;
- mempertahankan inventaris fitur mesin templating: tab leader ``hyphen``,
  run ber-bold, font ``Bookman Old Style`` ukuran 24, dan deklarasi
  namespace Office yang lazim (termasuk prefiks yang hanya dirujuk lewat
  nilai atribut ``mc:Ignorable``).

Jalankan dari folder aplikasi:

    python tools/build_synthetic_template.py

Berkas keluaran ditulis ulang setiap kali skrip dijalankan (deterministik
kecuali stempel waktu zip, lihat ``SOURCE_DATE_EPOCH``).
"""

from __future__ import annotations

import os
import sys
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import fields  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)
OUT_PATH = os.path.join(BASE_DIR, "templates", "SKMHT.example.template.docx")

# Prefiks namespace Office yang lazim muncul di document.xml Word. Beberapa
# di antaranya (mis. w14/w15/wp14) hanya dirujuk lewat nilai atribut
# ``mc:Ignorable`` sehingga harus tetap terdeklarasi walau tak dipakai nama
# elemen. Ini meniru struktur berkas Word nyata tanpa menyalin isinya.
_NS_DECLARATIONS = (
    ("wpc", "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"),
    ("cx", "http://schemas.microsoft.com/office/drawing/2014/chartex"),
    ("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006"),
    ("o", "urn:schemas-microsoft-com:office:office"),
    ("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
    ("m", "http://schemas.openxmlformats.org/officeDocument/2006/math"),
    ("v", "urn:schemas-microsoft-com:vml"),
    ("wp14", "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"),
    ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"),
    ("w10", "urn:schemas-microsoft-com:office:word"),
    ("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main"),
    ("w14", "http://schemas.microsoft.com/office/word/2010/wordml"),
    ("w15", "http://schemas.microsoft.com/office/word/2012/wordml"),
    ("w16", "http://schemas.microsoft.com/office/word/2018/wordml"),
    ("w16cex", "http://schemas.microsoft.com/office/word/2018/wordml/cex"),
    ("w16cid", "http://schemas.microsoft.com/office/word/2016/wordml/cid"),
    ("w16du", "http://schemas.microsoft.com/office/word/2023/wordml/word16du"),
    ("w16sdtdh", "http://schemas.microsoft.com/office/word/2020/wordml/sdtdatahash"),
    ("w16sdtfl", "http://schemas.microsoft.com/office/word/2026/wordml/sdtformatlock"),
    ("w16se", "http://schemas.microsoft.com/office/word/2015/wordml/symex"),
    ("wpg", "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"),
    ("wpi", "http://schemas.microsoft.com/office/word/2010/wordprocessingInk"),
    ("wne", "http://schemas.microsoft.com/office/word/2006/wordml"),
    ("wps", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"),
)

# mc:Ignorable meniru berkas Word; semua prefiks di sini terdeklarasi di atas
# (walaupun sebagian hanya dirujuk lewat nilai atribut).
_MC_IGNORABLE = ("w14 w15 w16se w16cid w16 w16cex w16sdtdh w16sdtfl w16du wp14")

_RPR_BODY = (
    '<w:rPr><w:rFonts w:ascii="Bookman Old Style" w:hAnsi="Bookman Old Style"'
    ' w:cs="Bookman Old Style"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>'
)
_RPR_BOLD = (
    '<w:rPr><w:rFonts w:ascii="Bookman Old Style" w:hAnsi="Bookman Old Style"'
    ' w:cs="Bookman Old Style"/><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>'
)

#: Tab leader kanan (posisi teks 8363 twip) untuk paragraf yang diakhiri
#: deret titik-titik pemisah pada dokumen contoh. Dua tab kiri meniru baris
#: tanda tangan.
_TABS_HYPHEN = (
    '<w:tabs><w:tab w:val="right" w:leader="hyphen" w:pos="8363"/></w:tabs>'
)
_TABS_SIG = (
    '<w:tabs>'
    '<w:tab w:val="right" w:leader="hyphen" w:pos="8363"/>'
    '<w:tab w:val="left" w:leader="hyphen" w:pos="8513"/>'
    '<w:tab w:val="left" w:leader="hyphen" w:pos="10206"/>'
    '</w:tabs>'
)


def _r(text: str, *, bold: bool = False, tab_leader: bool = False) -> str:
    """Run ``<w:r>`` dengan teks ter-escape; opsional diakhiri ``<w:tab/>``."""
    rpr = _RPR_BOLD if bold else _RPR_BODY
    body = f'<w:t xml:space="preserve">{escape(text)}</w:t>'
    if tab_leader:
        body += "<w:tab/>"
    return f"<w:r>{rpr}{body}</w:r>"


def _p(*runs: str, tabs: str = "") -> str:
    """Paragraf ``<w:p>`` dari run yang diberikan; ``tabs`` mengisi ``pPr``."""
    ppr = f"<w:pPr>{tabs}</w:pPr>" if tabs else ""
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def _build_body() -> str:
    """Isi ``<w:body>`` sintetis (teks demonstratif).

    Semua teks yang tampak adalah contoh generik/demonstratif; identitas
    bersifat placeholder dan klausul ditulis ulang generik. Marker ``{{key}}``
    mengikuti skema aplikasi (dipakai apa adanya oleh mesin render).
    """
    p = _p

    paras: list[str] = []

    # --- Judul & nomor akta ------------------------------------------------
    paras.append(p(_r("CONTOH TEMPLATE SURAT KUASA MEMBEBANKAN HAK TANGGUNGAN",
                      bold=True)))
    paras.append(p(_r("(DOKUMEN DEMONSTRASI - BUKAN INSTRUMEN HUKUM SIAP PAKAI)")))
    paras.append(p(_r("Nomor : {{nomor_akta}}", bold=True)))
    paras.append(p(_r("Lembar Pertama")))

    # --- Kepala notaris (aktor sintetis tetap) -----------------------------
    paras.append(p(
        _r("Pada hari ini, {{tanggal_akta_lengkap}}, hadir di hadapan saya "),
        _r("NOTARIS CONTOH, Sarjana Hukum, Magister Kenotariatan", bold=True),
        _r(", yang berdasarkan Surat Keputusan Menteri Hukum dan Hak Asasi "
           "Manusia Republik Indonesia tanggal 1 Januari 2000 Nomor: "
           "AHU-CONTOH-00000 diangkat sebagai Notaris, dengan daerah kerja "
           "Provinsi Contoh dan berkantor di Jalan Contoh, Rukun Tetangga "
           "001, Rukun Warga 001, Desa Kota Contoh, Kecamatan Kota Contoh, "
           "Kabupaten Kota Contoh, dengan dihadiri oleh saksi-saksi yang saya "
           "kenal dan akan disebut pada bagian akhir akta ini:"),
    ))

    # --- Identitas pemberi kuasa / pemilik --------------------------------
    paras.append(p(
        _r("{{owner_title}} "),
        _r("{{owner_nama}}", bold=True),
        _r(" Lahir di {{owner_lahir_tempat}} pada tanggal "
           "{{owner_lahir_tanggal_kata}} ({{owner_lahir_tanggal_singkat}}), "
           "Warga Negara Indonesia, Kawin, {{owner_pekerjaan}}, "
           "{{owner_alamat}}, Pemegang Kartu Tanda Penduduk Nomor Induk "
           "Kependudukan: {{owner_nik}}"),
    ))
    paras.append(p(_r("Selanjutnya disebut Pemberi Kuasa.")))

    # --- Persetujuan pasangan ---------------------------------------------
    paras.append(p(_r("{{spouse_intro}}")))
    paras.append(p(
        _r("{{spouse_title}} "),
        _r("{{spouse_nama}}", bold=True),
        _r(", lahir di {{spouse_lahir_tempat}}, pada tanggal "
           "{{spouse_lahir_tanggal_kata}} ({{spouse_lahir_tanggal_singkat}}), "
           "Warga Negara Indonesia, Kawin, {{spouse_pekerjaan}}, "
           "{{spouse_alamat}}, Pemegang Kartu Tanda Penduduk Nomor Induk "
           "Kependudukan : {{spouse_nik}}"),
    ))

    # --- Penerima kuasa (aktor lembaga sintetis tetap) --------------------
    paras.append(p(
        _r("Tuan "),
        _r("PENERIMA KUASA CONTOH", bold=True),
        _r(", lahir di Kabupaten Contoh, pada tanggal 03-03-2000, Warga Negara "
           "Indonesia, Karyawan Swasta, bertempat tinggal di Dusun Contoh, "
           "Rukun Tetangga 003, Rukun Warga 015, Desa Kecamatan Contoh, "
           "Kecamatan Kecamatan Contoh, Kabupaten Kabupaten Contoh. Dalam hal "
           "ini bertindak berdasarkan Surat Keputusan tertanggal 02-01-2000 "
           "Nomor: SK/CONTOH/2023, dari dan karenanya mewakili Pengurus dari "
           "dan sebagai demikian berwenang bertindak untuk dan atas nama "),
        _r("LEMBAGA PEMBIAYAAN CONTOH", bold=True),
        _r(", berkedudukan di Kabupaten Kabupaten Contoh, selanjutnya disebut "
           "Penerima Kuasa."),
    ))
    paras.append(p(_r("Para penghadap dikenal oleh saya.")))
    paras.append(p(_r("Pemberi Kuasa menerangkan dengan ini memberi kuasa "
                      "kepada Penerima Kuasa.")))

    # --- Bagian KHUSUS -----------------------------------------------------
    paras.append(p(_r("--------------------------------------------------- "
                      "K H U S U S -----------------------------------------")))
    paras.append(p(_r("untuk membebankan Hak Tanggungan guna menjamin "
                      "pelunasan Pembiayaan")))

    # --- Identitas debitor -------------------------------------------------
    paras.append(p(
        _r("{{debtor_title}} "),
        _r("{{debtor_nama}}", bold=True),
        _r(", Lahir di {{debtor_lahir_tempat}} pada tanggal "
           "{{debtor_lahir_tanggal_kata}} ({{debtor_lahir_tanggal_singkat}}), "
           "Warga Negara Indonesia, Kawin, {{debtor_pekerjaan}}, "
           "{{debtor_alamat}}, Pemegang Kartu Tanda Penduduk Nomor Induk "
           "Kependudukan : {{debtor_nik}},"),
    ))

    # --- Nilai pembiayaan --------------------------------------------------
    paras.append(p(_r("{{nilai_pembiayaan_teks}}")))
    paras.append(p(_r("{{nilai_pembiayaan_kata}}")))
    paras.append(p(
        _r("berdasarkan perjanjian pembiayaan yang ditandatangani oleh "
           "Debitor/Pemberi Kuasa dengan "),
        _r("LEMBAGA PEMBIAYAAN CONTOH", bold=True),
        _r(", selaku Kreditor dan dibuktikan dengan : {{akad_jenis_teks}} "
           "{{akad_nomor_teks}} {{akad_tanggal_teks}}, bermaterai cukup, dan "
           "penambahan, perubahan, perpanjangan serta Pembaharuannya yang "
           "mungkin diadakan kemudian, sampai sejumlah nilai Tanggungan "
           "Peringkat Pertama sebesar"),
    ))
    paras.append(p(_r("{{nilai_tanggungan_teks}}")))
    paras.append(p(_r("atas Objek Hak Tanggungan berupa 1 (satu) Hak atas "
                      "Tanah yang diuraikan di bawah ini:")))

    # --- Objek hak tanggungan / tanah -------------------------------------
    paras.append(p(_r("{{ht_teks}}")))
    paras.append(p(
        _r("atas sebidang tanah sebagaimana diuraikan dalam Surat Ukur "
           "tanggal {{surat_ukur_tanggal_teks}}, Nomor: {{surat_ukur_nomor}}, "
           "seluas {{luas_m2}} M2 ({{luas_kata}} meter persegi), dengan Nomor "
           "Identifikasi Bidang Tanah (NIB): {{nib}}, Surat Pemberitahuan "
           "Pajak Terhutang Pajak Bumi dan Bangunan (SPPTPBB) Nomor Objek "
           "Pajak (NOP): {{nop}}."),
    ))

    # --- Lokasi objek ------------------------------------------------------
    paras.append(p(_r("terletak di :")))
    paras.append(p(_r("Provinsi: {{lok_provinsi}} ;")))
    paras.append(p(_r("Kabupaten: {{lok_kabupaten}} ;")))
    paras.append(p(_r("Kecamatan: {{lok_kecamatan}} ;")))
    paras.append(p(_r("Desa: {{lok_desa}} ;")))
    # Baris jalan dipecah dua paragraf seperti bentuk Word asli; paragraf
    # kedua dibersihkan oleh marker ``_remove_jalan_cont`` (gagal-keras bila
    # bernilai non-kosong) sehingga tidak ada sisa teks contoh.
    paras.append(p(_r("Jalan: {{lok_jalan}} ;", tab_leader=True),
                   tabs=_TABS_HYPHEN))
    paras.append(p(_r("{{_remove_jalan_cont}}")))

    # --- Klausul kuasa generik (ditulis ulang, bukan salinan) -------------
    paras.append(p(_r(
        "Sertipikat dan bukti pemilikan yang disebutkan di atas diperlihatkan "
        "kepada saya, Notaris, untuk keperluan pembuatan Surat Kuasa "
        "Membebankan Hak Tanggungan ini. Objek Hak Tanggungan ini meliputi "
        "pula bidang tanah beserta turutan-turutannya baik yang ada sekarang "
        "maupun ditambah, dibangun yang oleh karena sifat dan peruntukannya "
        "menurut hukum dianggap sebagai bagian yang tidak terpisahkan dengan "
        "bidang tanah tersebut di atas.")))
    paras.append(p(_r(
        "Kuasa untuk membebankan Hak Tanggungan ini meliputi kuasa untuk "
        "menghadap di mana perlu, memberikan keterangan, memperlihatkan dan "
        "menyerahkan surat-surat yang diminta, membuat atau meminta dibuatkan "
        "serta menandatangani Akta Pemberian Hak Tanggungan serta surat-surat "
        "lain yang diperlukan, serta memilih domisili. Kuasa yang diberikan "
        "dengan akta ini tidak dapat ditarik kembali dan tidak berakhir "
        "karena sebab apa pun kecuali oleh karena telah dilaksanakan "
        "pembuatan Akta Pemberian Hak Tanggungan.")))

    # --- Saksi-saksi (aktor sintetis tetap) -------------------------------
    paras.append(p(_r("Demikian akta ini dibuat di hadapan para pihak dan:")))
    paras.append(p(_r("Saksi-saksi : ")))
    paras.append(p(
        _r("Tuan "),
        _r("SAKSI CONTOH SATU", bold=True),
        _r(", lahir di Kota Contoh, tanggal 01-01-2000, Warga Negara "
           "Indonesia, bertempat tinggal di Dusun Contoh, Rukun Tetangga 002, "
           "Rukun Warga 003, Desa Desa Contoh, Kecamatan Kecamatan Contoh, "
           "Kabupaten Kota Contoh."),
    ))
    paras.append(p(
        _r("Tuan "),
        _r("SAKSI CONTOH DUA", bold=True),
        _r(", lahir di Kota Contoh, tanggal 02-02-2000, Warga Negara "
           "Indonesia, bertempat tinggal di Jalan Contoh, Rukun Tetangga 002, "
           "Rukun Warga 013, Kelurahan Kelurahan Contoh, Kecamatan Kota "
           "Contoh Tengah, Kota Kota Contoh."),
    ))
    paras.append(p(_r(
        "sebagai saksi-saksi dan setelah dibacakan serta dijelaskan, maka "
        "sebagai bukti kebenaran pernyataan yang dikemukakan oleh Pemberi "
        "Kuasa dan Penerima Kuasa tersebut di atas, akta ini ditandatangani "
        "oleh Pemberi Kuasa, Penerima Kuasa, para saksi dan saya, Notaris "
        "sebanyak 2 (dua) rangkap asli. DOKUMEN DEMONSTRASI: bukan instrumen "
        "hukum siap pakai.")))

    # --- Blok tanda tangan -------------------------------------------------
    paras.append(p(
        _r("Pemberi Kuasa", tab_leader=True),
        _r("Penerima Kuasa", tab_leader=True),
        _r("Materai"),
        tabs=_TABS_SIG,
    ))
    paras.append(p(
        _r("{{owner_nama}}", bold=True, tab_leader=True),
        _r("PENERIMA KUASA CONTOH", bold=True, tab_leader=True),
        tabs=_TABS_HYPHEN,
    ))
    paras.append(p(_r("qq. LEMBAGA PEMBIAYAAN CONTOH")))
    paras.append(p(_r("{{persetujuan_label}}")))
    paras.append(p(_r("{{spouse_nama_sig}}")))
    paras.append(p(_r("Saksi"), _r("Saksi")))
    paras.append(p(
        _r("SAKSI CONTOH SATU", bold=True, tab_leader=True),
        _r("SAKSI CONTOH DUA", bold=True, tab_leader=True),
        tabs=_TABS_HYPHEN,
    ))
    paras.append(p(_r("Notaris")))
    paras.append(p(_r("NOTARIS CONTOH, S.H., M.Kn.")))

    return "".join(paras)


def _document_xml() -> bytes:
    ns = " ".join(f'xmlns:{p}="{u}"' for p, u in _NS_DECLARATIONS)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        f'<w:document {ns} mc:Ignorable="{_MC_IGNORABLE}">'
        f"<w:body>{_build_body()}</w:body></w:document>"
    )
    return document.encode("utf-8")


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
    'package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
    'openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.extended-properties+xml"/>'
    "</Types>"
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/'
    '2006/relationships/metadata/core-properties" '
    'Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/extended-properties" '
    'Target="docProps/app.xml"/>'
    "</Relationships>"
)

_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
    '2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Bookman Old Style" w:hAnsi="Bookman Old Style" '
    'w:cs="Bookman Old Style"/><w:sz w:val="24"/><w:szCs w:val="24"/>'
    "</w:rPr></w:rPrDefault></w:docDefaults>"
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    '<w:name w:val="Normal"/></w:style>'
    "</w:styles>"
)

_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/'
    '2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/'
    '1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.'
    'w3.org/2001/XMLSchema-instance">'
    "<dc:creator>SKMHT Public Example</dc:creator>"
    "<cp:lastModifiedBy>SKMHT Public Example</cp:lastModifiedBy>"
    "<cp:revision>1</cp:revision>"
    '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z'
    "</dcterms:created>"
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z'
    "</dcterms:modified></cp:coreProperties>"
)

_APP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
    '2006/extended-properties"><Application>SKMHT Public Example</Application>'
    "<DocSecurity>0</DocSecurity><Company></Company>"
    "<AppVersion>16.0000</AppVersion></Properties>"
)


def build() -> bytes:
    """Rakit byte DOCX sintetis (deterministik)."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Stempel waktu tetap agar keluaran reproducible.
        def w(name: str, data: str) -> None:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)

        w("[Content_Types].xml", _CONTENT_TYPES)
        w("_rels/.rels", _ROOT_RELS)
        w("word/document.xml", _document_xml().decode("utf-8"))
        w("word/styles.xml", _STYLES)
        w("docProps/core.xml", _CORE)
        w("docProps/app.xml", _APP)
    return buf.getvalue()


def main() -> int:
    data = build()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as fh:
        fh.write(data)

    # Verifikasi cepat: seluruh marker wajib + pembersih harus ada.
    from app import docx_template
    ledger = docx_template.ledger_of(data)
    missing_required = [k for k in fields.REQUIRED_MARKER_KEYS
                        if k not in ledger]
    missing_removal = [k for k in fields.REMOVAL_MARKER_KEYS
                       if k not in ledger]
    print(f"ditulis: {OUT_PATH} ({len(data)} byte)")
    print(f"marker: {len(ledger)} unik, {sum(ledger.values())} token")
    if missing_required or missing_removal:
        print("GAGAL: marker wajib hilang:", missing_required, missing_removal)
        return 1
    print("OK: seluruh marker wajib + pembersih tersedia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
