"""试点窗口的中性 QSS。

先功能后视觉：不追 Web 主题，只要字号、间距、状态色舒服。
"""

QSS = """
QDialog#SettingsWindow {
    background: #f5f6fa;
}
QLabel#PageTitle {
    font-size: 18px;
    font-weight: 600;
    color: #1c2333;
}
QLabel#SectionTitle {
    font-size: 15px;
    font-weight: 600;
    color: #1c2333;
}
QLabel#FieldLabel {
    color: #2b3242;
    font-size: 13px;
}
QLabel#Hint {
    color: #6b7280;
    font-size: 12px;
}
QLabel#Small {
    color: #9aa1ad;
    font-size: 11px;
}
QLabel#Status[state="info"] {
    color: #4b5563;
}
QLabel#Status[state="ok"] {
    color: #0f7b3f;
}
QLabel#Status[state="err"] {
    color: #b42318;
}
QWidget#Section {
    background: #ffffff;
    border: 1px solid #e3e6ee;
    border-radius: 8px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #cfd5e3;
    border-radius: 5px;
    padding: 5px 8px;
    min-height: 22px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #5b7cfa;
}
QLineEdit:read-only {
    background: #f1f3f8;
    color: #6b7280;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #cfd5e3;
    border-radius: 5px;
    padding: 5px 12px;
}
QPushButton:hover {
    border-color: #5b7cfa;
}
QPushButton:disabled {
    color: #9aa1ad;
    background: #f1f3f8;
}
QPushButton#Primary {
    background: #3f5bd8;
    border-color: #3f5bd8;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#Primary:disabled {
    background: #aab4e5;
    border-color: #aab4e5;
}
"""
