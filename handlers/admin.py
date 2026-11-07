"""System administration tools: registry, firewall, OS-level scheduled tasks, elevation.

No deterministic text routing here on purpose — "set this registry key" or "open port
8080" is too free-form and too high-stakes for a brittle regex to guess at. These are
exposed only as tools the language model can call (still confirm-gated), reached the
same way any other unmatched sentence reaches the model: through GENERAL/chat.
"""
from core.tools import params
from handlers.base import Handler


class AdminHandler(Handler):
    intents = set()          # tools only; never intercepts a deterministic route

    def handle(self, text, intent):
        return None

    def register_tools(self, t):
        admin = getattr(self.app, "system_admin", None)
        if admin is None:
            return

        t.add("is_admin", "Check whether JARVIS is currently running with administrator rights.",
              lambda: "yes" if admin.is_admin() else "no")
        t.add("run_elevated_command", "Run ONE command with administrator rights (one UAC prompt), "
              "without elevating JARVIS itself. Use for anything that needs admin and isn't covered "
              "by a more specific tool.", admin.request_elevated,
              params(["command"], command=("string", "The command to run, e.g. 'ipconfig /flushdns'")),
              confirm=True, confirm_text="Run this with administrator rights: {command}?")

        t.add("read_registry_value", "Read a Windows registry value.", admin.read_registry_value,
              params(["hive", "path", "name"],
                    hive=("string", "HKCU, HKLM, HKCR, HKU or HKCC"),
                    path=("string", r"Key path, e.g. 'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'"),
                    name=("string", "Value name")))
        t.add("write_registry_value", "Create or change a Windows registry value.", admin.write_registry_value,
              params(["hive", "path", "name", "value"],
                    hive=("string", "HKCU, HKLM, HKCR, HKU or HKCC"),
                    path=("string", "Key path"), name=("string", "Value name"),
                    value=("string", "New value"),
                    value_type=("string", "string, expand_string, dword, qword, multi_string or binary",
                               ("string", "expand_string", "dword", "qword", "multi_string", "binary"))),
              confirm=True, confirm_text="Set the registry value {hive}\\{path}\\{name} to '{value}'?")
        t.add("delete_registry_value", "Delete a Windows registry value.", admin.delete_registry_value,
              params(["hive", "path", "name"], hive=("string", "HKCU, HKLM, HKCR, HKU or HKCC"),
                    path=("string", "Key path"), name=("string", "Value name")),
              confirm=True, confirm_text="Delete the registry value {hive}\\{path}\\{name}?")

        t.add("list_firewall_rules", "List Windows Firewall rules, optionally filtered by name.",
              lambda name_filter="": admin.list_firewall_rules(name_filter),
              params(name_filter=("string", "Optional name filter")))
        t.add("add_firewall_rule", "Add a Windows Firewall rule to allow or block a port or program.",
              admin.add_firewall_rule,
              params(["name"], name=("string", "Rule name"),
                    direction=("string", "in or out", ("in", "out")),
                    action=("string", "allow or block", ("allow", "block")),
                    protocol=("string", "TCP or UDP", ("TCP", "UDP")),
                    port=("string", "Port number, if not targeting a program"),
                    program=("string", "Full path to a program, if not targeting a port")),
              confirm=True, confirm_text="Add a firewall rule '{name}'?")
        t.add("remove_firewall_rule", "Remove a Windows Firewall rule by name.", admin.remove_firewall_rule,
              params(["name"], name=("string", "Rule name")),
              confirm=True, confirm_text="Remove the firewall rule '{name}'?")

        t.add("list_scheduled_tasks", "List Windows Task Scheduler tasks (OS-level, not JARVIS's own "
              "reminders), optionally filtered by name.", lambda query="": admin.list_scheduled_tasks(query),
              params(query=("string", "Optional name filter")))
        t.add("create_scheduled_task", "Create a Windows Task Scheduler task that runs a command on a "
              "schedule (OS-level — for JARVIS's own reminders/alarms use the schedule tools instead).",
              admin.create_scheduled_task,
              params(["name", "command"], name=("string", "Task name"), command=("string", "Command to run"),
                    schedule=("string", "ONCE, MINUTE, HOURLY, DAILY, WEEKLY, MONTHLY, ONLOGON or ONSTART"),
                    start_time=("string", "HH:MM start time, if relevant")),
              confirm=True, confirm_text="Create a scheduled task '{name}' that runs: {command}?")
        t.add("delete_scheduled_task", "Delete a Windows Task Scheduler task by name.",
              admin.delete_scheduled_task, params(["name"], name=("string", "Task name")),
              confirm=True, confirm_text="Delete the scheduled task '{name}'?")
