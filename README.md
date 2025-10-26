<img width="1396" height="649" alt="Screenshot 2025-10-26 090313" src="https://github.com/user-attachments/assets/5d51ef79-0c73-49e9-86d5-d11b478e9d28" />

# ModZT2 - Mod Manager for Zoo Tycoon 2

**ModZT2** is a mod manager and launcher for *Zoo Tycoon 2*, built with **Python** and **ttkbootstrap**.  
It features threaded background tasks, automatic path detection, persistent settings, and a database for mods and bundles.

---

Features of the mod manager include:
  - Add, enable/disable, remove mods
  - Track mod folders and load order
  - Detect and resolve file conflicts

  - Group mods into named bundles
  - Export/import loadouts easily

  - Auto-detect Zoo Tycoon 2 in common installation paths
  - Persistent settings
  - Theme and window size saved between sessions

  - Threaded background tasks with progress bar
  - Live action log and recent actions list
  - Dark/light themes with one click - Alpha

---

## Building

### Requirements
- Python **3.10+**
- Dependencies:
  ```bash
  pip install ttkbootstrap

### Run
python modzt2.py

### Build
pyinstaller --onefile --noconsole --icon=assets/icon.ico modzt2.py

## Notice
ModZT2 is an alpha program, but I run it with my game install with no problems. If you run into any bugs, please report them on Github Issues!

This project is not affiliated with Microsoft, Xbox Game Studios, or Blue Fang Games.

---

## License

```text
MIT License

Copyright (c) 2025 Kael

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.






