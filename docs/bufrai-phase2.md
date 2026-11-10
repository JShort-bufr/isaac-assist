# Bufrai phase 2 — Sticky Note mode

Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0). See `LICENSE` and `NOTICE`.
This continues `docs/bufrai-phase1.md` for Isaac Sim 6.2 (`exts/isaac_6.2/omni.isaac.assist`).

The cloud build cannot run Isaac Sim. Viewport drawing, Nucleus, and live Kit undo
are covered by mocks here and marked for a Legion GUI check below.

## What confirm will and will not do

Confirm is an explicit click. Send only stores a proposal. A note becomes
`applied` only after Kit reports that the open stage changed.

Before that call, the proposal is checked against known USD types:

- `xformOp:scale` and `set_transform` `scale` accept a scalar and store it as `[s, s, s]`.
- Any other known attribute must already match its type (`double3`, `double`, `matrix4d`, `quatd`, `token`, `bool`).
- A mismatch is not sent to Kit. The note status becomes `rejected` and `error` explains the type. A later headless apply only accepts `confirmed` notes, so the bad op cannot land.

`omni.kit.commands` performs the live edit (`TransformPrimSRT`, `ChangeProperty`, `CreatePrim`, `CreateDefaultXformOnPrim`) inside one `omni.kit.undo` group, with `usd_context_name`. Values passed to those commands are cast from the attribute `typeName` to `Gf` (`Vec2d` / `Vec2f` / `Vec2h`, `Vec3d` / `Vec3f` / `Vec3h`, `Vec4d` / `Vec4f` / `Vec4h`, `Quatd` / `Quatf`, `Matrix4d`, float, int, bool) or `Vt` arrays. A scalar scale is a uniform `Gf.Vec3d`. The dict printed for Kit `/exec_sync` is plain JSON: vectors are lists of floats, quaternions are `[w, x, y, z]`, matrices are nested row-major lists, and `Vt` arrays are lists. If a command in the group fails, the group is closed and rolled back, and the note becomes `rejected` with that error. `POST /api/v1/notes/{id}/undo` calls `omni.kit.undo.undo()` for the last applied note and sets status `reverted`. If Kit is down, the status stays `applied`.

The headless script still uses raw `pxr`. It records `before` on the sidecar and `--revert` restores those values.

## Stage access

| Stage | Sidecar | customData | Confirm |
|---|---|---|---|
| Writable local file | `<stage>.notes.json` | `bufrai:stickyNotes` on the prim | Allowed |
| `omniverse://` URL | `~/.local/share/bufrai/isaac-assist/notes/<sha256>.notes.json` | Not written | Refused |
| Read-only file or `read_only=true` | Same hashed directory | Not written | Refused |
| Those, plus `session_layer` and `session_layer_writable=true` | Hashed sidecar | Not written | Allowed on that session or anonymous layer |

No Nucleus credential is read or stored. `BUFRAI_NOTES_DIR` overrides the hashed directory. The sidecar wins when it disagrees with prim customData. On load, `POST /api/v1/notes/reconcile` copies prim-only notes into the sidecar and, when the stage is writable, returns the dictionary to write back.

## HTTP

| Call | Effect |
|---|---|
| `POST /api/v1/notes` | Draft. `region` accepts `x,y,w,h` or `width,height` plus optional `viewport`. A region without `crop_path` is stored as `<stage>.notes/<id>.png`. |
| `GET /api/v1/notes?stage_path=` | List. Also reports `kind`, `edits_allowed`, `custom_data_allowed`. |
| `POST /api/v1/notes/send` | One proposal per id. Does not edit. |
| `POST /api/v1/notes/review` | Body `{stage_path, action: confirm\|reject, ids}`. Confirm with an empty `ids` list confirms every `proposed` note. Each note gets its own result. One failure does not roll back the others. |
| `POST /api/v1/notes/reconcile` | Body `{stage_path, prims}`. Sidecar wins. |
| `POST /api/v1/notes/{id}/confirm?stage_path=` | Type check, then Kit. `409` on a read-only or Nucleus stage. |
| `POST /api/v1/notes/{id}/reject?stage_path=` | Status `rejected`. |
| `POST /api/v1/notes/{id}/undo?stage_path=` | Last applied note only. Kit undo, then `reverted`. Kit absent leaves `applied`. |

Optional query or body fields: `read_only`, `session_layer`, `session_layer_writable`. Pass the same stage flags on every call for that stage so the sidecar path stays stable.

## Panel

Sticky Note mode in the 6.2 chat window:

1. Drag a rectangle. The extension stores `{x, y, w, h, viewport}` and writes the cropped viewport PNG to the note's `crop_path`. Prims whose screen bounds hit the rect are selected. If none hit, the single current selection is used.
2. Markers are anchored to each note's world translation (USD matrix row 3, or `translate`) and recolored by status: proposed, confirmed, applied, rejected, reverted. The Markers toggle hides them. A prim xform change updates the anchor.
3. The list shows each proposal summary. Confirm all, Confirm, and Reject are clicks. The row shows that note's result. Undo appears on the last applied note's row after it is applied.

