# PDFApps

> Editor e gestor de PDFs para Windows — rápido, offline e sem subscrições.

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.10-green?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## Funcionalidades

PDFApps reúne num só lugar todas as operações do dia a dia com ficheiros PDF, sem necessidade de ligação à Internet nem conta em serviços externos.

| Ferramenta | Descrição |
|---|---|
| **Dividir** | Corta o PDF em vários ficheiros por intervalos de páginas definidos pelo utilizador |
| **Juntar** | Combina múltiplos PDFs (arrastar e largar) numa única saída, com ordenação livre |
| **Rodar** | Roda páginas individuais ou todo o documento em qualquer ângulo |
| **Extrair páginas** | Exporta um subconjunto de páginas para um novo PDF |
| **Reordenar** | Interface drag-and-drop para reordenar ou remover páginas com pré-visualização |
| **Comprimir** | Reduz o tamanho do ficheiro com três níveis de compressão (extrema / recomendada / leve) |
| **Encriptar** | Protege o PDF com senha ou remove a proteção existente |
| **Marca d'água** | Sobrepõe um PDF de marca/carimbo sobre as páginas com controlo de opacidade e posição |
| **OCR** | Reconhece texto em PDFs digitalizados — suporta PT, EN, ES, FR e DE |
| **Editar** | Editor visual inline: redigir, inserir texto, imagem, realce, notas, formulários e edição de texto existente |
| **Informação** | Mostra metadados, número de páginas, tamanho e propriedades do documento |

### Visualizador integrado

- Scroll contínuo por todas as páginas (estilo Adobe Acrobat)
- Zoom com Ctrl+scroll ou botões de zoom
- Seleção e cópia de texto por arrastar
- Suporte a PDF com senha
- Drag & drop de ficheiros

### Outros destaques

- Interface escura moderna com painel lateral colapsável
- Suporte completo a arrastar e largar ficheiros em todos os campos
- 100% offline — os teus ficheiros nunca saem do teu computador
- Instalador com deteção e instalação automática do motor OCR (Tesseract)

---

## Requisitos

### Execução (utilizador final)

| Plataforma | Requisito |
|---|---|
| **Windows** 10/11 64-bit | `PDFAppsSetup.exe` — inclui tudo; Tesseract instalado automaticamente |
| **macOS** 10.14+ | `PDFApps.app` — Tesseract via `brew install tesseract tesseract-lang` |
| **Linux** (Ubuntu/Debian/Arch) | Binário `PDFApps` — Tesseract via `sudo apt install tesseract-ocr` |

### Desenvolvimento

- Python 3.14+
- Dependências em [requirements.txt](requirements.txt)

> **Tesseract OCR** é necessário para a funcionalidade de reconhecimento de texto.
> - **Windows**: o instalador trata disto automaticamente
> - **macOS**: `brew install tesseract tesseract-lang`
> - **Linux**: `sudo apt install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng`

---

## Instalação (utilizador final)

1. Descarrega `PDFAppsSetup.exe` da pasta `dist/`
2. Executa o instalador e segue os passos
3. O PDFApps ficará disponível no Menu Iniciar e, opcionalmente, no Ambiente de Trabalho

Para desinstalar, vai a **Definições → Aplicações** ou usa o atalho de desinstalação no Menu Iniciar.

---

## Configuração do ambiente de desenvolvimento

```bash
# Clonar o repositório
git clone <url-do-repositório>
cd PDFApps

# Criar e ativar ambiente virtual
python -m venv venv
venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt

# Executar a aplicação
python pdfapps.py
```

---

## Build

O processo de build gera três executáveis na pasta `dist/`:

```bash
# 1. Aplicação principal
python -m PyInstaller --noconfirm pdfapps.spec

# 2. Desinstalador
python -m PyInstaller --noconfirm uninstaller.spec

# 3. Instalador (bundla os dois anteriores)
python -m PyInstaller --noconfirm installer.spec
```

| Ficheiro | Descrição |
|---|---|
| `dist/PDFApps.exe` | Aplicação principal (~78 MB) |
| `dist/PDFAppsUninstall.exe` | Desinstalador standalone (~11 MB) |
| `dist/PDFAppsSetup.exe` | **Instalador para distribuição** (~99 MB) |

---

## Stack tecnológica

| Componente | Tecnologia | Versão |
|---|---|---|
| Interface gráfica | [PySide6](https://doc.qt.io/qtforpython/) (Qt 6) | 6.10.2 |
| Renderização PDF | [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz) | 1.27.2 |
| Manipulação PDF | [pypdf](https://pypdf.readthedocs.io/) | 6.8.0 |
| OCR | [Tesseract](https://github.com/tesseract-ocr/tesseract) + [pytesseract](https://github.com/madmaze/pytesseract) | 0.3.13 |
| Processamento de imagem | [Pillow](https://python-pillow.org/) | 12.1.1 |
| Ícones | [QtAwesome](https://github.com/spyder-ide/qtawesome) | 1.4.1 |
| Empacotamento | [PyInstaller](https://pyinstaller.org/) | 6.19.0 |

---

## Estrutura do projeto

```
PDFApps/
├── pdfapps.py              # Ponto de entrada da aplicação
├── installer.py            # Instalador (UI tkinter)
├── uninstaller.py          # Desinstalador
├── pdfapps.spec            # Configuração PyInstaller — app
├── installer.spec          # Configuração PyInstaller — instalador
├── uninstaller.spec        # Configuração PyInstaller — desinstalador
├── icon.ico                # Ícone da aplicação
├── requirements.txt        # Dependências Python
├── app/                    # Código fonte modular
│   ├── constants.py        # Cores e constantes de design
│   ├── styles.py           # Stylesheet Qt (tema escuro/claro)
│   ├── utils.py            # Utilitários partilhados
│   ├── widgets.py          # Widgets reutilizáveis (DropFileEdit, etc.)
│   ├── base.py             # Classe base para ferramentas (BasePage)
│   ├── window.py           # Janela principal (MainWindow)
│   ├── tools/              # Ferramentas de manipulação PDF
│   │   ├── dividir.py
│   │   ├── juntar.py
│   │   ├── rotar.py
│   │   ├── extrair.py
│   │   ├── reordenar.py
│   │   ├── comprimir.py
│   │   ├── encriptar.py
│   │   ├── marca_dagua.py
│   │   ├── info.py
│   │   └── ocr.py
│   ├── viewer/             # Visualizador PDF integrado
│   │   ├── canvas.py       # Renderização contínua de páginas (fitz)
│   │   └── panel.py        # Painel do visualizador com controlos
│   └── editor/             # Editor PDF visual
│       ├── canvas.py       # Canvas de edição (PdfEditCanvas)
│       ├── tab.py          # Tab de edição (TabEditar)
│       └── dialogs.py      # Diálogos auxiliares
└── dist/                   # Executáveis gerados (após build)
```

---

## Licença

Este projeto está licenciado sob a [MIT License](LICENSE).
