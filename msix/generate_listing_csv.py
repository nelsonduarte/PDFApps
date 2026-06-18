#!/usr/bin/env python3
"""Generate complete listingData CSV for Microsoft Partner Center submission.

Output: ../listingData-9P70QGR8BSMZ-filled.csv (UTF-8 with BOM)
Importable via Partner Center > Listagens na Store > Importar listagens.
"""
import csv
import os

LANGS = ['en-us', 'pt-pt', 'es-es', 'fr-fr', 'de-de', 'zh-cn', 'it-it', 'nl-nl']

# ============================================================
# DESCRIPTIONS
# ============================================================
DESCRIPTION = {}

DESCRIPTION['en-us'] = '''PDFApps is a fast, offline, free PDF editor with everything you need in one app,  no subscriptions, no accounts, no cloud uploads.

\U0001F6E0️  15 BUILT-IN TOOLS
• Split, merge, rotate, extract, reorder pages
• Compress (powered by Ghostscript)
• OCR (Tesseract, 5 language packs)
• Convert to/from DOCX, PPTX, XLSX, HTML, EPUB, TXT, images
• Watermark, page numbers, N-up printing
• Encrypt with AES-256, decrypt
• Visual editor: redact, add text, images, signatures, highlights, notes
• Metadata viewer

\U0001F3AF WORKFLOW
• Continuous-scroll viewer with night mode
• Tabbed viewing — open multiple PDFs at once
• Presentation mode (F5) and fullscreen (F11)
• Drag and drop, multi-select PDF open
• Pipeline mode: chain tools before saving

\U0001F30D LANGUAGES
English, Portuguese, Spanish, French, German, Chinese, Italian, Dutch.

\U0001F512 PRIVACY
100% offline. No subscriptions, no cloud uploads, no telemetry, no account required. Your PDFs never leave your computer.

'''

DESCRIPTION['pt-pt'] = '''PDFApps é um editor de PDF rápido, gratuito e 100% offline para Windows. Reúne 15 ferramentas essenciais numa só aplicação, sem subscrições, sem contas e sem enviar os seus ficheiros para a cloud — tudo é processado localmente no seu computador.

Construído para quem valoriza privacidade, desempenho e simplicidade. Código aberto sob licença MIT.

══ AS 15 FERRAMENTAS ══

• Juntar PDFs — combine vários ficheiros num só, com pré-visualização e reordenação por arrastar.
• Dividir PDF — extraia páginas específicas, intervalos, ou divida por marcador.
• Comprimir PDF — reduza o tamanho dos ficheiros mantendo a qualidade (Ghostscript integrado).
• Converter — PDF para Word, Excel, PowerPoint, HTML, TXT, JPG, PNG, e vice-versa.
• OCR (reconhecimento de texto) — torne PDFs digitalizados pesquisáveis em mais de 100 idiomas.
• Reordenar páginas — mude a ordem das páginas com drag-and-drop.
• Rodar páginas — corrija orientação de páginas individuais ou de todo o documento.
• Marca de água — adicione texto ou imagem em todas as páginas, com controlo de transparência e ângulo.
• Numeração de páginas — insira números com formato e posição personalizáveis.
• N-up (várias páginas por folha) — coloque 2, 4, 6 ou mais páginas numa só folha A4.
• Encriptar — proteja PDFs com palavra-passe (AES-256).
• Desencriptar — remova palavras-passe de PDFs que possui.
• Eliminar páginas — apague páginas individuais ou intervalos.
• Extrair imagens — extraia todas as imagens embutidas num PDF.
• Importar — converta JPG, PNG, DOCX, XLSX, PPTX, TXT, HTML e EPUB para PDF.

══ PORQUE ESCOLHER PDFAPPS ══

✓ 100% Offline — os seus ficheiros nunca saem do computador.
✓ Sem subscrição — gratuito hoje, gratuito amanhã, sem upsells.
✓ Sem conta — não precisa de email, palavra-passe ou cartão de crédito.
✓ Sem publicidade — interface limpa, sem distracções.
✓ Código aberto — auditável no GitHub sob licença MIT.
✓ Rápido — arranca em segundos e processa PDFs grandes sem travar.
✓ 8 idiomas — Português, Inglês, Espanhol, Francês, Alemão, Italiano, Holandês e Chinês.
✓ Modo claro e escuro — escolhe automaticamente conforme o tema do Windows.

══ PRIVACIDADE ══

A PDFApps é o oposto das ferramentas online de PDF: nada do que abre é carregado para servidores, nada é registado, nada é partilhado. A única ligação à Internet é a verificação opcional de novas versões via GitHub Releases. Pode desligá-la nas definições.

══ IDEAL PARA ══

• Profissionais que lidam com documentos confidenciais (advogados, médicos, contabilistas).
• Estudantes que precisam de juntar, dividir ou anotar materiais de estudo.
• Empresas que querem evitar serviços cloud sem compliance GDPR.
• Qualquer pessoa cansada de subscrições caras para tarefas simples.

Descarregue, instale e comece a editar PDFs em menos de um minuto. Sem registo, sem truques, sem limites.
'''

