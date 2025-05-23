"""The main screen GUI, which allows sending commands, and viewing the RX/TX log.

The main screen has the following components:
- Left Side: The list of commands, as a pick list.
- Left Side: Text fields to input each argument for the command.
- Right Side: An "RX/TX" log, which shows the most recent received and transmitted messages
(occupies the right 70% of the screen).
"""

import argparse
import functools
import json
import tempfile
import time
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
import dash_split_pane
from dash import callback, dcc, html
from dash.dependencies import Input, Output, State
from loguru import logger
from sortedcontainers import SortedDict

from cts1_ground_support.paths import clone_firmware_repo
from cts1_ground_support.serial_util import list_serial_ports
from cts1_ground_support.telecommand_array_parser import parse_telecommand_list_from_repo
from cts1_ground_support.telecommand_preview import generate_telecommand_preview
from cts1_ground_support.telecommand_types import TelecommandDefinition
from cts1_ground_support.terminal_app.app_config import MAX_ARGS_PER_TELECOMMAND
from cts1_ground_support.terminal_app.app_store import app_store
from cts1_ground_support.terminal_app.app_types import UART_PORT_NAME_DISCONNECTED, RxTxLogEntry
from cts1_ground_support.terminal_app.serial_thread import start_uart_listener

UART_PORT_OPTION_LABEL_DISCONNECTED = "⛔ Disconnected ⛔"

# TODO: log the UART comms to a file
# TODO: fix the connect/disconnect loop when multiple clients are connected
#   ^ Ideas: Add an "Apply" button to change the port, or a mechanism where the "default-on-load"
#            value comes from the app_store's latest connected port (esp on load).


# TODO: Change this to a TTL cache so that it refreshes sometimes, maybe.
@functools.lru_cache  # Cache forever is fine.
def get_telecommand_list_from_repo_cached(repo_path: Path | None) -> list[TelecommandDefinition]:
    """Get the telecommand list from a repo, and cache the result."""
    if repo_path is None:
        return []

    return parse_telecommand_list_from_repo(repo_path)


def get_telecommand_list_from_repo() -> list[TelecommandDefinition]:
    """Get the telecommand list from the repo, based on the app_store repo path."""
    return get_telecommand_list_from_repo_cached(app_store.firmware_repo_path)


def get_telecommand_name_list() -> list[str]:
    """Get a list of telecommand names by reading the telecommands from the repo."""
    telecommands = get_telecommand_list_from_repo()
    return [tcmd.name for tcmd in telecommands]


def get_telecommand_by_name(name: str) -> TelecommandDefinition:
    """Get a telecommand definition by name."""
    telecommands = get_telecommand_list_from_repo()
    telecommand = next((tcmd for tcmd in telecommands if tcmd.name == name), None)
    if not telecommand:
        msg = f"Telecommand not found: {name}"
        raise ValueError(msg)
    return telecommand


@callback(
    Output("argument-inputs-container", "children"),
    Input("telecommand-dropdown", "value"),
)
def update_argument_inputs(selected_command_name: str) -> list[html.Div]:
    """Generate the argument input fields based on the selected telecommand."""
    selected_tcmd = get_telecommand_by_name(selected_command_name)

    arg_inputs = []
    for arg_num in range(MAX_ARGS_PER_TELECOMMAND):
        if (selected_tcmd.argument_descriptions is not None) and (
            arg_num < len(selected_tcmd.argument_descriptions)
        ):
            arg_description = selected_tcmd.argument_descriptions[arg_num]
            label = f"Arg {arg_num}: {arg_description}"
        else:
            label = f"Arg {arg_num}"

        this_id = f"arg-input-{arg_num}"

        arg_inputs.append(
            dbc.FormFloating(
                [
                    dbc.Input(
                        type="text",
                        id=this_id,
                        placeholder=label,
                        disabled=(arg_num >= selected_tcmd.number_of_args),
                        style={"fontFamily": "monospace"},
                    ),
                    dbc.Label(label, html_for=this_id),
                ],
                className="mb-3",
                # Hide the argument input if it is not needed for the selected telecommand.
                style=({"display": "none"} if arg_num >= selected_tcmd.number_of_args else {}),
            )
        )

    return arg_inputs


