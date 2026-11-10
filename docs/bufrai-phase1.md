# Bufrai phase 1 — Isaac Assist frame

House-build phase 2 frame; module isaac-assist-frame; MCP + Kit bank deferred by OD.

Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0). See `LICENSE` and `NOTICE`.
This frame copies the Isaac Sim 6.0 extension forward. It does not add a
Lumberyard or Open 3D Engine project; the 6.2 extension is built from that
existing extension.

The cloud build cannot run Isaac Sim, Ollama, or a private network. Everything
below that needs those is marked UNVERIFIED for the Legion smoke.

## Layout

| Piece | Where |
|---|---|
| Isaac Sim 6.2 extension | `exts/isaac_6.2/omni.isaac.assist` |
| Runtime profile | `isaacsim-6.2` in `service/isaac_assist_service/runtime_profiles.py` |
| Provider chain | `service/isaac_assist_service/providers/` |
| Sticky notes | `service/isaac_assist_service/notes/` and the 6.2 `ui/sticky_notes.py` |

`LLM_MODE=local` and the other upstream modes are unchanged. `LLM_MODE=chain`
selects the new fallback chain.

## Legion Ubuntu setup

Isaac Sim is expected at `~/isaacsim`. The service listens on `127.0.0.1:8000`.

```bash
cd ~/isaac-assist
python -m service.isaac_assist_service.main --host 127.0.0.1 --port 8000 --mode chain
```

Launch Kit with the 6.2 extension folder:

```bash
export ISAAC_SIM_ROOT="$HOME/isaacsim"
export ISAAC_VERSION=6.2
export ISAAC_RUNTIME_PROFILE=isaacsim-6.2
./launch_isaac.sh --version 6.2
```

`--version 6.2` selects `exts/isaac_6.2`. `~/isaacsim` is one of the 6.2
candidates and is not preferred over an existing 6.0 install unless the
version is requested. Whether `~/isaacsim/isaac-sim.sh` exists on this machine
is UNVERIFIED.

## Environment

| Variable | Default | Role |
|---|---|---|
| `LLM_MODE` | `local` | Set to `chain` for the phase-1 fallback chain |
| `ISAAC_ASSIST_PROVIDER_ORDER` | `legion-ollama,nvidia,offline` | Ordered fallback |
| `OLLAMA_OPENAI_BASE` | `http://127.0.0.1:11434/v1` for the legion provider | OpenAI-compatible Ollama |
| `LOCAL_MODEL_NAME` | existing service default | Legion model. Use `codey-builder-64k`. It must accept tool calls |
| `NVIDIA_MODEL` | empty | Model id for `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_API_KEY_FILE` | `~/.config/bufrai/nvidia-api.env` | File containing `NVIDIA_API_KEY=...` |
| `ISAAC_RUNTIME_PROFILE` | unset | `isaacsim-6.2` selects the 6.2 lane |
| `ISAAC_ASSIST_PROVIDER_PROBE_TIMEOUT` | `0.5` | Seconds for a `/models` probe |
| `ISAAC_ASSIST_PROVIDER_CHAT_TIMEOUT` | `180` | Seconds for a chat completion. Cap is 300. A cold `codey-builder-64k` load on Legion took about two minutes and fell through to offline at the old 60s default. |

The NVIDIA provider reads the key only from that file. It does not read
`NVIDIA_API_KEY` from the environment. The file must be mode `0600`, must not
be a symlink, and must be a regular file. Any other mode disables the
provider. Logs say `key present: yes` or `key present: no` and never the key.

`GET /api/v1/providers/status` returns `name`, `enabled`, `reachable`, and
`model` for each provider. It does not return key material.

## Sticky notes

A note is `{id, created_at, prim_path, prim_type, key_attributes, world_transform, region, crop_path, comment, status, proposal}`.

`status` is `draft`, `sent`, `proposed`, `confirmed`, `applied`, or `rejected`.

`world_transform` is either a 4x4 `matrix` or `translate` / `rotate` / `scale`.
`region` is an optional viewport rect `{x, y, width, height}`.

Persistence is a sidecar next to a local stage: `/path/scene.usd` is stored
as `/path/scene.usd.notes.json`. URL stages are rejected. Writing `customData`
on the prim is not implemented.

| Call | Effect |
|---|---|
| `POST /api/v1/notes` | Create a draft. Does not edit the stage |
| `GET /api/v1/notes?stage_path=` | List notes |
| `DELETE /api/v1/notes?stage_path=&id=` | Delete one note |
| `POST /api/v1/notes/send` | Body `{stage_path, ids}`. One proposal per note, status `proposed`. Does not edit |
| `POST /api/v1/notes/{id}/confirm?stage_path=` | Forwards an executable proposal over Kit RPC `/exec_sync`. Status becomes `applied` only after the open stage changes. No Kit, or a Kit call that does not change the stage, leaves status `confirmed`. Offline proposals become `confirmed` and are not applied |
| `POST /api/v1/notes/{id}/reject?stage_path=` | Status `rejected`. Does not apply |

