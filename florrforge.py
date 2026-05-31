from ast import Not
import os
from random import random
import discord
from discord import app_commands
from discord.ext import commands 
import re
import time
import asyncio
import json
import signal
import atexit
import traceback
import sys
from discord.ui import View, Button, button
from discord.enums import ButtonStyle
from collections import Counter
import aiohttp.web
from collections import defaultdict

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATA_FILE = "data.json"
STATE_FILE = "bot_state.json"
BASE_URL = "https://api.n.m28.io/endpoint/florrio-map-{}-green/findEach/"

TARGET_BOT_ID_FOR_AUTO_UPDATES = 1379160458698690691
YOUR_USER_ID = 1453329316833398819
ADMIN_USER_IDS = [
    YOUR_USER_ID, 1020489591800729610, 1188633780261507102,
    934249510127935529, 504748495933145103, 1095468010564767796, 1318608682971566194, 1065159585419247657, 1255285712740421787, 1280968897654292490
]
BANNED_USER_IDS = [708410255033237586]

AUTO_UPDATE_MESSAGE_REGEX = re.compile(
    r"The Unique\s+([a-zA-Z0-9_\-\s'.]+?)\s+has been forged by\s+([a-zA-Z0-9_\-\s'.]+?)(?:!|$|\s+@)",
    re.IGNORECASE
)

INTERACTIVE_LIST_TARGET_CHANNEL_IDS = [
    1379541947189821460, 1355614867490345192, 1378070555638628383, 1378850404565127229, 1385453089338818651
]

#BETA
REPORT_CHANNEL_ID = [1378070194148217012, 1383418429460971520]

EPHEMERAL_REQUEST_LOG_CHANNEL_ID = 1385094756912205984

VERSION_CHANNEL_ID = 1457390424296521883
VERSION = "27.1 beta 3"
DESCRIPTION = "florrOS beta gives you an early preview of upcoming apps and features. This update provides bugfixes and other improvements."

TRIGGERS = ["manfred", "pehiley", "magic stick", "unique"]
EMOJI = "💲"

probabilities = {
    "common": 0.64,
    "unusual": 0.32,
    "rare": 0.16,
    "epic": 0.08,
    "legendary": 0.04,
    "mythic": 0.02,
    "ultra": 0.01
}

rarity_order = ["common", "unusual", "rare", "epic", "legendary", "mythic", "ultra"]

next_rarity_colors = {
    "common": 0xFFE65D,
    "unusual": 0x4D52E3,
    "rare": 0x861FDE,
    "epic": 0xDE1F1F,
    "legendary": 0x1FDBDD,
    "mythic": 0xFF2B75,
    "ultra": 0x2BFFA3
}

# GLOBAL VARIABLES FOR PERSISTENT DATA
data_list = []
channel_list_states = {}
DEFAULT_PERSISTENT_SORT_KEY = "sort_config_item"

SECONDS_IN_WEEK = 604800
MAX_MESSAGE_LENGTH = 1900

INITIAL_DATA_LIST = []
# --- END CONFIGURATION ---
def expected_successes(petals: int, chance: float) -> float:
    if petals < 5:
        return 0.0
    return (petals - 2.5 * (1 - chance)) / ((2.5 / chance) + 2.5)

# --- CLIENT SETUP ---
intents = discord.Intents.default()
intents.messages = True
# intents.message_content = True # <-- REMOVED: This was causing the "unavailable scope" invite error.
intents.guilds = True
intents.members = True # KEEP THIS: This intent is required for slash command context and MUST be enabled in the Developer Portal.
client = commands.Bot(command_prefix="!", intents=intents)
tree = client.tree

# --- UTILITY FUNCTIONS ---

def format_join_code(server_id: str) -> str:
    # Zorgt dat het ALTIJD exact correct geformatteerd wordt
    server_id = str(server_id).strip()
    return f'cp6.forceServerID("{server_id}")'

last_updated_item_details = {"item_val": None, "name_val": None, "cost_val": None}
view_message_tracker = {}

def is_admin(user_id: int):
    """Checks if a user ID is in the global ADMIN_USER_IDS list."""
    return user_id in ADMIN_USER_IDS

# Helper function for the new 'Owner' sort (FIXED for stability)
def sort_by_owner_tally(data):
    if not data:
        return []
    name_counts = Counter(row[1].lower() for row in data)
    def custom_sort_key(row):
        name = row[1].lower()
        # Safely convert cost to int, defaulting to 0
        try:
            cost = int(row[2])
        except (IndexError, ValueError):
            cost = 0
        return (-name_counts[name], name, -cost)
    return sorted(data, key=custom_sort_key)


SORT_CONFIGS = {
    "sort_config_item": {
        "label": "by Item", "button_label": "Sort: Item",
        "sort_lambda": lambda data: sorted(data, key=lambda x: (x[0].lower(), x[1].lower())),
        "column_order_indices": [0, 1, 2], "headers": ["Item", "Name", "Cost"]
    },
    "sort_config_name": {
        "label": "by Name", "button_label": "Sort: Name",
        "sort_lambda": lambda data: sorted(data, key=lambda x: (x[1].lower(), x[0].lower())),
        "column_order_indices": [1, 0, 2], "headers": ["Name", "Item", "Cost"]
    },
    "sort_config_cost": {
        "label": "by Cost", "button_label": "Sort: Cost",
        "sort_lambda": lambda data: sorted(data, key=lambda x: (int(x[2]) if str(x[2]).isdigit() else 0, x[0].lower())),
        "column_order_indices": [2, 0, 1], "headers": ["Cost", "Item", "Name"]
    },
    "sort_config_recent": {
        "label": "by Recent (Last 7 Days)", "button_label": "Sort: Recent",
        "sort_lambda": lambda data: [
            row for row in data
            if len(row) > 3 and row[3] >= (time.time() - SECONDS_IN_WEEK)
        ][::-1],
        "column_order_indices": [0, 1, 2], "headers": ["Item", "Name", "Cost (7 Days)"]
    },
    "sort_config_owner": {
        "label": "by Owner Count", "button_label": "Sort: Owner",
        "sort_lambda": sort_by_owner_tally,
        "column_order_indices": [1, 0, 2], "headers": ["Name", "Item", "Cost"]
    }
}