def handle_uart_port_change(uart_port_name: str) -> None:
    """Update the serial port name in the app store, if the port name changes."""
    last_uart_port_name = app_store.uart_port_name

    if uart_port_name != last_uart_port_name:
        if uart_port_name == UART_PORT_NAME_DISCONNECTED:
            logger.debug(
                f"Disconnect. Last port: {last_uart_port_name}. New port: {uart_port_name}."
            )
            msg = "Serial port disconnected."
        elif last_uart_port_name == UART_PORT_NAME_DISCONNECTED:
            logger.debug(f"Connect. Last port: {last_uart_port_name}. New port: {uart_port_name}.")
            msg = f"Serial port connected: {uart_port_name}"
        else:
            msg = f"Serial port changed from {last_uart_port_name} to {uart_port_name}"

        logger.info(msg)
        app_store.append_to_rxtx_log(RxTxLogEntry(msg.encode(), "notice"))

    app_store.uart_port_name = uart_port_name


@callback(
    Output("stored-command-preview", "data"),
    Input("telecommand-dropdown", "value"),
    Input("suffix-tags-checklist", "value"),
    Input("input-tsexec-suffix-tag", "value"),
    Input("input-resp_fname-suffix-tag", "value"),
    Input("extra-suffix-tags-input", "value"),  # Advanced feature for debugging
    Input("uart-update-interval-component", "n_intervals"),
    # TODO: Maybe this could be cleaner with `Input/State("argument-inputs-container", "children")`
    *[Input(f"arg-input-{arg_num}", "value") for arg_num in range(MAX_ARGS_PER_TELECOMMAND)],
    prevent_initial_call=True,  # Objects aren't created yet, so errors are thrown.
)
def update_stored_command_preview(
    selected_command_name: str,
    suffix_tags_checklist: list[str] | None,
    tsexec_suffix_tag: str | None,
    resp_fname_suffix_tag: str | None,
    extra_suffix_tags_input: str,
    _n_intervals: int,
    *every_arg_value: str,
) -> str:
    """When any input to the command preview changes, regenerate the command preview.

    Stores the command preview so that it's accessible from any function which wants it.
    """
    # Prep incoming args.
    if suffix_tags_checklist is None:
        suffix_tags_checklist = []

    if tsexec_suffix_tag == "":
        tsexec_suffix_tag = None

    if resp_fname_suffix_tag == "":
        resp_fname_suffix_tag = None

    # Get the selected command and its arguments.
    selected_command = get_telecommand_by_name(selected_command_name)
    arg_vals = [every_arg_value[arg_num] for arg_num in range(selected_command.number_of_args)]

    # Replace None with empty string, to avoid "None" in the preview.
    arg_vals: list[str] = [str(arg) if arg is not None else "" for arg in arg_vals]

    enable_tssent_suffix = "enable_tssent_tag" in suffix_tags_checklist

    extra_suffix_tags = {}
    if extra_suffix_tags_input:
        try:
            extra_suffix_tags = json.loads(extra_suffix_tags_input)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON in extra-suffix-tags-input field: {e}")

        if not isinstance(extra_suffix_tags, dict):
            logger.error(f"Extra suffix tags input is not a dictionary: {extra_suffix_tags}")
            extra_suffix_tags = {}

    return generate_telecommand_preview(
        tcmd_name=selected_command_name,
        arg_list=arg_vals,
        enable_tssent_suffix=enable_tssent_suffix,
        tsexec_suffix_value=tsexec_suffix_tag,
        resp_fname_suffix_value=resp_fname_suffix_tag,
        extra_suffix_tags=extra_suffix_tags.copy(),
    )


@callback(
    Output("command-preview-container", "children"),
    Input("stored-command-preview", "data"),
)
def update_command_preview_render(command_preview: str) -> list:
    """Make an area with the command preview for the selected telecommand."""
    return [
        html.H4(["Command Preview"], className="text-center"),
        html.Pre(command_preview, id="command-preview", className="mb-3"),
    ]