## Legion smoke

Service, from the repo, with the chain and a long enough chat timeout:

```bash
cd ~/isaac-assist
python -m service.isaac_assist_service.main --host 127.0.0.1 --port 8000 --mode chain
```

`ISAAC_ASSIST_PROVIDER_CHAT_TIMEOUT` defaults to 180 and caps at 300. A cold `codey-builder-64k` load can take about two minutes. The NVIDIA provider is optional and reads only `~/.config/bufrai/nvidia-api.env` (mode `0600`).

Headless Isaac plus the Kit bridge on `127.0.0.1:8001`:

```bash
export ISAAC_SIM_ROOT="$HOME/isaacsim"
export ISAAC_VERSION=6.2
./launch_isaac.sh --version 6.2
```

Create, propose, confirm, read the scale back, undo, and read it again. Replace `STAGE` and the prim. This assumes `/World/Cube` already has a scale of 1.

```bash
STAGE=/path/scene.usd
NOTE=$(curl -s -X POST http://127.0.0.1:8000/api/v1/notes \
  -H 'Content-Type: application/json' \
  -d "{\"stage_path\":\"$STAGE\",\"prim_path\":\"/World/Cube\",\"prim_type\":\"Cube\",\"comment\":\"scale the cube by 2\"}" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["note"]["id"])')
curl -s -X POST http://127.0.0.1:8000/api/v1/notes/send \
  -H 'Content-Type: application/json' \
  -d "{\"stage_path\":\"$STAGE\",\"ids\":[\"$NOTE\"]}"
curl -s -X POST "http://127.0.0.1:8000/api/v1/notes/$NOTE/confirm?stage_path=$STAGE"
```

Verify on the open stage with Kit `/exec_sync` (the extension's existing RPC, port 8001). The scale should be `(2, 2, 2)` and the note status `applied`:

```bash
curl -s -X POST http://127.0.0.1:8001/exec_sync \
  -H 'Content-Type: application/json' \
  -d '{"code":"prim=omni.usd.get_context().get_stage().GetPrimAtPath(\"/World/Cube\")\nprint(prim.GetAttribute(\"xformOp:scale\").Get())","timeout":30}'
curl -s "http://127.0.0.1:8000/api/v1/notes?stage_path=$STAGE"
```

Undo that note and verify the scale returned to the previous value. Status becomes `reverted`. A second undo is refused once this note is no longer the last applied note.

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/notes/$NOTE/undo?stage_path=$STAGE"
curl -s -X POST http://127.0.0.1:8001/exec_sync \
  -H 'Content-Type: application/json' \
  -d '{"code":"prim=omni.usd.get_context().get_stage().GetPrimAtPath(\"/World/Cube\")\nprint(prim.GetAttribute(\"xformOp:scale\").Get())","timeout":30}'
```

Headless file path, when the Kit bridge is down. Confirm leaves the note `confirmed`. Then:

```bash
~/isaacsim/python.sh scripts/bufrai_apply_note.py --stage "$STAGE" --note-id "$NOTE"
~/isaacsim/python.sh scripts/bufrai_apply_note.py --stage "$STAGE" --note-id "$NOTE" --revert
```

The first command writes `before` into the sidecar and sets `applied`. The second restores those values and sets `reverted`.

### GUI checks (not run in this cloud build)

1. Drag a rectangle around a prim. A PNG appears at `<stage>.notes/<id>.png`, and the note's region includes the viewport size. A drag that hits nothing keeps the single selected prim.
2. Turn markers on. Move the prim. The pin stays on the prim and the color matches status after confirm, reject, and undo.
3. Propose two notes and click Confirm all. Each row shows its own result. A type-mismatched proposal is rejected with the error text and does not change the stage.
4. Open an `omniverse://` stage. Confirm without a writable session layer is refused and no customData is written. Repeat with the session layer selected and `session_layer_writable=true` and the edit lands on that layer.
5. In chat, a turn that emits the same code patch more than once (whitespace ignored) shows one `code_patch` in `actions_to_approve`.

## UNVERIFIED on Legion

- Drag capture through `omni.kit.viewport.utility` and the cropped PNG's pixels.
- `omni.ui.scene` marker drawing inside the live viewport.
- `TransformPrimSRT` / `ChangeProperty` / `CreatePrim` / `CreateDefaultXformOnPrim` argument names on the Isaac Sim 6.2 Kit build. The mocks assert those command names and `usd_context_name`.
- `omni.kit.undo.undo()` after a confirmed note on a real stage. The 9cbd028 smoke showed that raw `pxr` `Set()` inside `begin_group` / `end_group` did not revert.
- Nucleus read-only detection from the root layer identifier, and session-layer edit targets.
- A scalar `xformOp:scale` from `nvidia/nemotron-3.5-lightning-30b-a3b` normalized to a double3 on a live stage.
