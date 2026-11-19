"""Connectors (Figma, ClickUp, Jira, Sentry, MCP servers), the files you attach in a chat, and the team's tools for them.

    uv run python -m unittest tests/test_connectors.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from hive import connectors, store, uploads
from hive.agents import AgentManager
from hive.main import TOKEN, create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

HEADERS = {"x-token": TOKEN}
TOOLS = store.KIT / "team" / "tools"
sys.path.insert(0, str(TOOLS))
import clickup  # noqa: E402
import connlib  # noqa: E402
import figma  # noqa: E402
import files  # noqa: E402
import jira  # noqa: E402
import sentry  # noqa: E402
import tickets  # noqa: E402


class Isolated(unittest.TestCase):
    """Settings in a temporary folder, for the console and the team's tools alike."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        self.tmp = tmp
        for target, attr, value in ((store, "SETTINGS", tmp / "settings.json"), (connlib, "SETTINGS", tmp / "settings.json"),
                                    (uploads, "UPLOADS", tmp / "uploads"), (files, "UPLOADS", tmp / "uploads")):
            original = getattr(target, attr)
            setattr(target, attr, value)
            self.addCleanup(setattr, target, attr, original)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in ("FIGMA_TOKEN", "CLICKUP_TOKEN", "JIRA_SITE", "JIRA_EMAIL", "JIRA_TOKEN", "SENTRY_TOKEN", "SENTRY_URL", "AGENT_ID"):
            os.environ.pop(name, None)


class ConnectorSettingsTest(Isolated):

    def test_a_token_is_kept_but_never_shown_again(self):
        connectors.save("figma", {"fields": {"token": "figd_secret_abcd"}})

        shown = connectors.public()["figma"]

        self.assertTrue(shown["connected"])
        self.assertEqual(shown["fields"]["token"], {**shown["fields"]["token"], "set": True, "hint": "abcd"})
        self.assertNotIn("figd_secret_abcd", json.dumps(connectors.public()))
        self.assertEqual(connectors.config("figma")["token"], "figd_secret_abcd")

    def test_saving_without_a_token_keeps_the_saved_one(self):
        connectors.save("figma", {"fields": {"token": "figd_one"}})
        connectors.save("figma", {"fields": {"token": ""}, "roles": ["dev"]})

        self.assertEqual(connectors.config("figma")["token"], "figd_one")
        self.assertEqual(connectors.config("figma")["roles"], ["dev"])

    def test_the_servers_environment_wins(self):
        connectors.save("figma", {"fields": {"token": "from-settings"}})
        os.environ["FIGMA_TOKEN"] = "from-env"

        self.assertEqual(connectors.config("figma")["token"], "from-env")
        self.assertTrue(connectors.public()["figma"]["fields"]["token"]["from_env"])

    def test_jira_needs_every_field_and_a_plain_site(self):
        connectors.save("jira", {"fields": {"site": "https://acme.atlassian.net/", "token": "t"}})
        self.assertFalse(connectors.is_connected("jira"))
        self.assertEqual(connectors.config("jira")["site"], "acme.atlassian.net")

        connectors.save("jira", {"fields": {"email": "me@acme.com"}})
        self.assertTrue(connectors.is_connected("jira"))
        with self.assertRaises(ValueError):
            connectors.save("jira", {"fields": {"site": "not a site/"}})

    def test_ticket_options_keep_only_the_statuses_you_filled_in(self):
        connectors.save("clickup", {"fields": {"token": "pk_1"}, "options": {"comment": False, "move": {"in-dev": "in progress", "done": " "}}})

        self.assertEqual(connectors.config("clickup")["options"], {"comment": False, "move": {"in-dev": "in progress"}})

    def test_disconnect_forgets_it(self):
        connectors.save("sentry", {"fields": {"token": "s"}})
        connectors.disconnect("sentry")

        self.assertFalse(connectors.is_connected("sentry"))


