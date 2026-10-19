# Plugvan

<p align="center">
  <a href="https://github.com/kagankurubas/plugvan/actions/workflows/ci.yml"><img src="https://github.com/kagankurubas/plugvan/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/MCP-FastMCP-8A2BE2?logo=anthropic&logoColor=white" alt="Model Context Protocol" />
  <img src="https://img.shields.io/badge/Pydantic-v2-e92063?logo=pydantic&logoColor=white" alt="Pydantic" />
  <img src="https://img.shields.io/badge/Todoist_API-v1-e44332?logo=todoist&logoColor=white" alt="Todoist API" />
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
</p>

<p align="center">
  <strong>Plugvan: hand-written and validated MCP integrations for the apps you use, starting with Todoist. It is a standalone server, not a gateway or proxy for other MCP servers.</strong>
</p>

<p align="center">
  <strong>Todoist integration:</strong> A local Model Context Protocol (MCP) server that lets AI assistants like Claude Desktop manage Todoist over STDIO, with smart project routing, natural language due dates, and strict validation.
</p>

<p align="center">
  <a href="#english">English</a> •
  <a href="#türkçe">Türkçe</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#tests">Tests</a>
</p>

---

<a name="architecture"></a>
## 🏗️ Architecture & Data Flow / Mimari Akış

```mermaid
flowchart TD
    subgraph Sources["📥 Input Sources"]
        A1["🤖 Claude Desktop (MCP Client via STDIO)"]
    end

    subgraph Gateways["🚀 Gateways & Interfaces"]
        C1["🤖 FastMCP Server (plugvan.todoist)\n[Task/Project Get/Create/Update/Delete, Section, Label, Comment Tools]"]
    end

    subgraph Todoist["✅ Todoist"]
        D["🎯 Todoist REST API v1\n(Categorized Tasks, Natural Due Dates & Direct Web Links)"]
    end

    A1 <-->|STDIO / JSON-RPC| C1
    C1 -->|Official Python SDK| D
```

---

<a name="english"></a>
## 🇬🇧 English

Plugvan is primarily a local **Model Context Protocol (MCP)** server: Claude Desktop launches it as a subprocess and talks to it over STDIO, so no web server or deployment is needed. It lets an AI assistant manage Todoist through conversation using smart project resolution, natural language due dates, and strict schema validation.

### 🌟 Key Features

- **🤖 Model Context Protocol (MCP) Server (`plugvan.todoist`):** FastMCP server over STDIO for Claude Desktop with full suite of Todoist management tools:
  - **Tasks:** `create_task` (subtasks via `parent_id`, deadlines via `deadline_date`), `get_task`, `list_tasks`, `complete_task`, `reopen_task`, `update_task` (move/reparent, deadline updates), `delete_task`
  - **Sections / Kanban:** `create_section`, `list_sections`, `update_section`, `delete_section`
  - **Labels:** `list_labels`, `create_label`, `update_label`, `delete_label`
  - **Comments / Notes:** `add_comment`, `get_comments`
  - **Projects & Hierarchy:** `create_project` (nested subprojects), `get_project`, `update_project`, `delete_project`, `list_projects` (tree view)
- **🎯 Smart Name Resolution:** Maps human-readable project, section and label names (case-insensitive, with Turkish/Unicode normalization) to Todoist IDs.
  - **MCP tools:**
    - An unknown name returns an error, and nothing is written.
    - When several items match, the tool returns an ambiguity error listing up to 5 candidates as `name (ID)`.
    - Destructive tools (`delete_project`, `update_project`, `delete_section`, `update_section`, `delete_label`, `update_label`) accept only an ID or an exact name.
    - `create_task`, `update_task`, `create_project` (parent), `create_section` and `list_sections` also accept a project name that partially matches exactly one project. Their messages show the project's real name.
    - Sections match only by ID or exact name, inside the resolved project.
    - `Inbox` / `Gelen Kutusu` always resolve to the Inbox.
- **📏 Name limits (MCP tools):**
  - Project names: up to 120 characters.
  - Label names: up to 60 characters.
  - Section names: up to 120 characters here. Todoist allows 2,048 (as of October 2026), so a section with a longer name can only be addressed by its ID.
  - The number of projects you can have depends on your Todoist plan. See Todoist's official [Usage limits in Todoist](https://www.todoist.com/help/todoist/get-started/usage-limits-in-todoist-e5rcSY) page for the current limits.
  - Name lookup searches only your active projects.
  - Archived projects are not listed, so their names are reported as "not found".