UPDATE_NOTIFICATION_CONFIG = [
    {
        "channel_id": 1349793261908262942,
        "message_format": "{item_val} - {name_val} - {cost_val}\n{role_ping}",
        "role_id_to_ping": 1357477336282566766
    },
    {
        "channel_id": 1378070194148217012,
        "message_format": "{name_val} - {item_val} - {cost_val}\n{role_ping}",
        "role_id_to_ping": 1378071231252926514
    },
    {
        "channel_id": 1383418429460971520,
        "message_format": "{name_val} - {item_val} - {cost_val}\n{role_ping}",
        "role_id_to_ping": 1271018797238583337
    },
]

# --- DATA PERSISTENCE FUNCTIONS ---
def load_data_list():
    """Loads item list data AND channel state data from the JSON file."""
    global data_list
    global channel_list_states

    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                loaded_data = json.load(f)

                if isinstance(loaded_data, dict) and "list_data" in loaded_data and isinstance(loaded_data["list_data"], list):
                    data_list = loaded_data["list_data"]
                elif isinstance(loaded_data, list):
                    data_list = loaded_data
                else:
                    data_list = list(INITIAL_DATA_LIST)

                if isinstance(loaded_data, dict) and "state_data" in loaded_data and isinstance(loaded_data["state_data"], dict):
                    raw_states = loaded_data["state_data"].get("channel_list_states", {})
                    channel_list_states = {int(k): v for k, v in raw_states.items() if str(k).isdigit()}
                else:
                    channel_list_states = {}

        except (IOError, json.JSONDecodeError) as e:
            data_list = list(INITIAL_DATA_LIST)
            channel_list_states = {}
    else:
        data_list = list(INITIAL_DATA_LIST)
        channel_list_states = {}

    for row in data_list:
        if len(row) > 2:
            row[2] = str(row[2])
        if len(row) < 4:
            row.append(0)

def save_data_list():
    """Saves item list data AND channel state data to the JSON file."""
    global data_list
    global channel_list_states

    data_to_save = {
        "list_data": data_list,
        "state_data": {
            "channel_list_states": channel_list_states
        }
    }

    try:
        temp_data_file = DATA_FILE + ".tmp"
        with open(temp_data_file, "w") as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_data_file, DATA_FILE)
    except (IOError, TypeError) as e:
        print(f"ERROR: Failed to save data to {DATA_FILE}: {e}")

# --- BOT STATE (CRASH/RESTART) HANDLING ---
prev_shutdown_info = {}

def load_bot_state():
    global prev_shutdown_info
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                prev_shutdown_info = json.load(f)
        except Exception:
            prev_shutdown_info = {}
    else:
        prev_shutdown_info = {}
    return prev_shutdown_info

def save_bot_state(state: dict):
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"ERROR: Failed to save bot state to {STATE_FILE}: {e}")

def mark_clean_shutdown():
    st = {"last_state": "stopped_clean", "timestamp": int(time.time()), "pid": os.getpid()}
    save_bot_state(st)

def mark_unclean_shutdown(reason: str = None):
    st = {"last_state": "stopped_unclean", "timestamp": int(time.time()), "pid": os.getpid(), "reason": reason}
    save_bot_state(st)

def _signal_handler(sig, frame):
    try:
        mark_clean_shutdown()
    except Exception:
        pass
    try:
        sys.exit(0)
    except SystemExit:
        raise

def register_signal_handlers():
    try:
        signal.signal(signal.SIGINT, _signal_handler)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        pass
    atexit.register(mark_clean_shutdown)

# Coroutine to send a crash embed; executed from on_ready where client is available
async def send_bot_crash_embed(prev_info: dict):
    try:
        channel = client.get_channel(VERSION_CHANNEL_ID)
        if not channel:
            return
        descr = "Previous run did not shut down cleanly."
        if prev_info and prev_info.get("reason"):
            descr += f"\nReason: {prev_info.get('reason')}"
        embed = discord.Embed(title="Bot Crashed", description=descr, color=0xFF4444)
        embed.add_field(name="Version", value=VERSION)
        if prev_info and prev_info.get("timestamp"):
            try:
                ts = int(prev_info.get("timestamp"))
                embed.add_field(name="Previous Timestamp", value=f"<t:{ts}:F>")
            except Exception:
                pass
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)
    except Exception:
        pass

# --- END BOT STATE HANDLING ---

# --- VIEW CLASSES ---

class EphemeralListView(View):
    def __init__(self, initial_sort_key: str, timeout=300):
        super().__init__(timeout=timeout)
        self.current_sort_key = initial_sort_key
        self._update_button_states()

    def _update_button_states(self):
        for child in self.children:
            if isinstance(child, Button):
                if child.custom_id == f"ephem_btn_{self.current_sort_key}":
                    child.disabled = True
                    child.style = ButtonStyle.success
                else:
                    child.disabled = False
                    child.style = ButtonStyle.secondary

    async def _update_ephemeral_message(self, interaction: discord.Interaction, new_sort_key: str):
        self.current_sort_key = new_sort_key
        self._update_button_states()
        full_content_parts = format_sorted_list_content(new_sort_key, is_ephemeral=True)
        try:
            content_to_send = full_content_parts[0] if isinstance(full_content_parts, list) else full_content_parts
            await interaction.response.edit_message(content=content_to_send, view=self)
        except discord.HTTPException as e:
            pass

    @button(label=SORT_CONFIGS["sort_config_item"]["button_label"], style=ButtonStyle.secondary, custom_id="ephem_btn_sort_config_item")
    async def sort_item_btn_e(self, i: discord.Interaction, b: Button):
        await self._update_ephemeral_message(i, "sort_config_item")

    @button(label=SORT_CONFIGS["sort_config_name"]["button_label"], style=ButtonStyle.secondary, custom_id="ephem_btn_sort_config_name")
    async def sort_name_btn_e(self, i: discord.Interaction, b: Button):
        await self._update_ephemeral_message(i, "sort_config_name")

    @button(label=SORT_CONFIGS["sort_config_cost"]["button_label"], style=ButtonStyle.secondary, custom_id="ephem_btn_sort_config_cost")
    async def sort_cost_btn_e(self, i: discord.Interaction, b: Button):
        await self._update_ephemeral_message(i, "sort_config_cost")

    @button(label=SORT_CONFIGS["sort_config_recent"]["button_label"], style=ButtonStyle.secondary, custom_id="ephem_btn_sort_recent")
    async def sort_recent_btn_e(self, i: discord.Interaction, b: Button):
        await self._update_ephemeral_message(i, "sort_config_recent")

    @button(label=SORT_CONFIGS["sort_config_owner"]["button_label"], style=ButtonStyle.secondary, custom_id="ephem_btn_sort_config_owner")
    async def sort_owner_btn_e(self, i: discord.Interaction, b: Button):
        await self._update_ephemeral_message(i, "sort_config_owner")

    async def on_timeout(self):
        pass