DESCRIPTION['es-es'] = '''PDFApps es un editor de PDF rápido, offline y gratuito con todo lo que necesita en una sola aplicación, sin suscripciones, sin cuentas y sin subidas a la nube.

\U0001F6E0️  15 HERRAMIENTAS INTEGRADAS
• Dividir, unir, rotar, extraer, reordenar páginas
• Comprimir (con Ghostscript)
• OCR (Tesseract, 5 paquetes de idiomas)
• Convertir desde/hacia DOCX, PPTX, XLSX, HTML, EPUB, TXT, imágenes
• Marca de agua, números de página, impresión N-up
• Cifrar con AES-256, descifrar
• Editor visual: redactar, añadir texto, imágenes, firmas, resaltados, notas
• Visor de metadatos

\U0001F3AF FLUJO DE TRABAJO
• Visor de desplazamiento continuo con modo nocturno
• Vista por pestañas — abra varios PDF a la vez
• Modo presentación (F5) y pantalla completa (F11)
• Arrastrar y soltar, selección múltiple al abrir
• Modo pipeline: encadene herramientas antes de guardar

\U0001F30D IDIOMAS
Inglés, Portugués, Español, Francés, Alemán, Chino, Italiano, Holandés.

\U0001F512 PRIVACIDAD
100% sin conexión. Sin suscripciones, sin nube, sin telemetría, sin cuenta. Sus PDF nunca salen de su ordenador.

'''

DESCRIPTION['fr-fr'] = '''PDFApps est un éditeur PDF rapide, hors ligne et gratuit qui contient tout ce dont vous avez besoin dans une seule application — pas d\'abonnements, pas de comptes, pas d\'envois vers le cloud.

\U0001F6E0️  15 OUTILS INTÉGRÉS
• Diviser, fusionner, faire pivoter, extraire, réorganiser les pages
• Compresser (avec Ghostscript)
• OCR (Tesseract, 5 packs de langues)
• Convertir depuis/vers DOCX, PPTX, XLSX, HTML, EPUB, TXT, images
• Filigrane, numérotation des pages, impression N-up
• Chiffrer avec AES-256, déchiffrer
• Éditeur visuel : caviarder, ajouter du texte, images, signatures, surlignages, notes
• Visualiseur de métadonnées

\U0001F3AF FLUX DE TRAVAIL
• Visualiseur à défilement continu avec mode nuit
• Vue par onglets — ouvrez plusieurs PDF à la fois
• Mode présentation (F5) et plein écran (F11)
• Glisser-déposer, ouverture multi-sélection
• Mode pipeline : enchaînez les outils avant d\'enregistrer

\U0001F30D LANGUES
Anglais, Portugais, Espagnol, Français, Allemand, Chinois, Italien, Néerlandais.

\U0001F512 CONFIDENTIALITÉ
100% hors ligne. Pas d\'abonnement, pas de cloud, pas de télémétrie, pas de compte requis. Vos PDF ne quittent jamais votre ordinateur.

'''