### 📁 Project Structure

```text
plugvan/
├── plugvan/todoist/        # FastMCP server for Claude Desktop (STDIO, python -m plugvan.todoist)
├── tests/                  # Pytest test suite (unit & integration tests)
├── pyproject.toml          # Package metadata and dependencies
└── .env.example            # Environment variable template
```

---

### 🚀 Getting Started

#### Install from the release (no clone)

Claude Desktop starts Plugvan from the release wheel; nothing needs to be cloned. Verified so far: Windows with Claude Desktop. CI also installs and tests the built wheel on Ubuntu and Windows. macOS and Linux with Claude Desktop have not been verified, so the steps below are for Windows.

**Option A: uvx (recommended)**

1. Install uv, which provides `uvx`: follow the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/), or on Windows run `winget install --id=astral-sh.uv -e`.
2. In a new terminal, find the full path of `uvx`:
```powershell
where uvx
```
   Claude Desktop does not use your shell's `PATH`, so `"command"` must be this full path.
3. In Claude Desktop, open **Settings ➔ Developer ➔ Edit Config**, which opens the folder with `claude_desktop_config.json`, and add the `todoist` server (if the file already has `mcpServers`, add the `todoist` entry inside it). Replace `C:\\path\\to\\uvx.exe` with the path from step 2, writing each `\` as `\\`, and `<your token>` with your Todoist API token:
```json
{
  "mcpServers": {
    "todoist": {
      "command": "C:\\path\\to\\uvx.exe",
      "args": [
        "--from",
        "https://github.com/kagankurubas/plugvan/releases/download/v0.1.0/plugvan_mcp-0.1.0-py3-none-any.whl",
        "plugvan-mcp",
        "todoist"
      ],
      "env": {
        "TODOIST_API_TOKEN": "<your token>"
      }
    }
  }
}
```
4. Restart Claude Desktop.

**Option B: pip into a virtual environment**

This install was verified from the Windows terminal; starting it from Claude Desktop with the config below has not been verified yet.
```powershell
python -m venv C:\path\to\plugvan-venv
C:\path\to\plugvan-venv\Scripts\python.exe -m pip install https://github.com/kagankurubas/plugvan/releases/download/v0.1.0/plugvan_mcp-0.1.0-py3-none-any.whl
```
Then use the venv's `plugvan-mcp.exe` as `"command"` (again with `\\` in JSON):
```json
{
  "mcpServers": {
    "todoist": {
      "command": "C:\\path\\to\\plugvan-venv\\Scripts\\plugvan-mcp.exe",
      "args": ["todoist"],
      "env": {
        "TODOIST_API_TOKEN": "<your token>"
      }
    }
  }
}
```

**Check the install (optional)**
```powershell
C:\path\to\uvx.exe --from https://github.com/kagankurubas/plugvan/releases/download/v0.1.0/plugvan_mcp-0.1.0-py3-none-any.whl plugvan-mcp --version
C:\path\to\plugvan-venv\Scripts\plugvan-mcp.exe --version
```
Each prints `plugvan-mcp <version>`, for example `plugvan-mcp 0.1.0`.

**Configuration and security**
- `TODOIST_API_TOKEN` (required) goes in the config's `env` block: in [Todoist Web](https://todoist.com) ➔ Settings ➔ **Integrations** ➔ **Developer**, copy your API token. For Turkish tool results, add `"PLUGVAN_LANG": "tr"` to the same block (`en` is the default).
- The installed `plugvan-mcp` command does not read a `.env` file; only `python -m plugvan.todoist` in a clone does.

> [!CAUTION]
> The token in the `env` block is stored in plain text in `claude_desktop_config.json`, which is no better and no worse than a `.env` file. Keep that file private: do not share it or commit it to a repository.

#### Run from a clone (contributors)

For development, or to run the server from a source checkout, follow steps 1–3 below and Method 1 under Usage Methods.

#### 1. Clone the Repository
```bash
git clone https://github.com/kagankurubas/plugvan.git
cd plugvan
```

#### 2. Create Virtual Environment & Install Dependencies
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# Install required packages
pip install -e ".[test]"
```

#### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit your `.env` file with your own credentials:
```env
TODOIST_API_TOKEN=your_todoist_api_token_here
# Optional: PLUGVAN_LANG=tr
```

