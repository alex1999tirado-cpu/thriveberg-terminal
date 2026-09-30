from __future__ import annotations

AJAX_BACKGROUND = "#030404"
AJAX_PANEL = "#0b0d0f"
AJAX_PANEL_ALT = "#303338"
AJAX_GRID = "#252a2e"
AJAX_BORDER = "#5b6065"
AJAX_TEXT = "#d7d7d7"
AJAX_MUTED = "#8f99a3"
AJAX_CYAN = "#4f9ebb"
AJAX_AMBER = "#ffb000"
AJAX_YELLOW = AJAX_AMBER
AJAX_GREEN = "#62e600"
AJAX_RED = "#ff315f"
AJAX_ORANGE = "#d99116"
AJAX_SELECTION = "#b87900"
AJAX_FONT = "DejaVu Sans Mono"

VOL_SURFACE_COLORS = (
    "#075d28",
    "#0db63f",
    "#35e335",
    "#a5ef32",
    "#f0ec27",
    "#ffb51f",
    "#ff7618",
    "#e93f13",
)


def qt_stylesheet() -> str:
    return f"""
        QWidget {{
            background: {AJAX_BACKGROUND};
            color: {AJAX_TEXT};
            font-family: "{AJAX_FONT}";
            font-size: 13px;
        }}
        QMainWindow, QSplitter, QTabWidget::pane {{
            background: {AJAX_BACKGROUND};
        }}
        QFrame#windowChrome {{
            background: #17191b;
            border-bottom: 1px solid #2e3236;
        }}
        QLabel#windowTitle {{
            color: {AJAX_TEXT};
            font-size: 13px;
            font-weight: bold;
            padding-left: 8px;
        }}
        QPushButton#windowControl {{
            background: transparent;
            color: #b8bdc2;
            min-width: 42px;
            min-height: 26px;
            padding: 0px;
            font-size: 14px;
        }}
        QPushButton#windowControl:hover {{ background: #3b3f43; color: white; }}
        QPushButton#windowClose {{
            background: transparent;
            color: #b8bdc2;
            min-width: 46px;
            min-height: 26px;
            padding: 0px;
            font-size: 14px;
        }}
        QPushButton#windowClose:hover {{ background: #b41f35; color: white; }}
        QFrame#splashPage, QFrame#authPage {{
            background: {AJAX_BACKGROUND};
            border: 0px;
        }}
        QLabel#splashBrand {{
            color: {AJAX_AMBER};
            font-size: 22px;
            font-weight: bold;
        }}
        QLabel#bootLine {{ color: {AJAX_MUTED}; font-size: 14px; }}
        QLabel#bootReady {{ color: {AJAX_AMBER}; font-size: 15px; font-weight: bold; }}
        QLabel#authBrand {{ color: #f4f4f4; font-size: 36px; font-weight: bold; }}
        QLabel#authBrandSub {{ color: #f4f4f4; font-size: 14px; font-weight: bold; }}
        QLabel#authCode {{ color: #f4f4f4; font-size: 29px; font-weight: bold; }}
        QLabel#authFieldLabel {{ color: #efefef; font-size: 18px; }}
        QLabel#authStatus {{ color: {AJAX_MUTED}; min-height: 42px; font-size: 12px; }}
        QLineEdit#authInput {{
            background: #f7931a;
            border: 1px solid #c5680a;
            color: #080808;
            min-height: 36px;
            max-height: 36px;
            padding: 1px 6px;
            font-size: 16px;
            selection-background-color: #252525;
            selection-color: white;
        }}
        QPushButton#authSubmit {{
            background: #343434;
            color: #f0f0f0;
            border: 1px solid #4b4b4b;
            min-height: 32px;
            max-height: 32px;
            padding: 0px 12px;
            font-size: 14px;
        }}
        QPushButton#authSubmit:hover {{ background: #505050; color: white; }}
        QPushButton#authLink {{
            background: transparent;
            color: {AJAX_AMBER};
            border: 0px;
            min-height: 24px;
            padding: 0px;
            text-align: left;
            font-size: 16px;
        }}
        QPushButton#authLink:hover {{ color: white; background: transparent; }}
        QLabel#languageTitle {{ color: #efefef; font-size: 18px; }}
        QPushButton#languageOption {{
            background: transparent;
            color: #c87b2f;
            border: 0px;
            min-width: 155px;
            min-height: 26px;
            padding: 0px 4px;
            text-align: left;
            font-size: 17px;
        }}
        QPushButton#languageOption:hover {{ background: transparent; color: #f0a04a; }}
        QPushButton#languageOption:checked {{ background: transparent; color: #f4f4f4; }}
        QLabel#languageNote {{ color: #e0e0e0; font-size: 16px; }}
        QLabel#authTechnical {{ color: #777d82; font-size: 13px; }}
        QLabel#authLegal {{ color: #a0a4a8; font-size: 12px; }}
        QTabWidget#workspaceTabs > QTabBar::tab {{
            background: #303338;
            color: #111111;
            min-width: 150px;
            padding: 4px 18px;
        }}
        QTabWidget#workspaceTabs > QTabBar::tab:selected {{
            background: #e3e3e3;
            color: #050505;
        }}
        QTextBrowser#socialTranscript {{
            background: #030404;
            border: 1px solid {AJAX_GRID};
            color: {AJAX_TEXT};
        }}
        QFrame#systemBar {{
            background: #111111;
            border: 0px;
        }}
        QFrame#menuBar {{
            background: #343434;
            border: 0px;
        }}
        QLabel#functionBar {{
            background: #97001d;
            color: white;
            font-weight: bold;
            padding: 2px 8px;
        }}
        QLabel#instrumentBar {{
            background: #080909;
            color: {AJAX_TEXT};
            border-bottom: 1px solid {AJAX_GRID};
            padding: 2px 8px;
        }}
        QLabel#footerBar {{
            background: #101315;
            color: {AJAX_TEXT};
            border-top: 1px solid {AJAX_GRID};
            padding: 2px 7px;
        }}
        QFrame#emptyWorkspace {{
            background: {AJAX_BACKGROUND};
            border: 1px solid {AJAX_GRID};
        }}
        QFrame#terminalPanel {{
            background: {AJAX_BACKGROUND};
            border: 1px solid {AJAX_BORDER};
        }}
        QFrame#controlStrip {{
            background: #101214;
            border: 0px;
        }}
        QFrame#viewStrip {{
            background: #303338;
            border: 0px;
        }}
        QFrame#chartPanel {{
            background: {AJAX_BACKGROUND};
            border: 1px solid {AJAX_BORDER};
        }}
        QLabel#titleBar {{
            background: #97001d;
            color: white;
            font-weight: bold;
            padding: 2px 8px;
        }}
        QLabel#sectionTitle {{
            color: {AJAX_CYAN};
            font-weight: bold;
            padding: 2px 5px;
        }}
        QLabel#panelHeader {{
            background: #373a3d;
            color: #dedede;
            font-size: 14px;
            padding: 2px 7px;
        }}
        QLabel#panelBadge {{
            background: {AJAX_ORANGE};
            color: #050505;
            font-weight: bold;
            padding: 1px 6px;
        }}
        QLabel#marketStrip {{
            background: #101214;
            color: {AJAX_TEXT};
            padding: 2px 7px;
        }}
        QLabel#metricsStrip {{
            background: #080a0b;
            color: {AJAX_TEXT};
            border-top: 1px solid #202428;
            border-bottom: 1px solid #202428;
            padding: 2px 7px;
        }}
        QLabel#controlLabel {{
            color: {AJAX_AMBER};
            font-weight: bold;
            padding: 0px 4px;
        }}
        QLabel#fieldName {{ color: {AJAX_TEXT}; }}
        QLabel#muted {{ color: {AJAX_MUTED}; }}
        QPushButton, QToolButton, QComboBox {{
            background: {AJAX_PANEL_ALT};
            border: 0px;
            border-radius: 0px;
            color: {AJAX_TEXT};
            min-height: 22px;
            padding: 2px 8px;
        }}
        QPushButton:hover, QToolButton:hover, QComboBox:hover {{
            background: #55585b;
            color: #ffffff;
        }}
        QPushButton:checked, QToolButton:checked {{
            background: {AJAX_ORANGE};
            color: black;
            font-weight: bold;
        }}
        QPushButton#menuButton {{
            background: transparent;
            color: {AJAX_TEXT};
            padding: 0px 8px;
        }}
        QPushButton#menuButton:hover {{ background: #5a5a5a; color: white; }}
        QPushButton#functionTab {{
            background: #55585b;
            color: #111111;
            font-weight: bold;
            min-height: 22px;
            padding: 1px 14px;
        }}
        QPushButton#functionTab:hover {{ background: #c7c8ca; }}
        QPushButton#functionTab:checked {{
            background: #e3e3e3;
            color: #050505;
        }}
        QPushButton#amberField, QToolButton#amberField, QComboBox#amberField, QLabel#amberField {{
            background: {AJAX_ORANGE};
            color: #050505;
            font-weight: bold;
        }}
        QComboBox#amberField::drop-down {{ border: 0px; width: 17px; }}
        QComboBox#amberField QAbstractItemView {{
            background: #111315;
            color: {AJAX_TEXT};
            selection-background-color: {AJAX_ORANGE};
            selection-color: #050505;
        }}
        QLineEdit {{
            background: #050505;
            border: 0px;
            border-radius: 0px;
            color: {AJAX_AMBER};
            min-height: 22px;
            padding: 2px 6px;
        }}
        QFrame#commandSuggestions {{
            background: #050607;
            border: 1px solid {AJAX_BORDER};
        }}
        QLabel#suggestionStatus {{
            background: #24272a;
            color: {AJAX_CYAN};
            border: 0px;
            border-bottom: 1px solid {AJAX_BORDER};
            font-weight: bold;
            padding: 2px 7px;
        }}
        QTableWidget#suggestionTable {{
            background: #030404;
            alternate-background-color: #0b0d0f;
            border: 0px;
            color: {AJAX_TEXT};
            gridline-color: transparent;
            selection-background-color: {AJAX_SELECTION};
            selection-color: #050505;
        }}
        QTableWidget#suggestionTable QHeaderView::section {{
            background: #15181a;
            color: {AJAX_MUTED};
            border: 0px;
            border-right: 1px solid {AJAX_GRID};
            border-bottom: 1px solid {AJAX_GRID};
            padding: 4px 7px;
        }}
        QTableWidget#suggestionTable::item {{
            border: 0px;
            padding: 3px 7px;
        }}
        QWidget#securityFunctionMenu {{
            background: {AJAX_BACKGROUND};
        }}
        QLabel#functionBreadcrumb {{
            color: {AJAX_TEXT};
            border-bottom: 1px solid {AJAX_GRID};
            padding: 3px 2px 7px 2px;
        }}
        QLabel#functionGroupTitle {{
            color: {AJAX_CYAN};
            font-weight: bold;
            padding: 2px 2px 3px 2px;
        }}
        QFrame[functionRow="true"] {{
            background: transparent;
            border: 0px;
        }}
        QFrame[functionRow="true"]:hover {{
            background: #33270b;
        }}
        QLabel#functionMenuCode {{
            color: {AJAX_TEXT};
            font-weight: bold;
        }}
        QLabel#functionMenuDescription {{
            color: {AJAX_AMBER};
        }}
        QTabBar::tab {{
            background: #55585b;
            border: 0px;
            border-radius: 0px;
            color: #111111;
            font-weight: bold;
            padding: 4px 14px;
        }}
        QTabBar::tab:selected {{
            background: #e3e3e3;
            color: black;
            font-weight: bold;
        }}
        QHeaderView::section {{
            background: {AJAX_PANEL_ALT};
            color: {AJAX_AMBER};
            border: 0px;
            border-right: 1px solid {AJAX_GRID};
            border-bottom: 1px solid {AJAX_BORDER};
            padding: 5px 7px;
            font-weight: bold;
        }}
        QTableWidget, QTableView {{
            background: {AJAX_BACKGROUND};
            alternate-background-color: {AJAX_PANEL};
            color: {AJAX_TEXT};
            gridline-color: {AJAX_GRID};
            border: 1px solid {AJAX_BORDER};
            selection-background-color: {AJAX_SELECTION};
            selection-color: #050505;
        }}
        QTableWidget::item, QTableView::item {{
            padding: 3px 7px;
        }}
        QFrame#researchControlStrip {{
            background: #101214;
            border-top: 1px solid {AJAX_GRID};
            border-bottom: 1px solid {AJAX_GRID};
        }}
        QPushButton#amberButton {{
            background: {AJAX_AMBER};
            color: #050505;
            border: 1px solid #ffc52d;
            padding: 3px 12px;
            font-weight: bold;
        }}
        QPushButton#amberButton:hover {{ background: #ffc52d; }}
        QPushButton#amberButton:pressed {{ background: #bd7900; }}
        QScrollBar:vertical {{
            background: #111315;
            border: 0px;
            width: 13px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {AJAX_ORANGE};
            min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {AJAX_AMBER}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            background: #303338;
            height: 13px;
            subcontrol-origin: margin;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: #111315;
        }}
        QStatusBar {{
            background: #0b0d0f;
            color: {AJAX_MUTED};
            border-top: 1px solid {AJAX_GRID};
        }}
        QSplitter::handle {{ background: #030404; width: 3px; height: 3px; }}
        QMenu {{
            background: {AJAX_PANEL};
            border: 1px solid {AJAX_BORDER};
        }}
        QMenu::item:selected {{ background: {AJAX_AMBER}; color: black; }}
    """