class PersistentListPromptView(View):
    def __init__(self, target_channel_id: int, timeout=None):
        super().__init__(timeout=timeout)
        self.target_channel_id = target_channel_id

    async def _send_ephemeral_sorted_list(self, interaction: discord.Interaction, sort_key: str):
        if EPHEMERAL_REQUEST_LOG_CHANNEL_ID and EPHEMERAL_REQUEST_LOG_CHANNEL_ID != 0:
            log_channel = client.get_channel(EPHEMERAL_REQUEST_LOG_CHANNEL_ID)
            if log_channel:
                try:
                    log_message = (
                        f"📋 Ephemeral list generated:\n"
                        f"▫️ **User:** {interaction.user.mention} (ID: `{interaction.user.id}`)\n"
                        f"▫️ **Requested Sort:** `{SORT_CONFIGS[sort_key]['label']}`\n"
                        f"▫️ **Interaction Channel:** <#{interaction.channel_id}>"
                    )
                    await log_channel.send(log_message)
                except:
                    pass

        full_content_parts = format_sorted_list_content(sort_key, is_ephemeral=True)
        ephemeral_view = EphemeralListView(initial_sort_key=sort_key)
        try:
            content_to_send = full_content_parts[0] if isinstance(full_content_parts, list) else full_content_parts
            await interaction.response.send_message(content=content_to_send, view=ephemeral_view, ephemeral=True)
        except Exception as e:
            try:
                await interaction.followup.send("Sorry, I couldn't generate your list view at this time.", ephemeral=True)
            except:
                pass

    @button(label=SORT_CONFIGS["sort_config_item"]["button_label"], style=ButtonStyle.primary, custom_id="persist_btn_sort_item")
    async def sort_item_btn_p(self, i: discord.Interaction, b: Button):
        await self._send_ephemeral_sorted_list(i, "sort_config_item")

    @button(label=SORT_CONFIGS["sort_config_name"]["button_label"], style=ButtonStyle.primary, custom_id="persist_btn_sort_name")
    async def sort_name_btn_p(self, i: discord.Interaction, b: Button):
        await self._send_ephemeral_sorted_list(i, "sort_config_name")

    @button(label=SORT_CONFIGS["sort_config_cost"]["button_label"], style=ButtonStyle.primary, custom_id="persist_btn_sort_cost")
    async def sort_cost_btn_p(self, i: discord.Interaction, b: Button):
        await self._send_ephemeral_sorted_list(i, "sort_config_cost")

    @button(label=SORT_CONFIGS["sort_config_recent"]["button_label"], style=ButtonStyle.primary, custom_id="persist_btn_sort_recent")
    async def sort_recent_btn_p(self, i: discord.Interaction, b: Button):
        await self._send_ephemeral_sorted_list(i, "sort_config_recent")

    @button(label=SORT_CONFIGS["sort_config_owner"]["button_label"], style=ButtonStyle.primary, custom_id="persist_btn_sort_owner")
    async def sort_owner_btn_p(self, i: discord.Interaction, b: Button):
        await self._send_ephemeral_sorted_list(i, "sort_config_owner")

    async def on_timeout(self):
        pass

@client.command(name="server_close")
@commands.has_any_role("Moderator", "Developer - CEO", "Owner", "Admin", "Bot manager")
async def server_close(ctx: commands.Context):
    channel = discord.utils.get(ctx.guild.text_channels, name="versions")
    if channel:
        embed = discord.Embed(
            title="Server Closing Soon",
            description="The server will close in 10 seconds. /ban @everyone funny",
            color=0xFF4444
        )
        await channel.send(embed=embed)
        await ctx.send("Close message sent to #versions")
    else:
        await ctx.send("No #versions channel found.")

# --- LIST FORMATTING AND UPDATE FUNCTIONS ---

def _update_last_changed_details(item_val, name_val, cost_val):
    global last_updated_item_details
    last_updated_item_details = {"item_val": item_val, "name_val": name_val, "cost_val": cost_val}

def update_data_for_auto(item_val, name_val):
    global data_list
    found_idx = -1
    final_cost = "1"
    for i, row in enumerate(data_list):
        if row[0].lower() == item_val.lower():
            found_idx = i
            break

    current_time_epoch = time.time()

    if found_idx != -1:
        existing_row = data_list.pop(found_idx)
        existing_row[1] = name_val
        try:
            final_cost = str(int(existing_row[2]) + 1)
        except ValueError:
            final_cost = "1"
        existing_row[2] = final_cost
        existing_row[3] = current_time_epoch
        data_list.append(existing_row)
    else:
        new_row = [item_val, name_val, final_cost, current_time_epoch]
        data_list.append(new_row)

    _update_last_changed_details(item_val, name_val, final_cost)
    save_data_list()
    return final_cost

