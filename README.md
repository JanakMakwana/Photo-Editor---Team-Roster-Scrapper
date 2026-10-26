# ⚡ VeloRoster AI — Athletic Roster & Headshot Studio

**Proprietary Commercial Software engineered and built from scratch by Ecstaticloud Technologies.**  
*Full commercial rights owned exclusively by Ecstaticloud Technologies.*

An interactive web studio and automated portrait processing system for:
1. **Multi-Source Athletic Roster Ingestion**: Scrapes athletic roster URLs (Sidearm Sports, NCAA, NHL, BCHL / HockeyTech, etc.) with automatic high-resolution URL quality boosting (`width=1200+`), standardizing down to crisp `width=800` portraits.
2. **Direct Athlete & Stint Search Engine**: Multi-tier search (HockeyTech/LeagueStat, NHL, Wikidata, and Wikimedia) with strict athlete name validation and instant portrait resolution.
3. **Custom Athletic ID Assignment**: Visual table UI with inline editing, bulk spreadsheet paste, and real-time filename previews.
4. **Interactive 180×180 Portrait Studio**: Pan, zoom, auto-align with MediaPipe face detection, AI background cutout (`rembg`), and precision retouch brushes (Recover / Erase).
5. **Standardized Transparent Headshots**: One-click batch processing and ZIP export of 180×180 transparent PNGs formatted by player number, ready for team rosters, video analyzers, and broadcast graphics.

---

## 🚀 Deploy to Render (Cloud Hosting)

You can host **VeloRoster AI** on the web using [Render](https://render.com).

### Method A: Connect Repository as a Web Service (Quickest)

1. Sign in to your dashboard on [Render](https://dashboard.render.com).
2. Click **New +** > **Web Service**.
3. Choose **Build and deploy from a Git repository**.
4. Connect and select your repository.
5. Configure the service settings:
   - **Name**: `veloroster-ai`
   - **Language / Runtime**: `Python`
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python studio.py`
   - **Instance Type**: `Free` (or Starter for faster AI processing)
6. Add the following **Environment Variable** under *Advanced*:
   - Key: `PYTHON_VERSION`
   - Value: `3.11.9`
7. Click **Create Web Service**. Render will install the dependencies and deploy your web app. Once complete, your live URL will be active (e.g. `https://veloroster-ai.onrender.com`).

---

### Method B: Render Blueprint (Infrastructure-as-Code)

This repository includes a `render.yaml` Blueprint file.
1. In the Render Dashboard, click **New +** > **Blueprint**.
2. Select this repository.
3. Render will automatically detect `render.yaml` and configure the Python 3.11.9 environment, build command, and start command with zero manual entry.
4. Click **Apply**.

---

## 💻 Running Locally

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch Studio Server
```bash
python studio.py
```
Open **[http://localhost:8080](http://localhost:8080)** in your browser.

---

## ✨ Studio Features

- **📥 Roster Photo Downloader & Number Assigner**:
  - Automatically replaces thumbnail constraints with maximum resolution before fetching.
  - Interactive table: assign numbers, copy/paste from spreadsheets, or use player names.
  - One-click ZIP download of all raw portraits.
- **📂 One-Click Team Folder Selection**:
  - Automatically detects team photo folders with photo counts.
- **🖐️ Freeform 180×180 Framing & Positioning**:
  - Pan & zoom smoothly with live square framing guide.
  - MediaPipe short-range face detection for instant centering.
- **✨ AI Cutout & Retouch Brushes**:
  - AI background removal via `rembg`.
  - **Recover Brush**: Paint over fine hair, jerseys, or collars to bring back original details.
  - **Erase Brush**: Clean up any background halos.
- **📦 Cloud ZIP Export**:
  - Download all edited transparent PNG headshots in a single `.zip` file from anywhere.

---

&copy; 2026 Ecstaticloud Technologies. All rights reserved.  
*VeloRoster AI™ is proprietary commercial software developed and owned by Ecstaticloud Technologies.*