The 6.2 chat window mounts a Sticky Note toggle, selection and region
buttons, a comment field, a note list with status, a `PIN <prim_path>` marker,
Send, and per-note Confirm / Reject. The panel calls the service.

Confirm does not edit USD inside the service process. The service posts a
short script to the extension's existing Kit RPC `/exec_sync` endpoint. That
script calls `apply_plan_on_open_stage`, which runs `pxr` on the open stage
inside one `omni.kit.undo` group. Supported ops are `set_transform`,
`set_attribute`, and `add_prim`. `set_transform` reads `scale`, `translate`,
`rotate`, or a 4x4 `matrix` from the plan or its `payload`.

When Kit is not connected, confirm leaves the note `confirmed` and the
response detail says the stage was not edited.

Headless proof, with Isaac's Python so `pxr` imports:

```bash
~/isaacsim/python.sh scripts/bufrai_apply_note.py --stage /path/scene.usda
~/isaacsim/python.sh scripts/bufrai_apply_note.py --stage /path/scene.usd --note-id <id>
```

The script applies one `confirmed` executable note, saves the file, and only
then sets the sidecar status to `applied`. A `proposed` note is refused.

## 6.0 to 6.2 API notes

The 6.2 profile keeps the 6.0 API lane:

- Python 3.12 on Isaac Sim 6.x (target VERSION `6.2.0`).
- New ROS2 OmniGraph node types stay under `isaacsim.ros2.nodes.*`.
- `isaacsim.ros2.bridge.*` node type strings are a version mismatch for both 6.0 and 6.2.
- Templates tagged `isaacsim-6.0` or `6.0.0` match the 6.2 profile because the API lane is 6.0. A 6.2 tag does not match the 6.0 profile.
- Knowledge files still point at the 6.0 jsonl corpora.

The copied articulation graph still emits `isaacsim.ros2.bridge.*` node types.
That is the 6.0 extension's graph, not a verified 6.2 graph.

No other 6.0-to-6.2 symbol rename was verified here.

## Legion smoke checklist

Run these on the Legion box. This cloud build did not run them.

1. Chat turn that reads the stage (`LLM_MODE=chain`, legion-ollama up, `LOCAL_MODEL_NAME=codey-builder-64k`).
2. One confirmed scene edit that is visible on the open stage. If the Kit RPC bridge on port 8001 is down, confirm stays `confirmed`; run `scripts/bufrai_apply_note.py` with `~/isaacsim/python.sh` and check the `.usd` or `.usda` file.
3. One sticky-note round trip: pick a prim, comment, send, receive a proposal, confirm, see status `applied` only after the stage changes, and see the note still present in `<stage>.notes.json`. Set `ISAAC_ASSIST_PROVIDER_CHAT_TIMEOUT=180` (the default) so a cold model load does not fall through to offline.

## UNVERIFIED

- Isaac Sim 6.2 actually loads `exts/isaac_6.2/omni.isaac.assist` (Kit dependency versions, extension enable).
- The Python inside `~/isaacsim` is 3.12 and can import this extension.
- The Kit SDK version that ships with Isaac Sim 6.2.
- Any 6.2-only USD, PhysX, or Kit rename beyond the 6.0 lane.
- Whether `isaacsim.ros2.bridge.*` shims in the copied articulation graph still resolve on 6.2.
- A dedicated 6.2 knowledge corpus. The profile reuses the 6.0 files.
- `codey-builder-64k` is installed in Legion Ollama and accepts tool calls.
- The NVIDIA integrate endpoint accepts `NVIDIA_MODEL` with the file-based key.
- `GET /api/v1/providers/status` against a live Ollama and a live NVIDIA host.
- Sticky Note viewport overlay placement, drag-drawn regions, and `omni.usd` selection inside a real Kit viewport.
- Reading a prim's real world matrix from UsdGeom. The panel stores a transform only when the prim snapshot provides one.
- Sidecar writes next to a Nucleus URL or a read-only stage. Only absolute local paths are accepted.
- A live Isaac 6.2 GUI undo of a sticky-note edit (the apply path uses `omni.kit.undo.begin_group` / `end_group` on the Kit main thread; this cloud build cannot open a stage).
- The headless script against a real `~/isaacsim/python.sh` and a real `.usda` file.
- `customData` on the prim (optional, not in this frame).
- MCP servers and the Kit tool bank (deferred by OD).