DESCRIPTION['de-de'] = '''PDFApps ist ein schneller, kostenloser Offline-PDF-Editor mit allem, was Sie brauchen, in einer App — keine Abonnements, keine Konten, keine Cloud-Uploads.

\U0001F6E0️  15 INTEGRIERTE WERKZEUGE
• Seiten teilen, zusammenführen, drehen, extrahieren, neu anordnen
• Komprimieren (mit Ghostscript)
• OCR (Tesseract, 5 Sprachpakete)
• Konvertieren von/zu DOCX, PPTX, XLSX, HTML, EPUB, TXT, Bildern
• Wasserzeichen, Seitenzahlen, N-up-Druck
• Mit AES-256 verschlüsseln, entschlüsseln
• Visueller Editor: schwärzen, Text, Bilder, Signaturen, Hervorhebungen, Notizen hinzufügen
• Metadaten-Anzeige

\U0001F3AF WORKFLOW
• Endlos-Scroll-Viewer mit Nachtmodus
• Tab-Ansicht — mehrere PDFs gleichzeitig öffnen
• Präsentationsmodus (F5) und Vollbild (F11)
• Drag-and-Drop, Mehrfachauswahl beim Öffnen
• Pipeline-Modus: Werkzeuge vor dem Speichern verketten

\U0001F30D SPRACHEN
Englisch, Portugiesisch, Spanisch, Französisch, Deutsch, Chinesisch, Italienisch, Niederländisch.

\U0001F512 DATENSCHUTZ
100% offline. Keine Abonnements, keine Cloud-Uploads, keine Telemetrie, kein Konto erforderlich. Ihre PDFs verlassen niemals Ihren Computer.

'''

DESCRIPTION['zh-cn'] = '''PDFApps 是一款快速、离线、免费的 PDF 编辑器，一个应用包含您需要的一切——无需订阅、无需账号、无需上传到云端。

\U0001F6E0️  15 种内置工具
• 拆分、合并、旋转、提取、重排页面
• 压缩（基于 Ghostscript）
• OCR（Tesseract，5 个语言包）
• 与 DOCX、PPTX、XLSX、HTML、EPUB、TXT、图像互转
• 水印、页码、多页合一打印
• AES-256 加密、解密
• 可视化编辑器：涂黑、添加文本、图像、签名、高亮、注释
• 元数据查看器

\U0001F3AF 工作流
• 连续滚动查看器，支持夜间模式
• 多标签查看——同时打开多个 PDF
• 演示模式 (F5) 和全屏 (F11)
• 拖放、多选打开
• 管道模式：保存前串联多个工具

\U0001F30D 语言
英语、葡萄牙语、西班牙语、法语、德语、中文、意大利语、荷兰语。

\U0001F512 隐私
100% 离线。无订阅，无云上传，无遥测，无需账号。您的 PDF 永远不离开您的电脑。

'''

DESCRIPTION['it-it'] = '''PDFApps è un editor PDF veloce, offline e gratuito con tutto ciò che ti serve in un\'unica app — niente abbonamenti, niente account, niente upload sul cloud.

\U0001F6E0️  15 STRUMENTI INTEGRATI
• Dividi, unisci, ruota, estrai, riordina pagine
• Comprimi (con Ghostscript)
• OCR (Tesseract, 5 pacchetti lingua)
• Conversione da/verso DOCX, PPTX, XLSX, HTML, EPUB, TXT, immagini
• Filigrana, numerazione pagine, stampa N-up
• Cifra con AES-256, decifra
• Editor visivo: oscura, aggiungi testo, immagini, firme, evidenziazioni, note
• Visualizzatore metadati

\U0001F3AF WORKFLOW
• Visualizzatore a scorrimento continuo con modalità notte
• Vista a schede — apri più PDF contemporaneamente
• Modalità presentazione (F5) e schermo intero (F11)
• Trascina e rilascia, apertura multi-selezione
• Modalità pipeline: concatena strumenti prima di salvare

\U0001F30D LINGUE
Inglese, Portoghese, Spagnolo, Francese, Tedesco, Cinese, Italiano, Olandese.

\U0001F512 PRIVACY
100% offline. Niente abbonamenti, niente cloud, niente telemetria, nessun account richiesto. I tuoi PDF non lasciano mai il computer.

'''

