# SKMHT Document Generator (Sanitized Example)

Local Python web application that generates a draft SKMHT `.docx` from a
marker-based example template. This public edition contains **synthetic names,
identifiers, addresses, institutional details, and document metadata only**.

> **Important:** This is a software demonstration, not legal advice and not a
> legally ready instrument. The bundled template is synthetic. Replace and
> review every clause and identity with qualified Indonesian legal/notarial
> professionals before any real use.

## Run locally

Requires Python 3.10+.

```console
python -m pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:8756/>. The server binds to localhost only.

Windows users may run `start.bat` (optionally `start.bat 9000`).

## Template

The application uses `templates/SKMHT.example.template.docx`. It is a sanitized
example containing `{{marker}}` placeholders and demonstrative clause text only
(explicitly labelled as a demo, **not a legally ready instrument**). No source
client document is included. The template is generated from a blank document by
`tools/build_synthetic_template.py`, so it can be rebuilt reproducibly; it must
contain exactly the marker schema the app requires. To use another template,
create a separate marker-based DOCX and update `TEMPLATE_PATH`; do not commit
real client records, scans, drafts, or signed documents.

## Optional OCR

Local KTP OCR requires Pillow (installed above) and a separately installed
Tesseract executable. Online AI OCR is disabled unless explicitly configured
through environment variables. `SKMHT_AI_BASE_URL` defaults to localhost;
`SKMHT_AI_API_KEY` is optional and must never be committed.

## Tests

```console
python -m unittest discover -s tests -v
```

All tests pass using only the standard library (one optional live-AI probe test
is skipped unless `SKMHT_AI_API_KEY` is set). Tests and smoke tools use clearly
synthetic fixtures. No real NIK, address, person, notary, witness, lender, API
key, or private endpoint is required.

## Privacy and limitations

- The app does not provide authentication and is intended for one-user local use.
- Draft JSON files are unencrypted; users are responsible for protecting them.
- OCR/AI output is untrusted and must be checked manually.
- Generated documents are drafts and must be reviewed in Word and by qualified
  professionals.
- Original/private DOCX, legacy `.doc`, photos, drafts, and generated documents
  are intentionally excluded from this repository.
