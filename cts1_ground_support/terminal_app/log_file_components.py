"""Additional GUI components for log file management."""

import os
from pathlib import Path

import dash_bootstrap_components as dbc
from dash import callback, dcc, html
from dash.dependencies import Input, Output

from cts1_ground_support.terminal_app.file_logger import daily_logger


def generate_log_file_info_section() -> list:
    """Generate GUI section showing log file information."""
    return [
        html.Hr(),
        html.H4("Daily Log Files", className="text-center"),
        html.Div(id="log-file-info-container"),
        dcc.Interval(
            id="log-file-info-interval",
            interval=30000,  # Update every 30 seconds
            n_intervals=0,
        ),
    ]


@callback(
    Output("log-file-info-container", "children"),
    Input("log-file-info-interval", "n_intervals"),
)
def update_log_file_info(_n_intervals: int) -> list:
    """Update the log file information display."""
    recent_files = daily_logger.get_recent_log_files(days=7)
    
    if not recent_files:
        return [html.P("No log files found.", className="text-muted text-center")]
    
    # Current log file info
    current_file = recent_files[0] if recent_files else None
    current_info = []
    
    if current_file:
        file_size = current_file.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        current_info = [
            html.P([
                html.Strong("Current Log File: "),
                html.Code(current_file.name),
                html.Br(),
                html.Strong("Size: "),
                f"{file_size_mb:.2f} MB ({file_size:,} bytes)"
            ], className="mb-3"),
        ]
    
    # Recent files table
    table_rows = []
    for log_file in recent_files[:5]:  # Show last 5 days
        file_size = log_file.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        table_rows.append(
            html.Tr([
                html.Td(log_file.name, style={"fontFamily": "monospace"}),
                html.Td(f"{file_size_mb:.2f} MB"),
                html.Td(
                    html.A(
                        "Download",
                        href=f"/download/{log_file.name}",
                        target="_blank",
                        className="btn btn-sm btn-outline-primary"
                    )
                ),
            ])
        )
    
    if table_rows:
        recent_files_table = dbc.Table([
            html.Thead([
                html.Tr([
                    html.Th("File Name"),
                    html.Th("Size"),
                    html.Th("Action"),
                ])
            ]),
            html.Tbody(table_rows)
        ], bordered=True, striped=True, hover=True, responsive=True, size="sm")
    else:
        recent_files_table = html.P("No recent log files found.", className="text-muted")
    
    return current_info + [
        html.P(html.Strong("Recent Log Files:"), className="mb-2"),
        recent_files_table,
        html.P([
            html.Small([
                "Log files are stored in: ",
                html.Code(str(daily_logger.log_directory.absolute()))
            ])
        ], className="text-muted mt-2")
    ]


def setup_download_route(app):
    """Set up download route for log files."""
    @app.server.route('/download/<filename>')
    def download_log_file(filename):
        """Serve log files for download."""
        try:
            from flask import send_file
            
            # Validate filename to prevent directory traversal
            if not filename.startswith('cts1_ground_support_') or not filename.endswith('.log'):
                return "Invalid filename", 400
            
            file_path = daily_logger.log_directory / filename
            if not file_path.exists():
                return "File not found", 404
            
            return send_file(
                file_path,
                as_attachment=True,
                download_name=filename,
                mimetype='text/plain'
            )
        except Exception as e:
            return f"Error downloading file: {str(e)}", 500