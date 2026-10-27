"""设置页与通用控件的深色 QSS（R3.10）。占位符由 style.py 填值。"""

QSS_COMMON = """
* {
    font-family: "{{font_family}}";
}
QDialog#SettingsWindow {
    background: {{bg}};
    color: {{text}};
    font-size: {{fs_base}};
}
QWidget#SettingsColumn, QWidget#SettingsContent {
    background: transparent;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget#qt_scrollarea_viewport {
    background: transparent;
}

QLabel {
    background: transparent;
    color: {{text}};
}
QLabel#PageTitle {
    font-size: {{fs_lg}};
    font-weight: 600;
    color: {{text}};
}
QLabel#SectionTitle {
    font-size: {{fs_md}};
    font-weight: 600;
    color: {{text}};
}
QLabel#FieldLabel {
    font-size: {{fs_sm}};
    color: {{text_dim}};
}
QLabel#Hint {
    font-size: {{fs_xs}};
    color: {{text_faint}};
}
QLabel#Small {
    font-size: {{fs_xs}};
    color: {{text_faint}};
}
QLabel#Status {
    font-size: {{fs_sm}};
    color: {{text_faint}};
}
QLabel#Status[state="info"] { color: {{text_faint}}; }
QLabel#Status[state="ok"]   { color: {{ok}}; }
QLabel#Status[state="err"]  { color: {{err}}; }

QWidget#Section {
    background: {{bg_raised}};
    border: 1px solid {{line}};
    border-radius: {{r_md}};
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: {{bg_input}};
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
    padding: {{s1}} {{s3}};
    min-height: 26px;
    color: {{text}};
    font-size: {{fs_sm}};
    selection-background-color: {{accent}};
    selection-color: {{on_accent}};
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: {{line_strong}};
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: {{accent_line}};
}
QLineEdit:read-only {
    background: {{bg_sunken}};
    color: {{text_faint}};
    border-color: {{line}};
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: {{bg_sunken}};
    color: {{text_faint}};
    border-color: {{line}};
}

QComboBox {
    padding-right: 28px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 24px;
    border: none;
    border-left: 1px solid {{line}};
    background: transparent;
}
QComboBox::down-arrow {
    image: url("{{arrow_icon}}");
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background: {{bg_raised}};
    color: {{text}};
    font-size: {{fs_sm}};
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
    padding: {{s1}};
    outline: 0;
    selection-background-color: {{accent_soft}};
    selection-color: {{text}};
}
QComboBox QAbstractItemView::item {
    padding: {{s1}} {{s2}};
    min-height: 24px;
}
QComboBox QAbstractItemView::item:selected {
    background: {{accent_soft}};
    color: {{text}};
}

QPushButton {
    background: transparent;
    border: 1px solid {{line_strong}};
    border-radius: {{r_sm}};
    color: {{text_dim}};
    padding: {{s1}} {{s3}};
    min-height: 24px;
    font-size: {{fs_sm}};
}
QPushButton:hover {
    background: {{bg_raised}};
    color: {{text}};
}
QPushButton:pressed {
    background: {{bg_input}};
}
QPushButton:focus {
    border-color: {{accent_line}};
}
QPushButton:disabled {
    background: {{bg_sunken}};
    border-color: {{line}};
    color: {{text_faint}};
}
QPushButton#Primary {
    background: {{accent}};
    border-color: {{accent}};
    color: {{on_accent}};
    font-weight: 600;
}
QPushButton#Primary:hover {
    background: {{accent_strong}};
    border-color: {{accent_strong}};
}
QPushButton#Primary:pressed {
    background: {{accent}};
}
QPushButton#Primary:disabled {
    background: {{bg_sunken}};
    border-color: {{line}};
    color: {{text_faint}};
}
QPushButton#Quiet {
    background: transparent;
    border-color: transparent;
    color: {{text_faint}};
    font-size: {{fs_xs}};
    padding: {{s1}} {{s2}};
}
QPushButton#Quiet:hover {
    background: {{bg_raised}};
    border-color: {{line_strong}};
    color: {{text}};
}
QPushButton#Danger {
    background: transparent;
    border: 1px solid rgba(227, 123, 123, 0.35);
    color: {{err}};
    font-size: {{fs_xs}};
    padding: {{s1}} {{s2}};
}
QPushButton#Danger:hover {
    background: {{err_soft}};
}

QCheckBox {
    background: transparent;
    color: {{text_dim}};
    font-size: {{fs_sm}};
    spacing: {{s2}};
}
QCheckBox:hover { color: {{text}}; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid {{line}};
    border-radius: 4px;
    background: {{bg_input}};
}
QCheckBox::indicator:hover { border-color: {{line_strong}}; }
QCheckBox::indicator:checked {
    background: {{accent}};
    border-color: {{accent}};
    image: url("{{check_icon}}");
}
QCheckBox::indicator:checked:hover {
    background: {{accent_strong}};
    border-color: {{accent_strong}};
}
QCheckBox::indicator:disabled {
    background: {{bg_sunken}};
    border-color: {{line}};
}

QListWidget {
    background: {{bg_sunken}};
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
    padding: {{s1}};
    color: {{text}};
    outline: 0;
}
QListWidget::item {
    border-bottom: 1px solid {{line}};
    padding: {{s1}};
}
QListWidget::item:selected {
    background: {{accent_soft}};
    color: {{text}};
}

QTableWidget {
    background: {{bg_sunken}};
    alternate-background-color: {{bg_sunken}};
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
    color: {{text}};
    gridline-color: {{line}};
    outline: 0;
}
QTableWidget::item {
    padding: {{s1}};
}
QTableWidget::item:selected {
    background: {{accent_soft}};
    color: {{text}};
}
QHeaderView::section {
    background: {{bg_raised}};
    color: {{text_muted}};
    border: 0;
    border-bottom: 1px solid {{line}};
    padding: {{s1}};
}
QTableCornerButton::section {
    background: {{bg_raised}};
    border: 0;
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: {{line_strong}};
    border-radius: 4px;
    min-height: 28px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: {{text_faint}}; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: {{line_strong}};
    border-radius: 4px;
    min-width: 28px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: {{text_faint}}; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QToolTip {
    background: {{bg_raised}};
    color: {{text}};
    border: 1px solid {{line}};
    padding: {{s1}} {{s2}};
    font-size: {{fs_xs}};
}

"""
