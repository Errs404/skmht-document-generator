#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probe manual: buktikan model AI yang dikonfigurasi menerima masukan gambar.

Jalankan dari folder aplikasi, setelah menyetel kunci (bila router
memerlukannya):

    set "SKMHT_AI_API_KEY=<kunci-anda>"
    python tools/probe_ai_vision.py
    :: model lain:
    python tools/probe_ai_vision.py example-vision-model-alt

Skrip ini:
- membuat GAMBAR SINTETIS kecil (token uji acak, BUKAN KTP/data pribadi nyata);
- mengirim SATU permintaan chat-completions dengan ``image_url`` data URL;
- memastikan balasan memuat karakter token (bukan hanya HTTP 200);
- TIDAK menuliskan kunci, payload, maupun isi balasan ke disk.

Keluar dengan kode 0 bila gambar diterima, 1 bila tidak.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ai_ocr  # noqa: E402


def main() -> int:
    models = sys.argv[1:] or [ai_ocr.model_name()]
    rc = 0
    for model in models:
        result = ai_ocr.probe_vision(model=model)
        print("=" * 64)
        print(f"model      : {result['model']}")
        print(f"endpoint   : {result['endpoint']}")
        print(f"gambar byte: {result['image_bytes']}")
        print(f"HTTP       : {result['status']}")
        print(f"cocok token: {result['matched']}")
        print(f"ok         : {result['ok']}  ({result['detail']})")
        if not result["ok"]:
            rc = 1
    print("=" * 64)
    if rc == 0:
        print("KESIMPULAN: model menerima masukan gambar (terbukti).")
    else:
        print("KESIMPULAN: TIDAK terbukti. Periksa kunci/model/endpoint.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
