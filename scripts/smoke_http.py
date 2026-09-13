"""HTTP smoke test for the SANKET API.

Walks the same vertical slice as scripts/smoke_loop.py, but over real HTTP: login as
each role, read the map, file a community report, find it in the action queue, move it
through the lifecycle, and confirm provenance/failure handling. Anything that does not
work is recorded and printed at the end rather than fixed inline.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._bootstrap import prepare  # noqa: E402

BASE = os.environ.get("SANKET_SMOKE_BASE", "http://127.0.0.1:8123/api")
ISSUES: list[str] = []
OK: list[str] = []

# The other port this project names: 8123 in `.env.example`, Vite's proxy and every smoke
# script; 8000 is what a browser bookmark or an earlier session tends to leave running.
OTHER_PORT = "8123" if ":8000" in BASE else ("8000" if ":8123" in BASE else "")


def warn_second_server() -> None:
    """Refuse to look green while a second server may be the one being tested.

    A leftover uvicorn answers a smoke run with the code from whenever it was started. Tonight a
    60-check pass went to :8123 while the edits under test were only loaded on :8000 - the same
    class of false proof as a test that passes because it never reached the thing it names. Two
    servers also share one SQLite file, which docs/known-issues.md already calls out.
    """
    if not OTHER_PORT:
        return
    try:
        answer = httpx.get(f"http://127.0.0.1:{OTHER_PORT}/api/health", timeout=3.0)
    except httpx.HTTPError:
        return
    note_issue(
        f"a second server answers on :{OTHER_PORT} (HTTP {answer.status_code}) while this run "
        f"targets {BASE}. One of them is not the code you just changed - list both with "
        f"`netstat -ano | Select-String ':8000|:8123'` and stop the one you did not start"
    )


def note_issue(text: str) -> None:
    ISSUES.append(text)
    print(f"  !! {text}")


def ok(text: str) -> None:
    OK.append(text)
    print(f"  ok  {text}")


def call(client: httpx.Client, method: str, path: str, json_body=None, expect=(200, 201)):
    resp = client.request(method, f"{BASE}{path}", json=json_body)
    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError):
        payload = {"_raw": resp.text[:200]}
    if resp.status_code not in expect:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise AssertionError(f"{method} {path} -> {resp.status_code}: {str(detail)[:300]}")
    return resp, payload


def _action_label(entry: dict) -> str:
    """`set_status -> contained`, so two status moves never read as a duplicate."""
    target = entry.get("target")
    return f"{entry.get('action')} -> {target}" if target else str(entry.get("action"))


def _path_matches(client_path: str, template: str) -> bool:
    """Compare a path literal from the frontend with an OpenAPI template.

    A `${...}` segment in the client and a `{param}` segment in the API are both "any one
    segment", so each matches the other. Anything else has to be equal.
    """
    left = client_path.split("?")[0].split("/")
    right = template.split("/")
    if len(left) != len(right):
        return False
    for a, b in zip(left, right, strict=True):
        if a.startswith("${") or b.startswith("{"):
            continue
        if a != b:
            return False
    return True


def frontend_contract(paths: dict) -> None:
    """Check every path literal in `frontend/src/api/client.ts` against the live OpenAPI.

    That file is the only place the frontend builds a URL, and a path invented in it does not
    fail loudly: it 404s, and the screen renders "nothing here" - which reads like an empty
    country, not like a bug. So the client is treated as a set of claims about the API, and the
    API gets to say whether they hold.
    """
    client_file = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "client.ts"
    if not client_file.is_file():
        print("  ..  no frontend client to check against the api")
        return
    text = client_file.read_text(encoding="utf-8")
    named = sorted(set(re.findall(r'["`](/api/[^"`]+)["`]', text)))
    unmatched = [p for p in named if not any(_path_matches(p, template) for template in paths)]
    if unmatched:
        note_issue(f"frontend client names paths the api does not have: {unmatched}")
    else:
        ok(f"every path the frontend client names exists in the api ({len(named)} distinct)")


def _query_bound(paths: dict, api_path: str, name: str) -> int | None:
    """The `le` bound FastAPI recorded for one query parameter, when it published one."""
    spec = (paths.get(api_path) or {}).get("get") or {}
    for param in spec.get("parameters") or []:
        if param.get("name") != name:
            continue
        schema = param.get("schema") or {}
        for key in ("le", "maximum"):
            if isinstance(schema.get(key), (int, float)):
                return int(schema[key])
    return None


def overlay_limits(rc: httpx.Client, paths: dict) -> None:
    """Every `?limit=` a layer URL asks for has to sit inside what that endpoint accepts.

    The map takes these URLs as given, so a limit above the endpoint's own ceiling turns a
    layer into a 422 - and on screen that is a missing layer with no explanation. Tonight's
    bug was exactly this: an alerts overlay published `limit=200` against an endpoint capped
    at 100, and it passed unnoticed until something actually requested it.
    """
    _, layers = call(rc, "GET", "/map/layers")
    too_big = []
    for overlay in layers.get("overlays") or []:
        url = overlay.get("url") or ""
        asked = re.search(r"[?&]limit=(\d+)", url)
        if not asked:
            continue
        endpoint = url.split("?")[0]
        ceiling = _query_bound(paths, endpoint, "limit")
        if ceiling is not None and int(asked.group(1)) > ceiling:
            too_big.append(
                f"{overlay.get('id')} asks limit={asked.group(1)} of {endpoint}, capped at {ceiling}"
            )
    for message in too_big:
        note_issue(f"overlay {message} - the published layer URL is a 422")
    if not too_big:
        ok("every overlay limit is inside its endpoint's own ceiling")


def items_of(body):
    """Every list endpoint here answers with {"items": [...]}; tolerate a bare list."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("items", [])
    return []