@callback(
    Input("send-button", "n_clicks"),
    State("telecommand-dropdown", "value"),
    State("stored-command-preview", "data"),
    # TODO: Maybe this could be cleaner with `Input/State("argument-inputs-container", "children")`
    *[State(f"arg-input-{arg_num}", "value") for arg_num in range(MAX_ARGS_PER_TELECOMMAND)],
    prevent_initial_call=True,
)
def send_button_callback(
    n_clicks: int,
    selected_command_name: str | None,
    command_preview: str,
    *every_arg_value: tuple[str],
) -> None:
    """Handle the send button click event by adding the command to the TX queue."""
    logger.info(f"Send button clicked ({n_clicks=})!")

    if selected_command_name is None:
        msg = "No command selected. Can't send a command!"
        logger.error(msg)
        app_store.append_to_rxtx_log(RxTxLogEntry(msg.encode(), "error"))
        return

    args = [
        every_arg_value[arg_num]
        for arg_num in range(get_telecommand_by_name(selected_command_name).number_of_args)
    ]
    if any(arg is None or arg == "" for arg in args):
        msg = f"Not all arguments are filled in. Can't run {selected_command_name}{args}!"
        logger.error(msg)
        app_store.append_to_rxtx_log(RxTxLogEntry(msg.encode(), "error"))
        return

    if app_store.uart_port_name == UART_PORT_NAME_DISCONNECTED:
        msg = "Can't send command when disconnected."
        logger.error(msg)
        app_store.append_to_rxtx_log(RxTxLogEntry(msg.encode(), "error"))
        return

    logger.info(f"Adding command to queue: {command_preview}")

    app_store.last_tx_timestamp_sec = time.time()
    app_store.tx_queue.append(command_preview.encode("ascii"))


@callback(
    Input("clear-log-button", "n_clicks"),
    prevent_initial_call=True,
)
def clear_log_button_callback(n_clicks: int) -> None:
    """Handle the "Clear Log" button click event by resetting the log."""
    logger.info(f"Clear Log button clicked ({n_clicks=})!")

    max_rxtx_log_index = app_store.rxtx_log.keys()[-1]
    app_store.rxtx_log = SortedDict(
        {
            max_rxtx_log_index + 1: RxTxLogEntry(b"Log Reset", "notice"),
        }
    ).copy()


@callback(
    Output("stored-rxtx-log-pause-limits", "data"),
    Output("pause-button", "children"),
    Output("pause-button", "color"),
    Input("pause-button", "n_clicks"),
)
def pause_button_callback(n_clicks: int) -> tuple[dict[str, int | bool | None], str, str]:
    """Handle the pause button click event by toggling the pause button state."""
    logger.info(f"Pause button clicked ({n_clicks=})!")

    if n_clicks % 2 == 0:
        # Set to running.
        logger.info("Setting to running")
        return (
            {
                "paused": False,
                "pause_min_idx": None,
                "pause_max_idx": None,
            },
            "Pause ⏸️",
            "danger",
        )

    # Pausing.
    pause_min_idx = app_store.rxtx_log.keys()[0]
    pause_max_idx = app_store.rxtx_log.keys()[-1]
    logger.info(f"Setting to paused: {pause_min_idx=}, {pause_max_idx=}")
    return (
        {
            "paused": True,
            "pause_min_idx": pause_min_idx,
            "pause_max_idx": pause_max_idx,
        },
        "Resume ▶️",
        "success",
    )


@callback(
    Output("uart-port-dropdown", "options"),
    Input("uart-port-dropdown", "value"),
    Input("uart-port-dropdown-interval-component", "n_intervals"),
)
def update_uart_port_dropdown_options(
    uart_port_name: str | None, _n_intervals: int
) -> list[dict[str, str]]:
    """Update the UART port dropdown with the available serial ports."""
    if uart_port_name is None:
        uart_port_name = UART_PORT_NAME_DISCONNECTED
    handle_uart_port_change(uart_port_name)

    # Re-render the dropdown with the updated list of serial ports.
    port_name_list = list_serial_ports()
    if app_store.uart_port_name not in ([*port_name_list, UART_PORT_NAME_DISCONNECTED]):
        msg = f"Serial port is no longer available in list of ports: {app_store.uart_port_name}"
        logger.warning(msg)
        app_store.append_to_rxtx_log(RxTxLogEntry(msg.encode(), "error"))
        app_store.uart_port_name = UART_PORT_NAME_DISCONNECTED

    if app_store.uart_port_name != uart_port_name:
        logger.debug("Would try to update the selected UART port value to 'DISCONNECTED'.")

    # NOTE: Don't try to update the dropdown options in the callback, as it will trigger the
    # callback again and infinitely toggle between connected and disconnected.
    return [
        {"label": UART_PORT_OPTION_LABEL_DISCONNECTED, "value": UART_PORT_NAME_DISCONNECTED}
    ] + [{"label": port, "value": port} for port in port_name_list]


