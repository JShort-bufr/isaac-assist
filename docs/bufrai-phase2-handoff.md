# Handoff — Sticky Note phase 2, local Legion pickup

Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0). See `LICENSE` and `NOTICE`.

Pick up on the Legion box. The cloud session cannot run Isaac Sim.

| | |
|---|---|
| Branch | `bufrai/phase2-sticky-notes` |
| Draft PR | https://github.com/JShort-bufr/isaac-assist/pull/2 |
| Base | `bufrai/phase1-isaac-6.2` (stacked on draft PR #1) |
| Head | `a3f054990b2ac72d19a2d76814938436bd9abb9d` |
| Design doc | `docs/bufrai-phase2.md` |

Leave the pull request a draft. Do not merge it, do not mark it ready, and do not add GitHub workflows.

## Pull

```bash
cd ~/isaac-assist
git fetch origin bufrai/phase2-sticky-notes
git checkout bufrai/phase2-sticky-notes
git pull origin bufrai/phase2-sticky-notes
git rev-parse HEAD   # a3f054990b2ac72d19a2d76814938436bd9abb9d
```

Restart the assist service from this checkout, and launch Kit with this extension tree so both sides are `a3f0549`:

```bash
python -m service.isaac_assist_service.main --host 127.0.0.1 --port 8000 --mode chain
```

```bash
export ISAAC_SIM_ROOT="$HOME/isaacsim"
export ISAAC_VERSION=6.2
./launch_isaac.sh --version 6.2
```

The full create / confirm / undo recipe is in `docs/bufrai-phase2.md`.

## Already proven on Legion

Smoke of `4230d53`:

- `set_attribute` scalar `4` on `xformOp:scale` cast to `Gf.Vec3d` and the stage became `[4, 4, 4]`.
- A failed command rolled the undo group back and the stage returned to the previous value exactly.
- `set_transform` scalar `3` to `[3, 3, 3]` still worked.

That same smoke failed to report the outcome. Kit RPC `/exec_sync` died in `json.dumps` with `Object of type Vec3d is not JSON serializable` on a successful apply (note stayed `confirmed` instead of `applied`) and `Object of type Vec2f is not JSON serializable` on a failed partial command (note stayed `confirmed` instead of `rejected`). The real Kit error under the Vec2f failure was `expected GfVec2f, got vector<VtValue>`.

## What `a3f0549` changes, and what to re-check

`apply_plan_on_open_stage` now converts every `Gf` / `Vt` value in the result to plain JSON before it is printed. Vectors are lists of floats, quaternions are `[w, x, y, z]`, matrices are nested row-major lists, and `Vt` arrays are lists. The cast also covers `Vec2d` / `Vec2f` / `Vec2h` and `Vec4d` / `Vec4f` / `Vec4h`. Typed values stay inside the Kit command call.

On Legion, with head `a3f0549` loaded in both the service and Kit:

1. Confirm a scalar `xformOp:scale` of `4`. The stage is `[4, 4, 4]`, `/exec_sync` returns JSON (no `Vec3d` dump error), and the note status is `applied`. The sidecar `before` value is a list of floats.
2. Force a `Vec2f` (or other) command failure, such as a list sent where the attribute type is `Gf.Vec2f` if the cast is bypassed, or any command Kit rejects. The stage is unchanged, `/exec_sync` returns JSON, and the note status is `rejected` with the Kit error text in `error`.
3. Confirm `set_transform` scale `3` still becomes `[3, 3, 3]` and can be undone with `POST /api/v1/notes/{id}/undo`.

GUI checks that this cloud session never ran: drag-rectangle crop PNG, marker pins that follow a moved prim, Confirm all, and an `omniverse://` stage that refuses confirm until a writable session layer is selected.

## Tests already green in the cloud session

```bash
python3 -m pytest -q \
  tests/test_bufrai_phase1_apply.py \
  tests/test_bufrai_phase1_isaac62.py \
  tests/test_bufrai_phase1_notes.py \
  tests/test_bufrai_phase1_providers.py \
  tests/test_bufrai_phase2_apply.py \
  tests/test_bufrai_phase2_notes.py \
  tests/test_bufrai_phase2_patches.py \
  tests/test_bufrai_phase2_ui.py
```

That run was **51 passed** (32 phase 1, 19 phase 2). Adding `tests/test_routes.py` made **63 passed**.

Five motion-controller wire tests in the chat orchestrator fail the same way on `bufrai/phase1-isaac-6.2`. Leave them. Do not count them against this branch.

Do not touch Isaac's bundled numpy or OpenBLAS. The NVIDIA key is only read from `~/.config/bufrai/nvidia-api.env` (mode `0600`). Do not put it in the repo, logs, or the pull request.

## Files that matter for the re-smoke

- `exts/isaac_6.2/omni.isaac.assist/omni/isaac/assist/executor/note_apply.py` — Gf/Vt cast and JSON-safe result
- `service/isaac_assist_service/notes/routes.py` — `applied` vs `rejected` from the Kit outcome
- `service/isaac_assist_service/notes/kit_apply.py` — parses the `/exec_sync` marker line
- `docs/bufrai-phase2.md` — endpoints and the longer smoke recipe