DESCRIPTION['nl-nl'] = '''PDFApps is een snelle, offline en gratis PDF-editor met alles wat u nodig heeft in één app — geen abonnementen, geen accounts, geen cloud-uploads.

\U0001F6E0️  15 INGEBOUWDE TOOLS
• Splitsen, samenvoegen, roteren, extraheren, pagina\'s herordenen
• Comprimeren (met Ghostscript)
• OCR (Tesseract, 5 taalpakketten)
• Conversie van/naar DOCX, PPTX, XLSX, HTML, EPUB, TXT, afbeeldingen
• Watermerk, paginanummers, N-up afdrukken
• Versleutelen met AES-256, ontsleutelen
• Visuele editor: redigeren, tekst, afbeeldingen, handtekeningen, markeringen, notities toevoegen
• Metadata-viewer

\U0001F3AF WORKFLOW
• Doorlopende-scroll viewer met nachtmodus
• Tab-weergave — meerdere PDF\'s tegelijk openen
• Presentatiemodus (F5) en volledig scherm (F11)
• Slepen en neerzetten, multi-selectie bij openen
• Pipeline-modus: tools aaneenrijgen vóór opslaan

\U0001F30D TALEN
Engels, Portugees, Spaans, Frans, Duits, Chinees, Italiaans, Nederlands.

\U0001F512 PRIVACY
100% offline. Geen abonnementen, geen cloud-uploads, geen telemetrie, geen account nodig. Uw PDF\'s verlaten nooit uw computer.

'''

