"""今日页的深色 QSS（R4）。占位符由 style.py 填值。"""

QSS_TODAY = """/* ---------- 今日页（R4） ---------- */

QDialog#TodayWindow {
    background: {{bg}};
    color: {{text}};
    font-size: {{fs_base}};
}
QWidget#TodayColumn, QWidget#TodayContent {
    background: transparent;
}
QLabel#TodayTitle {
    font-size: {{fs_lg}};
    font-weight: 600;
    color: {{text}};
}
QLabel#TodayDate {
    font-size: {{fs_sm}};
    color: {{text_faint}};
}
QWidget#HeroCard {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_lg}};
}
QLabel#Eyebrow {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#HeroTitle {
    font-size: 28px;
    font-weight: 700;
    color: {{text}};
}
QLabel#HeroSub {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}
QLabel#HeroBadge {
    color: {{text_dim}};
    background: {{surface_2}};
    border: 1px solid {{line}};
    border-radius: 11px;
    padding: 1px {{s2}};
    font-size: {{fs_xs}};
}
QWidget#HeroBadge {
    background: {{surface_2}};
    border: 1px solid {{line}};
    border-radius: 11px;
}
QWidget#HeroBadge[mark="true"] {
    background: {{mark_soft}};
    border-color: transparent;
}
QLabel#HeroBadgeText {
    background: transparent;
    color: {{text_dim}};
    font-size: {{fs_xs}};
}
QWidget#HeroBadge[mark="true"] QLabel#HeroBadgeText {
    color: {{mark}};
}
QLabel#GoalHead {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#GoalText {
    color: {{text}};
    font-size: {{fs_sm}};
    font-weight: 600;
}
QLabel#GoalNote {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QProgressBar#GoalBar {
    background: {{bg_sunken}};
    border: none;
    border-radius: 4px;
}
QProgressBar#GoalBar::chunk {
    background: {{accent}};
    border-radius: 4px;
}
QLabel#RingValue {
    color: {{text}};
    font-size: 22px;
    font-weight: 700;
}
QLabel#RingLabel {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}

QWidget#StatStrip {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_md}};
}
QWidget#StatSep {
    background: {{line}};
}
QLabel#StatLabel {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#StatValue {
    color: {{text}};
    font-size: {{fs_xl}};
    font-weight: 600;
}
QLabel#StatUnit {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}
QLabel#StatNote {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}

QWidget#ActionCard, QWidget#PluginCard {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_md}};
}
QWidget#ActionCard:hover, QWidget#PluginCard:hover {
    background: {{accent_soft}};
    border-color: {{accent_line}};
}
QWidget#ActionCard:focus, QWidget#PluginCard:focus {
    border-color: {{accent_line}};
}
QLabel#ActionNo {
    background: {{accent_soft}};
    color: {{accent_strong}};
    border-radius: 11px;
    font-size: {{fs_xs}};
    font-weight: 600;
}
QLabel#CardTitle {
    color: {{text}};
    font-size: {{fs_sm}};
    font-weight: 600;
}
QLabel#CardDetail {
    color: {{text_dim}};
    font-size: {{fs_xs}};
}
QLabel#CardLabel {
    color: {{accent_strong}};
    font-size: {{fs_xs}};
}
QLabel#PluginIcon {
    background: {{accent_soft}};
    color: {{accent_strong}};
    border-radius: {{r_sm}};
    font-size: 16px;
}
QLabel#PluginName {
    color: {{text}};
    font-size: {{fs_md}};
    font-weight: 600;
}
QLabel#PluginCat {
    color: {{text_faint}};
    border: 1px solid {{line}};
    border-radius: 9px;
    padding: 1px 7px;
    font-size: {{fs_xs}};
}
QWidget#PluginFoot {
    border: none;
    border-top: 1px solid {{line}};
}
QLabel#PluginCount {
    color: {{text_dim}};
    font-size: {{fs_xs}};
}
QLabel#PluginOpen {
    color: {{accent_strong}};
    font-size: {{fs_xs}};
}
QLabel#Empty {
    color: {{text_faint}};
    font-size: {{fs_sm}};
    padding: {{s4}};
}
QWidget#Banner {
    background: {{accent_soft}};
    border: 1px solid {{accent_line}};
    border-radius: {{r_sm}};
}
QLabel#BannerText {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}

/* ---------- R5：底栏时间线与侧栏面板 ---------- */

QWidget#TodayBottom, QWidget#TodaySide {
    background: transparent;
}
QLabel#EmptyState {
    color: {{text_faint}};
    font-size: {{fs_sm}};
    padding: {{s4}} 0;
}
QWidget#TimelineItem {
    background: transparent;
    border-radius: {{r_sm}};
}
QWidget#TimelineItem:hover {
    background: {{bg_raised}};
}
QWidget#TimelineItem:focus {
    border: 1px solid {{accent_line}};
}
QLabel#TimelineTime {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#TimelineQ {
    color: {{text}};
    font-size: {{fs_base}};
}
QLabel#TimelineA {
    color: {{text_faint}};
    font-size: {{fs_sm}};
}
QLabel#TimelineTag {
    color: {{text_faint}};
    border: 1px solid {{line}};
    border-radius: 4px;
    padding: 0 5px;
    font-size: 10px;
}
QWidget#InfoPanel {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_md}};
}
QWidget#PanelHead {
    background: transparent;
    border: none;
    border-bottom: 1px solid {{line}};
}
QLabel#PanelTitle {
    color: {{text_dim}};
    font-size: {{fs_sm}};
    font-weight: 600;
}
QLabel#PanelHint {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QWidget#PanelBody {
    background: transparent;
}
QWidget#PanelRow {
    background: transparent;
    border-radius: {{r_sm}};
}
QWidget#PanelRow[clickable="true"]:hover {
    background: {{accent_soft}};
}
QWidget#PanelRow:focus {
    border: 1px solid {{accent_line}};
}
QLabel#PanelRowLabel {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}
QLabel#PanelRowValue {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QFrame#PanelSep {
    background: {{line}};
    border: none;
}
QLabel#PanelNote {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QWidget#AchRow {
    background: transparent;
    border-radius: {{r_sm}};
}
QWidget#AchRow[earned="true"] {
    background: {{mark_soft}};
}
QLabel#AchDot {
    color: {{mark}};
    font-size: {{fs_xs}};
}
QWidget#AchRow[earned="false"] QLabel#AchDot {
    color: {{text_faint}};
}
QLabel#AchName {
    color: {{text}};
    font-size: {{fs_xs}};
}
QWidget#AchRow[earned="false"] QLabel#AchName {
    color: {{text_dim}};
}
QLabel#AchProgress {
    color: {{text_faint}};
    font-size: 11px;
}
QWidget#Shortcut {
    background: transparent;
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
}
QWidget#Shortcut:hover {
    border-color: {{line_strong}};
    background: {{bg_raised}};
}
QWidget#Shortcut:focus {
    border-color: {{accent_line}};
}
QLabel#ShortcutText {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}
QLabel#ShortcutHint {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
"""
