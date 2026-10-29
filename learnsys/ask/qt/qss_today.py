"""今日页的 QSS。占位符由 style.py 从 tokens.css 填值。"""

QSS_TODAY = """/* ---------- 今日页（2026-10-28 改版） ---------- */

QDialog#TodayWindow {
    background: {{bg}};
    color: {{text}};
    font-size: {{fs_base}};
}
QWidget#TodayColumn, QWidget#TodayContent,
QWidget#TodayBottom, QWidget#TodaySide, QWidget#TodayLeft {
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

/* ---------- Hero ---------- */
QWidget#HeroCard {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_lg}};
}
QLabel#HeroTitle {
    font-size: 30px;
    font-weight: 700;
    color: {{text}};
}
QLabel#HeroBadge {
    color: {{text_dim}};
    background: {{surface_2}};
    border-radius: 11px;
    padding: 2px 9px;
    font-size: {{fs_xs}};
}
QLabel#HeroBadgeMark {
    color: {{mark}};
    background: {{mark_soft}};
    border-radius: 11px;
    padding: 2px 9px;
    font-size: {{fs_xs}};
}
QLabel#HeroState {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}
QWidget#GoalTask {
    background: {{surface_2}};
    border: 1px solid {{line}};
    border-radius: 10px;
}
QWidget#GoalTask:hover {
    border-color: {{accent_line}};
}
QWidget#GoalTask:focus {
    border: 1px solid {{accent_line}};
}
QLabel#GoalCheck {
    color: {{text_faint}};
    font-size: {{fs_sm}};
}
QWidget#GoalTask[done="true"] QLabel#GoalCheck {
    color: {{accent}};
}
QLabel#GoalTaskTitle {
    color: {{text}};
    font-size: {{fs_sm}};
    font-weight: 600;
}
QWidget#GoalTask[done="true"] QLabel#GoalTaskTitle {
    color: {{text_faint}};
}
QLabel#GoalTaskDetail {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#GoalTaskMin {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#GoalTaskGo {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QWidget#HeroAsk {
    background: {{bg_input}};
    border: 1px solid {{line_strong}};
    border-radius: 11px;
}
QWidget#HeroAsk:hover {
    border-color: {{accent_line}};
}
QLabel#HeroAskIcon {
    color: {{text_faint}};
    font-size: {{fs_base}};
}
QLabel#HeroAskText {
    color: {{text_faint}};
    font-size: {{fs_sm}};
}
QLabel#HeroAskSend {
    color: {{on_accent}};
    background: {{accent}};
    border-radius: 7px;
    padding: 3px 12px;
    font-size: {{fs_xs}};
    font-weight: 600;
}

/* ---------- 三域卡（学习 / 工作 / 生活） ---------- */
QWidget#DomainGrid {
    background: transparent;
}
QWidget#DomainCard {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_lg}};
}
QWidget#DomainCard:hover, QWidget#DomainCard:focus {
    border-color: {{accent_line}};
}
QLabel#DomainLabel {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#DomainTitle {
    color: {{text}};
    font-size: {{fs_md}};
    font-weight: 600;
}
QLabel#DomainSub {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}

/* ---------- 今日简报 ---------- */
QWidget#BriefingBand {
    background: {{surface}};
    border: 1px solid {{line}};
    border-top: 1px solid {{mark}};
    border-radius: {{r_lg}};
}
QLabel#BriefEyebrow {
    color: {{mark}};
    font-size: {{fs_xs}};
}
QLabel#BriefTitle {
    color: {{text}};
    font-size: 20px;
    font-weight: 650;
}
QLabel#BriefMeta {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QPushButton#Ghost {
    color: {{text_dim}};
    background: transparent;
    border: 1px solid {{line}};
    border-radius: 8px;
    padding: 4px 10px;
    font-size: {{fs_xs}};
}
QPushButton#Ghost:hover {
    color: {{text}};
    border-color: {{line_strong}};
}
QWidget#BriefLead {
    background: transparent;
    border-radius: {{r_sm}};
}
QWidget#BriefLead:hover {
    background: {{surface_2}};
}
QLabel#BriefTagMark {
    color: {{mark}};
    background: {{mark_soft}};
    border-radius: 9px;
    padding: 0 7px;
    font-size: {{fs_xs}};
}
QLabel#BriefTag {
    color: {{text_dim}};
    background: {{surface_2}};
    border-radius: 9px;
    padding: 0 6px;
    font-size: {{fs_xs}};
}
QLabel#BriefLeadTitle {
    color: {{text}};
    font-size: {{fs_md}};
    font-weight: 600;
}
QLabel#BriefLeadSummary {
    color: {{text_dim}};
    font-size: {{fs_xs}};
}
QLabel#BriefSource {
    color: {{text_faint}};
    font-size: 10px;
}
QWidget#BriefRow {
    background: transparent;
    border-top: 1px solid {{line}};
    border-radius: 0;
}
QWidget#BriefRow:hover {
    background: {{surface_2}};
}
QLabel#BriefRowTitle {
    color: {{text}};
    font-size: {{fs_sm}};
    font-weight: 500;
}

/* ---------- 接着上次 / 工作入口 ---------- */
QWidget#ContinueCard {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_lg}};
}
QLabel#Eyebrow {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#Pill {
    color: {{mark}};
    background: {{mark_soft}};
    border-radius: 9px;
    padding: 1px 8px;
    font-size: {{fs_xs}};
}
QLabel#ContinueTitle {
    color: {{text}};
    font-size: 17px;
    font-weight: 600;
}
QLabel#ContinueSub {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}
QLabel#ContinueStat {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#Hint {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QWidget#AltRow {
    border-top: 1px solid {{line}};
    border-radius: 0;
}
QWidget#AltRow:hover {
    background: {{surface_2}};
}
QLabel#AltLabel {
    color: {{text_faint}};
    font-size: 10px;
}
QLabel#AltTitle {
    color: {{text_dim}};
    font-size: {{fs_sm}};
}
QLabel#AltMeta {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#AltGo {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}

/* ---------- 问答轨道 ---------- */
QWidget#TimelineCard {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_lg}};
}
QWidget#TimelineGroup {
    background: transparent;
}
QLabel#TimelineGroupLabel {
    color: {{text_dim}};
    font-size: {{fs_xs}};
    font-weight: 600;
}
QFrame#TimelineGroupLine {
    background: {{line}};
    border: none;
}
QLabel#TimelineGroupCount {
    color: {{text_faint}};
    font-size: 10px;
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
    font-size: {{fs_sm}};
    font-weight: 550;
}
QLabel#TimelineA {
    color: {{text_faint}};
    font-size: {{fs_sm}};
}
QLabel#TimelineTag {
    color: {{accent}};
    background: {{accent_soft}};
    border-radius: 4px;
    padding: 0 5px;
    font-size: 10px;
}

/* ---------- 本周 / 今天一行 ---------- */
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
QLabel#PanelNote {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QWidget#FactsStrip {
    background: {{surface_2}};
    border: none;
    border-top: 1px solid {{line}};
    border-radius: 6px;
}
QWidget#FactCell {
    background: transparent;
}
QWidget#FactSep {
    background: {{line}};
}
QLabel#FactValue {
    color: {{text}};
    font-size: 16px;
    font-weight: 650;
}
QLabel#FactLabel {
    color: {{text_faint}};
    font-size: 10px;
}

/* ---------- 成就折叠 ---------- */
QWidget#AchievementsCard {
    background: {{surface}};
    border: 1px solid {{line}};
    border-radius: {{r_md}};
}
QWidget#AchHeader {
    background: transparent;
    border-radius: {{r_md}};
}
QWidget#AchHeader:hover {
    background: {{surface_2}};
}
QLabel#AchSummary {
    color: {{text_faint}};
    font-size: {{fs_xs}};
}
QLabel#AchChev {
    color: {{text_faint}};
    font-size: {{fs_sm}};
}
QWidget#AchBody {
    background: transparent;
}
QWidget#AchRow {
    background: transparent;
    border-top: 1px solid {{line}};
    border-radius: 0;
}
QLabel#AchDot {
    color: {{ok}};
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
    font-size: 10px;
}

/* ---------- 空态 / 首次提示 ---------- */
QLabel#Empty {
    color: {{text_faint}};
    font-size: {{fs_sm}};
    padding: {{s4}};
}
QLabel#EmptyState {
    color: {{text_faint}};
    font-size: {{fs_sm}};
    padding: {{s4}} 0;
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
"""