# ============================================================
# RELEASE NOTES
# ============================================================
RELEASE_NOTES = {}
RELEASE_NOTES['en-us'] = ''  # User left empty
RELEASE_NOTES['pt-pt'] = '''Versão 1.13.9 — Melhorias de segurança e instalador

• Auditoria de segurança completa: validação SHA-256 nos updates, escrita atómica de ficheiros de configuração, e limites mais restritos na extração de ZIP/TAR.
• Splash screen do instalador traduzido em 8 idiomas com animação de carregamento.
• Pacote macOS agora distribuído como .dmg (arrasta para Aplicações).
• Atualização da pypdf 6.10.2 com várias correções de segurança.
• 9 correções em ferramentas: validação reforçada na junção, marca de água, encriptação, OCR e conversão.
• Updater traduzido em 8 idiomas com diálogo de progresso melhorado.
'''
RELEASE_NOTES['es-es'] = '''Versión 1.13.9 — Auditoría de seguridad y mejoras del instalador

• Validación SHA-256 en actualizaciones, escritura atómica de configuración y límites más estrictos en extracción ZIP/TAR.
• Pantalla de carga del instalador traducida a 8 idiomas con animación.
• macOS ahora se distribuye como .dmg (arrastra a Aplicaciones).
• pypdf actualizado a 6.10.2 con varios parches de seguridad.
• 9 correcciones en herramientas: unión, marca de agua, cifrado, OCR y conversión.
• Actualizador traducido a 8 idiomas con diálogo de progreso mejorado.
'''
RELEASE_NOTES['fr-fr'] = '''Version 1.13.9 — Audit de sécurité et améliorations de l\'installateur

• Validation SHA-256 sur les mises à jour, écriture atomique de la configuration, limites strictes sur l\'extraction ZIP/TAR.
• Écran de démarrage de l\'installateur traduit en 8 langues avec animation.
• macOS livré désormais en .dmg (glissez vers Applications).
• Mise à jour de pypdf vers 6.10.2 avec plusieurs correctifs de sécurité.
• 9 corrections dans les outils : fusion, filigrane, chiffrement, OCR et conversion.
• Programme de mise à jour traduit en 8 langues avec dialogue de progression amélioré.
'''
RELEASE_NOTES['de-de'] = '''Version 1.13.9 — Sicherheitsaudit und Installer-Verbesserungen

• SHA-256-Validierung bei Updates, atomares Schreiben der Konfiguration, strengere ZIP/TAR-Extraktionsgrenzen.
• Übersetzte Installer-Splash in 8 Sprachen mit Ladeanimation.
• macOS wird jetzt als .dmg ausgeliefert (in Programme ziehen).
• pypdf auf 6.10.2 aktualisiert mit mehreren Sicherheitspatches.
• 9 Korrekturen in Werkzeugen: Zusammenführen, Wasserzeichen, Verschlüsselung, OCR, Konvertierung.
• Updater in 8 Sprachen übersetzt, mit verbessertem Fortschrittsdialog.
'''
RELEASE_NOTES['zh-cn'] = '''版本 1.13.9 — 安全审计与安装器优化

• 更新使用 SHA-256 校验、配置文件原子写入、更严格的 ZIP/TAR 解压限制。
• 安装器启动画面已翻译为 8 种语言，含加载动画。
• macOS 现以 .dmg 格式发布（拖入“应用程序”）。
• pypdf 升级至 6.10.2，包含多项安全补丁。
• 工具中 9 处修复：合并、水印、加密、OCR 与格式转换。
• 更新程序翻译为 8 种语言，进度对话框已改进。
'''
RELEASE_NOTES['it-it'] = '''Versione 1.13.9 — Audit di sicurezza e miglioramenti dell\'installer

• Validazione SHA-256 sugli aggiornamenti, scrittura atomica della configurazione, limiti più rigidi sull\'estrazione ZIP/TAR.
• Splash dell\'installer tradotto in 8 lingue con animazione di caricamento.
• macOS distribuito come .dmg (trascina in Applicazioni).
• pypdf aggiornato a 6.10.2 con diverse patch di sicurezza.
• 9 correzioni negli strumenti: unione, filigrana, crittografia, OCR e conversione.
• Updater tradotto in 8 lingue con dialogo di avanzamento migliorato.
'''
RELEASE_NOTES['nl-nl'] = '''Versie 1.13.9 — Beveiligingsaudit en installer-verbeteringen

• SHA-256-validatie bij updates, atomair schrijven van configuratie, striktere ZIP/TAR-extractielimieten.
• Vertaalde installer-splash in 8 talen met laad-animatie.
• macOS wordt nu als .dmg geleverd (sleep naar Programma\'s).
• pypdf bijgewerkt naar 6.10.2 met meerdere beveiligingspatches.
• 9 fixes in tools: samenvoegen, watermerk, versleuteling, OCR en conversie.
• Updater vertaald in 8 talen met verbeterd voortgangsdialoog.
'''

# ============================================================
# TITLE
# ============================================================
TITLE = {
    'en-us': 'pdfapps',  # User chose lowercase
    'pt-pt': 'pdfapps',
    'es-es': 'PDFApps',
    'fr-fr': 'PDFApps',
    'de-de': 'PDFApps',
    'zh-cn': 'PDFApps',
    'it-it': 'PDFApps',
    'nl-nl': 'PDFApps',
}