class WhatAgentsAreToldTest(Isolated):

    def test_only_connected_apps_for_the_agents_role(self):
        connectors.save("figma", {"fields": {"token": "f"}})                       # Tech Lead, Dev, Reviewer
        connectors.save("sentry", {"fields": {"token": "s"}, "roles": ["dev"]})

        dev, reviewer, coach = (connectors.instructions_for(r, "claude") for r in ("dev", "reviewer", "coach"))

        self.assertIn("figma.py read", dev)
        self.assertIn("sentry.py issue", dev)
        self.assertIn("figma.py read", reviewer)
        self.assertIn("doesn't match it", reviewer)        # the Reviewer's own line
        self.assertNotIn("sentry.py", reviewer)
        self.assertNotIn("## Connected apps", coach)
        self.assertNotIn("clickup.py", dev)                 # not connected

    def test_everyone_learns_to_read_attached_files(self):
        text = connectors.instructions_for("coach", "openai")

        self.assertIn("📎", text)
        self.assertIn("files.py read", text)

    def test_the_tech_lead_learns_to_link_tickets(self):
        connectors.save("clickup", {"fields": {"token": "pk"}})

        self.assertIn("`ticket:`", connectors.instructions_for("techlead", "claude"))
        self.assertNotIn("`ticket:`", connectors.instructions_for("dev", "claude"))


class McpServersTest(Isolated):

    def test_claude_agents_get_the_servers_for_their_role(self):
        connectors.save_mcp([
            {"name": "notion", "type": "stdio", "command": "npx -y @notionhq/notion-mcp-server --verbose", "env": {"NOTION_TOKEN": "ntn"}, "roles": ["techlead"]},
            {"name": "linear", "type": "http", "url": "https://mcp.linear.app/mcp", "headers": {"Authorization": "Bearer lin"}, "roles": ["techlead", "dev"]},
        ])

        self.assertEqual(connectors.mcp_for("techlead"), {
            "notion": {"type": "stdio", "command": "npx", "args": ["-y", "@notionhq/notion-mcp-server", "--verbose"], "env": {"NOTION_TOKEN": "ntn"}},
            "linear": {"type": "http", "url": "https://mcp.linear.app/mcp", "headers": {"Authorization": "Bearer lin"}}})
        self.assertEqual(list(connectors.mcp_for("dev")), ["linear"])
        self.assertIn("`linear`", connectors.instructions_for("dev", "claude"))
        self.assertNotIn("`linear`", connectors.instructions_for("dev", "openai"))   # only Claude Code runs them

    def test_secrets_are_hidden_and_kept_when_left_empty(self):
        connectors.save_mcp([{"name": "db", "command": "db-mcp", "env": {"DB_URL": "postgres://secret"}, "roles": ["dev"]}])

        shown = connectors.public()["mcp"]["servers"][0]
        self.assertEqual(shown["env"], {"DB_URL": ""})
        connectors.save_mcp([{**shown, "roles": ["dev", "reviewer"]}])
        self.assertEqual(connectors.mcp_for("reviewer")["db"]["env"], {"DB_URL": "postgres://secret"})

    def test_names_and_commands_are_checked(self):
        for bad in ([{"name": "has space", "command": "x"}], [{"name": "a", "command": ""}],
                    [{"name": "a", "type": "http", "url": "ftp://x"}], [{"name": "a", "command": "x"}, {"name": "a", "command": "y"}]):
            with self.assertRaises(ValueError):
                connectors.save_mcp(bad)