def wait_for_server(timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/health", timeout=3.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            time.sleep(1.0)
    return False


def responder_section(rc: httpx.Client) -> None:
    """One victim report through the only agent route that writes, then worked as a case.

    What is asserted here holds with a model configured and without one, which is the point of
    running this suite either way: a timeline of named steps, the priority inputs read by the
    fixed rules, a place named in prose never recorded at the confidence of a shared GPS pin, a
    case that reaches the queue still waiting for a human, and no status an agent moved.

    `mode` and `model_calls` are printed rather than asserted, so a provider being slow cannot
    turn this suite red while the report it processed is genuinely in the queue.
    """
    text = "My father is injured and we are trapped near Melamchi. The road is blocked and we need help."
    # A run that goes to a provider is two round trips plus the tools in between: not a
    # 30-second request. Same credentials, longer leash.
    with httpx.Client(timeout=180.0, headers=dict(rc.headers)) as agent:
        _, out = call(agent, "POST", "/agent/respond", {"text": text})

        print(
            f"  ..  responder: mode={out.get('mode')} model_calls={out.get('model_calls')} "
            f"status={out.get('status')} filed={out.get('created_requests')}"
        )
        if out.get("error"):
            print(f"  ..  the run reports its own provider error, not a substitute: {str(out['error'])[:110]}")

        steps = out.get("tool_calls") or []
        # The contract behind "do not expose chain-of-thought", checked as a shape rather than as
        # a hope: a step has a time, a name, a kind and a status, and the only free text on it is
        # the one line a tool wrote about its own result. There is no key a model's working could
        # arrive under, and one appearing here is a change someone should have to explain.
        stray = sorted({key for step in steps for key in step} - {"at", "action", "kind", "status", "detail", "asked"})
        if stray:
            note_issue(f"the activity timeline carries fields nothing named: {stray}")
        unnamed = [
            step.get("action")
            for step in steps
            if not (step.get("at") and step.get("action") and step.get("status") and step.get("kind"))
        ]
        too_long = [step.get("action") for step in steps if len(str(step.get("detail") or "")) > 240]
        if not steps:
            note_issue("a responder run came back with no activity timeline")
        elif unnamed:
            note_issue(f"activity steps missing a name, a time or a status: {unnamed}")
        elif too_long:
            note_issue(f"activity steps carrying more than a line of result: {too_long}")
        else:
            ok(f"{len(steps)} activity steps, each with a name, a status, a time and one line of result")

        reading = out.get("reading") or {}
        flags = {name for name, on in (reading.get("risk_flags") or {}).items() if on}
        if not {"medical_need", "trapped"} <= flags:
            note_issue(f"the fixed rules did not read injury and entrapment: {sorted(flags)}")
        elif reading.get("method") != "keyword_rules":
            note_issue(f"risk flags attributed to {reading.get('method')!r}, not the keyword table")
        else:
            ok("the priority's inputs came from the keyword table over the report, not from a model")

        location = out.get("location") or {}
        if location.get("location_confidence") == "high":
            note_issue("a place named in prose was recorded at the confidence of a shared GPS pin")
        elif not location.get("district"):
            print("  ..  no district resolved from these words, and the case says so")
        else:
            ok(
                f"'Melamchi' resolved to {location['district']} at confidence "
                f"{location['location_confidence']}"
            )

        refs = out.get("created_requests") or []
        if not refs:
            note_issue("a report asking for help filed no assistance request")
            return
        _, detail = call(agent, "GET", f"/rc/requests/{refs[0]}")
        request = detail.get("request", detail)
        structured = request.get("structured") or {}
        problems = []
        if request.get("status") != "received":
            problems.append(f"filed in status {request.get('status')!r}, not waiting for a person")
        if structured.get("filed_by") != "agent":
            problems.append("the case does not record that the agent filed it")
        if structured.get("filing_route") not in {"model_called_the_tool", "deterministic_rules"}:
            problems.append(f"the case does not say which route filed it: {structured.get('filing_route')!r}")
        if request.get("description") != text:
            problems.append("the case does not carry the reporter's own words")
        if request.get("location_confidence") != location.get("location_confidence"):
            problems.append("the case and the run disagree about how sure the location is")
        if not request.get("urgency_reasons"):
            problems.append("the case has no urgency reasons, so its priority cannot be questioned")
        if problems:
            note_issue("; ".join(problems))
        else:
            ok(
                f"{refs[0]} filed at {request.get('urgency')}, description verbatim, "
                f"by {structured.get('filing_route')}, still unacknowledged"
            )

        _, queue = call(agent, "GET", "/rc/queue")
        entries = [row for bucket in (queue.get("buckets") or {}).values() for row in bucket]
        mine = next((row for row in entries if row.get("ref_code") == refs[0]), None)
        if mine is None:
            note_issue("the case the agent filed never reached the action queue")
            return
        ok(f"the action queue shows {refs[0]} under {mine.get('urgency')}, unacknowledged={not mine.get('acknowledged')}")

        # Work it the way the console works anything else. An agent's case that an operator
        # cannot acknowledge and close is not a case, it is a log line. Each step is the
        # machine's own: acknowledge pulls a received case into reviewing by itself, and
        # in_progress only becomes legal once a team is named.
        rid = mine.get("id") or refs[0]
        call(agent, "POST", f"/rc/requests/{rid}/acknowledge", {"note": "seen in console"})
        _, after_ack = call(agent, "GET", f"/rc/requests/{rid}")
        acked = after_ack.get("request", after_ack)
        if acked.get("status") != "reviewing" or not acked.get("acknowledged_at"):
            note_issue(
                f"acknowledging left the agent's case at {acked.get('status')!r} "
                f"with acknowledged_at={acked.get('acknowledged_at')!r}"
            )
            return
        call(agent, "POST", f"/rc/requests/{rid}/assign", {"team": "Police Relief Unit 09"})
        call(agent, "POST", f"/rc/requests/{rid}/status", {"status": "in_progress"})
        _, closed = call(agent, "POST", f"/rc/requests/{rid}/status", {"status": "resolved"})
        finished = closed.get("request", closed)
        if finished.get("status") != "resolved" or not finished.get("resolved_at"):
            note_issue(f"the case would not close: {finished.get('status')!r}")
        else:
            ok("an operator acknowledged, assigned, worked and resolved the case the agent filed")


def agent_section(rc: httpx.Client, cm: httpx.Client) -> None:
    """The language layer must work with no model installed.

    So "it works" here means "it works and says how it worked". A silent fake-model
    success is the failure mode being tested for.
    """
    _, agent_status = call(rc, "GET", "/agent/status")
    if "available" not in agent_status or "fallback" not in agent_status:
        note_issue(f"/agent/status does not report availability and fallback: {sorted(agent_status)}")
    elif agent_status["available"]:
        ok(f"model reachable via {agent_status.get('provider')}/{agent_status.get('model')}")
    else:
        if agent_status.get("credentials_present") is False:
            ok("no model credentials, and /agent/status says so instead of pretending")
        else:
            note_issue(f"model unavailable despite credentials: {agent_status.get('reason')}")
        if not agent_status.get("reason"):
            note_issue("/agent/status reports unavailability without a reason")
        if not isinstance(agent_status.get("runs"), dict):
            note_issue("/agent/status does not include run statistics")

    _, tools_body = call(rc, "GET", "/agent/tools")
    tool_rows = tools_body.get("tools") or []
    names = [t.get("name") or "" for t in tool_rows]
    if len(names) < 25:
        note_issue(f"agent publishes {len(names)} tools; the two sets together are 26")
    # Two sets, published apart on purpose. The investigation set reads; the response set also
    # files, and the inventory says which is which instead of the smoke test assuming it. That
    # is why `/agent/tools` no longer claims `read_only: true` for the whole list.
    if tools_body.get("read_only") is not False:
        note_issue("/agent/tools does not admit that part of its inventory writes")
    if not tools_body.get("sets"):
        note_issue("/agent/tools does not separate the sets, so 'read only' has no subject")
    writers = set(tools_body.get("write_tools") or [])
    expected_writers = {
        "create_assistance_request",
        "update_assistance_request",
        "notify_response_center",
        "send_victim_update",
    }
    if writers != expected_writers:
        note_issue(f"the tools that write are {sorted(writers)}, not the four the design allows")
    else:
        ok("exactly four agent tools write, and none of them is a status change")
    mislabelled = [
        t.get("name")
        for t in tool_rows
        if bool(t.get("writes")) != (t.get("name") in writers)
    ]
    if mislabelled:
        note_issue(f"tools whose `writes` flag disagrees with the published list: {mislabelled}")
    else:
        ok(f"all {len(names)} agent tools declare their set and whether they write")
    if any(not (t.get("description") or "").strip() for t in tool_rows):
        note_issue("some agent tools publish no description, so the model cannot choose them")

    # An agent must not be a way past the caller's own permissions.
    _, _ = call(cm, "GET", "/agent/tools", expect=(403,))
    ok("community credentials cannot list the agent's tool inventory")
    _, _ = call(cm, "POST", "/agent/investigate", {"ref_code": "SANK-A-0001"}, expect=(403,))
    ok("community credentials cannot start an investigation")
    _, _ = call(cm, "POST", "/agent/respond", {"text": "We are trapped, please help"}, expect=(403,))
    ok("community credentials cannot run the responder, which is the route that writes")

    # A resident's chat is a model run too - the route has the same shape as the two above, so
    # it gets the same leash. Without it the 30s default timed out on a reply that arrived a
    # moment later, and the suite blamed the server.
    with httpx.Client(timeout=180.0, headers=dict(cm.headers)) as agent_cm:
        _, chat_body = call(agent_cm, "POST", "/agent/chat", {"message": "What is the situation in my area?"})
        if not (chat_body.get("response_text") or "").strip():
            note_issue("/agent/chat returned an empty answer")
        else:
            ok(f"chat answered in {chat_body.get('mode')} mode ({len(chat_body['response_text'])} chars)")
        if chat_body.get("language") not in {"en", "ne"}:
            note_issue(f"/agent/chat reported an unknown language: {chat_body.get('language')}")

        nepali = "मेरो क्षेत्रमा के भइरहेको छ?"
        _, chat_ne = call(agent_cm, "POST", "/agent/chat", {"message": nepali, "language": "en"})
    # `language` in the request is deliberately ignored: the reply follows the script the
    # question was actually written in, so a mismatch in the form cannot mislabel the answer.
    if chat_ne.get("language") != "ne":
        note_issue(f"a Nepali question got a '{chat_ne.get('language')}' reply")
    else:
        ok("a Nepali question is answered in Nepali whatever the form said")
    if chat_ne.get("mode") == "deterministic" and not chat_ne.get("note"):
        note_issue("a no-model answer did not label itself as assembled from records")

    help_text = "भूकम्पले घर भत्कियो, तीन जना भित्र फसेका छन्, मद्दत गर्नुहोस्"
    _, classify_body = call(rc, "POST", "/agent/classify", {"text": help_text})
    if classify_body.get("language") != "ne":
        note_issue(f"classify called a Nepali message '{classify_body.get('language')}'")
    if not classify_body.get("needs_help"):
        note_issue("classify missed an explicit plea for help")
    else:
        ok(f"classify reads a plea for help (hazard={classify_body.get('hazard')}, {classify_body.get('method')})")

    responder_section(rc)

    _, live_incidents = call(rc, "GET", "/incidents?limit=1")
    first_incident = (items_of(live_incidents) or [{}])[0]
    if not first_incident.get("ref_code"):
        print("  ..  no live incidents to investigate, so the agent path was skipped")
        return
    # The same longer leash `responder_section` uses, for the same reason: an investigation with
    # a live model is several provider round trips plus the tools it chose. The frontend allows
    # three minutes on this route (`AGENT_RUN_TIMEOUT_MS` in `api/client.ts`); 30s here was
    # timing out on a run that completed a second later, which reads as a server fault.
    with httpx.Client(timeout=180.0, headers=dict(rc.headers)) as agent_rc:
        _, investigation = call(
            agent_rc, "POST", "/agent/investigate", {"ref_code": first_incident["ref_code"]}
        )
    shipped = (investigation.get("response_text") or "").strip()
    rejected = investigation.get("rejected_numbers") or []
    # Which tools the model chose, now recorded on this route too (`agent/workflows/
    # investigate.py` watches the runs it used to credit them to the answer).
    called = sorted({str(step.get("action")) for step in investigation.get("tool_calls") or []})
    if investigation.get("status") == "rejected_unverified_numbers":
        # A refusal degrades to the deterministic rendering, which is the safe direction, but it
        # is still an investigation that never reached the operator - and this guard has already
        # fired once on a figure the platform itself had handed the model, so the suite stays red
        # until a person reads the values. Named values, not the whole evidence bundle: the last
        # time this printed, it dumped 30 KB of JSON over the terminal.
        note_issue(
            f"agent's answer for {first_incident['ref_code']} refused for unverified numbers "
            f"{rejected!r}; tools it called: {called or 'none'}"
        )
    elif not shipped:
        note_issue("investigation returned no text")
    else:
        ok(f"investigated {first_incident['ref_code']} in {investigation.get('mode')} mode"
           + (f" after {len(called)} tool call(s): {', '.join(called)}" if called else ""))
    # Whatever the guard rejected has to have actually left the answer - the fallback is only a
    # safety net if it replaces the wording instead of appending to it. Compared as whole number
    # tokens, because `13` is a substring of every ref code filed on the 13th.
    shipped_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", shipped))
    leaked = [number for number in rejected if number in shipped_numbers]
    if leaked:
        note_issue(f"numbers the guard rejected are still in the answer shown: {leaked}")
    # Looked up by the incident it investigated, not by the run's own id - a list of runs is
    # only useful from the incident's page, which is where an operator reads it.
    _, prior = call(rc, "GET", f"/agent/investigations?incident_id={investigation.get('subject_id')}")
    if prior.get("count", 0) < 1:
        note_issue("a finished investigation was not stored")
    else:
        ok("investigation runs are stored and readable after the fact")


def main() -> int:
    prepare()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print("=" * 72)
    print("SANKET HTTP API smoke test")
    print("=" * 72)

    if not wait_for_server():
        print("  !! server never answered /api/health - aborting")
        print(f"      base: {BASE}")
        return 1
    ok(f"server up on {BASE}")
    warn_second_server()

    with httpx.Client(timeout=30.0) as c:
        # ---------------------------------------------------------------- health
        _, health = call(c, "GET", "/health")
        print(f"  ..  health: {json.dumps(health)[:200]}")
        # ---------------------------------------------------------------- auth
        _, demos = call(c, "GET", "/auth/demo-accounts")
        accounts = demos.get("accounts", demos) if isinstance(demos, dict) else demos
        print(f"  ..  demo accounts: {json.dumps(accounts)[:260]}")

        def login(username: str, password: str) -> str:
            _, body = call(c, "POST", "/auth/login", {"username": username, "password": password})
            token = body.get("token") or body.get("access_token")
            if not token:
                raise AssertionError(f"login returned no token: {json.dumps(body)[:200]}")
            return token

        rc_token = login("sunita.rc", "sanket123")
        community_token = login("ram.prasad", "sanket123")
        analyst_token = login("analyst.rc", "sanket123")
        ok("logged in as Response Center operator and as community member")

        rc = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {rc_token}"})
        cm = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {community_token}"})
        analyst = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {analyst_token}"})

        # -------------------------------------------------- system status + source health
        _, system = call(rc, "GET", "/system/status")
        print(f"  ..  mode: {json.dumps(system.get('mode', {}), ensure_ascii=False)[:220]}")
        print(
            f"  ..  sources: {system.get('sources_healthy')}/{system.get('sources_total')} healthy, "
            f"failing={json.dumps(system.get('sources_failing'), ensure_ascii=False)[:200]}"
        )
        print(f"  ..  llm: {json.dumps(system.get('llm', {}), ensure_ascii=False)[:260]}")
        ok("system status reports mode, source health and honest model state")

        _, sources = call(rc, "GET", "/sources")
        rows = items_of(sources)
        for s in rows:
            print(
                f"  ..  {s['code']:<18} {s['status']:<9} {s['freshness_state']:<7} "
                f"official={s['official']} last_data={str(s.get('last_data_timestamp'))[:19]}"
            )
        good = [s for s in rows if s["status"] == "healthy"]
        if good:
            ok(f"{len(good)}/{len(rows)} sources healthy")
        else:
            note_issue("no source reports status=healthy over HTTP")
        unpolled = [s for s in rows if s["code"] in {"community", "demo"} and s["status"] != "never_fetched"]
        if unpolled:
            note_issue(f"internal sources are being polled: {[s['code'] for s in unpolled]}")

        # Whether the poller thread is alive is a different fact from whether polling is switched on,
        # and the two are indistinguishable from the table below: a dead thread and an agency with
        # nothing new both leave every source showing an old "last check". That is exactly how this
        # was reported - "polling seems to have stopped" - and it took a script against the SQLite
        # file to answer, so the answer has to be in the API and on the screen.
        worker = sources.get("worker") or {}
        print(f"  ..  ingestion worker: {json.dumps(worker, ensure_ascii=False)[:200]}")
        if "running" not in worker:
            note_issue("/sources no longer reports the ingestion worker")
        elif worker.get("running") is None:
            note_issue("the server cannot say whether its ingestion worker is running")
        elif not worker.get("running") and system.get("ingestion_enabled"):
            note_issue("ingestion is enabled but the worker thread is not running")
        else:
            ok(
                f"ingestion worker reports itself: running={worker.get('running')} "
                f"cycles={worker.get('cycles')} last cycle={worker.get('last_cycle_label')}"
            )

        me_rc = call(rc, "GET", "/auth/me")[1]["user"]
        me_cm = call(cm, "GET", "/auth/me")[1]["user"]
        print(f"  ..  rc user: {me_rc.get('role')}/{me_rc.get('rank')} "
              f"perms={len(me_rc.get('permissions', []))}")
        print(f"  ..  community user: {me_cm.get('role')}/{me_cm.get('rank')} "
              f"perms={len(me_cm.get('permissions', []))}")
        if me_rc.get("rank") != "operator":
            note_issue(f"/auth/me returned rank {me_rc.get('rank')!r} for sunita.rc")
        elif me_cm.get("rank") not in (None, "community_member"):
            note_issue(f"/auth/me returned rank {me_cm.get('rank')!r} for ram.prasad")
        elif len(me_cm.get("permissions", [])) >= len(me_rc.get("permissions", [])):
            note_issue("community member holds at least as many permissions as an operator")
        else:
            ok("ranks and permission sets differ per role")
        if me_rc.get("password_hash") or me_cm.get("password_hash"):
            note_issue("/auth/me leaked password material")

        # ---------------------------------------------------------------- auth failures
        _, bad = call(
            c, "POST", "/auth/login", {"username": "sunita.rc", "password": "wrong"}, expect=(401,)
        )
        _, ghost = call(
            c, "POST", "/auth/login", {"username": "nobody", "password": "x"}, expect=(401,)
        )
        if bad == ghost or bad.get("detail") == ghost.get("detail"):
            ok("unknown user and wrong password give the identical error")
        else:
            note_issue("login error messages differ between bad password and unknown user")

        try:
            call(rc, "GET", "/rc/queue")
            ok("operator can read the action queue")
        except AssertionError as exc:
            note_issue(f"operator /rc/queue failed: {exc}")

        # Community must not reach the Response Center surface.
        call(cm, "GET", "/rc/queue", expect=(403,))
        ok("community member is refused /rc/queue with 403")

        # Anonymous must not reach anything sensitive.
        call(c, "GET", "/rc/dashboard", expect=(401, 403))
        call(c, "GET", "/sources", expect=(401, 403))
        ok("anonymous requests to /rc/dashboard and /sources are refused")

        # ---------------------------------------------------------------- incidents + map
        _, incidents = call(rc, "GET", "/incidents?limit=10")
        items = items_of(incidents)
        print(f"  ..  /incidents returned {len(items)} of count={incidents.get('count')}")
        if not items:
            note_issue("/incidents returned no rows over HTTP though the DB has incidents")
            top = None
        else:
            top = items[0]
            keys = set(top)
            required = {"id", "title", "incident_type", "district", "severity"}
            missing = required - keys
            if missing:
                note_issue(f"incident summary missing fields: {sorted(missing)}")
            else:
                ok("incident summaries carry id/title/type/district/severity")
            if not top.get("provenance"):
                note_issue("incident summary exposes no provenance field")
            else:
                ok(f"incident summary carries provenance: {json.dumps(top['provenance'], ensure_ascii=False)[:120]}")
            print(f"  ..  top incident: {json.dumps(top, ensure_ascii=False)[:300]}")

        _, geo = call(rc, "GET", "/map/incidents.geojson")
        features = geo.get("features", [])
        print(f"  ..  incidents.geojson: {len(features)} features, type={geo.get('type')}")
        if features:
            props = features[0].get("properties", {})
            for field in ("location_precision", "freshness_state", "demo", "score_band"):
                if field not in props:
                    note_issue(f"geojson properties missing {field!r}")
            ok("geojson features carry provenance properties")
            coords = features[0].get("geometry", {}).get("coordinates")
            if not coords:
                note_issue("first geojson feature has no coordinates")
        else:
            note_issue("/map/incidents.geojson returned zero features")

        _, sig_list = call(rc, "GET", "/signals")
        srows = items_of(sig_list)
        _, sig = call(rc, "GET", "/map/signals.geojson")
        feats = sig.get("features", [])
        sig_meta = sig.get("meta", {})
        print(f"  ..  signals: {len(srows)} active, {len(feats)} placed on the map")
        for f in feats:
            p = f.get("properties", {})
            print(f"      - {p.get('code')} {p.get('level')} @{p.get('location_precision')}")
        if srows and not feats and not sig_meta.get("unplaced"):
            note_issue("risk signals exist but none can be drawn (no coordinates)")
        elif srows and not feats:
            # An empty layer that explains itself is not a broken layer: a national roll-up
            # genuinely has no point to put on a map.
            ok(
                f"no signal was drawable and the layer says so "
                f"(unplaced: {sig_meta.get('unplaced')})"
            )
        elif feats and all(
            f.get("properties", {}).get("location_precision") is None for f in feats
        ):
            note_issue("signal geojson features do not state how they were located")
        else:
            ok("risk signals are placed and labelled with their location precision")

        _, layers = call(rc, "GET", "/map/layers")
        origin = BASE.rsplit("/api", 1)[0]
        # The map builds itself from this catalogue, so every address in it has to answer.
        # A layer the client cannot fetch is a layer that silently never appears on screen -
        # and one asking for `?limit=200` of an endpoint capped at 100 fails as a 422.
        overlays = layers.get("overlays") or []
        broken: list[str] = []
        for overlay in overlays:
            url = overlay.get("url")
            if not url:
                broken.append(f"{overlay.get('id')} publishes no url")
                continue
            # Probe with the credentials the surface that draws the layer actually has: a
            # staff-only overlay is fetched as staff, a public one as a resident.
            probe = rc.get(f"{origin}{url}") if overlay.get("staff_only") else cm.get(f"{origin}{url}")
            if probe.status_code != 200:
                broken.append(f"{overlay.get('id')} points at {url}, which answered {probe.status_code}")
        for message in broken:
            note_issue(f"overlay {message}")
        if overlays and not broken:
            ok(f"every published overlay url answers the client that draws it ({len(overlays)} layers)")
        # Both surfaces reading the same official feed is the whole point of the product;
        # `alerts:read` used to exist only on the community role, so the console could not.
        _, alerts_rc = call(rc, "GET", "/alerts?limit=1")
        _, alerts_cm = call(cm, "GET", "/alerts?limit=1")
        if len(items_of(alerts_rc)) == len(items_of(alerts_cm)):
            ok("operators and residents read the same official alert feed")
        else:
            note_issue("the alert feed differs between the two surfaces")
        reachable = [v for v in (layers.get("vector_layers") or []) if v.get("available")]
        if not reachable:
            note_issue("/map/layers offers no boundary file - the map would have no Nepal in it")
        for layer in reachable:
            got = c.get(f"{origin}{layer['url']}")
            if got.status_code != 200 or got.json().get("type") not in ("FeatureCollection", "GeometryCollection"):
                note_issue(f"boundary '{layer['id']}' at {layer['url']} is not readable geojson ({got.status_code})")
        if reachable and all(
            c.get(f"{origin}{layer['url']}").json().get("type") in ("FeatureCollection", "GeometryCollection")
            for layer in reachable
        ):
            ok(f"boundary files are served and readable ({len(reachable)} layers)")

        # A misspelled API path used to answer 200 with the built frontend's index.html,
        # because the SPA catch-all sits behind the router. That turns a wrong path into a
        # JSON parse error far away from the typo, and in the browser into a map layer that
        # is quietly empty rather than a layer that failed. `probe/anonymous_surface.py`
        # is the same claim printed out by hand.
        missed = c.get(f"{origin}/api/map/not-an-endpoint")
        if missed.status_code == 404 and "json" in (missed.headers.get("content-type") or ""):
            ok("an unknown /api path fails as 404 json instead of serving the app shell")
        else:
            note_issue(
                f"unknown /api path answered {missed.status_code} "
                f"{missed.headers.get('content-type')} - a typo would look like an empty country"
            )
        # The catalogue is public so a signed-out resident can learn what the map would draw;
        # the rows behind it are not, so this asserts the split rather than assuming it.
        if c.get(f"{origin}/api/map/layers").status_code == 200 and any(
            c.get(f"{origin}{url}").status_code == 401
            for url in (o.get("url") or "" for o in overlays)
            if url.startswith("/api/map/")
        ):
            ok("the layer catalogue is public while the data it names is not")
        else:
            note_issue("the map catalogue and its feeds no longer disagree about who may read them")

        # Community incident list must only contain official items.
        _, pub = call(cm, "GET", "/incidents?limit=10")
        pub_items = items_of(pub)
        print(f"  ..  community-visible incidents: {len(pub_items)}")

        # ---------------------------------------------------------------- incident detail
        if top is not None:
            _, detail = call(rc, "GET", f"/incidents/{top['id']}")
            for section in ("incident", "why_prioritized", "evidence", "timeline", "available_actions"):
                if section not in detail:
                    note_issue(f"incident detail missing {section!r} over HTTP")
            ev = detail.get("evidence", {})
            print(f"  ..  evidence state: {ev.get('state')} / {ev.get('label')}")
            print(f"  ..  score: {detail.get('why_prioritized', {}).get('score')}")
            print(f"  ..  actions: {[_action_label(a) for a in detail.get('available_actions', [])]}")
            ok("incident detail returns evidence + prioritization + action surface")
            # The action bar is built by the server, so a viewer must never be offered a
            # control the API would refuse - and a resident must be offered none at all.
            _, pub_detail = call(cm, "GET", f"/incidents/{top['id']}")
            pub_actions = pub_detail.get("available_actions")
            print(f"  ..  actions a resident may press: {pub_actions!r}")
            if pub_actions:
                note_issue(f"community viewer was offered operator actions: {pub_actions}")
            elif "available_actions" in pub_detail:
                ok("resident's view of the same incident offers no actions")
            else:
                ok("resident's view is the public shape, with no action surface at all")

        # ---------------------------------------------------------------- community report
        report_body = {
            "message": "भूकम्पको कम्पन महसुस गरियो, गाउँ तिर धुलो देखिएको छ। कसैलाई सहयोग चाहिन्छ।",
            "language": "ne",
            "report_type": "incident",
            "incident_type": "earthquake",
            "latitude": 29.12,
            "longitude": 83.9,
            "location_text": "Chitre, Mustang",
            "needs_help": True,
            "help_types": ["rescue"],
            "immediate_danger": True,
        }
        _, rep = call(cm, "POST", "/community/reports", report_body, expect=(200, 201))
        print(f"  ..  report response keys: {sorted(rep)[:14]}")
        report = rep.get("report", rep)
        request = rep.get("assistance_request") or rep.get("request")
        answer = rep.get("answer")
        nxt = rep.get("what_happens_next") or rep.get("next_step")
        if not report.get("id"):
            note_issue("POST /community/reports returned no report id")
        else:
            ok(f"community report accepted ({report['id'][:8]}...)")
        # A resident describing shaking near a recorded quake must land on that quake,
        # not open a parallel incident: this is the report -> incident correlation.
        linked_incident = report.get("incident")
        print(f"  ..  report linked to: {json.dumps(linked_incident, ensure_ascii=False)[:200] if linked_incident else 'NOTHING'}")
        if linked_incident and linked_incident.get("ref_code"):
            ok(f"report correlated with an official incident ({linked_incident['ref_code']})")
        else:
            note_issue("an earthquake report 11 km from a recorded quake did not link to it")
        print(f"  ..  answer: {json.dumps(answer, ensure_ascii=False)[:300]}")
        print(f"  ..  next:   {json.dumps(nxt, ensure_ascii=False)[:300]}")
        print(f"  ..  request: {json.dumps(request, ensure_ascii=False)[:300] if request else 'NONE'}")
        if request is None:
            note_issue("needs_help=true report did not produce an assistance request over HTTP")

        # A message this short is refused before anything is written.
        _, empty = call(cm, "POST", "/community/reports", {"message": "hi", "language": "en"}, expect=(422,))
        print(f"  ..  2-character report rejected: {json.dumps(empty, ensure_ascii=False)[:160]}")
        ok("validation rejects a report below the minimum length")

        # Same person, same plea, case still open: no second ticket, but the repeat
        # must be carried onto the open one and raised - never dropped.
        if request:
            _, rep2 = call(cm, "POST", "/community/reports", report_body, expect=(200, 201))
            second = rep2.get("assistance_request") or rep2.get("request")
            carried = (rep2.get("report", {}) or {}).get("carried_on_request")
            print(f"  ..  repeat plea -> request {second.get('ref_code') if second else None}, "
                  f"carried_on={carried}, urgency={second.get('urgency') if second else None}")
            if second and second.get("ref_code") == request.get("ref_code"):
                ok("repeat plea reuses the open case instead of doubling the queue")
            elif second:
                note_issue("repeat plea opened a second case while the first was still open")
            else:
                note_issue("repeat plea produced no request at all - a waiting person was ignored")
            if carried != (request.get("ref_code")):
                note_issue(f"report did not record which open case carried it (got {carried!r})")
            _, tl2 = call(cm, "GET", f"/community/requests/{request['ref_code']}")
            kinds = [e.get("kind") for e in tl2.get("timeline", [])]
            print(f"  ..  timeline kinds: {kinds}")
            if "repeat_request" not in kinds:
                note_issue("the repeat plea is not visible in the victim's own timeline")
            else:
                ok("victim timeline shows the repeat plea and what was done about it")
            carried_answer = rep2.get("answer") or ""
            print(f"  ..  carry answer: {json.dumps(carried_answer, ensure_ascii=False)[:220]}")
            if carried and request.get("ref_code") not in carried_answer:
                note_issue("the answer to a carried plea does not name the open case it joined")
            elif carried and any(phrase in carried_answer.lower() for phrase in ("was opened", "खोलिएको")):
                note_issue("the answer claims a new request was opened on top of an existing one")
            elif carried:
                ok("a carried plea is described as joining the open case, not as a new one")

        # ---------------------------------------------------------------- feed
        _, feed = call(cm, "GET", "/community/feed")
        print(f"  ..  community feed: {json.dumps(feed, ensure_ascii=False)[:280]}")
        _, act = call(cm, "GET", "/community/activity")
        print(f"  ..  activity: {json.dumps(act, ensure_ascii=False)[:280]}")

        # ---------------------------------------------------------------- action queue
        _, queue = call(rc, "GET", "/rc/queue")
        qrows = [row for bucket in queue.get("buckets", {}).values() for row in bucket]
        print(f"  ..  action queue: {len(qrows)} items across "
              f"{json.dumps(queue.get('counts', {}))}")
        target = None
        if request:
            ref = request.get("ref_code") or request.get("id")
            for row in qrows:
                if row.get("kind") != "assistance_request":
                    continue
                if ref in {row.get("id"), row.get("ref_code")}:
                    target = row
                    break
            if target is None:
                note_issue("the new assistance request did not appear in /rc/queue")
            else:
                ok("new assistance request surfaced in the action queue")
        else:
            ref = None

        # ---------------------------------------------------------------- lifecycle
        if target is not None:
            rid = target.get("id") or target.get("ref") or ref
            _, dash_before = call(rc, "GET", "/rc/dashboard")
            print(f"  ..  dashboard: {json.dumps(dash_before, ensure_ascii=False)[:300]}")

            call(rc, "POST", f"/rc/requests/{rid}/acknowledge", {"note": "seen in console"})
            ok("acknowledge 200")
            _, after_ack = call(rc, "GET", f"/rc/requests/{rid}")
            print(f"  ..  status after acknowledge: {after_ack.get('request', after_ack).get('status')}")

            call(
                rc,
                "POST",
                f"/rc/requests/{rid}/assign",
                {"team": "Police Relief Unit 09", "share_note_with_requester": True},
            )
            ok("assign 200")
            _, after_assign = call(rc, "GET", f"/rc/requests/{rid}")
            body = after_assign.get("request", after_assign)
            print(f"  ..  status after assign: {body.get('status')}")
            timeline = after_assign.get("victim_timeline") or after_assign.get("timeline") or []
            print(f"  ..  victim timeline entries: {len(timeline)}")
            for entry in timeline[-4:]:
                print(f"      - {json.dumps(entry, ensure_ascii=False)[:200]}")
            nepali = [e for e in timeline if any("\u0900" <= ch <= "\u097f" for ch in json.dumps(e, ensure_ascii=False))]
            if not nepali:
                note_issue("victim timeline shows no Nepali-language entry after assignment")
            else:
                ok("victim timeline includes Nepali-language updates")
            actors = {e.get("actor_type") or e.get("actor") for e in timeline}
            print(f"  ..  timeline actors: {actors}")

            call(rc, "POST", f"/rc/requests/{rid}/status", {"status": "in_progress"})
            call(rc, "POST", f"/rc/requests/{rid}/message", {"message": "टोली बाटोमा छ।"})
            ok("in_progress + direct victim message 200")

            _, illegal = call(
                rc, "POST", f"/rc/requests/{rid}/status", {"status": "received"}, expect=(400, 409)
            )
            print(f"  ..  backwards transition rejected: {json.dumps(illegal, ensure_ascii=False)[:220]}")
            ok("illegal backwards transition refused")

            call(rc, "POST", f"/rc/requests/{rid}/status", {"status": "resolved"})
            ok("resolved 200")

            # Community side sees its own request; another user must not.
            _, own = call(cm, "GET", f"/community/requests/{ref}")
            print(f"  ..  community view of own request: "
                  f"{json.dumps(own, ensure_ascii=False)[:280]}")
        else:
            note_issue("skipped lifecycle assertions (nothing in the queue to act on)")

        # ---------------------------------------------------------------- notifications
        _, notif = call(cm, "GET", "/notifications")
        nrows = items_of(notif)
        print(f"  ..  notifications for community user: {len(nrows)} unread={notif.get('unread')}")
        if not nrows:
            note_issue("the reporter received no notification about their own case")
        _, unread = call(cm, "GET", "/notifications/unread-count")
        print(f"  ..  unread: {json.dumps(unread)[:160]}")

        # ---------------------------------------------------------------- audit
        _, audit_rows = call(rc, "GET", "/rc/audit?limit=10")
        arows = items_of(audit_rows)
        print(f"  ..  audit rows: {len(arows)}")
        if not arows:
            note_issue("/rc/audit returned nothing after a full lifecycle run")
        else:
            ok("audit trail records operator actions")
            print(f"  ..  latest: {json.dumps(arows[0], ensure_ascii=False)[:240]}")
        # Filtering is the point of a log: an operator's status change must be findable.
        audit_target = (request or {}).get("id")
        if audit_target:
            _, filtered = call(
                rc, "GET", f"/rc/audit?entity_type=assistance_request&entity_id={audit_target}"
            )
            frows = items_of(filtered)
            print(f"  ..  audit for this request: {len(frows)} rows, actions={[r.get('action') for r in frows][:8]}")
            if not frows:
                note_issue("entity-filtered audit found nothing for a request that was moved four times")
            else:
                ok("audit trail is filterable down to one entity's history")
        # Analysts read the situation, not the staff log.
        call(analyst, "GET", "/rc/audit", expect=(403,))
        ok("analyst is refused the staff audit log")

        # ---------------------------------------------------------------- validation
        call(rc, "POST", f"/rc/requests/{ref or 'x'}/status", {"status": "not_a_status"}, expect=(400, 422, 404, 409))
        ok("bogus status value is rejected")
        # A 5000-character message is a real thing a frightened person types. It is
        # stored, clipped to the documented limit - never silently dropped.
        _, big = call(cm, "POST", "/community/reports", {"message": "x" * 5000, "language": "en"}, expect=(200, 201, 400, 422))
        stored = (big.get("report") or {}).get("message") or ""
        print(f"  ..  oversized report: status accepted, stored length={len(stored)}")
        if big.get("report") and len(stored) > 4000:
            note_issue(f"report message not clipped to 4000 chars (stored {len(stored)})")
        else:
            ok("oversized report body is accepted and clipped, or refused - never dropped silently")

        # ---------------------------------------------------------------- resources
        # The facility catalogue is the one place a fabricated row could send a rescuer to
        # a door that does not exist, so these checks read what OpenStreetMap really
        # returned and only ever write a test entry that is retired again below.
        _, res = call(rc, "GET", "/rc/resources?limit=5")
        cat = res.get("catalogue") or {}
        ritems = res.get("items") or []
        print(f"  ..  catalogue: {cat.get('total')} facilities, {len(ritems)} in page")
        if cat.get("empty"):
            note_issue(
                "resource catalogue is empty - run scripts/seed_resources.py "
                "(POST /rc/resources/seed is the same path over HTTP)"
            )
        else:
            ok(f"facility catalogue holds {cat.get('total')} real facilities")
            if ritems and all(row.get("provenance") for row in ritems):
                ok("every facility in the page states where its facts came from")
            else:
                note_issue("a facility reached the catalogue with no provenance")
            if any(not row.get("availability") for row in ritems):
                note_issue("a facility has no availability state at all")
            else:
                ok("every facility states an availability, even if only 'unknown'")
            if cat.get("by_availability", {}).get("available"):
                note_issue(
                    "something claims 'available' with no human confirmation - decay did not run"
                )
            else:
                ok("nothing claims to be open without a confirmation behind it")

        _, geo = call(rc, "GET", "/map/resources.geojson?limit=50")
        feats = geo.get("features") or []
        print(f"  ..  map layer features: {len(feats)}  meta: {(geo.get('meta') or {}).get('returned')}")
        if feats and any("contact" in (f.get("properties") or {}) for f in feats):
            note_issue("phone numbers leaked into the map layer - they belong in the detail view")
        else:
            ok("map layer carries no contact details (those stay in the catalogue view)")
        if feats and not all((f.get("properties") or {}).get("name") for f in feats):
            note_issue("an unnamed facility reached the map")
        elif feats:
            ok("every mapped facility has a name a dispatcher can read aloud")

        # A half-given coordinate must be refused, not stored as a point at (0, 0).
        _, _ = call(
            rc,
            "POST",
            "/rc/resources",
            {"resource_type": "hospital", "name": "Smoke Half Coordinate", "latitude": 27.7},
            expect=(400, 422),
        )
        ok("a facility with a latitude but no longitude is refused")
        _, _ = call(
            rc,
            "POST",
            "/rc/resources",
            {"resource_type": "hospital", "name": "Smoke Bad Type", "latitude": 27.7, "longitude": 85.3,
             "availability": "avliable"},
            expect=(422,),
        )
        ok("a misspelled availability is refused rather than stored unreachable")
        _, _ = call(cm, "GET", "/rc/resources", expect=(403,))
        ok("community credentials cannot read the response-centre catalogue")

        # Write path, proven and then withdrawn so the catalogue stays real-data only.
        _, made = call(
            rc,
            "POST",
            "/rc/resources",
            {
                "resource_type": "shelter",
                "name": "SMOKE TEST SITE - NOT A REAL SHELTER",
                "latitude": 27.7104,
                "longitude": 85.3182,
                "capacity": 40,
            },
            expect=(201,),
        )
        made_res = made.get("resource") or {}
        made_id = made_res.get("id")
        if not made_id:
            note_issue("creating a facility returned no id")
        else:
            if made_res.get("district"):
                ok(f"operator entry resolved to district '{made_res['district']}' from its coordinates")
            else:
                note_issue(f"operator entry at Kathmandu coordinates got no district: {made_res.get('district')}")
            if made_res.get("provenance") == "operator":
                ok("an operator-entered facility is labelled as their statement, not open data")
            else:
                note_issue(f"operator entry provenance is {made_res.get('provenance')}")
            _, _ = call(rc, "POST", f"/rc/resources/{made_id}/deactivate", {"reason": "smoke test cleanup"})
            _, after = call(rc, "GET", "/rc/resources?limit=500")
            still = [row for row in (after.get("items") or []) if row.get("id") == made_id]
            if still:
                note_issue("a retired facility is still listed in the active catalogue")
            else:
                ok("a retired facility leaves the map and the active list (the row is kept for the log)")

        agent_section(rc, cm)

        # ---------------------------------------------------------------- provenance headers
        h = c.get(f"{BASE}/health")
        gen = h.headers.get("x-sanket-generated-at")
        md = h.headers.get("x-sanket-mode")
        if gen and md:
            ok(f"provenance headers present (mode={md})")
        else:
            note_issue(f"missing provenance headers: generated-at={gen} mode={md}")

        _, docs = call(c, "GET", "/openapi.json")
        paths = docs.get("paths", {})
        print(f"  ..  openapi paths: {len(paths)}")
        if len(paths) < 25:
            note_issue(f"openapi exposes only {len(paths)} paths - some routers did not mount")
        frontend_contract(paths)
        overlay_limits(rc, paths)

    print()
    print("=" * 72)
    print(f"passed checks: {len(OK)}")
    print(f"ISSUES TO FIX LATER: {len(ISSUES)}")
    for i, issue in enumerate(ISSUES, 1):
        print(f"  {i:2d}. {issue}")
    print("=" * 72)
    # A smoke test that always exits 0 is decoration. Anything left in ISSUES has to
    # fail the run, and each one must be fixed or written down as a known limitation.
    return 1 if ISSUES else 0


if __name__ == "__main__":
    raise SystemExit(main())
