# Is This News Real? — Browser Extension

Chrome extension that connects to your FastAPI backend and fact-checks
images, articles, and text claims directly from the browser.

---

## Setup

### 1. Generate icons
```bash
cd extension
pip install Pillow
python generate_icons.py
```

### 2. Load in Chrome
1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select this `extension/` folder

The extension icon appears in your toolbar.

---

## Usage

### Right-click on an image
Right-click any image on any webpage → "Fact-check this image"

### Right-click on selected text
Select any text → right-click → "Fact-check selected text"

### Right-click on a page
Right-click anywhere → "Fact-check this page"

### Manual input
Click the extension icon → paste any URL or text claim → click Check

---

## Requirements

Backend must be running:
```bash
docker start searxng
conda activate your_env
python main.py
```

---

## File Structure

```
extension/
├── manifest.json      ← Chrome extension config
├── background.js      ← Service worker, context menus, API calls
├── sidepanel.html     ← UI panel shown on the right side
├── sidepanel.js       ← Live agent progress, polling, verdict display
├── generate_icons.py  ← Run once to create icons
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```