**How to obtain your credentials:**
- **`TODOIST_API_TOKEN`**: Log into [Todoist Web](https://todoist.com) ➔ Settings ➔ **Integrations** ➔ **Developer** ➔ Copy your API token.
- **`PLUGVAN_LANG`** (optional): the language of tool results, `en` (default) or `tr` for Turkish.

> [!CAUTION]
> **🔒 Security Considerations:**
> - **Secret Management:** Keep `.env` private. It is pre-configured in `.gitignore` and must never be committed to Git.

---

### 🛠️ Usage Methods

#### Method 1: Claude Desktop (Model Context Protocol - MCP)
Integrate Todoist directly into your Claude Desktop application.

1. In Claude Desktop, open **Settings ➔ Developer ➔ Edit Config**.
2. Add the `todoist` server configuration (replace `<REPO_PATH>` with your project path):
```json
{
  "mcpServers": {
    "todoist": {
      "command": "<REPO_PATH>\\venv\\Scripts\\python.exe",
      "args": ["-m", "plugvan.todoist"],
      "env": {
        "PYTHONPATH": "<REPO_PATH>",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```
   For Turkish tool results, add `"PLUGVAN_LANG": "tr"` to the `env` block.
3. Restart Claude Desktop. You can now prompt Claude:
   - *"List my open tasks in Todoist for today."*
   - *"Create a p2 task 'Prepare weekly report' due tomorrow at 14:00."*
   - *"Complete task ID 6hM2..."*

---

<a name="türkçe"></a>
## 🇹🇷 Türkçe

Plugvan, temelde yerel çalışan bir **Model Context Protocol (MCP)** sunucusudur: Claude Desktop onu alt süreç olarak başlatır ve STDIO üzerinden konuşur; web sunucusu veya deploy gerekmez. Yapay zeka asistanının Todoist'i sohbet üzerinden yönetmesini sağlar.

### 🌟 Öne Çıkan Özellikler

- **🤖 Model Context Protocol (MCP) Sunucusu (`plugvan.todoist`):** Claude Desktop için FastMCP mimarisiyle yerel STDIO üzerinden çalışan kapsamlı Todoist yönetim araç seti:
  - **Görev Yönetimi:** `create_task` (parent_id ile alt görev, deadline_date ile son teslim tarihi), `get_task`, `list_tasks`, `complete_task`, `reopen_task`, `update_task` (proje/bölüm/üst görev taşıma, deadline güncelleme), `delete_task`
  - **Bölüm / Kanban Listeleri:** `create_section`, `list_sections`, `update_section`, `delete_section`
  - **Etiketler:** `list_labels`, `create_label`, `update_label`, `delete_label`
  - **Yorumlar & Notlar:** `add_comment`, `get_comments`
  - **Projeler & Hiyerarşi:** `create_project` (alt proje / parent_id), `get_project`, `update_project`, `delete_project`, `list_projects` (ağaç görünümü)
- **🎯 Akıllı İsim Eşleme:** Proje, bölüm ve etiket isimlerini büyük/küçük harf duyarsız ve Türkçe karakter uyumlu olarak Todoist ID'lerine eşler.
  - **MCP tool'ları:**
    - Bilinmeyen isim hata döndürür ve hiçbir şey yazılmaz.
    - Birden fazla eşleşmede en fazla 5 aday `isim (ID)` olarak listelenir.
    - Yıkıcı tool'lar (`delete_project`, `update_project`, `delete_section`, `update_section`, `delete_label`, `update_label`) yalnızca ID veya tam isim kabul eder.
    - `create_task`, `update_task`, `create_project` (üst proje), `create_section` ve `list_sections` yalnızca tek bir projeyle kısmi eşleşen bir proje adını da kabul eder; mesajlar projenin gerçek adını gösterir.
    - Bölümler yalnızca ID veya tam isimle, çözümlenen projenin içinde aranır.
    - `Inbox` / `Gelen Kutusu` her zaman Gelen Kutusu'na çözümlenir.
- **📏 İsim limitleri (MCP tool'ları):**
  - Proje adı: en fazla 120 karakter.
  - Etiket adı: en fazla 60 karakter.
  - Bölüm adı: burada en fazla 120 karakter. Todoist 2.048 karaktere izin verdiği için (Ekim 2026 itibarıyla) daha uzun isimli bir bölüme yalnızca ID ile ulaşılabilir.
  - Kullanabileceğiniz proje sayısı Todoist planınıza göre değişir. Güncel limitler için Todoist'in resmi [Usage limits in Todoist](https://www.todoist.com/help/todoist/get-started/usage-limits-in-todoist-e5rcSY) sayfasına bakın.
  - İsim araması yalnızca aktif projeleriniz içinde yapılır.
  - Arşivlenmiş projeler listelenmediği için isimleri "bulunamadı" sayılır.

### 📁 Proje Yapısı

```text
plugvan/
├── plugvan/todoist/        # Claude Desktop için FastMCP sunucusu (STDIO, python -m plugvan.todoist)
├── tests/                  # Pytest test paketi (birim ve entegrasyon testleri)
├── pyproject.toml          # Paket bilgileri ve bağımlılıklar
└── .env.example            # Çevre değişkeni şablonu
```

---

### 🚀 Kurulum ve Başlangıç

#### Sürümden kurulum (klonlamadan)

Claude Desktop, Plugvan'ı sürümdeki wheel dosyasından başlatır; depoyu klonlamanız gerekmez. Şu ana kadar doğrulanan: Claude Desktop ile Windows. CI ayrıca derlenen wheel'i Ubuntu ve Windows'ta kurup test eder. Claude Desktop ile macOS ve Linux doğrulanmadı; bu yüzden aşağıdaki adımlar Windows içindir.

**A seçeneği: uvx (önerilen)**

1. `uvx`'i sağlayan uv'yi kurun: [resmi kurulum kılavuzunu](https://docs.astral.sh/uv/getting-started/installation/) izleyin ya da Windows'ta `winget install --id=astral-sh.uv -e` komutunu çalıştırın.
2. Yeni bir terminalde `uvx`'in tam yolunu bulun:
```powershell
where uvx
```
   Claude Desktop kabuğunuzun `PATH` değişkenini kullanmaz; bu yüzden `"command"` bu tam yol olmalıdır.
3. Claude Desktop'ta **Settings ➔ Developer ➔ Edit Config** ile `claude_desktop_config.json` dosyasının bulunduğu klasörü açın ve `todoist` sunucusunu ekleyin (dosyada zaten `mcpServers` varsa `todoist` girdisini onun içine ekleyin). `C:\\path\\to\\uvx.exe` yerine 2. adımdaki yolu (JSON'da her `\` işaretini `\\` olarak yazarak), `<your token>` yerine Todoist API token'ınızı yazın:
```json
{
  "mcpServers": {
    "todoist": {
      "command": "C:\\path\\to\\uvx.exe",
      "args": [
        "--from",
        "https://github.com/kagankurubas/plugvan/releases/download/v0.1.0/plugvan_mcp-0.1.0-py3-none-any.whl",
        "plugvan-mcp",
        "todoist"
      ],
      "env": {
        "TODOIST_API_TOKEN": "<your token>"
      }
    }
  }
}
```
4. Claude Desktop'ı tamamen kapatıp yeniden başlatın.

**B seçeneği: sanal ortama pip ile kurulum**

Bu kurulum Windows terminalinden doğrulandı; aşağıdaki yapılandırmayla Claude Desktop'tan başlatılması henüz doğrulanmadı.
```powershell
python -m venv C:\path\to\plugvan-venv
C:\path\to\plugvan-venv\Scripts\python.exe -m pip install https://github.com/kagankurubas/plugvan/releases/download/v0.1.0/plugvan_mcp-0.1.0-py3-none-any.whl
```
Ardından `"command"` olarak sanal ortamdaki `plugvan-mcp.exe` dosyasını kullanın (JSON'da yine `\\` ile):
```json
{
  "mcpServers": {
    "todoist": {
      "command": "C:\\path\\to\\plugvan-venv\\Scripts\\plugvan-mcp.exe",
      "args": ["todoist"],
      "env": {
        "TODOIST_API_TOKEN": "<your token>"
      }
    }
  }
}
```

**Kurulumu kontrol etme (isteğe bağlı)**
```powershell
C:\path\to\uvx.exe --from https://github.com/kagankurubas/plugvan/releases/download/v0.1.0/plugvan_mcp-0.1.0-py3-none-any.whl plugvan-mcp --version
C:\path\to\plugvan-venv\Scripts\plugvan-mcp.exe --version
```
Her ikisi de `plugvan-mcp <sürüm>` yazdırır, örneğin `plugvan-mcp 0.1.0`.

**Yapılandırma ve güvenlik**
- `TODOIST_API_TOKEN` (zorunlu) yapılandırmanın `env` bloğuna yazılır: [Todoist Web](https://todoist.com) ➔ Ayarlar ➔ **Entegrasyonlar** ➔ **Geliştirici** ➔ API belirtecinizi kopyalayın. Araç sonuçlarını Türkçe almak için aynı bloğa `"PLUGVAN_LANG": "tr"` ekleyin (varsayılan `en`).
- Kurulan `plugvan-mcp` komutu `.env` dosyasını okumaz; `.env` dosyasını yalnızca klondaki `python -m plugvan.todoist` okur.

> [!CAUTION]
> `env` bloğundaki token, `claude_desktop_config.json` içinde düz metin olarak saklanır; bu bir `.env` dosyasından ne daha iyi ne daha kötüdür. Bu dosyayı gizli tutun: kimseyle paylaşmayın ve bir depoya eklemeyin.

#### Klondan çalıştırma (geliştiriciler için)

Geliştirme için ya da sunucuyu kaynak kodundan çalıştırmak için aşağıdaki 1–3. adımları ve Kullanım Yöntemleri altındaki 1. Yöntem'i izleyin.

#### 1. Projeyi Klonlayın
```bash
git clone https://github.com/kagankurubas/plugvan.git
cd plugvan
```

#### 2. Sanal Ortam Oluşturun ve Paketleri Yükleyin
```bash
python -m venv venv

# Windows (PowerShell):
.\venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -e ".[test]"
```

#### 3. Çevre Değişkenlerini Yapılandırın
`.env.example` dosyasını `.env` olarak kopyalayın:
```bash
cp .env.example .env
```

`.env` dosyanızı açıp kendi token ve anahtarlarınızı girin:
```env
TODOIST_API_TOKEN=kendi_todoist_api_tokeniniz
# İsteğe bağlı: PLUGVAN_LANG=tr
```

**Anahtarlarınızı Alma:**
- **`TODOIST_API_TOKEN`**: [Todoist Web](https://todoist.com) ➔ Ayarlar ➔ **Entegrasyonlar** ➔ **Geliştirici** ➔ API belirtecinizi kopyalayın.
- **`PLUGVAN_LANG`** (isteğe bağlı): araç sonuçlarının dili; `en` (varsayılan) veya Türkçe için `tr`.

> [!CAUTION]
> **🔒 Güvenlik Uyarıları:**
> - **Gizli Anahtar Yönetimi:** `.env` dosyası `.gitignore`'da tanımlıdır; bu dosyayı asla Git deposuna eklemeyin ve kimseyle paylaşmayın.

---

### 🛠️ Kullanım Yöntemleri

#### 1. Yöntem: Claude Desktop ile Kullanım (MCP Sunucusu)
Claude Desktop uygulamanıza Todoist yeteneği kazandırmak için:

1. Claude Desktop'ta **Settings ➔ Developer ➔ Edit Config**'i açın.
2. Aşağıdaki yapılandırmayı ekleyin (`<REPO_PATH>` yerine kendi proje yolunuzu yazın):
```json
{
  "mcpServers": {
    "todoist": {
      "command": "<REPO_PATH>\\venv\\Scripts\\python.exe",
      "args": ["-m", "plugvan.todoist"],
      "env": {
        "PYTHONPATH": "<REPO_PATH>",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```
   Araç sonuçlarını Türkçe almak için `env` bloğuna `"PLUGVAN_LANG": "tr"` ekleyin.
3. Claude Desktop'ı tamamen kapatıp yeniden başlatın. Artık Claude ile sohbet ederken doğrudan Todoist'e görev ekleyebilir, görevlerinizi listeleyebilir veya tamamlayabilirsiniz:
   - *"Bugün için tanımlı Todoist görevlerimi listele."*
   - *"Yarın saat 15:00'e 'Proje Raporunu Teslim Et' başlıklı p2 görev ekle."*
   - *"ID'si 6hM2... olan görevi kapat."*

---

<a name="tests"></a>
## 🧪 Testing / Testleri Çalıştırma

Projede birim ve entegrasyon testleri yer almaktadır:

```bash
# Tüm testleri çalıştırmak için:
pytest

# Detaylı çıktı ile çalıştırmak için:
pytest -v
```

---

## 📄 License / Lisans

This project is licensed under the [MIT License](LICENSE).  
Bu proje [MIT Lisansı](LICENSE) kapsamında lisanslanmıştır.
