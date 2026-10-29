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
RELEASE_NOTES['en-us'] = '''Version 1.15.2: Compression fixes and security updates

• Compression no longer removes colour gradients. On some PDFs, pages lost their gradients or came out blank. PDFs with gradients now skip the step that caused it, so they may compress less than before.
• Compression no longer turns pages to follow the direction of their text.
• Compression keeps the invisible text layer added by OCR, so compressed scans stay searchable, and in most cases also keeps links, form values, attachments and metadata.
• Converter and Import now ask before replacing an existing file with the same name.
• Security: pypdf 6.21.2, closing three high-severity issues that a crafted PDF could reach, and Pillow 13.0.0.
• Known issue: on rare PDFs, compression can close the app. The cause is in a third-party library and a fix is planned for the next update.
'''
RELEASE_NOTES['pt-pt'] = '''Versão 1.15.2: Correções na compressão e atualizações de segurança

• A compressão deixa de remover gradientes de cor. Em alguns PDFs, as páginas perdiam os gradientes ou ficavam em branco. Os PDFs com gradientes passam a saltar o passo que causava o problema, pelo que podem comprimir menos do que antes.
• A compressão deixa de rodar as páginas para seguir a direção do texto.
• A compressão mantém a camada de texto invisível criada pelo OCR, para que os documentos digitalizados continuem pesquisáveis, e na maioria dos casos mantém também ligações, valores de formulários, anexos e metadados.
• O Converter e o Importar passam a perguntar antes de substituir um ficheiro existente com o mesmo nome.
• Segurança: pypdf 6.21.2, que fecha três falhas graves que um PDF manipulado podia explorar, e Pillow 13.0.0.
• Problema conhecido: em PDFs raros, a compressão pode fechar a aplicação. A causa está numa biblioteca de terceiros e a correção está prevista para a próxima atualização.
'''
RELEASE_NOTES['es-es'] = '''Versión 1.15.2: Correcciones de compresión y actualizaciones de seguridad

• La compresión ya no elimina los degradados de color. En algunos PDF, las páginas perdían sus degradados o quedaban en blanco. Los PDF con degradados omiten ahora el paso que lo causaba, por lo que pueden comprimirse menos que antes.
• La compresión ya no gira las páginas para seguir la dirección de su texto.
• La compresión conserva la capa de texto invisible que añade el OCR, para que los documentos escaneados comprimidos sigan admitiendo búsquedas, y en la mayoría de los casos conserva también los enlaces, los valores de los formularios, los adjuntos y los metadatos.
• Convertir e Importar preguntan ahora antes de reemplazar un archivo existente con el mismo nombre.
• Seguridad: pypdf 6.21.2, que cierra tres fallos de gravedad alta a los que podía llegar un PDF manipulado, y Pillow 13.0.0.
• Problema conocido: en algunos PDF poco habituales, la compresión puede cerrar la aplicación. La causa está en una biblioteca de terceros y hay una corrección prevista para la próxima actualización.
'''
RELEASE_NOTES['fr-fr'] = '''Version 1.15.2 : Corrections de la compression et mises à jour de sécurité

• La compression ne supprime plus les dégradés de couleur. Sur certains PDF, les pages perdaient leurs dégradés ou devenaient blanches. Les PDF contenant des dégradés ignorent désormais l\'étape qui en était la cause, ils peuvent donc être moins compressés qu\'avant.
• La compression ne fait plus pivoter les pages pour suivre le sens de leur texte.
• La compression conserve la couche de texte invisible ajoutée par l\'OCR, afin que les documents numérisés compressés restent consultables par recherche, et conserve aussi, dans la plupart des cas, les liens, les valeurs des formulaires, les pièces jointes et les métadonnées.
• Convertir et Importer demandent désormais confirmation avant de remplacer un fichier existant portant le même nom.
• Sécurité : pypdf 6.21.2, qui corrige trois failles de gravité élevée qu\'un PDF malveillant pouvait atteindre, et Pillow 13.0.0.
• Problème connu : sur de rares PDF, la compression peut fermer l\'application. La cause se trouve dans une bibliothèque tierce et un correctif est prévu pour la prochaine mise à jour.
'''
RELEASE_NOTES['de-de'] = '''Version 1.15.2: Komprimierungskorrekturen und Sicherheitsupdates

• Die Komprimierung entfernt keine Farbverläufe mehr. Bei manchen PDFs verloren Seiten ihre Farbverläufe oder wurden leer. PDFs mit Farbverläufen überspringen jetzt den Schritt, der das verursacht hat, und werden daher möglicherweise weniger stark komprimiert als bisher.
• Die Komprimierung dreht Seiten nicht mehr, um sie an der Richtung ihres Textes auszurichten.
• Die Komprimierung behält die unsichtbare Textebene der Texterkennung (OCR), sodass komprimierte Scans durchsuchbar bleiben, und in den meisten Fällen auch Links, Formularwerte, Anhänge und Metadaten.
• Konvertieren und Importieren fragen jetzt nach, bevor eine vorhandene Datei mit demselben Namen ersetzt wird.
• Sicherheit: pypdf 6.21.2 schließt drei schwerwiegende Lücken, die eine manipulierte PDF-Datei erreichen konnte, dazu Pillow 13.0.0.
• Bekanntes Problem: Bei seltenen PDFs kann die Komprimierung die App schließen. Die Ursache liegt in einer Drittanbieter-Bibliothek, eine Korrektur ist für das nächste Update geplant.
'''
RELEASE_NOTES['zh-cn'] = '''版本 1.15.2：压缩修复及安全更新

• 压缩不再移除颜色渐变。在某些 PDF 中，页面会丢失渐变或变成空白。包含渐变的 PDF 现在会跳过导致该问题的步骤，因此压缩效果可能不如以前。
• 压缩不再为了顺应文字方向而旋转页面。
• 压缩会保留 OCR 添加的不可见文本层，使压缩后的扫描件仍可搜索；在大多数情况下，还会保留链接、表单值、附件和元数据。
• “转换”和“导入”现在会在替换同名的现有文件之前进行询问。
• 安全：pypdf 升级至 6.21.2，修复三个特制 PDF 可触发的高危问题；Pillow 升级至 13.0.0。
• 已知问题：在少数 PDF 上，压缩可能导致应用关闭。原因在于第三方库，修复计划在下一次更新中发布。
'''
RELEASE_NOTES['it-it'] = '''Versione 1.15.2: Correzioni della compressione e aggiornamenti di sicurezza

• La compressione non rimuove più le sfumature di colore. In alcuni PDF, le pagine perdevano le sfumature o risultavano vuote. I PDF con sfumature saltano ora il passaggio che causava il problema, quindi potrebbero essere compressi meno di prima.
• La compressione non ruota più le pagine per seguire la direzione del testo.
• La compressione mantiene il livello di testo invisibile aggiunto dall\'OCR, così le scansioni compresse restano ricercabili, e nella maggior parte dei casi mantiene anche link, valori dei moduli, allegati e metadati.
• Converti e Importa chiedono ora conferma prima di sostituire un file esistente con lo stesso nome.
• Sicurezza: pypdf 6.21.2, che chiude tre vulnerabilità di gravità elevata sfruttabili da un PDF manipolato, e Pillow 13.0.0.
• Problema noto: su rari PDF, la compressione può chiudere l\'app. La causa è in una libreria di terze parti e una correzione è prevista per il prossimo aggiornamento.
'''
RELEASE_NOTES['nl-nl'] = '''Versie 1.15.2: Compressiefixes en beveiligingsupdates

• Compressie verwijdert geen kleurverlopen meer. Bij sommige PDF\'s verloren pagina\'s hun kleurverlopen of werden ze leeg. PDF\'s met kleurverlopen slaan nu de stap over die dit veroorzaakte, waardoor ze mogelijk minder sterk worden gecomprimeerd dan voorheen.
• Compressie draait pagina\'s niet meer om de richting van hun tekst te volgen.
• Compressie behoudt de onzichtbare tekstlaag die OCR toevoegt, zodat gecomprimeerde scans doorzoekbaar blijven, en behoudt in de meeste gevallen ook koppelingen, formulierwaarden, bijlagen en metadata.
• Converteren en Importeren vragen nu om bevestiging voordat een bestaand bestand met dezelfde naam wordt vervangen.
• Beveiliging: pypdf 6.21.2, met drie ernstige problemen verholpen die een gemanipuleerde PDF kon bereiken, en Pillow 13.0.0.
• Bekend probleem: bij zeldzame PDF\'s kan compressie de app afsluiten. De oorzaak ligt in een externe bibliotheek en een oplossing staat gepland voor de volgende update.
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
