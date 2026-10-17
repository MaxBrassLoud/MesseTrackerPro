STYLESHEET = """
QWidget { background:#111; color:#eee; font-family: 'Segoe UI', Arial; font-size: 10pt; }
QMainWindow { background:#000; }
#Sidebar { background:#000; border-right: 2px solid #FF8200; }
#Sidebar QPushButton {
    background:#000; color:#eee; border:0; padding:14px 18px; text-align:left;
    border-left: 4px solid transparent;
}
#Sidebar QPushButton:hover { background:#1a1a1a; }
#Sidebar QPushButton:checked { background:#1a1a1a; border-left: 4px solid #FF8200; color:#FF8200; }
QPushButton { background:#FF8200; color:#000; border:0; padding:8px 14px; border-radius:6px; font-weight:600; }
QPushButton:hover { background:#ffa040; }
QPushButton#Ghost { background:#222; color:#eee; }
QLineEdit, QComboBox, QTextEdit, QSpinBox, QDateEdit {
    background:#1a1a1a; border:1px solid #333; border-radius:6px; padding:6px;
}
QTableWidget { background:#0d0d0d; gridline-color:#222; }
QHeaderView::section { background:#1a1a1a; color:#FF8200; padding:6px; border:0; }
QGroupBox { border:1px solid #333; border-radius:8px; margin-top:12px; }
QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; color:#FF8200; }
QTabWidget::pane { border:1px solid #333; }
QLabel#Title { font-size: 18pt; color:#FF8200; font-weight:700; }
QLabel#Sub { color:#aaa; }
QLabel#Stat { font-size: 22pt; color:#FF8200; font-weight:700; }
"""