@callback(
    Output("selected-tcmd-info-container", "children"),
    Input("telecommand-dropdown", "value"),
)
def update_selected_tcmd_info(selected_command_name: str) -> list:
    """Make an area with the docstring for the selected telecommand."""
    selected_command = get_telecommand_by_name(selected_command_name)

    if selected_command.full_docstring is None:
        docstring = f"No docstring found for {selected_command.tcmd_func}"
    else:
        docstring = selected_command.full_docstring

    table_fields = selected_command.to_dict_table_fields()

    table_header = html.Thead(html.Tr([html.Th("Field"), html.Th("Value")]))
    table_body = html.Tbody(
        [
            html.Tr(
                [
                    html.Td(key),
                    html.Td(value, style={"fontFamily": "monospace"}),
                ]
            )
            for key, value in table_fields.items()
        ]
    )

    table = dbc.Table(
        [table_header, table_body], bordered=True, striped=True, hover=True, responsive=True
    )

    return [
        html.H4(["Command Info"], className="text-center"),
        table,
        html.Hr(),
        html.H4(["Command Docstring"], className="text-center"),
        # TODO: add the "brief" docstring here, and then hide the rest in a "Click to expand"
        html.Pre(docstring, id="selected-tcmd-info", className="mb-3"),
    ]


def generate_rx_tx_log(
    *,
    show_end_of_line_chars: bool = False,
    show_timestamp: bool = False,
    auto_format_json: bool = False,
    pause_min_idx: int | None = None,
    pause_max_idx: int | None = None,
) -> html.Div:
    """Generate the RX/TX log, which shows the most recent received and transmitted messages."""
    if pause_min_idx is None:
        pause_min_idx = app_store.rxtx_log.keys()[0]
    if pause_max_idx is None:
        pause_max_idx = app_store.rxtx_log.keys()[-1]

    logger.info(f"Showing log: {pause_min_idx=}, {pause_max_idx=}")

    return html.Div(
        [
            html.Pre(
                entry.to_string(
                    show_end_of_line_chars=show_end_of_line_chars,
                    show_timestamp=show_timestamp,
                    auto_format_json=auto_format_json,
                ),
                style=(entry.css_style | {"margin": "0", "lineHeight": "1.1"}),
            )
            for idx, entry in app_store.rxtx_log.items()
            if (idx >= pause_min_idx) and (idx <= pause_max_idx)
        ],
        id="rx-tx-log",
        className="p-3",
        style={
            "display": "block",
            "width": "fit-content",  # Make the horizontal scrollbar work correctly.
        },
    )


# Should be the last callback in the file, as other callbacks modify the log.
@callback(
    Output("rx-tx-log-container", "children"),
    Output("uart-update-interval-component", "interval"),
    Input("uart-port-dropdown", "value"),
    Input("send-button", "n_clicks"),
    Input("clear-log-button", "n_clicks"),
    Input("uart-update-interval-component", "n_intervals"),
    Input("display-options-checklist", "value"),
    Input("stored-rxtx-log-pause-limits", "data"),
)
def update_uart_log_interval(
    _uart_port_name: str,
    _n_clicks_send: int,
    _n_clicks_clear_logs: int,
    _update_interval_count: int,
    display_options_checklist: list[str] | None,
    stored_rxtx_log_pause_limits: dict[str, int | bool | None],
) -> tuple[html.Div, int]:
    """Update the UART log at the specified interval. Also, update the refresh interval."""
    sec_since_send = time.time() - app_store.last_tx_timestamp_sec
    if sec_since_send < 10:  # noqa: PLR2004
        # Rapid refreshed right after sending a command.
        app_store.uart_log_refresh_rate_ms = 250
    elif sec_since_send < 60:  # noqa: PLR2004
        # Chill if it's been a while since the last command.
        app_store.uart_log_refresh_rate_ms = 800
    else:
        # Slow down if it's been a long time since the last command.
        app_store.uart_log_refresh_rate_ms = 2000

    if display_options_checklist:
        show_end_of_line_chars = "show_end_of_line_chars" in display_options_checklist
        show_timestamp = "show_timestamp" in display_options_checklist
        auto_format_json = "auto_format_json" in display_options_checklist
    else:
        show_end_of_line_chars = False
        show_timestamp = False
        auto_format_json = False

    return (
        # New log entries.
        generate_rx_tx_log(
            show_end_of_line_chars=show_end_of_line_chars,
            show_timestamp=show_timestamp,
            auto_format_json=auto_format_json,
            pause_min_idx=stored_rxtx_log_pause_limits.get("pause_min_idx"),
            pause_max_idx=stored_rxtx_log_pause_limits.get("pause_max_idx"),
        ),
        app_store.uart_log_refresh_rate_ms,  # new refresh interval
    )