def format_list_for_display(data, col_indices, headers):
    if not data: return []
    widths = [len(h) for h in headers]
    for r in data:
        disp_row = [str(r[i]) for i in col_indices]
        for i, val in enumerate(disp_row):
            widths[i] = max(widths[i], len(val))
    padding = [2] * len(widths)
    total_line_length = sum(widths) + sum(padding) - padding[-1]
    if total_line_length > MAX_MESSAGE_LENGTH - 50:
        padding = [1] * len(widths)
        total_line_length = sum(widths) + sum(padding) - padding[-1]
    header_line = " ".join(f"{headers[i]:<{widths[i]}}" for i in range(len(headers)))
    message_parts = []
    current_part_lines = [header_line]
    current_length = len(header_line)
    for row in data:
        disp_row = [str(row[i]) for i in col_indices]
        line = " ".join(f"{disp_row[i]:<{widths[i]}}" for i in range(len(headers)))
        if current_length + len(line) + 1 + 100 > MAX_MESSAGE_LENGTH:
            message_parts.append("\n".join(current_part_lines))
            current_part_lines = [header_line, line]
            current_length = len(header_line) + len(line) + 1
        else:
            current_part_lines.append(line)
            current_length += len(line) + 1
    if current_part_lines:
        message_parts.append("\n".join(current_part_lines))
    return message_parts

def format_sorted_list_content(sort_key: str, is_ephemeral: bool = False):
    sort_details = SORT_CONFIGS[sort_key]
    list_data_source = data_list
    processed_data = []
    current_epoch = int(time.time())
    timestamp_base = f"<t:{current_epoch}:F> (<t:{current_epoch}:R>)"

    if sort_key == "sort_config_recent":
        processed_data = sort_details["sort_lambda"](list_data_source)
        if not processed_data:
            empty_msg = "No items have been updated in the last 7 days."
            timestamp_line = f"{empty_msg}\nLast Updated: {timestamp_base} (Sorted {sort_details['label']})"
            return [timestamp_line]
        formatted_text_parts = format_list_for_display(processed_data,
                                                       sort_details["column_order_indices"],
                                                       sort_details["headers"])
    else:
        if not list_data_source:
            timestamp_line = f"The list is currently empty.\nLast Updated: {timestamp_base} (List is Empty)"
            return [timestamp_line]
        processed_data = sort_details["sort_lambda"](list_data_source)
        if not processed_data:
            timestamp_line = f"The list is empty after applying the sort/filter.\nLast Updated: {timestamp_base} (List is Empty)"
            return [timestamp_line]
        formatted_text_parts = format_list_for_display(processed_data,
                                                       sort_details["column_order_indices"],
                                                       sort_details["headers"])

    final_message_parts = []
    ts_msg_base = f"(Sorted {sort_details['label']})"
    code_block_overhead = 8

    for i, part in enumerate(formatted_text_parts):
        part_header = ""
        if len(formatted_text_parts) > 1:
            part_header = f"Part {i+1}/{len(formatted_text_parts)} - "

        timestamp_line = f"Last Updated: {timestamp_base} | {part_header}{ts_msg_base}"
        content_length_with_meta = len(timestamp_line) + len(part) + code_block_overhead + 1
        if content_length_with_meta > MAX_MESSAGE_LENGTH:
            final_message_parts.append(f"List is too large to display. Please contact an admin.")
            break

        final_message_parts.append(f"{timestamp_line}\n```\n{part}\n```")

    return final_message_parts if final_message_parts else ["The list is currently empty."]


async def send_or_edit_persistent_list_prompt(target_channel_id: int, force_new: bool = False):
    global channel_list_states
    if target_channel_id not in channel_list_states:
        channel_list_states[target_channel_id] = {"message_ids": [], "default_sort_key_for_display": DEFAULT_PERSISTENT_SORT_KEY}

    state = channel_list_states[target_channel_id]
    msg_ids = state.get("message_ids", [])
    default_sort = state.get("default_sort_key_for_display", DEFAULT_PERSISTENT_SORT_KEY)

    channel = client.get_channel(target_channel_id)
    if not channel:
        if state["message_ids"]:
            state["message_ids"] = []
            save_data_list()
        return

    content_parts = format_sorted_list_content(default_sort, is_ephemeral=False)
    view = PersistentListPromptView(target_channel_id=target_channel_id)

    ids_changed = False
    if force_new or len(msg_ids) != len(content_parts):
        ids_changed = True
        for msg_id in msg_ids:
            try:
                old_msg = await channel.fetch_message(msg_id)
                await old_msg.delete()
            except:
                pass
            if msg_id in view_message_tracker:
                del view_message_tracker[msg_id]
        msg_ids = []
        state["message_ids"] = []

    sent_messages = []
    for i, content in enumerate(content_parts):
        if i < len(msg_ids):
            try:
                m = await channel.fetch_message(msg_ids[i])
                if i == 0:
                    await m.edit(content=content, view=view)
                    view_message_tracker[m.id] = ("PersistentListPromptView", target_channel_id)
                else:
                    await m.edit(content=content, view=None)
                sent_messages.append(m.id)
            except (discord.NotFound, Exception):
                ids_changed = True
                new_m = None
                if i == 0 and not sent_messages:
                    new_m = await channel.send(content=content, view=view)
                    view_message_tracker[new_m.id] = ("PersistentListPromptView", target_channel_id)
                else:
                    new_m = await channel.send(content=content, view=None)
                sent_messages.append(new_m.id)
        else:
            ids_changed = True
            try:
                new_m = None
                if i == 0 and not msg_ids:
                    new_m = await channel.send(content=content, view=view)
                    view_message_tracker[new_m.id] = ("PersistentListPromptView", target_channel_id)
                else:
                    new_m = await channel.send(content=content, view=None)
                sent_messages.append(new_m.id)
            except Exception as e:
                pass

        await asyncio.sleep(0.5)

    for old_msg_id in msg_ids[len(content_parts):]:
        ids_changed = True
        try:
            old_msg = await channel.fetch_message(old_msg_id)
            await old_msg.delete()
        except:
            pass
        if old_msg_id in view_message_tracker:
            del view_message_tracker[old_msg_id]

    if set(state["message_ids"]) != set(sent_messages):
        ids_changed = True

    state["message_ids"] = sent_messages

    if ids_changed:
        save_data_list()


async def update_all_persistent_list_prompts(force_new: bool = False):
    """Iterates through all configured channels and calls the update/edit function."""
    for cid in INTERACTIVE_LIST_TARGET_CHANNEL_IDS:
        if cid and isinstance(cid, int):
            await send_or_edit_persistent_list_prompt(cid, force_new)
        await asyncio.sleep(1)