# ============================================================
# FEATURE 1 (single tagline, max 200 chars)
# ============================================================
FEATURE1 = {
    'en-us': 'All-in-one PDF editor with 15 tools — split, merge, OCR, compress, watermark, edit, sign, and more. 100% offline, no subscription, no account, no cloud uploads.',
    'pt-pt': 'Editor de PDF tudo-em-um com 15 ferramentas — dividir, juntar, OCR, comprimir, marca de água, editar, assinar e mais. 100% offline, sem subscrição, sem conta, sem cloud.',
    'es-es': 'Editor de PDF todo en uno con 15 herramientas — dividir, unir, OCR, comprimir, marca de agua, editar, firmar y más. 100% offline, sin suscripción, sin cuenta, sin nube.',
    'fr-fr': 'Éditeur PDF tout-en-un avec 15 outils — diviser, fusionner, OCR, compresser, filigraner, éditer, signer et plus. 100% hors ligne, sans abonnement, sans compte, sans cloud.',
    'de-de': 'All-in-One-PDF-Editor mit 15 Werkzeugen — teilen, zusammenführen, OCR, komprimieren, Wasserzeichen, bearbeiten, signieren und mehr. 100% offline, ohne Abo, ohne Konto, ohne Cloud.',
    'zh-cn': '集 15 种工具于一身的 PDF 编辑器——拆分、合并、OCR、压缩、加水印、编辑、签名等。10 0% 离线，无订阅、无账号、无云端。',
    'it-it': 'Editor PDF tutto-in-uno con 15 strumenti — dividi, unisci, OCR, comprimi, filigrana, modifica, firma e altro. 100% offline, senza abbonamento, senza account, senza cloud.',
    'nl-nl': 'All-in-one PDF-editor met 15 tools — splitsen, samenvoegen, OCR, comprimeren, watermerk, bewerken, ondertekenen en meer. 100% offline, geen abonnement, geen account, geen cloud.',
}

# ============================================================
# SEARCH TERMS (1-6, max 30 chars each)
# ============================================================
SEARCH_TERMS = {
    'en-us': ['PDF editor offline', 'Offline PDF tools', 'Compress PDF ghostscript', 'OCR PDF multi-language', 'PDF watermark tool', 'Free pdf apps'],
    'pt-pt': ['PDF editor offline', 'offline PDF tools', 'PDF splitter software', 'paginate PDF documents', '', ''],
    'es-es': ['editor de pdf offline', 'herramientas pdf offline', 'unir pdf', 'comprimir pdf', 'ocr pdf', 'pdf gratis'],
    'fr-fr': ['editeur pdf hors ligne', 'outils pdf hors ligne', 'fusionner pdf', 'compresser pdf', 'ocr pdf', 'pdf gratuit'],
    'de-de': ['pdf editor offline', 'pdf werkzeuge offline', 'pdf zusammenfuegen', 'pdf komprimieren', 'pdf ocr', 'pdf kostenlos'],
    'zh-cn': ['pdf编辑器离线', 'pdf离线工具', '合并pdf', '压缩pdf', 'pdf ocr', '免费pdf'],
    'it-it': ['editor pdf offline', 'strumenti pdf offline', 'unire pdf', 'comprimere pdf', 'ocr pdf', 'pdf gratis'],
    'nl-nl': ['pdf editor offline', 'pdf tools offline', 'pdf samenvoegen', 'pdf comprimeren', 'pdf ocr', 'gratis pdf'],
}

# ============================================================
# SCREENSHOT URLS (only en-us and pt-pt; others empty)
# ============================================================
SCREENSHOT_URLS = {
    'en-us': [
        'https://developer.microsoft.com/en-us/dashboard/apps/9P70QGR8BSMZ/submissions/1152921505700992693/listings/1152922700025040175/listingassets/3063727465079013565',
        'https://developer.microsoft.com/en-us/dashboard/apps/9P70QGR8BSMZ/submissions/1152921505700992693/listings/1152922700025040175/listingassets/3042372921360863076',
        'https://developer.microsoft.com/en-us/dashboard/apps/9P70QGR8BSMZ/submissions/1152921505700992693/listings/1152922700025040175/listingassets/3024021726938796876',
        'https://developer.microsoft.com/en-us/dashboard/apps/9P70QGR8BSMZ/submissions/1152921505700992693/listings/1152922700025040175/listingassets/3036182175373402679',
    ],
    'pt-pt': [
        'https://developer.microsoft.com/en-us/dashboard/apps/9P70QGR8BSMZ/submissions/1152921505700992693/listings/1152922700025040177/listingassets/3018033713296881548',
    ],
}