def generate_left_pane(*, selected_command_name: str, enable_advanced: bool) -> list:
    """Make the left pane of the GUI, to be put inside a Col."""
    return [
        html.H1("CTS-SAT-1 Ground Support - Telecommand Terminal", className="text-center"),
        dbc.Row(
            [
                dbc.Label("Select a Serial Port:", html_for="uart-port-dropdown"),
                dcc.Dropdown(
                    id="uart-port-dropdown",
                    options=(
                        [
                            {
                                "label": UART_PORT_OPTION_LABEL_DISCONNECTED,
                                "value": UART_PORT_NAME_DISCONNECTED,
                            }
                        ]
                        + [{"label": port, "value": port} for port in list_serial_ports()]
                    ),
                    value=UART_PORT_NAME_DISCONNECTED,
                    className="mb-3",  # Add margin bottom to the dropdown
                ),
                dcc.Interval(
                    id="uart-port-dropdown-interval-component",
                    interval=2500,  # in milliseconds
                    n_intervals=0,
                ),
            ],
        ),
        html.Hr(),
        dbc.Row(
            [
                dbc.Label("Select a Telecommand:", html_for="telecommand-dropdown"),
                dcc.Dropdown(
                    id="telecommand-dropdown",
                    options=[{"label": cmd, "value": cmd} for cmd in get_telecommand_name_list()],
                    value=selected_command_name,
                    className="mb-3",  # Add margin bottom to the dropdown
                    style={"fontFamily": "monospace"},
                ),
            ],
        ),
        html.Div(
            update_argument_inputs(selected_command_name),
            id="argument-inputs-container",
            className="mb-3",
        ),
        html.Hr(),
        html.Div(
            [
                dbc.Label("Suffix Tag Options:", html_for="suffix-tags-checklist"),
                dbc.Checklist(
                    options={
                        "enable_tssent_tag": "Send '@tssent=current_timestamp' Tag?",
                        # TODO: add more here, like the "Send 'sha256' Tag"
                    },
                    id="suffix-tags-checklist",
                ),
            ]
        ),
        html.Div(
            dbc.FormFloating(
                [
                    dbc.Input(
                        type="text",
                        id="input-tsexec-suffix-tag",
                        placeholder="Timestamp to Execute Command (@tsexec=xxx)",
                        style={"fontFamily": "monospace"},
                    ),
                    dbc.Label(
                        "Timestamp to Execute Command (@tsexec=xxx)",
                        html_for="input-tsexec-suffix-tag",
                    ),
                ],
                className="mb-3",
            ),
        ),
        html.Div(
            dbc.FormFloating(
                [
                    dbc.Input(
                        type="text",
                        id="input-resp_fname-suffix-tag",
                        placeholder="File Name to log the response",
                        style={"fontFamily": "monospace"},
                    ),
                    dbc.Label(
                        "File Name to store TCMD response",
                        html_for="input-resp_fname-suffix-tag",
                    ),
                ],
                className="mb-3",
            ),
        ),
        html.Div(
            dbc.FormFloating(
                [
                    dbc.Input(
                        type="text",
                        id="extra-suffix-tags-input",
                        placeholder="Extra Suffix Tags Input (JSON)",
                        style={"fontFamily": "monospace"},
                    ),
                    dbc.Label(
                        "Extra Suffix Tags Input (JSON)", html_for="extra-suffix-tags-input"
                    ),
                ],
                className="mb-3",
                # Hide this field by default, and only show if the CLI arg "--advanced" is passed.
                style=({} if enable_advanced else {"display": "none"}),
            ),
        ),
        html.Hr(),
        html.Div(id="command-preview-container", className="mb-3"),
        dbc.Row(
            [
                dbc.Button(
                    "Clear Log 🫗",
                    id="clear-log-button",
                    n_clicks=0,
                    className="m-1 px-3",
                    style={"width": "auto"},
                    color="warning",
                ),
                dbc.Button(
                    "Pause ⏯️",
                    id="pause-button",
                    n_clicks=0,
                    className="m-1 px-3",
                    style={"width": "auto"},
                ),
                dbc.Button(
                    "Send 📡",
                    id="send-button",
                    n_clicks=0,
                    className="m-1 px-5",
                    style={"width": "auto"},
                ),
            ],
            justify="center",
            className="mb-3",
        ),
        html.Hr(),
        html.Div(id="selected-tcmd-info-container", className="mb-3"),
        html.Hr(),
        html.H4("Display Options", className="text-center"),
        html.Div(
            [
                dbc.Checklist(
                    options={
                        "show_end_of_line_chars": "Show End-of-Line Characters?",
                        "show_timestamp": "Show Timestamps?",
                        "auto_format_json": "Auto Format JSON?",
                    },
                    id="display-options-checklist",
                    value=["auto_format_json"],  # Default enables.
                ),
            ]
        ),
    ]


