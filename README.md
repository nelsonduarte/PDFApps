# PDFApps

> Editor e gestor de PDFs para Windows — rápido, offline e sem subscrições.

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.10-green?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?logo=windows)
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
| **Reordenar** | Interface drag-and-drop para reordenar ou remover páginas |
| **Comprimir** | Reduz o tamanho do ficheiro com três níveis de compressão (extrema / recomendada / leve) |
| **Encriptar** | Protege o PDF com senha ou remove a proteção existente |
| **Marca d'água** | Sobrepõe um PDF de marca/carimbo sobre as páginas com controlo de opacidade e posição |
| **OCR** | Reconhece texto em PDFs digitalizados — suporta PT, EN, ES, FR e DE |
| **Editar** | Editor visual inline: redigir, inserir texto, imagem, realce, notas, formulários e edição de texto existente |
| **Informação** | Mostra metadados, número de páginas, tamanho e propriedades do documento |

### Destaques

- Visualizador de PDF integrado com zoom e navegação por páginas
- Suporte completo a arrastar e largar ficheiros em todos os campos
- Interface escura moderna com painel lateral colapsável
- 100% offline — os teus ficheiros nunca saem do teu computador
- Instalador com deteção e instalação automática do motor OCR (Tesseract)

---

## Requisitos

### Execução (utilizador final)

- Windows 10 / 11 (64-bit)
- [PDFAppsSetup.exe](dist/PDFAppsSetup.exe) — inclui tudo; o Tesseract OCR é instalado automaticamente se necessário

### Desenvolvimento

- Python 3.14+
- As dependências listadas em [requirements.txt](requirements.txt)

> **Tesseract OCR** é necessário para a funcionalidade de reconhecimento de texto.
> O instalador trata disto automaticamente. Para desenvolvimento, instala manualmente:
> <https://github.com/UB-Mannheim/tesseract/releases>

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
pyinstaller pdfapps.spec --noconfirm

# 2. Desinstalador
pyinstaller uninstaller.spec --noconfirm

# 3. Instalador (bundla os dois anteriores)
pyinstaller installer.spec --noconfirm
```

| Ficheiro | Descrição |
|---|---|
| `dist/PDFApps.exe` | Aplicação principal (~78 MB) |
| `dist/PDFAppsUninstall.exe` | Desinstalador standalone (~11 MB) |
| `dist/PDFAppsSetup.exe` | **Instalador para distribuição** (~99 MB) |

---

## Stack tecnológica

| Componente | Tecnologia |
|---|---|
| Interface gráfica | [PySide6](https://doc.qt.io/qtforpython/) (Qt 6) |
| Renderização PDF | [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz) |
| Manipulação PDF | [pypdf](https://pypdf.readthedocs.io/) |
| OCR | [Tesseract](https://github.com/tesseract-ocr/tesseract) + [pytesseract](https://github.com/madmaze/pytesseract) |
| Processamento de imagem | [Pillow](https://python-pillow.org/) |
| Ícones | [QtAwesome](https://github.com/spyder-ide/qtawesome) |
| Empacotamento | [PyInstaller](https://pyinstaller.org/) |

---

## Estrutura do projeto

```
PDFApps/
├── pdfapps.py          # Código fonte principal
├── installer.py        # Instalador (UI tkinter)
├── uninstaller.py      # Desinstalador
├── pdfapps.spec        # Configuração PyInstaller — app
├── installer.spec      # Configuração PyInstaller — instalador
├── uninstaller.spec    # Configuração PyInstaller — desinstalador
├── icon.ico            # Ícone da aplicação
├── requirements.txt    # Dependências Python
└── dist/               # Executáveis gerados
```

---

## Licença

Este projeto está licenciado sob a [MIT License](LICENSE).
