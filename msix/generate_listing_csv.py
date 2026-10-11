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
RELEASE_NOTES['en-us'] = '''Version 1.15.1: OCR and compression fixes, and security updates

• OCR language: OCR now runs in the language you pick. Before, every run used the first installed language in alphabetical order. The list shows only installed languages and keeps your choice, and Chinese and Dutch now appear under their translated names.
• PDFApps no longer closes when you run OCR with an old or unrecognised version of Tesseract installed.
• No more console windows: running OCR or compressing a PDF no longer opens a terminal window on Windows.
• Linux (Snap): OCR now finds its bundled language files, and compression runs its stronger stage, which it skipped before. On Linux, compressing some damaged PDFs no longer hangs for about two minutes.
• Starting PDFApps from a terminal no longer prints a deprecation notice.
• The Help button now opens the current documentation page.
• Security: pypdf 6.19.0, closing three advisories present in 1.15.0 where a crafted PDF could use excessive memory or keep the app busy, and urllib3 2.8.0, closing three more.
'''
RELEASE_NOTES['pt-pt'] = '''Versão 1.15.1: Correções no OCR e na compressão, e atualizações de segurança

• Idioma do OCR: o OCR passa a usar o idioma que escolher. Antes, cada execução usava o primeiro idioma instalado por ordem alfabética. A lista mostra apenas os idiomas instalados e mantém a sua escolha, e o chinês e o neerlandês passam a aparecer com o nome traduzido.
• O PDFApps deixa de fechar quando executa o OCR com uma versão antiga ou não reconhecida do Tesseract instalada.
• Sem janelas de consola: executar o OCR ou comprimir um PDF deixa de abrir uma janela de terminal no Windows.
• Linux (Snap): o OCR passa a encontrar os ficheiros de idioma incluídos, e a compressão executa a etapa mais forte, que antes era ignorada. No Linux, comprimir alguns PDFs danificados deixa de bloquear durante cerca de dois minutos.
• Iniciar o PDFApps a partir de um terminal deixa de mostrar um aviso de descontinuação.
• O botão de Ajuda abre agora a página de documentação atual.
• Segurança: pypdf 6.19.0, que fecha três avisos presentes na 1.15.0 em que um PDF manipulado podia consumir memória em excesso ou manter a aplicação ocupada, e urllib3 2.8.0, que fecha mais três.
'''
RELEASE_NOTES['es-es'] = '''Versión 1.15.1: Correcciones de OCR y compresión, y actualizaciones de seguridad

• Idioma del OCR: el OCR usa ahora el idioma que elija. Antes, cada ejecución usaba el primer idioma instalado por orden alfabético. La lista muestra solo los idiomas instalados y conserva su elección, y el chino y el neerlandés aparecen ahora con su nombre traducido.
• PDFApps ya no se cierra al ejecutar el OCR con una versión antigua o no reconocida de Tesseract instalada.
• Sin ventanas de consola: ejecutar el OCR o comprimir un PDF ya no abre una ventana de terminal en Windows.
• Linux (Snap): el OCR encuentra ahora los archivos de idioma incluidos, y la compresión ejecuta su etapa más potente, que antes se omitía. En Linux, comprimir algunos PDF dañados ya no se bloquea durante unos dos minutos.
• Iniciar PDFApps desde un terminal ya no muestra un aviso de obsolescencia.
• El botón de Ayuda abre ahora la página de documentación actual.
• Seguridad: pypdf 6.19.0, que cierra tres avisos presentes en 1.15.0 en los que un PDF manipulado podía consumir memoria en exceso o mantener ocupada la aplicación, y urllib3 2.8.0, que cierra otros tres.
'''
RELEASE_NOTES['fr-fr'] = '''Version 1.15.1 : Corrections de l\'OCR et de la compression, et mises à jour de sécurité

• Langue de l\'OCR : l\'OCR utilise désormais la langue que vous choisissez. Auparavant, chaque exécution utilisait la première langue installée par ordre alphabétique. La liste n\'affiche que les langues installées et conserve votre choix, et le chinois et le néerlandais apparaissent désormais sous leur nom traduit.
• PDFApps ne se ferme plus lorsque vous lancez l\'OCR avec une version ancienne ou non reconnue de Tesseract installée.
• Plus de fenêtres de console : lancer l\'OCR ou compresser un PDF n\'ouvre plus de fenêtre de terminal sous Windows.
• Linux (Snap) : l\'OCR trouve désormais les fichiers de langue inclus, et la compression exécute son étape la plus poussée, qui était ignorée auparavant. Sous Linux, compresser certains PDF endommagés ne bloque plus pendant environ deux minutes.
• Lancer PDFApps depuis un terminal n\'affiche plus d\'avis d\'obsolescence.
• Le bouton Aide ouvre désormais la page de documentation actuelle.
• Sécurité : pypdf 6.19.0, qui corrige trois avis présents dans la 1.15.0 où un PDF malveillant pouvait consommer trop de mémoire ou occuper l\'application, et urllib3 2.8.0, qui en corrige trois autres.
'''
RELEASE_NOTES['de-de'] = '''Version 1.15.1: OCR- und Komprimierungskorrekturen sowie Sicherheitsupdates

• OCR-Sprache: Die Texterkennung verwendet jetzt die Sprache, die Sie auswählen. Bisher nutzte jeder Lauf die erste installierte Sprache in alphabetischer Reihenfolge. Die Liste zeigt nur installierte Sprachen und behält Ihre Auswahl, und Chinesisch und Niederländisch erscheinen jetzt mit übersetztem Namen.
• PDFApps schließt sich nicht mehr, wenn Sie OCR mit einer alten oder nicht erkannten Tesseract-Version ausführen.
• Keine Konsolenfenster mehr: OCR oder das Komprimieren einer PDF-Datei öffnet unter Windows kein Terminalfenster mehr.
• Linux (Snap): Die OCR findet jetzt die mitgelieferten Sprachdateien, und die Komprimierung führt ihre stärkere Stufe aus, die bisher übersprungen wurde. Unter Linux hängt das Komprimieren mancher beschädigter PDFs nicht mehr etwa zwei Minuten lang.
• Beim Start von PDFApps aus einem Terminal erscheint kein Veraltungshinweis mehr.
• Die Hilfe-Schaltfläche öffnet jetzt die aktuelle Dokumentationsseite.
• Sicherheit: pypdf 6.19.0 schließt drei in 1.15.0 vorhandene Hinweise, bei denen eine manipulierte PDF-Datei übermäßig Speicher verbrauchen oder die App blockieren konnte, und urllib3 2.8.0 schließt drei weitere.
'''
RELEASE_NOTES['zh-cn'] = '''版本 1.15.1：OCR 与压缩修复及安全更新

• OCR 语言：OCR 现在使用您选择的语言。此前每次运行都会使用按字母顺序排列的第一个已安装语言。列表只显示已安装的语言并保留您的选择，简体中文和荷兰语现在显示为翻译后的名称。
• 安装了旧版或无法识别版本的 Tesseract 时，运行 OCR 不再导致 PDFApps 关闭。
• 不再弹出控制台窗口：在 Windows 上运行 OCR 或压缩 PDF 时不再打开终端窗口。
• Linux (Snap)：OCR 现在能找到随附的语言文件，压缩也会运行此前被跳过的更强压缩步骤。在 Linux 上，压缩某些损坏的 PDF 不再卡住约两分钟。
• 从终端启动 PDFApps 时不再显示弃用提示。
• “帮助”按钮现在打开当前的文档页面。
• 安全：pypdf 升级至 6.19.0，修复 1.15.0 中存在的三项公告（特制 PDF 可能占用过多内存或使程序长时间忙碌）；urllib3 升级至 2.8.0，另修复三项公告。
'''
RELEASE_NOTES['it-it'] = '''Versione 1.15.1: Correzioni di OCR e compressione, e aggiornamenti di sicurezza

• Lingua dell\'OCR: l\'OCR usa ora la lingua che scegli. Prima, ogni esecuzione usava la prima lingua installata in ordine alfabetico. L\'elenco mostra solo le lingue installate e mantiene la tua scelta, e il cinese e l\'olandese compaiono ora con il nome tradotto.
• PDFApps non si chiude più quando esegui l\'OCR con una versione di Tesseract vecchia o non riconosciuta.
• Niente più finestre di console: eseguire l\'OCR o comprimere un PDF non apre più una finestra del terminale su Windows.
• Linux (Snap): l\'OCR trova ora i file di lingua inclusi, e la compressione esegue la sua fase più incisiva, che prima veniva saltata. Su Linux, comprimere alcuni PDF danneggiati non si blocca più per circa due minuti.
• Avviare PDFApps da un terminale non mostra più un avviso di deprecazione.
• Il pulsante Aiuto apre ora la pagina della documentazione attuale.
• Sicurezza: pypdf 6.19.0, che chiude tre avvisi presenti nella 1.15.0 in cui un PDF manipolato poteva consumare troppa memoria o tenere occupata l\'app, e urllib3 2.8.0, che ne chiude altri tre.
'''
RELEASE_NOTES['nl-nl'] = '''Versie 1.15.1: OCR- en compressiefixes, en beveiligingsupdates

• OCR-taal: OCR gebruikt nu de taal die u kiest. Voorheen gebruikte elke run de eerste geïnstalleerde taal in alfabetische volgorde. De lijst toont alleen geïnstalleerde talen en onthoudt uw keuze, en Chinees en Nederlands verschijnen nu met hun vertaalde naam.
• PDFApps sluit niet meer af wanneer u OCR uitvoert met een oude of niet-herkende versie van Tesseract.
• Geen consolevensters meer: OCR uitvoeren of een PDF comprimeren opent op Windows geen terminalvenster meer.
• Linux (Snap): OCR vindt nu de meegeleverde taalbestanden, en compressie voert de sterkere stap uit die voorheen werd overgeslagen. Op Linux blijft het comprimeren van sommige beschadigde PDF\'s niet langer zo\'n twee minuten hangen.
• PDFApps starten vanuit een terminal toont geen verouderingsmelding meer.
• De Help-knop opent nu de actuele documentatiepagina.
• Beveiliging: pypdf 6.19.0, met drie adviezen uit 1.15.0 verholpen waarbij een gemanipuleerde PDF overmatig geheugen kon gebruiken of de app bezig kon houden, en urllib3 2.8.0, met nog drie verholpen.
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