def run_dash_app(*, enable_debug: bool = False, enable_advanced: bool = False) -> None:
    """Run the main Dash application."""
    app_name = "CTS-SAT-1 Ground Support"
    app = dash.Dash(
        __name__,  # required to load /assets folder
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        title=app_name,
        update_title=(
            # Disable the update title, unless we're debugging.
            # Makes it look cleaner overall.
            "Updating..." if enable_debug else ""
        ),
    )

    app.layout = dbc.Container(
        [
            dash_split_pane.DashSplitPane(
                [
                    html.Div(
                        generate_left_pane(
                            selected_command_name=get_telecommand_name_list()[0],  # default
                            enable_advanced=enable_advanced,
                        ),
                        className="p-3",
                        style={
                            "height": "100%",
                            "overflowY": "auto",  # Enable vertical scroll.
                        },
                    ),
                    html.Div(
                        generate_rx_tx_log(),
                        id="rx-tx-log-container",
                        style={
                            "fontFamily": "monospace",
                            "backgroundColor": "black",
                            "height": "100%",
                            "overflowY": "auto",
                            "overflowX": "auto",  # Not really used; pane2Style is main scroll bar.
                            # So that new messages appear at the bottom.
                            "flexDirection": "column-reverse",
                            "display": "flex",
                            # Make the horizontal scrollbar work correctly.
                            "position": "absolute",
                        },
                    ),
                ],
                id="vertical-split-pane-1",
                split="vertical",
                size=500,  # Default starting size.
                minSize=300,
                # Fill the space to the right side of the log black before receiving data.
                pane2Style={
                    "backgroundColor": "black",
                    "overflowX": "auto",
                },
            ),
            dbc.Button(
                "Jump to Bottom ⬇️",
                id="scroll-to-bottom-button",
                style={
                    "display": "none",
                    "position": "fixed",
                    "bottom": "20px",
                    "right": "60px",
                    "zIndex": "99",
                },
                color="danger",
            ),
            dcc.Interval(
                id="uart-update-interval-component",
                interval=800,  # in milliseconds
                n_intervals=0,
            ),
            dcc.Store(id="stored-command-preview", data=""),
            dcc.Store(id="stored-rxtx-log-pause-limits", data={"paused": False}.copy()),
        ],
        fluid=True,  # Use a fluid container for full width.
    )

    start_uart_listener()

    app.run_server(debug=enable_debug)
    logger.info("Dash app started and finished.")


def main() -> None:
    """Run the main server, with optional debug mode (via CLI arg)."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-r",
        "--repo",
        "--firmware-repo",
        dest="firmware_repo",
        type=str,
        help=(
            "Path to the root of the CTS-SAT-1-OBC-Firmware repository, for reading telecommand "
            "list. "
            "If not provided, the repo will automatically be cloned to a temporary directory."
        ),
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug mode for the Dash app.",
    )
    parser.add_argument(
        "-a",
        "--advanced",
        action="store_true",
        help="Enable advanced features for ground debugging, like the extra suffix tags input.",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        if args.firmware_repo is None:
            firmware_repo_path, repo = clone_firmware_repo(Path(tmp_dir))
            logger.info(
                "Cloned CTS-SAT-1-OBC-Firmware repo to temporary directory "
                f"(commit={repo.head.commit.hexsha[0:7]}): {tmp_dir}"
            )
        else:
            firmware_repo_path = Path(args.firmware_repo)

            if not firmware_repo_path.is_dir():
                msg = f"Provided CTS-SAT-1-OBC-Firmware repo not found: {args.firmware_repo}"
                raise FileNotFoundError(msg)

            logger.info(f"Using provided CTS-SAT-1-OBC-Firmware repo: {args.firmware_repo}")

        app_store.firmware_repo_path = firmware_repo_path

        logger.info(
            f"CTS-SAT-1-OBC-Firmware repo contains {len(get_telecommand_name_list())} "
            "telecommands."
        )

        run_dash_app(
            enable_debug=args.debug,
            enable_advanced=args.advanced,
        )


if __name__ == "__main__":
    main()