# ============================================================
# SCREENSHOT CAPTIONS
# ============================================================
SCREENSHOT_CAPTIONS = {
    'en-us': ['pdfapps viewer', 'Compress pdf with different levels of compression', 'Convert pdfs in different formats', 'Edit mode'],
    'pt-pt': ['Visualizador de pdfs com várias ferramentas'],
}

# ============================================================
# BUILD ROWS
# ============================================================
def lang_values(d, default=''):
    return [d.get(lang, default) for lang in LANGS]

URL_TYPE = 'Caminho relativo (ou URL do ficheiro no Centro de Parceiros)'
TXT = 'Texto'

rows = []

# Header
rows.append(['Field', 'ID', 'Type (Tipo)', 'default'] + LANGS)

# Core text fields
rows.append(['Description', '2', TXT, ''] + lang_values(DESCRIPTION))
rows.append(['ReleaseNotes', '3', TXT, ''] + lang_values(RELEASE_NOTES))
rows.append(['Title', '4', TXT, ''] + lang_values(TITLE))
rows.append(['ShortTitle', '5', TXT, ''] + [''] * 8)
rows.append(['SortTitle', '6', TXT, ''] + [''] * 8)
rows.append(['VoiceTitle', '7', TXT, ''] + [''] * 8)
rows.append(['ShortDescription', '8', TXT, ''] + [''] * 8)
rows.append(['DevStudio', '9', TXT, ''] + ['Nelson Duarte'] * 8)
rows.append(['CopyrightTrademarkInformation', '12', TXT, ''] + ['MIT licence'] * 8)
rows.append(['AdditionalLicenseTerms', '13', TXT, ''] + [''] * 8)

# Desktop screenshots 1-30
for i in range(1, 31):
    row_id = 99 + i  # 1->100
    values = [''] * 8
    if i <= len(SCREENSHOT_URLS['en-us']):
        values[0] = SCREENSHOT_URLS['en-us'][i-1]
    if i <= len(SCREENSHOT_URLS['pt-pt']):
        values[1] = SCREENSHOT_URLS['pt-pt'][i-1]
    rows.append([f'DesktopScreenshot{i}', str(row_id), URL_TYPE, ''] + values)

# Desktop screenshot captions 1-30
for i in range(1, 31):
    row_id = 149 + i
    values = [''] * 8
    if i <= len(SCREENSHOT_CAPTIONS['en-us']):
        values[0] = SCREENSHOT_CAPTIONS['en-us'][i-1]
    if i <= len(SCREENSHOT_CAPTIONS['pt-pt']):
        values[1] = SCREENSHOT_CAPTIONS['pt-pt'][i-1]
    rows.append([f'DesktopScreenshotCaption{i}', str(row_id), TXT, ''] + values)

# Mobile screenshots/captions, Xbox, Holographic - all empty
for prefix, base_id, count in [
    ('MobileScreenshot', 200, 30),
    ('MobileScreenshotCaption', 250, 30),
    ('XboxScreenshot', 300, 30),
    ('XboxScreenshotCaption', 350, 30),
    ('HolographicScreenshot', 400, 30),
    ('HolographicScreenshotCaption', 450, 30),
]:
    type_str = URL_TYPE if 'Caption' not in prefix else TXT
    for i in range(1, count + 1):
        rows.append([f'{prefix}{i}', str(base_id + i - 1), type_str, ''] + [''] * 8)