async def clear_all_persistent_list_prompts():
    """Deletes all messages and clears the state in memory AND file."""
    for cid in list(channel_list_states.keys()):
        state = channel_list_states[cid]
        msg_ids = state.get("message_ids", [])
        for msg_id in msg_ids:
            if not msg_id: continue
            channel = client.get_channel(cid)
            if not channel:
                state["message_ids"] = []
                continue
            try:
                m = await channel.fetch_message(msg_id)
                await m.delete()
            except:
                pass
            if msg_id in view_message_tracker:
                del view_message_tracker[msg_id]
            await asyncio.sleep(0.5)
        state["message_ids"] = []
    save_data_list()


async def send_custom_update_notifications(item_val, name_val, cost_val):
    """Sends a notification to all configured channels."""
    for cfg in UPDATE_NOTIFICATION_CONFIG:
        cid, fmt, rid = cfg.get("channel_id"), cfg.get("message_format"), cfg.get("role_id_to_ping")
        if not cid or not fmt or cid == 0: continue
        chan = client.get_channel(cid)
        if not chan: continue

        p_str = ""
        if rid and rid != 0 and chan.guild:
            role = chan.guild.get_role(rid)
            p_str = role.mention if role else ""
        try:
            content = fmt.format(item_val=item_val, name_val=name_val, cost_val=cost_val, role_ping=p_str)
        except KeyError as e:
            continue
        try:
            mentions = discord.AllowedMentions.none()
            if rid and rid != 0 and p_str:
                mentions.roles = [discord.Object(id=rid)]
            await chan.send(content, allowed_mentions=mentions)
        except Exception as e:
            pass
        await asyncio.sleep(0.5)

# --- SLASH COMMANDS ---

list_group = app_commands.Group(name="list", description="Admin commands for managing the unique list and bot state.")

