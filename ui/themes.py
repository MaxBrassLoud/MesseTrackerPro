"""Theme-Definitionen für Desktop (QSS) und Web (CSS-Variablen)."""

THEMES = {
    "Flipper": {
        "name": "Flipper",
        "bg_main": "#000000",
        "bg_panel": "#111111",
        "bg_input": "#1a1a1a",
        "fg_text": "#eeeeee",
        "fg_muted": "#aaaaaa",
        "accent": "#FF8200",
        "accent_hover": "#ffa040",
        "accent_fg": "#000000",
        "border": "#333333",
        "border_strong": "#FF8200",
    },
    "Nachtblau": {
        "name": "Nachtblau",
        "bg_main": "#0a0e27",
        "bg_panel": "#131a3a",
        "bg_input": "#1a2347",
        "fg_text": "#e0e8ff",
        "fg_muted": "#8a9bcc",
        "accent": "#4A9EFF",
        "accent_hover": "#6db4ff",
        "accent_fg": "#000000",
        "border": "#2a3555",
        "border_strong": "#4A9EFF",
    },
    "Wald": {
        "name": "Wald",
        "bg_main": "#0d1f0d",
        "bg_panel": "#16291a",
        "bg_input": "#1f3524",
        "fg_text": "#e0f0e0",
        "fg_muted": "#8fa890",
        "accent": "#4CAF50",
        "accent_hover": "#6cc770",
        "accent_fg": "#000000",
        "border": "#2a402c",
        "border_strong": "#4CAF50",
    },
    "Hell": {
        "name": "Hell",
        "bg_main": "#f5f5f5",
        "bg_panel": "#ffffff",
        "bg_input": "#f0f0f0",
        "fg_text": "#222222",
        "fg_muted": "#666666",
        "accent": "#FF8200",
        "accent_hover": "#e67500",
        "accent_fg": "#ffffff",
        "border": "#dddddd",
        "border_strong": "#FF8200",
    },
    "Violett": {
        "name": "Violett",
        "bg_main": "#1a0f2e",
        "bg_panel": "#241540",
        "bg_input": "#2e1c50",
        "fg_text": "#ede0ff",
        "fg_muted": "#a896c8",
        "accent": "#a855f7",
        "accent_hover": "#bc75ff",
        "accent_fg": "#ffffff",
        "border": "#3d2a5c",
        "border_strong": "#a855f7",
    },
}


def get_theme(name):
    return THEMES.get(name, THEMES["Flipper"])


QSS_TEMPLATE = """
QWidget {
    background: %(bg_panel)s;
    color: %(fg_text)s;
    font-family: 'Segoe UI', Arial;
    font-size: 10pt;
}
QMainWindow { background: %(bg_main)s; }
#Sidebar { background: %(bg_main)s; border-right: 2px solid %(accent)s; }
#Sidebar QPushButton {
    background: %(bg_main)s;
    color: %(fg_text)s;
    border: 0;
    padding: 14px 18px;
    text-align: left;
    border-left: 4px solid transparent;
}
#Sidebar QPushButton:hover { background: %(bg_input)s; }
#Sidebar QPushButton:checked {
    background: %(bg_input)s;
    border-left: 4px solid %(accent)s;
    color: %(accent)s;
}
QPushButton {
    background: %(accent)s;
    color: %(accent_fg)s;
    border: 0;
    padding: 8px 14px;
    border-radius: 6px;
    font-weight: 600;
}
QPushButton:hover { background: %(accent_hover)s; }
QPushButton:disabled { background: %(border)s; color: %(fg_muted)s; }
QPushButton#Ghost { background: %(bg_input)s; color: %(fg_text)s; }
QPushButton#Ghost:hover { background: %(border)s; }
QLineEdit, QComboBox, QTextEdit, QSpinBox, QDateEdit {
    background: %(bg_input)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
    padding: 6px;
    color: %(fg_text)s;
}
QComboBox QAbstractItemView {
    background: %(bg_input)s;
    color: %(fg_text)s;
    selection-background-color: %(accent)s;
    selection-color: %(accent_fg)s;
}
QTableWidget {
    background: %(bg_panel)s;
    gridline-color: %(border)s;
    color: %(fg_text)s;
    alternate-background-color: %(bg_input)s;
}
QHeaderView::section {
    background: %(bg_input)s;
    color: %(accent)s;
    padding: 6px;
    border: 0;
    font-weight: 600;
}
QGroupBox {
    border: 1px solid %(border)s;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: %(accent)s;
    font-weight: 600;
}
QTabWidget::pane { border: 1px solid %(border)s; }
QTabBar::tab {
    background: %(bg_input)s;
    color: %(fg_text)s;
    padding: 8px 14px;
    border: 1px solid %(border)s;
}
QTabBar::tab:selected { background: %(accent)s; color: %(accent_fg)s; }
QLabel#Title { font-size: 18pt; color: %(accent)s; font-weight: 700; }
QLabel#Sub { color: %(fg_muted)s; }
QLabel#Stat { font-size: 22pt; color: %(accent)s; font-weight: 700; }
QLabel#Hint { color: %(fg_muted)s; }
QScrollBar:vertical { background: %(bg_main)s; width: 12px; }
QScrollBar::handle:vertical {
    background: %(border)s;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QSplitter::handle { background: %(border)s; }
QStatusBar { background: %(bg_main)s; color: %(fg_muted)s; }
QDialog { background: %(bg_panel)s; }
"""