class ApiTest(Isolated):

    def setUp(self):
        super().setUp()
        app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([])))
        self.client = TestClient(app, base_url="http://127.0.0.1:8420")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_connect_from_the_settings_page(self):
        got = self.client.put("/api/connectors/clickup", json={"fields": {"token": "pk_123_wxyz"}, "roles": ["techlead"]}, headers=HEADERS)

        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["fields"]["token"]["hint"], "wxyz")
        listed = self.client.get("/api/connectors", headers=HEADERS).json()
        self.assertTrue(listed["clickup"]["connected"])
        self.assertEqual(listed["clickup"]["roles"], ["techlead"])
        self.assertEqual(self.client.put("/api/connectors/nope", json={}, headers=HEADERS).status_code, 400)

    def test_mcp_servers_through_the_same_route(self):
        got = self.client.put("/api/connectors/mcp", json={"servers": [{"name": "db", "command": "db-mcp", "roles": ["dev"]}]}, headers=HEADERS)

        self.assertEqual(got.json()["servers"][0]["name"], "db")

    def test_attach_a_file_and_open_it(self):
        got = self.client.post("/api/uploads", content=b"a,b\n1,2\n", headers={**HEADERS, "x-filename": "Q1%20prices.csv"})

        self.assertEqual(got.status_code, 200)
        info = got.json()
        self.assertEqual(info["name"], "Q1 prices.csv")
        self.assertTrue(Path(info["path"]).is_file())
        again = self.client.post("/api/uploads", content=b"x", headers={**HEADERS, "x-filename": "Q1%20prices.csv"}).json()
        self.assertEqual(again["name"], "Q1 prices (2).csv")
        self.assertEqual(self.client.get(f"/api/uploads/{info['rel']}", headers=HEADERS).content, b"a,b\n1,2\n")

    def test_nothing_outside_uploads(self):
        (self.tmp / "settings.json").write_text("{}")

        self.assertEqual(self.client.get("/api/uploads/..%2Fsettings.json", headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.post("/api/uploads", content=b"", headers={**HEADERS, "x-filename": "empty.txt"}).status_code, 400)


class ToolsTest(Isolated):

    def test_a_tool_refuses_an_agent_whose_role_isnt_allowed(self):
        (self.tmp / "settings.json").write_text(json.dumps({
            "agents": {"coach": {"role": "coach"}, "dev-2": {"role": "dev"}},
            "connectors": {"figma": {"token": "f"}}}))

        os.environ["AGENT_ID"] = "dev-2"
        self.assertEqual(connlib.require("figma")["token"], "f")
        os.environ["AGENT_ID"] = "coach"
        with self.assertRaisesRegex(connlib.ConnectorError, "not for your role"):
            connlib.require("figma")
        os.environ.pop("AGENT_ID")
        with self.assertRaisesRegex(connlib.ConnectorError, "isn't connected"):
            connlib.require("clickup")

    def test_figma_links(self):
        self.assertEqual(figma.parse_link("https://www.figma.com/design/AbC123/Checkout?node-id=12-345&t=x"), ("AbC123", "12:345"))
        self.assertEqual(figma.parse_link("https://figma.com/file/AbC123/Old"), ("AbC123", ""))
        with self.assertRaises(connlib.ConnectorError):
            figma.parse_link("https://example.com/design/x")

    def test_figma_describes_what_a_developer_needs(self):
        frame = {"type": "FRAME", "name": "Card", "absoluteBoundingBox": {"width": 320, "height": 120}, "layoutMode": "VERTICAL",
                 "itemSpacing": 8, "paddingTop": 16, "paddingRight": 16, "paddingBottom": 16, "paddingLeft": 16, "cornerRadius": 12,
                 "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
                 "children": [{"type": "TEXT", "name": "Title", "characters": "Plus plan", "absoluteBoundingBox": {"width": 100, "height": 24},
                               "style": {"fontFamily": "Inter", "fontWeight": 600, "fontSize": 18, "lineHeightPx": 24},
                               "fills": [{"type": "SOLID", "color": {"r": 0.067, "g": 0.094, "b": 0.153, "a": 1}}]}]}

        text = "\n".join(figma.outline(frame, {}, 6))

        self.assertIn('frame "Card", 320×120, auto layout column, gap 8, padding 16, fill #ffffff, radius 12', text)
        self.assertIn('Inter 600 18px/24 #111827, "Plus plan"', text)
        self.assertIn("Colours used: ", text)

    def test_figma_image_lands_in_the_topics_visuals(self):
        import visual
        calls = []

        def fake(method, url, headers=None, body=None, raw=False, what=""):
            calls.append(url)
            return b"\x89PNG" if raw else {"images": {"1:2": "https://figma-cdn/x.png"}}
        connlib.SETTINGS.write_text(json.dumps({"connectors": {"figma": {"token": "t"}}}))
        with mock.patch.object(figma, "request", fake), mock.patch.object(visual, "VISUALS", self.tmp / "visuals"), redirect_stdout(io.StringIO()) as out:
            figma.cmd_image(["https://www.figma.com/design/K/x?node-id=1-2", "pricing-page", "Design"])

        self.assertEqual((self.tmp / "visuals" / "pricing-page" / "design.png").read_bytes(), b"\x89PNG")
        self.assertIn("![Design (Figma)](visuals/pricing-page/design.png)", out.getvalue())

    def test_ticket_ids(self):
        self.assertEqual(clickup.parse("https://app.clickup.com/t/86c2xk1ab"), ("86c2xk1ab", ""))
        self.assertEqual(clickup.parse("https://app.clickup.com/t/9012/ENG-42"), ("ENG-42", "?custom_task_ids=true&team_id=9012"))
        self.assertEqual(clickup.parse("CU-86c2xk1ab"), ("86c2xk1ab", ""))
        self.assertEqual(jira.parse("https://acme.atlassian.net/browse/PAY-118?focused=1"), "PAY-118")
        self.assertEqual(sentry.parse("https://acme.sentry.io/issues/4512/?project=2"), ("acme", "4512"))
        self.assertEqual(sentry.parse("https://sentry.example.com/organizations/acme/issues/77/"), ("acme", "77"))

    def test_which_app_a_ticket_belongs_to(self):
        self.assertEqual(tickets.which("https://app.clickup.com/t/86c2"), "clickup")
        self.assertEqual(tickets.which("https://acme.atlassian.net/browse/PAY-1"), "jira")
        self.assertEqual(tickets.which("PAY-1"), "jira")
        connlib.SETTINGS.write_text(json.dumps({"connectors": {"clickup": {"token": "pk"}}}))
        self.assertEqual(tickets.which("ENG-42"), "clickup")   # only ClickUp connected: a custom ID

    def test_a_task_moving_comments_on_its_ticket_and_moves_it(self):
        connlib.SETTINGS.write_text(json.dumps({"console_url": "https://hive.acme.com", "connectors": {
            "jira": {"site": "acme.atlassian.net", "email": "me@acme.com", "token": "t", "options": {"move": {"ready-for-review": "In Review"}}}}}))
        task = self.tmp / "TASK-012-x.md"
        task.write_text("---\nid: TASK-012\ntitle: Pricing page\nstatus: ready-for-review\nticket: PAY-118   # from Jira\n---\n")
        done = []
        with mock.patch.object(jira, "comment", lambda t, text: done.append(("comment", t, text))), \
             mock.patch.object(jira, "move", lambda t, s: done.append(("move", t, s))), \
             mock.patch.object(tickets, "LOG", self.tmp / "tickets.log"):
            tickets.sync(task, "in-dev", "ready-for-review")

        self.assertEqual(done[0], ("comment", "PAY-118", 'Hive: TASK-012 "Pricing page" is now ready for review. https://hive.acme.com/#/tasks/TASK-012'))
        self.assertEqual(done[1], ("move", "PAY-118", "In Review"))
        self.assertIn("updated, moved to In Review", (self.tmp / "tickets.log").read_text())

    def test_jira_rich_text_reads_as_text(self):
        doc = {"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Goal"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Show "}, {"type": "text", "text": "3", "marks": [{"type": "strong"}]}, {"type": "text", "text": " plans."}]},
            {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Basic"}]}]}]}]}

        self.assertEqual(jira.adf_text(doc).strip(), "## Goal\n\nShow **3** plans.\n\n- Basic")


class FilesToolTest(Isolated):

    def test_every_sheet_of_a_workbook_as_a_table(self):
        path = self.tmp / "prices.xlsx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                       '<sheet name="Plans" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<si><t>Plan</t></si><si><t>Price</t></si><si><t>Basic</t></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                       '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                       '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>149</v></c></row>'
                       '<row r="3"><c r="B3"><f>B2*12</f></c></row></sheetData></worksheet>')

        text = files.read(path, 200, None)

        self.assertIn("prices.xlsx: 1 sheet (Plans)", text)
        self.assertIn("| Plan | Price |\n|---|---|\n| Basic | 149 |\n|  | =B2*12 |", text)

    def test_csv_with_semicolons(self):
        path = self.tmp / "a.csv"
        path.write_text("plan;price\nBasic;149\n")

        self.assertIn("| plan | price |\n|---|---|\n| Basic | 149 |", files.read(path, 200, None))


if __name__ == "__main__":
    unittest.main()
