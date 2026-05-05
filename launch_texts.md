# Textos de lançamento — PDFApps

## Quando publicar

| Plataforma | Dia | Hora (PT) | Nota |
|---|---|---|---|
| Product Hunt | Terça | 08:00 | Ranking reseta à meia-noite PST — publicar cedo dá mais horas para upvotes |
| Hacker News | Terça | 14:00 | Mesmo dia, à tarde — audiência diferente |
| Reddit (r/opensource) | Quarta | 14:00 | Dia seguinte — dá tempo para responder aos comentários do PH e HN |
| Reddit (r/Python) | Quinta | 14:00 | Espaçar para não saturar e ter tempo de responder |

Responder rápido aos comentários faz o post subir. Reservar 2-3 horas após cada publicação para interagir.

---

## Reddit — r/opensource (ou r/linux, r/selfhosted)

**Titulo:** I got tired of uploading my PDFs to random websites, so I built my own editor

Every time I needed to merge a PDF or remove a page, I ended up on some sketchy website that wanted me to upload my files to their servers. I never liked that, especially with contracts, IDs, or anything work-related.

So I started building PDFApps. It's a desktop app that runs completely offline. No cloud, no accounts, no "premium tier", just the tools I actually needed.

Right now it has 15 tools (split, merge, rotate, compress, encrypt, OCR, and more), a visual editor where you can add text, images, signatures and highlights directly on the PDF, and an integrated viewer with tabs, search, bookmarks, night mode and presentation mode.

It works on Windows, macOS and Linux. I ship installers for all three, plus Snap, AUR, Copr, AppImage and winget.

A few things I'm happy with:

- You can chain tools without saving in between (rotate a PDF, then compress it, then add page numbers — save once at the end)
- The editor handles large PDFs without freezing (pages render in background as you scroll)
- 8 languages out of the box
- Dark and light theme

Built with Python, PySide6 and pypdf. MIT licensed.

I'd love to hear what you think, and if there are tools or features you'd want to see.

GitHub: https://github.com/nelsonduarte/PDFApps
Website: https://pdf-apps.com
Download: https://github.com/nelsonduarte/PDFApps/releases/latest

---

## Hacker News — Show HN

**Titulo:** Show HN: PDFApps – Offline PDF editor with 15 tools (Win/Mac/Linux, open source)

**Texto:**

I built PDFApps because I didn't want to upload my documents to online PDF tools.

It's a desktop app with 15 tools (split, merge, compress, encrypt, OCR, convert, etc.), a visual editor (text, images, signatures, redactions, highlights) and a full PDF viewer with tabs, search and bookmarks.

Everything runs locally. No internet, no accounts, no telemetry.

A few technical details for those interested:

- Python + PySide6 (Qt 6) for the GUI
- pypdf for PDF manipulation, PyMuPDF for rendering
- Pages render lazily in background threads — large PDFs open instantly
- Pipeline mode: chain multiple tools before saving (works via temp files)
- PyInstaller for packaging, CI/CD builds for all platforms on every tag

MIT licensed. Installers for Windows, macOS, Linux (also on Snap, AUR, Copr, winget).

https://github.com/nelsonduarte/PDFApps

---

## Product Hunt

**Tagline:** Free offline PDF editor — 15 tools, no cloud, no subscriptions

**Description:**

PDFApps is a desktop PDF editor that runs entirely on your computer. No uploads, no accounts, no subscriptions.

It includes 15 tools — from the basics like split, merge and compress to more advanced ones like OCR, watermarks and page numbering. There's also a visual editor where you can add text, images, signatures, highlights and redactions directly on the page.

The viewer supports tabs, bookmarks, text search, night reading mode and a presentation mode for showing PDFs fullscreen.

I built it because the existing options were either paid, required an internet connection, or wanted me to upload sensitive documents to third-party servers. I wanted something that just works offline and doesn't ask for anything.

Available for Windows, macOS and Linux. Open source, MIT licensed.

---

## Reddit — r/commandline ou r/Python

**Titulo:** Built an offline PDF editor in Python — 15 tools, PySide6, lazy rendering, pipeline mode

I've been working on a desktop PDF editor called PDFApps. Thought some of you might find it useful or interesting from a technical perspective.

Stack: Python 3.14, PySide6, pypdf, PyMuPDF, Tesseract for OCR.

Some things that were fun to figure out:

- Lazy page rendering: the viewer and editor only render pages that are visible on screen, in background threads via QThreadPool. Big PDFs open in ~60ms.
- Pipeline mode: when you apply a tool (say, rotate), the result goes to a temp file and reloads in the viewer. You can then apply another tool on top. Ctrl+S saves the final result. No intermediate files cluttering your desktop.
- Continuous scroll canvas: all pages are laid out vertically like a web page, with text selection across pages.
- 3-pass compression: tries Ghostscript, PyMuPDF and pikepdf in sequence, keeps the smallest result.

15 tools total, visual editor with 10 modes (redact, text, image, highlight, signature, freehand drawing, etc.), 8 languages, dark/light theme.

MIT licensed, builds for Windows/macOS/Linux via GitHub Actions.

https://github.com/nelsonduarte/PDFApps

Would appreciate any feedback, especially on the code structure — it's a solo project and I don't always know if I'm doing things the "right" way.