def build_qss(theme: dict) -> str:
    return QSS_TEMPLATE % theme


WEB_CSS_TEMPLATE = """
:root {
    --bg-main: %(bg_main)s;
    --bg-panel: %(bg_panel)s;
    --bg-input: %(bg_input)s;
    --fg-text: %(fg_text)s;
    --fg-muted: %(fg_muted)s;
    --accent: %(accent)s;
    --accent-hover: %(accent_hover)s;
    --accent-fg: %(accent_fg)s;
    --border: %(border)s;
    --success-bg: #063;
    --success-fg: #fff;
    --danger-bg: #a30;
    --danger-fg: #fff;
    --warning-bg: #430;
    --warning-fg: #fc9;
    --info-bg: #0a2a3a;
    --info-border: #0a4a5a;
    --info-fg: #9fd;
}
*{box-sizing:border-box}
body{font-family:-apple-system,system-ui,'Segoe UI',Arial,sans-serif;
     background:var(--bg-main);color:var(--fg-text);margin:0;min-height:100vh}
header{background:var(--bg-main);border-bottom:2px solid var(--accent);
       padding:14px 16px;position:sticky;top:0;z-index:10}
header h1{color:var(--accent);font-size:1.2em;margin:0;letter-spacing:.5px}
header .emp{color:var(--fg-muted);font-size:.9em;margin-top:4px}
header .emp b{color:var(--accent)}
main{padding:16px;max-width:640px;margin:0 auto}
h3{color:var(--fg-text);font-size:1em;margin:0 0 10px}
.card{background:var(--bg-panel);border:1px solid var(--border);
      border-radius:12px;padding:16px;margin:10px 0}
.info{background:var(--info-bg);border-color:var(--info-border);color:var(--info-fg)}
button,input[type=submit]{background:var(--accent);color:var(--accent-fg);
  border:0;padding:14px 16px;border-radius:10px;font-weight:700;width:100%%;
  margin-top:10px;font-size:1em;cursor:pointer}
button:active,input[type=submit]:active{background:var(--accent-hover)}
button.alt{background:var(--bg-input);color:var(--fg-text);border:1px solid var(--border)}
input,select,textarea{width:100%%;padding:12px;margin:6px 0;
  border-radius:8px;border:1px solid var(--border);background:var(--bg-input);
  color:var(--fg-text);font-size:1em;font-family:inherit}
textarea{min-height:70px;resize:vertical}
.ok{background:var(--success-bg);color:var(--success-fg);
    padding:14px;border-radius:10px;margin:10px 0;font-weight:600}
.err{background:var(--danger-bg);color:var(--danger-fg);
     padding:14px;border-radius:10px;margin:10px 0}
.warn{background:var(--warning-bg);color:var(--warning-fg);
      padding:14px;border-radius:10px;margin:10px 0}
.status{padding:14px;border-radius:10px;margin-bottom:12px;font-size:1.05em}
.status-on{background:var(--success-bg);border:1px solid #0a8;color:var(--success-fg)}
.status-off{background:var(--bg-input);border:1px solid var(--border)}
.status small{color:var(--fg-muted)}
.link{color:var(--accent);text-decoration:none;font-weight:600}
small{color:var(--fg-muted)}
"""


def build_web_css(theme: dict) -> str:
    return WEB_CSS_TEMPLATE % theme