# SurfaceHub screenshots/captions - start at index 11 per original
for i in range(11, 31):
    rows.append([f'SurfaceHubScreenshot{i}', str(500 + i - 1), URL_TYPE, ''] + [''] * 8)
for i in range(11, 31):
    rows.append([f'SurfaceHubScreenshotCaption{i}', str(550 + i - 1), TXT, ''] + [''] * 8)

# Logos and promo images
rows.append(['StoreLogo720x1080', '600', URL_TYPE, ''] + [''] * 8)
rows.append(['StoreLogo1080x1080', '601', URL_TYPE, ''] + [''] * 8)
rows.append(['StoreLogo300x300', '602', URL_TYPE, ''] + [''] * 8)
rows.append(['OverrideLogosForWin10', '603', 'True/False', ''] + ['False'] * 8)
rows.append(['StoreLogoOverride150x150', '604', URL_TYPE, ''] + [''] * 8)
rows.append(['StoreLogoOverride71x71', '605', URL_TYPE, ''] + [''] * 8)
rows.append(['PromoImage1920x1080', '606', URL_TYPE, ''] + [''] * 8)
rows.append(['PromoImage2400x1200', '607', URL_TYPE, ''] + [''] * 8)
rows.append(['XboxBrandedKeyArt584x800', '608', URL_TYPE, ''] + [''] * 8)
rows.append(['XboxTitledHero1920x1080', '609', URL_TYPE, ''] + [''] * 8)
rows.append(['XboxFeaturedPromo1080x1080', '610', URL_TYPE, ''] + [''] * 8)
rows.append(['OptionalPromo358x358', '611', URL_TYPE, ''] + [''] * 8)
rows.append(['OptionalPromo1000x800', '612', URL_TYPE, ''] + [''] * 8)
rows.append(['OptionalPromo414x180', '613', URL_TYPE, ''] + [''] * 8)

# Features 1-20
for i in range(1, 21):
    row_id = 699 + i
    values = [''] * 8
    if i == 1:
        values = lang_values(FEATURE1)
    rows.append([f'Feature{i}', str(row_id), TXT, ''] + values)

# Hardware reqs
for i in range(1, 12):
    rows.append([f'MinimumHardwareReq{i}', str(799 + i), TXT, ''] + [''] * 8)
for i in range(1, 12):
    rows.append([f'RecommendedHardwareReq{i}', str(849 + i), TXT, ''] + [''] * 8)

# Search terms 1-7
for i in range(1, 8):
    row_id = 899 + i
    values = []
    for lang in LANGS:
        terms = SEARCH_TERMS.get(lang, [])
        values.append(terms[i-1] if i-1 < len(terms) else '')
    rows.append([f'SearchTerm{i}', str(row_id), TXT, ''] + values)

# Trailers
rows.append(['TrailerToPlayAtTopOfListing', '999', URL_TYPE, ''] + [''] * 8)
for i in range(1, 16):
    rows.append([f'Trailer{i}', str(999 + i), URL_TYPE, ''] + [''] * 8)
for i in range(1, 16):
    rows.append([f'TrailerTitle{i}', str(1019 + i), TXT, ''] + [''] * 8)
for i in range(1, 16):
    rows.append([f'TrailerThumbnail{i}', str(1039 + i), URL_TYPE, ''] + [''] * 8)
for i in range(1, 16):
    rows.append([f'TrailerClosedCaption{i}', str(1054 + i), URL_TYPE, ''] + [''] * 8)
for i in range(1, 16):
    rows.append([f'TrailerAudioDescription{i}', str(1069 + i), URL_TYPE, ''] + [''] * 8)

# Trailing empty rows (match original)
for _ in range(24):
    rows.append([''] * 12)

# ============================================================
# WRITE FILE
# ============================================================
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, '..', 'listingData-9P70QGR8BSMZ-filled.csv')
output_path = os.path.normpath(output_path)

with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
    writer.writerows(rows)

print(f'Wrote {len(rows)} rows to {output_path}')
