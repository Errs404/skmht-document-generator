"""Mesin templating DOCX berbasis zip + XML (Standard Library saja).

Pendekatan:
- Paket DOCX diperlakukan sebagai arsip zip. Semua entri disalin apa adanya.
- Hanya ``word/document.xml`` yang diubah isinya.
- Penggantian dilakukan pada level <w:t> (teks run) dengan melacak posisi
  (offset) teks asli di seluruh node <w:t> sebuah paragraf. Kecocokan
  terpanjang dipilih dan diterapkan dari KANAN ke KIRI sehingga nilai yang
  baru disisipkan tidak pernah dipindai ulang. Node <w:t> yang tidak
  bersinggungan dengan penggantian, serta <w:tab/>, <w:br/>, dan
  <w:cr/> di dalam paragraf, dibiarkan utuh. Teks pengganti mewarisi gaya
  run dari node <w:t> pertama yang bersinggungan (tanpa meruntuhkan
  seluruh paragraf ke satu run).

- Deklarasi namespace asli root (termasuk yang hanya dirujuk lewat nilai
  atribut, mis. prefiks pada ``mc:Ignorable``) dipertahankan apa adanya
  karena tag root asli dikembalikan utuh setelah serialisasi.

Penting: berkas template TIDAK pernah ditimpa. Fungsi render hanya membaca.

Dua mode penggantian
--------------------
- ``render_docx`` (mode frasa, generik): mengganti pasangan frase teks apa pun
  pada ``document.xml``; dipakai mesin marker di bawah dan oleh pengujian unit
  mesin. Tidak dipakai jalur produksi secara langsung.
- ``render_template`` (mode produksi): mengganti **marker** ``{{key}}`` yang
  eksplisit pada template contoh (``templates/SKMHT.example.template.docx``).
  Mode ini tahan terhadap pemecahan token lintas run, mewajibkan seluruh marker
  wajib terisi (gagal-keras), dan memastikan tidak ada marker tak dikenal/sisa
  yang tertinggal pada dokumen hasil.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("w", W_NS)

#: Pola satu token marker ``{{key}}`` (tanpa kurung kurawal di dalamnya).
MARKER_RE = re.compile(r"\{\{([^{}]+)\}\}")

#: Nama berkas template produksi relatif terhadap folder aplikasi.
DEFAULT_TEMPLATE_RELPATH = "templates/SKMHT.example.template.docx"

#: Ukuran maksimum berkas template (kewajaran; mencegah berkas tak sengaja).
MAX_TEMPLATE_BYTES = 40 * 1024 * 1024



def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


class DocxTemplateError(Exception):
    pass


class MissingTemplateError(DocxTemplateError):
    """Template tidak ditemukan pada lokasi yang diharapkan."""


class TemplateAlteredError(DocxTemplateError):
    """Template ditemukan, tetapi strukturnya tidak seperti yang diharapkan."""


class MissingMarkerError(DocxTemplateError):
    """Ada marker wajib yang tidak terisi atau marker tak dikenal tersisa."""


class MarkerValueError(DocxTemplateError):
    """Ada nilai marker yang tidak lulus validasi (mis. ditolak intern)."""


def _escape_text(value: str) -> str:
    """Meng-escape karakter XML untuk teks isi.

    ElementTree menangani escaping saat serialize, jadi di sini cukup
    membuang karakter kontrol yang tidak sah di XML 1.0 (kecuali tab/LF/CR).
    """
    if value is None:
        return ""
    text = str(value)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


# ---------------------------------------------------------------------------
# Namespace: ekstraksi deklarasi asli + pemulihan prefix pada serialisasi
# ---------------------------------------------------------------------------

_DECL_RE = re.compile(
    rb'\sxmlns:([A-Za-z_][\w.\-]*)\s*=\s*"([^"]*)"')
_ROOT_RE = re.compile(rb'(?s)\s*(?P<decl><\?xml[^>]*\?>)?\s*(?P<root><[^>]+>)')


def _extract_root_declarations(document_xml: bytes):
    """Mengembalikan (xml_decl, root_open_tag, {prefix: uri}) dari berkas asli.

    Peta prefix mencakup deklarasi di SELURUH dokumen (termasuk yang
    dideklarasikan pada elemen anak, mis. ``xmlns:a`` pada gambar), sehingga
    serialisasi dapat memakai kembali prefix aslinya dan tidak menghasilkan
    prefix sintetis ``nsN``.
    """
    match = _ROOT_RE.match(document_xml)
    if not match:
        return b"", b"", {}
    xml_decl = match.group("decl") or b""
    root_tag = match.group("root")
    decls = {}
    # Deklarasi root dahulu (prioritas tertinggi untuk pemetaan URI->prefix).
    for prefix, uri in _DECL_RE.findall(root_tag):
        p = prefix.decode("ascii", "replace")
        u = uri.decode("utf-8", "replace")
        if p != "xml":
            decls.setdefault(p, u)
    # Deklarasi pada elemen anak (mis. prefiks drawing).
    try:
        for _event, (prefix, uri) in ET.iterparse(
                io.BytesIO(document_xml), events=("start-ns",)):
            if prefix and prefix != "xml":
                decls.setdefault(prefix, uri)
    except ET.ParseError:  # pragma: no cover - defensif
        pass
    return xml_decl, root_tag, decls


def _register_original_namespaces(decls) -> None:
    """Mendaftarkan prefix asli agar serialisasi memakai prefix yang sama.

    Entri lama pada peta namespace ElementTree (mis. prefix sintetis ``ns0``)
    yang memetakan URI sama tidak dapat dihapus lewat API publik; sisa itu
    diperbaiki pasca-serialisasi oleh ``_restore_prefixes``.
    """
    for prefix, uri in decls.items():
        if prefix in ("xml", "xmlns") or not prefix:
            continue
        try:
            ET.register_namespace(prefix, uri)
        except (ValueError, TypeError):
            # Prefix tidak valid untuk ElementTree; diabaikan (tetap utuh
            # karena tag root asli dikembalikan apa adanya).
            continue


def _restore_prefixes(serialized: bytes, decls) -> bytes:
    """Mengganti prefix sintetis ``nsN`` kembali ke prefix asli berdasarkan URI.

    ElementTree dapat memakai ``ns0``, ``ns1``, ... bila peta namespace-nya
    sudah kotor. Fungsi ini memetakan URI dari deklarasi sintetis pada root
    yang baru diserialisasi ke prefix asli, lalu mengganti seluruh
    kemunculan ``nsN:`` pada nama elemen/atribut.
    """
    uri_to_prefix = {uri: p for p, uri in decls.items()}
    if not uri_to_prefix:
        return serialized
    root_open = re.match(rb'(<[^>]+>)', serialized)
    if not root_open:
        return serialized
    fixups = {}
    for prefix, uri in _DECL_RE.findall(root_open.group(1)):
        p = prefix.decode("ascii", "replace")
        u = uri.decode("utf-8", "replace")
        if p.startswith("ns") and p[2:].isdigit() and u in uri_to_prefix:
            fixups[p] = uri_to_prefix[u]
    for synthetic, original in fixups.items():
        serialized = re.sub(
            rb"<" + synthetic.encode("ascii") + rb":",
            b"<" + original.encode("ascii") + b":",
            serialized)
        serialized = re.sub(
            rb"</" + synthetic.encode("ascii") + rb":",
            b"</" + original.encode("ascii") + b":",
            serialized)
        serialized = re.sub(
            rb"\s" + synthetic.encode("ascii") + rb":",
            b" " + original.encode("ascii") + b":",
            serialized)
    return serialized


def _merge_root_declarations(serialized_root: bytes, original_root: bytes) -> bytes:
    """Memastikan tag root memuat SEMUA deklarasi asli tanpa duplikat.

    Tag root hasil serialisasi (memuat deklarasi yang dipakai nama elemen)
    digabung dengan deklarasi asli (memuat prefiks yang hanya dirujuk nilai
    atribut, mis. ``mc:Ignorable``). Deklarasi asli dipakai sebagai basis,
    lalu deklarasi baru yang belum ada ditambahkan.
    """
    def decls_of(tag: bytes):
        return {
            p.decode("ascii", "replace"): u.decode("utf-8", "replace")
            for p, u in _DECL_RE.findall(tag)
        }

    orig_decls = decls_of(original_root)
    ser_decls = decls_of(serialized_root)
    extra = "".join(
        f' xmlns:{p}="{u}"' for p, u in ser_decls.items()
        if p not in orig_decls and p != "xml"
    )
    if not extra:
        return original_root
    # Sisipkan deklarasi tambahan sebelum '>' penutup (setelah '<name').
    return original_root[:-1] + extra.encode("utf-8") + b">"


# ---------------------------------------------------------------------------
# Manipulasi teks run
# ---------------------------------------------------------------------------

def _set_run_text(run_el: ET.Element, value: str) -> None:
    """Menetapkan teks sebuah <w:r> dengan menghormati xml:space."""
    value = _escape_text(value)
    texts = run_el.findall(_w("t"))
    if not texts:
        t = ET.SubElement(run_el, _w("t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = value
        return
    keep = texts[0]
    for extra in texts[1:]:
        run_el.remove(extra)
    keep.set(f"{{{XML_NS}}}space", "preserve")
    keep.text = value


def _text_nodes_in_order(par_el: ET.Element, seen=None):
    """Semua node <w:t> paragraf dalam urutan dokumen.

    Mengembalikan daftar (node, offset_awal, offset_akhir). Bila ``seen``
    diberikan (himpunan id node), node yang sudah diproses paragraf lain
    dilewati sehingga paragraf bersarang (mis. di dalam text box) tidak
    dihitung ganda.
    """
    nodes = []
    offset = 0
    for node in par_el.iter(_w("t")):
        if seen is not None:
            if id(node) in seen:
                continue
            seen.add(id(node))
        text = node.text or ""
        start = offset
        offset += len(text)
        nodes.append((node, start, offset))
    return nodes


def _apply_replacements_to_paragraph(par_el: ET.Element, pairs, seen=None) -> int:
    """Menerapkan penggantian pada satu paragraf tanpa meruntuhkannya.

    Bekerja di atas offset teks asli seluruh node <w:t>. Kecocokan
    terpanjang diutamakan dan diterapkan dari kanan ke kiri, sehingga teks
    yang baru disisipkan tidak pernah dipindai ulang. Hanya node yang
    bersinggungan dengan penggantian yang diubah; node lain (termasuk
    <w:tab/>, <w:br/>, dan run berformat lain) dibiarkan utuh.

    Mengembalikan jumlah penggantian yang dilakukan.
    """
    nodes = _text_nodes_in_order(par_el, seen)
    if not nodes:
        return 0

    full = "".join((node.text or "") for (node, _s, _e) in nodes)
    if not full:
        return 0

    # Kumpulkan kecocokan tak-tumpang-tindih pada teks ASLI, terpanjang dulu.
    matches = []          # list of (start, end, replacement)
    occupied = []         # rentang yang sudah terpakai
    for find, repl in pairs:
        if not find:
            continue
        pos = full.find(find)
        while pos != -1:
            end = pos + len(find)
            if not any(pos < oe and os_ < end for (os_, oe) in occupied):
                matches.append((pos, end, _escape_text(repl)))
                occupied.append((pos, end))
            pos = full.find(find, pos + 1)

    if not matches:
        return 0

    # Terapkan dari kanan ke kiri agar offset kiri tidak bergeser. Offset
    # node dihitung ulang dari teks terkini tiap kali; karena setiap
    # suntingan selalu berada di posisi >= akhir kecocokan sekarang, semua
    # indeks < end tetap valid pada teks terkini.
    matches.sort(key=lambda m: m[0], reverse=True)
    count = 0
    for start, end, repl in matches:
        current = _nodes_with_offsets(nodes)
        if _splice_paragraph(current, start, end, repl):
            count += 1
    return count


def _nodes_with_offsets(nodes):
    """Menghitung ulang offset teks terkini untuk daftar node yang sama."""
    result = []
    offset = 0
    for (node, _s, _e) in nodes:
        text = node.text or ""
        result.append((node, offset, offset + len(text)))
        offset += len(text)
    return result


def _splice_paragraph(nodes, start: int, end: int, repl: str) -> bool:
    """Mengganti rentang [start, end) pada teks gabungan dengan ``repl``.

    Teks pengganti mewarisi gaya run dari node pertama yang bersinggungan
    (yakni node yang memuat karakter pertama rentang). Node yang bersinggungan
    sebagian mempertahankan sisa teks di luar rentang; node yang seluruhnya
    berada di dalam rentang dikosongkan (tetap ada agar struktur run/rPr
    tak berubah). Mengembalikan True bila ada node yang diubah.
    """
    first = True
    changed = False
    for (node, s, e) in nodes:
        if e <= start or s >= end:
            continue  # tidak bersinggungan
        text = node.text or ""
        left = text[: max(0, start - s)]
        right = text[max(0, end - s):]
        if first:
            _set_node_text(node, left + repl + right)
            first = False
        else:
            _set_node_text(node, left + right)
        changed = True
    return changed


def _set_node_text(node: ET.Element, value: str) -> None:
    node.text = _escape_text(value)
    node.set(f"{{{XML_NS}}}space", "preserve")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_docx(template_bytes: bytes, replacements) -> bytes:
    """Menghasilkan DOCX baru dari byte template.

    ``replacements`` adalah iterable pasangan (teks_lama, teks_baru).
    Semua entri zip selain document.xml disalin identik.
    """
    if isinstance(template_bytes, bytearray):
        template_bytes = bytes(template_bytes)

    try:
        src = zipfile.ZipFile(io.BytesIO(template_bytes), "r")
    except zipfile.BadZipFile as exc:  # pragma: no cover - defensif
        raise DocxTemplateError("Berkas template DOCX tidak valid.") from exc

    out = io.BytesIO()
    with src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = _render_document_xml(data, replacements)
            # Pertahankan metadata waktu/kompresi sedapat mungkin.
            new_item = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            new_item.compress_type = (
                zipfile.ZIP_DEFLATED
                if item.compress_type == zipfile.ZIP_DEFLATED
                else item.compress_type
            )
            new_item.external_attr = item.external_attr
            new_item.internal_attr = item.internal_attr
            new_item.create_system = item.create_system
            dst.writestr(new_item, data)
    return out.getvalue()


def _render_document_xml(document_xml: bytes, replacements) -> bytes:
    pairs = [(f, r) for (f, r) in replacements if f]
    # Urutkan pencarian terpanjang dulu agar frasa panjang tidak terpotong
    # oleh penggantian pendek.
    pairs.sort(key=lambda fr: len(fr[0]), reverse=True)

    xml_decl, original_root, decls = _extract_root_declarations(document_xml)
    _register_original_namespaces(decls)

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:  # pragma: no cover - defensif
        raise DocxTemplateError("document.xml tidak dapat diparsing.") from exc

    seen: set = set()
    for par in root.iter(_w("p")):
        _apply_replacements_to_paragraph(par, pairs, seen)

    body = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    body = _restore_prefixes(body, decls)

    # Kembalikan tag root asli (memuat semua deklarasi & mc:Ignorable),
    # tambahkan deklarasi yang benar-benar diperlukan bila belum ada.
    if original_root:
        ser_root = re.match(rb'(<[^>]+>)', body)
        if ser_root:
            merged = _merge_root_declarations(ser_root.group(1), original_root)
            body = merged + body[ser_root.end():]

    decl = xml_decl or b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    return decl + b"\r\n" + body


# ---------------------------------------------------------------------------
# Mesin marker (produksi): {{key}} tahan pemecahan lintas run
# ---------------------------------------------------------------------------

def _paragraph_nodes(par_el: ET.Element, seen=None):
    """Node ``<w:t>`` paragraf dalam urutan dokumen (tanpa duplikat bersarang)."""
    nodes = []
    for node in par_el.iter(_w("t")):
        if seen is not None:
            if id(node) in seen:
                continue
            seen.add(id(node))
        nodes.append(node)
    return nodes


def _offsets(nodes):
    out = []
    off = 0
    for node in nodes:
        text = node.text or ""
        out.append((node, off, off + len(text)))
        off += len(text)
    return out


def _substitute_markers_in_paragraph(par_el: ET.Element, values: dict,
                                     seen=None) -> int:
    """Ganti seluruh marker pada **satu** paragraf; mengembalikan jumlah ganti.

    Marker yang ditolak validasi (nilai ``None``) sengaja TIDAK diganti agar
    token aslinya tetap ada dan terdeteksi sebagai marker tak terisi.
    """
    nodes = _paragraph_nodes(par_el, seen)
    if not nodes:
        return 0
    full = "".join(node.text or "" for node in nodes)
    if "{{" not in full:
        return 0

    matches = []
    for m in MARKER_RE.finditer(full):
        key = m.group(1)
        if key not in values:
            continue  # marker tak dikenal; biarkan untuk deteksi validasi
        value = values[key]
        if value is None:
            continue  # sengaja gagal-keras di tahap verifikasi
        matches.append((m.start(), m.end(), _escape_text(value)))

    if not matches:
        return 0
    matches.sort(key=lambda t: t[0], reverse=True)
    count = 0
    for start, end, repl in matches:
        _splice_paragraph(_offsets(nodes), start, end, repl)
        count += 1
    return count


def render_template(document_xml: bytes, values: dict) -> bytes:
    """Mengganti marker ``{{key}}`` pada satu ``document.xml``.

    ``values`` memetakan nama key -> teks pengganti. Nilai ``None`` dilewati
    (marker tetap ada) sehingga markup tidak pernah terisi paksa.

    Tag root asli dikembalikan utuh (termasuk deklarasi prefiks yang hanya
    dirujuk lewat nilai atribut, mis. ``mc:Ignorable``) agar tidak muncul
    prefiks sintetis ``nsN``.
    """
    xml_decl, original_root, decls = _extract_root_declarations(document_xml)
    _register_original_namespaces(decls)

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:  # pragma: no cover - defensif
        raise TemplateAlteredError(
            "document.xml pada template tidak dapat diparsing.") from exc

    seen: set = set()
    for par in root.iter(_w("p")):
        _substitute_markers_in_paragraph(par, values, seen)

    body = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    body = _restore_prefixes(body, decls)

    if original_root:
        ser_root = re.match(rb'(<[^>]+>)', body)
        if ser_root:
            merged = _merge_root_declarations(ser_root.group(1), original_root)
            body = merged + body[ser_root.end():]

    decl = xml_decl or b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    return decl + b"\r\n" + body


def _template_document_xml(template_bytes: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(template_bytes)) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                raise TemplateAlteredError(
                    "Template tidak memuat word/document.xml.")
            return z.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise TemplateAlteredError("Berkas template DOCX tidak valid.") from exc


def ledger_of(template_bytes: bytes) -> dict:
    """Inventaris marker pada template: ``{key: jumlah}`` (berdasarkan teks run).

    Pencatatan dilakukan pada teks gabungan tiap paragraf sehingga marker yang
    terpecah lintas run tetap terhitung satu.
    """
    document_xml = _template_document_xml(template_bytes)
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise TemplateAlteredError(
            "document.xml pada template tidak dapat diparsing.") from exc
    ledger: dict[str, int] = {}
    seen: set = set()
    for par in root.iter(_w("p")):
        text = "".join(node.text or ""
                       for node in _paragraph_nodes(par, seen))
        for m in MARKER_RE.finditer(text):
            key = m.group(1)
            ledger[key] = ledger.get(key, 0) + 1
    return ledger


def render_docx_from_template(template_bytes: bytes, values: dict,
                              required_keys=(),
                              removal_keys=()) -> bytes:
    """Render penuh dari byte template khusus berbasis marker.

    Gagal-keras (``MissingMarkerError``) bila:
    - ada key pada ``required_keys`` yang tidak terpetakan atau nilainya kosong;
    - ada key pada ``removal_keys`` yang nilainya tidak kosong;
    - setelah penggantian masih ada token ``{{...}}`` yang tersisa.

    Seluruh entri zip selain ``word/document.xml`` disalin identik.
    """
    if isinstance(template_bytes, (bytearray, memoryview)):
        template_bytes = bytes(template_bytes)
    if not template_bytes:
        raise MissingTemplateError("Berkas template kosong.")
    if len(template_bytes) > MAX_TEMPLATE_BYTES:
        raise TemplateAlteredError("Ukuran berkas template tidak wajar.")

    ledger = ledger_of(template_bytes)

    missing = [key for key in required_keys
               if not _clean_value(values.get(key))]
    if missing:
        raise MissingMarkerError(
            "Marker wajib belum terisi: " + ", ".join(sorted(missing)))
    bad_removal = [key for key in removal_keys if _clean_value(values.get(key))]
    if bad_removal:
        raise MissingMarkerError(
            "Marker pembersih harus kosong: " + ", ".join(sorted(bad_removal)))

    document_xml = _template_document_xml(template_bytes)
    rendered_doc = render_template(document_xml, values)

    rendered_root = ET.fromstring(rendered_doc)
    leftover = []
    seen: set = set()
    for par in rendered_root.iter(_w("p")):
        text = "".join(node.text or ""
                       for node in _paragraph_nodes(par, seen))
        for m in MARKER_RE.finditer(text):
            leftover.append(m.group(1))
    if leftover:
        raise MissingMarkerError(
            "Marker tak dikenal/tak terisi tersisa pada dokumen: "
            + ", ".join(sorted(set(leftover))))

    try:
        src = zipfile.ZipFile(io.BytesIO(template_bytes), "r")
    except zipfile.BadZipFile as exc:  # pragma: no cover - sudah dicek
        raise TemplateAlteredError("Berkas template DOCX tidak valid.") from exc

    out = io.BytesIO()
    with src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = rendered_doc
            new_item = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            new_item.compress_type = (
                zipfile.ZIP_DEFLATED
                if item.compress_type == zipfile.ZIP_DEFLATED
                else item.compress_type
            )
            new_item.external_attr = item.external_attr
            new_item.internal_attr = item.internal_attr
            new_item.create_system = item.create_system
            dst.writestr(new_item, data)
    return out.getvalue()


def _clean_value(value) -> str:
    if value is None:
        return ""
    return str(value).strip()