@list_group.command(name="restart", description="Forces a complete delete and re-create of the list messages.")
async def list_restart(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    try:
        await update_all_persistent_list_prompts(force_new=True)
        await interaction.followup.send("🔄 Bot list messages restarted and re-synced successfully. All old messages were deleted.")
    except Exception as e:
        await interaction.followup.send(f"❌ Restart failed: {e}")

@list_group.command(name="close", description="Deletes all persistent list messages and clears the stored message IDs.")
async def list_close(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    try:
        await clear_all_persistent_list_prompts()
        await interaction.followup.send("🗑️ All list displays cleared and state saved.")
    except Exception as e:
        await interaction.followup.send(f"❌ Close command failed: {e}")

@list_group.command(name="add", description="Manually adds or updates a list item.")
@app_commands.describe(
    item="The name of the unique item.",
    name="The player's name.",
    cost="The cost count. Defaults to 1 or increments if item exists."
)
async def list_add(interaction: discord.Interaction, item: str, name: str, cost: app_commands.Range[int, 1] = None):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    global data_list
    found_idx = -1
    final_cost = str(cost) if cost is not None else "1"
    resp = ""

    for i, r in enumerate(data_list):
        if r[0].lower() == item.lower():
            found_idx = i
            break

    current_time_epoch = time.time()

    if found_idx != -1:
        row_to_update = data_list.pop(found_idx)
        row_to_update[1] = name
        if cost is None:
            try:
                final_cost = str(int(row_to_update[2]) + 1)
            except:
                final_cost = "1"
        row_to_update[2] = final_cost
        row_to_update[3] = current_time_epoch
        data_list.append(row_to_update)
        resp = f"✅ Updated Item **'{item}'**. Name:'{name}', Cost:{final_cost}."
    else:
        new_row = [item, name, final_cost, current_time_epoch]
        data_list.append(new_row)
        resp = f"✅ Added Item **'{item}'**. Name:'{name}', Cost:{final_cost}."

    _update_last_changed_details(item, name, final_cost)
    save_data_list()
    await update_all_persistent_list_prompts()
    await interaction.followup.send(resp)

@list_group.command(name="delete", description="Deletes a unique item from the list by name.")
@app_commands.describe(item="The name of the unique item to delete.")
async def list_delete(interaction: discord.Interaction, item: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    global data_list
    original_len = len(data_list)
    data_list = [r for r in data_list if r[0].lower() != item.lower()]

    if len(data_list) < original_len:
        if last_updated_item_details.get("item_val") and \
           last_updated_item_details["item_val"].lower() == item.lower():
            _update_last_changed_details(None, None, None)
        save_data_list()
        await update_all_persistent_list_prompts()
        await interaction.followup.send(f"✅ Item **'{item}'** deleted.")
    else:
        await interaction.followup.send(f"❓ Item **'{item}'** not found.")

@list_group.command(name="announce", description="Re-sends the last recorded item update notification to configured channels.")
async def list_announce(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    item, name, cost = last_updated_item_details.get("item_val"), last_updated_item_details.get("name_val"), last_updated_item_details.get("cost_val")
    if item and name and cost is not None:
        await send_custom_update_notifications(item, name, cost)
        await interaction.followup.send(f"📢 Re-announced last update: Item: **{item}**, Name: **{name}**, Cost: **{cost}**.")
    else:
        await interaction.followup.send("❓ No recent update (with cost) to announce.")

@list_group.command(name="say", description="Sends a message to all configured announcement channels (UPDATE_NOTIFICATION_CONFIG).")
@app_commands.describe(message="The message to be sent.")
async def list_say(interaction: discord.Interaction, message: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    sent_to_channels = []

    for cfg in UPDATE_NOTIFICATION_CONFIG:
        cid = cfg.get("channel_id")
        if not cid or cid == 0: continue
        chan = client.get_channel(cid)
        if not chan: continue

        try:
            await chan.send(message)
            sent_to_channels.append(chan.name if hasattr(chan, 'name') else str(cid))
        except:
            pass
        await asyncio.sleep(0.5)

    if sent_to_channels:
        await interaction.followup.send(f"✅ Your message was sent to: {', '.join(sent_to_channels)}.")
    else:
        await interaction.followup.send("❌ Could not send your message to any configured channels.")

@list_group.command(name="message", description="Sends a message to a specific channel using Server ID and Channel ID.")
@app_commands.describe(
    server_id="The ID of the target server (Guild).",
    channel_id="The ID of the target text channel.",
    message="The message content."
)
async def list_message(interaction: discord.Interaction, server_id: str, channel_id: str, message: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    
    if not (server_id.isdigit() and channel_id.isdigit()):
        await interaction.followup.send("❌ Server ID and Channel ID must be valid numerical IDs.")
        return

    try:
        s_id = int(server_id)
        c_id = int(channel_id)
    except ValueError:
        await interaction.followup.send("❌ Server ID and Channel ID must be valid numerical IDs.")
        return

    guild = client.get_guild(s_id)
    if not guild:
        await interaction.followup.send(f"❌ Server not found or bot is not in server with ID: `{server_id}`")
        return

    channel = guild.get_channel(c_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.followup.send(f"❌ Channel not found, or it's not a text channel in server `{guild.name}` with ID: `{channel_id}`")
        return

    if not channel.permissions_for(guild.me).send_messages:
        await interaction.followup.send(f"❌ I do not have permissions to send messages in channel `{channel.name}` on server `{guild.name}`.")
        return

    try:
        await channel.send(message)
        await interaction.followup.send(f"✅ Message successfully sent to <#{channel.id}> on server **{guild.name}**.")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to send message: An unexpected error occurred. Details: `{e}`")

@list_group.command(name="raw", description="Outputs the complete list data in JSON format for debugging.")
async def list_raw(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    global data_list
    if not data_list:
        await interaction.followup.send("`data_list` is empty.")
        return

    raw_json = json.dumps(data_list, indent=2)
    MAX_CONTENT_CHUNK_SIZE = MAX_MESSAGE_LENGTH - 150
    chunks = []
    i = 0
    while i < len(raw_json):
        chunk = raw_json[i:i + MAX_CONTENT_CHUNK_SIZE]
        chunks.append(chunk)
        i += MAX_CONTENT_CHUNK_SIZE

    total_parts = len(chunks)
    for i, chunk in enumerate(chunks):
        part_number = i + 1
        header_text = f"Raw List Data (Part {part_number}/{total_parts})" if total_parts > 1 else "Raw List Data"
        msg_content = f"{header_text}\n```json\n{chunk}\n```"
        if i == 0:
            await interaction.followup.send(msg_content)
        else:
            await interaction.channel.send(msg_content)
        await asyncio.sleep(0.5)

@list_group.command(
    name="importjson",
    description="Imports a complete JSON array into the list (replaces current data) and shows changes."
)
@app_commands.describe(json_data="A JSON array of items, e.g., [[\"Item1\",\"Player1\",1],[\"Item2\",\"Player2\",3]]")
async def list_importjson(interaction: discord.Interaction, json_data: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ Access Denied. You must be a bot admin to use this command.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    global data_list
    try:
        loaded = json.loads(json_data)
        if not isinstance(loaded, list):
            raise ValueError("JSON is not a list.")

        # Validate items and ensure timestamp
        for idx, row in enumerate(loaded):
            if not isinstance(row, list) or len(row) < 3:
                raise ValueError(f"Row {idx} is invalid. Each row must be a list of at least 3 elements: [Item, Name, Cost].")
            row[2] = str(row[2])
            if len(row) < 4:
                row.append(int(time.time()))

        # Maak overzicht van huidige eigenaars
        old_owners = {item[0]: item[1] for item in data_list}
        old_counts = {}
        for owner in [item[1] for item in data_list]:
            old_counts[owner] = old_counts.get(owner, 0) + 1

        # Update data_list
        data_list = loaded
        save_data_list()
        await update_all_persistent_list_prompts(force_new=True)

        # Nieuw overzicht van eigenaars
        new_owners = {item[0]: item[1] for item in data_list}
        new_counts = {}
        for owner in [item[1] for item in data_list]:
            new_counts[owner] = new_counts.get(owner, 0) + 1

        # Bepaal wijzigingen
        changes = []
        for item_name, new_owner in new_owners.items():
            old_owner = old_owners.get(item_name)
            if old_owner != new_owner:
                changes.append(f"{item_name} → {old_owner} -> {new_owner}")

        # Update counts only for affected users
        affected_users = set()
        for item_name, new_owner in new_owners.items():
            old_owner = old_owners.get(item_name)
            if old_owner != new_owner:
                affected_users.add(new_owner)
                if old_owner:
                    affected_users.add(old_owner)

        counts_changes = []
        for user in affected_users:
            old_count = old_counts.get(user, 0)
            new_count = new_counts.get(user, 0)
            if old_count != new_count:
                counts_changes.append(f"{user} : {old_count} uniques -> {new_count} uniques")

        # Combineer bericht
        msg = "✅ JSON successfully imported.\n"
        if changes:
            msg += "\n**Transferred items:**\n" + "\n".join(changes)
        if counts_changes:
            msg += "\n\n**Updated unique counts:**\n" + "\n".join(counts_changes)

        await interaction.followup.send(msg if changes or counts_changes else "JSON imported, no changes detected.")

    except json.JSONDecodeError:
        await interaction.followup.send("Invalid JSON format. Make sure it's a valid JSON array.")
    except ValueError as ve:
        await interaction.followup.send(f"JSON validation error: {ve}")
    except Exception as e:
        await interaction.followup.send(f"Unexpected error: {e}")

@list_group.command(
    name="announce_specific",
    description="Announces a specific item update to the configured channels."
)
@app_commands.describe(
    item="The name of the unique item.",
    name="The player's name.",
)
async def list_announce_specific(
    interaction: discord.Interaction, 
    item: str, 
    name: str, 
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ Access Denied. You must be a bot admin to use this command.", 
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    # Loop over de UPDATE_NOTIFICATION_CONFIG om in elk kanaal te posten
    for cfg in UPDATE_NOTIFICATION_CONFIG:
        cid, fmt, rid = cfg.get("channel_id"), cfg.get("message_format"), cfg.get("role_id_to_ping")
        if not cid or not fmt or cid == 0:
            continue
        chan = client.get_channel(cid)
        if not chan:
            continue

        # role mention string
        role_mention = ""
        if rid and rid != 0 and chan.guild:
            role = chan.guild.get_role(rid)
            role_mention = role.mention if role else ""

        # format message exactly like: Item - Name - Cost\n@Role
        try:
            embed = discord.Embed(
                title=f"The Unique {item} has been forged by {name}!",
                description=f"{role_mention} A moderator just announced a forge.",
                color=0xFF4444
            )
            embed.set_footer(text="florrForge 27.1 beta 3")
            await chan.send(embed=embed)
        except Exception:
            pass

    await interaction.followup.send(
        f"📢 Specific announcement sent: **{item} - {name}**"
    )

@list_group.command(
    name="report",
    description="This command is currently unavailable."
    #description="Announces a specific item update to the configured channels. Remember a false report is bannable!"
)
async def list_report(interaction: discord.Interaction):
    await interaction.response.send_message(
        "❌ This command is currently unavailable becuase of abuse.",
        ephemeral=True
    )

@list_group.command(name="server_codes", description="Show server codes for a specific map.")
@app_commands.describe(map="Choose a map.")
@app_commands.choices(map=[
    app_commands.Choice(name="Garden", value=0),
    app_commands.Choice(name="Desert", value=1),
    app_commands.Choice(name="Ocean", value=2),
    app_commands.Choice(name="Jungle", value=3),
    app_commands.Choice(name="Ant Hell", value=4),
    app_commands.Choice(name="Hel", value=5),
    app_commands.Choice(name="Sewers", value=6),
    app_commands.Choice(name="Factory", value=7),
    app_commands.Choice(name="Pyramid", value=8),
    app_commands.Choice(name="Ant hell", value=9),
])
async def green(interaction: discord.Interaction, map: app_commands.Choice[int]):
    await interaction.response.defer()

    api_url = BASE_URL.format(map.value)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as response:
                if response.status != 200:
                    await interaction.followup.send(f"API error (HTTP {response.status})", ephemeral=True)
                    return
                data = await response.json()
    except Exception as e:
        await interaction.followup.send(f"API request failed:\n```{e}```", ephemeral=True)
        return

    servers = data.get("servers", {})
    if not servers:
        await interaction.followup.send(f"No active servers found for {map.name}.", ephemeral=True)
        return

    # Regio mapping op basis van naam
    REGION_LABELS = {
        "miami": "🇺🇸 US",
        "frankfurt": "🇪🇺 EU",
        "tokyo": "🌏 AS",
    }

    embed = discord.Embed(
        title=f"{map.name} Server Codes",
        color=discord.Color.green()
    )

    for server_key, server_info in servers.items():
        server_id = server_info.get("id")
        if not server_id:
            continue

        # Zoek regio label op basis van sleutelwoord in server_key
        region = next((label for keyword, label in REGION_LABELS.items() if keyword in server_key), f"🌐 {server_key}")

        join_code = format_join_code(server_id)

        embed.add_field(
            name=region,
            value=f"ID: `{server_id}`\n```js\n{join_code}\n```",
            inline=False
        )

    embed.set_footer(text=f"florrForge {VERSION}")
    await interaction.followup.send(embed=embed)

@list_group.command(
    name="announce_version",
    description="Manually triggers a version announcement in the configured VERSION_CHANNEL_ID."
)
async def list_announce_version(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ Access Denied. You must be a bot admin to use this command.", 
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        await check_and_announce_version()
        await interaction.followup.send("Version announcement check completed.")
    except Exception as e:
        await interaction.followup.send(f"Version announcement failed: {e}")

@list_group.command(name="craft", description="Calculate crafting averages to the next rarity")
@app_commands.describe(
    rarity="Choose the current rarity",
    petals="Number of petals you want to use"
)
@app_commands.choices(rarity=[
    app_commands.Choice(name="Common", value="common"),
    app_commands.Choice(name="Unusual", value="unusual"),
    app_commands.Choice(name="Rare", value="rare"),
    app_commands.Choice(name="Epic", value="epic"),
    app_commands.Choice(name="Legendary", value="legendary"),
    app_commands.Choice(name="Mythic", value="mythic"),
    app_commands.Choice(name="Ultra", value="ultra")
])
async def craft(interaction: discord.Interaction, rarity: app_commands.Choice[str], petals: int):
    if petals < 0:
        await interaction.response.send_message("Please enter a positive number of petals.", ephemeral=True)
        return

    current_rarity = rarity.value
    index = rarity_order.index(current_rarity)
    next_rarity = "Super" if index == len(rarity_order) - 1 else rarity_order[index + 1].capitalize()
    result = expected_successes(petals, probabilities[current_rarity])
    color = next_rarity_colors[current_rarity]

    embed = discord.Embed(
        title=f"Crafting Calculator: {current_rarity.capitalize()} → {next_rarity}",
        color=color
    )
    embed.add_field(name="Current Rarity", value=current_rarity.capitalize(), inline=True)
    embed.add_field(name="Next Rarity", value=next_rarity, inline=True)
    embed.add_field(name="Petals", value=str(petals), inline=True)
    embed.add_field(name="Expected Result", value=f"{result:.2f}", inline=False)
    await interaction.response.send_message(embed=embed)


@list_group.command(name="guessgame", description="Guess crafting averages for a random rarity and amount")
async def guessgame(interaction: discord.Interaction):
    random_rarity = random.choice(rarity_order)
    random_petals = random.randint(5, 1000)
    expected = expected_successes(random_petals, probabilities[random_rarity])

    await interaction.response.send_message(
        f"🎮 Guess how many petals will craft from **{random_petals} {random_rarity.capitalize()} petals** to the next rarity! Type your guess as a number. You have 30 seconds."
    )

    def check(m: discord.Message):
        return m.author == interaction.user and m.channel.id == interaction.channel_id

    try:
        guess_msg = await client.wait_for("message", check=check, timeout=30.0)
        guess = float(guess_msg.content)
        difference = abs(guess - expected)
        percentage_error = (difference / expected) * 100

        if percentage_error <= 10:
            result_text = "Amazing! You were within 10% of the correct value!"
        elif percentage_error <= 25:
            result_text = "Not bad! You were within 25%."
        else:
            result_text = "Too far off, better luck next time."

        next_rarity = "Super" if random_rarity == "ultra" else rarity_order[rarity_order.index(random_rarity) + 1]

        embed = discord.Embed(
            title="Crafting Guess Game Results",
            description=f"You guessed: **{guess}**\nActual average: **{expected:.2f}**\n{result_text}",
            color=next_rarity_colors[random_rarity]
        )
        embed.add_field(name="Petals", value=str(random_petals))
        embed.add_field(name="Rarity", value=random_rarity.capitalize())
        embed.add_field(name="Next Rarity", value=next_rarity.capitalize())
        await interaction.followup.send(embed=embed)

    except asyncio.TimeoutError:
        await interaction.followup.send("Time's up! You didn't answer in time.")
    except ValueError:
        await interaction.followup.send("That's not a valid number!")

# --- BOT EVENTS ---

last_on_ready_timestamp = 0

@client.event
async def on_ready():
    global last_on_ready_timestamp
    current_time = time.time()
    if current_time - last_on_ready_timestamp < 60:
        return

    last_on_ready_timestamp = current_time

    print(f'{client.user.name} ({client.user.id}) connected!')

    tree.add_command(list_group)

    print("Syncing slash commands...")
    try:
        await tree.sync()
        print(f"Successfully synced {len(tree.get_commands())} slash commands.")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")

    print("Loading data and persistent message IDs from file...")
    load_data_list()

    print("Initializing channel states and updating persistent list prompts.")
    for cid in INTERACTIVE_LIST_TARGET_CHANNEL_IDS:
        if cid == 0 or not isinstance(cid, int):
            continue
        if cid not in channel_list_states:
            channel_list_states[cid] = {"message_ids": [], "default_sort_key_for_display": DEFAULT_PERSISTENT_SORT_KEY}

    await update_all_persistent_list_prompts(force_new=False)

    try:
        await check_and_announce_version()
    except Exception as e:
        print(f"Version announcement check failed: {e}")

    # If previous shutdown state wasn't clean, notify in the version channel
    try:
        if prev_shutdown_info and prev_shutdown_info.get("last_state") != "stopped_clean":
            await send_bot_crash_embed(prev_shutdown_info)
    except Exception:
        pass

    # Mark current run as active/running
    try:
        save_bot_state({"last_state": "running", "timestamp": int(time.time()), "pid": os.getpid()})
    except Exception:
        pass

@client.event
async def on_message(m: discord.Message):
    """
    Handles only the auto-update logic.
    Note: Since the message is from another bot (TARGET_BOT_ID_FOR_AUTO_UPDATES),
    the message content is accessible without the privileged message_content intent.
    """
    if m.author == client.user:
        return
    content = m.content.lower()
    if any(trigger in content for trigger in TRIGGERS):
        try:
            await m.add_reaction(EMOJI)
        except Exception as e:
            print("Reaction failed:", e)

    if random.randint(1, 100) == 1:
        await m.channel.send("Fun fact: Manfred is p2w")
    # ↑ TOT HIER

    # bestaande code blijft hieronder staan
    # Check for the target bot's automated message
    if m.author.id == TARGET_BOT_ID_FOR_AUTO_UPDATES:
        match = AUTO_UPDATE_MESSAGE_REGEX.search(m.content)
        if match:
            item_val, name_val = match.group(1).strip(), match.group(2).strip()
            updated_cost = update_data_for_auto(item_val, name_val)
            await update_all_persistent_list_prompts(force_new=False)
            await send_custom_update_notifications(item_val, name_val, updated_cost)
            return

# --- WEB SERVER AND MAIN EXECUTION ---

async def web_server():
    app = aiohttp.web.Application()
    app.router.add_get("/", lambda r: aiohttp.web.Response(text="Bot is running!"))
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = aiohttp.web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN environment variable not set. Please configure it on Render.")
        return

    # Load previous state and register shutdown handlers
    try:
        load_bot_state()
    except Exception:
        pass
    try:
        register_signal_handlers()
    except Exception:
        pass

    web_task = asyncio.create_task(web_server())
    try:
        await client.start(BOT_TOKEN)
    finally:
        web_task.cancel()

async def check_and_announce_version():
    # 1. Channel resolven (cache → fetch fallback)
    try:
        channel = client.get_channel(VERSION_CHANNEL_ID)
        if channel is None:
            channel = await client.fetch_channel(VERSION_CHANNEL_ID)
    except Exception as e:
        print(f"[VERSION] Failed to fetch channel {VERSION_CHANNEL_ID}: {e}")
        return

    # 2. Embed opbouwen
    desc = DESCRIPTION if DESCRIPTION else "No description provided."
    embed = discord.Embed(
        title=f"Version: {VERSION}",
        description=desc,
        color=0xA7A7A7
    )
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="The florrOS Project.")

    # 3. Role resolven (betrouwbaar)
    role_mention = ""
    allowed_mentions = discord.AllowedMentions.none()

    try:
        if channel.guild:
            role = discord.utils.get(channel.guild.roles, name="Version Notify")
            if role:
                role_mention = role.mention
                allowed_mentions = discord.AllowedMentions(roles=[discord.Object(id=role.id)])
            else:
                print("[VERSION] Role 'Version Notify' not found.")
    except Exception as e:
        print(f"[VERSION] Failed to resolve role: {e}")

    # 4. Bericht verzenden (geen silent drop)
    try:
        await channel.send(
            content=f"{role_mention} **@everyone A new bot version is available:** `{VERSION}`\n{DESCRIPTION}",
            embed=embed,
            allowed_mentions=allowed_mentions
        )
        print(f"[VERSION] Announcement sent successfully ({VERSION}).")
    except Exception as e:
        print(f"[VERSION] Failed to send version announcement: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot and web server stopped.")
    except Exception as e:
        # Record unclean shutdown reason and traceback
        try:
            tb = traceback.format_exc()
            mark_unclean_shutdown(tb)
        except Exception:
            pass
        print(f"An error occurred during startup: {e}")
