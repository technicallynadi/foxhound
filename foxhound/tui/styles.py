"""Shared TCSS styles for the Foxhound TUI."""

APP_CSS = """
#sidebar {
    width: 24;
    background: $surface;
    border-right: solid $primary;
    padding: 1 0;
}

#sidebar .nav-item {
    padding: 0 2;
    height: 1;
}

#sidebar .nav-item:hover {
    background: $primary-background;
}

#sidebar .nav-item.--active {
    background: $primary;
    color: $text;
}

#main-content {
    width: 1fr;
}

.view-title {
    text-style: bold;
    padding: 0 1;
    height: 1;
    background: $primary-background;
    color: $text;
}

.detail-panel {
    height: 22;
    border-top: solid $primary;
    padding: 0;
    background: $surface;
}

#detail-text {
    height: 1fr;
    overflow-y: auto;
    padding: 1 2;
}

.detail-panel .label {
    text-style: bold;
    color: $accent;
}

#detail-buttons-container {
    height: auto;
    padding: 0;
    margin-bottom: 3;
}

.detail-button-row {
    height: auto;
    min-height: 3;
    padding: 0 1;
    margin-bottom: 1;
    layout: horizontal;
}

.detail-button-row Button {
    margin: 0 1;
    min-width: 12;
    height: 3;
}

Button.purple {
    background: mediumpurple;
    color: white;
}

Button.purple:hover, Button.purple:focus {
    background: plum;
}

Button {
    min-width: 14;
    height: 3;
    text-style: none;
    padding: 0 2;
}

Button:hover {
    text-style: none;
    background: $primary-lighten-2;
}

Button:focus {
    text-style: none;
    background: $primary-lighten-2;
}

Button.-success:hover, Button.-success:focus {
    background: $success-lighten-2;
}

Button.-error:hover, Button.-error:focus {
    background: $error-lighten-2;
}

Button.-warning:hover, Button.-warning:focus {
    background: $warning-lighten-2;
}

Button.-primary:hover, Button.-primary:focus {
    background: $primary-lighten-2;
}

#dash-buttons {
    height: 5;
    padding: 1 1;
    layout: horizontal;
}

#dash-buttons Button {
    margin: 0 1;
    min-width: 14;
    height: 3;
}

#doctor-buttons {
    height: 5;
    padding: 1 1;
    layout: horizontal;
}

#doctor-summary {
    height: 2;
    padding: 0 1;
}

#retention-buttons {
    height: 5;
    padding: 1 1;
    layout: horizontal;
}

#retention-buttons Button {
    margin: 0 1;
    min-width: 18;
    height: 3;
}

#scout-search {
    height: 3;
    margin: 0 0 0 0;
    border: solid $primary;
}

DataTable {
    height: 1fr;
}

DataTable > .datatable--cursor {
    background: $primary;
}

.empty-state {
    text-align: center;
    padding: 4;
    color: $text-muted;
}

.state-suggested {
    color: cyan;
}

.state-approved {
    color: green;
}

.state-rejected {
    color: red;
}

.state-executing {
    color: magenta;
}

.state-completed {
    color: ansi_bright_green;
}

.state-failed {
    color: ansi_bright_red;
    text-style: bold;
}

.score-pending {
    color: $text-muted;
    text-style: italic;
}
"""
